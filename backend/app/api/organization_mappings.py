from __future__ import annotations

import io
import re

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company
from app.models.accounting import OrganizationMapping


router = APIRouter(prefix="/organization-mappings", tags=["organization-mappings"], dependencies=[Depends(require_company)])


class MappingPayload(BaseModel):
    branch_name: str
    org_code: str
    taxpayer_id: str = ""
    active: bool = True
    rpa_enabled: bool = False
    rpa_org_name: str = ""
    parent_branch: str = ""


def _validate(
    branch_name: str,
    org_code: str,
    taxpayer_id: str = "",
    rpa_enabled: bool = False,
    rpa_org_name: str = "",
    parent_branch: str = "",
) -> tuple[str, str, str, str, str]:
    name = branch_name.strip()
    code = org_code.strip()
    normalized_taxpayer_id = "".join(taxpayer_id.split()).upper()
    full_name = rpa_org_name.strip()
    parent = parent_branch.strip()
    if not name:
        raise HTTPException(status_code=400, detail="营业部名称不能为空")
    if not re.fullmatch(r"\d{5}", code):
        raise HTTPException(status_code=400, detail="机构代码必须为5位数字")
    if rpa_enabled and not full_name:
        raise HTTPException(status_code=400, detail="启用 RPA 时营业部全称不能为空")
    if rpa_enabled and not parent:
        raise HTTPException(status_code=400, detail="启用 RPA 时所属分公司不能为空")
    return name, code, normalized_taxpayer_id, full_name, parent


def _validate_taxpayer_id_conflict(
    db: Session, taxpayer_id: str, exclude_id: int | None = None
) -> None:
    if not taxpayer_id:
        return
    query = db.query(OrganizationMapping).filter(OrganizationMapping.taxpayer_id == taxpayer_id)
    if exclude_id is not None:
        query = query.filter(OrganizationMapping.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="该机构纳税人识别号已被其他机构使用")


def _validate_org_code_conflict(db: Session, org_code: str, exclude_id: int | None = None) -> None:
    query = db.query(OrganizationMapping).filter(OrganizationMapping.org_code == org_code)
    if exclude_id is not None:
        query = query.filter(OrganizationMapping.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="该机构代码已存在")


def _validate_rpa_conflicts(
    db: Session,
    *,
    org_code: str,
    rpa_org_name: str,
    rpa_enabled: bool,
    exclude_id: int | None = None,
) -> None:
    if not rpa_enabled:
        return
    query = db.query(OrganizationMapping).filter(OrganizationMapping.rpa_enabled == 1)
    if exclude_id is not None:
        query = query.filter(OrganizationMapping.id != exclude_id)
    if query.filter(OrganizationMapping.org_code == org_code).first():
        raise HTTPException(status_code=409, detail="该机构代码已被其他 RPA 机构使用")
    if query.filter(OrganizationMapping.rpa_org_name == rpa_org_name).first():
        raise HTTPException(status_code=409, detail="该营业部全称已被其他 RPA 机构使用")


def _payload(item: OrganizationMapping) -> dict:
    return {
        "id": item.id,
        "branch_name": item.branch_name,
        "org_code": item.org_code,
        "taxpayer_id": item.taxpayer_id,
        "active": bool(item.active),
        "rpa_enabled": bool(item.rpa_enabled),
        "rpa_org_name": item.rpa_org_name,
        "parent_branch": item.parent_branch,
        "updated_at": item.updated_at,
    }


@router.get("")
def list_mappings(db: Session = Depends(get_db)) -> list[dict]:
    return [_payload(item) for item in db.query(OrganizationMapping).order_by(OrganizationMapping.org_code, OrganizationMapping.branch_name).all()]


@router.post("")
def create_mapping(payload: MappingPayload, db: Session = Depends(get_db)) -> dict:
    name, code, taxpayer_id, full_name, parent = _validate(
        payload.branch_name, payload.org_code, payload.taxpayer_id,
        payload.rpa_enabled, payload.rpa_org_name, payload.parent_branch
    )
    if db.query(OrganizationMapping).filter(OrganizationMapping.branch_name == name).first():
        raise HTTPException(status_code=409, detail="该营业部名称已存在")
    _validate_org_code_conflict(db, code)
    _validate_rpa_conflicts(db, org_code=code, rpa_org_name=full_name, rpa_enabled=payload.rpa_enabled)
    _validate_taxpayer_id_conflict(db, taxpayer_id)
    item = OrganizationMapping(
        branch_name=name,
        org_code=code,
        taxpayer_id=taxpayer_id,
        active=int(payload.active),
        rpa_enabled=int(payload.rpa_enabled),
        rpa_org_name=full_name,
        parent_branch=parent,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _payload(item)


@router.put("/{mapping_id}")
def update_mapping(mapping_id: int, payload: MappingPayload, db: Session = Depends(get_db)) -> dict:
    item = db.query(OrganizationMapping).filter(OrganizationMapping.id == mapping_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="机构映射不存在")
    name, code, taxpayer_id, full_name, parent = _validate(
        payload.branch_name, payload.org_code, payload.taxpayer_id,
        payload.rpa_enabled, payload.rpa_org_name, payload.parent_branch
    )
    duplicate = db.query(OrganizationMapping).filter(OrganizationMapping.branch_name == name, OrganizationMapping.id != mapping_id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="该营业部名称已存在")
    _validate_org_code_conflict(db, code, exclude_id=mapping_id)
    _validate_rpa_conflicts(
        db,
        org_code=code,
        rpa_org_name=full_name,
        rpa_enabled=payload.rpa_enabled,
        exclude_id=mapping_id,
    )
    _validate_taxpayer_id_conflict(db, taxpayer_id, exclude_id=mapping_id)
    item.branch_name = name
    item.org_code = code
    item.taxpayer_id = taxpayer_id
    item.active = int(payload.active)
    item.rpa_enabled = int(payload.rpa_enabled)
    item.rpa_org_name = full_name
    item.parent_branch = parent
    db.add(item)
    db.commit()
    db.refresh(item)
    return _payload(item)


@router.post("/import")
def import_mappings(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    frame = pd.read_excel(io.BytesIO(file.file.read()), dtype=str).fillna("")
    required = {"营业部名称", "机构代码"}
    if not required.issubset(frame.columns):
        raise HTTPException(status_code=400, detail="机构名称维护表必须包含：营业部名称、机构代码")
    count = 0
    for _, row in frame.iterrows():
        raw_code = str(row["机构代码"]).strip()
        item = db.query(OrganizationMapping).filter(OrganizationMapping.org_code == raw_code).first()
        if item is None:
            raw_name = str(row["营业部名称"]).strip()
            item = db.query(OrganizationMapping).filter(OrganizationMapping.branch_name == raw_name).first()
        enabled_text = str(row.get("是否启用RPA", "")).strip()
        rpa_enabled = (
            enabled_text.lower() in {"是", "启用", "true", "1", "yes", "y"}
            if "是否启用RPA" in frame.columns
            else bool(item.rpa_enabled) if item is not None else False
        )
        name, code, taxpayer_id, full_name, parent = _validate(
            str(row["营业部名称"]),
            str(row["机构代码"]),
            str(row.get("机构纳税人识别号", item.taxpayer_id if item is not None else "")),
            rpa_enabled,
            str(row.get("营业部全称", item.rpa_org_name if item is not None else "")),
            str(row.get("所属分公司", item.parent_branch if item is not None else "")),
        )
        if item is None:
            item = OrganizationMapping(branch_name=name)
        else:
            branch_conflict = db.query(OrganizationMapping).filter(
                OrganizationMapping.branch_name == name,
                OrganizationMapping.id != item.id,
            ).first()
            if branch_conflict:
                raise HTTPException(status_code=409, detail=f"营业部名称已被机构代码 {branch_conflict.org_code} 使用：{name}")
        _validate_rpa_conflicts(
            db,
            org_code=code,
            rpa_org_name=full_name,
            rpa_enabled=rpa_enabled,
            exclude_id=item.id,
        )
        _validate_taxpayer_id_conflict(db, taxpayer_id, exclude_id=item.id)
        item.org_code = code
        item.branch_name = name
        item.taxpayer_id = taxpayer_id
        item.active = 1
        item.rpa_enabled = int(rpa_enabled)
        item.rpa_org_name = full_name
        item.parent_branch = parent
        db.add(item)
        db.flush()
        count += 1
    db.commit()
    return {"updated": count}


@router.get("/export")
def export_mappings(db: Session = Depends(get_db)) -> Response:
    rows = [
        {
            "营业部名称": item.branch_name,
            "机构代码": item.org_code,
            "机构纳税人识别号": item.taxpayer_id,
            "启用": "是" if item.active else "否",
            "是否启用RPA": "是" if item.rpa_enabled else "否",
            "营业部全称": item.rpa_org_name,
            "所属分公司": item.parent_branch,
        }
        for item in db.query(OrganizationMapping).order_by(OrganizationMapping.org_code).all()
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="机构名称维护表", index=False)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%9C%BA%E6%9E%84%E5%90%8D%E7%A7%B0%E7%BB%B4%E6%8A%A4%E8%A1%A8.xlsx"},
    )
