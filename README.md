# Emby Edge Panel

Emby Edge Panel 是一个面向小型社群与私有流媒体服务的多节点反向代理控制平面。项目采用单主控、多 Worker 架构，将 Cloudflare DNS、线路生命周期、节点健康检查、HTTPS 证书分发和 Nginx 动态路由统一到一个轻量化管理界面中。

## 设计目标

- 在 2 核 2 GB 等入门 VPS 上稳定承载数十名用户，并保留继续扩展的空间。
- 用户只保存一个固定入口；源站变更或节点迁移由主控热更新，无需修改播放器配置。
- Worker 不保存 Cloudflare 凭据，证书与基础域名由主控集中管理。
- 同时支持独立公网服务器和 NAT VPS，公网端口完全以服务商的实际映射为准。
- 避免引入数据库集群、消息队列等高维护组件，保持部署和故障恢复简单可控。

## 技术架构

主控由 Nginx、Python `ThreadingHTTPServer` 和 SQLite WAL 组成。读请求并行处理，注册、授权码签发和线路部署等状态变更进入 FIFO 队列串行提交，降低突发并发下的 SQLite 锁竞争。Cloudflare DNS 使用幂等更新，节点切换遵循“新节点预热、DNS 更新、数据库提交、旧节点清理”的顺序，减少迁移窗口中的服务中断。

Worker 使用 Nginx Stream 的 TLS 预读能力，在同一个内部端口 `12345` 自动区分 HTTP 与 HTTPS。HTTP 和 TLS 请求分别转发到本地反向代理后端，动态 Map 由签名 Agent 原子写入并热重载。主控与 Worker 之间使用 HMAC-SHA256 防止伪造和重放；通配符证书包使用由共享密钥派生的 AES-GCM 密钥加密传输。

证书采用 Cloudflare DNS-01 验证。整个集群共享主控维护的 `BASE_DOMAIN` 通配符证书，Worker 每日自动拉取续期结果，因此新增节点无需填写基础域名、Zone ID、API Token 或证书路径。

## 主要能力

- 用户注册、授权码和可调整线路额度
- 用户名大小写字母/数字约束与不区分大小写的唯一性控制
- 自动生成 `用户名-线路缩写` 前缀，例如 `Jack` + `wwj` → `jack-wwj`
- Cloudflare DNS-only 记录创建、更新与删除
- 目标源站热更新和跨节点热迁移
- Worker 心跳、离线熔断与管理端状态展示
- HTTP/HTTPS 同端口识别、Range 请求和 WebSocket 转发
- 集群通配符证书集中签发、加密分发和自动续期
- Alpine/OpenRC 与 Debian/Ubuntu/systemd Worker
- Debian/Ubuntu/systemd 主控
- 服务后台运行、开机自启及安装菜单状态检查
- 独立、彻底的主控和 Worker 卸载流程

## 下载

先用一条命令清理旧目录、创建目录并下载最新版：

```sh
cd ~ && rm -rf emby-edge-panel && mkdir emby-edge-panel && curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz | tar -xz --strip-components=1 -C emby-edge-panel && cd emby-edge-panel
```

随后按服务器角色运行一个安装命令。

主控：

```sh
sudo ./install-master.sh
```

Worker：

```sh
sudo ./install-worker.sh
```

再次运行安装器会读取现有配置。密码、Token 和共享密钥只显示“已设置”，直接回车即可保留。菜单同时提供服务状态检查。

## 主控配置

主控安装器支持 Debian 和 Ubuntu，交互菜单包括：

- 面板管理员密码
- Cloudflare API Token
- Cloudflare Zone ID
- 集群基础域名
- Worker 全局共享密钥
- 面板名称
- 可选面板访问域名

必填项未完成时安装器会列出缺失内容并拒绝开始。面板域名未配置时使用主控 IP；若 80 端口已有其他默认站点，安装器会提示配置独立面板域名，避免覆盖现有服务。

## Worker 与 NAT 端口

Worker 安装器自动识别 Alpine、Debian 和 Ubuntu。Alpine 使用 OpenRC 与 `/etc/periodic`，Debian/Ubuntu 使用 systemd service/timer；两类系统运行相同的 Agent、证书同步和 Nginx 双协议转发逻辑。安装时只需填写主控公网 IP 和共享密钥。Worker 内部服务端口固定为 `12345`，但公网端口没有任何固定值。

例如服务商控制台提供以下映射：

```text
公网 45678 → 内部 12345
```

则在主控添加节点时，“线路公网端口”填写 `45678`。如果主控通过同一个映射端口访问 Worker API，“Worker 通信公网端口”也填写 `45678`；若服务商另行映射通信端口，则按控制台实际值分别填写。用户入口会生成：

```text
https://用户名-线路缩写.基础域名:45678
```

公网端口可以是服务商允许的任意端口。SSH 映射端口与 Worker 服务端口无关。

## 授权码与线路命名

授权码中间的数字代表注册用户初始线路额度，不再代表有效天数。例如中间数字为 `5`，该用户注册后可创建 5 条线路，管理员之后仍可在用户额度模块修改。

用户名仅允许 2–24 位大小写英文字母和数字。线路输入框填写简短英文缩写，例如“哇哇叫”填写 `wwj`。系统会将用户名转为小写并组合为 `jack-wwj`；若完整前缀已存在，系统会要求修改缩写。

## 并发策略

面板使用多线程 HTTP 服务处理页面、数据读取和队列查询。注册、授权码签发、线路部署等写操作通过轻量 FIFO 队列有序执行，前端实时展示前方等待人数，并在轮到当前用户时自动提交。该方案针对几十人规模和 2C2G 主控设计，避免额外部署 Redis、数据库代理或负载均衡集群。

## 更新

重新执行“下载”中的单行命令，再运行对应安装器。安装器会读取已安装配置并备份应用和 Nginx 配置；主控数据库和 Worker 节点标识会保留。

## 卸载

```sh
sudo ./uninstall.sh
```

卸载器会检测主控和 Worker 是否存在，可分别删除。Worker 卸载会清理 Agent、OpenRC 或 systemd 服务、Nginx Map/Stream 配置、证书、证书同步任务、日志和备份；主控卸载会清理 systemd 服务、面板站点、Cloudflare 凭据、Certbot 续期配置和集群通配符证书。主控和 Worker 都不存在后，卸载器才会删除当前项目目录。

系统级 Nginx、Python、Certbot 等软件包不会自动删除，以免影响同机其他服务。

## 安全建议

- Cloudflare Token 仅授予指定 Zone 的 DNS 编辑权限。
- 使用足够长的随机共享密钥，并确保主控与所有 Worker 保持一致。
- Worker 系统时间误差必须小于 60 秒；受限 NAT 容器无法运行 Chrony 时由宿主机提供准确时间。
- Cloudflare 路线记录保持 DNS-only，任意端口不会经过 Cloudflare HTTP 代理。
- 不要提交 `.env`、数据库、Token、密码、私钥或 SSH 凭据。

## License

MIT
