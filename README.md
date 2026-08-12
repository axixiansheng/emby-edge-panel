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

## Install Master

```sh
git clone https://github.com/axixiansheng/emby-edge-panel.git
cd emby-edge-panel
export PANEL_PASSWORD='choose-a-strong-password'
export CF_API_TOKEN='cloudflare-api-token'
export CF_ZONE_ID='cloudflare-zone-id'
export BASE_DOMAIN='example.com'
export GLOBAL_SECRET_KEY='long-random-shared-secret'
export PANEL_NAME='My Emby Edge'
sudo -E ./install-master.sh
```

## Install Worker

```sh
git clone https://github.com/axixiansheng/emby-edge-panel.git
cd emby-edge-panel
export MASTER_IP='master-public-ip'
export SECRET_KEY='this-node-shared-secret'
sudo -E ./install-worker.sh
```

Use the same Worker `SECRET_KEY` when adding that node in the master panel.

## Public One-Command Download

Master, after exporting the required variables:

```sh
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz | tar -xz && cd emby-edge-panel-main && sudo -E ./install-master.sh
```

Worker, after exporting `MASTER_IP` and `SECRET_KEY`:

```sh
curl -fsSL https://github.com/axixiansheng/emby-edge-panel/archive/refs/heads/main.tar.gz | tar -xz && cd emby-edge-panel-main && sudo -E ./install-worker.sh
```

## NAT Workers

The Worker always listens internally on `12345`. If a provider maps public `54321` to internal `12345`, configure the master panel with the public host and port `54321`.

SSH mapping ports are unrelated to Worker service ports.

## Updating

Pull or download the latest source and run the relevant installer again. Installers back up existing application and Nginx directories before replacement. The master installer preserves an existing `panel.db`.

## Security

- Never commit `.env`, databases, API tokens, passwords, or SSH credentials
- Use a separate long random secret for every Worker
- Keep Worker clocks synchronized; requests with clock skew over 60 seconds are rejected
- Restrict Worker `/api/` to the master public IP
- Configure HTTPS before exposing the panel to untrusted users
- Review shell scripts before running them as root

## License

MIT
