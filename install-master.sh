#!/bin/sh
set -eu

: "${PANEL_PASSWORD:?PANEL_PASSWORD must be set}"
: "${CF_API_TOKEN:?CF_API_TOKEN must be set}"
: "${CF_ZONE_ID:?CF_ZONE_ID must be set}"
: "${BASE_DOMAIN:?BASE_DOMAIN must be set}"
: "${GLOBAL_SECRET_KEY:?GLOBAL_SECRET_KEY must be set}"
PANEL_NAME=${PANEL_NAME:-Emby Edge}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$SCRIPT_DIR/master/app.py" ] || { echo "Missing master/app.py" >&2; exit 1; }
[ -f "$SCRIPT_DIR/master/index.html" ] || { echo "Missing master/index.html" >&2; exit 1; }

if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx python3 curl
else
    echo "Master installer supports Debian/Ubuntu (apt)." >&2
    exit 1
fi

stamp=$(date +%Y%m%d-%H%M%S)
[ ! -d /opt/emby_panel ] || cp -a /opt/emby_panel "/opt/emby_panel.backup-$stamp"
cp -a /etc/nginx "/etc/nginx.backup-$stamp"

mkdir -p /opt/emby_panel/frontend /opt/emby_panel/db /etc/nginx/sites-available /etc/nginx/sites-enabled
install -m 0750 "$SCRIPT_DIR/master/app.py" /opt/emby_panel/app.py
install -m 0644 "$SCRIPT_DIR/master/index.html" /opt/emby_panel/frontend/index.html
touch /etc/nginx/emby_url.map /etc/nginx/emby_sni.map

cat > /opt/emby_panel/.env <<EOF
PANEL_PASSWORD="$PANEL_PASSWORD"
CF_API_TOKEN="$CF_API_TOKEN"
CF_ZONE_ID="$CF_ZONE_ID"
BASE_DOMAIN="$BASE_DOMAIN"
GLOBAL_SECRET_KEY="$GLOBAL_SECRET_KEY"
PANEL_NAME="$PANEL_NAME"
EOF
chmod 600 /opt/emby_panel/.env

cat > /etc/nginx/sites-available/emby-panel <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $BASE_DOMAIN www.$BASE_DOMAIN _;
    port_in_redirect off;
    server_name_in_redirect off;
    location / {
        alias /opt/emby_panel/frontend/;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

cat > /etc/systemd/system/emby-panel.service <<'EOF'
[Unit]
Description=Emby Edge Master Panel
After=network-online.target nginx.service
Wants=network-online.target
[Service]
WorkingDirectory=/opt/emby_panel
ExecStart=/usr/bin/python3 /opt/emby_panel/app.py
Restart=always
RestartSec=2
User=root
[Install]
WantedBy=multi-user.target
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/emby-panel /etc/nginx/sites-enabled/emby-panel
python3 -m py_compile /opt/emby_panel/app.py
nginx -t
systemctl daemon-reload
systemctl enable --now nginx emby-panel
systemctl restart nginx emby-panel
sleep 2
curl -fsS http://127.0.0.1/ >/dev/null
systemctl is-active --quiet nginx
systemctl is-active --quiet emby-panel
echo "Master installed: http://$(hostname -I | awk '{print $1}')/"
