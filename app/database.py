from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import settings


def now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    database = sqlite3.connect(settings.database_path, timeout=30)
    database.row_factory = sqlite3.Row
    try:
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                columns_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS training_jobs (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL REFERENCES datasets(id),
                label_column TEXT NOT NULL,
                feature_columns_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_versions (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL REFERENCES datasets(id),
                job_id TEXT NOT NULL REFERENCES training_jobs(id),
                version TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                metadata_path TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prediction_logs (
                id TEXT PRIMARY KEY,
                model_version_id TEXT NOT NULL REFERENCES model_versions(id),
                input_json TEXT NOT NULL,
                probability REAL NOT NULL,
                predicted_label TEXT NOT NULL,
                threshold REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON training_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_models_active ON model_versions(is_active);
            """
        )
        add_column_if_missing(db, "training_jobs", "model_name", "TEXT")
        add_column_if_missing(db, "training_jobs", "purpose", "TEXT")
        add_column_if_missing(db, "model_versions", "model_name", "TEXT")
        add_column_if_missing(db, "model_versions", "purpose", "TEXT")
        db.execute(
            "UPDATE training_jobs SET status = 'failed', error_message = 'Server restarted before job completed.', completed_at = ? WHERE status = 'running'",
            (now(),),
        )


def add_column_if_missing(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def deserialize(value: str) -> Any:
    return json.loads(value)


def relative_storage_path(path: Path) -> str:
    """Persist paths independently of the checkout directory."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(settings.data_dir.resolve()))
    except ValueError:
        return str(path)


def resolve_storage_path(value: str | Path) -> Path:
    """Resolve stored paths, including snapshots made with older absolute paths."""
    path = Path(value)
    if not path.is_absolute():
        return settings.data_dir / path
    try:
        return settings.data_dir / path.resolve().relative_to(settings.data_dir.resolve())
    except ValueError:
        for marker in ("uploads", "models"):
            if marker in path.parts:
                return settings.data_dir.joinpath(*path.parts[path.parts.index(marker):])
        return path


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connection() as db:
        row = db.execute(query, params).fetchone()
    return dict(row) if row else None


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def create_dataset(dataset_id: str, filename: str, path: Path, row_count: int, columns: list[dict[str, Any]]) -> None:
    with connection() as db:
        db.execute(
            "INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?)",
            (dataset_id, filename, relative_storage_path(path), row_count, serialize(columns), now()),
        )


def create_job(job_id: str, dataset_id: str, label_column: str, features: list[str], model_name: str, purpose: str) -> None:
    with connection() as db:
        existing = db.execute("SELECT id FROM training_jobs WHERE status IN ('queued', 'running')").fetchone()
        if existing:
            raise ValueError("Đang có một job train chạy. Hãy chờ job đó hoàn tất.")
        db.execute(
            "INSERT INTO training_jobs (id, dataset_id, label_column, feature_columns_json, model_name, purpose, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
            (job_id, dataset_id, label_column, serialize(features), model_name, purpose, now()),
        )


def update_job(job_id: str, status: str, error_message: str | None = None) -> None:
    with connection() as db:
        if status == "running":
            db.execute("UPDATE training_jobs SET status = ?, started_at = ? WHERE id = ?", (status, now(), job_id))
        else:
            db.execute(
                "UPDATE training_jobs SET status = ?, error_message = ?, completed_at = ? WHERE id = ?",
                (status, error_message, now(), job_id),
            )


def create_model(model: dict[str, Any]) -> None:
    with connection() as db:
        db.execute("UPDATE model_versions SET is_active = 0")
        db.execute(
            "INSERT INTO model_versions (id, dataset_id, job_id, version, artifact_path, metadata_path, metrics_json, is_active, created_at, model_name, purpose) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (
                model["id"], model["dataset_id"], model["job_id"], model["version"],
                relative_storage_path(Path(model["artifact_path"])), relative_storage_path(Path(model["metadata_path"])),
                serialize(model["metrics"]), now(), model["model_name"], model["purpose"],
            ),
        )


def activate_model(model_id: str) -> bool:
    with connection() as db:
        exists = db.execute("SELECT id FROM model_versions WHERE id = ?", (model_id,)).fetchone()
        if not exists:
            return False
        db.execute("UPDATE model_versions SET is_active = 0")
        db.execute("UPDATE model_versions SET is_active = 1 WHERE id = ?", (model_id,))
    return True


def update_model_identity(model_id: str, model_name: str, purpose: str) -> bool:
    with connection() as db:
        result = db.execute(
            "UPDATE model_versions SET model_name = ?, purpose = ? WHERE id = ?",
            (model_name, purpose, model_id),
        )
    return result.rowcount == 1


def log_prediction(log_id: str, model_id: str, inputs: dict[str, Any], probability: float, label: str, threshold: float) -> None:
    with connection() as db:
        db.execute(
            "INSERT INTO prediction_logs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (log_id, model_id, serialize(inputs), probability, label, threshold, now()),
        )
