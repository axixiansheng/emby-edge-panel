#!/bin/sh
set -eu

# Before running, set the shared key:
# export SECRET_KEY='replace-with-the-key-configured-for-this-node-in-master'
: "${SECRET_KEY:?SECRET_KEY must be set}"
: "${MASTER_IP:?MASTER_IP must be set}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AGENT_SOURCE="$SCRIPT_DIR/worker/agent.py"
if [ ! -f "$AGENT_SOURCE" ]; then
    echo "Missing $AGENT_SOURCE. Upload both files into the same directory." >&2
    exit 1
fi

apk update
apk add nginx python3 chrony

mkdir -p /opt/emby_agent /etc/nginx/http.d
cp "$AGENT_SOURCE" /opt/emby_agent/agent.py
chmod 750 /opt/emby_agent/agent.py
touch /etc/nginx/emby_url.map /etc/nginx/emby_sni.map
chmod 640 /etc/nginx/emby_url.map /etc/nginx/emby_sni.map

cat > /etc/nginx/http.d/default.conf <<'EOF'
map $host $target_url {
    default "";
    include /etc/nginx/emby_url.map;
}

map $host $target_sni {
    default "";
    include /etc/nginx/emby_sni.map;
}

server {
    listen 12345;
    listen [::]:12345;
    server_name _;
    resolver 8.8.8.8 1.1.1.1 valid=300s ipv6=off;

    location /api/ {
        allow __MASTER_IP__;
        deny all;
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        if ($target_url = "") { return 404 "Edge Node Target Not Found"; }
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_max_temp_file_size 0;
        proxy_force_ranges on;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
        proxy_set_header Host $target_sni;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto "https";
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_ssl_server_name on;
        proxy_ssl_name $target_sni;
        proxy_pass $target_url$request_uri;
    }
}
EOF
sed -i "s/__MASTER_IP__/$MASTER_IP/g" /etc/nginx/http.d/default.conf

cat > /opt/emby_agent/.env <<EOF
SECRET_KEY="$SECRET_KEY"
EOF
chmod 600 /opt/emby_agent/.env

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
depend() {
    need net
    after nginx chronyd
}
EOF
chmod +x /etc/init.d/emby-agent

rc-update add chronyd default
rc-update add nginx default
rc-update add emby-agent default
python3 -m py_compile /opt/emby_agent/agent.py
nginx -t
rc-service chronyd restart || rc-service chronyd start
rc-service nginx restart || rc-service nginx start
rc-service emby-agent restart || rc-service emby-agent start
rc-service emby-agent status
