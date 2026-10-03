import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowUpRight,
  ArchiveRestore,
  Check,
  DatabaseBackup,
  FileCheck2,
  FileJson,
  FileUp,
  HardDriveDownload,
  LayoutGrid,
  List,
  LockKeyhole,
  Megaphone,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  Save,
  Server,
  ShieldCheck,
  Ticket,
  Trash2,
  UserRound,
  Users,
  X,
} from 'lucide-react';
import { download, human, labels } from './api';
import {
  ActionForm,
  Avatar,
  Button,
  Cell,
  Confirm,
  CopyButton,
  Dialog,
  Empty,
  IconButton,
  NodeEditor,
  RouteEditor,
  SearchField,
  Status,
  Table,
  usePanel,
} from './components';

export function Routes() {
  const { data, admin, api, refresh, notify } = usePanel(),
    [query, setQuery] = useState(''),
    [filter, setFilter] = useState(''),
    [editor, setEditor] = useState(undefined),
    [remove, setRemove] = useState(null);
  const [layout, setLayout] = useState(() => {
    try {
      return localStorage.getItem('emby_route_layout_v2') || 'grid';
    } catch {
      return 'grid';
    }
  });
  const rows = data.routes.filter(
    (r) =>
      (!filter || String(r.node_id) === filter) &&
      [r.subdomain, r.target, r.user, r.node_name].some((v) =>
        String(v || '')
          .toLowerCase()
          .includes(query.trim().toLowerCase()),
      ),
  );
  function chooseLayout(value) {
    setLayout(value);
    try {
      localStorage.setItem('emby_route_layout_v2', value);
    } catch {}
  }
  function state(route) {
    const pending = data.operations.some(
      (o) => o.resource === route.subdomain && ['pending', 'running'].includes(o.status),
    );
    return pending
      ? 'running'
      : data.nodes.find((n) => n.id === route.node_id)?.online
        ? 'online'
        : 'offline';
  }
  function entry(route) {
    return `https://${route.subdomain}.${data.base_domain}:${route.node_port}`;
  }
  function actions(route) {
    const pending = state(route) === 'running';
    return (
      <div className="route-actions">
        <CopyButton value={entry(route)} />
        <IconButton
          icon={Pencil}
          label="修改线路"
          disabled={pending}
          onClick={() => setEditor(route)}
        />
        <IconButton
          icon={Trash2}
          label="删除线路"
          className="danger-icon"
          disabled={pending}
          onClick={() => setRemove(route)}
        />
      </div>
    );
  }
  return (
    <>
      {data.announcement && (
        <aside className="announcement">
          <Megaphone size={17} aria-hidden="true" />
          <p>{data.announcement}</p>
        </aside>
      )}
      <div className="section-toolbar">
        <div className="section-label">
          <h2>{admin ? '全部线路' : '线路入口'}</h2>
          <span className="count">
            {rows.length}
            {rows.length !== data.routes.length ? ' / ' + data.routes.length : ''}
          </span>
        </div>
        {!admin && (
          <Button icon={Plus} className="primary" onClick={() => setEditor(null)}>
            新建线路
          </Button>
        )}
      </div>
      <div className="filter-toolbar">
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder={admin ? '搜索线路、用户或源站' : '搜索线路或源站'}
          label="搜索线路"
        />
        <div className="filter-tools">
          <select aria-label="筛选节点" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">全部节点</option>
            {data.nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name}
              </option>
            ))}
          </select>
          <div className="layout-switch" role="group" aria-label="线路布局">
            <IconButton
              icon={List}
              label="列表布局"
              aria-pressed={layout === 'table'}
              onClick={() => chooseLayout('table')}
            />
            <IconButton
              icon={LayoutGrid}
              label="网格布局"
              aria-pressed={layout === 'grid'}
              onClick={() => chooseLayout('grid')}
            />
          </div>
        </div>
      </div>
      {!rows.length ? (
        <Empty
          title={query || filter ? '没有匹配的线路' : '暂无线路'}
          action={
            query || filter ? (
              <Button
                className="secondary"
                onClick={() => {
                  setQuery('');
                  setFilter('');
                }}
              >
                清除筛选
              </Button>
            ) : !admin ? (
              <Button icon={Plus} className="primary" onClick={() => setEditor(null)}>
                新建线路
              </Button>
            ) : null
          }
        />
      ) : layout === 'grid' ? (
        <div className="route-grid">
          {rows.map((r, index) => (
            <motion.article
              key={r.id}
              className={'route-tile ' + (index === 0 ? 'featured' : '')}
              whileHover={{ y: -3 }}
              transition={{ type: 'spring', stiffness: 320, damping: 30 }}
            >
              <header>
                <span className="route-node">
                  <Server size={16} />
                  {r.node_name || '节点缺失'}
                </span>
                <Status status={state(r)}>{state(r) === 'running' ? '同步中' : undefined}</Status>
              </header>
              <div className="route-tile-main">
                <h3>{r.subdomain}</h3>
                <a
                  href={entry(r)}
                  target="_blank"
                  rel="noopener noreferrer"
                  translate="no"
                  className="route-entry"
                >
                  {r.subdomain}.{data.base_domain}:{r.node_port}
                  <ArrowUpRight size={15} />
                </a>
              </div>
              <div className="route-tile-source">
                <span>源站</span>
                <span translate="no">{r.target}</span>
              </div>
              <footer>
                {admin ? (
                  <span className="route-owner">
                    <Avatar name={r.user} />
                    {r.user}
                  </span>
                ) : (
                  <a
                    className="open-route"
                    href={entry(r)}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={'打开 ' + r.subdomain + ' 线路入口'}
                  >
                    <ArrowUpRight size={22} />
                  </a>
                )}
                {actions(r)}
              </footer>
            </motion.article>
          ))}
        </div>
      ) : (
        <Table
          headers={['线路', ...(admin ? ['用户'] : []), '节点', '源站', '操作']}
          className="route-table"
        >
          {rows.map((r) => (
            <tr key={r.id}>
              <Cell>
                <div className="table-route-name">
                  <Route size={17} aria-hidden="true" />
                  <strong>{r.subdomain}</strong>
                  <Status status={state(r)}>{state(r) === 'running' ? '同步中' : undefined}</Status>
                </div>
                <a
                  href={entry(r)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="small-entry"
                  translate="no"
                >
                  {r.subdomain}.{data.base_domain}:{r.node_port}
                  <ArrowUpRight size={12} />
                </a>
              </Cell>
              {admin && (
                <Cell label="用户">
                  <span className="user-identity">
                    <Avatar name={r.user} />
                    {r.user}
                  </span>
                </Cell>
              )}
              <Cell label="节点">
                <span className="node-inline">
                  <Server size={14} />
                  {r.node_name || '节点缺失'}
                </span>
              </Cell>
              <Cell label="源站">
                <span translate="no" className="origin">
                  {r.target}
                </span>
              </Cell>
              <Cell className="action-cell">{actions(r)}</Cell>
            </tr>
          ))}
        </Table>
      )}
      {editor !== undefined && <RouteEditor route={editor} onClose={() => setEditor(undefined)} />}
      {remove && (
        <Confirm
          title="删除线路"
          description={'删除 ' + remove.subdomain + ' 后，该入口将停止转发。'}
          onClose={() => setRemove(null)}
          onConfirm={async () => {
            await api(admin ? '/admin/delete_route' : '/user/delete_route', { id: remove.id });
            notify('删除任务已提交');
            await refresh(true);
          }}
        />
      )}
    </>
  );
}
export function Nodes() {
  const { data, api, refresh, notify } = usePanel(),
    [adding, setAdding] = useState(false),
    [remove, setRemove] = useState(null);
  return (
    <>
      <div className="section-toolbar">
        <h2>转发节点</h2>
        <Button icon={Plus} className="primary" onClick={() => setAdding(true)}>
          添加节点
        </Button>
      </div>
      {!data.nodes.length ? (
        <Empty title="暂无节点" icon={Server} />
      ) : (
        <div className="node-grid">
          {data.nodes.map((n) => (
            <article className={'node-tile ' + (n.online ? 'online' : 'offline')} key={n.id}>
              <div className="node-tile-top">
                <div className="server-mark">
                  <Server size={38} strokeWidth={1.15} />
                </div>
                <Status status={n.online ? 'online' : 'offline'} />
              </div>
              <h3>{n.name}</h3>
              <span className="node-host" translate="no">
                {n.host}
              </span>
              <dl className="node-details">
                <div>
                  <dt>通信端口</dt>
                  <dd>{n.port}</dd>
                </div>
                <div>
                  <dt>公网端口</dt>
                  <dd>{n.public_port || n.port}</dd>
                </div>
                <div>
                  <dt>关联线路</dt>
                  <dd>{data.routes.filter((r) => r.node_id === n.id).length}</dd>
                </div>
              </dl>
              <footer>
                <span>节点 #{n.id}</span>
                <IconButton
                  icon={Trash2}
                  className="danger-icon"
                  label="删除节点"
                  onClick={() => setRemove(n)}
                />
              </footer>
            </article>
          ))}
        </div>
      )}
      {adding && <NodeEditor onClose={() => setAdding(false)} />}
      {remove && (
        <Confirm
          title="删除节点"
          description={'删除 ' + remove.name + '。存在关联线路或未完成任务时无法删除。'}
          onClose={() => setRemove(null)}
          onConfirm={async () => {
            await api('/admin/delete_node', { id: remove.id });
            notify('节点已删除');
            await refresh(true);
          }}
        />
      )}
    </>
  );
}
function Quota({ user }) {
  const { api, refresh, notify } = usePanel(),
    [value, setValue] = useState(user.route_limit),
    [busy, setBusy] = useState(false);
  useEffect(() => setValue(user.route_limit), [user.route_limit]);
  return (
    <form
      className="quota-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        try {
          await api('/admin/update_user_limit', { username: user.username, route_limit: value });
          notify('额度已保存');
          await refresh(true);
        } catch (e) {
          notify(e.message, 'error');
        } finally {
          setBusy(false);
        }
      }}
    >
      <input
        type="number"
        required
        min="0"
        max="1000"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={busy}
        aria-label={user.username + ' 线路额度'}
      />
      <IconButton
        icon={busy ? RefreshCw : Save}
        label="保存额度"
        disabled={busy}
        className={busy ? 'spin-icon' : ''}
        onClick={(e) => e.currentTarget.closest('form').requestSubmit()}
      />
    </form>
  );
}
export function UsersView() {
  const { data } = usePanel(),
    [query, setQuery] = useState('');
  const users = data.users.filter((u) => u.username.toLowerCase().includes(query.toLowerCase()));
  return (
    <>
      <div className="section-toolbar">
        <h2>账户与额度</h2>
        <SearchField value={query} onChange={setQuery} placeholder="搜索用户名" label="搜索用户" />
      </div>
      {!users.length ? (
        <Empty title="没有匹配的用户" icon={Users} />
      ) : (
        <Table className="users-table" headers={['用户', '有效期', '线路数', '额度']}>
          {users.map((u) => (
            <tr key={u.username}>
              <Cell className="user-main">
                <span className="user-identity">
                  <Avatar name={u.username} />
                  <strong>{u.username}</strong>
                </span>
              </Cell>
              <Cell className="user-expiry" label="有效期">
                <time dateTime={u.expire}>{u.expire}</time>
              </Cell>
              <Cell className="user-count" label="线路数">
                <strong className="numeric">{u.route_count}</strong>
              </Cell>
              <Cell className="user-quota" label="额度">
                <Quota user={u} />
              </Cell>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
export function Codes() {
  const { data, api, refresh, notify } = usePanel(),
    [query, setQuery] = useState(''),
    [filter, setFilter] = useState('all'),
    [adding, setAdding] = useState(false);
  const codes = data.codes.filter(
    (c) =>
      (filter === 'all' || Boolean(c.used) === (filter === 'used')) &&
      [c.code, c.user].some((v) =>
        String(v || '')
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
  );
  return (
    <>
      <div className="section-toolbar">
        <h2>注册授权</h2>
        <Button icon={Plus} className="primary" onClick={() => setAdding(true)}>
          签发授权码
        </Button>
      </div>
      <div className="filter-toolbar">
        <SearchField
          value={query}
          onChange={setQuery}
          label="搜索授权码"
          placeholder="搜索授权码或用户"
        />
        <select aria-label="授权码状态" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">全部状态</option>
          <option value="available">未使用</option>
          <option value="used">已使用</option>
        </select>
      </div>
      {!codes.length ? (
        <Empty title="暂无匹配授权码" icon={Ticket} />
      ) : (
        <div className="code-grid">
          {codes.map((c) => (
            <article className={'code-ticket' + (c.used ? ' redeemed' : '')} key={c.code}>
              <div className="code-ticket-main">
                <span className="code-ticket-icon">
                  <Ticket size={22} aria-hidden="true" />
                </span>
                <span className="code-value" translate="no">
                  {c.code}
                </span>
                <CopyButton value={c.code} label="复制授权码" />
              </div>
              <div className="code-ticket-details">
                <span className="code-quota">
                  <strong>{c.dur}</strong> 条线路
                </span>
                <Status status={c.used ? 'used' : 'available'} />
                <span className="code-owner">
                  <UserRound size={13} aria-hidden="true" />
                  {c.user || '未绑定'}
                </span>
              </div>
            </article>
          ))}
        </div>
      )}
      {adding && (
        <Dialog title="签发授权码" onClose={() => setAdding(false)}>
          <ActionForm
            buttonLabel="签发授权码"
            onClose={() => setAdding(false)}
            onSubmit={async (body) => {
              await api('/admin/generate', body);
              setAdding(false);
              notify('授权码已签发');
              await refresh(true);
            }}
          >
            <label>
              初始线路额度
              <input
                autoFocus
                name="route_limit"
                type="number"
                min="0"
                max="1000"
                required
                defaultValue="3"
              />
            </label>
          </ActionForm>
        </Dialog>
      )}
    </>
  );
}
export function Operations() {
  const { data, admin } = usePanel(),
    [filter, setFilter] = useState('all');
  const rows = data.operations.filter(
    (o) =>
      filter === 'all' ||
      (filter === 'active' ? ['pending', 'running'].includes(o.status) : o.status === filter),
  );
  return (
    <>
      <div className="section-toolbar">
        <h2>配置变更</h2>
        <select aria-label="任务状态" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">全部任务</option>
          <option value="active">进行中</option>
          <option value="succeeded">已完成</option>
          <option value="failed">已回退</option>
        </select>
      </div>
      {!rows.length ? (
        <Empty title={filter === 'all' ? '暂无线路变更任务' : '没有此状态的任务'} icon={Route} />
      ) : (
        <div className="task-list">
          {rows.map((o) => (
            <article className={'task-row task-' + o.status} key={o.id}>
              <span className="task-glyph">
                {o.status === 'succeeded' ? (
                  <Check size={19} />
                ) : o.status === 'failed' ? (
                  <ArchiveRestore size={19} />
                ) : (
                  <RefreshCw className={o.status === 'running' ? 'spin' : ''} size={19} />
                )}
              </span>
              <div className="task-content">
                <div className="task-title">
                  <h3>{o.resource}</h3>
                </div>
                <p className={'task-meta' + (!admin ? ' personal' : '')}>
                  <span className="task-action">{labels[o.action]}</span>
                  <span
                    className="task-phase"
                    title={
                      o.status === 'succeeded' && o.phase === 'cleanup'
                        ? '旧节点保留至 ' +
                          new Date(o.next_run * 1000).toLocaleTimeString('zh-CN', { hour12: false })
                        : undefined
                    }
                  >
                    {o.status === 'succeeded' && o.phase === 'cleanup'
                      ? '缓存保护中'
                      : labels[o.phase]}
                  </span>
                  {admin && (
                    <span className="task-owner">
                      <UserRound size={12} aria-hidden="true" />
                      {o.username === 'admin' ? '管理员' : o.username}
                      {o.owner_username &&
                        o.owner_username !== o.username &&
                        ' / ' + o.owner_username}
                    </span>
                  )}
                </p>
                {o.error && (
                  <p className="task-error">
                    {o.status === 'succeeded' ? '旧节点清理重试：' : ''}
                    {human(o.error)}
                  </p>
                )}
              </div>
              <div className="task-status">
                <Status status={o.status} />
              </div>
              <time dateTime={new Date(o.updated_at * 1000).toISOString()}>
                {new Date(o.updated_at * 1000).toLocaleString('zh-CN', { hour12: false })}
              </time>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
export function Settings() {
  const { data, api, refresh, notify } = usePanel(),
    [text, setText] = useState(data.announcement);
  return (
    <div className="announcement-editor">
      <h2>发布公告</h2>
      <ActionForm
        buttonLabel="发布公告"
        onSubmit={async () => {
          await api('/admin/update_announcement', { text });
          notify('公告已发布');
          await refresh(true);
        }}
      >
        <label>
          公告内容
          <textarea
            name="text"
            rows={8}
            maxLength={10000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="向用户发布的公告"
          />
        </label>
        <div className="editor-count">{text.length} / 10000</div>
      </ActionForm>
      {text && (
        <div className="announcement-preview">
          <Megaphone size={18} />
          <p>{text}</p>
        </div>
      )}
    </div>
  );
}
const tableNames = {
  users: '用户',
  routes: '线路',
  nodes: '节点',
  auth_codes: '授权码',
  settings: '公告与设置',
};
export function Backups() {
  const { data, api, response, refresh, notify } = usePanel(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [preview, setPreview] = useState(null),
    [confirmed, setConfirmed] = useState(false),
    [saved, setSaved] = useState([]),
    [restored, setRestored] = useState('');
  const fileRef = useRef(null),
    sequence = useRef(0),
    backup = useRef(null),
    confirmation = useRef(null),
    working = useRef(false),
    mounted = useRef(true);
  const blocked = (data.active_tasks || 0) > 0;
  const restoreBlocked = blocked || (data.cleanup_tasks || 0) > 0;
  useEffect(
    () => () => {
      mounted.current = false;
      sequence.current++;
      backup.current = null;
    },
    [],
  );
  async function loadSaved() {
    const result = await api('/admin/backups/list');
    if (mounted.current) setSaved(result.backups);
  }
  useEffect(() => {
    loadSaved().catch((e) => notify(e.message, 'error'));
  }, []);
  function reset() {
    sequence.current++;
    backup.current = null;
    confirmation.current = null;
    setPreview(null);
    setConfirmed(false);
    setError('');
    if (fileRef.current) fileRef.current.value = '';
  }
  async function prepare(payload, name) {
    if (working.current) return;
    reset();
    const current = sequence.current;
    working.current = true;
    setBusy(true);
    setRestored('');
    try {
      const result = await api('/admin/backups/preview', { backup: payload });
      if (!mounted.current || sequence.current !== current) return;
      backup.current = payload;
      confirmation.current = result.confirmation;
      setPreview({ ...result, name });
    } catch (e) {
      if (mounted.current && sequence.current === current) setError(e.message);
    } finally {
      working.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function exportData() {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError('');
    try {
      await download(
        await response('/admin/backups/export'),
        'emby-edge-' + new Date().toISOString().replace(/[:.]/g, '-') + '.json',
      );
      notify('数据已导出');
    } catch (e) {
      if (mounted.current) setError(e.message);
    } finally {
      working.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function importFile(file) {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      reset();
      setError('文件过大，最大支持 8 MiB');
      return;
    }
    try {
      await prepare(JSON.parse(await file.text()), file.name);
    } catch {
      reset();
      setError('无法读取备份，请选择有效的 JSON 文件');
    }
  }
  async function restore(e) {
    e.preventDefault();
    if (!confirmed || !backup.current || !confirmation.current || working.current || restoreBlocked)
      return;
    working.current = true;
    setBusy(true);
    setError('');
    try {
      const result = await api('/admin/backups/restore', {
        backup: backup.current,
        confirmation: confirmation.current,
      });
      if (!mounted.current) return;
      reset();
      setRestored(
        '数据已恢复。' +
          (result.tasks ? result.tasks + ' 条线路正在同步，可在任务中查看进度。' : '') +
          '恢复前的自动备份已保留。',
      );
      notify('数据已恢复');
      await refresh(true);
      await loadSaved();
    } catch (err) {
      if (mounted.current) {
        reset();
        setError(err.message);
      }
    } finally {
      working.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <>
      {blocked && (
        <p className="notice" role="status">
          有线路任务正在执行，完成后可导出或恢复数据。
        </p>
      )}
      {!blocked && restoreBlocked && (
        <p className="notice" role="status">
          数据可正常导出。旧节点缓存保护结束后可恢复备份。
        </p>
      )}
      <div className="backup-workbench">
        <section className="backup-export">
          <div className="backup-art" aria-hidden="true">
            <DatabaseBackup size={80} strokeWidth={0.85} />
            <span className="backup-art-stamp">
              <Check size={15} />
            </span>
          </div>
          <h2>留一份，安心一点。</h2>
          <p>用户、密码哈希、额度、授权码、节点、线路与公告。</p>
          <div className="backup-counts">
            <span>
              <strong>{data.users.length}</strong> 用户
            </span>
            <span>
              <strong>{data.routes.length}</strong> 线路
            </span>
            <span>
              <strong>{data.nodes.length}</strong> 节点
            </span>
          </div>
          <Button
            icon={ArrowDownToLine}
            className="primary"
            busy={busy && !preview}
            disabled={blocked || busy}
            onClick={exportData}
          >
            导出数据
          </Button>
        </section>
        <section className="backup-import">
          <FileUp size={30} strokeWidth={1.2} aria-hidden="true" />
          <h2>让熟悉的一切回来。</h2>
          <p>恢复前自动保存当前数据，线路随后同步至节点与 DNS。</p>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".json,application/json"
            aria-label="选择备份文件"
            onChange={(e) => importFile(e.target.files[0])}
          />
          <button
            type="button"
            className="upload-zone"
            disabled={blocked || busy}
            onClick={() => fileRef.current.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (!blocked && !busy) importFile(e.dataTransfer.files[0]);
            }}
          >
            <FileJson size={25} strokeWidth={1.4} />
            <span>
              <strong>{busy ? '正在处理' : '选择备份文件'}</strong>
              <small>JSON / 最大 8 MiB</small>
            </span>
            <ArrowUpFromLine size={17} />
          </button>
        </section>
      </div>
      <p className="backup-warning">
        <LockKeyhole size={16} />
        <span>
          备份包含密码哈希和节点密钥，请私密保存。恢复会覆盖当前业务数据，其他会话将失效。管理员密码、Cloudflare
          配置与证书需单独保留。
        </span>
      </p>
      <p className="form-error" role="alert">
        {error}
      </p>
      {restored && (
        <p className="restore-result" role="status">
          <FileCheck2 size={19} />
          {restored}
        </p>
      )}
      {preview && (
        <motion.section
          className="restore-preview"
          initial={{ opacity: 0.5, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="section-toolbar">
            <div className="section-label">
              <h2>恢复预览</h2>
              <Status status="online">校验通过</Status>
            </div>
            <IconButton icon={X} label="取消恢复预览" disabled={busy} onClick={reset} />
          </div>
          <div className="backup-file">
            <FileJson size={22} />
            <div>
              <strong>{preview.name}</strong>
              <p>
                {new Date(preview.created_at).toLocaleString('zh-CN')} · {preview.base_domain}
              </p>
            </div>
          </div>
          <Table
            headers={['数据', '当前', '恢复后', '新增', '更新', '移除']}
            className="backup-table"
          >
            {Object.entries(preview.counts).map(([name, counts]) => (
              <tr key={name}>
                <Cell>
                  <strong>{tableNames[name]}</strong>
                </Cell>
                {[
                  ['current', '当前'],
                  ['incoming', '恢复后'],
                  ['added', '新增'],
                  ['updated', '更新'],
                  ['removed', '移除'],
                ].map(([key, label]) => (
                  <Cell
                    key={key}
                    label={label}
                    className={key === 'removed' && counts[key] ? 'destructive' : ''}
                  >
                    {counts[key]}
                  </Cell>
                ))}
              </tr>
            ))}
          </Table>
          <form className="restore-confirm" onSubmit={restore}>
            <label className="checkbox-label">
              <input
                type="checkbox"
                name="confirm"
                checked={confirmed}
                disabled={busy || restoreBlocked}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>确认使用此备份覆盖当前数据</span>
            </label>
            <Button
              icon={ArchiveRestore}
              type="submit"
              className="danger"
              busy={busy}
              disabled={restoreBlocked || !confirmed}
            >
              恢复数据
            </Button>
          </form>
        </motion.section>
      )}
      <section className="saved-backups">
        <div className="section-toolbar">
          <div className="section-label">
            <h2>恢复前的自动备份</h2>
            <span className="count">{saved.length}</span>
          </div>
          <IconButton
            icon={RefreshCw}
            label="刷新自动备份"
            onClick={() => loadSaved().catch((e) => notify(e.message, 'error'))}
          />
        </div>
        {!saved.length ? (
          <Empty title="暂无自动备份" icon={HardDriveDownload} />
        ) : (
          saved.map((item) => (
            <div className="saved-backup-row" key={item.name}>
              <HardDriveDownload size={21} />
              <div>
                <strong>{new Date(item.created_at * 1000).toLocaleString('zh-CN')}</strong>
                <p>{(item.size / 1024).toFixed(1)} KiB · 恢复前自动保存</p>
              </div>
              <div className="row-actions">
                <IconButton
                  icon={ArrowDownToLine}
                  label="下载自动备份"
                  onClick={async () => {
                    try {
                      await download(
                        await response('/admin/backups/saved/' + encodeURIComponent(item.name)),
                        item.name,
                      );
                    } catch (e) {
                      notify(e.message, 'error');
                    }
                  }}
                />
                <IconButton
                  icon={ArchiveRestore}
                  label="选择此备份恢复"
                  disabled={busy || blocked}
                  onClick={async () => {
                    if (working.current) return;
                    try {
                      const result = await response(
                        '/admin/backups/saved/' + encodeURIComponent(item.name),
                      );
                      await prepare(await result.json(), item.name);
                    } catch (e) {
                      notify(e.message, 'error');
                    }
                  }}
                />
              </div>
            </div>
          ))
        )}
      </section>
    </>
  );
}
