#!/bin/sh
set -eu

EXISTING_ENV=/opt/emby_panel/.env

read_existing_value() {
    key=$1
    [ -f "$EXISTING_ENV" ] || return 0
    awk -v wanted="$key" '
        index($0, wanted "=") == 1 {
            value = substr($0, length(wanted) + 2)
            sub(/^[[:space:]]+/, "", value)
            sub(/[[:space:]]+$/, "", value)
            if ((substr(value, 1, 1) == "\"" && substr(value, length(value), 1) == "\"") ||
                (substr(value, 1, 1) == "\047" && substr(value, length(value), 1) == "\047")) {
                value = substr(value, 2, length(value) - 2)
            }
            print value
            exit
        }
    ' "$EXISTING_ENV"
}

# Explicit environment variables take precedence. Otherwise, a reinstall or
# upgrade starts with the values already stored by the previous installation.
PANEL_PASSWORD=${PANEL_PASSWORD:-$(read_existing_value PANEL_PASSWORD)}
CF_API_TOKEN=${CF_API_TOKEN:-$(read_existing_value CF_API_TOKEN)}
CF_ZONE_ID=${CF_ZONE_ID:-$(read_existing_value CF_ZONE_ID)}
BASE_DOMAIN=${BASE_DOMAIN:-$(read_existing_value BASE_DOMAIN)}
GLOBAL_SECRET_KEY=${GLOBAL_SECRET_KEY:-$(read_existing_value GLOBAL_SECRET_KEY)}
PANEL_NAME=${PANEL_NAME:-$(read_existing_value PANEL_NAME)}
PANEL_NAME=${PANEL_NAME:-Emby Edge}
PANEL_DOMAIN=${PANEL_DOMAIN:-$(read_existing_value PANEL_DOMAIN)}

is_set() { [ -n "$1" ] && printf '已设置' || printf '未设置'; }
prompt_value() {
    label=$1
    current=$2
    printf '%s' "$label" >&2
    [ -z "$current" ] || printf ' [%s]' "$current" >&2
    printf ': ' >&2
    IFS= read -r answer
    [ -z "$answer" ] && answer=$current
    printf '%s' "$answer"
}
prompt_secret() {
    label=$1
    current=$2
    printf '%s' "$label" >&2
    [ -z "$current" ] || printf ' [直接回车保留当前值]' >&2
    printf ': ' >&2
    stty -echo 2>/dev/null || true
    IFS= read -r answer
    stty echo 2>/dev/null || true
    printf '\n' >&2
    [ -z "$answer" ] && answer=$current
    printf '%s' "$answer"
}
show_menu() {
    printf '\n=== Emby Edge 主控安装配置 ===\n'
    printf '1. 面板管理员密码: %s\n' "$(is_set "$PANEL_PASSWORD")"
    printf '2. Cloudflare API Token: %s\n' "$(is_set "$CF_API_TOKEN")"
    printf '3. Cloudflare Zone ID: %s\n' "$(is_set "$CF_ZONE_ID")"
    printf '4. 基础域名: %s\n' "${BASE_DOMAIN:-未设置}"
    printf '5. Worker 全局共享密钥: %s\n' "$(is_set "$GLOBAL_SECRET_KEY")"
    printf '6. 面板名称: %s\n' "$PANEL_NAME"
    printf '7. 面板访问域名（可选）: %s\n' "${PANEL_DOMAIN:-未设置，将使用 IP}"
    printf '8. 开始安装\n'
    printf '0. 退出\n'
}

show_missing_required() {
    missing=''
    [ -n "$PANEL_PASSWORD" ] || missing="$missing 面板管理员密码(1)"
    [ -n "$CF_API_TOKEN" ] || missing="$missing Cloudflare API Token(2)"
    [ -n "$CF_ZONE_ID" ] || missing="$missing Cloudflare Zone ID(3)"
    [ -n "$BASE_DOMAIN" ] || missing="$missing 基础域名(4)"
    [ -n "$GLOBAL_SECRET_KEY" ] || missing="$missing Worker 共享密钥(5)"
    if [ -n "$missing" ]; then
        echo "无法开始安装，以下必填项未设置:$missing"
        return 1
    fi
    return 0
}

if [ -t 0 ]; then
    while :; do
        show_menu
        printf '请选择 [0-8]: '
        IFS= read -r choice
        case "$choice" in
            1) PANEL_PASSWORD=$(prompt_secret '请输入面板管理员密码' "$PANEL_PASSWORD") ;;
            2) CF_API_TOKEN=$(prompt_secret '请输入 Cloudflare API Token' "$CF_API_TOKEN") ;;
            3) CF_ZONE_ID=$(prompt_value '请输入 Cloudflare Zone ID' "$CF_ZONE_ID") ;;
            4) BASE_DOMAIN=$(prompt_value '请输入基础域名（不含协议）' "$BASE_DOMAIN") ;;
            5) GLOBAL_SECRET_KEY=$(prompt_secret '请输入 Worker 全局共享密钥' "$GLOBAL_SECRET_KEY") ;;
            6) PANEL_NAME=$(prompt_value '请输入面板名称' "$PANEL_NAME") ;;
            7) PANEL_DOMAIN=$(prompt_value '请输入面板域名（可留空使用 IP）' "$PANEL_DOMAIN") ;;
            8) show_missing_required && break ;;
            0) exit 0 ;;
            *) echo '无效选项。' ;;
        esac
    done
else
    : "${PANEL_PASSWORD:?PANEL_PASSWORD must be set in non-interactive mode}"
    : "${CF_API_TOKEN:?CF_API_TOKEN must be set in non-interactive mode}"
    : "${CF_ZONE_ID:?CF_ZONE_ID must be set in non-interactive mode}"
    : "${BASE_DOMAIN:?BASE_DOMAIN must be set in non-interactive mode}"
    : "${GLOBAL_SECRET_KEY:?GLOBAL_SECRET_KEY must be set in non-interactive mode}"
fi

BASE_DOMAIN=$(printf '%s' "$BASE_DOMAIN" | sed 's#^[[:space:]]*https\?://##; s#/.*$##; s/^\.//; s/[[:space:]]*$//' | tr 'A-Z' 'a-z')
PANEL_DOMAIN=$(printf '%s' "$PANEL_DOMAIN" | sed 's#^[[:space:]]*https\?://##; s#/.*$##; s/^\.//; s/[[:space:]]*$//' | tr 'A-Z' 'a-z')
case "$BASE_DOMAIN" in ''|*[!a-z0-9.-]*|.*|*..*|*.) echo '基础域名格式无效。' >&2; exit 1 ;; esac
if [ -n "$PANEL_DOMAIN" ]; then
    case "$PANEL_DOMAIN" in ''|*[!a-z0-9.-]*|.*|*..*|*.) echo '面板域名格式无效。' >&2; exit 1 ;; esac
    case "$PANEL_DOMAIN" in
        "$BASE_DOMAIN") ;;
        *.$BASE_DOMAIN)
            panel_prefix=${PANEL_DOMAIN%.$BASE_DOMAIN}
            case "$panel_prefix" in *.*|'') echo '面板域名只能是基础域名或其一级子域名，例如 panel.example.com。' >&2; exit 1 ;; esac
            ;;
        *) echo '面板域名必须等于基础域名或属于基础域名，例如 panel.example.com。' >&2; exit 1 ;;
    esac
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$SCRIPT_DIR/master/app.py" ] || { echo "Missing master/app.py" >&2; exit 1; }
[ -f "$SCRIPT_DIR/master/index.html" ] || { echo "Missing master/index.html" >&2; exit 1; }

if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx python3 curl certbot python3-certbot-dns-cloudflare python3-cryptography
else
    echo "Master installer supports Debian/Ubuntu (apt)." >&2
    exit 1
fi

stamp=$(date +%Y%m%d-%H%M%S)
[ ! -d /opt/emby_panel ] || cp -a /opt/emby_panel "/opt/emby_panel.backup-$stamp"
cp -a /etc/nginx "/etc/nginx.backup-$stamp"

mkdir -p /opt/emby_panel/frontend /opt/emby_panel/db /etc/nginx/sites-available /etc/nginx/sites-enabled
install -m 0750 "$SCRIPT_DIR/master/app.py" /opt/emby_panel/app.py
install -m 0644 "$SCRIPT_DIR/master/index.html" /opt/emby_panel/frontend/index.html
touch /etc/nginx/emby_url.map /etc/nginx/emby_sni.map

cat > /opt/emby_panel/.env <<EOF
PANEL_PASSWORD="$PANEL_PASSWORD"
CF_API_TOKEN="$CF_API_TOKEN"
CF_ZONE_ID="$CF_ZONE_ID"
BASE_DOMAIN="$BASE_DOMAIN"
GLOBAL_SECRET_KEY="$GLOBAL_SECRET_KEY"
PANEL_NAME="$PANEL_NAME"
PANEL_DOMAIN="$PANEL_DOMAIN"
EOF
chmod 600 /opt/emby_panel/.env

mkdir -p /root/.secrets
cat > /root/.secrets/emby-cloudflare.ini <<EOF
dns_cloudflare_api_token=$CF_API_TOKEN
EOF
chmod 600 /root/.secrets/emby-cloudflare.ini
if [ -n "$PANEL_DOMAIN" ]; then
    certbot certonly --dns-cloudflare --dns-cloudflare-credentials /root/.secrets/emby-cloudflare.ini \
        --dns-cloudflare-propagation-seconds 30 --non-interactive --agree-tos \
        --register-unsafely-without-email --cert-name emby-edge-wildcard \
        -d "*.$BASE_DOMAIN" -d "$BASE_DOMAIN"
fi

cat > /etc/cron.daily/emby-edge-cert-renew <<'EOF'
#!/bin/sh
certbot renew --quiet --deploy-hook 'systemctl reload nginx'
EOF
chmod 700 /etc/cron.daily/emby-edge-cert-renew

cat > /etc/nginx/sites-available/emby-panel <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${PANEL_DOMAIN:-_} emby-worker-bootstrap;
    port_in_redirect off;
    server_name_in_redirect off;
    location / {
        alias /opt/emby_panel/frontend/;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_read_timeout 240s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

if [ -n "$PANEL_DOMAIN" ]; then
cat > /etc/nginx/sites-available/emby-panel-https <<EOF
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $PANEL_DOMAIN;
    ssl_certificate /etc/letsencrypt/live/emby-edge-wildcard/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/emby-edge-wildcard/privkey.pem;
    location / {
        alias /opt/emby_panel/frontend/;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_read_timeout 240s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF
else
    rm -f /etc/nginx/sites-available/emby-panel-https
fi

if [ -z "$PANEL_DOMAIN" ]; then
    sed -i 's/listen 80;/listen 80 default_server;/; s/listen \[::\]:80;/listen [::]:80 default_server;/' /etc/nginx/sites-available/emby-panel
fi

if [ -n "$PANEL_DOMAIN" ]; then
    MASTER_PUBLIC_IP=$(curl -4fsS --max-time 15 https://api.ipify.org)
    PANEL_DOMAIN="$PANEL_DOMAIN" MASTER_PUBLIC_IP="$MASTER_PUBLIC_IP" python3 - <<'PY'
import json, os, urllib.request
env = {}
for raw in open('/opt/emby_panel/.env', encoding='utf-8'):
    raw = raw.strip()
    if raw and not raw.startswith('#') and '=' in raw:
        key, value = raw.split('=', 1)
        env[key] = value.strip().strip('"\'')
name, address = os.environ['PANEL_DOMAIN'], os.environ['MASTER_PUBLIC_IP']
base = f"https://api.cloudflare.com/client/v4/zones/{env['CF_ZONE_ID']}/dns_records"
headers = {'Authorization': 'Bearer ' + env['CF_API_TOKEN'], 'Content-Type': 'application/json'}
with urllib.request.urlopen(urllib.request.Request(base + '?name=' + name, headers=headers), timeout=15) as response:
    found = json.load(response).get('result', [])
payload = json.dumps({'type': 'A', 'name': name, 'content': address, 'proxied': False}).encode()
url = base + '/' + found[0]['id'] if found else base
request = urllib.request.Request(url, data=payload, method='PUT' if found else 'POST', headers=headers)
with urllib.request.urlopen(request, timeout=15) as response:
    result = json.load(response)
if not result.get('success'):
    raise SystemExit('面板域名 DNS 配置失败: ' + json.dumps(result, ensure_ascii=False))
PY
fi

cat > /etc/systemd/system/emby-panel.service <<'EOF'
[Unit]
Description=Emby Edge Master Panel
After=network-online.target nginx.service
Wants=network-online.target
[Service]
WorkingDirectory=/opt/emby_panel
ExecStart=/usr/bin/python3 /opt/emby_panel/app.py
Restart=always
RestartSec=2
User=root
[Install]
WantedBy=multi-user.target
EOF

# Disable known legacy/default Emby site links. The full Nginx directory was
# backed up above, so these links can be restored from the timestamped backup.
rm -f \
    /etc/nginx/sites-enabled/default \
    /etc/nginx/sites-enabled/emby-panel-http \
    /etc/nginx/sites-enabled/emby-panel
ln -sfn /etc/nginx/sites-available/emby-panel /etc/nginx/sites-enabled/emby-panel
[ -f /etc/nginx/sites-available/emby-panel-https ] && ln -sfn /etc/nginx/sites-available/emby-panel-https /etc/nginx/sites-enabled/emby-panel-https || rm -f /etc/nginx/sites-enabled/emby-panel-https
if [ -z "$PANEL_DOMAIN" ] && grep -RqsE 'listen[[:space:]]+([^;[:space:]]+:)?80([^;]*[[:space:]])default_server' /etc/nginx/sites-enabled --exclude=emby-panel; then
    echo '检测到其他网站已经占用 80 端口 default_server。' >&2
    echo '请重新运行安装器并设置“面板访问域名”，避免面板与现有网站冲突。' >&2
    echo "备份: /etc/nginx.backup-$stamp" >&2
    exit 1
fi
python3 -m py_compile /opt/emby_panel/app.py
if ! nginx_output=$(nginx -t 2>&1); then
    printf '%s\n' "$nginx_output" >&2
    echo "Nginx configuration failed. Check enabled sites with:" >&2
    echo "  grep -RIn 'listen .*default_server' /etc/nginx/sites-enabled /etc/nginx/conf.d" >&2
    echo "Backup: /etc/nginx.backup-$stamp" >&2
    exit 1
fi
systemctl daemon-reload
systemctl enable --now nginx emby-panel
systemctl restart nginx emby-panel
sleep 2
curl -fsS -H "Host: ${PANEL_DOMAIN:-emby-worker-bootstrap}" http://127.0.0.1/ >/dev/null
systemctl is-active --quiet nginx
systemctl is-active --quiet emby-panel
if [ -n "$PANEL_DOMAIN" ]; then
    echo "Master installed: https://$PANEL_DOMAIN/"
else
    echo "Master installed: http://$(hostname -I | awk '{print $1}')/"
fi
