import { Component, Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion/react';
import {
  ArrowRight,
  ArrowUpRight,
  Archive,
  Check,
  ChevronDown,
  DatabaseBackup,
  Eye,
  EyeOff,
  Layers,
  ListChecks,
  LockKeyhole,
  LogOut,
  Megaphone,
  Moon,
  RefreshCw,
  Route,
  Server,
  Settings2,
  Sun,
  Ticket,
  UserRound,
  Users,
  Waypoints,
} from 'lucide-react';
import { request } from './api';
import { Avatar, Button, IconButton, PanelContext, Status, Toaster } from './components';
import { Backups, Codes, Nodes, Operations, Routes, Settings, UsersView } from './views';
import './style.css';
const Scene = lazy(() => import('./Scene'));
const views = {
  routes: ['线路', Route],
  nodes: ['节点', Server],
  users: ['用户', Users],
  codes: ['授权码', Ticket],
  operations: ['任务', ListChecks],
  settings: ['公告', Megaphone],
  backups: ['备份', DatabaseBackup],
};
function preference(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}
function initialSession() {
  try {
    const token = sessionStorage.getItem('emby_token') || sessionStorage.getItem('token');
    const role = sessionStorage.getItem('emby_role') || sessionStorage.getItem('role');
    return token && ['admin', 'user'].includes(role) ? { token, role } : null;
  } catch {
    return null;
  }
}
class ErrorBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="fatal">
        <h1>页面暂时无法加载</h1>
        <Button icon={RefreshCw} onClick={() => location.reload()}>
          重新加载
        </Button>
      </main>
    ) : (
      this.props.children
    );
  }
}

function App() {
  const reduce = useReducedMotion();
  const [session, setSession] = useState(null),
    [checkingSession, setCheckingSession] = useState(true),
    [data, setData] = useState(null),
    [loading, setLoading] = useState(false),
    [connected, setConnected] = useState(true),
    [updated, setUpdated] = useState(null);
  const [view, setView] = useState(() => location.hash.slice(1) || 'routes'),
    [toast, setToast] = useState(null),
    [theme, setTheme] = useState(() => preference('emby_theme', 'light'));
  const [systemDark, setSystemDark] = useState(
      () => matchMedia('(prefers-color-scheme: dark)').matches,
    ),
    [name, setName] = useState('Emby Edge'),
    flight = useRef(null),
    sessionRef = useRef(session),
    abort = useRef(null),
    toastId = useRef(0);
  sessionRef.current = session;
  useEffect(() => {
    const controller = new AbortController();
    const legacy = initialSession();
    request('/session', { token: legacy?.token || '', signal: controller.signal })
      .then((r) => r.json())
      .then((s) => {
        if (!controller.signal.aborted && ['admin', 'user'].includes(s.role)) {
          setSession({ role: s.role, token: '' });
          for (const key of ['emby_token', 'emby_role', 'token', 'role'])
            sessionStorage.removeItem(key);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!controller.signal.aborted) setCheckingSession(false);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    request('/public/config', { signal: controller.signal })
      .then((r) => r.json())
      .then((c) => {
        if (!controller.signal.aborted) {
          setName(c.panel_name);
          document.title = c.panel_name;
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  const dark = theme === 'dark' || (theme === 'system' && systemDark),
    admin = session?.role === 'admin';
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)'),
      handle = () => setSystemDark(media.matches);
    media.addEventListener('change', handle);
    return () => media.removeEventListener('change', handle);
  }, []);
  useEffect(() => {
    const closeMenus = (event) => {
      document.querySelectorAll('.profile-menu[open]').forEach((menu) => {
        if (event.type === 'keydown' && event.key === 'Escape') {
          menu.open = false;
          menu.querySelector('summary').focus();
        } else if (event.type === 'pointerdown' && !menu.contains(event.target)) menu.open = false;
      });
    };
    document.addEventListener('pointerdown', closeMenus);
    document.addEventListener('keydown', closeMenus);
    return () => {
      document.removeEventListener('pointerdown', closeMenus);
      document.removeEventListener('keydown', closeMenus);
    };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]').content = dark ? '#1b1b20' : '#f2f2f0';
    remember('emby_theme', theme);
  }, [dark, theme]);
  const notify = useCallback(
    (text, kind = 'success') => setToast({ text, kind, id: ++toastId.current }),
    [],
  );
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  const clearSession = useCallback(() => {
    abort.current?.abort();
    setSession(null);
    setData(null);
    setView('routes');
    history.replaceState(null, '', '/');
    for (const key of ['emby_token', 'emby_role', 'token', 'role']) sessionStorage.removeItem(key);
  }, []);
  const response = useCallback(
    async (path, body) => {
      const current = sessionRef.current;
      const token = current?.token || '';
      try {
        const result = await request(path, { token, body });
        if (current !== sessionRef.current) throw new Error('登录状态已变化');
        return result;
      } catch (e) {
        if (e.status === 401 && sessionRef.current === current) clearSession();
        throw e;
      }
    },
    [clearSession],
  );
  const api = useCallback(async (path, body) => (await response(path, body)).json(), [response]);
  const refresh = useCallback(
    async (force = false) => {
      const current = sessionRef.current;
      if (!current) return;
      if (flight.current) {
        if (!force) return flight.current;
        await flight.current.catch(() => {});
      }
      if (sessionRef.current !== current) return;
      const controller = new AbortController();
      abort.current = controller;
      setLoading(true);
      const promise = (async () => {
        try {
          const result = await request(current.role === 'admin' ? '/admin/data' : '/user/data', {
            token: current.token,
            signal: controller.signal,
          });
          const next = await result.json();
          if (
            sessionRef.current !== current ||
            controller.signal.aborted ||
            abort.current !== controller
          )
            return;
          setData((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
          setConnected(true);
          setUpdated(Date.now());
          setName(next.panel_name);
          document.title = next.panel_name;
        } catch (e) {
          if (controller.signal.aborted) return;
          if (e.status === 401) clearSession();
          else {
            setConnected(false);
            throw e;
          }
        } finally {
          if (abort.current === controller) {
            setLoading(false);
            flight.current = null;
          }
        }
      })();
      flight.current = promise;
      return promise;
    },
    [clearSession],
  );
  useEffect(() => {
    if (!session) return;
    history.replaceState(
      null,
      '',
      (session.role === 'admin' ? '/admin-panel' : '/panel') + location.hash,
    );
    refresh().catch((e) => notify(e.message, 'error'));
    const timer = setInterval(() => {
      if (
        !document.hidden &&
        !document.querySelector('dialog[open]') &&
        !document.activeElement?.matches('input,textarea,select')
      )
        refresh().catch(() => {});
    }, 5000);
    return () => {
      clearInterval(timer);
      abort.current?.abort();
      flight.current = null;
    };
  }, [session, refresh, notify]);
  const allowed = admin ? Object.keys(views) : ['routes', 'operations'];
  const selected = allowed.includes(view) ? view : 'routes';
  useEffect(() => {
    const handler = () => setView(location.hash.slice(1) || 'routes');
    addEventListener('hashchange', handler);
    return () => removeEventListener('hashchange', handler);
  }, []);
  function navigate(key) {
    setView(key);
    history.replaceState(null, '', location.pathname + (key === 'routes' ? '' : '#' + key));
    document.querySelector('#content')?.focus({ preventScroll: true });
  }
  async function logout() {
    try {
      await api('/logout', {});
    } catch (e) {
      notify(e.message, 'error');
      return;
    }
    clearSession();
  }
  const context = { data, admin, api, response, refresh, notify };
  return (
    <MotionConfig reducedMotion="user" transition={{ type: 'spring', stiffness: 350, damping: 34 }}>
      <PanelContext.Provider value={context}>
        <a className="skip-link" href="#content">
          跳转到主要内容
        </a>
        <header className={'app-header ' + (!session ? 'auth-header' : '')}>
          <a
            className="brand"
            href={session ? (admin ? '/admin-panel' : '/panel') : '/'}
            aria-label={data?.panel_name || name}
            onClick={(e) => {
              if (
                session &&
                e.button === 0 &&
                !e.ctrlKey &&
                !e.metaKey &&
                !e.shiftKey &&
                !e.altKey
              ) {
                e.preventDefault();
                navigate('routes');
                window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
              }
            }}
          >
            <Waypoints size={25} strokeWidth={2.1} />
            <span>{data?.panel_name || name}</span>
          </a>
          {session && (
            <div className="space-label">
              <span /> {admin ? '管理空间' : '我的空间'}
            </div>
          )}
          <div className="header-tools">
            {session && (
              <IconButton
                icon={RefreshCw}
                label="刷新数据"
                disabled={loading}
                className={loading ? 'spin-icon' : ''}
                onClick={() => refresh(true).catch((e) => notify(e.message, 'error'))}
              />
            )}
            <details className="profile-menu">
              <summary aria-label="账户与外观" title="账户与外观">
                {session ? <Avatar name={admin ? 'A' : data?.username} /> : <Settings2 size={19} />}
                <ChevronDown size={13} />
              </summary>
              <div className="profile-content">
                {session && <strong>{admin ? '管理员' : data?.username || '用户'}</strong>}
                <label>
                  外观
                  <select
                    aria-label="外观"
                    value={theme}
                    onChange={(e) => setTheme(e.target.value)}
                  >
                    <option value="light">浅色</option>
                    <option value="dark">深色</option>
                    <option value="system">跟随系统</option>
                  </select>
                </label>
                {session && (
                  <Button icon={LogOut} className="secondary" onClick={logout}>
                    退出登录
                  </Button>
                )}
              </div>
            </details>
          </div>
        </header>
        {checkingSession ? (
          <main id="content" className="session-check" aria-busy="true" />
        ) : session ? (
          <>
            <nav
              className="main-nav"
              role="tablist"
              aria-label="面板视图"
              onKeyDown={(e) => {
                if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
                e.preventDefault();
                const buttons = [...e.currentTarget.querySelectorAll('button')],
                  index = buttons.indexOf(document.activeElement),
                  next =
                    e.key === 'Home'
                      ? 0
                      : e.key === 'End'
                        ? buttons.length - 1
                        : (index + (e.key === 'ArrowRight' ? 1 : -1) + buttons.length) %
                          buttons.length;
                buttons[next].click();
                buttons[next].focus();
              }}
            >
              {allowed.map((key) => {
                const [label, Icon] = views[key];
                return (
                  <button
                    key={key}
                    role="tab"
                    id={'nav-' + key}
                    aria-controls={'view-' + key}
                    aria-selected={selected === key}
                    tabIndex={selected === key ? 0 : -1}
                    onClick={(e) => {
                      navigate(key);
                      e.currentTarget.scrollIntoView({
                        block: 'nearest',
                        inline: 'nearest',
                        behavior: reduce ? 'auto' : 'smooth',
                      });
                    }}
                  >
                    <Icon size={17} aria-hidden="true" />
                    <span>{label}</span>
                    {selected === key && (
                      <motion.span className="nav-active" layoutId="active-tab" />
                    )}
                    {key === 'operations' &&
                      data?.operations.some((o) => ['pending', 'running'].includes(o.status)) && (
                        <span className="nav-attention" />
                      )}
                  </button>
                );
              })}
            </nav>
            <main id="content" className="workspace" tabIndex={-1}>
              {!data ? (
                <div className="loading-workspace">
                  <div className="skeleton wide-line" />
                  <div className="skeleton scene-skeleton" />
                  <div className="skeleton line" />
                  {!connected && (
                    <Button
                      icon={RefreshCw}
                      onClick={() => refresh(true).catch((e) => notify(e.message, 'error'))}
                    >
                      重试连接
                    </Button>
                  )}
                </div>
              ) : (
                <>
                  <div className="page-title">
                    <div>
                      <h1>
                        {selected === 'routes'
                          ? admin
                            ? '线路管理'
                            : '我的线路'
                          : {
                              nodes: '节点网络',
                              users: '用户管理',
                              codes: '授权码',
                              operations: '线路任务',
                              settings: '公告',
                              backups: '数据备份',
                            }[selected]}
                      </h1>
                      <p>
                        {selected === 'routes'
                          ? admin
                            ? `${data.users.length} 位用户，${data.routes.length} 条线路`
                            : `${data.username}，${data.expire} 到期`
                          : {
                              nodes: `${data.nodes.filter((n) => n.online).length} / ${data.nodes.length} 个节点在线`,
                              users: `${data.users?.length} 位用户`,
                              codes: `${data.codes?.filter((c) => !c.used).length} 枚授权码可用`,
                              operations: `${data.operations.length} 条任务记录`,
                              settings: '面向所有用户发布',
                              backups: '保存账号、线路与节点配置',
                            }[selected]}
                      </p>
                    </div>
                    <span className={'connection-state ' + (!connected ? 'stale' : '')}>
                      <span />
                      {connected ? '已连接主控' : '连接暂时中断'}
                    </span>
                  </div>
                  {selected === 'routes' && <Overview data={data} admin={admin} dark={dark} />}
                  <motion.section
                    key={selected}
                    id={'view-' + selected}
                    role="tabpanel"
                    aria-labelledby={'nav-' + selected}
                    initial={{ opacity: 0.65 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.18 }}
                  >
                    {selected === 'routes' ? (
                      <Routes />
                    ) : selected === 'nodes' ? (
                      <Nodes />
                    ) : selected === 'users' ? (
                      <UsersView />
                    ) : selected === 'codes' ? (
                      <Codes />
                    ) : selected === 'operations' ? (
                      <Operations />
                    ) : selected === 'settings' ? (
                      <Settings />
                    ) : (
                      <Backups />
                    )}
                  </motion.section>
                </>
              )}
              <footer className="workspace-footer">
                <span>
                  Emby Edge <span className="footer-version">2.2.2</span>
                </span>
                <span>
                  {updated
                    ? '更新于 ' + new Date(updated).toLocaleTimeString('zh-CN', { hour12: false })
                    : '正在连接'}
                </span>
              </footer>
            </main>
          </>
        ) : (
          <Auth
            onLogin={(s) => {
              setSession({ role: s.role, token: '' });
              for (const key of ['emby_token', 'emby_role', 'token', 'role'])
                sessionStorage.removeItem(key);
            }}
            dark={dark}
            name={name}
          />
        )}
        <Toaster toast={toast} onClose={() => setToast(null)} />
      </PanelContext.Provider>
    </MotionConfig>
  );
}
function Overview({ data, admin, dark }) {
  const nodes = data.nodes.filter((n) => n.online),
    active = data.operations.filter((o) => ['pending', 'running'].includes(o.status));
  const reserved = active.filter(
    (o) => o.action === 'add' && !data.routes.some((r) => r.subdomain === o.resource),
  ).length;
  const available = Math.max(0, (data.route_limit || 0) - data.routes.length - reserved);
  return (
    <section className="overview" aria-label="连接概览">
      <div className="overview-content">
        <div className="overview-line">
          <Status status={nodes.length ? 'online' : 'offline'}>
            {nodes.length ? '节点就绪' : '暂无在线节点'}
          </Status>
          <span className="domain" translate="no">
            {data.base_domain}
          </span>
        </div>
        <h2>{nodes[0]?.name || '等待连接'}</h2>
        <div className="overview-facts">
          {admin ? (
            <>
              <span>
                <strong>{data.routes.length}</strong> 条线路
              </span>
              <span>
                <strong>{data.users.length}</strong> 位用户
              </span>
              <span>
                <strong>{data.active_tasks ?? active.length}</strong> 项进行中任务
              </span>
            </>
          ) : (
            <>
              <span>
                <strong>{data.routes.length}</strong> 条线路
              </span>
              <span>
                <strong>{available}</strong> / {data.route_limit} 可用额度
              </span>
            </>
          )}
        </div>
        {nodes.length > 1 && <p className="additional-nodes">另有 {nodes.length - 1} 个在线节点</p>}
      </div>
      <Suspense fallback={<div className="scene-pending" />}>
        <Scene
          mode="overview"
          nodeStates={data.nodes.map((n) => (n.online ? '1' : '0')).join(',')}
          dark={dark}
        />
      </Suspense>
    </section>
  );
}
function Auth({ onLogin, dark, name }) {
  const [register, setRegister] = useState(false),
    [visible, setVisible] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  useEffect(() => {
    const hide = () => {
      if (document.hidden) setVisible(false);
    };
    document.addEventListener('visibilitychange', hide);
    return () => document.removeEventListener('visibilitychange', hide);
  }, []);
  return (
    <main id="content" className="auth-world" tabIndex={-1}>
      <Suspense fallback={null}>
        <Scene dark={dark} />
      </Suspense>
      <motion.section
        className="auth-content"
        initial={{ opacity: 0.5, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h1>{name}</h1>
        <div className="auth-tabs" role="tablist" aria-label="账户">
          <button
            type="button"
            role="tab"
            aria-selected={!register}
            disabled={busy}
            onClick={() => {
              setRegister(false);
              setError('');
            }}
          >
            登录{!register && <motion.span layoutId="auth-tab" />}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={register}
            disabled={busy}
            onClick={() => {
              setRegister(true);
              setError('');
            }}
          >
            注册{register && <motion.span layoutId="auth-tab" />}
          </button>
        </div>
        <form
          id="auth-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            const form = e.currentTarget,
              body = Object.fromEntries(new FormData(form));
            if (!register) body.code = '';
            setBusy(true);
            setError('');
            try {
              const result = await (await request('/login', { body })).json();
              form.elements.password.value = '';
              setVisible(false);
              onLogin(result);
            } catch (err) {
              setError(err.message);
            } finally {
              setBusy(false);
            }
          }}
          aria-busy={busy}
        >
          <fieldset disabled={busy}>
            <label>
              用户名
              <div className="auth-input">
                <UserRound size={18} aria-hidden="true" />
                <input
                  name="username"
                  autoComplete="username"
                  pattern="[A-Za-z0-9]{2,24}"
                  minLength={2}
                  maxLength={24}
                  required
                  spellCheck={false}
                  placeholder="你的用户名"
                />
              </div>
            </label>
            <label>
              密码
              <div className="auth-input">
                <LockKeyhole size={18} aria-hidden="true" />
                <input
                  name="password"
                  type={visible ? 'text' : 'password'}
                  autoComplete={register ? 'new-password' : 'current-password'}
                  maxLength={1024}
                  required
                  placeholder="输入密码"
                />
                <IconButton
                  icon={visible ? EyeOff : Eye}
                  label={visible ? '隐藏密码' : '显示密码'}
                  aria-pressed={visible}
                  onClick={() => setVisible((v) => !v)}
                />
              </div>
            </label>
            <AnimatePresence>
              {register && (
                <motion.label
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  授权码
                  <div className="auth-input">
                    <Ticket size={18} aria-hidden="true" />
                    <input
                      name="code"
                      maxLength={128}
                      autoComplete="off"
                      required
                      placeholder="输入你的授权码"
                    />
                  </div>
                </motion.label>
              )}
            </AnimatePresence>
          </fieldset>
          <p className="form-error" role="alert">
            {error}
          </p>
          <Button type="submit" busy={busy} className="primary auth-submit">
            {register ? '创建账户' : '进入我的空间'}
            <ArrowRight size={18} aria-hidden="true" />
          </Button>
        </form>
        <div className="auth-signature">
          <Waypoints size={16} aria-hidden="true" />
          <span>Emby Edge</span>
          <span className="signature-rule" />
          <span>与你的媒体相连</span>
        </div>
      </motion.section>
    </main>
  );
}
createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
