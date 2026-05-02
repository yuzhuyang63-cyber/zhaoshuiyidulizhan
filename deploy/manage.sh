#!/usr/bin/env bash

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-zhaoshuiyidulizhan}"
PROJECT_DIR="${PROJECT_DIR:-/opt/zhaoshuiyidulizhan}"
STATIC_DIR="${STATIC_DIR:-/var/www/zhaoshuiyidulizhan}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
BACKEND_LOG="${BACKEND_LOG:-$PROJECT_DIR/logs/chat-backend.log}"
TRANSCRIPT_LOG="${TRANSCRIPT_LOG:-$PROJECT_DIR/logs/chat-transcript.log}"
LOCAL_HEALTH_URL="${LOCAL_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-http://cyqwater.com/api/health}"

usage() {
    cat <<'EOF'
Usage:
  bash deploy/manage.sh <command>

Commands:
  start               Start nginx and backend service
  stop                Stop backend service and nginx
  restart             Restart backend service and reload nginx
  status              Show backend and nginx status
  health              Check local and public health endpoints
  logs                Tail backend runtime log
  transcript-logs     Tail chat transcript log
  journal             Show systemd journal for backend service
  pull                Pull latest code from git
  install-deps        Install Python dependencies in the venv
  reload-nginx        Test and reload nginx
  deploy-backend      Pull code, install deps, restart backend
  deploy-frontend     Copy static files and reload nginx
  deploy-all          Pull code, install deps, copy static files, restart backend, reload nginx
  help                Show this help message

Environment overrides:
  SERVICE_NAME, PROJECT_DIR, STATIC_DIR, VENV_DIR,
  BACKEND_LOG, TRANSCRIPT_LOG, LOCAL_HEALTH_URL, PUBLIC_HEALTH_URL
EOF
}

run_in_project() {
    (
        cd "$PROJECT_DIR"
        "$@"
    )
}

ensure_venv() {
    if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        echo "Virtual environment not found: $VENV_DIR" >&2
        exit 1
    fi
}

start_services() {
    sudo systemctl start nginx
    sudo systemctl start "$SERVICE_NAME"
}

stop_services() {
    sudo systemctl stop "$SERVICE_NAME"
    sudo systemctl stop nginx
}

restart_services() {
    sudo systemctl restart "$SERVICE_NAME"
    sudo systemctl reload nginx
}

show_status() {
    sudo systemctl status "$SERVICE_NAME" --no-pager -l
    sudo systemctl status nginx --no-pager -l
}

check_health() {
    echo "Local health:"
    curl "$LOCAL_HEALTH_URL"
    echo
    echo "Public health:"
    curl "$PUBLIC_HEALTH_URL"
    echo
}

show_logs() {
    tail -f "$BACKEND_LOG"
}

show_transcript_logs() {
    tail -f "$TRANSCRIPT_LOG"
}

show_journal() {
    sudo journalctl -u "$SERVICE_NAME" -n 200 --no-pager
}

pull_code() {
    run_in_project git pull
}

install_deps() {
    ensure_venv
    run_in_project "$VENV_DIR/bin/pip" install -r requirements.txt
}

copy_static_files() {
    (
        cd "$PROJECT_DIR"
        sudo mkdir -p "$STATIC_DIR"
        sudo cp ./*.html ./*.css ./*.js robots.txt sitemap.xml "$STATIC_DIR/"
        sudo cp -r assets media "$STATIC_DIR/"
    )
}

reload_nginx() {
    sudo nginx -t
    sudo systemctl reload nginx
}

deploy_backend() {
    pull_code
    install_deps
    sudo systemctl restart "$SERVICE_NAME"
}

deploy_frontend() {
    copy_static_files
    reload_nginx
}

deploy_all() {
    pull_code
    install_deps
    copy_static_files
    sudo systemctl restart "$SERVICE_NAME"
    reload_nginx
}

main() {
    local command="${1:-help}"

    case "$command" in
        start)
            start_services
            ;;
        stop)
            stop_services
            ;;
        restart)
            restart_services
            ;;
        status)
            show_status
            ;;
        health)
            check_health
            ;;
        logs)
            show_logs
            ;;
        transcript-logs)
            show_transcript_logs
            ;;
        journal)
            show_journal
            ;;
        pull)
            pull_code
            ;;
        install-deps)
            install_deps
            ;;
        reload-nginx)
            reload_nginx
            ;;
        deploy-backend)
            deploy_backend
            ;;
        deploy-frontend)
            deploy_frontend
            ;;
        deploy-all)
            deploy_all
            ;;
        help|-h|--help)
            usage
            ;;
        *)
            echo "Unknown command: $command" >&2
            usage
            exit 1
            ;;
    esac
}

main "$@"
