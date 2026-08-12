# Emby Edge Panel

Lightweight Emby reverse-proxy control panel with one master and multiple Worker nodes.

## Architecture

- Master: Debian/Ubuntu, Nginx on port 80 and Python API on `127.0.0.1:8080`.
- Worker: Alpine Linux, Nginx on internal port `12345` and Agent on `127.0.0.1:8081`.
- NAT Worker: map a public service port (for example `54321`) to internal port `12345`; enter the public port in the panel.

## Install Master

```sh
git clone https://github.com/axixiansheng/emby-edge-panel.git
cd emby-edge-panel
export PANEL_PASSWORD='replace-me'
export CF_API_TOKEN='replace-me'
export CF_ZONE_ID='replace-me'
export BASE_DOMAIN='example.com'
export GLOBAL_SECRET_KEY='replace-me'
sudo -E ./install-master.sh
```

## Install Worker

```sh
git clone https://github.com/axixiansheng/emby-edge-panel.git
cd emby-edge-panel
export MASTER_IP='master-public-ip'
export SECRET_KEY='node-shared-secret'
sudo -E ./install-worker.sh
```

Configure the same Worker secret in the master panel. For NAT servers, configure the provider mapping from the public port to internal `12345`, then enter the public port in the panel.

## Security

- Do not commit `.env`, database files, API tokens, passwords, or SSH credentials.
- Keep Worker clocks synchronized. Requests with clock skew over 60 seconds are rejected.
- Worker `/api/` is restricted to `MASTER_IP` by Nginx and protected with HMAC signatures.
- Use HTTPS on the master before exposing it to untrusted users.

## Updating

Pull the latest code and run the installer again. Existing databases and Nginx configurations are backed up before replacement.
