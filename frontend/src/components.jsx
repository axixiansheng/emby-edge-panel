import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronRight,
  Copy,
  LoaderCircle,
  Plus,
  Route,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import { copyText, labels } from './api';

export const PanelContext = createContext(null);
export const usePanel = () => useContext(PanelContext);
export function IconButton({ icon: Icon, label, className = '', ...props }) {
  return (
    <button
      type="button"
      className={'icon-button ' + className}
      aria-label={label}
      title={label}
      {...props}
    >
      <Icon aria-hidden="true" size={18} />
    </button>
  );
}
export function Button({ children, icon: Icon, busy = false, className = '', ...props }) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
      className={'button ' + className}
      {...props}
      disabled={busy || props.disabled}
    >
      {busy ? (
        <LoaderCircle className="spin" size={17} aria-hidden="true" />
      ) : (
        Icon && <Icon size={17} aria-hidden="true" />
      )}
      {children}
    </motion.button>
  );
}
export function CopyButton({ value, label = '复制入口' }) {
  const { notify } = usePanel(),
    [copied, setCopied] = useState(false);
  const timer = useRef();
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <IconButton
      icon={copied ? CheckCheck : Copy}
      className={copied ? 'copied' : ''}
      label={copied ? '已复制' : label}
      onClick={async () => {
        try {
          await copyText(value);
          setCopied(true);
          clearTimeout(timer.current);
          timer.current = setTimeout(() => setCopied(false), 1800);
        } catch (e) {
          notify(e.message, 'error');
        }
      }}
    />
  );
}
export function Status({ status, children }) {
  return (
    <span className={'status status-' + status}>
      <span className="status-dot" />
      {children ||
        labels[status] ||
        { online: '在线', offline: '离线', available: '未使用', used: '已使用' }[status] ||
        status}
    </span>
  );
}
export function SearchField({ value, onChange, placeholder = '搜索', label = '搜索' }) {
  return (
    <div className="search-field">
      <Search size={17} aria-hidden="true" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        placeholder={placeholder}
      />
      {value && <IconButton icon={X} label="清除搜索" onClick={() => onChange('')} />}
    </div>
  );
}
export function Empty({ title, icon: Icon = Route, action, children }) {
  return (
    <div className="empty">
      <Icon size={36} strokeWidth={1.2} aria-hidden="true" />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
export function Table({ headers, children, className = '' }) {
  return (
    <div className={'table-wrap ' + className}>
      <table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
export function Cell({ label, children, className = '' }) {
  return (
    <td data-label={label || undefined} className={className}>
      {children}
    </td>
  );
}
export function Avatar({ name }) {
  return (
    <span className={'avatar avatar-' + ((name || 'A').charCodeAt(0) % 4)} aria-hidden="true">
      {name?.slice(0, 1).toUpperCase() || 'A'}
    </span>
  );
}
export function Dialog({ title, children, onClose, busy = false, wide = false }) {
  const ref = useRef(null),
    close = useRef(onClose);
  close.current = onClose;
  const reduced = useReducedMotion();
  const attemptClose = () => {
    if (!busy && !ref.current?.querySelector('form[aria-busy="true"]')) close.current();
  };
  useEffect(() => {
    const d = ref.current;
    const active = document.activeElement;
    d.showModal();
    d.querySelector('input:not([type="hidden"]),select,textarea')?.focus();
    return () => {
      d.close();
      active?.focus?.();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? 'dialog wide' : 'dialog'}
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        attemptClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) attemptClose();
      }}
    >
      <motion.div
        className="dialog-inner"
        initial={reduced ? false : { y: 20, opacity: 0.6 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 360, damping: 32 }}
      >
        <header className="dialog-header">
          <h2 id="dialog-title">{title}</h2>
          <IconButton icon={X} label="关闭" disabled={busy} onClick={attemptClose} />
        </header>
        {children}
      </motion.div>
    </dialog>
  );
}
export function ActionForm({
  onSubmit,
  children,
  buttonLabel = '保存',
  onClose,
  destructive = false,
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const live = useRef(true),
    working = useRef(false);
  useEffect(
    () => () => {
      live.current = false;
    },
    [],
  );
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (working.current) return;
        working.current = true;
        const body = Object.fromEntries(new FormData(e.currentTarget));
        setBusy(true);
        setError('');
        try {
          await onSubmit(body);
        } catch (err) {
          if (live.current) setError(err.message);
        } finally {
          working.current = false;
          if (live.current) setBusy(false);
        }
      }}
      aria-busy={busy}
    >
      <fieldset disabled={busy}>{children}</fieldset>
      <p className="form-error" role="alert">
        {error}
      </p>
      <footer className="form-actions">
        {onClose && (
          <Button type="button" className="secondary" disabled={busy} onClick={onClose}>
            取消
          </Button>
        )}
        <Button
          type="submit"
          icon={destructive ? Trash2 : Check}
          busy={busy}
          className={destructive ? 'danger' : 'primary'}
        >
          {buttonLabel}
        </Button>
      </footer>
    </form>
  );
}
export function RouteEditor({ route, onClose }) {
  const { data, admin, api, refresh, notify } = usePanel(),
    [suffix, setSuffix] = useState(''),
    [nodeId, setNodeId] = useState(
      String(route?.node_id || data.nodes.find((n) => n.online)?.id || ''),
    );
  return (
    <Dialog title={route ? '修改线路' : '新建线路'} onClose={onClose}>
      <ActionForm
        buttonLabel={route ? '保存更改' : '创建线路'}
        onClose={onClose}
        onSubmit={async (body) => {
          const endpoint = route
            ? admin
              ? '/admin/update_route'
              : '/user/update_route'
            : '/user/add_route';
          await api(endpoint, route ? { ...body, id: route.id } : body);
          onClose();
          notify('线路任务已提交');
          await refresh(true);
        }}
      >
        {!route && (
          <label>
            线路缩写
            <input
              autoFocus
              name="subdomain"
              required
              pattern={'[a-z0-9](?:[a-z0-9\\-]{0,30}[a-z0-9])?'}
              maxLength={32}
              value={suffix}
              onChange={(e) => setSuffix(e.target.value)}
              placeholder="main"
              autoComplete="off"
            />
          </label>
        )}
        <div className="address-preview">
          <Route size={17} aria-hidden="true" />
          <span translate="no">
            {route?.subdomain || data.username?.toLowerCase() + '-' + suffix}.{data.base_domain}
          </span>
        </div>
        <label>
          节点
          <select
            name="node_id"
            required
            value={nodeId}
            onChange={(e) => setNodeId(e.target.value)}
          >
            {!nodeId && <option value="">选择节点</option>}
            {data.nodes.map((n) => (
              <option key={n.id} value={n.id} disabled={!n.online && n.id !== route?.node_id}>
                {n.name}
                {n.online ? '' : ' · 离线'}
              </option>
            ))}
          </select>
        </label>
        <label>
          源站地址
          <input
            name="target"
            required
            defaultValue={route?.target || ''}
            placeholder="https://emby.example.com:8096"
            maxLength={2048}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
      </ActionForm>
    </Dialog>
  );
}
export function NodeEditor({ onClose }) {
  const { api, refresh, notify } = usePanel();
  return (
    <Dialog title="添加节点" onClose={onClose}>
      <ActionForm
        onClose={onClose}
        buttonLabel="添加节点"
        onSubmit={async (body) => {
          await api('/admin/add_node', body);
          onClose();
          notify('节点已添加，等待健康检查');
          await refresh(true);
        }}
      >
        <label>
          节点名称
          <input autoFocus name="name" maxLength={80} required placeholder="香港节点" />
        </label>
        <label>
          公网 IP 或域名
          <input
            name="host"
            maxLength={253}
            spellCheck={false}
            required
            placeholder="node.example.com"
          />
        </label>
        <div className="form-grid">
          <label>
            通信端口
            <input name="port" type="number" min="1" max="65535" required defaultValue="54321" />
          </label>
          <label>
            转发端口
            <input
              name="public_port"
              type="number"
              min="1"
              max="65535"
              required
              defaultValue="54321"
            />
          </label>
        </div>
        <label>
          共享密钥
          <input name="key" type="password" autoComplete="new-password" maxLength={256} required />
        </label>
      </ActionForm>
    </Dialog>
  );
}
export function Confirm({ title, description, onConfirm, onClose }) {
  return (
    <Dialog title={title} onClose={onClose}>
      <p className="confirm-description">{description}</p>
      <ActionForm
        buttonLabel="确认删除"
        destructive
        onClose={onClose}
        onSubmit={async () => {
          await onConfirm();
          onClose();
        }}
      />
    </Dialog>
  );
}
export function Toaster({ toast, onClose }) {
  return (
    <AnimatePresence mode="wait">
      {toast && (
        <motion.div
          key={toast.id}
          className={'toast ' + toast.kind}
          role={toast.kind === 'error' ? 'alert' : 'status'}
          initial={{ y: 16, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 8, opacity: 0 }}
        >
          <span className="toast-symbol">
            {toast.kind === 'error' ? <X size={17} /> : <Check size={17} />}
          </span>
          <span>{toast.text}</span>
          <IconButton icon={X} label="关闭提示" onClick={onClose} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
