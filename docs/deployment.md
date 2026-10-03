# 安装与部署

**全新设备可以直接安装新版，不需要先安装旧版。主控从首次安装到后续更新，都运行在 Docker 中。**

先按自己的情况选择入口，不要把下面各场景当成必须依次执行的步骤：

| 你的情况 | 执行什么 | 部署结果 |
| --- | --- | --- |
| 主控设备从未安装过本项目 | `sh install-master.sh` | 直接安装新版 Docker 主控 |
| 已经运行新版 Docker 主控，需要更新代码 | `sh deploy-docker.sh` | 备份数据，更新 Docker 主控 |
| 已经运行以前的原生旧版，需要迁移 | `sh deploy-docker.sh` | 保留已有数据，迁移成 Docker 主控 |
| 新安装 Worker 节点 | `sh install-worker.sh` | 原生 Python Agent + Nginx |

没有旧版的用户，直接看“全新安装主控”，不需要执行“已有旧版迁移”。

## 什么运行在 Docker 中

| 组件 | 运行位置 |
| --- | --- |
| 主控面板、API、用户端与管理端 | 主控 VPS 的同一个 Docker 容器 |
| 用户数据库 | 主控 VPS 的持久化目录，挂载进容器 |
| 主控 Nginx、Certbot 与证书续期 | 主控 VPS 宿主机 |
| Worker Agent 与转发 Nginx | Worker 节点的原生服务，不要求 Docker |

主控不是“安装时原生、升级时才 Docker”。宿主机保留 Nginx 和证书工具，是为了处理 HTTPS，并与同机其他网站共存；面板应用本身始终在容器中。

## 全新安装主控

以下命令在**主控 VPS** 上以 root 身份执行。只做这一节，即可得到新版主控。

### 1. 准备环境

使用 Debian/Ubuntu，并准备已经托管在 Cloudflare 的基础域名、API Token 和 Zone ID。

主控安装器要求设备已安装 Docker Engine 与 Docker Compose 2.30+。先检查：

```sh
docker --version
docker compose version
```

如果提示命令不存在，先按对应系统的 Docker 官方教程安装：[Debian](https://docs.docker.com/engine/install/debian/) 或 [Ubuntu](https://docs.docker.com/engine/install/ubuntu/)。同时安装 Compose 插件。这里安装的是 Docker，不是旧版 Emby Edge Panel。

准备源码下载工具：

```sh
apt-get update
apt-get install -y ca-certificates curl
```

### 2. 下载新版源码

```sh
mkdir -p emby-edge-panel
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz |
  tar -xz --strip-components=1 -C emby-edge-panel
cd emby-edge-panel
```

### 3. 启动新版安装器

```sh
sh install-master.sh
```

按菜单填写配置，完成后选择“8. 开始安装”：

| 配置 | 用途 |
| --- | --- |
| `PANEL_PASSWORD` | 管理员密码 |
| `CF_API_TOKEN` / `CF_ZONE_ID` | Cloudflare DNS 和 DNS 验证 |
| `BASE_DOMAIN` | 基础域名，如 `example.com`，不含协议 |
| `GLOBAL_SECRET_KEY` | Worker 协议和证书分发共享密钥 |
| `PANEL_NAME` / `PANEL_DOMAIN` | 面板名称和可选访问域名 |

面板域名可以填写 `panel.example.com`；不填写时，面板通过主控 IP 的 HTTP 入口访问。共享密钥应随机且足够长，安装 Worker 时使用相同密钥。

安装器会准备宿主机 Nginx 和证书，再构建并启动**新版 Docker 容器**。全新数据库会自动初始化。宿主机安装的 Python 用于备份等运维步骤，不代表面板改为原生运行。

`install-master.sh` 内部会调用 `deploy-docker.sh`，因为首次安装与更新共用容器构建、检查和启动流程。**这不是先装旧版再升级；首次安装也不需要再手动执行一次升级脚本。**

### 4. 确认安装结果

安装完成后，终端会给出面板访问地址。可以检查容器：

```sh
docker ps --filter name=emby-edge-panel
curl -fsS http://127.0.0.1:8080/healthz
```

出现 `emby-edge-panel` 容器且健康接口返回成功，即可使用新版面板。

基础配置示例见 [`.env.master.example`](../.env.master.example)。不要把实际配置文件提交到 Git。

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

## 全新安装 Worker

主控安装完成后，在 **Worker 节点**上执行，而不是在主控上重复安装：

```sh
mkdir -p emby-edge-panel
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz |
  tar -xz --strip-components=1 -C emby-edge-panel
cd emby-edge-panel
sh install-worker.sh
```

同样以 root 身份执行；如果节点没有 `curl`，Alpine 可先用 `apk add curl`，Debian/Ubuntu 可用 `apt-get install -y curl`。

配置主控公网 IP 和共享密钥，证书与基础域名由主控下发。非交互部署需要通过环境变量预先提供 `MASTER_IP` 与 `SECRET_KEY`。

安装完成后，在主控的“节点”页面添加该节点的公网地址、端口和共享密钥，等待健康检查标记在线，再分配线路。

Worker 内部转发端口为 `12345`，自动区分 HTTP/HTTPS；Agent 只监听 `127.0.0.1:8081`。NAT 服务商应将分配的公网端口映射到内部转发端口；主控节点配置填写实际公网 API 端口与客户端入口端口。

例如公网 `45678` 映射内部 `12345` 时，客户端入口包含 `:45678`，而不是内部端口。NAT 的 SSH 端口是另一项配置，不属于反代入口。

Worker 不保存 Cloudflare Token。节点时钟误差需要在 HMAC 校验窗口内；共享密钥应随机且足够长。小内存 NAT 节点可直接使用原生服务，不必额外部署 Docker。

## 已有 Docker 主控更新

**只适用于已经安装并正在使用本项目的用户。全新安装不需要执行这一节。**

在主控 VPS 上下载新代码到单独的源码目录，再执行更新脚本：

```sh
mkdir -p emby-edge-panel-update
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz |
  tar -xz --strip-components=1 -C emby-edge-panel-update
cd emby-edge-panel-update
sh deploy-docker.sh
```

更新脚本读取现有 `/opt/emby_panel/.env`，继续使用现有数据库。无需重新配置账号或重装 Docker，也不需要再次运行完整安装器。

升级流程使用 SQLite Backup API 生成一致性备份，构建镜像，并在独立数据库副本上启动候选容器。健康检查通过后切换正式主控，热重载面板 Nginx 站点。

候选容器不执行生产后台任务。升级不清理其他项目、用户数据库或备份；主控切换可能短时中断面板，但 Worker 已加载的转发规则不依赖主控持续在线。

Worker 版本单独维护。已有节点更新应先备份 Agent、映射、配置和证书，再替换代码并验证；完整安装器会配置 Nginx 和系统服务，不应当作无损热更新工具使用。

## 已有旧版主控迁移

这一节只为**已经运行原生旧版**的用户提供，不是新用户的安装前置条件。

准备好 Docker 与 Compose 后，在新版源码目录执行 `sh deploy-docker.sh`。脚本读取已有配置、备份数据库，将旧主控服务切换为新版 Docker 容器；旧服务停止，已有用户和线路数据继续使用。

因此有两种独立路径：

```text
全新设备：下载新版 -> install-master.sh -> 新版 Docker 主控
已有旧版：下载新版 -> deploy-docker.sh -> 新版 Docker 主控，保留已有数据
```

## 面板数据备份

管理员登录后进入“数据备份”，点击“导出数据”下载 JSON。下次恢复时选择此文件，查看差异预览，确认覆盖后点击“恢复数据”。无需先安装旧版本。

包含用户、密码哈希、有效期、额度、授权码、节点密钥、线路和公告。备份含敏感数据，请私密保存。只能恢复到相同基础域名的面板；新主控需先完成 Docker 安装及 Cloudflare、管理员密码、证书等环境配置，这些不在 JSON 中。

恢复前会自动保存当前数据，失败则取消恢复；自动备份位于 `/opt/emby_panel/db/backups/`，可在面板下载或再次选择恢复。有未完成线路任务时先等待完成。恢复后其他会话失效，线路配置通过任务同步，可在“任务”中查看进度。

## 代码回档

回档用于撤销一次已经完成的版本升级。**全新安装没有上一版本可恢复，不需要为了回档而先装旧版。**

有上一版本备份时，先确认线路任务已经完成或妥善处理，再使用相应升级备份：

```sh
sh rollback.sh /opt/emby-backups/upgrade-YYYYMMDD-HHMMSS
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
sh uninstall.sh
```

卸载会停止本项目服务并提供数据库备份选择。共享证书、升级备份和系统级依赖不会自动删除，避免影响同机其他应用。
