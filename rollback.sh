#!/bin/sh
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
BACKUP=${1:?Usage: sh rollback.sh /opt/emby-backups/upgrade-TIMESTAMP}
BACKUP=$(readlink -f "$BACKUP")
case "$BACKUP" in /opt/emby-backups/upgrade-*) ;; *) echo "Invalid backup path" >&2; exit 1 ;; esac
[ -f "$BACKUP/deployment.tar.gz" ] || { echo "Backup not found" >&2; exit 1; }
python3 -c 'import argon2' || { echo "Missing legacy password compatibility dependency: python3-argon2" >&2; exit 1; }
check_operations() {
python3 - <<'PY'
import sqlite3
with sqlite3.connect("file:/opt/emby_panel/db/panel.db?mode=ro", uri=True) as db:
    has_ops = db.execute("SELECT 1 FROM sqlite_master WHERE name='operations'").fetchone()
    if has_ops and db.execute("SELECT COUNT(*) FROM operations WHERE status IN ('pending','running')").fetchone()[0]:
        raise SystemExit("Unfinished operations exist; complete or repair them before rolling back.")
PY
}
check_operations
# Preserve all current users; a code rollback does NOT restore an older database.
docker stop --time 45 emby-edge-panel
if ! check_operations; then
    docker start emby-edge-panel >/dev/null
    exit 1
fi
if [ -f "$BACKUP/previous-image" ]; then
    docker tag "$(cat "$BACKUP/previous-image")" emby-edge-panel:2.0.0
    docker rm emby-edge-panel >/dev/null
    docker compose -f "$BACKUP/compose.yaml" up -d --no-build
    tar -xzf "$BACKUP/deployment.tar.gz" -C / etc/nginx
    nginx -t
    systemctl reload nginx
    echo "Previous Docker release restored; current user data preserved."
    exit 0
fi
[ -f "$BACKUP/emby-panel.service" ] || { echo "Legacy service backup missing" >&2; docker start emby-edge-panel; exit 1; }
tar -xzf "$BACKUP/deployment.tar.gz" -C /opt emby_panel/app.py emby_panel/frontend
python3 "$ROOT/tools/prepare_legacy_rollback.py" /opt/emby_panel/app.py "$ROOT/master/security.py"
tar -xzf "$BACKUP/deployment.tar.gz" -C / etc/nginx
cp "$BACKUP/emby-panel.service" /etc/systemd/system/emby-panel.service
systemctl daemon-reload
systemctl enable --now emby-panel
if ! curl -fsS http://127.0.0.1:8080/queue/status?ticket=rollback >/dev/null; then
    systemctl stop emby-panel
    docker start emby-edge-panel
    echo "Legacy service failed; container restarted" >&2
    exit 1
fi
nginx -t
systemctl reload nginx
docker update --restart=no emby-edge-panel >/dev/null
echo "Legacy code restored. Current users, codes, routes and sessions were preserved."
