from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_secret: str
    data_dir: Path
    max_upload_bytes: int
    max_rows: int
    trusted_hosts: list[str]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ml_lab.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development")
    app_secret = os.getenv("APP_SECRET", "")
    if app_env == "production" and len(app_secret) < 32:
        raise RuntimeError("APP_SECRET phải có ít nhất 32 ký tự khi deploy production.")
    if not app_secret:
        app_secret = "development-only-secret-change-before-production"

    settings = Settings(
        app_env=app_env,
        app_secret=app_secret,
        data_dir=Path(os.getenv("DATA_DIR", "storage")).resolve(),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        max_rows=int(os.getenv("MAX_ROWS", "100000")),
        trusted_hosts=[host.strip() for host in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()],
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(exist_ok=True)
    settings.model_dir.mkdir(exist_ok=True)
    return settings


settings = load_settings()
