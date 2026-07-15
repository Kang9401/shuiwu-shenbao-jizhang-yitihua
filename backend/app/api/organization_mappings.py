from __future__ import annotations

import io
import re

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.accounting import OrganizationMapping


router = APIRouter(prefix="/organization-mappings", tags=["organization-mappings"])


class MappingPayload(BaseModel):
    branch_name: str
    org_code: str
    active: bool = True


def _validate(branch_name: str, org_code: str) -> tuple[str, str]:
    name = branch_name.strip()
    code = org_code.strip()
    if not name:
        raise HTTPException(status_code=400, detail="营业部名称不能为空")
    if not re.fullmatch(r"\d{5}", code):
        raise HTTPException(status_code=400, detail="机构代码必须为5位数字")
    return name, code


def _payload(item: OrganizationMapping) -> dict:
    return {
        "id": item.id,
        "branch_name": item.branch_name,
        "org_code": item.org_code,
        "active": bool(item.active),
        "updated_at": item.updated_at,
    }


@router.get("")
def list_mappings(db: Session = Depends(get_db)) -> list[dict]:
    return [_payload(item) for item in db.query(OrganizationMapping).order_by(OrganizationMapping.org_code, OrganizationMapping.branch_name).all()]


@router.post("")
def create_mapping(payload: MappingPayload, db: Session = Depends(get_db)) -> dict:
    name, code = _validate(payload.branch_name, payload.org_code)
    if db.query(OrganizationMapping).filter(OrganizationMapping.branch_name == name).first():
        raise HTTPException(status_code=409, detail="该营业部名称已存在")
    item = OrganizationMapping(branch_name=name, org_code=code, active=int(payload.active))
    db.add(item)
    db.commit()
    db.refresh(item)
    return _payload(item)


@router.put("/{mapping_id}")
def update_mapping(mapping_id: int, payload: MappingPayload, db: Session = Depends(get_db)) -> dict:
    item = db.query(OrganizationMapping).filter(OrganizationMapping.id == mapping_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="机构映射不存在")
    name, code = _validate(payload.branch_name, payload.org_code)
    duplicate = db.query(OrganizationMapping).filter(OrganizationMapping.branch_name == name, OrganizationMapping.id != mapping_id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="该营业部名称已存在")
    item.branch_name = name
    item.org_code = code
    item.active = int(payload.active)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _payload(item)


@router.post("/import")
def import_mappings(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    frame = pd.read_excel(io.BytesIO(file.file.read()), dtype=str).fillna("")
    required = {"营业部名称", "机构代码"}
    if not required.issubset(frame.columns):
        raise HTTPException(status_code=400, detail="映射文件必须包含：营业部名称、机构代码")
    count = 0
    for _, row in frame.iterrows():
        name, code = _validate(str(row["营业部名称"]), str(row["机构代码"]))
        item = db.query(OrganizationMapping).filter(OrganizationMapping.branch_name == name).first()
        if item is None:
            item = OrganizationMapping(branch_name=name)
        item.org_code = code
        item.active = 1
        db.add(item)
        count += 1
    db.commit()
    return {"updated": count}


@router.get("/export")
def export_mappings(db: Session = Depends(get_db)) -> Response:
    rows = [{"营业部名称": item.branch_name, "机构代码": item.org_code, "启用": "是" if item.active else "否"} for item in db.query(OrganizationMapping).order_by(OrganizationMapping.org_code).all()]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="机构映射", index=False)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''organization_mappings.xlsx"},
    )
