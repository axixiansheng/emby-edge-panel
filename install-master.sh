#!/bin/sh
set -eu

PANEL_PASSWORD=${PANEL_PASSWORD:-}
CF_API_TOKEN=${CF_API_TOKEN:-}
CF_ZONE_ID=${CF_ZONE_ID:-}
BASE_DOMAIN=${BASE_DOMAIN:-}
GLOBAL_SECRET_KEY=${GLOBAL_SECRET_KEY:-}
PANEL_NAME=${PANEL_NAME:-Emby Edge}

is_set() { [ -n "$1" ] && printf '已设置' || printf '未设置'; }
prompt_value() {
    label=$1
    current=$2
    printf '%s' "$label"
    [ -z "$current" ] || printf ' [%s]' "$current"
    printf ': '
    IFS= read -r answer
    [ -z "$answer" ] && answer=$current
    printf '%s' "$answer"
}
prompt_secret() {
    label=$1
    current=$2
    printf '%s' "$label"
    [ -z "$current" ] || printf ' [直接回车保留当前值]'
    printf ': '
    stty -echo 2>/dev/null || true
    IFS= read -r answer
    stty echo 2>/dev/null || true
    printf '\n'
    [ -z "$answer" ] && answer=$current
    printf '%s' "$answer"
}
show_menu() {
    printf '\n=== Emby Edge 主控安装配置 ===\n'
    printf '1. 面板管理员密码: %s\n' "$(is_set "$PANEL_PASSWORD")"
    printf '2. Cloudflare API Token: %s\n' "$(is_set "$CF_API_TOKEN")"
    printf '3. Cloudflare Zone ID: %s\n' "$(is_set "$CF_ZONE_ID")"
    printf '4. 基础域名: %s\n' "${BASE_DOMAIN:-未设置}"
    printf '5. Worker 全局共享密钥: %s\n' "$(is_set "$GLOBAL_SECRET_KEY")"
    printf '6. 面板名称: %s\n' "$PANEL_NAME"
    printf '7. 开始安装\n'
    printf '0. 退出\n'
}

if [ -t 0 ]; then
    while :; do
        show_menu
        printf '请选择 [0-7]: '
        IFS= read -r choice
        case "$choice" in
            1) PANEL_PASSWORD=$(prompt_secret '请输入面板管理员密码' "$PANEL_PASSWORD") ;;
            2) CF_API_TOKEN=$(prompt_secret '请输入 Cloudflare API Token' "$CF_API_TOKEN") ;;
            3) CF_ZONE_ID=$(prompt_value '请输入 Cloudflare Zone ID' "$CF_ZONE_ID") ;;
            4) BASE_DOMAIN=$(prompt_value '请输入基础域名（不含协议）' "$BASE_DOMAIN") ;;
            5) GLOBAL_SECRET_KEY=$(prompt_secret '请输入 Worker 全局共享密钥' "$GLOBAL_SECRET_KEY") ;;
            6) PANEL_NAME=$(prompt_value '请输入面板名称' "$PANEL_NAME") ;;
            7)
                if [ -z "$PANEL_PASSWORD" ] || [ -z "$CF_API_TOKEN" ] || [ -z "$CF_ZONE_ID" ] || [ -z "$BASE_DOMAIN" ] || [ -z "$GLOBAL_SECRET_KEY" ]; then
                    echo '仍有必填配置未设置。'
                else
                    break
                fi
                ;;
            0) exit 0 ;;
            *) echo '无效选项。' ;;
        esac
    done
else
    : "${PANEL_PASSWORD:?PANEL_PASSWORD must be set in non-interactive mode}"
    : "${CF_API_TOKEN:?CF_API_TOKEN must be set in non-interactive mode}"
    : "${CF_ZONE_ID:?CF_ZONE_ID must be set in non-interactive mode}"
    : "${BASE_DOMAIN:?BASE_DOMAIN must be set in non-interactive mode}"
    : "${GLOBAL_SECRET_KEY:?GLOBAL_SECRET_KEY must be set in non-interactive mode}"
fi

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

# Disable known legacy/default Emby site links. The full Nginx directory was
# backed up above, so these links can be restored from the timestamped backup.
rm -f \
    /etc/nginx/sites-enabled/default \
    /etc/nginx/sites-enabled/emby-panel-http \
    /etc/nginx/sites-enabled/emby-panel
ln -sfn /etc/nginx/sites-available/emby-panel /etc/nginx/sites-enabled/emby-panel
python3 -m py_compile /opt/emby_panel/app.py
if ! nginx_output=$(nginx -t 2>&1); then
    printf '%s\n' "$nginx_output" >&2
    echo "Nginx configuration failed. Check enabled sites with:" >&2
    echo "  grep -RIn 'listen .*default_server' /etc/nginx/sites-enabled /etc/nginx/conf.d" >&2
    echo "Backup: /etc/nginx.backup-$stamp" >&2
    exit 1
fi
systemctl daemon-reload
systemctl enable --now nginx emby-panel
systemctl restart nginx emby-panel
sleep 2
curl -fsS http://127.0.0.1/ >/dev/null
systemctl is-active --quiet nginx
systemctl is-active --quiet emby-panel
echo "Master installed: http://$(hostname -I | awk '{print $1}')/"
