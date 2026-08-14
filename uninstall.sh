#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

confirm() {
    printf '%s [y/N]: ' "$1"
    IFS= read -r answer
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

master_exists() {
    [ -d /opt/emby_panel ] || [ -f /etc/systemd/system/emby-panel.service ] || \
    [ -e /etc/nginx/sites-enabled/emby-panel ] || [ -f /etc/nginx/sites-available/emby-panel ]
}

worker_exists() {
    [ -d /opt/emby_agent ] || [ -f /etc/init.d/emby-agent ] || \
    [ -f /etc/systemd/system/emby-agent.service ] || [ -f /etc/nginx/stream.d/emby.conf ] || [ -d /etc/ssl/emby ]
}

cleanup_project_if_unused() {
    if ! master_exists && ! worker_exists; then
        case "$PROJECT_DIR" in
            /|/root|/home|/opt|'') echo '拒绝删除不安全的项目路径。' >&2; return 1 ;;
        esac
        echo "主控和 Worker 均已不存在，将删除项目目录: $PROJECT_DIR"
        (sleep 1; rm -rf -- "$PROJECT_DIR") >/dev/null 2>&1 &
    fi
}

remove_master() {
    echo '正在彻底移除主控服务...'
    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now emby-panel 2>/dev/null || true
        rm -f /etc/systemd/system/emby-panel.service
        systemctl daemon-reload 2>/dev/null || true
    fi
    if [ -d /opt/emby_panel ] && confirm '是否在删除前备份 panel.db？'; then
        save_dir="/root/emby-panel-data-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$save_dir"
        [ ! -f /opt/emby_panel/db/panel.db ] || cp -a /opt/emby_panel/db/panel.db* "$save_dir/"
        echo "数据库已保存到 $save_dir"
    fi
    rm -rf /opt/emby_panel /opt/emby_panel.backup-* /opt/emby_panel.pre-*
    rm -f /etc/nginx/sites-enabled/emby-panel /etc/nginx/sites-enabled/emby-panel-http /etc/nginx/sites-enabled/emby-panel-https
    rm -f /etc/nginx/sites-available/emby-panel /etc/nginx/sites-available/emby-panel-http /etc/nginx/sites-available/emby-panel-https
    rm -f /etc/cron.daily/emby-edge-cert-renew /root/.secrets/emby-cloudflare.ini
    rm -rf /etc/letsencrypt/live/emby-edge-wildcard /etc/letsencrypt/archive/emby-edge-wildcard
    rm -f /etc/letsencrypt/renewal/emby-edge-wildcard.conf
    rm -f /var/log/emby-panel.log /var/log/emby-panel.err
    rmdir /root/.secrets 2>/dev/null || true
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
        systemctl reload nginx 2>/dev/null || true
    fi
}

remove_worker() {
    echo '正在彻底移除 Worker 服务...'
    stream_include_added=0
    [ ! -f /opt/emby_agent/.stream_include_added ] || stream_include_added=1
    if command -v rc-service >/dev/null 2>&1; then
        rc-service emby-agent stop 2>/dev/null || true
        rc-update del emby-agent default 2>/dev/null || true
    fi
    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now emby-agent emby-cert-sync.timer 2>/dev/null || true
        rm -f /etc/systemd/system/emby-agent.service /etc/systemd/system/emby-cert-sync.service /etc/systemd/system/emby-cert-sync.timer
        systemctl daemon-reload 2>/dev/null || true
    fi
    pkill -f '/opt/emby_agent/agent.py' 2>/dev/null || true
    rm -f /etc/init.d/emby-agent
    rm -rf /opt/emby_agent /opt/emby_agent.backup-* /opt/emby_agent.pre-*
    rm -f /etc/nginx/http.d/default.conf /etc/nginx/conf.d/emby-worker.conf /etc/nginx/stream.d/emby.conf /etc/nginx/conf.d/emby-stream.conf
    if [ "$stream_include_added" -eq 1 ] && [ -f /etc/nginx/nginx.conf ]; then
        sed -i '/# Emby Edge managed stream include/{N;N;N;d;}' /etc/nginx/nginx.conf
        nginx_tmp=$(mktemp)
        awk 'index($0, "include /etc/nginx/stream.d/*.conf;") == 0' /etc/nginx/nginx.conf > "$nginx_tmp"
        cat "$nginx_tmp" > /etc/nginx/nginx.conf
        rm -f "$nginx_tmp"
    fi
    rm -f /etc/nginx/emby_url.map /etc/nginx/emby_sni.map
    rm -f /etc/periodic/daily/emby-cert-renew /etc/periodic/daily/emby-cert-sync
    rm -rf /etc/ssl/emby
    rm -f /var/log/emby-agent.log /var/log/emby-agent.err
    rm -rf /etc/nginx.backup-emby-worker-* /etc/nginx.pre-emby-worker-*
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
        if command -v systemctl >/dev/null 2>&1; then
            systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
        else
            rc-service nginx reload 2>/dev/null || rc-service nginx restart 2>/dev/null || true
        fi
    fi
}

printf '=== Emby Edge 卸载程序 ===\n'
printf '检测结果：主控=%s，Worker=%s\n' "$(master_exists && echo 已安装 || echo 未安装)" "$(worker_exists && echo 已安装 || echo 未安装)"
printf '1. 卸载主控\n2. 卸载 Worker\n3. 卸载主控和 Worker\n4. 查看服务状态\n0. 退出\n请选择 [0-4]: '
IFS= read -r choice
case "$choice" in
    1) confirm '确认卸载主控？' && remove_master ;;
    2) confirm '确认卸载 Worker？' && remove_worker ;;
    3) confirm '确认卸载主控和 Worker？' && { remove_master; remove_worker; } ;;
    4)
        if command -v systemctl >/dev/null 2>&1; then
            systemctl is-active emby-panel 2>/dev/null || true
            systemctl is-active emby-agent 2>/dev/null || true
            systemctl is-active emby-cert-sync.timer 2>/dev/null || true
        fi
        command -v rc-service >/dev/null 2>&1 && rc-service emby-agent status 2>/dev/null || true
        exit 0
        ;;
    0) exit 0 ;;
    *) echo '无效选项。'; exit 1 ;;
esac

cleanup_project_if_unused
echo '卸载完成。仅删除 Emby Edge 创建的服务和数据，系统级 Nginx/Python 软件包予以保留。'
