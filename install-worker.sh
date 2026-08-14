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

show_worker_status() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --no-pager --full status nginx 2>/dev/null || true
        systemctl --no-pager --full status emby-agent 2>/dev/null || true
        systemctl --no-pager --full status emby-cert-sync.timer 2>/dev/null || true
    elif command -v rc-service >/dev/null 2>&1; then
        rc-service nginx status 2>/dev/null || true
        rc-service emby-agent status 2>/dev/null || true
    else
        echo '当前系统未检测到受支持的服务管理器。'
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -lntp 2>/dev/null | grep -E ':(12345|12346|12347|8081)[[:space:]]' || true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -lnt 2>/dev/null | grep -E ':(12345|12346|12347|8081)[[:space:]]' || true
    fi
}

SECRET_KEY=${SECRET_KEY:-$(read_existing_value SECRET_KEY)}
MASTER_IP=${MASTER_IP:-$(read_existing_value MASTER_IP)}
NODE_ID=${NODE_ID:-$(read_existing_value NODE_ID)}

if [ -t 0 ]; then
    while :; do
        printf '\n=== Emby Edge Worker HTTPS 安装配置 ===\n'
        printf '1. 主控公网 IP: %s\n' "${MASTER_IP:-未设置}"
        printf '2. 节点共享密钥: %s\n' "$(is_set "$SECRET_KEY")"
        printf '3. 开始安装（基础域名和 HTTPS 证书由主控自动下发）\n'
        printf '4. 查看 Worker 服务状态\n0. 退出\n请选择 [0-4]: '
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
            4)
                show_worker_status
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

if command -v apk >/dev/null 2>&1; then
    WORKER_PLATFORM=alpine
    apk update
    apk add nginx nginx-mod-stream python3 py3-cryptography chrony
    HTTP_CONF=/etc/nginx/http.d/default.conf
elif command -v apt-get >/dev/null 2>&1; then
    WORKER_PLATFORM=debian
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx libnginx-mod-stream python3 python3-cryptography chrony iproute2
    HTTP_CONF=/etc/nginx/conf.d/emby-worker.conf
else
    echo 'Worker 安装器仅支持 Alpine、Debian 和 Ubuntu。' >&2
    exit 1
fi

stamp=$(date +%Y%m%d-%H%M%S)
STREAM_INCLUDE_MANAGED=0
[ ! -f /opt/emby_agent/.stream_include_added ] || STREAM_INCLUDE_MANAGED=1
[ ! -d /opt/emby_agent ] || cp -a /opt/emby_agent "/opt/emby_agent.backup-$stamp"
cp -a /etc/nginx "/etc/nginx.backup-emby-worker-$stamp"

mkdir -p /opt/emby_agent "$(dirname "$HTTP_CONF")" /etc/nginx/stream.d /etc/ssl/emby
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

cat > "$HTTP_CONF" <<EOF
map \$host \$target_url {
    default "";
    include /etc/nginx/emby_url.map;
}
map \$host \$target_sni {
    default "";
    include /etc/nginx/emby_sni.map;
}
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
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

# Debian requires stream configuration to be nested in a stream{} context.
# Remove the direct include written by the previous failed Worker installer,
# then install a marked, removable stream block.
if [ "$STREAM_INCLUDE_MANAGED" -eq 1 ]; then
    sed -i '/# Emby Edge managed stream include/{N;N;N;d;}' /etc/nginx/nginx.conf
    nginx_tmp=$(mktemp)
    awk 'index($0, "include /etc/nginx/stream.d/*.conf;") == 0' /etc/nginx/nginx.conf > "$nginx_tmp"
    cat "$nginx_tmp" > /etc/nginx/nginx.conf
    rm -f "$nginx_tmp"
fi
if ! grep -RqsF 'include /etc/nginx/stream.d/*.conf;' /etc/nginx/nginx.conf /etc/nginx/modules-enabled 2>/dev/null; then
    cat >> /etc/nginx/nginx.conf <<'EOF'

# Emby Edge managed stream include
stream {
    include /etc/nginx/stream.d/*.conf;
}
EOF
    STREAM_INCLUDE_MANAGED=1
fi
[ "$STREAM_INCLUDE_MANAGED" -eq 0 ] || touch /opt/emby_agent/.stream_include_added

printf 'BASE_DOMAIN="%s"\n' "$BASE_DOMAIN" >> "$WORKER_ENV"

if [ "$WORKER_PLATFORM" = alpine ]; then
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
else
cat > /etc/systemd/system/emby-agent.service <<'EOF'
[Unit]
Description=Emby Edge Worker Agent
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/emby_agent
ExecStart=/usr/bin/python3 /opt/emby_agent/agent.py
Restart=always
RestartSec=2
User=root

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/emby-cert-sync.service <<'EOF'
[Unit]
Description=Synchronize Emby Edge Worker certificate
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/emby_agent/cert_sync.py
EOF

cat > /etc/systemd/system/emby-cert-sync.timer <<'EOF'
[Unit]
Description=Daily Emby Edge Worker certificate synchronization

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable nginx emby-agent emby-cert-sync.timer
fi

python3 -m py_compile /opt/emby_agent/agent.py
python3 -m py_compile /opt/emby_agent/cert_sync.py
nginx -t

if [ "$WORKER_PLATFORM" = alpine ] && rc-service chronyd restart 2>/tmp/emby-chrony-error.log; then
    rc-update add chronyd default >/dev/null 2>&1 || true
    echo 'Chrony 已启动，系统时间会自动同步。'
elif [ "$WORKER_PLATFORM" = debian ] && systemctl enable --now chrony 2>/tmp/emby-chrony-error.log; then
    echo 'Chrony 已启动，系统时间会自动同步。'
else
    if [ "$WORKER_PLATFORM" = alpine ]; then
        rc-service chronyd stop >/dev/null 2>&1 || true
        rc-update del chronyd default >/dev/null 2>&1 || true
    else
        systemctl disable --now chrony >/dev/null 2>&1 || true
    fi
    echo '警告：当前虚拟化环境不允许 Chrony 调整系统时间，已跳过。' >&2
    echo 'Worker 仍会继续安装，但节点 UTC 时间必须由宿主机保持准确（误差不超过 60 秒）。' >&2
fi
rm -f /tmp/emby-chrony-error.log

if [ "$WORKER_PLATFORM" = alpine ]; then
    rc-service nginx restart || rc-service nginx start
    rc-service emby-agent restart || rc-service emby-agent start
    rc-service crond restart || rc-service crond start || true
else
    systemctl restart nginx
    systemctl restart emby-agent
    systemctl start emby-cert-sync.timer
fi
show_worker_status

echo "Worker HTTPS 安装完成。"
echo "内部服务端口: 12345（HTTP/HTTPS 自动分流）"
echo "证书由主控统一签发和更新。"
echo "NAT 节点请把服务商分配的任意公网端口映射到内部 12345，并在主控节点配置中填写该实际公网端口。"
