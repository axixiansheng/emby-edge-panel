# Emby Edge Panel

An open-source Emby reverse-proxy control panel with one master and multiple signed Worker nodes.

## Features

- Multi-user panel with invitation codes and per-user route limits
- Cloudflare DNS automation
- Route creation, source updates, and hot migration between nodes
- Signed master-to-Worker synchronization and health checks
- Dynamic Nginx maps for streaming proxy routes
- Alpine/OpenRC Worker support, including NAT servers
- SQLite WAL, operation logs, node health state, and atomic map writes

## Architecture

- Master: Debian/Ubuntu, Nginx on port 80, Python API on `127.0.0.1:8080`
- Worker: Alpine Linux, Nginx on internal port `12345`, Agent on `127.0.0.1:8081`
- NAT Worker: map a public service port such as `54321` to internal port `12345`; enter `54321` in the panel

## Download

```sh
rm -rf emby-edge-panel
mkdir emby-edge-panel
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=1 -C emby-edge-panel
cd emby-edge-panel
```

This produces `emby-edge-panel`, not `emby-edge-panel-main`.

## Interactive Master Install

```sh
sudo ./install-master.sh
```

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

Enter the master public IP and this Worker's shared secret in the menu. Use the same Worker secret when adding that node in the master panel.

## Uninstall

```sh
sudo ./uninstall.sh
```

The uninstaller menu can remove the master, Worker, both, or timestamped project backups. It can preserve the master database in a timestamped directory under `/root`. System packages such as Nginx and Python are not removed.

## NAT Workers

The Worker always listens internally on `12345`. If a provider maps public `54321` to internal `12345`, configure the master panel with the public host and port `54321`.

SSH mapping ports are unrelated to Worker service ports.

## Updating

Pull or download the latest source and run the relevant installer again. Installers back up existing application and Nginx directories before replacement. The master installer preserves an existing `panel.db`.

The master installer disables known legacy links named `default`, `emby-panel-http`, and `emby-panel` before enabling the current site. Other Nginx websites are preserved. If another website is already configured as `default_server` on port 80, remove `default_server` from one of the sites or choose which site should own the default port.

## Security

- Never commit `.env`, databases, API tokens, passwords, or SSH credentials
- Use a separate long random secret for every Worker
- Keep Worker clocks synchronized; requests with clock skew over 60 seconds are rejected
- Restrict Worker `/api/` to the master public IP
- Configure HTTPS before exposing the panel to untrusted users
- Review shell scripts before running them as root

## License

MIT
