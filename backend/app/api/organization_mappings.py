from __future__ import annotations

import io
import re
from collections import OrderedDict

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company
from app.models.accounting import OrganizationMapping
from app.core.company_context import current_company_id
from app.services.bank_accounts import normalize_bank_account


router = APIRouter(prefix="/organization-mappings", tags=["organization-mappings"], dependencies=[Depends(require_company)])


class MappingPayload(BaseModel):
    branch_name: str
    org_code: str
    taxpayer_id: str = ""
    active: bool = True
    rpa_enabled: bool = False
    rpa_org_name: str = ""
    rpa_search_result_index: int = 1
    parent_branch: str = ""
    bank_subaccount: str = ""
    bank_account: str = ""


def _validate(
    branch_name: str,
    org_code: str,
    taxpayer_id: str = "",
    rpa_enabled: bool = False,
    rpa_org_name: str = "",
    rpa_search_result_index: int = 1,
    parent_branch: str = "",
) -> tuple[str, str, str, str, int, str]:
    name = branch_name.strip()
    code = org_code.strip()
    normalized_taxpayer_id = "".join(taxpayer_id.split()).upper()
    full_name = rpa_org_name.strip()
    result_index = int(rpa_search_result_index)
    parent = parent_branch.strip()
    if not name:
        raise HTTPException(status_code=400, detail="营业部名称不能为空")
    if not re.fullmatch(r"\d{5}", code):
        raise HTTPException(status_code=400, detail="机构代码必须为5位数字")
    if rpa_enabled and not full_name:
        raise HTTPException(status_code=400, detail="启用 RPA 时营业部全称不能为空")
    if rpa_enabled and not parent:
        raise HTTPException(status_code=400, detail="启用 RPA 时所属分公司不能为空")
    if result_index < 1:
        raise HTTPException(status_code=400, detail="RPA 搜索结果序号必须从 1 开始")
    return name, code, normalized_taxpayer_id, full_name, result_index, parent


def _validate_taxpayer_id_conflict(
    db: Session, taxpayer_id: str, exclude_id: int | None = None
) -> None:
    if not taxpayer_id:
        return
    query = db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id(), OrganizationMapping.taxpayer_id == taxpayer_id)
    if exclude_id is not None:
        query = query.filter(OrganizationMapping.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="该机构纳税人识别号已被其他机构使用")

def _validate_bank_account_conflict(db: Session, bank_account: str, exclude_id: int | None = None) -> None:
    account = normalize_bank_account(bank_account)
    if not account:
        return
    query = db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id(), OrganizationMapping.bank_account == account)
    if exclude_id is not None:
        query = query.filter(OrganizationMapping.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="该银行账号已被其他机构使用")


def _validate_org_code_conflict(db: Session, org_code: str, exclude_id: int | None = None) -> None:
    query = db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id(), OrganizationMapping.org_code == org_code)
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
    query = db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id(), OrganizationMapping.rpa_enabled == 1)
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
        "rpa_search_result_index": item.rpa_search_result_index,
        "parent_branch": item.parent_branch,
        "bank_subaccount": item.bank_subaccount,
        "bank_account": item.bank_account,
        "updated_at": item.updated_at,
    }


@router.get("")
def list_mappings(db: Session = Depends(get_db)) -> list[dict]:
    return [_payload(item) for item in db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id()).order_by(OrganizationMapping.org_code, OrganizationMapping.branch_name).all()]


@router.post("")
def create_mapping(payload: MappingPayload, db: Session = Depends(get_db)) -> dict:
    name, code, taxpayer_id, full_name, result_index, parent = _validate(
        payload.branch_name, payload.org_code, payload.taxpayer_id,
        payload.rpa_enabled, payload.rpa_org_name, payload.rpa_search_result_index, payload.parent_branch
    )
    if db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id(), OrganizationMapping.branch_name == name).first():
        raise HTTPException(status_code=409, detail="该营业部名称已存在")
    _validate_org_code_conflict(db, code)
    _validate_rpa_conflicts(db, org_code=code, rpa_org_name=full_name, rpa_enabled=payload.rpa_enabled)
    _validate_taxpayer_id_conflict(db, taxpayer_id)
    _validate_bank_account_conflict(db, payload.bank_account)
    item = OrganizationMapping(
        branch_name=name,
        org_code=code,
        taxpayer_id=taxpayer_id,
        active=int(payload.active),
        rpa_enabled=int(payload.rpa_enabled),
        rpa_org_name=full_name,
        rpa_search_result_index=result_index,
        parent_branch=parent,
        bank_subaccount=payload.bank_subaccount.strip(),
        bank_account=normalize_bank_account(payload.bank_account),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _payload(item)


@router.put("/{mapping_id}")
def update_mapping(mapping_id: int, payload: MappingPayload, db: Session = Depends(get_db)) -> dict:
    item = db.query(OrganizationMapping).filter(OrganizationMapping.id == mapping_id).first()
    if not item or item.company_id != current_company_id():
        raise HTTPException(status_code=404, detail="机构映射不存在")
    name, code, taxpayer_id, full_name, result_index, parent = _validate(
        payload.branch_name, payload.org_code, payload.taxpayer_id,
        payload.rpa_enabled, payload.rpa_org_name, payload.rpa_search_result_index, payload.parent_branch
    )
    duplicate = db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id(), OrganizationMapping.branch_name == name, OrganizationMapping.id != mapping_id).first()
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
    _validate_bank_account_conflict(db, payload.bank_account, exclude_id=mapping_id)
    item.branch_name = name
    item.org_code = code
    item.taxpayer_id = taxpayer_id
    item.active = int(payload.active)
    item.rpa_enabled = int(payload.rpa_enabled)
    item.rpa_org_name = full_name
    item.rpa_search_result_index = result_index
    item.parent_branch = parent
    item.bank_subaccount = payload.bank_subaccount.strip()
    item.bank_account = normalize_bank_account(payload.bank_account)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _payload(item)


@router.delete("/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.query(OrganizationMapping).filter(
        OrganizationMapping.id == mapping_id,
        OrganizationMapping.company_id == current_company_id(),
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="机构映射不存在")
    db.delete(item)
    db.commit()
    return {"deleted": mapping_id}


@router.post("/import")
def import_mappings(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    frame = pd.read_excel(io.BytesIO(file.file.read()), dtype=str).fillna("")
    required = {"营业部名称", "机构代码"}
    if not required.issubset(frame.columns):
        raise HTTPException(status_code=400, detail="机构名称维护表必须包含：营业部名称、机构代码")
    prepared: OrderedDict[str, dict] = OrderedDict()
    for row_index, row in frame.iterrows():
        raw_code = str(row["机构代码"]).strip()
        if raw_code.endswith(".0"):
            raw_code = raw_code[:-2]
        raw_name = str(row["营业部名称"]).strip()
        if not raw_code and not raw_name:
            continue
        enabled_text = str(row.get("是否启用RPA", "")).strip()
        rpa_enabled = enabled_text.lower() in {"是", "启用", "true", "1", "yes", "y"}
        active_text = str(row.get("启用", "是")).strip().lower()
        active = active_text not in {"否", "停用", "false", "0", "no", "n"}
        raw_result_index = row.get("RPA搜索结果序号", 1)
        try:
            result_index = int(float(str(raw_result_index).strip() or "1"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"机构代码 {raw_code} 的 RPA搜索结果序号必须为正整数") from None
        name, code, taxpayer_id, full_name, result_index, parent = _validate(
            str(row["营业部名称"]),
            raw_code,
            str(row.get("机构纳税人识别号", "")),
            rpa_enabled,
            str(row.get("营业部全称", "")),
            result_index,
            str(row.get("所属分公司", "")),
        )
        prepared[code] = {
            "branch_name": name,
            "org_code": code,
            "taxpayer_id": taxpayer_id,
            "active": int(active),
            "rpa_enabled": int(rpa_enabled),
            "rpa_org_name": full_name,
            "rpa_search_result_index": result_index,
            "parent_branch": parent,
            "bank_subaccount": str(row.get("银行子目", "")).strip(),
            "bank_account": normalize_bank_account(row.get("银行账号", "")),
            "row_number": int(row_index) + 2,
        }

    def ensure_unique(rows, field: str, label: str, *, populated_only: bool = False) -> None:
        seen: dict[str, tuple[str, int]] = {}
        for code, values in rows:
            value = str(values[field])
            if populated_only and not value:
                continue
            if value in seen:
                other_code, other_row = seen[value]
                raise HTTPException(
                    status_code=409,
                    detail=f"第 {values['row_number']} 行与第 {other_row} 行的{label}重复：{value}（机构代码 {other_code}、{code}）",
                )
            seen[value] = (code, values["row_number"])

    ensure_unique(prepared.items(), "branch_name", "营业部名称")
    ensure_unique(prepared.items(), "bank_account", "银行账号", populated_only=True)
    ensure_unique(prepared.items(), "taxpayer_id", "机构纳税人识别号", populated_only=True)
    ensure_unique(
        ((code, values) for code, values in prepared.items() if values["rpa_enabled"]),
        "rpa_org_name",
        "RPA营业部全称",
        populated_only=True,
    )

    existing = db.query(OrganizationMapping).filter(
        OrganizationMapping.company_id == current_company_id()
    ).count()
    try:
        db.query(OrganizationMapping).filter(
            OrganizationMapping.company_id == current_company_id()
        ).delete(synchronize_session=False)
        for values in prepared.values():
            values = {key: value for key, value in values.items() if key != "row_number"}
            db.add(OrganizationMapping(**values))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"updated": len(prepared), "deleted": existing}


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
            "RPA搜索结果序号": item.rpa_search_result_index,
            "所属分公司": item.parent_branch,
            "银行子目": item.bank_subaccount,
            "银行账号": item.bank_account,
        }
        for item in db.query(OrganizationMapping).filter(OrganizationMapping.company_id == current_company_id()).order_by(OrganizationMapping.org_code).all()
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="机构名称维护表", index=False)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%9C%BA%E6%9E%84%E5%90%8D%E7%A7%B0%E7%BB%B4%E6%8A%A4%E8%A1%A8.xlsx"},
    )
