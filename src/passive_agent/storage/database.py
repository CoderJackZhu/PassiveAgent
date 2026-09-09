from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from passive_agent.storage.models import FeedbackRecord, Item, Score
from passive_agent.utils.logger import log

SCHEMA_VERSION = 5

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    local_path TEXT,
    zotero_key TEXT,
    collected_at TEXT NOT NULL,
    content_type TEXT,
    topics TEXT,
    stage TEXT NOT NULL DEFAULT 'new',
    summary TEXT,
    interview_relevance TEXT,
    estimated_minutes INTEGER,
    priority_score REAL,
    recommended_action TEXT,
    ignored_count INTEGER DEFAULT 0,
    is_weekend INTEGER DEFAULT 0,
    raw_text TEXT,
    extra_meta TEXT,
    created_at TEXT NOT NULL,
    actioned_at TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id),
    goal_relevance REAL NOT NULL,
    novelty REAL NOT NULL,
    actionability REAL NOT NULL,
    difficulty_fit REAL NOT NULL,
    source_quality REAL NOT NULL,
    timeliness REAL NOT NULL,
    weighted_total REAL NOT NULL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL,
    topic TEXT,
    source TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_weights (
    topic TEXT PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 1.0,
    last_updated_at TEXT,
    ignore_count_window INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_weights (
    source TEXT PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 1.0,
    last_updated_at TEXT,
    ignore_count_window INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    collected_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    pushed_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success',
    user_actions TEXT,
    errors TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    surface TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    week_start TEXT PRIMARY KEY,
    report_path TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    pushed_at TEXT,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS zotero_write_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    tag TEXT NOT NULL,
    remove_tag TEXT,
    created_at TEXT NOT NULL,
    executed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_stage ON items(stage);
CREATE INDEX IF NOT EXISTS idx_items_collected_at ON items(collected_at);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_feedback_topic_time ON feedback(topic, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_source_time ON feedback(source, created_at);
CREATE INDEX IF NOT EXISTS idx_scores_item ON scores(item_id);
CREATE INDEX IF NOT EXISTS idx_daily_log_date ON daily_log(date);
CREATE INDEX IF NOT EXISTS idx_item_events_time ON item_events(created_at);
CREATE INDEX IF NOT EXISTS idx_item_events_item_type_time ON item_events(item_id, event_type, created_at);
"""


class Database:
    def __init__(self, db_path: str | Path = "data/workbench.db"):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self):
        current_version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version < SCHEMA_VERSION:
            self.conn.executescript(SCHEMA_SQL)
            # Migrations
            if current_version < 2:
                try:
                    self.conn.execute("ALTER TABLE zotero_write_queue ADD COLUMN remove_tag TEXT")
                except sqlite3.OperationalError:
                    pass  # column already exists (fresh DB)
            if current_version < 3:
                try:
                    self.conn.execute("ALTER TABLE items ADD COLUMN extra_meta TEXT")
                except sqlite3.OperationalError:
                    pass
            if current_version < 4:
                try:
                    self.conn.execute("ALTER TABLE daily_log ADD COLUMN status TEXT NOT NULL DEFAULT 'success'")
                except sqlite3.OperationalError:
                    pass
            if current_version < 5:
                self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS item_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    surface TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS weekly_reports (
                    week_start TEXT PRIMARY KEY,
                    report_path TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    pushed_at TEXT,
                    summary TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_item_events_time ON item_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_item_events_item_type_time
                    ON item_events(item_id, event_type, created_at);
                """)
                self._backfill_legacy_ignore_events()
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()
            log.info(f"Database initialized (version {SCHEMA_VERSION})")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Items ---

    def save_item(self, item: Item):
        with self.conn:
            self._insert_item(item)

    def _insert_item(self, item: Item):
        data = item.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        self.conn.execute(
            f"INSERT OR REPLACE INTO items ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )

    def save_items(self, items: list[Item]):
        with self.conn:
            for item in items:
                self._insert_item(item)

    def save_scored_items(self, items: list[Item], scores: list[Score]):
        with self.conn:
            for item in items:
                self._insert_item(item)
            for score in scores:
                self._insert_score(score)

    def get_item(self, item_id: str) -> Item | None:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        return Item.from_row(dict(row))

    def get_items_by_stage(self, stage: str) -> list[Item]:
        rows = self.conn.execute("SELECT * FROM items WHERE stage = ?", (stage,)).fetchall()
        return [Item.from_row(dict(r)) for r in rows]

    def get_weekend_queue(self) -> list[Item]:
        rows = self.conn.execute(
            "SELECT * FROM items WHERE is_weekend = 1 AND stage NOT IN ('archived', 'ignored')"
        ).fetchall()
        return [Item.from_row(dict(r)) for r in rows]

    def get_all_titles(self) -> set[str]:
        rows = self.conn.execute("SELECT title FROM items").fetchall()
        return {r["title"] for r in rows}

    def get_all_urls(self) -> set[str]:
        rows = self.conn.execute("SELECT url FROM items WHERE url IS NOT NULL").fetchall()
        return {r["url"] for r in rows}

    def get_items_by_source(self, source: str, topic: str | None = None) -> list[Item]:
        if topic:
            rows = self.conn.execute(
                "SELECT * FROM items WHERE source = ? AND topics LIKE ?",
                (source, f'%"{topic}"%'),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM items WHERE source = ?", (source,)).fetchall()
        return [Item.from_row(dict(r)) for r in rows]

    def update_item_extra_meta(self, item_id: str, extra_meta: dict):
        self.conn.execute(
            "UPDATE items SET extra_meta = ? WHERE id = ?",
            (json.dumps(extra_meta, ensure_ascii=False), item_id),
        )
        self.conn.commit()

    def get_archived_titles(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT title FROM items WHERE stage = 'archived' ORDER BY actioned_at DESC LIMIT 100"
        ).fetchall()
        return [r["title"] for r in rows]

    def count_items_by_date(self, date_str: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM items WHERE id LIKE ?",
            (f"item_{date_str}_%",),
        ).fetchone()
        return row["cnt"]

    def update_item_stage(self, item_id: str, stage: str):
        now = datetime.now().isoformat()
        if stage in ("archived", "actioned"):
            self.conn.execute(
                "UPDATE items SET stage = ?, actioned_at = ? WHERE id = ?",
                (stage, now, item_id),
            )
        else:
            self.conn.execute("UPDATE items SET stage = ? WHERE id = ?", (stage, item_id))
        self.conn.commit()

    def mark_stale_recommendations(self, days: int = 7) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.execute(
            """UPDATE items
               SET stage = 'stale'
               WHERE stage = 'recommended'
                 AND actioned_at IS NULL
                 AND created_at < ?""",
            (cutoff,),
        )
        self.conn.commit()
        return cursor.rowcount if cursor.rowcount is not None else 0

    def count_items_by_stage(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT stage, COUNT(*) AS cnt FROM items GROUP BY stage"
        ).fetchall()
        return {r["stage"]: r["cnt"] for r in rows}

    # --- Scores ---

    def save_score(self, score: Score):
        with self.conn:
            self._insert_score(score)

    def _insert_score(self, score: Score):
        self.conn.execute(
            """INSERT INTO scores (item_id, goal_relevance, novelty, actionability,
               difficulty_fit, source_quality, timeliness, weighted_total, scored_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                score.item_id,
                score.goal_relevance,
                score.novelty,
                score.actionability,
                score.difficulty_fit,
                score.source_quality,
                score.timeliness,
                score.weighted_total,
                score.scored_at.isoformat(),
            ),
        )

    # --- Feedback ---

    def save_feedback(self, record: FeedbackRecord):
        self.conn.execute(
            "INSERT INTO feedback (item_id, action, topic, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (record.item_id, record.action, record.topic, record.source, record.created_at.isoformat()),
        )
        self.conn.commit()

    def get_recent_feedback_for_topic(self, topic: str, window: int = 10) -> list[FeedbackRecord]:
        rows = self.conn.execute(
            "SELECT * FROM feedback WHERE topic = ? ORDER BY created_at DESC LIMIT ?",
            (topic, window),
        ).fetchall()
        return [
            FeedbackRecord(
                id=r["id"], item_id=r["item_id"], action=r["action"],
                topic=r["topic"], source=r["source"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def get_recent_feedback_for_source(self, source: str, window: int = 15) -> list[FeedbackRecord]:
        rows = self.conn.execute(
            "SELECT * FROM feedback WHERE source = ? ORDER BY created_at DESC LIMIT ?",
            (source, window),
        ).fetchall()
        return [
            FeedbackRecord(
                id=r["id"], item_id=r["item_id"], action=r["action"],
                topic=r["topic"], source=r["source"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # --- Item Events ---

    def _backfill_legacy_ignore_events(self):
        self.conn.execute(
            """INSERT INTO item_events (item_id, event_type, surface, metadata, created_at)
               SELECT f.item_id,
                      'ignore',
                      'legacy_feedback',
                      '{"feedback_id":' || f.id || '}',
                      f.created_at
               FROM feedback AS f
               WHERE f.action = 'ignore'
                 AND NOT EXISTS (
                    SELECT 1
                    FROM item_events AS e
                    WHERE e.item_id = f.item_id
                      AND e.event_type = 'ignore'
                      AND e.created_at = f.created_at
                 )"""
        )

    def record_item_event(
        self,
        item_id: str,
        event_type: str,
        *,
        surface: str | None = None,
        metadata: dict | None = None,
        created_at: datetime | None = None,
    ):
        created = created_at or datetime.now()
        self.conn.execute(
            """INSERT INTO item_events (item_id, event_type, surface, metadata, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                item_id,
                event_type,
                surface,
                json.dumps(metadata or {}, ensure_ascii=False),
                created.isoformat(),
            ),
        )
        self.conn.commit()

    def get_item_events_between(self, start: datetime, end: datetime) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, item_id, event_type, surface, metadata, created_at
               FROM item_events
               WHERE created_at >= ? AND created_at < ?
               ORDER BY created_at ASC, id ASC""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._parse_item_event_row(row) for row in rows]

    @staticmethod
    def _parse_item_event_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        try:
            data["metadata"] = json.loads(data.get("metadata") or "{}")
        except json.JSONDecodeError:
            data["metadata"] = {}
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return data

    # --- Weights ---

    def get_topic_weight(self, topic: str) -> float:
        row = self.conn.execute("SELECT weight FROM topic_weights WHERE topic = ?", (topic,)).fetchone()
        return row["weight"] if row else 1.0

    def set_topic_weight(self, topic: str, weight: float):
        self.conn.execute(
            """INSERT INTO topic_weights (topic, weight, last_updated_at)
               VALUES (?, ?, ?) ON CONFLICT(topic) DO UPDATE SET weight = ?, last_updated_at = ?""",
            (topic, weight, datetime.now().isoformat(), weight, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_source_weight(self, source: str) -> float:
        row = self.conn.execute("SELECT weight FROM source_weights WHERE source = ?", (source,)).fetchone()
        return row["weight"] if row else 1.0

    def set_source_weight(self, source: str, weight: float):
        self.conn.execute(
            """INSERT INTO source_weights (source, weight, last_updated_at)
               VALUES (?, ?, ?) ON CONFLICT(source) DO UPDATE SET weight = ?, last_updated_at = ?""",
            (source, weight, datetime.now().isoformat(), weight, datetime.now().isoformat()),
        )
        self.conn.commit()

    def recover_stale_weights(self, days: int = 30, rate: float = 0.05):
        """Recover weights that haven't been updated in `days` days towards 1.0"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        rows = self.conn.execute(
            "SELECT topic, weight FROM topic_weights WHERE weight < 1.0 AND last_updated_at < ?",
            (cutoff,),
        ).fetchall()
        for r in rows:
            new_weight = min(r["weight"] + rate, 1.0)
            self.set_topic_weight(r["topic"], new_weight)

        rows = self.conn.execute(
            "SELECT source, weight FROM source_weights WHERE weight < 1.0 AND last_updated_at < ?",
            (cutoff,),
        ).fetchall()
        for r in rows:
            new_weight = min(r["weight"] + rate, 1.0)
            self.set_source_weight(r["source"], new_weight)

    # --- App State ---

    def set_app_state(self, key: str, value: str):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO app_state (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
            (key, value, now, value, now),
        )
        self.conn.commit()

    def get_app_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_paused(self, paused: bool):
        self.set_app_state("paused", "1" if paused else "0")

    def is_paused(self) -> bool:
        value = self.get_app_state("paused", "0")
        return str(value).lower() in ("1", "true", "yes", "on")

    # --- Daily Log ---

    def log_daily_run(
        self,
        run_date: date,
        collected: int,
        processed: int,
        pushed: int,
        errors: list[str],
        status: str = "success",
    ):
        self.conn.execute(
            """INSERT OR REPLACE INTO daily_log
               (date, collected_count, processed_count, pushed_count, status, errors, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_date.isoformat(),
                collected,
                processed,
                pushed,
                status,
                json.dumps(errors, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def get_daily_logs_since(self, start_date: date) -> list[dict]:
        rows = self.conn.execute(
            """SELECT date, collected_count, processed_count, pushed_count, status, errors, created_at
               FROM daily_log
               WHERE date >= ?
               ORDER BY date ASC""",
            (start_date.isoformat(),),
        ).fetchall()

        logs = []
        for row in rows:
            data = dict(row)
            try:
                data["errors"] = json.loads(data.get("errors") or "[]")
            except json.JSONDecodeError:
                data["errors"] = [data.get("errors")]
            logs.append(data)
        return logs

    # --- Weekly Reports ---

    def save_weekly_report(
        self,
        *,
        week_start: date,
        report_path: str,
        generated_at: datetime | None = None,
        summary: dict | None = None,
    ):
        generated = generated_at or datetime.now()
        self.conn.execute(
            """INSERT INTO weekly_reports (week_start, report_path, generated_at, summary)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(week_start) DO UPDATE SET
                   report_path = excluded.report_path,
                   generated_at = excluded.generated_at,
                   summary = excluded.summary""",
            (
                week_start.isoformat(),
                report_path,
                generated.isoformat(),
                json.dumps(summary or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def get_weekly_report(self, week_start: date) -> dict | None:
        row = self.conn.execute(
            """SELECT week_start, report_path, generated_at, pushed_at, summary
               FROM weekly_reports
               WHERE week_start = ?""",
            (week_start.isoformat(),),
        ).fetchone()
        if row is None:
            return None
        return self._parse_weekly_report_row(row)

    def mark_weekly_report_pushed(
        self,
        week_start: date,
        *,
        pushed_at: datetime | None = None,
    ):
        pushed = pushed_at or datetime.now()
        self.conn.execute(
            "UPDATE weekly_reports SET pushed_at = ? WHERE week_start = ?",
            (pushed.isoformat(), week_start.isoformat()),
        )
        self.conn.commit()

    @staticmethod
    def _parse_weekly_report_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["week_start"] = date.fromisoformat(data["week_start"])
        data["generated_at"] = datetime.fromisoformat(data["generated_at"])
        data["pushed_at"] = (
            datetime.fromisoformat(data["pushed_at"]) if data.get("pushed_at") else None
        )
        try:
            data["summary"] = json.loads(data.get("summary") or "{}")
        except json.JSONDecodeError:
            data["summary"] = {}
        return data

    # --- Zotero Write Queue ---

    def enqueue_zotero_write(self, item_key: str, tag: str, remove_tag: str | None = None):
        self.conn.execute(
            "INSERT INTO zotero_write_queue (item_key, tag, remove_tag, created_at) VALUES (?, ?, ?, ?)",
            (item_key, tag, remove_tag, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_pending_zotero_writes(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, item_key, tag, remove_tag FROM zotero_write_queue WHERE executed_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_zotero_write_done(self, write_id: int):
        self.conn.execute(
            "UPDATE zotero_write_queue SET executed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), write_id),
        )
        self.conn.commit()
