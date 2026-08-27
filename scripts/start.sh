#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
START_MODE="${1:-auto}"
BACKEND_PORT=8000
FRONTEND_PORT=5175
BACKEND_PID=""
FRONTEND_PID=""

die() {
  echo "错误：$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：./scripts/start.sh [--docker|--local]

不带参数时自动选择：检测到可用 Docker 就启动 Compose，否则在本机启动。
  --docker  强制使用 Docker Compose
  --local   强制在本机启动 FastAPI 和 Vite
EOF
}

case "${START_MODE}" in
  auto) ;;
  --docker) START_MODE="docker" ;;
  --local) START_MODE="local" ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

port_is_free() {
  "${PYTHON_BIN}" -c '
import socket
import sys

with socket.socket() as sock:
    sock.settimeout(0.2)
    sys.exit(1 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 0)
' "$1"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  echo
  echo "正在关闭服务……"
  if [[ -n "${FRONTEND_PID}" ]]; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID}" ]]; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  wait "${FRONTEND_PID}" 2>/dev/null || true
  wait "${BACKEND_PID}" 2>/dev/null || true
  echo "前后端已关闭。"
  exit "${exit_code}"
}

start_docker() {
  command -v docker >/dev/null 2>&1 || die "未找到 Docker；请安装 Docker 或使用 --local"
  docker compose version >/dev/null 2>&1 || die "未找到 Docker Compose 插件"
  docker info >/dev/null 2>&1 || \
    die "检测到 Docker 命令，但无法连接 Docker 服务；请先启动 Docker"

  echo "正在使用 Docker Compose 启动或更新拾影成文……"
  (
    cd "${PROJECT_DIR}"
    docker compose up -d --build
  )
  echo
  echo "拾影成文 Docker 服务已启动："
  echo "  Web 页面： http://127.0.0.1:${FRONTEND_PORT}"
  echo "  查看日志： docker compose logs -f"
  echo "  停止服务： docker compose down"
}

if [[ "${START_MODE}" == "docker" ]] || \
  { [[ "${START_MODE}" == "auto" ]] && command -v docker >/dev/null 2>&1; }; then
  start_docker
  exit 0
fi

[[ -x "${PYTHON_BIN}" ]] || die "未找到虚拟环境，请先运行 python3.12 -m venv .venv"
"${PYTHON_BIN}" -c 'import dashscope, fastapi, oss2, uvicorn, yt_dlp' 2>/dev/null || \
  die "后端依赖未安装，请运行 .venv/bin/pip install -e './backend[dev]'"
command -v npm >/dev/null 2>&1 || die "未找到 npm，请先安装 Node.js"
[[ -d "${PROJECT_DIR}/frontend/node_modules" ]] || \
  die "前端依赖未安装，请在 frontend 目录运行 npm install"
port_is_free "${BACKEND_PORT}" || die "端口 ${BACKEND_PORT} 已被占用"
port_is_free "${FRONTEND_PORT}" || die "端口 ${FRONTEND_PORT} 已被占用"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "警告：未找到 ffmpeg；有公开字幕的视频仍可处理，无字幕视频将无法转写。" >&2
fi
if [[ ! -f "${PROJECT_DIR}/config.env" ]]; then
  echo "提示：尚未创建 config.env；未配置模型密钥时无法生成知识稿。" >&2
fi

trap cleanup EXIT INT TERM

(
  cd "${PROJECT_DIR}/backend"
  exec "${PYTHON_BIN}" -m app
) &
BACKEND_PID=$!

(
  cd "${PROJECT_DIR}/frontend"
  exec npm run dev -- --host 127.0.0.1
) &
FRONTEND_PID=$!

echo
echo "拾影成文已启动："
echo "  Web 页面： http://127.0.0.1:${FRONTEND_PORT}"
echo "  API 文档： http://127.0.0.1:${BACKEND_PORT}/docs"
echo "  按 Ctrl+C 同时关闭前后端。"
echo

set +e
wait -n "${BACKEND_PID}" "${FRONTEND_PID}"
SERVICE_STATUS=$?
set -e
if [[ ${SERVICE_STATUS} -ne 0 ]]; then
  echo "某个服务异常退出（状态码 ${SERVICE_STATUS}）。" >&2
else
  echo "某个服务已退出。" >&2
fi
exit "${SERVICE_STATUS}"
