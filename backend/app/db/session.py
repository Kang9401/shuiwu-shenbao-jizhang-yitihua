from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria

from app.core.config import settings
from app.core.company_context import current_company_id


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Session, "do_orm_execute")
def _scope_business_queries(execute_state) -> None:
    if not execute_state.is_select:
        return
    company_id = current_company_id(default=None)
    if company_id is None:
        return
    from app.models import COMPANY_SCOPED_MODELS

    statement = execute_state.statement
    for model in COMPANY_SCOPED_MODELS:
        statement = statement.options(
            with_loader_criteria(model, lambda cls: cls.company_id == company_id, include_aliases=True)
        )
    execute_state.statement = statement


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
