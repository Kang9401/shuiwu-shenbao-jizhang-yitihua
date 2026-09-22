from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import (
    FmssApiError, FmssDecisionFailed, FmssError, FmssImportFailed, FmssStateConflict,
    FmssSubmitFailed, FmssWriteDisabled,
)
from app.integrations.fmss.iit.sheets import list_sheets
from app.models.core import Company, Period
from app.models.pit_reconciliation import PitReconciliationWorkpaper
from app.services.pit_fmss_excel import PitFmssExcelBuilder
from app.services.pit_fmss_mapper import PitFmssMapper


def fmss_stage(local_stage: str) -> str:
    return "PRE" if local_stage == "pre_payment" else "POST"


def declaration_document(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("document", "declaration"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload if payload.get("id") is not None or payload.get("declarationId") is not None else None


def declaration_status(payload: Any) -> str:
    document = declaration_document(payload)
    return str((document or {}).get("status") or "NOT_SUBMITTED")


def declaration_id(payload: Any) -> str | None:
    document = declaration_document(payload) or {}
    value = document.get("id") or document.get("declarationId")
    return str(value) if value is not None else None


def _import_document_id(payload: Any, branch_code: str) -> str | None:
    data = payload if isinstance(payload, dict) else {}
    documents = data.get("documents") or []
    if isinstance(documents, dict):
        documents = [documents]
    for document in documents:
        if not isinstance(document, dict):
            continue
        if str(document.get("branchCode") or "") != str(branch_code):
            continue
        value = document.get("id") or document.get("declarationId")
        if value is not None:
            return str(value)
    return None


def _skipped_sheets(payload: Any) -> list[str]:
    data = payload if isinstance(payload, dict) else {}
    sheets = data.get("sheets") or {}
    items = sheets.items() if isinstance(sheets, dict) else ((str(index), item) for index, item in enumerate(sheets))
    return [str(name) for name, result in items if isinstance(result, dict) and int(result.get("skipped") or 0) > 0]


class PitOnlineService:
    def __init__(self, db: Session, client: FmssClient | None = None) -> None:
        self.db = db
        self.client = client or FmssClient()

    def _context(self, company_id: int, period_id: int) -> tuple[Company, Period]:
        company = self.db.query(Company).filter_by(id=company_id).one()
        period = self.db.query(Period).filter_by(id=period_id, company_id=company_id).one()
        if not company.fmss_branch_code:
            raise FmssStateConflict("当前本地公司尚未绑定FMSS申报分公司。")
        return company, period

    def query_declaration(self, company_id: int, period_id: int, stage: str) -> tuple[Any, str]:
        company, period = self._context(company_id, period_id)
        payload = self.client.declaration(company.fmss_branch_code, f"{period.year}-{period.month:02d}", fmss_stage(stage))
        return payload, declaration_status(payload)

    def sync_workpaper(self, workpaper: PitReconciliationWorkpaper) -> dict[str, Any]:
        payload, status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        document = declaration_document(payload)
        declaration_id = (document or {}).get("id") or (document or {}).get("declarationId")
        if declaration_id is not None:
            if workpaper.platform_submission_id and workpaper.platform_submission_id != str(declaration_id):
                raise FmssStateConflict("FMSS返回的申报单ID与本地关联不一致，请联系管理员处理。")
            workpaper.platform_submission_id = str(declaration_id)
        workpaper.last_synced_at = datetime.utcnow()
        self.db.commit()
        return {"status": status, "declaration": payload, "declaration_id": workpaper.platform_submission_id}

    def enforce_editable(self, workpaper: PitReconciliationWorkpaper) -> None:
        if not workpaper.platform_submission_id:
            return
        state = self.sync_workpaper(workpaper)["status"]
        if state in {"REVIEWING", "APPROVED"}:
            raise FmssStateConflict("该底稿正在FMSS审核中或已复核通过，不能修改。")
        if state != "RETURNED":
            raise FmssStateConflict("该底稿存在FMSS线上关联，但当前状态不允许修改。")

    def prepare_pre_upload(self, workpaper: PitReconciliationWorkpaper) -> Path:
        if workpaper.stage != "pre_payment":
            raise FmssStateConflict("本轮只支持缴款前底稿线上提交。")
        payload, status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        if status in {"REVIEWING", "APPROVED"}:
            raise FmssStateConflict("该缴款前底稿正在FMSS审核中或已经复核通过，不能重新提交。")
        if status == "DRAFT":
            document = declaration_document(payload) or {}
            if not document.get("canReimport"):
                raise FmssStateConflict("FMSS线上草稿不允许重新导入，请先确认草稿处理方式。")
        company, period = self._context(workpaper.company_id, workpaper.period_id)
        sheets = list_sheets(self.client, "PRE")
        rows = PitFmssMapper().map_pre(self.db, company.id, period.id, workpaper.id, sheets)
        return PitFmssExcelBuilder().build(sheets, rows)

    def _assert_write_enabled(self, stage: str) -> None:
        if not settings.fmss_write_enabled:
            raise FmssWriteDisabled()
        if stage == "POST" and not settings.fmss_post_write_enabled:
            raise FmssWriteDisabled("FMSS缴款后写入功能未启用。")
        if settings.fmss_environment.strip().lower() not in {"dev", "development", "test"} and not settings.fmss_production_write_enabled:
            raise FmssWriteDisabled("生产FMSS写入尚未单独启用。")

    def _assert_ready(self, workpaper: PitReconciliationWorkpaper) -> None:
        if workpaper.calculation_status != "success" or workpaper.data_status not in {"ready", "complete"}:
            raise FmssStateConflict("本地个税底稿尚未完成计算或数据准备，不能提交审核。")

    def _assert_post_prerequisite(self, workpaper: PitReconciliationWorkpaper) -> None:
        payload, status = self.query_declaration(workpaper.company_id, workpaper.period_id, "post_payment")
        company, period = self._context(workpaper.company_id, workpaper.period_id)
        pre_payload = self.client.declaration(company.fmss_branch_code, f"{period.year}-{period.month:02d}", "PRE")
        if declaration_status(pre_payload) != "APPROVED":
            raise FmssStateConflict("缴款前底稿尚未复核通过，不能提交缴款后底稿。")

    def _assert_reviewer(self, company: Company, period: Period, stage: str, reviewer: str) -> None:
        payload = self.client.reviewers(company.fmss_branch_code or "", f"{period.year}-{period.month:02d}", stage)
        rows = payload if isinstance(payload, list) else (payload.get("rows") if isinstance(payload, dict) else None)
        if not rows:
            raise FmssStateConflict("FMSS未返回可选复核人，请刷新复核人列表。")
        usernames = set()
        for row in rows:
            if isinstance(row, str):
                usernames.add(row.strip())
            elif isinstance(row, dict):
                for key in ("username", "userName", "loginName", "account", "code"):
                    if row.get(key):
                        usernames.add(str(row[key]).strip())
                        break
        if usernames and reviewer not in usernames:
            raise FmssStateConflict("所选复核人不是FMSS当前可用账号。")

    def submit_pre_workpaper(self, workpaper: PitReconciliationWorkpaper, reviewer: str) -> dict[str, Any]:
        return self.submit_workpaper(workpaper, reviewer)

    def submit_workpaper(self, workpaper: PitReconciliationWorkpaper, reviewer: str) -> dict[str, Any]:
        stage = fmss_stage(workpaper.stage)
        self._assert_write_enabled(stage)
        self._assert_ready(workpaper)
        reviewer = reviewer.strip()
        if not reviewer:
            raise FmssStateConflict("请选择FMSS复核人账号。")
        if stage == "POST":
            self._assert_post_prerequisite(workpaper)
            raise FmssStateConflict("缴款后四张FMSS工作表的本地数据边界尚未确认，暂不开放提交。")
        path: Path | None = None
        imported_id: str | None = None
        try:
            path = self.prepare_pre_upload(workpaper)
            company, period = self._context(workpaper.company_id, workpaper.period_id)
            try:
                imported = self.client.import_iit_workbook(company.fmss_branch_code, f"{period.year}-{period.month:02d}", stage, path)
            except FmssApiError as exc:
                # Import has an unknown result on timeout/reset.  Re-query once;
                # never repeat the multipart POST automatically.
                try:
                    current, current_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
                    if current_status == "DRAFT":
                        raise FmssImportFailed("数据导入FMSS后提交审核未完成，请重新获取线上状态。") from exc
                except FmssImportFailed:
                    raise
                except Exception:
                    pass
                raise FmssImportFailed("FMSS导入失败，请检查线上状态后重试。") from exc
            skipped = _skipped_sheets(imported)
            if skipped:
                raise FmssImportFailed("FMSS导入存在跳过记录，请检查后重新操作。")
            imported_id = _import_document_id(imported, company.fmss_branch_code)
            if not imported_id:
                raise FmssImportFailed("FMSS导入未返回当前申报分公司的申报单ID。")
            current, current_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
            current_id = declaration_id(current)
            if current_id != imported_id:
                raise FmssImportFailed("FMSS导入返回的申报单与查询结果不一致。")
            if current_status != "DRAFT":
                raise FmssStateConflict(f"FMSS导入后当前状态为{current_status}，未进入线上草稿。")
            self._assert_reviewer(company, period, stage, reviewer)
            try:
                self.client.submit_iit_declaration(imported_id, reviewer)
            except FmssApiError as exc:
                _, after_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
                if after_status == "REVIEWING":
                    return self.sync_workpaper(workpaper)
                raise FmssSubmitFailed("数据已导入FMSS，但提交审核未完成。") from exc
            confirmed, confirmed_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
            if confirmed_status != "REVIEWING":
                raise FmssSubmitFailed(f"FMSS提交接口已响应，但当前状态为{confirmed_status}。")
            result = self.sync_workpaper(workpaper)
            workpaper.last_submitted_revision = workpaper.draft_revision
            workpaper.last_submitted_at = datetime.utcnow()
            workpaper.workflow_status = "submitted"
            self.db.commit()
            result["declaration"] = confirmed
            return result
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    def decide_workpaper(self, workpaper: PitReconciliationWorkpaper, passed: bool, comment: str) -> dict[str, Any]:
        self._assert_write_enabled(fmss_stage(workpaper.stage))
        if not workpaper.platform_submission_id:
            raise FmssStateConflict("当前底稿没有FMSS申报单关联。")
        comment = comment.strip()
        if not passed and not comment:
            raise FmssDecisionFailed("退回原因必填。")
        try:
            self.client.decide_iit_declaration(workpaper.platform_submission_id, passed, comment)
        except FmssApiError as exc:
            current, current_status = self._confirm_decision_state(workpaper)
            expected = "APPROVED" if passed else "RETURNED"
            if current_status == expected:
                return self.sync_workpaper(workpaper)
            raise FmssDecisionFailed(f"FMSS已响应审核操作，但当前状态为{current_status}，请刷新状态确认。") from exc
        current, current_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        expected = "APPROVED" if passed else "RETURNED"
        if current_status != expected:
            raise FmssDecisionFailed(f"FMSS审核操作已响应，但当前状态为{current_status}，请刷新状态确认。")
        result = self.sync_workpaper(workpaper)
        workpaper.workflow_status = "reviewed" if passed else "returned"
        self.db.commit()
        result["declaration"] = current
        return result

    def _confirm_decision_state(self, workpaper: PitReconciliationWorkpaper) -> tuple[Any, str]:
        """Re-read all decision views after an unknown POST result.

        Declaration status is authoritative. The review and approval-log reads
        refresh the same server-side views used by the review page, but a
        transient failure in either auxiliary read must not hide a confirmed
        declaration status.
        """
        current, current_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        if not workpaper.platform_submission_id:
            return current, current_status
        try:
            self.client.review(workpaper.platform_submission_id)
        except FmssError:
            pass
        try:
            company, period = self._context(workpaper.company_id, workpaper.period_id)
            self.client.approval_log(company.fmss_branch_code or "", f"{period.year}-{period.month:02d}")
        except FmssError:
            pass
        return current, current_status
