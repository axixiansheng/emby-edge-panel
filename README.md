# Emby Edge Panel

An open-source Emby reverse-proxy control panel with one master and multiple signed Worker nodes.

## Features

- Multi-user panel with invitation codes and per-user route limits
- Cloudflare DNS automation
- Route creation, source updates, and hot migration between nodes
- Signed master-to-Worker synchronization and health checks
- Dynamic Nginx maps for streaming proxy routes
- Browser-trusted HTTPS on every Worker with automatic HTTP/TLS protocol detection
- Automatic Let's Encrypt wildcard certificate issuance and renewal through Cloudflare DNS-01
- Alpine/OpenRC Worker support, including NAT servers
- SQLite WAL, operation logs, node health state, and atomic map writes

## Architecture

- Master: Debian/Ubuntu, Nginx on port 80, Python API on `127.0.0.1:8080`
- Worker: Alpine Linux, Nginx stream on internal port `12345`, HTTP backend on `127.0.0.1:12346`, HTTPS backend on `127.0.0.1:12347`, Agent on `127.0.0.1:8081`
- NAT Worker: map a public service port such as `54321` to internal port `12345`; enter `54321` in the panel

## Download

```sh
rm -rf emby-edge-panel
mkdir emby-edge-panel
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz | tar -xz --strip-components=1 -C emby-edge-panel
cd emby-edge-panel
```

This produces `emby-edge-panel`, not `emby-edge-panel-main`.

## Interactive Master Install

```sh
sudo ./install-master.sh
```

再次运行安装器时，会自动读取 `/opt/emby_panel/.env` 中的现有配置并在菜单中显示为已设置；密码、Token 和共享密钥不会明文显示。直接回车可保留当前值。命令行预先导出的环境变量优先于现有配置。

The menu lets you enter or modify:

- panel administrator password
- Cloudflare API Token
- Cloudflare Zone ID
- base domain
- Worker shared secret
- panel name

Existing environment variables are used as defaults. Non-interactive automation remains supported:

```sh
export PANEL_PASSWORD='choose-a-strong-password'
export CF_API_TOKEN='cloudflare-api-token'
export CF_ZONE_ID='cloudflare-zone-id'
export BASE_DOMAIN='example.com'
export GLOBAL_SECRET_KEY='long-random-shared-secret'
export PANEL_NAME='My Emby Edge'
sudo -E ./install-master.sh </dev/null
```

## Interactive Worker Install

```sh
sudo ./install-worker.sh
```

The Worker installer asks for:

- master public IP
- this Worker's shared HMAC secret
- the same base domain configured on the master
- a Cloudflare API Token with `Zone:DNS:Edit` and `Zone:Zone:Read` permission for that zone
- an optional unique node certificate ID

It automatically installs Certbot and Nginx stream support, obtains a Let's Encrypt wildcard certificate using Cloudflare DNS-01, and configures the same internal port `12345` to accept both HTTP and HTTPS. The panel displays and copies HTTPS route addresses by default.

The Cloudflare token is stored root-only at `/root/.secrets/emby-cloudflare.ini` because it is required for automatic certificate renewal. For public deployments, create a restricted token limited to the one DNS zone; do not reuse a global API key.

Non-interactive Worker installation is also supported:

```sh
export MASTER_IP='203.0.113.10'
export SECRET_KEY='same-node-key-configured-in-master'
export BASE_DOMAIN='example.com'
export CF_API_TOKEN='restricted-cloudflare-dns-token'
sudo -E ./install-worker.sh </dev/null
```

## Uninstall

```sh
sudo ./uninstall.sh
```

The uninstaller menu can remove the master, Worker, both, or timestamped project backups. It can preserve the master database in a timestamped directory under `/root`. System packages such as Nginx and Python are not removed.

## NAT Workers

The Worker always listens internally on `12345` and automatically distinguishes HTTP from TLS. If a provider maps public `54321` to internal `12345`, configure the master panel with the public host and port `54321`; the generated user route is `https://subdomain.example.com:54321`.

SSH mapping ports are unrelated to Worker service ports.

## Updating

Pull or download the latest source and run the relevant installer again. Installers back up existing application and Nginx directories before replacement. The master installer preserves an existing `panel.db`.

When upgrading an older HTTP-only Worker, run the new `install-worker.sh` and provide the base domain plus a restricted Cloudflare DNS token. Existing route map files are preserved, and the Worker begins serving the same routes over HTTPS after the installer succeeds.

The master installer disables known legacy links named `default`, `emby-panel-http`, and `emby-panel` before enabling the current site. Other Nginx websites are preserved. If another website is already configured as `default_server` on port 80, remove `default_server` from one of the sites or choose which site should own the default port.

## Security

- Never commit `.env`, databases, API tokens, passwords, or SSH credentials
- Use a separate long random secret for every Worker
- Keep Worker clocks synchronized; requests with clock skew over 60 seconds are rejected
- On restricted NAT/LXC/OpenVZ containers, Chrony may lack permission to adjust time. The installer now warns and continues; the hosting provider must keep the host clock accurate
- Restrict Worker `/api/` to the master public IP
- Revoke and replace a Worker Cloudflare token immediately if the server is compromised
- Worker wildcard certificates cover one base domain. All route hostnames must remain direct DNS records (`proxied: false`) pointing to the selected Worker
- Configure HTTPS for the master panel before exposing it to untrusted users
- Review shell scripts before running them as root

## License

MIT
