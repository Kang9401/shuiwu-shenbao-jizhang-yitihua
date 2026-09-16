from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.paths import default_backup_root, default_frontend_dist, default_storage_root, sqlite_url
from app.core.version import PRODUCT_NAME


class Settings(BaseSettings):
    app_name: str = PRODUCT_NAME
    api_prefix: str = "/api"
    runtime_mode: str = "development"
    storage_root: Path = Field(default_factory=default_storage_root)
    database_url: str = ""
    backup_root: Path = Field(default_factory=default_backup_root)
    frontend_dist_dir: Path = Field(default_factory=default_frontend_dist)
    allow_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    finance_ai_base_url: str = ""
    finance_ai_api_key: str = ""
    finance_ai_model: str = ""
    finance_ai_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def resolve_runtime_paths(self) -> "Settings":
        self.storage_root = self.storage_root.expanduser().resolve()
        self.backup_root = self.backup_root.expanduser().resolve()
        self.frontend_dist_dir = self.frontend_dist_dir.expanduser().resolve()
        if not self.database_url:
            self.database_url = sqlite_url(self.storage_root / "tax_accounting.db")
        return self

    @property
    def upload_dir(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def artifact_dir(self) -> Path:
        return self.storage_root / "artifacts"

    @property
    def log_dir(self) -> Path:
        return self.storage_root / "logs"

    @property
    def temp_dir(self) -> Path:
        return self.storage_root / "temp"

    @property
    def backup_dir(self) -> Path:
        return self.backup_root

    @property
    def allow_origins_list(self) -> list[str]:
        return [item.strip() for item in self.allow_origins.split(",") if item.strip()]


settings = Settings()
settings.allow_origins = ",".join(settings.allow_origins_list)
