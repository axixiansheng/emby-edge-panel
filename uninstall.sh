#!/bin/sh
set -eu

confirm() {
    printf '%s [y/N]: ' "$1"
    IFS= read -r answer
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

remove_master() {
    echo '正在停止并移除主控服务...'
    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now emby-panel 2>/dev/null || true
        rm -f /etc/systemd/system/emby-panel.service
        systemctl daemon-reload
    fi
    rm -f /etc/nginx/sites-enabled/emby-panel /etc/nginx/sites-enabled/emby-panel-http
    rm -f /etc/nginx/sites-available/emby-panel /etc/nginx/sites-available/emby-panel-http
    if [ -d /opt/emby_panel ]; then
        if confirm '是否保留主控数据库 panel.db？'; then
            save_dir="/root/emby-panel-data-$(date +%Y%m%d-%H%M%S)"
            mkdir -p "$save_dir"
            [ ! -f /opt/emby_panel/db/panel.db ] || cp -a /opt/emby_panel/db/panel.db* "$save_dir/"
            echo "数据库已保存到 $save_dir"
        fi
        rm -rf /opt/emby_panel
    fi
    rm -f /etc/nginx/emby_url.map /etc/nginx/emby_sni.map
    nginx -t 2>/dev/null && { systemctl restart nginx 2>/dev/null || true; }
}

remove_worker() {
    echo '正在停止并移除 Worker 服务...'
    if command -v rc-service >/dev/null 2>&1; then
        rc-service emby-agent stop 2>/dev/null || true
        rc-update del emby-agent default 2>/dev/null || true
    fi
    rm -f /etc/init.d/emby-agent
    rm -rf /opt/emby_agent
    rm -f /etc/nginx/http.d/default.conf /etc/nginx/emby_url.map /etc/nginx/emby_sni.map
    nginx -t 2>/dev/null && { rc-service nginx restart 2>/dev/null || true; }
}

printf '=== Emby Edge 卸载程序 ===\n'
printf '1. 卸载主控\n2. 卸载 Worker\n3. 卸载主控和 Worker\n4. 清理本项目自动备份\n0. 退出\n请选择 [0-4]: '
IFS= read -r choice
case "$choice" in
    1) confirm '确认卸载主控？' && remove_master ;;
    2) confirm '确认卸载 Worker？' && remove_worker ;;
    3) confirm '确认卸载主控和 Worker？' && { remove_master; remove_worker; } ;;
    4)
        if confirm '确认删除 /opt 和 /etc 下由本项目创建的所有时间戳备份？'; then
            rm -rf /opt/emby_panel.backup-* /opt/emby_panel.pre-* /opt/emby_agent.pre-*
            rm -rf /etc/nginx.backup-* /etc/nginx.pre-emby-* /etc/nginx.pre-emby-worker-*
            echo '项目备份已清理。'
        fi
        ;;
    0) exit 0 ;;
    *) echo '无效选项。'; exit 1 ;;
esac

echo '操作完成。系统 Nginx、Python、Curl、Chrony 软件包未被卸载。'
