from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.accounting import OrganizationMapping
from app.services.intern_org_mapping import INTERN_ORG_CODE_MAP


def seed_organization_mappings() -> None:
    db = SessionLocal()
    try:
        if db.query(OrganizationMapping).count() == 0:
            db.add_all([
                OrganizationMapping(branch_name=name, org_code=code, active=1)
                for name, code in INTERN_ORG_CODE_MAP.items()
            ])
            db.commit()
    finally:
        db.close()


def active_mapping_dict(db: Session) -> dict[str, str]:
    return {
        item.branch_name.strip(): item.org_code.strip()
        for item in db.query(OrganizationMapping).filter(OrganizationMapping.active == 1).all()
    }
