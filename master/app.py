import http.server, json, urllib.request, urllib.error
import subprocess, sqlite3, time, random, string
import os, re, threading, hmac, hashlib, logging
from urllib.parse import urlparse, urlsplit
from ipaddress import ip_address

ENV = {}
if os.path.exists('/opt/emby_panel/.env'):
    with open('/opt/emby_panel/.env', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                k, v = line.split('=', 1)
                ENV[k.strip()] = v.strip().strip('"\'')

PANEL_PASSWORD = ENV.get('PANEL_PASSWORD', 'admin')
CF_API_TOKEN = ENV.get('CF_API_TOKEN', '')
CF_ZONE_ID = ENV.get('CF_ZONE_ID', '')
BASE_DOMAIN = ENV.get('BASE_DOMAIN', 'axifd.asia')

DB_FILE = "/opt/emby_panel/db/panel.db"
MAX_BODY = 1024 * 1024
HEARTBEAT_INTERVAL = 60
HEALTH_SKEW = 120
HEALTH_NONCE = os.environ.get('EMBY_HEALTH_NONCE', '')
login_failures = {}
login_lock = threading.Lock()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('emby-panel')

def db_connect():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def valid_subdomain(value):
    return bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', value or ''))

def valid_target(value):
    try:
        p = urlsplit(value if '://' in value else 'https://' + value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password: return False
        try:
            ip = ip_address(p.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: return False
        except ValueError: pass
        return len(value) <= 2048 and '\n' not in value and '\r' not in value
    except Exception: return False

def init_db():
    with db_connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, expire_time REAL)')
        conn.execute('CREATE TABLE IF NOT EXISTS auth_codes (code TEXT PRIMARY KEY, duration INTEGER, is_used INTEGER, bound_user TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS routes (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, subdomain TEXT, target TEXT, node_id INTEGER)')
        conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, host TEXT, port TEXT, secret_key TEXT, is_online INTEGER DEFAULT 1)')
        conn.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT, role TEXT, expire_time REAL)')
        
        try: conn.execute('ALTER TABLE users ADD COLUMN password_hash TEXT')
        except: pass
        try: conn.execute('ALTER TABLE users ADD COLUMN route_limit INTEGER DEFAULT 3')
        except: pass
        conn.execute('UPDATE users SET route_limit=3 WHERE route_limit IS NULL OR route_limit < 0')
        try: conn.execute('ALTER TABLE nodes ADD COLUMN is_online INTEGER DEFAULT 1')
        except: pass
        
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_routes_subdomain ON routes(subdomain)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_routes_username ON routes(username)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_expire ON sessions(expire_time)')
        conn.execute('CREATE TABLE IF NOT EXISTS operation_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, route_id INTEGER, status TEXT, detail TEXT, created_at REAL)')
        conn.execute('DELETE FROM sessions WHERE expire_time < ?', (time.time(),))
init_db()

def hash_pwd(pwd): return hashlib.pbkdf2_hmac('sha256', pwd.encode('utf-8'), b'emby-panel-v1', 240000).hex() if pwd else ''
def legacy_hash_pwd(pwd): return hashlib.sha256(pwd.encode('utf-8')).hexdigest() if pwd else ''
def generate_auth_code(duration):
    return f"{''.join(random.choices(string.ascii_letters+string.digits, k=4))}_{duration}_{''.join(random.choices(string.ascii_letters+string.digits, k=8))}"

def req_with_retry(req, retries=3, timeout=8):
    for i in range(retries):
        try: return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            if i == retries - 1: raise e
            time.sleep(1.5 ** i)

def audit(action, status, detail=''):
    logger.info('action=%s status=%s detail=%s', action, status, detail[:500])
    try:
        with db_connect() as conn:
            conn.execute('INSERT INTO operation_logs(action,route_id,status,detail,created_at) VALUES(?,?,?,?,?)', (action, None, status, detail[:1000], time.time()))
    except Exception as e:
        logger.warning('audit-db-failed: %s', e)

def call_remote_node(host, port, secret, action, sub, target):
    ts = int(time.time())
    msg = f"{ts}:{action}:{sub}:{target}".encode('utf-8')
    sign = hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()
    payload = {"action": action, "subdomain": sub, "target": target, "base_domain": BASE_DOMAIN, "t": ts, "sign": sign}
    req = urllib.request.Request(f"http://{host}:{port}/api/sync", data=json.dumps(payload).encode('utf-8'), method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        return req_with_retry(req)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise Exception(f"节点 {host} 通信失败: HTTP {e.code}: {body[:300]}")
    except Exception as e: raise Exception(f"节点 {host} 通信失败: {str(e)}")

def cf_set(subdomain, target_host):
    full_domain = f"{subdomain}.{BASE_DOMAIN}"
    headers = {'Authorization': f'Bearer {CF_API_TOKEN}', 'Content-Type': 'application/json'}
    search = urllib.request.Request(f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?name={full_domain}", headers=headers)
    result = json.loads(req_with_retry(search).read().decode('utf-8'))
    if not result.get('success'): raise Exception(f"CF 查询失败: {result}")
    record_type = "A" if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target_host) else "CNAME"
    payload = json.dumps({'type': record_type, 'name': full_domain, 'content': target_host, 'proxied': False}).encode('utf-8')
    if result.get('result'):
        url = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{result['result'][0]['id']}"
        req = urllib.request.Request(url, data=payload, method='PUT', headers=headers)
    else:
        url = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records"
        req = urllib.request.Request(url, data=payload, method='POST', headers=headers)
    response = json.loads(req_with_retry(req).read().decode('utf-8'))
    if not response.get('success'): raise Exception(f"CF 更新失败: {response}")

def cf_api(action, subdomain, target_host=""):
    full_domain = f"{subdomain}.{BASE_DOMAIN}"
    if action == 'add':
        api_url = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records"
        record_type = "A" if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target_host) else "CNAME"
        payload = {"type": record_type, "name": full_domain, "content": target_host, "proxied": False}
        req = urllib.request.Request(api_url, data=json.dumps(payload).encode('utf-8'), method='POST')
    else:
        search_req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?name={full_domain}", method='GET')
        search_req.add_header('Authorization', f'Bearer {CF_API_TOKEN}')
        search_req.add_header('Content-Type', 'application/json')
        resp = req_with_retry(search_req)
        res_data = json.loads(resp.read().decode('utf-8'))
        if not res_data.get('success') or len(res_data['result']) == 0: return
        req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{res_data['result'][0]['id']}", method='DELETE')
    
    req.add_header('Authorization', f'Bearer {CF_API_TOKEN}')
    req.add_header('Content-Type', 'application/json')
    try: req_with_retry(req)
    except urllib.error.HTTPError as e:
        if action == 'add' and "already exists" not in e.read().decode('utf-8'): raise Exception(f"CF 解析拒绝，详细原因: {e.read().decode('utf-8')}")

def heartbeat_worker():
    fails = {}
    while True:
        time.sleep(60)
        with db_connect() as conn: nodes = conn.execute('SELECT id, host, port, secret_key FROM nodes').fetchall()
        active_ids = {n[0] for n in nodes}
        for old_id in list(fails):
            if old_id not in active_ids: fails.pop(old_id, None)
        for nid, host, port, secret_key in nodes:
            try:
                req = urllib.request.Request(f"http://{host}:{port}/api/health")
                ts = str(int(time.time()))
                req.add_header('X-Emby-Timestamp', ts)
                req.add_header('X-Emby-Signature', hmac.new(secret_key.encode(), ts.encode(), hashlib.sha256).hexdigest())
                req_with_retry(req, retries=1, timeout=5)
                fails[nid] = 0
                with db_connect() as conn:
                    conn.execute('UPDATE nodes SET is_online=1 WHERE id=?', (nid,)); conn.commit()
            except Exception as e:
                fails[nid] = fails.get(nid, 0) + 1
                logger.warning('node-health-failed id=%s host=%s failures=%s error=%s', nid, host, fails[nid], e)
                if fails[nid] >= 3:
                    with db_connect() as conn:
                        conn.execute('UPDATE nodes SET is_online=0 WHERE id=?', (nid,)); conn.commit()
threading.Thread(target=heartbeat_worker, daemon=True).start()

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def send_resp(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def get_user(self):
        token = self.headers.get('Authorization', '')
        if not token: return None
        now = time.time()
        with db_connect() as conn:
            sess = conn.execute('SELECT username, role FROM sessions WHERE token=? AND expire_time>?', (token, now)).fetchone()
            if sess:
                user, role = sess[0], sess[1]
                if role == 'user':
                    exp = conn.execute('SELECT expire_time FROM users WHERE username=?', (user,)).fetchone()
                    if not exp or exp[0] < now: return None
                return {'username': user, 'role': role}
        return None

    def do_POST(self):
        origin = self.headers.get('Origin')
        host = self.headers.get('Host', '').split(':', 1)[0]
        if origin:
            try:
                if urlsplit(origin).hostname != host: return self.send_resp(403, {'msg': 'Origin rejected'})
            except Exception: return self.send_resp(403, {'msg': 'Origin rejected'})
        try: len_ = int(self.headers.get('Content-Length', 0))
        except ValueError: return self.send_resp(400, {'msg': 'Invalid content length'})
        if len_ > MAX_BODY: return self.send_resp(413, {'msg': 'Request too large'})
        if len_ == 0: return self.send_resp(400, {'msg': 'No data'})
        try: data = json.loads(self.rfile.read(len_).decode('utf-8'))
        except (ValueError, UnicodeDecodeError): return self.send_resp(400, {'msg': 'Invalid JSON'})
        
        if self.path == '/login':
            user, pwd, code = data.get('username', '').strip(), data.get('password', '').strip(), data.get('code', '').strip()
            if not user: return self.send_resp(400, {'msg': '用户名不能为空'})
            client_ip = self.client_address[0]
            with login_lock:
                failures, blocked_until = login_failures.get(client_ip, (0, 0))
                if blocked_until > time.time(): return self.send_resp(429, {'msg': '登录尝试过于频繁，请稍后再试'})
            
            now = time.time()
            with db_connect() as conn:
                if user == 'admin' and pwd == PANEL_PASSWORD:
                    token = os.urandom(16).hex()
                    conn.execute('INSERT INTO sessions (token, username, role, expire_time) VALUES (?, ?, ?, ?)', (token, 'admin', 'admin', now + 604800))
                    conn.commit()
                    audit('login', 'success', 'admin')
                    return self.send_resp(200, {'token': token, 'role': 'admin'})
                
                if code: 
                    code_rec = conn.execute('SELECT duration, is_used FROM auth_codes WHERE code=?', (code,)).fetchone()
                    if not code_rec: return self.send_resp(403, {'msg': '授权码无效'})
                    if code_rec[1] == 1: return self.send_resp(403, {'msg': '授权码已被使用'})
                    if not pwd: return self.send_resp(400, {'msg': '激活时请设置自定义密码'})
                    
                    user_exist = conn.execute('SELECT username FROM users WHERE username=?', (user,)).fetchone()
                    if user_exist: return self.send_resp(403, {'msg': '用户名已存在，请直接密码登录'})
                    
                    conn.execute('INSERT INTO users (username, password_hash, expire_time) VALUES (?, ?, ?)', (user, hash_pwd(pwd), now + (code_rec[0] * 86400)))
                    conn.execute('UPDATE auth_codes SET is_used=1, bound_user=? WHERE code=?', (user, code))
                else: 
                    db_user = conn.execute('SELECT password_hash, expire_time FROM users WHERE username=?', (user,)).fetchone()
                    if not db_user: return self.send_resp(404, {'msg': '账户不存在，需输入授权码注册'})
                    if db_user[0] not in (hash_pwd(pwd), legacy_hash_pwd(pwd)):
                        with login_lock:
                            failures, _ = login_failures.get(client_ip, (0, 0)); failures += 1
                            login_failures[client_ip] = (failures, time.time() + 900 if failures >= 5 else 0)
                        return self.send_resp(403, {'msg': '密码错误'})
                    if db_user[0] == legacy_hash_pwd(pwd): conn.execute('UPDATE users SET password_hash=? WHERE username=?', (hash_pwd(pwd), user))
                    if db_user[1] < now: return self.send_resp(403, {'msg': '账户已过期'})

                token = os.urandom(16).hex()
                conn.execute('INSERT INTO sessions (token, username, role, expire_time) VALUES (?, ?, ?, ?)', (token, user, 'user', now + 604800))
                conn.commit()
            audit('login', 'success', user)
            return self.send_resp(200, {'token': token, 'role': 'user'})

        session = self.get_user()
        if not session: return self.send_resp(401, {'msg': '会话已过期，请重新登录'})
        username, is_admin = session['username'], session['role'] == 'admin'

        if self.path == '/user/add_route':
            sub, target, node_id = data.get('subdomain', '').strip().lower(), data.get('target', '').strip(), data.get('node_id')
            if not valid_subdomain(sub): return self.send_resp(400, {'msg': 'Invalid subdomain'})
            if not valid_target(target): return self.send_resp(400, {'msg': 'Invalid target URL'})
            if not sub or not target or not node_id: return self.send_resp(400, {'msg': '参数缺失'})
            with db_connect() as conn:
                if not is_admin:
                    route_count = conn.execute('SELECT COUNT(*) FROM routes WHERE username=?', (username,)).fetchone()[0]
                    limit_row = conn.execute('SELECT route_limit FROM users WHERE username=?', (username,)).fetchone()
                    route_limit = limit_row[0] if limit_row else 3
                    if route_count >= route_limit: return self.send_resp(403, {'msg': f'额度已满({route_limit}条)'})
                if conn.execute('SELECT id FROM routes WHERE subdomain=?', (sub,)).fetchone(): return self.send_resp(403, {'msg': '子域名已被占用'})
                node = conn.execute('SELECT host, port, secret_key, is_online FROM nodes WHERE id=?', (node_id,)).fetchone()
                if not node: return self.send_resp(404, {'msg': '节点不存在'})
                if node[3] == 0: return self.send_resp(403, {'msg': '节点离线，禁止部署'})
                
                try:
                    cf_api('add', sub, node[0])
                    call_remote_node(node[0], node[1], node[2], 'add', sub, target)
                    conn.execute('INSERT INTO routes (username, subdomain, target, node_id) VALUES (?, ?, ?, ?)', (username, sub, target, node_id))
                    conn.commit()
                except Exception as e:
                    try: cf_api('delete', sub)
                    except: pass
                    return self.send_resp(500, {'msg': str(e)})
            return self.send_resp(200, {'msg': '部署成功'})

        elif self.path in ('/user/update_route', '/admin/update_route'): 
            route_id, new_node_id, new_target = data.get('id'), data.get('node_id'), data.get('target', '').strip()
            with db_connect() as conn:
                q = 'SELECT r.subdomain, r.target, r.node_id, n.host, n.port, n.secret_key FROM routes r JOIN nodes n ON r.node_id=n.id WHERE r.id=?'
                route = conn.execute(q + (' AND r.username=?' if not is_admin else ''), (route_id, username) if not is_admin else (route_id,)).fetchone()
                if not route: return self.send_resp(403, {'msg': '越权或路由不存在'})
                
                sub, old_target, old_node_id, old_host, old_port, old_key = route
                target_to_use = new_target if new_target else old_target
                node_to_use = new_node_id if new_node_id else old_node_id

                if target_to_use == old_target and str(node_to_use) == str(old_node_id): return self.send_resp(200, {'msg': '未做任何修改'})

                new_n = conn.execute('SELECT host, port, secret_key, is_online FROM nodes WHERE id=?', (node_to_use,)).fetchone()
                if not new_n: return self.send_resp(404, {'msg': '新节点不存在'})
                if new_n[3] == 0: return self.send_resp(403, {'msg': '目标节点已离线'})

                new_applied = False
                try:
                    # 先让新节点准备好路由；旧节点仍可继续服务，避免切换窗口中断。
                    call_remote_node(new_n[0], new_n[1], new_n[2], 'add', sub, target_to_use)
                    new_applied = True
                    if old_host != new_n[0]:
                        cf_set(sub, new_n[0])
                    conn.execute('UPDATE routes SET target=?, node_id=? WHERE id=?', (target_to_use, node_to_use, route_id))
                    conn.commit()
                    audit('route_update', 'success', f'{sub}:{old_node_id}->{node_to_use}')
                    # 旧节点清理失败不影响已经完成的新线路，兼容旧 Worker。
                    try: call_remote_node(old_host, old_port, old_key, 'delete', sub, '')
                    except Exception as cleanup_error: logger.warning('old-node-cleanup-failed sub=%s error=%s', sub, cleanup_error)
                except Exception as e:
                    if new_applied:
                        try: call_remote_node(new_n[0], new_n[1], new_n[2], 'delete', sub, '')
                        except Exception: pass
                    return self.send_resp(500, {'msg': f'切换中断: {e}'})
            return self.send_resp(200, {'msg': '线路已热切换成功'})

        elif self.path in ('/user/delete_route', '/admin/delete_route'):
            route_id = data.get('id')
            with db_connect() as conn:
                q = 'SELECT r.subdomain, n.host, n.port, n.secret_key FROM routes r JOIN nodes n ON r.node_id = n.id WHERE r.id=?'
                route = conn.execute(q + (' AND r.username=?' if not is_admin else ''), (route_id, username) if not is_admin else (route_id,)).fetchone()
                if route:
                    try:
                        cf_api('delete', route[0])
                        conn.execute('DELETE FROM routes WHERE id=?', (route_id,)); conn.commit()
                        
                        try: call_remote_node(route[1], route[2], route[3], 'delete', route[0], '')
                        except: pass
                    except Exception as e: return self.send_resp(500, {'msg': str(e)})
            return self.send_resp(200, {'msg': '已销毁'})

        if not is_admin: return self.send_resp(403, {'msg': 'Forbidden'})

        if self.path == '/admin/generate':
            code = generate_auth_code(int(data.get('duration', 30)))
            with db_connect() as conn: conn.execute('INSERT INTO auth_codes (code, duration, is_used, bound_user) VALUES (?, ?, 0, "")', (code, int(data.get('duration', 30)))); conn.commit()
            return self.send_resp(200, {'msg': '生成成功', 'code': code})
        elif self.path == '/admin/add_node':
            with db_connect() as conn: conn.execute('INSERT INTO nodes (name, host, port, secret_key, is_online) VALUES (?, ?, ?, ?, 0)', (data.get('name'), data.get('host'), data.get('port'), data.get('key'))); conn.commit()
            return self.send_resp(200, {'msg': '节点接入成功'})
        elif self.path == '/admin/delete_node':
            nid = data.get('id')
            with db_connect() as conn:
                if conn.execute('SELECT COUNT(*) FROM routes WHERE node_id=?', (nid,)).fetchone()[0] > 0: return self.send_resp(403, {'msg': '节点下存在线路，请先迁移用户线路'})
                conn.execute('DELETE FROM nodes WHERE id=?', (nid,)); conn.commit()
            return self.send_resp(200, {'msg': '卸载成功'})
        elif self.path == '/admin/update_user_limit':
            target_user = str(data.get('username', '')).strip()
            try: route_limit = int(data.get('route_limit'))
            except (TypeError, ValueError): return self.send_resp(400, {'msg': '线路额度必须是整数'})
            if not target_user or route_limit < 0 or route_limit > 1000: return self.send_resp(400, {'msg': '线路额度范围为 0-1000'})
            with db_connect() as conn:
                if not conn.execute('SELECT 1 FROM users WHERE username=?', (target_user,)).fetchone(): return self.send_resp(404, {'msg': '用户不存在'})
                conn.execute('UPDATE users SET route_limit=? WHERE username=?', (route_limit, target_user)); conn.commit()
            audit('update_user_limit', 'success', f'{target_user}:{route_limit}')
            return self.send_resp(200, {'msg': '用户线路额度已更新'})
        elif self.path == '/admin/update_announcement':
            # 新增接口：管理员更新系统公告
            text = data.get('text', '').strip()
            with db_connect() as conn:
                # 兼容旧版本的 sqlite，先删除旧 key，再插入新 key
                conn.execute("DELETE FROM settings WHERE key='announcement'")
                conn.execute("INSERT INTO settings (key, value) VALUES ('announcement', ?)", (text,))
                conn.commit()
            return self.send_resp(200, {'msg': '公告已发布生效'})

    def do_GET(self):
        session = self.get_user()
        if not session: return self.send_resp(401, {'msg': 'Unauthorized'})
        
        with db_connect() as conn:
            # 统一读取公告信息
            ann_row = conn.execute("SELECT value FROM settings WHERE key='announcement'").fetchone()
            ann_text = ann_row[0] if ann_row else ""

            if self.path == '/user/data' and session['role'] == 'user':
                user_row = conn.execute('SELECT expire_time, route_limit FROM users WHERE username=?', (session['username'],)).fetchone()
                exp, route_limit = user_row[0], user_row[1]
                routes = conn.execute('SELECT r.id, r.subdomain, r.target, n.name, n.port, n.host, n.id FROM routes r JOIN nodes n ON r.node_id = n.id WHERE r.username=?', (session['username'],)).fetchall()
                nodes_data = conn.execute('SELECT id, name, host, port, is_online FROM nodes').fetchall()
                
                return self.send_resp(200, {
                    'username': session['username'],
                    'expire': time.strftime("%Y-%m-%d", time.localtime(exp)),
                    'route_limit': route_limit,
                    'nodes': [{'id': n[0], 'name': n[1], 'online': n[4]} for n in nodes_data],
                    'routes': [{'id': r[0], 'subdomain': r[1], 'target': r[2], 'node_name': r[3], 'node_port': r[4], 'node_id': r[6]} for r in routes],
                    'announcement': ann_text
                })
            
            if self.path == '/admin/data' and session['role'] == 'admin':
                codes = conn.execute('SELECT code, duration, is_used, bound_user FROM auth_codes ORDER BY is_used ASC').fetchall()
                nodes_full = conn.execute('SELECT id, name, host, port, is_online FROM nodes').fetchall()
                routes = conn.execute('SELECT r.id, r.username, r.subdomain, r.target, n.name, n.id FROM routes r JOIN nodes n ON r.node_id = n.id').fetchall()
                users = conn.execute('SELECT u.username, u.expire_time, u.route_limit, COUNT(r.id) FROM users u LEFT JOIN routes r ON r.username=u.username GROUP BY u.username, u.expire_time, u.route_limit ORDER BY u.username').fetchall()
                return self.send_resp(200, {
                    'codes': [{'code': c[0], 'dur': c[1], 'used': c[2], 'user': c[3]} for c in codes],
                    'nodes': [{'id': n[0], 'name': n[1], 'host': n[2], 'port': n[3], 'online': n[4]} for n in nodes_full],
                    'routes': [{'id': r[0], 'user': r[1], 'subdomain': r[2], 'target': r[3], 'node_name': r[4], 'node_id': r[5]} for r in routes],
                    'users': [{'username': u[0], 'expire': time.strftime("%Y-%m-%d", time.localtime(u[1])), 'route_limit': u[2], 'route_count': u[3]} for u in users],
                    'announcement': ann_text
                })

if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 8080), RequestHandler)
    server.serve_forever()
