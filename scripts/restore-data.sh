#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
ARCHIVE_PATH="${1:-}"
CONFIRM="${2:-}"

die() {
  echo "错误：$*" >&2
  exit 1
}

[[ -n "${ARCHIVE_PATH}" ]] || die "用法：$0 <迁移包.tar.zst> [--yes]"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"
[[ -n "${PYTHON_BIN}" ]] || die "未找到 Python 3"
if [[ "${ARCHIVE_PATH}" != /* ]]; then
  ARCHIVE_PATH="$(cd -- "$(dirname -- "${ARCHIVE_PATH}")" && pwd)/$(basename -- "${ARCHIVE_PATH}")"
fi
[[ -f "${ARCHIVE_PATH}" ]] || die "迁移包不存在：${ARCHIVE_PATH}"

if pgrep -f "${PROJECT_DIR}/.venv/bin/python -m app" >/dev/null 2>&1; then
  die "后端仍在运行。请先在启动终端按 Ctrl+C，完全停止服务后再恢复"
fi

if [[ "${CONFIRM}" != "--yes" ]]; then
  [[ -t 0 ]] || die "非交互环境必须添加 --yes"
  read -r -p "将恢复历史、知识库和来源产物，并保留旧数据快照。继续？[y/N] " answer
  [[ "${answer}" == "y" || "${answer}" == "Y" ]] || exit 0
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf -- "${STAGING_DIR}"' EXIT
tar --zstd -xf "${ARCHIVE_PATH}" -C "${STAGING_DIR}"
BUNDLE_DIR="${STAGING_DIR}/bili-knowledge-backup"
[[ -f "${BUNDLE_DIR}/manifest.json" ]] || die "迁移包缺少 manifest.json"

"${PYTHON_BIN}" - "${BUNDLE_DIR}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("format_version") != 1:
    raise SystemExit("错误：不支持的迁移包版本")
expected = manifest.get("files")
if not isinstance(expected, dict):
    raise SystemExit("错误：迁移包文件清单无效")
actual_paths = {
    path.relative_to(bundle).as_posix()
    for path in bundle.rglob("*")
    if path.is_file() and path.name != "manifest.json"
}
if actual_paths != set(expected):
    raise SystemExit("错误：迁移包文件集合与清单不一致")
for relative, metadata in expected.items():
    path = bundle / relative
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != metadata.get("sha256") or path.stat().st_size != metadata.get("size"):
        raise SystemExit(f"错误：迁移包校验失败：{relative}")
print(f"迁移包校验通过，共 {len(expected)} 个文件")
PY

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK_DIR="${PROJECT_DIR}/pre-restore-data/${TIMESTAMP}"
mkdir -p -- "${ROLLBACK_DIR}"
for directory in data source-output knowledge-base profiles; do
  if [[ -e "${PROJECT_DIR}/${directory}" ]]; then
    mv -- "${PROJECT_DIR}/${directory}" "${ROLLBACK_DIR}/${directory}"
  fi
  mkdir -p -- "${PROJECT_DIR}/${directory}"
  rsync -a "${BUNDLE_DIR}/${directory}/" "${PROJECT_DIR}/${directory}/"
done

"${PYTHON_BIN}" - "${BUNDLE_DIR}/manifest.json" "${PROJECT_DIR}/data/app.sqlite3" "${PROJECT_DIR}" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

manifest_path, database_path, new_root = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
old_root = str(manifest.get("source_project_dir") or "").rstrip("/")
new_root = new_root.rstrip("/")
if old_root and old_root != new_root:
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute("SELECT id,path FROM artifacts").fetchall()
        changed = 0
        for artifact_id, path in rows:
            if path == old_root or path.startswith(old_root + "/"):
                rewritten = new_root + path[len(old_root):]
                connection.execute(
                    "UPDATE artifacts SET path=? WHERE id=?", (rewritten, artifact_id)
                )
                changed += 1
        connection.commit()
    finally:
        connection.close()
    print(f"已将 {changed} 条产物路径改为新项目目录")
PY

echo "数据恢复完成。原数据可从这里恢复：${ROLLBACK_DIR}"
echo "config.env 未被修改；确认配置后可启动 ./scripts/start.sh"
