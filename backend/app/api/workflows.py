from __future__ import annotations

import io
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company
from app.models.core import Company
from app.models.accounting import OrganizationMapping
from app.workflows import list_workflows

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("")
def get_workflows() -> list[dict]:
    return [
        {
            "code": workflow.info.code,
            "name": workflow.info.name,
            "domain": workflow.info.domain,
            "description": workflow.info.description,
            "required_file_roles": workflow.info.required_file_roles,
        }
        for workflow in list_workflows()
    ]


@router.get("/intern-tax/template")
def download_intern_template(
    db: Session = Depends(get_db),
    _company: Company = Depends(require_company),
) -> Response:
    columns = [
        "机构代码", "营业部名称", "*姓名", "*证件类型", "*证件号码", "*国籍(地区)", "*性别",
        "*出生日期", "实习开始时间", "实习结束时间", "发放补贴数（元）", "联系方式", "备注",
    ]
    mappings = db.query(OrganizationMapping).filter(OrganizationMapping.active == 1).order_by(OrganizationMapping.org_code).all()
    instructions = pd.DataFrame([
        {"字段": "机构代码", "填写说明": "5位数字；与营业部名称至少填写一项，同时填写时必须匹配"},
        {"字段": "*证件类型", "填写说明": "居民身份证、中国护照、港澳居民来往内地通行证、台湾居民来往大陆通行证或外国护照"},
        {"字段": "*国籍(地区)、*性别、*出生日期", "填写说明": "非居民身份证人员必填"},
        {"字段": "发放补贴数（元）", "填写说明": "允许0和负数，系统会在页面提醒"},
    ])
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(columns=columns).to_excel(writer, sheet_name="实习生导入", index=False)
        instructions.to_excel(writer, sheet_name="填写说明", index=False)
        pd.DataFrame([{"机构代码": item.org_code, "营业部名称": item.branch_name} for item in mappings]).to_excel(
            writer, sheet_name="机构映射", index=False
        )
    filename = "实习生申报导入模板.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
