#!/usr/bin/env bash
set -eu

python -m uvicorn app.main:app --app-dir /app/backend --host 127.0.0.1 --port 8000 &
backend_pid=$!

stop_services() {
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
}

trap stop_services INT TERM EXIT
nginx -g 'daemon off;' &
nginx_pid=$!

set +e
wait -n "$backend_pid" "$nginx_pid"
status=$?
set -e
kill "$backend_pid" "$nginx_pid" 2>/dev/null || true
wait "$backend_pid" "$nginx_pid" 2>/dev/null || true
exit "$status"
