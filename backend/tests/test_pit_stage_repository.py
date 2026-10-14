from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.pit_reconciliation import PitReconciliationWorkpaper
from app.services.pit_reconciliation.repository import PitReconciliationRepository


def test_repository_creates_independent_workpapers_per_stage():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    pre = PitReconciliationRepository(session, 1, 1, "pre_payment").get_or_create_workpaper()
    post = PitReconciliationRepository(session, 1, 1, "post_payment").get_or_create_workpaper()
    session.commit()
    assert pre.id != post.id
    assert {row.stage for row in session.query(PitReconciliationWorkpaper).all()} == {"pre_payment", "post_payment"}
    assert pre.workflow_status == post.workflow_status == "data_preparation"
