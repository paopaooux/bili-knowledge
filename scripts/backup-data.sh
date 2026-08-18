#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_OUTPUT="${PROJECT_DIR}/migration-backups/bili-knowledge-data-${TIMESTAMP}.tar.zst"
OUTPUT_PATH="${1:-${DEFAULT_OUTPUT}}"

die() {
  echo "错误：$*" >&2
  exit 1
}

[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"
[[ -n "${PYTHON_BIN}" ]] || die "未找到 Python 3"
[[ -f "${PROJECT_DIR}/data/app.sqlite3" ]] || die "未找到历史数据库 data/app.sqlite3"

if pgrep -f "${PROJECT_DIR}/.venv/bin/python -m app" >/dev/null 2>&1; then
  die "后端仍在运行。请先在启动终端按 Ctrl+C，完全停止服务后再备份"
fi

if [[ "${OUTPUT_PATH}" != /* ]]; then
  OUTPUT_PATH="${PROJECT_DIR}/${OUTPUT_PATH}"
fi
mkdir -p -- "$(dirname -- "${OUTPUT_PATH}")"
[[ ! -e "${OUTPUT_PATH}" ]] || die "输出文件已存在：${OUTPUT_PATH}"

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf -- "${STAGING_DIR}"' EXIT
BUNDLE_DIR="${STAGING_DIR}/bili-knowledge-backup"
mkdir -p -- "${BUNDLE_DIR}/data" "${BUNDLE_DIR}/source-output" \
  "${BUNDLE_DIR}/knowledge-base" "${BUNDLE_DIR}/profiles"

for directory in source-output knowledge-base profiles; do
  if [[ -d "${PROJECT_DIR}/${directory}" ]]; then
    rsync -a "${PROJECT_DIR}/${directory}/" "${BUNDLE_DIR}/${directory}/"
  fi
done

"${PYTHON_BIN}" - "${PROJECT_DIR}/data/app.sqlite3" "${BUNDLE_DIR}/data/app.sqlite3" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY

"${PYTHON_BIN}" - "${BUNDLE_DIR}" "${PROJECT_DIR}" "${TIMESTAMP}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
project_dir = sys.argv[2]
created_at = sys.argv[3]
files = {}
for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    files[path.relative_to(bundle).as_posix()] = {
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
    }
manifest = {
    "format_version": 1,
    "created_at_utc": created_at,
    "source_project_dir": project_dir,
    "config_included": False,
    "files": files,
}
(bundle / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY

tar --zstd -cf "${OUTPUT_PATH}" -C "${STAGING_DIR}" bili-knowledge-backup
echo "迁移包已创建：${OUTPUT_PATH}"
echo "配置文件未包含；文件数：$("${PYTHON_BIN}" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["files"]))' "${BUNDLE_DIR}/manifest.json")"
echo "SHA-256：$(sha256sum "${OUTPUT_PATH}" | cut -d ' ' -f 1)"
