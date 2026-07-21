from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.accounting import CertificationLedger, InvoiceLedger, VoucherDraft
from app.models.core import UploadedFile
from app.services.excel import (
    dataframe_records,
    pick_column,
    read_excel,
    to_decimal,
    write_workbook,
)
from app.services.formulas import (
    merge_duplicate_invoice_lines,
)
from app.services.storage import artifact_path
from app.workflows.base import WorkflowInfo, WorkflowResult


class ExcelWorkflow:
    info: WorkflowInfo
    tax_category = "个税"

    def _read_all(self, files: List[UploadedFile]) -> List[tuple[UploadedFile, pd.DataFrame]]:
        return [(file, read_excel(file.stored_path)) for file in files]

    def _read_by_role(self, files: List[UploadedFile]) -> Dict[str, pd.DataFrame]:
        frames: Dict[str, List[pd.DataFrame]] = {}
        for file in files:
            frames.setdefault(file.file_role, []).append(read_excel(file.stored_path))
        return {
            role: pd.concat(role_frames, ignore_index=True, sort=False)
            if len(role_frames) > 1
            else role_frames[0]
            for role, role_frames in frames.items()
        }

    def _issue_status(self, issues: List[Dict[str, Any]]) -> str:
        return "needs_review" if issues else "success"


class InvoiceWorkflow(ExcelWorkflow):
    info: WorkflowInfo

    def run(
        self,
        db: Session,
        job_id: int,
        period_id: Optional[int],
        files: List[UploadedFile],
    ) -> WorkflowResult:
        frames = self._read_all(files)
        raw = pd.concat([frame for _, frame in frames], ignore_index=True, sort=False) if frames else pd.DataFrame()
        combined, duplicate_rows = merge_duplicate_invoice_lines(
            raw,
            key_cols=["发票代码", "发票号码", "数电票号码（全电票必录）"],
            sum_cols=["票面无税", "票面税额", "实际入账金额", "不含税额", "抵扣税额", "票面合计", "可抵扣税额", "金额", "税额"],
        )
        records = dataframe_records(combined)
        duplicate_keys: set[str] = set()
        seen: set[str] = set()
        for row in records:
            invoice_no = str(pick_column(row, ["发票号码", "发票号", "数电票号码（全电票必录）", "invoice_no"]) or "").strip()
            if invoice_no:
                if invoice_no in seen:
                    duplicate_keys.add(invoice_no)
                seen.add(invoice_no)
            db.add(
                InvoiceLedger(
                    period_id=period_id,
                    job_id=job_id,
                    invoice_no=invoice_no or None,
                    seller_name=pick_column(row, ["销售方名称", "销方名称", "销售方纳税人名称（被扣缴义务人名称）", "seller_name"]),
                    buyer_name=pick_column(row, ["购买方名称", "购方名称", "buyer_name"]),
                    invoice_date=str(pick_column(row, ["开票日期", "发票日期", "开票日期（必录）", "invoice_date"]) or ""),
                    amount=to_decimal(pick_column(row, ["金额", "价税合计", "合计金额", "票面无税", "amount"])),
                    tax_amount=to_decimal(pick_column(row, ["税额", "票面税额", "tax_amount"])),
                    status="duplicate_merged" if invoice_no in duplicate_keys else "draft",
                    raw_data=row,
                )
            )

        issues = [
            {"issue_type": "重复发票", "field": "发票号码", "message": f"发票号码重复并已合并：{key}"}
            for key in sorted(duplicate_keys)
        ]
        if not duplicate_rows.empty:
            issues.append({"issue_type": "重复发票", "message": f"发现重复发票明细 {len(duplicate_rows)} 行，已按发票号合并金额"})

        output = artifact_path(job_id, f"{self.info.code}_发票台账.xlsx")
        write_workbook(output, {"发票台账": combined, "重复明细": duplicate_rows, "校验问题": pd.DataFrame(issues)})
        return WorkflowResult(
            status=self._issue_status(issues),
            summary={"rows": len(records), "duplicate_invoices": int(len(duplicate_rows)), "issues": len(issues)},
            artifact_paths=[("invoice_ledger", str(output))],
        )


class CertificationWorkflow(ExcelWorkflow):
    def run(
        self,
        db: Session,
        job_id: int,
        period_id: Optional[int],
        files: List[UploadedFile],
    ) -> WorkflowResult:
        frames = self._read_all(files)
        combined = pd.concat([frame for _, frame in frames], ignore_index=True, sort=False) if frames else pd.DataFrame()
        records = dataframe_records(combined)
        issues: List[Dict[str, Any]] = []
        for idx, row in enumerate(records, start=2):
            booking_amount = to_decimal(pick_column(row, ["记账金额", "本位币借方", "金额", "价税合计"]))
            tax_amount = to_decimal(pick_column(row, ["税务金额", "认证金额", "税额", "税局金额"]))
            match_status = "matched"
            issue_type = None
            if booking_amount is not None and tax_amount is not None and booking_amount != tax_amount:
                match_status = "amount_mismatch"
                issue_type = "金额不一致"
                issues.append({"issue_type": issue_type, "row": idx, "message": "记账金额和税务金额不一致"})
            db.add(
                CertificationLedger(
                    period_id=period_id,
                    job_id=job_id,
                    invoice_no=pick_column(row, ["发票号码", "发票号", "弹性域14", "invoice_no"]),
                    booking_amount=booking_amount,
                    tax_amount=tax_amount,
                    match_status=match_status,
                    issue_type=issue_type,
                    raw_data=row,
                )
            )
        output = artifact_path(job_id, f"{self.info.code}_认证核对.xlsx")
        write_workbook(output, {"认证核对": combined, "校验问题": pd.DataFrame(issues)})
        return WorkflowResult(
            status=self._issue_status(issues),
            summary={"rows": len(records), "amount_mismatches": len(issues), "issues": len(issues)},
            artifact_paths=[("certification_ledger", str(output))],
        )


class VoucherDraftWorkflow(ExcelWorkflow):
    def run(
        self,
        db: Session,
        job_id: int,
        period_id: Optional[int],
        files: List[UploadedFile],
    ) -> WorkflowResult:
        frames = self._read_all(files)
        combined = pd.concat([frame for _, frame in frames], ignore_index=True, sort=False) if frames else pd.DataFrame()
        drafts: List[Dict[str, Any]] = []
        for row in dataframe_records(combined):
            amount = to_decimal(pick_column(row, ["价税合计", "金额", "税额", "票面税额", "amount"]))
            summary = str(pick_column(row, ["摘要", "销售方名称", "纳税人名称", "姓名"]) or "税务申报记账草稿")
            draft = {
                "摘要": summary,
                "借方科目": "应交税费",
                "贷方科目": "银行存款/应付账款",
                "金额": amount,
                "状态": "draft",
            }
            drafts.append(draft)
            db.add(
                VoucherDraft(
                    period_id=period_id,
                    job_id=job_id,
                    source_type=self.info.code,
                    debit_account=draft["借方科目"],
                    credit_account=draft["贷方科目"],
                    amount=amount,
                    summary=summary,
                    status="draft",
                    raw_data=row,
                )
            )
        output = artifact_path(job_id, "voucher_draft_凭证草稿.xlsx")
        write_workbook(output, {"凭证草稿": pd.DataFrame(drafts)})
        return WorkflowResult(
            status="success",
            summary={"rows": len(drafts), "draft_vouchers": len(drafts), "issues": 0},
            artifact_paths=[("voucher_draft", str(output))],
        )
