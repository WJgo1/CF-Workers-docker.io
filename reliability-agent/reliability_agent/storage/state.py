"""增量状态库：SQLite 保存记录镜像、同步游标和运行历史。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    table_key TEXT PRIMARY KEY,
    last_success_ms INTEGER,
    last_run_ms INTEGER,
    run_count INTEGER NOT NULL DEFAULT 0,
    total_records INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS records (
    table_key TEXT NOT NULL,
    record_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at_ms INTEGER,
    synced_at_ms INTEGER NOT NULL,
    PRIMARY KEY (table_key, record_id)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    mode TEXT,
    table_key TEXT,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_changed INTEGER NOT NULL DEFAULT 0,
    excel_path TEXT,
    sheet_synced INTEGER NOT NULL DEFAULT 0,
    message TEXT
);
"""


@dataclass
class SyncDiff:
    changed: int = 0
    added: int = 0
    deleted: int = 0


def _content_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------ 同步状态
    def get_sync_state(self, table_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM sync_state WHERE table_key = ?", (table_key,)
        ).fetchone()
        return dict(row) if row else None

    def count_records(self, table_key: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM records WHERE table_key = ?", (table_key,)
        ).fetchone()
        return int(row["n"]) if row else 0

    def upsert_records(
        self, table_key: str, items: list[dict[str, Any]], *, now_ms: int | None = None
    ) -> SyncDiff:
        """按 content_hash 判断新增/变更，只写有变化的记录。"""
        now_ms = now_ms or int(time.time() * 1000)
        existing = {
            row["record_id"]: row["content_hash"]
            for row in self.conn.execute(
                "SELECT record_id, content_hash FROM records WHERE table_key = ?", (table_key,)
            )
        }
        diff = SyncDiff()
        rows: list[tuple[Any, ...]] = []
        for item in items:
            record_id = str(item["record_id"])
            row = item["row"]
            digest = _content_hash(row)
            previous = existing.get(record_id)
            if previous != digest:
                diff.changed += 1
                if previous is None:
                    diff.added += 1
            rows.append(
                (
                    table_key,
                    record_id,
                    json.dumps(row, ensure_ascii=False, default=str),
                    digest,
                    item.get("updated_at_ms"),
                    now_ms,
                )
            )
        self.conn.executemany(
            "INSERT OR REPLACE INTO records "
            "(table_key, record_id, payload, content_hash, updated_at_ms, synced_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return diff

    def delete_missing(self, table_key: str, keep_ids: set[str]) -> int:
        """全量对账时清理源表中已删除的记录。"""
        existing_ids = [
            row["record_id"]
            for row in self.conn.execute(
                "SELECT record_id FROM records WHERE table_key = ?", (table_key,)
            )
        ]
        to_delete = [record_id for record_id in existing_ids if record_id not in keep_ids]
        if to_delete:
            self.conn.executemany(
                "DELETE FROM records WHERE table_key = ? AND record_id = ?",
                [(table_key, record_id) for record_id in to_delete],
            )
            self.conn.commit()
        return len(to_delete)

    def mark_sync(
        self, table_key: str, *, total_records: int, last_success_ms: int | None = None
    ) -> None:
        now_ms = int(time.time() * 1000)
        self.conn.execute(
            """
            INSERT INTO sync_state (table_key, last_success_ms, last_run_ms, run_count, total_records)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(table_key) DO UPDATE SET
                last_success_ms = excluded.last_success_ms,
                last_run_ms = excluded.last_run_ms,
                run_count = sync_state.run_count + 1,
                total_records = excluded.total_records
            """,
            (table_key, last_success_ms or now_ms, now_ms, total_records),
        )
        self.conn.commit()

    def load_dataframe(self, table_key: str) -> pd.DataFrame:
        rows = [
            json.loads(row["payload"])
            for row in self.conn.execute(
                "SELECT payload FROM records WHERE table_key = ? "
                "ORDER BY updated_at_ms IS NULL, updated_at_ms, record_id",
                (table_key,),
            )
        ]
        return pd.DataFrame(rows)

    # ------------------------------------------------------------ 运行历史
    def start_run(self, run_id: str, *, mode: str, started_at: str) -> None:
        self.conn.execute(
            "INSERT INTO runs (run_id, started_at, status, mode) VALUES (?, ?, 'running', ?)",
            (run_id, started_at, mode),
        )
        self.conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: str,
        table_key: str = "",
        rows_total: int = 0,
        rows_changed: int = 0,
        excel_path: str | None = None,
        sheet_synced: bool = False,
        message: str = "",
    ) -> None:
        self.conn.execute(
            """
            UPDATE runs SET finished_at = ?, status = ?, table_key = ?, rows_total = ?,
                rows_changed = ?, excel_path = ?, sheet_synced = ?, message = ?
            WHERE run_id = ?
            """,
            (
                finished_at,
                status,
                table_key,
                rows_total,
                rows_changed,
                excel_path,
                int(sheet_synced),
                message[:2000],
                run_id,
            ),
        )
        self.conn.commit()

    def recent_runs(self, limit: int = 20) -> pd.DataFrame:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(row) for row in rows])
        df["sheet_synced"] = df["sheet_synced"].map({1: "是", 0: "否"}).fillna("否")
        return df.rename(
            columns={
                "run_id": "运行ID",
                "started_at": "开始时间",
                "finished_at": "结束时间",
                "status": "状态",
                "mode": "模式",
                "table_key": "数据源",
                "rows_total": "记录数",
                "rows_changed": "变更数",
                "excel_path": "Excel 路径",
                "sheet_synced": "飞书表格",
                "message": "说明",
            }
        )
