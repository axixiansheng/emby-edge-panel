export const labels = {
  add: '创建',
  update: '更新',
  delete: '删除',
  restore: '恢复同步',
  pending: '等待处理',
  running: '处理中',
  succeeded: '已完成',
  failed: '已回退',
  apply: '部署',
  cleanup: '清理旧配置',
  rollback: '回退中',
};
const messages = {
  'Session expired': '会话已过期，请重新登录',
  'Invalid username or password': '用户名或密码错误',
  'Authorization code is invalid or already used': '授权码无效或已使用',
  'Username already exists': '用户名已存在',
  'Username is reserved': '此用户名已保留',
  'Route quota reached': '线路额度已用完',
  'Node is offline': '目标节点离线',
  'Route prefix already exists': '线路前缀已存在',
  'This route already has an active operation': '该线路已有进行中的任务',
  'Origin must use a public HTTP(S) address': '源站必须使用有效的公网 HTTP(S) 地址',
  'Invalid origin URL': '源站地址格式无效',
  'Too many login attempts; retry in 15 minutes': '登录尝试过于频繁，请 15 分钟后重试',
  'Migrate all routes before deleting this node': '请先迁移此节点上的全部线路',
  'Node has unfinished operations': '节点还有未完成的任务',
  'Node endpoint already exists': '该节点通信地址已存在',
  'Password is required': '请输入密码',
  'Username must contain 2-24 letters or digits': '用户名仅支持 2-24 位英文字母和数字',
  'Invalid route prefix': '线路缩写仅支持小写字母、数字和连字符',
  'DNS name already exists; choose another route prefix': '此 DNS 名称已有记录，请更换线路缩写',
  'DNS record differs from managed route; administrator review required':
    'DNS 记录与线路不一致，请联系管理员核对',
  'Upstream unavailable or invalid response': '上游暂不可用，系统将自动重试',
  'Cloudflare DNS lookup rejected': 'DNS 查询失败，系统将自动重试',
  'Cloudflare DNS update rejected': 'DNS 更新失败，系统将自动重试',
  'Cloudflare DNS deletion rejected': 'DNS 删除失败，系统将自动重试',
  'Cloudflare DNS restore rejected': 'DNS 回退失败，系统将自动重试',
  'Worker rejected operation': '节点拒绝了操作，请联系管理员检查',
  'Database temporarily busy; retry shortly': '数据库暂忙，请稍后重试',
  'Internal error; check master logs': '系统内部错误，请联系管理员查看日志',
  'Account expired': '账户已过期',
  'Node not found': '节点不存在',
  'Expected an integer': '请输入整数',
  'Value out of range': '数值超出允许范围',
  'Wait for all route tasks before backup or restore': '请等待全部线路任务完成后，再备份或恢复',
  'Invalid or damaged backup': '备份文件不完整、已损坏或包含无效数据',
  'Unsupported backup format or version': '此备份格式或版本尚不受支持',
  'Backup domain does not match this panel': '备份基础域名与当前面板不同，请在相同域名的面板恢复',
  'Backup preview expired; validate again': '预览已过期，请重新选择并校验备份',
  'Panel data changed; validate backup again': '当前数据已变化，请重新选择并校验备份',
  'Preview this backup before restoring': '请先选择备份，查看恢复预览',
  'Could not save safety backup; restore cancelled': '无法保存恢复前的自动备份，已取消恢复',
  'Data restore in progress; retry shortly': '正在恢复数据，请稍后重试',
  'Active requests; retry restore shortly': '当前请求尚未结束，请稍后重试恢复',
  'Restore DNS conflict; administrator review required': '恢复 DNS 与现有记录冲突，请管理员核对',
  'Request too large': '文件过大，最大支持 8 MiB',
  'Node name and secret are required': '请输入节点名称与共享密钥',
  'User not found': '用户不存在',
  Forbidden: '没有此操作权限',
};
export const human = (text) => messages[text] || text;
export async function request(path, { token = '', body, signal } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, path === '/login' ? 60000 : 45000);
  try {
    const response = await fetch('/api' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: token },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      let data = {};
      try {
        data = await response.json();
      } catch {}
      const error = new Error(human(data.msg || '请求失败，请稍后重试'));
      error.status = response.status;
      throw error;
    }
    return response;
  } catch (error) {
    if (error.name === 'AbortError' && !signal?.aborted)
      throw new Error('请求超时，请刷新确认结果后再操作');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
export async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const input = document.createElement('textarea');
    input.value = value;
    input.className = 'clipboard-buffer';
    document.body.append(input);
    input.select();
    try {
      if (!document.execCommand('copy')) throw new Error('复制不可用，请手动选择地址');
    } finally {
      input.remove();
    }
  }
}
export async function download(response, name) {
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
