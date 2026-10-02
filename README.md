# Emby Edge Panel

面向几十至百来人社群的多节点 Emby 反向代理控制平面。保留单主控、多 Worker、固定用户入口、Cloudflare DNS-only、NAT 公网端口、通配符证书分发及节点热迁移等业务。

## v2 架构

- 主控：Python 3.12、Starlette、Uvicorn 单进程、SQLite WAL；HTML/CSS/原生 JavaScript，无前端运行时或构建服务。
- 主控业务拆分为配置、数据库、安全、外部通信、业务服务和 HTTP 接口；页面和 API 由同一容器提供。
- 注册直接提交短事务：授权码占用、用户创建和会话签发原子完成；密码计算在事务外进行。取消浏览器票据队列和全局 POST 写锁。
- 线路创建、更新、迁移、删除进入 SQLite 持久化任务，每条线路最多一个活动任务。两个后台执行线程处理外部通信，不占用数据库写事务。
- 保存 DNS 原始记录和执行阶段；数据库状态与清理阶段原子提交。重启恢复未完成任务，失败自动重试、回退；清理失败不会错误回退已生效的新线路。
- 迁移先预热新 Worker，再切换 DNS，等待旧 DNS TTL（至少 300 秒）加 60 秒余量后清理旧 Worker。仅修改同节点源站时不会删除新线路。
- 保留旧数据库表、用户名大小写、密码和未过期会话。旧 SHA256/固定盐 PBKDF2 密码登录成功后升级为随机盐 Argon2id。Argon2id 使用 19 MiB、2 次迭代、单线程，密码计算最多两个并发，适合小内存 VPS。
- 用户端：线路、额度、公告、复制入口、编辑及迁移、任务状态。管理端：线路、节点、用户额度、授权码、任务、公告独立视图。
- 配置缺失拒绝启动；限制请求体、并发线程、登录尝试和目标地址，避免目标 URL 注入 Nginx 配置。页面采用安全 DOM API 和 CSP。

## 主控安装

要求 Debian/Ubuntu、已安装 Docker 和 Docker Compose 2.30+、root 权限。Nginx 和 Certbot 留在宿主机，兼容同机其他项目。主控不安装 Redis、数据库服务或 Node.js。配置采用 raw env-file 读取，保留密码及密钥中的 `$` 等字符。

```sh
mkdir -p emby-edge-panel
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz |
  tar -xz --strip-components=1 -C emby-edge-panel
cd emby-edge-panel
sudo sh install-master.sh
```

安装器读取 `/opt/emby_panel/.env`，交互配置管理员密码、Cloudflare Token/Zone、基础域名、共享密钥、面板名称和可选面板域名；直接回车保留已有值。

容器运行资源限制：192 MB 内存、1 CPU 配额、96 PID、只读根文件系统、删除 Linux capabilities、禁止提权。只在 `127.0.0.1:8080` 发布端口，由宿主机 Nginx 提供 HTTPS。宿主机现有证书目录权限要求容器使用 UID 0，但它没有宿主机管理权限、Docker socket、特权模式或可写证书挂载。

数据位置：

```text
/opt/emby_panel/.env                 主控配置（不得上传）
/opt/emby_panel/db/panel.db          原有用户数据库，原路径不变
/opt/emby-backups/upgrade-*          升级前数据库、部署配置和旧镜像信息
/etc/letsencrypt/                   宿主机证书与续期配置
```

生产只运行一个主控进程/副本。不要同时启动多个容器共享同一个数据库：启动恢复逻辑及任务认领按单实例设计。

## 已安装主控升级

在新的版本目录执行：

```sh
sudo sh deploy-docker.sh
```

升级脚本先用 SQLite Backup API 创建一致性备份，再构建镜像，以数据库副本启动不执行后台任务的候选容器。健康检查通过后才停止旧 systemd 主控、切换正式容器，并热重载面板的 Nginx 站点。其他容器和网站不变。首次切换会有短暂面板中断，Worker 的 Emby 转发不依赖主控在线。

候选检查使用自动分配的本机端口，避免与其他服务冲突。候选数据与正式数据库分离；升级脚本不会删除用户数据、清理 Docker 镜像或清理不相关项目。

状态与日志：

```sh
docker ps --filter name=emby-edge-panel
docker logs --tail 100 emby-edge-panel
curl -fsS http://127.0.0.1:8080/healthz
```

## 回档

升级前的 GitHub 原代码保留在标签 `backup/pre-refactor-20261003`。服务器每次升级另外保留数据库和部署备份。

```sh
sudo sh rollback.sh /opt/emby-backups/upgrade-时间戳
```

回档脚本拒绝在有未完成线路任务时回档，防止主控代码与 DNS/Worker 状态不一致。应先在“任务”视图确认任务完成，或修复其上游故障。代码回档保留当前数据库，**不会用升级前的旧数据库覆盖新增用户**。首次从 systemd 升级的备份可恢复旧 systemd 业务代码、前端和 Nginx，并为旧登录逻辑自动补充新密码格式验证；后续 Docker 升级可恢复旧镜像。升级会预先安装小型宿主机 `python3-argon2` 包，确保回档后新旧用户都能登录。

数据库灾难恢复与代码回档是两种不同操作。只有在确认可以舍弃备份之后的数据，并停止所有数据库写入时，才能另行恢复数据库备份。

## Worker

```sh
sudo sh install-worker.sh
```

支持 Alpine/OpenRC 和 Debian/Ubuntu/systemd，内置 Nginx Stream 在内部 `12345` 区分 HTTP/HTTPS；主控填写服务商实际公网映射端口。比如公网 `45678 → 内部 12345`，线路入口为 `https://用户名-缩写.基础域名:45678`。

Worker 不保存 Cloudflare Token。证书从主控按原 HMAC/AES-GCM 协议获取，由每日同步任务刷新。主控兼容现有 v3.0 Worker；仓库的 v3.1 Worker 增加目标校验、Nginx 配置检测及同步重载确认。Worker 更新与主控更新分别进行，不会自动登录未提供 SSH 信息的节点。

HMAC 的 60 秒时间窗口不是严格的单次 nonce 防重放；线路同步操作设计为幂等。Worker 时钟需准确，共享密钥必须足够随机。目标域名在主控提交时验证公网解析，但不能完全防止后续 DNS 重绑定，应仅发放给可信社群用户。

## 业务规则

- 用户名 2–24 位英文字母或数字，新注册不区分大小写唯一，`admin` 为保留名。
- 授权码中间数字为初始线路额度，不是有效天数；管理员可设置用户额度为 0–1000，签发授权码额度为 1–1000。
- 完整线路前缀由小写用户名和缩写组成，比如 `Jack` + `wwj` → `jack-wwj`；前缀保持唯一。
- 额度计算包括尚未部署完成的创建任务，避免并发超额。下调额度不删除用户已存在的线路。
- 离线节点不可接收新部署；已有线路不会因短时心跳失败被删除。连续三次健康检查失败标记离线，成功后恢复。
- DNS 记录必须与受管理线路匹配；发现其他用途的同名记录时拒绝覆盖，不会在回退中误删。
- 任务提交返回 HTTP 202 和 `operation_id`，通过 `/api/operations/{id}` 查询结果。用户只能查询自己的任务。

## 测试

本地使用 Python 3.10+：

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖并发注册、授权码竞争、大小写兼容、旧密码、额度竞争、线路所有权、同节点更新、跨节点迁移、DNS 回退、清理重试、任务重启恢复、证书协议、HTTP 输入校验和管理员权限。压测与故障测试应使用独立数据库，不要向正式用户数据注入测试账户。

## 卸载

```sh
sudo sh uninstall.sh
```

主控卸载会停止本项目容器，并询问是否备份数据库。升级备份、共享通配符证书及其续期配置保留，避免影响同机其他网站。系统级 Docker/Nginx/Python 不自动卸载。

## 依赖与许可

Python 依赖版本固定于 `requirements.txt`。前端本地打包 Lucide 1.50.0，许可证见 `master/lucide.LICENSE`，运行无需 CDN。项目采用 MIT。
