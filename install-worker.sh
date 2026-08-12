#!/bin/sh
set -eu

WORKER_ENV=/opt/emby_agent/.env

read_existing_value() {
    key=$1
    [ -f "$WORKER_ENV" ] || return 0
    awk -v wanted="$key" '
        index($0, wanted "=") == 1 {
            value = substr($0, length(wanted) + 2)
            sub(/^[[:space:]]+/, "", value)
            sub(/[[:space:]]+$/, "", value)
            if ((substr(value, 1, 1) == "\"" && substr(value, length(value), 1) == "\"") ||
                (substr(value, 1, 1) == "\047" && substr(value, length(value), 1) == "\047")) {
                value = substr(value, 2, length(value) - 2)
            }
            print value
            exit
        }
    ' "$WORKER_ENV"
}

is_set() { [ -n "$1" ] && printf '已设置' || printf '未设置'; }
prompt_value() {
    label=$1
    current=$2
    printf '%s' "$label" >&2
    [ -z "$current" ] || printf ' [%s]' "$current" >&2
    printf ': ' >&2
    IFS= read -r answer
    [ -z "$answer" ] && answer=$current
    printf '%s' "$answer"
}
prompt_secret() {
    label=$1
    current=$2
    printf '%s' "$label" >&2
    [ -z "$current" ] || printf ' [直接回车保留当前值]' >&2
    printf ': ' >&2
    stty -echo 2>/dev/null || true
    IFS= read -r answer
    stty echo 2>/dev/null || true
    printf '\n' >&2
    [ -z "$answer" ] && answer=$current
    printf '%s' "$answer"
}

SECRET_KEY=${SECRET_KEY:-$(read_existing_value SECRET_KEY)}
MASTER_IP=${MASTER_IP:-$(read_existing_value MASTER_IP)}
NODE_ID=${NODE_ID:-$(read_existing_value NODE_ID)}

if [ -t 0 ]; then
    while :; do
        printf '\n=== Emby Edge Worker HTTPS 安装配置 ===\n'
        printf '1. 主控公网 IP: %s\n' "${MASTER_IP:-未设置}"
        printf '2. 节点共享密钥: %s\n' "$(is_set "$SECRET_KEY")"
        printf '3. 开始安装（基础域名和 HTTPS 证书由主控自动下发）\n0. 退出\n请选择 [0-3]: '
        IFS= read -r choice
        case "$choice" in
            1) MASTER_IP=$(prompt_value '请输入主控公网 IP' "$MASTER_IP") ;;
            2) SECRET_KEY=$(prompt_secret '请输入节点共享密钥' "$SECRET_KEY") ;;
            3)
                if [ -z "$MASTER_IP" ] || [ -z "$SECRET_KEY" ]; then
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
    : "${SECRET_KEY:?SECRET_KEY must be set in non-interactive mode}"
    : "${MASTER_IP:?MASTER_IP must be set in non-interactive mode}"
fi
case "$MASTER_IP" in
    ''|*[!0-9a-fA-F:.]*) echo '主控公网 IP 格式无效。' >&2; exit 1 ;;
esac

if [ -z "$NODE_ID" ]; then
    host_part=$(hostname 2>/dev/null | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9-]/-/g; s/^-*//; s/-*$//' | cut -c1-24)
    random_part=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
    NODE_ID="${host_part:-worker}-$random_part"
else
    NODE_ID=$(printf '%s' "$NODE_ID" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9-]/-/g; s/^-*//; s/-*$//' | cut -c1-40)
fi
[ -n "$NODE_ID" ] || { echo '节点证书标识无效。' >&2; exit 1; }

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AGENT_SOURCE="$SCRIPT_DIR/worker/agent.py"
CERT_SYNC_SOURCE="$SCRIPT_DIR/worker/cert_sync.py"
[ -f "$AGENT_SOURCE" ] && [ -f "$CERT_SYNC_SOURCE" ] || { echo "Missing Worker source files" >&2; exit 1; }

apk update
apk add nginx nginx-mod-stream python3 py3-cryptography chrony

stamp=$(date +%Y%m%d-%H%M%S)
[ ! -d /opt/emby_agent ] || cp -a /opt/emby_agent "/opt/emby_agent.backup-$stamp"
cp -a /etc/nginx "/etc/nginx.backup-emby-worker-$stamp"

mkdir -p /opt/emby_agent /etc/nginx/http.d /etc/nginx/stream.d /etc/ssl/emby
cp "$AGENT_SOURCE" /opt/emby_agent/agent.py
cp "$CERT_SYNC_SOURCE" /opt/emby_agent/cert_sync.py
chmod 750 /opt/emby_agent/agent.py
chmod 750 /opt/emby_agent/cert_sync.py
touch /etc/nginx/emby_url.map /etc/nginx/emby_sni.map
chmod 640 /etc/nginx/emby_url.map /etc/nginx/emby_sni.map

cat > "$WORKER_ENV" <<EOF
SECRET_KEY="$SECRET_KEY"
MASTER_IP="$MASTER_IP"
NODE_ID="$NODE_ID"
EOF
chmod 600 "$WORKER_ENV"
BASE_DOMAIN=$(python3 /opt/emby_agent/cert_sync.py)

cat > /etc/nginx/http.d/default.conf <<EOF
map \$host \$target_url {
    default "";
    include /etc/nginx/emby_url.map;
}
map \$host \$target_sni {
    default "";
    include /etc/nginx/emby_sni.map;
}

server {
    listen 127.0.0.1:12346 proxy_protocol;
    server_name _;
    set_real_ip_from 127.0.0.1;
    real_ip_header proxy_protocol;
    resolver 8.8.8.8 1.1.1.1 valid=300s ipv6=off;

    location /api/ {
        allow $MASTER_IP;
        deny all;
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location / {
        if (\$target_url = "") { return 404 "Edge Node Target Not Found"; }
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_max_temp_file_size 0;
        proxy_force_ranges on;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
        proxy_set_header Host \$target_sni;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto "http";
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Range \$http_range;
        proxy_set_header If-Range \$http_if_range;
        proxy_ssl_server_name on;
        proxy_ssl_name \$target_sni;
        proxy_pass \$target_url\$request_uri;
    }
}

server {
    listen 127.0.0.1:12347 ssl proxy_protocol;
    server_name *.$BASE_DOMAIN;
    set_real_ip_from 127.0.0.1;
    real_ip_header proxy_protocol;
    ssl_certificate /etc/ssl/emby/fullchain.pem;
    ssl_certificate_key /etc/ssl/emby/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    resolver 8.8.8.8 1.1.1.1 valid=300s ipv6=off;

    location / {
        if (\$target_url = "") { return 404 "Edge Node Target Not Found"; }
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_max_temp_file_size 0;
        proxy_force_ranges on;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
        proxy_set_header Host \$target_sni;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto "https";
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Range \$http_range;
        proxy_set_header If-Range \$http_if_range;
        proxy_ssl_server_name on;
        proxy_ssl_name \$target_sni;
        proxy_pass \$target_url\$request_uri;
    }
}
EOF

rm -f /etc/nginx/conf.d/emby-stream.conf
cat > /etc/nginx/stream.d/emby.conf <<'EOF'
map $ssl_preread_protocol $emby_backend {
    ""      127.0.0.1:12346;
    default 127.0.0.1:12347;
}
server {
    listen 12345;
    listen [::]:12345;
    proxy_pass $emby_backend;
    proxy_protocol on;
    ssl_preread on;
    proxy_connect_timeout 10s;
    proxy_timeout 3600s;
}
EOF

printf 'BASE_DOMAIN="%s"\n' "$BASE_DOMAIN" >> "$WORKER_ENV"

cat > /etc/init.d/emby-agent <<'EOF'
#!/sbin/openrc-run
name="emby-agent"
description="Emby Worker Agent V3"
command="/usr/bin/python3"
command_args="/opt/emby_agent/agent.py"
command_background=true
pidfile="/run/emby-agent.pid"
output_log="/var/log/emby-agent.log"
error_log="/var/log/emby-agent.err"
depend() { need net; after nginx; }
EOF
chmod +x /etc/init.d/emby-agent

mkdir -p /etc/periodic/daily
cat > /etc/periodic/daily/emby-cert-sync <<'EOF'
#!/bin/sh
/usr/bin/python3 /opt/emby_agent/cert_sync.py >/dev/null
EOF
chmod 700 /etc/periodic/daily/emby-cert-sync

rc-update add nginx default
rc-update add emby-agent default
rc-update add crond default >/dev/null 2>&1 || true
python3 -m py_compile /opt/emby_agent/agent.py
nginx -t

if rc-service chronyd restart 2>/tmp/emby-chrony-error.log; then
    rc-update add chronyd default >/dev/null 2>&1 || true
    echo 'Chrony 已启动，系统时间会自动同步。'
else
    rc-service chronyd stop >/dev/null 2>&1 || true
    rc-update del chronyd default >/dev/null 2>&1 || true
    echo '警告：当前虚拟化环境不允许 Chrony 调整系统时间，已跳过。' >&2
    echo 'Worker 仍会继续安装，但节点 UTC 时间必须由宿主机保持准确（误差不超过 60 秒）。' >&2
fi
rm -f /tmp/emby-chrony-error.log

rc-service nginx restart || rc-service nginx start
rc-service emby-agent restart || rc-service emby-agent start
rc-service crond restart || rc-service crond start || true
rc-service nginx status
rc-service emby-agent status

echo "Worker HTTPS 安装完成。"
echo "内部服务端口: 12345（HTTP/HTTPS 自动分流）"
echo "证书由主控统一签发和更新。"
echo "NAT 节点仍需把公网服务端口映射到内部 12345。"
