from __future__ import annotations

from pathlib import Path

from app.db.session import Base, engine
from app.models import accounting, core, pit_reconciliation, tax
from app.db.migrations import run_migrations
from app.services.company_migration import migrate_legacy_company_storage


def _sqlite_db_path() -> Path | None:
    if engine.url.get_backend_name() != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).resolve()


def init_db(*, create_preupgrade_backup: bool = True) -> None:
    db_path = _sqlite_db_path()
    existed = bool(db_path and db_path.exists() and db_path.stat().st_size)
    if db_path:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    engine.dispose()
    Base.metadata.create_all(bind=engine)
    run_migrations(engine, backup_existing=create_preupgrade_backup and existed)
    migrate_legacy_company_storage()


if __name__ == "__main__":
    init_db()
