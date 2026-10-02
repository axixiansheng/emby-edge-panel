# 安装与部署

本文介绍通用部署方式，不包含特定服务器的操作记录。架构、优化机制和安全边界见[README](../README.md)。

## 部署模型

- 主控：Debian/Ubuntu，Docker、Docker Compose 2.30+，单容器、单 Uvicorn 进程。
- Worker：Alpine/OpenRC 或 Debian/Ubuntu/systemd，Python Agent 与 Nginx 原生服务。
- Nginx 与 Certbot 留在主控宿主机，负责 HTTPS 和证书续期。
- Cloudflare 使用 DNS-only 记录；控制面不承载视频流量。

安装脚本需要 root 权限。已有部署升级时使用升级脚本，不应通过重新运行完整安装器来替代升级。

## 主控安装

```sh
mkdir -p emby-edge-panel
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz |
  tar -xz --strip-components=1 -C emby-edge-panel
cd emby-edge-panel
sudo sh install-master.sh
```

安装器交互配置管理员密码、Cloudflare Token/Zone、基础域名、共享密钥、面板名称和可选访问域名；已有配置可直接回车保留。配置文件不要提交到 Git。

| 配置 | 用途 |
| --- | --- |
| `PANEL_PASSWORD` | 管理员密码 |
| `CF_API_TOKEN` / `CF_ZONE_ID` | Cloudflare DNS 和 DNS 验证 |
| `BASE_DOMAIN` | 用户线路与通配符证书的基础域名 |
| `GLOBAL_SECRET_KEY` | Worker 协议和证书分发共享密钥 |
| `PANEL_NAME` / `PANEL_DOMAIN` | 面板名称和可选访问域名 |

基础配置示例见 `.env.master.example`。Compose 使用 raw env-file，避免配置中的 `$` 等字符被插值。

## 数据与容器限制

| 路径 | 内容 |
| --- | --- |
| `/opt/emby_panel/.env` | 主控配置和凭据 |
| `/opt/emby_panel/db/panel.db` | SQLite 数据库 |
| `/opt/emby-backups/upgrade-*` | 每次升级生成的一致性备份 |
| `/etc/letsencrypt/` | 宿主机证书和续期配置 |

容器默认限制为 192 MiB 内存、1 CPU、96 PID；只读根文件系统、删除 capabilities、禁止提权，证书只读挂载，不挂载 Docker socket。数据库目录必须可写。

Compose 默认使用 UID 0 读取宿主机现有证书权限；这不等于特权容器。自定义 UID/GID 时必须同步处理数据库和证书的读取权限。

容器只向 `127.0.0.1:8080` 发布服务端口，由宿主机 Nginx 代理。同机端口冲突需要同时调整发布端口与 Nginx 上游配置。

**生产只运行一个主控实例。** 不要通过增加 Uvicorn workers 或复制容器实现扩容；当前任务恢复与进程内协调按单实例设计。

## Worker 安装

在 Worker 设备上下载项目源码，再执行：

```sh
sudo sh install-worker.sh
```

配置主控公网 IP 和共享密钥，证书与基础域名由主控下发。非交互部署需要通过环境变量预先提供 `MASTER_IP` 与 `SECRET_KEY`。

Worker 内部转发端口为 `12345`，自动区分 HTTP/HTTPS；Agent 只监听 `127.0.0.1:8081`。NAT 服务商应将分配的公网端口映射到内部转发端口；主控节点配置填写实际公网 API 端口与客户端入口端口。

例如公网 `45678` 映射内部 `12345` 时，客户端入口包含 `:45678`，而不是内部端口。NAT 的 SSH 端口是另一项配置，不属于反代入口。

Worker 不保存 Cloudflare Token。节点时钟误差需要在 HMAC 校验窗口内；共享密钥应随机且足够长。小内存 NAT 节点可直接使用原生服务，不必额外部署 Docker。

## 主控升级

在新版本源码目录执行：

```sh
sudo sh deploy-docker.sh
```

升级流程使用 SQLite Backup API 生成一致性备份，构建镜像，并在独立数据库副本上启动候选容器。健康检查通过后切换正式主控，热重载面板 Nginx 站点。

候选容器不执行生产后台任务。升级不清理其他项目、用户数据库或备份；主控切换可能短时中断面板，但 Worker 已加载的转发规则不依赖主控持续在线。

Worker 版本单独维护。已有节点更新应先备份 Agent、映射、配置和证书，再替换代码并验证；完整安装器会配置 Nginx 和系统服务，不应当作无损热更新工具使用。

## 代码回档

先确认线路任务已经完成或妥善处理，再使用相应升级备份：

```sh
sudo sh rollback.sh /opt/emby-backups/upgrade-YYYYMMDD-HHMMSS
```

回档脚本保留**当前数据库**，不会覆盖升级后新增用户；停止容器后会再次检查是否存在未完成任务。

从旧 systemd 部署升级时，可恢复旧业务代码和前端，并补充新密码格式验证；Docker 升级可恢复旧镜像。宿主机 `python3-argon2` 依赖用于兼容新密码。

Nginx 只恢复面板的 `sites-available/emby-panel` 和 `sites-available/emby-panel-https`，不恢复其他项目或全局配置。

数据库灾难恢复是独立操作，会舍弃备份之后的数据。需要停止写入并明确恢复范围，不能与代码回档混用。备份可能包含密钥，应限制权限并妥善保管。

## 健康检查

```sh
docker ps --filter name=emby-edge-panel
curl -fsS http://127.0.0.1:8080/healthz
docker logs --tail 100 emby-edge-panel
```

Worker 使用签名健康检查。未经授权的请求应被拒绝，不能用匿名请求的 403 判断节点故障。

## 卸载

```sh
sudo sh uninstall.sh
```

卸载会停止本项目服务并提供数据库备份选择。共享证书、升级备份和系统级依赖不会自动删除，避免影响同机其他应用。
