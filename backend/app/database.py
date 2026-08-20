from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .constants import STAGES


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS videos (
      id TEXT PRIMARY KEY, bvid TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
      uploader TEXT, cover_url TEXT, published_at TEXT, duration REAL,
      raw_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS parts (
      id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
      part_index INTEGER NOT NULL, cid TEXT, title TEXT NOT NULL, url TEXT NOT NULL,
      duration REAL, subtitle_json TEXT NOT NULL DEFAULT '[]', raw_json TEXT NOT NULL DEFAULT '{}',
      UNIQUE(video_id, part_index)
    );
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id), status TEXT NOT NULL,
      cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL, completed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS job_parts (
      job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      part_id TEXT NOT NULL REFERENCES parts(id), status TEXT NOT NULL DEFAULT 'queued',
      summary TEXT, PRIMARY KEY(job_id, part_id)
    );
    CREATE TABLE IF NOT EXISTS job_stages (
      id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      part_id TEXT REFERENCES parts(id), stage TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      error TEXT, retries INTEGER NOT NULL DEFAULT 0, started_at TEXT, finished_at TEXT,
      UNIQUE(job_id, part_id, stage)
    );
    CREATE TABLE IF NOT EXISTS artifacts (
      id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      part_id TEXT REFERENCES parts(id), kind TEXT NOT NULL, path TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(job_id, part_id, kind)
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_stages_job ON job_stages(job_id);
    """,
    """
    INSERT OR IGNORE INTO job_stages(job_id,part_id,stage,status)
    SELECT jp.job_id,jp.part_id,'organize','pending'
    FROM job_parts jp JOIN jobs j ON j.id=jp.job_id
    WHERE j.status IN ('queued','running','failed');
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_topics (
      path TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      source_bvid TEXT,
      last_job_id TEXT,
      last_part_id TEXT,
      last_action TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE knowledge_topics RENAME TO knowledge_topics_v3;
    CREATE TABLE knowledge_topics (
      path TEXT PRIMARY KEY,
      source_bvid TEXT,
      last_action TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    INSERT INTO knowledge_topics(path,source_bvid,last_action,updated_at)
    SELECT path,source_bvid,last_action,updated_at FROM knowledge_topics_v3;
    DROP TABLE knowledge_topics_v3;
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_profiles (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      mode TEXT NOT NULL CHECK(mode IN ('open','guided','strict')),
      scope TEXT NOT NULL DEFAULT '',
      rules_json TEXT NOT NULL DEFAULT '{}',
      is_active INTEGER NOT NULL DEFAULT 0,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_profiles_active
      ON knowledge_profiles(is_active) WHERE is_active=1;
    CREATE TABLE IF NOT EXISTS knowledge_profile_topics (
      id TEXT PRIMARY KEY,
      profile_id TEXT NOT NULL REFERENCES knowledge_profiles(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      path TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      sort_order INTEGER NOT NULL DEFAULT 0,
      UNIQUE(profile_id,path)
    );
    CREATE INDEX IF NOT EXISTS idx_profile_topics_profile
      ON knowledge_profile_topics(profile_id,sort_order);
    """,
    """
    ALTER TABLE artifacts RENAME TO artifacts_v5;
    CREATE TABLE artifacts (
      id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      part_id TEXT REFERENCES parts(id), kind TEXT NOT NULL, path TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(job_id, part_id, kind, path)
    );
    INSERT INTO artifacts(id,job_id,part_id,kind,path,created_at)
    SELECT id,job_id,part_id,kind,path,created_at FROM artifacts_v5;
    DROP TABLE artifacts_v5;
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def migrate(self) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in enumerate(MIGRATIONS, 1):
                if version not in applied:
                    connection.executescript(sql)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, utcnow()),
                    )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as connection:
            yield connection
            connection.commit()

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.transaction() as connection:
            connection.execute(sql, params)

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def save_inspection(self, metadata: dict) -> dict:
        video_id = str(uuid.uuid4())
        now = utcnow()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO videos
                (id,bvid,url,title,uploader,cover_url,published_at,duration,raw_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    video_id,
                    metadata["bvid"],
                    metadata["url"],
                    metadata["title"],
                    metadata.get("uploader"),
                    metadata.get("cover_url"),
                    metadata.get("published_at"),
                    metadata.get("duration"),
                    json.dumps(metadata.get("raw", {}), ensure_ascii=False),
                    now,
                ),
            )
            saved_parts = []
            for part in metadata["parts"]:
                part_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO parts
                    (id,video_id,part_index,cid,title,url,duration,subtitle_json,raw_json)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        part_id,
                        video_id,
                        part["index"],
                        part.get("cid"),
                        part["title"],
                        part["url"],
                        part.get("duration"),
                        json.dumps(part.get("subtitles", []), ensure_ascii=False),
                        json.dumps(part.get("raw", {}), ensure_ascii=False),
                    ),
                )
                saved_parts.append({**part, "id": part_id})
        return {**metadata, "id": video_id, "parts": saved_parts}

    def create_job(self, video_id: str, part_ids: list[str]) -> str:
        job_id, now = str(uuid.uuid4()), utcnow()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO jobs(id,video_id,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                (job_id, video_id, "queued", now, now),
            )
            for part_id in part_ids:
                connection.execute(
                    "INSERT INTO job_parts(job_id,part_id,status) VALUES (?,?,?)",
                    (job_id, part_id, "queued"),
                )
                for stage in STAGES:
                    connection.execute(
                        "INSERT INTO job_stages(job_id,part_id,stage,status) VALUES (?,?,?,?)",
                        (job_id, part_id, stage, "pending"),
                    )
        return job_id

    def create_job_if_absent(self, video_id: str, part_ids: list[str]) -> tuple[str, bool]:
        """Create a job unless the same BVID and part selection was submitted before."""
        job_id, now = str(uuid.uuid4()), utcnow()
        with self.transaction() as connection:
            requested = connection.execute(
                f"""SELECT v.bvid,p.part_index FROM videos v JOIN parts p ON p.video_id=v.id
                WHERE v.id=? AND p.id IN ({','.join('?' for _ in part_ids)})
                ORDER BY p.part_index""",
                (video_id, *part_ids),
            ).fetchall()
            requested_parts = tuple(row["part_index"] for row in requested)
            if requested:
                candidates = connection.execute(
                    """SELECT j.id FROM jobs j JOIN videos v ON v.id=j.video_id
                    WHERE v.bvid=? ORDER BY j.created_at DESC,j.id DESC""",
                    (requested[0]["bvid"],),
                ).fetchall()
                for candidate in candidates:
                    existing_parts = tuple(
                        row["part_index"]
                        for row in connection.execute(
                            """SELECT p.part_index FROM job_parts jp
                            JOIN parts p ON p.id=jp.part_id
                            WHERE jp.job_id=? ORDER BY p.part_index""",
                            (candidate["id"],),
                        ).fetchall()
                    )
                    if existing_parts == requested_parts:
                        return candidate["id"], False

            connection.execute(
                "INSERT INTO jobs(id,video_id,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                (job_id, video_id, "queued", now, now),
            )
            for part_id in part_ids:
                connection.execute(
                    "INSERT INTO job_parts(job_id,part_id,status) VALUES (?,?,?)",
                    (job_id, part_id, "queued"),
                )
                for stage in STAGES:
                    connection.execute(
                        "INSERT INTO job_stages(job_id,part_id,stage,status) VALUES (?,?,?,?)",
                        (job_id, part_id, stage, "pending"),
                    )
        return job_id, True

    def set_stage(
        self, job_id: str, part_id: str, stage: str, status: str, error: str | None = None
    ) -> None:
        now = utcnow()
        started = now if status == "running" else None
        finished = now if status in {"completed", "failed", "skipped"} else None
        with self.transaction() as connection:
            connection.execute(
                """UPDATE job_stages SET status=?, error=?,
                started_at=COALESCE(?,started_at), finished_at=?
                WHERE job_id=? AND part_id=? AND stage=?""",
                (status, error, started, finished, job_id, part_id, stage),
            )
            connection.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now, job_id))

    def save_artifact(self, job_id: str, part_id: str | None, kind: str, path: Path) -> str:
        artifact_id = str(uuid.uuid4())
        with self.transaction() as connection:
            if kind == "topic":
                existing = connection.execute(
                    "SELECT id FROM artifacts WHERE job_id=? AND part_id IS ? AND kind=? AND path=?",
                    (job_id, part_id, kind, str(path)),
                ).fetchone()
            else:
                existing = connection.execute(
                    "SELECT id FROM artifacts WHERE job_id=? AND part_id IS ? AND kind=?",
                    (job_id, part_id, kind),
                ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE artifacts SET path=?,created_at=? WHERE id=?",
                    (str(path), utcnow(), existing["id"]),
                )
                return existing["id"]
            connection.execute(
                "INSERT INTO artifacts(id,job_id,part_id,kind,path,created_at) VALUES (?,?,?,?,?,?)",
                (artifact_id, job_id, part_id, kind, str(path), utcnow()),
            )
        return artifact_id

    def save_topic_state(
        self,
        path: str,
        source_bvid: str | None,
        action: str,
        updated_at: str,
    ) -> None:
        self.execute(
            """INSERT INTO knowledge_topics
            (path,source_bvid,last_action,updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
              source_bvid=excluded.source_bvid,
              last_action=excluded.last_action,
              updated_at=excluded.updated_at""",
            (path, source_bvid, action, updated_at),
        )

    def _profile_from_row(self, row: dict) -> dict:
        rules = json.loads(row.pop("rules_json") or "{}")
        rules["ignore_out_of_scope"] = row["mode"] == "strict"
        rules["merge_similar"] = True
        row["is_active"] = bool(row["is_active"])
        row["rules"] = rules
        row["preferred_topics"] = self.all(
            """SELECT name,path,description FROM knowledge_profile_topics
            WHERE profile_id=? ORDER BY sort_order,id""",
            (row["id"],),
        )
        return row

    def list_knowledge_profiles(self) -> list[dict]:
        rows = self.all("SELECT * FROM knowledge_profiles ORDER BY is_active DESC,created_at,id")
        return [self._profile_from_row(row) for row in rows]

    def get_knowledge_profile(self, profile_id: str) -> dict | None:
        row = self.one("SELECT * FROM knowledge_profiles WHERE id=?", (profile_id,))
        return self._profile_from_row(row) if row else None

    def active_knowledge_profile(self) -> dict | None:
        row = self.one("SELECT * FROM knowledge_profiles WHERE is_active=1")
        return self._profile_from_row(row) if row else None

    def save_knowledge_profile(self, profile: dict, profile_id: str | None = None) -> dict:
        now = utcnow()
        profile_id = profile_id or str(uuid.uuid4())
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT version,is_active FROM knowledge_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE knowledge_profiles SET name=?,mode=?,scope=?,rules_json=?,
                    version=version+1,updated_at=? WHERE id=?""",
                    (
                        profile["name"],
                        profile["mode"],
                        profile["scope"],
                        json.dumps(profile["rules"], ensure_ascii=False),
                        now,
                        profile_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM knowledge_profile_topics WHERE profile_id=?", (profile_id,)
                )
            else:
                active_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_profiles WHERE is_active=1"
                ).fetchone()[0]
                connection.execute(
                    """INSERT INTO knowledge_profiles
                    (id,name,mode,scope,rules_json,is_active,version,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        profile_id,
                        profile["name"],
                        profile["mode"],
                        profile["scope"],
                        json.dumps(profile["rules"], ensure_ascii=False),
                        0 if active_count else 1,
                        1,
                        now,
                        now,
                    ),
                )
            for order, topic in enumerate(profile["preferred_topics"]):
                connection.execute(
                    """INSERT INTO knowledge_profile_topics
                    (id,profile_id,name,path,description,sort_order) VALUES (?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        profile_id,
                        topic["name"],
                        topic["path"],
                        topic["description"],
                        order,
                    ),
                )
        return self.get_knowledge_profile(profile_id)

    def seed_knowledge_profile(self, profile: dict) -> dict:
        existing = self.active_knowledge_profile()
        return existing or self.save_knowledge_profile(profile)

    def activate_knowledge_profile(self, profile_id: str) -> dict | None:
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM knowledge_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if not existing:
                return None
            connection.execute("UPDATE knowledge_profiles SET is_active=0 WHERE is_active=1")
            connection.execute(
                "UPDATE knowledge_profiles SET is_active=1,updated_at=? WHERE id=?",
                (utcnow(), profile_id),
            )
        return self.get_knowledge_profile(profile_id)

    def delete_knowledge_profile(self, profile_id: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT is_active FROM knowledge_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            count = connection.execute("SELECT COUNT(*) FROM knowledge_profiles").fetchone()[0]
            if not row or row["is_active"] or count <= 1:
                return False
            connection.execute("DELETE FROM knowledge_profiles WHERE id=?", (profile_id,))
            return True

    def job_detail(self, job_id: str) -> dict | None:
        job = self.one(
            """SELECT j.*,v.title AS video_title,v.bvid,v.url AS video_url
            FROM jobs j JOIN videos v ON v.id=j.video_id WHERE j.id=?""",
            (job_id,),
        )
        if not job:
            return None
        job["parts"] = self.all(
            """SELECT p.*,jp.status,jp.summary FROM job_parts jp
            JOIN parts p ON p.id=jp.part_id WHERE jp.job_id=? ORDER BY p.part_index""",
            (job_id,),
        )
        stages = self.all("SELECT * FROM job_stages WHERE job_id=? ORDER BY part_id,id", (job_id,))
        artifacts = self.all(
            "SELECT * FROM artifacts WHERE job_id=? ORDER BY created_at", (job_id,)
        )
        for part in job["parts"]:
            part["stages"] = sorted(
                [stage for stage in stages if stage["part_id"] == part["id"]],
                key=lambda stage: STAGES.index(stage["stage"]),
            )
            part["artifacts"] = [item for item in artifacts if item["part_id"] == part["id"]]
            part.pop("subtitle_json", None)
            part.pop("raw_json", None)
        job["artifacts"] = [item for item in artifacts if item["part_id"] is None]
        job["cancel_requested"] = bool(job["cancel_requested"])
        return job

    def list_jobs(self) -> list[dict]:
        # Keep this endpoint cheap because both clients poll it. The previous implementation
        # called job_detail() for every row (four SQL queries per job), which became noticeably
        # slower as history grew.
        jobs = self.all(
            """SELECT j.*,v.title AS video_title,v.bvid,v.url AS video_url
            FROM jobs j JOIN videos v ON v.id=j.video_id
            ORDER BY j.updated_at DESC,j.created_at DESC,j.id DESC"""
        )
        if not jobs:
            return []
        parts = self.all(
            """SELECT jp.job_id,p.*,jp.status,jp.summary FROM job_parts jp
            JOIN parts p ON p.id=jp.part_id ORDER BY jp.job_id,p.part_index"""
        )
        stages = self.all(
            "SELECT * FROM job_stages ORDER BY job_id,part_id,id"
        )
        artifacts = self.all(
            "SELECT * FROM artifacts ORDER BY job_id,created_at"
        )
        parts_by_job: dict[str, list[dict]] = {}
        stages_by_part: dict[tuple[str, str], list[dict]] = {}
        artifacts_by_part: dict[tuple[str, str | None], list[dict]] = {}
        for part in parts:
            parts_by_job.setdefault(part["job_id"], []).append(part)
        for stage in stages:
            stages_by_part.setdefault((stage["job_id"], stage["part_id"]), []).append(stage)
        for artifact in artifacts:
            artifacts_by_part.setdefault(
                (artifact["job_id"], artifact["part_id"]), []
            ).append(artifact)
        for job in jobs:
            job_parts = parts_by_job.get(job["id"], [])
            for part in job_parts:
                part["stages"] = sorted(
                    stages_by_part.get((job["id"], part["id"]), []),
                    key=lambda stage: STAGES.index(stage["stage"]),
                )
                part["artifacts"] = artifacts_by_part.get((job["id"], part["id"]), [])
                part.pop("subtitle_json", None)
                part.pop("raw_json", None)
            job["parts"] = job_parts
            job["artifacts"] = artifacts_by_part.get((job["id"], None), [])
            job["cancel_requested"] = bool(job["cancel_requested"])
        return jobs

    def list_jobs_compact(self) -> list[dict]:
        """Return only the fields needed by polling clients such as the Android app."""
        jobs = self.all(
            """SELECT j.id,j.status,j.error,j.created_at,j.updated_at,j.cancel_requested,
            v.title AS video_title,v.bvid,v.url AS video_url
            FROM jobs j JOIN videos v ON v.id=j.video_id
            ORDER BY j.updated_at DESC,j.created_at DESC,j.id DESC"""
        )
        if not jobs:
            return []
        parts = self.all(
            """SELECT jp.job_id,p.id,p.title,jp.status FROM job_parts jp
            JOIN parts p ON p.id=jp.part_id ORDER BY jp.job_id,p.part_index"""
        )
        stages = self.all(
            """SELECT job_id,part_id,stage,status,error FROM job_stages
            ORDER BY job_id,part_id,id"""
        )
        parts_by_job: dict[str, list[dict]] = {}
        stages_by_part: dict[tuple[str, str], list[dict]] = {}
        for part in parts:
            parts_by_job.setdefault(part.pop("job_id"), []).append(part)
        for stage in stages:
            job_id = stage.pop("job_id")
            part_id = stage.pop("part_id")
            stages_by_part.setdefault((job_id, part_id), []).append(stage)
        for job in jobs:
            job_parts = parts_by_job.get(job["id"], [])
            for part in job_parts:
                part["stages"] = sorted(
                    stages_by_part.get((job["id"], part["id"]), []),
                    key=lambda stage: STAGES.index(stage["stage"]),
                )
            job["parts"] = job_parts
            job["cancel_requested"] = bool(job["cancel_requested"])
        return jobs

    def recover_interrupted(self) -> list[str]:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE job_stages SET status='failed',error='后端重启导致阶段中断',finished_at=? WHERE status='running'",
                (utcnow(),),
            )
            connection.execute(
                "UPDATE jobs SET status='failed',error='后端重启导致任务中断',updated_at=? WHERE status='running'",
                (utcnow(),),
            )
            return [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM jobs WHERE status='queued' AND cancel_requested=0"
                ).fetchall()
            ]
