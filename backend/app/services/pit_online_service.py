from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
from typing import Any

import openpyxl
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.fmss.branch_code import to_fmss_branch_code
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import (
    FmssApiError, FmssDecisionFailed, FmssError, FmssImportFailed, FmssStateConflict,
    FmssSubmitFailed, FmssWriteDisabled,
)
from app.integrations.fmss.iit.sheets import list_sheets
from app.integrations.fmss.iit.schemas import FmssSheet
from app.models.core import Company, Period
from app.models.accounting import ReconciliationImportBatch, ReconciliationImportRow
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


def _sheet_results(payload: Any) -> dict[str, dict[str, Any]]:
    data = payload if isinstance(payload, dict) else {}
    sheets = data.get("sheets") or {}
    if isinstance(sheets, dict):
        return {str(name): result for name, result in sheets.items() if isinstance(result, dict)}
    return {str(index): result for index, result in enumerate(sheets) if isinstance(result, dict)}


def _result_for_sheet(results: dict[str, dict[str, Any]], sheet: FmssSheet) -> dict[str, Any] | None:
    return results.get(sheet.key) or results.get(sheet.title) or results.get(sheet.title[:31])


def _workbook_row_counts(path: Path, sheets: list[FmssSheet]) -> dict[str, int]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        counts: dict[str, int] = {}
        for sheet in sheets:
            worksheet = workbook[sheet.title[:31]]
            counts[sheet.key] = max(worksheet.max_row - 1, 0)
        return counts
    finally:
        workbook.close()


def _assert_post_import_counts(payload: Any, path: Path, sheets: list[FmssSheet]) -> dict[str, int]:
    expected = _workbook_row_counts(path, sheets)
    results = _sheet_results(payload)
    for sheet in sheets:
        result = _result_for_sheet(results, sheet)
        if result is None:
            raise FmssImportFailed(f"FMSS导入结果缺少工作表 {sheet.key}。")
        imported = int(result.get("imported") or 0)
        if imported != expected[sheet.key]:
            raise FmssImportFailed(f"FMSS工作表 {sheet.key} 导入行数不一致。")
    return expected

def _assert_declaration_counts(payload: Any, expected: dict[str, int], sheets: list[FmssSheet]) -> None:
    document = declaration_document(payload) or {}
    raw_sheets = document.get("sheets") or (payload.get("sheets") if isinstance(payload, dict) else None)
    if not isinstance(raw_sheets, dict):
        return
    for sheet in sheets:
        result = raw_sheets.get(sheet.key) or raw_sheets.get(sheet.title) or raw_sheets.get(sheet.title[:31])
        if not isinstance(result, dict):
            continue
        value = result.get("rowCount", result.get("row_count", result.get("total")))
        if value is not None and int(value) != expected[sheet.key]:
            raise FmssImportFailed(f"FMSS申报单工作表 {sheet.key} 回读行数不一致。")


class PitOnlineService:
    def __init__(self, db: Session, client: FmssClient | None = None) -> None:
        self.db = db
        self.client = client or FmssClient()

    def _context(self, company_id: int, period_id: int) -> tuple[Company, Period]:
        company = self.db.query(Company).filter_by(id=company_id).one()
        period = self.db.query(Period).filter_by(id=period_id, company_id=company_id).one()
        return company, period

    @staticmethod
    def fmss_branch_code(company: Company) -> str:
        return to_fmss_branch_code(company.code)

    def query_declaration(self, company_id: int, period_id: int, stage: str) -> tuple[Any, str]:
        company, period = self._context(company_id, period_id)
        payload = self.client.declaration(self.fmss_branch_code(company), f"{period.year}-{period.month:02d}", fmss_stage(stage))
        return payload, declaration_status(payload)

    def sync_workpaper(self, workpaper: PitReconciliationWorkpaper) -> dict[str, Any]:
        payload, status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        document = declaration_document(payload)
        declaration_id = (document or {}).get("id") or (document or {}).get("declarationId")
        if declaration_id is not None:
            if workpaper.platform_submission_id and workpaper.platform_submission_id != str(declaration_id):
                raise FmssStateConflict("FMSS返回的申报单ID与本地关联不一致，请联系管理员处理。")
            workpaper.platform_submission_id = str(declaration_id)
        if status == "REVIEWING":
            workpaper.workflow_status = "submitted"
        elif status == "APPROVED":
            workpaper.workflow_status = "reviewed"
        elif status == "RETURNED":
            workpaper.workflow_status = "returned"
        elif status == "DRAFT":
            workpaper.workflow_status = "pending_submission" if workpaper.data_status in {"ready", "complete"} else "data_preparation"
        workpaper.last_synced_at = datetime.utcnow()
        self.db.commit()
        double_review_completed = False
        if status == "APPROVED":
            other_stage = "post_payment" if workpaper.stage == "pre_payment" else "pre_payment"
            _, other_status = self.query_declaration(workpaper.company_id, workpaper.period_id, other_stage)
            double_review_completed = other_status == "APPROVED"
        return {
            "status": status,
            "declaration": payload,
            "declaration_id": workpaper.platform_submission_id,
            "double_review_completed": double_review_completed,
        }

    def enforce_editable(self, workpaper: PitReconciliationWorkpaper) -> None:
        had_online_id = bool(workpaper.platform_submission_id)
        state = self.sync_workpaper(workpaper)["status"]
        if state in {"REVIEWING", "APPROVED"}:
            raise FmssStateConflict("该底稿正在FMSS审核中或已复核通过，不能修改。")
        if state == "NOT_SUBMITTED" and had_online_id:
            raise FmssStateConflict("该底稿存在FMSS线上关联，但当前线上状态无法确认，已保守锁定。")
        if state not in {"NOT_SUBMITTED", "DRAFT", "RETURNED"}:
            raise FmssStateConflict("该底稿存在FMSS线上关联，但当前状态不允许修改。")

    def prepare_pre_upload(self, workpaper: PitReconciliationWorkpaper) -> Path:
        if workpaper.stage != "pre_payment":
            raise FmssStateConflict("本轮只支持缴款前底稿线上提交。")
        payload, status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        if status in {"REVIEWING", "APPROVED"}:
            raise FmssStateConflict("该缴款前底稿正在FMSS审核中或已经复核通过，不能重新提交。")
        company, period = self._context(workpaper.company_id, workpaper.period_id)
        sheets = list_sheets(self.client, "PRE")
        rows = PitFmssMapper().map_pre(self.db, company.id, period.id, workpaper.id, sheets)
        return PitFmssExcelBuilder().build(sheets, rows, prefix="iit-pre")

    def prepare_post_upload(self, workpaper: PitReconciliationWorkpaper) -> Path:
        path, _ = self._prepare_post_upload(workpaper)
        return path

    def _prepare_post_upload(self, workpaper: PitReconciliationWorkpaper) -> tuple[Path, list[FmssSheet]]:
        if workpaper.stage != "post_payment":
            raise FmssStateConflict("当前底稿不是缴款后阶段。")
        _, post_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        if post_status in {"REVIEWING", "APPROVED"}:
            raise FmssStateConflict("该缴款后底稿正在FMSS审核中或已经复核通过，不能重新提交。")
        self._assert_post_prerequisite(workpaper)
        company, period = self._context(workpaper.company_id, workpaper.period_id)
        sheets = list_sheets(self.client, "POST")
        rows = PitFmssMapper().map_post(self.db, company.id, period.id, workpaper.id, sheets)
        return PitFmssExcelBuilder().build(sheets, rows, prefix="iit-post"), sheets

    def _assert_write_enabled(self, stage: str) -> None:
        if not settings.fmss_write_enabled:
            raise FmssWriteDisabled()
        if stage == "POST" and not settings.fmss_post_write_enabled:
            raise FmssWriteDisabled("FMSS缴款后写入功能未启用。")
        if settings.fmss_environment.strip().lower() not in {"dev", "development", "test"} and not settings.fmss_production_write_enabled:
            raise FmssWriteDisabled("生产FMSS写入尚未单独启用。")

    def _assert_post_prerequisite(self, workpaper: PitReconciliationWorkpaper) -> None:
        company, period = self._context(workpaper.company_id, workpaper.period_id)
        pre_payload = self.client.declaration(self.fmss_branch_code(company), f"{period.year}-{period.month:02d}", "PRE")
        if declaration_status(pre_payload) != "APPROVED":
            raise FmssStateConflict("缴款前底稿尚未复核通过，不能提交缴款后底稿。")

    def _certificate_upload_paths(self, workpaper: PitReconciliationWorkpaper) -> list[Path]:
        batch = (
            self.db.query(ReconciliationImportBatch)
            .filter_by(company_id=workpaper.company_id, period_id=workpaper.period_id, import_type="tax_certificate")
            .order_by(ReconciliationImportBatch.created_at.desc(), ReconciliationImportBatch.id.desc())
            .first()
        )
        if batch is None or not batch.stored_path:
            raise FmssStateConflict("当前缴款后底稿没有可绑定的本地完税凭证文件。")
        source_paths = [Path(value) for value in batch.stored_path.split(";") if value]
        if not source_paths or any(not path.is_file() for path in source_paths):
            raise FmssStateConflict("本地完税凭证源文件不存在，不能提交FMSS。")
        rows = self.db.query(ReconciliationImportRow).filter_by(batch_id=batch.id).order_by(ReconciliationImportRow.row_number).all()
        rows_by_name: dict[str, list[ReconciliationImportRow]] = {}
        for row in rows:
            name = str((row.raw_data or {}).get("file_name") or "").strip()
            if name:
                rows_by_name.setdefault(name, []).append(row)
        names = list(rows_by_name)
        if len(source_paths) != len(names):
            raise FmssStateConflict("本地完税凭证文件与解析记录无法一一对应，不能自动绑定。")
        directory = settings.temp_dir / "fmss" / "certificates"
        directory.mkdir(parents=True, exist_ok=True)
        _, period = self._context(workpaper.company_id, workpaper.period_id)
        month = f"{period.year}-{period.month:02d}"
        copies: list[Path] = []
        try:
            for source, original_name in zip(source_paths, names):
                matched = rows_by_name[original_name]
                org_code = next((str(row.organization_code).strip() for row in matched if row.organization_code), "")
                if not org_code:
                    raise FmssStateConflict(f"完税凭证 {original_name} 未识别机构代码，不能绑定FMSS。")
                suffix = source.suffix.lower()
                if suffix != ".pdf":
                    raise FmssStateConflict(f"完税凭证 {original_name} 不是PDF文件，不能绑定FMSS。")
                stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", Path(original_name).stem).strip("_") or "完税凭证"
                target = directory / f"{org_code}_{month}_{stem}{suffix}"
                shutil.copy2(source, target)
                copies.append(target)
            return copies
        except Exception:
            for path in copies:
                path.unlink(missing_ok=True)
            raise

    def _upload_post_certificates(self, declaration_id: str, workpaper: PitReconciliationWorkpaper) -> dict[str, Any]:
        copies = self._certificate_upload_paths(workpaper)
        expected_count = len(copies)
        try:
            result = self.client.upload_iit_certificates(declaration_id, copies)
        finally:
            for path in copies:
                path.unlink(missing_ok=True)
        if not isinstance(result, dict):
            raise FmssStateConflict("FMSS完税凭证上传返回格式异常。")
        results = result.get("results") or []
        if not isinstance(results, list) or not results:
            raise FmssStateConflict("FMSS完税凭证上传未返回逐文件结果。")
        failed = [row for row in results if not isinstance(row, dict) or str(row.get("status") or "").upper() not in {"SUCCESS", "REPLACED"}]
        if failed:
            raise FmssStateConflict("FMSS存在未成功绑定的完税凭证，已停止提交审核。")
        bound = self.client.certificates(declaration_id)
        bound_rows: list[Any] = []
        if isinstance(bound, list):
            bound_rows = bound
        elif isinstance(bound, dict):
            for key in ("rows", "certificates", "files"):
                candidate = bound.get(key)
                if isinstance(candidate, list):
                    bound_rows = candidate
                    break
        file_ids = [row.get("fileId") for row in bound_rows if isinstance(row, dict) and row.get("fileId") is not None]
        if len(file_ids) < expected_count:
            raise FmssStateConflict("FMSS完税凭证上传后未完成全部绑定，已停止提交审核。")
        return {"upload": result, "bound": bound, "uploaded_count": expected_count, "bound_file_ids": file_ids}

    def _post_certificate_file_ids(self, workpaper: PitReconciliationWorkpaper) -> dict[str, Any]:
        batch = (
            self.db.query(ReconciliationImportBatch)
            .filter_by(company_id=workpaper.company_id, period_id=workpaper.period_id, import_type="tax_certificate")
            .order_by(ReconciliationImportBatch.created_at.desc(), ReconciliationImportBatch.id.desc())
            .first()
        )
        results = batch.file_results if batch is not None and isinstance(batch.file_results, list) else []
        failed = [str(item.get("file_name") or "") for item in results if isinstance(item, dict) and (item.get("status") != "success" or item.get("fmss_file_id") is None)]
        if failed:
            raise FmssStateConflict(f"完税凭证未全部上传FMSS：{'、'.join(name for name in failed if name)}")
        mapping = {
            str(item.get("file_name")).strip(): item.get("fmss_file_id")
            for item in results if isinstance(item, dict) and item.get("file_name") and item.get("fmss_file_id") is not None
        }
        if not mapping:
            raise FmssStateConflict("当前缴款后底稿没有已上传FMSS的完税凭证。")
        return mapping

    @staticmethod
    def _assert_post_certificate_file_ids(payload: Any, expected: dict[str, Any]) -> dict[str, Any]:
        document = declaration_document(payload) or {}
        sheets = document.get("sheets") or (payload.get("sheets") if isinstance(payload, dict) else None)
        sheet = sheets.get("iit_post_certificate") if isinstance(sheets, dict) else None
        if isinstance(sheet, dict):
            sheet = sheet.get("rows") or sheet.get("data") or sheet.get("values")
        if not isinstance(sheet, list):
            raise FmssImportFailed("FMSS完税凭证文件绑定失败，已停止提交审核。")
        for file_name, expected_id in expected.items():
            matched = []
            for row in sheet:
                if isinstance(row, (list, tuple)) and len(row) > 9 and str(row[1] or "").strip() == file_name:
                    matched.append(row[9])
                elif isinstance(row, dict):
                    row_name = row.get("fileName") or row.get("file_name") or row.get("文件名")
                    row_id = row.get("fileId") or row.get("file_id")
                    if str(row_name or "").strip() == file_name:
                        matched.append(row_id)
            if not matched or any(str(value) != str(expected_id) for value in matched):
                raise FmssImportFailed("FMSS完税凭证文件绑定失败，已停止提交审核。")
        return {"file_ids": expected, "matched_rows": sum(1 for row in sheet if isinstance(row, (list, tuple)) and len(row) > 9)}

    def _reviewing_approval_id(self, company: Company, period: Period, declaration_id: str, reviewer: str) -> str | None:
        payload = self.client.approval_log(self.fmss_branch_code(company), f"{period.year}-{period.month:02d}")
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        candidates = [
            row for row in rows if isinstance(row, dict)
            and str(row.get("declarationId")) == declaration_id
            and str(row.get("stage")) == "POST"
            and str(row.get("approvalStatus")) == "REVIEWING"
            and str(row.get("reviewer") or "").strip() == reviewer
        ]
        if not candidates:
            return None
        value = candidates[-1].get("approvalId") or candidates[-1].get("currentApprovalId")
        return str(value) if value is not None else None

    def _assert_reviewer(self, company: Company, period: Period, stage: str, reviewer: str) -> None:
        payload = self.client.reviewers(self.fmss_branch_code(company), f"{period.year}-{period.month:02d}", stage)
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
        reviewer = reviewer.strip()
        if not reviewer:
            raise FmssStateConflict("请选择FMSS复核人账号。")
        path: Path | None = None
        imported_id: str | None = None
        post_sheets: list[FmssSheet] | None = None
        try:
            if stage == "POST":
                path, post_sheets = self._prepare_post_upload(workpaper)
            else:
                path = self.prepare_pre_upload(workpaper)
            company, period = self._context(workpaper.company_id, workpaper.period_id)
            branch_code = self.fmss_branch_code(company)
            try:
                imported = self.client.import_iit_workbook(branch_code, f"{period.year}-{period.month:02d}", stage, path)
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
            expected_post_rows = _assert_post_import_counts(imported, path, post_sheets) if stage == "POST" and post_sheets else None
            imported_id = _import_document_id(imported, branch_code)
            if not imported_id:
                raise FmssImportFailed("FMSS导入未返回当前申报分公司的申报单ID。")
            current, current_status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
            current_id = declaration_id(current)
            if current_id != imported_id:
                raise FmssImportFailed("FMSS导入返回的申报单与查询结果不一致。")
            if current_status != "DRAFT":
                raise FmssStateConflict(f"FMSS导入后当前状态为{current_status}，未进入线上草稿。")
            if expected_post_rows is not None:
                _assert_declaration_counts(current, expected_post_rows, post_sheets or [])
            certificate_result = self._assert_post_certificate_file_ids(current, self._post_certificate_file_ids(workpaper)) if stage == "POST" else None
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
            if certificate_result is not None:
                result["certificates"] = certificate_result
                result["approval_id"] = self._reviewing_approval_id(company, period, imported_id, reviewer)
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

    def withdraw_workpaper(self, workpaper: PitReconciliationWorkpaper) -> dict[str, Any]:
        self._assert_write_enabled(fmss_stage(workpaper.stage))
        if not workpaper.platform_submission_id:
            raise FmssStateConflict("当前底稿没有FMSS申报单关联。")
        try:
            self.client.withdraw_iit_declaration(workpaper.platform_submission_id)
        except FmssApiError as exc:
            _, status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
            if status == "DRAFT":
                return self.sync_workpaper(workpaper)
            raise FmssStateConflict("FMSS撤回未完成，请刷新线上状态确认。") from exc
        _, status = self.query_declaration(workpaper.company_id, workpaper.period_id, workpaper.stage)
        if status != "DRAFT":
            raise FmssStateConflict(f"FMSS撤回接口已响应，但当前状态为{status}。")
        return self.sync_workpaper(workpaper)

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
            self.client.approval_log(self.fmss_branch_code(company), f"{period.year}-{period.month:02d}")
        except FmssError:
            pass
        return current, current_status
