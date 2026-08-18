import shutil
import sqlite3
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _prepare_project(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "data/tmp").mkdir(parents=True)
    (root / "source-output/video").mkdir(parents=True)
    (root / "knowledge-base/topics").mkdir(parents=True)
    (root / "profiles").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "scripts/backup-data.sh", root / "scripts/backup-data.sh")
    shutil.copy2(PROJECT_ROOT / "scripts/restore-data.sh", root / "scripts/restore-data.sh")
    (root / "data/tmp/temporary.txt").write_text("temporary", encoding="utf-8")
    (root / "source-output/video/transcript.json").write_text("[]", encoding="utf-8")
    topic = root / "knowledge-base/topics/example.md"
    topic.write_text("# Example\n", encoding="utf-8")
    (root / "profiles/open.json").write_text('{"mode":"open"}', encoding="utf-8")
    connection = sqlite3.connect(root / "data/app.sqlite3")
    try:
        connection.execute("CREATE TABLE artifacts (id TEXT PRIMARY KEY, path TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO artifacts(id,path) VALUES (?,?)", ("topic-1", str(topic))
        )
        connection.commit()
    finally:
        connection.close()


def test_backup_and_restore_data_without_config(tmp_path: Path):
    source = tmp_path / "old-project"
    target = tmp_path / "new-project"
    archive = tmp_path / "migration.tar.zst"
    _prepare_project(source)

    subprocess.run(
        [str(source / "scripts/backup-data.sh"), str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )

    (target / "scripts").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "scripts/restore-data.sh", target / "scripts/restore-data.sh")
    (target / "knowledge-base/topics").mkdir(parents=True)
    (target / "knowledge-base/topics/old.md").write_text("old", encoding="utf-8")
    (target / "config.env").write_text("LLM_API_KEY=cloud-secret\n", encoding="utf-8")

    subprocess.run(
        [str(target / "scripts/restore-data.sh"), str(archive), "--yes"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (target / "config.env").read_text(encoding="utf-8") == (
        "LLM_API_KEY=cloud-secret\n"
    )
    assert not (target / "data/tmp/temporary.txt").exists()
    assert (target / "source-output/video/transcript.json").is_file()
    assert (target / "knowledge-base/topics/example.md").is_file()
    assert (target / "profiles/open.json").is_file()
    rollback_topics = list(
        (target / "pre-restore-data").glob("*/knowledge-base/topics/old.md")
    )
    assert len(rollback_topics) == 1

    connection = sqlite3.connect(target / "data/app.sqlite3")
    try:
        restored_path = connection.execute(
            "SELECT path FROM artifacts WHERE id='topic-1'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert restored_path == str(target / "knowledge-base/topics/example.md")
