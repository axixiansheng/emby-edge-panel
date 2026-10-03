#!/bin/sh
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
docker compose version >/dev/null
[ -s /opt/emby_panel/.env ] || { echo "Run install-master.sh to configure the master first" >&2; exit 1; }
docker compose -f "$ROOT/compose.yaml" config --quiet
IMAGE=$(docker compose -f "$ROOT/compose.yaml" config --images)
if ! python3 -c 'import argon2' >/dev/null 2>&1; then
    # Ensure native rollback can authenticate users created by the new container.
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-argon2
fi
STAMP=$(date -u +%Y%m%d-%H%M%S)
BACKUP=/opt/emby-backups/upgrade-$STAMP
mkdir -p "$BACKUP" /opt/emby_panel/db
export BACKUP
cp "$ROOT/compose.yaml" "$BACKUP/compose.yaml"
python3 - <<'PY'
import os, sqlite3
source = "/opt/emby_panel/db/panel.db"
if os.path.exists(source):
    with sqlite3.connect(source) as db, sqlite3.connect(os.environ["BACKUP"] + "/panel.db") as out:
        db.backup(out)
        assert out.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
PY
tar -czf "$BACKUP/deployment.tar.gz" --exclude=emby_panel/db --exclude=emby_panel/releases \
    -C /opt emby_panel -C / etc/nginx
if [ -f /etc/systemd/system/emby-panel.service ]; then
    cp -a /etc/systemd/system/emby-panel.service "$BACKUP/emby-panel.service"
fi
if docker inspect emby-edge-panel >/dev/null 2>&1; then
    docker inspect --format '{{.Image}}' emby-edge-panel > "$BACKUP/previous-image"
    docker tag "$(cat "$BACKUP/previous-image")" "emby-edge-panel:backup-$STAMP"
    previous_compose=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' emby-edge-panel)
    [ ! -f "$previous_compose" ] || cp "$previous_compose" "$BACKUP/compose.yaml"
fi
docker compose -f "$ROOT/compose.yaml" build

# A disposable copy prevents preflight migrations or requests touching live user data.
mkdir "$BACKUP/preflight"
[ ! -f "$BACKUP/panel.db" ] || cp "$BACKUP/panel.db" "$BACKUP/preflight/panel.db"
CANDIDATE=emby-edge-preflight-$STAMP
cleanup() { docker rm -f "$CANDIDATE" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
docker run -d --name "$CANDIDATE" --env-file /opt/emby_panel/.env \
    -e EMBY_BACKGROUND=0 -e EMBY_DB_FILE=/data/panel.db \
    -v "$BACKUP/preflight:/data" -p 127.0.0.1::8080 \
    --memory=192m --cpus=1 --cap-drop=ALL --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:size=16m \
    --user 0:0 "$IMAGE" >/dev/null
PORT=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8080/tcp") 0).HostPort}}' "$CANDIDATE")
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then ready=1; break; fi
    sleep 1
done
[ "$ready" -eq 1 ] || { docker logs "$CANDIDATE"; exit 1; }
curl -fsS "http://127.0.0.1:$PORT/assets/panel.js" >/dev/null
docker exec "$CANDIDATE" python -c 'from master.config import Config; from master.database import Database; from master.service import Service; from master.integrations import Integrations; c=Config.load(); s=Service(c,Database(c.db_file),Integrations(c)); b=s.backups.export(); s.backups.validate(b); print("Portable backup validation passed:", {k:len(v) for k,v in b["data"].items()})'
cleanup

python3 - <<'PY'
import re
from pathlib import Path
old = """        alias /opt/emby_panel/frontend/;
        index index.html;
        try_files $uri $uri/ /index.html;"""
new = """        proxy_pass http://127.0.0.1:8080;
        proxy_read_timeout 30s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"""
for name in ("emby-panel", "emby-panel-https"):
    path = Path("/etc/nginx/sites-available") / name
    if path.exists():
        content = path.read_text()
        if "alias /opt/emby_panel/frontend/" in content and old not in content:
            raise SystemExit("Unrecognized panel Nginx layout; review before deploying")
        content = content.replace(old, new)
        if "client_max_body_size" in content:
            content = re.sub(r"client_max_body_size\s+[^;]+;", "client_max_body_size 9m;", content)
        else:
            content = re.sub(r"(server_name\s+[^;]+;)", r"\1\n    client_max_body_size 9m;", content)
        path.write_text(content)
PY
restore_nginx() {
    python3 "$ROOT/tools/restore_panel_nginx.py" "$BACKUP/deployment.tar.gz"
}
if ! nginx -t; then restore_nginx; exit 1; fi

legacy=0
systemctl is-active --quiet emby-panel && legacy=1 || true
rollback() {
    docker rm -f emby-edge-panel >/dev/null 2>&1 || true
    restore_nginx
    if [ -f "$BACKUP/previous-image" ]; then
        previous_image=$(docker compose -f "$BACKUP/compose.yaml" config --images)
        docker tag "$(cat "$BACKUP/previous-image")" "$previous_image"
        docker compose -f "$BACKUP/compose.yaml" up -d --no-build
    elif [ "$legacy" -eq 1 ]; then
        systemctl enable --now emby-panel
    fi
    nginx -t && systemctl reload nginx || true
    echo "Upgrade failed; previous service restarted. Backup: $BACKUP" >&2
}
systemctl stop emby-panel 2>/dev/null || true
if ! docker compose -f "$ROOT/compose.yaml" up -d --no-build; then rollback; exit 1; fi
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS http://127.0.0.1:8080/healthz >/dev/null; then ready=1; break; fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then rollback; exit 1; fi
if ! systemctl reload nginx; then rollback; exit 1; fi
systemctl disable emby-panel 2>/dev/null || true
echo "Master upgraded. Database preserved at /opt/emby_panel/db/panel.db"
echo "Backup: $BACKUP"
