from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.accounting import ReconciliationImportBatch
from app.models.core import Period, UploadedFile
from app.services.excel import write_workbook
from app.services.formulas import (
    annual_bonus_transform,
    BROKER_DECLARATION_COLUMNS,
    broker_tax_transform,
    first_existing,
    general_salary_tax_transform,
    intern_tax_transform,
    INTERN_DECLARATION_COLUMNS,
    restricted_stock_interest_transform,
)
from app.services.personnel_master import (
    PersonnelMasterResolver,
    copy_previous_month_personnel_master_if_missing,
)
from app.services.organization_mapping import active_mapping_dict
from app.services.reconciliation_import import read_balance_sheet
from app.services.personnel_update import (
    PersonnelUpdateValidationError,
    apply_staff_info_update,
    build_personnel_collection_files,
)
from app.services.storage import artifact_path
from app.workflows.base import WorkflowInfo, WorkflowResult
from app.workflows.common import (
    CertificationWorkflow,
    ExcelWorkflow,
    InvoiceWorkflow,
    VoucherDraftWorkflow,
)


TransformFunc = Callable[[dict[str, pd.DataFrame]], dict[str, Any]]


def _period_year_month(db: Session, period_id: Optional[int]) -> tuple[int, int]:
    if period_id is not None:
        period = db.query(Period).filter(Period.id == period_id).first()
        if period:
            return period.year, period.month
    now = datetime.now()
    return now.year, now.month


def _issue_frame(issues: list[dict[str, Any]]) -> pd.DataFrame:
    if issues:
        return pd.DataFrame(issues)
    return pd.DataFrame(columns=["issue_type", "message"])


def _row_first_text(row: pd.Series, candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate not in row.index:
            continue
        value = row.get(candidate)
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return ""


def _inject_shared_staff_info(
    db: Session,
    period_id: Optional[int],
    files: list[UploadedFile],
    person_type: Optional[str],
) -> tuple[list[UploadedFile], bool]:
    if any(file.file_role == "staff_info" for file in files):
        return files, False
    if not person_type:
        return files, False
    shared = PersonnelMasterResolver(db, period_id).resolve_uploaded_file(person_type)
    if shared is None:
        return files, False
    return [*files, shared], True


def _inject_period_balance_sheet(
    db: Session,
    period_id: Optional[int],
    files: list[UploadedFile],
) -> tuple[list[UploadedFile], bool]:
    if period_id is None or any(file.file_role == "balance_sheet" for file in files):
        return files, False
    batch = (
        db.query(ReconciliationImportBatch)
        .filter(
            ReconciliationImportBatch.period_id == period_id,
            ReconciliationImportBatch.import_type == "balance_sheet",
        )
        .order_by(ReconciliationImportBatch.created_at.desc())
        .first()
    )
    if batch is None or not Path(batch.stored_path).exists():
        return files, False
    source = Path(batch.stored_path)
    return [
        *files,
        UploadedFile(
            period_id=period_id,
            file_role="balance_sheet",
            original_name=source.name,
            stored_path=str(source),
            size_bytes=source.stat().st_size,
            validation_status="shared_balance_sheet",
            validation_issues=[],
        ),
    ], True


class TaxTransformWorkflow(ExcelWorkflow):
    """Run a migrated tax transform and persist review/download workbooks."""

    info: WorkflowInfo
    transform: TransformFunc
    artifact_type = "tax_result"
    output_label = "处理结果"
    detail_sheet = "申报明细"
    summary_sheet = "汇总"
    split_file_label: Optional[str] = None
    split_artifact_type = "declaration"
    person_type: Optional[str] = None
    requires_period_balance_sheet = False
    supports_balance_reconciliation = False
    expose_issue_details = False
    role_aliases: dict[str, list[str]] = {}
    org_column_candidates = [
        "机构代码",
        "分支机构代码",
        "分支机构名称",
        "单位编号",
        "公司段",
    ]

    def _frames_with_aliases(self, files: list[UploadedFile]) -> dict[str, pd.DataFrame]:
        balance_files = [file for file in files if file.file_role == "balance_sheet"]
        frames = self._read_by_role([file for file in files if file.file_role != "balance_sheet"])
        if balance_files:
            balance_frames = [read_balance_sheet(file.stored_path) for file in balance_files]
            frames["balance_sheet"] = (
                pd.concat(balance_frames, ignore_index=True, sort=False)
                if len(balance_frames) > 1
                else balance_frames[0]
            )
        normalized = dict(frames)
        for canonical, aliases in self.role_aliases.items():
            candidates = [role for role in [canonical, *aliases] if role in frames]
            if not candidates:
                continue
            role_frames = [frames[role] for role in candidates]
            normalized[canonical] = (
                pd.concat(role_frames, ignore_index=True, sort=False)
                if len(role_frames) > 1
                else role_frames[0]
            )
            for alias in aliases:
                if alias != canonical:
                    normalized.pop(alias, None)
        return normalized

    def _write_split_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        if not self.split_file_label or detail.empty:
            return []
        org_col = first_existing(detail, self.org_column_candidates)
        if org_col is None:
            return []

        artifacts: list[tuple[str, str]] = []
        for org, group in detail.groupby(org_col, dropna=False):
            org_text = str(org or "").strip()
            if not org_text or org_text.lower() == "nan":
                continue
            file_name = f"{org_text}_{self.split_file_label}({year}年{month:02d}月).xlsx"
            output = artifact_path(job_id, file_name)
            export = group.drop(columns=[org_col], errors="ignore")
            write_workbook(output, {self.detail_sheet: export}, text_values=True)
            artifacts.append((self.split_artifact_type, str(output)))
        return artifacts

    def _write_additional_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        return []

    def _input_issues(self, files: list[UploadedFile], operation: str) -> list[dict[str, Any]]:
        return []

    def _prepare_frames(self, db: Session, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        return frames

    def run(
        self,
        db: Session,
        job_id: int,
        period_id: Optional[int],
        files: list[UploadedFile],
        operation: str = "generate",
    ) -> WorkflowResult:
        if db is not None and period_id is not None and self.person_type == "broker" and not any(file.file_role == "staff_info" for file in files):
            copy_previous_month_personnel_master_if_missing(
                db,
                period_id=period_id,
                person_type="broker",
            )
        files, used_shared_staff_info = _inject_shared_staff_info(db, period_id, files, self.person_type)
        is_balance_reconciliation = self.supports_balance_reconciliation and operation == "reconcile"
        files, used_period_balance_sheet = (
            _inject_period_balance_sheet(db, period_id, files)
            if self.requires_period_balance_sheet or is_balance_reconciliation
            else (files, False)
        )
        year, month = _period_year_month(db, period_id)
        missing_shared_staff_info = (
            self.person_type is not None
            and "staff_info" in self.info.required_file_roles
            and not any(file.file_role == "staff_info" for file in files)
        )
        result = self.transform(self._prepare_frames(db, self._frames_with_aliases(files)))
        detail = result.get("detail", pd.DataFrame())
        summary = result.get("summary", pd.DataFrame())
        issues = [*self._input_issues(files, operation), *result.get("issues", [])]
        if (self.requires_period_balance_sheet or is_balance_reconciliation) and not any(
            file.file_role == "balance_sheet" for file in files
        ):
            issues = [
                *issues,
                {"issue_type": "missing_balance_sheet", "message": "请先在核对数据导入中导入本期余额表"},
            ]
        if missing_shared_staff_info:
            issues = [
                *issues,
                {
                    "issue_type": "missing_personnel_master",
                    "message": f"请先在人员主数据页面维护 {self.person_type} 人员主数据",
                    "person_type": self.person_type,
                    **({"severity": "warning"} if self.person_type == "broker" else {}),
                },
            ]
        extra_sheets = result.get("extra_sheets", {})

        if not isinstance(detail, pd.DataFrame):
            detail = pd.DataFrame(detail)
        if not isinstance(summary, pd.DataFrame):
            summary = pd.DataFrame(summary)

        sheets: dict[str, pd.DataFrame] = {
            self.detail_sheet: detail,
            self.summary_sheet: summary,
            "校验问题": _issue_frame(issues),
        }
        for sheet_name, sheet_df in extra_sheets.items():
            sheets[str(sheet_name)] = sheet_df if isinstance(sheet_df, pd.DataFrame) else pd.DataFrame(sheet_df)

        output = artifact_path(job_id, f"{self.info.code}_{self.output_label}.xlsx")
        write_workbook(output, sheets)
        artifact_paths = [(self.artifact_type, str(output))]
        # Reconciliation only produces its review workbook. Declaration files are
        # created once during the generation step and must not be duplicated.
        if operation == "generate" and not result.get("block_declarations", False):
            artifact_paths.extend(self._write_split_artifacts(job_id, detail, year, month))
            artifact_paths.extend(self._write_additional_artifacts(job_id, detail, year, month))
        summary_payload = {
            "input_files": len(files),
            "rows": int(len(detail)),
            "summary_rows": int(len(summary)),
            "issues": int(len(issues)),
            "artifacts": len(artifact_paths),
            "shared_staff_info": used_shared_staff_info,
            "shared_balance_sheet": used_period_balance_sheet,
            "operation": operation,
            **result.get("metrics", {}),
        }
        if self.supports_balance_reconciliation:
            summary_payload["generated_files"] = sum(
                artifact_type in {"declaration", "personnel_collection"}
                for artifact_type, _ in artifact_paths
            )
            summary_payload["reconciliation_rows"] = result.get("reconciliation_rows", [])
        if self.expose_issue_details:
            summary_payload["issue_details"] = issues
        has_blocking_issues = any(issue.get("severity") != "warning" for issue in issues)

        return WorkflowResult(
            status="needs_review" if has_blocking_issues else "success",
            summary=summary_payload,
            artifact_paths=artifact_paths,
        )


class StaffInfoUpdateWorkflow(ExcelWorkflow):
    info = WorkflowInfo(
        code="staff_info_update",
        name="人员信息更新",
        domain="个税申报",
        description="根据人员信息变动表更新人员信息表，并生成税局人员信息采集文件。",
        required_file_roles=["staff_info", "staff_change"],
    )

    def run(
        self,
        db: Session,
        job_id: int,
        period_id: Optional[int],
        files: list[UploadedFile],
    ) -> WorkflowResult:
        files, used_shared_staff_info = _inject_shared_staff_info(db, period_id, files, "employee")
        by_role = {file.file_role: file for file in files}
        year, month = _period_year_month(db, period_id)
        issues: list[dict[str, Any]] = []
        if "staff_info" not in by_role:
            issues.append({"issue_type": "missing_input", "message": "缺少人员信息表"})
        if "staff_change" not in by_role:
            issues.append({"issue_type": "missing_input", "message": "缺少人员信息变动表"})
        if issues:
            output = artifact_path(job_id, f"{self.info.code}_校验问题.xlsx")
            write_workbook(output, {"校验问题": _issue_frame(issues)})
            return WorkflowResult(
                status="needs_review",
                summary={
                    "input_files": len(files),
                    "issues": len(issues),
                    "artifacts": 1,
                    "shared_staff_info": used_shared_staff_info,
                },
                artifact_paths=[("validation_issues", str(output))],
            )

        output_dir = artifact_path(job_id, "人员信息更新").parent / "人员信息更新"
        try:
            result = apply_staff_info_update(
                by_role["staff_info"].stored_path,
                by_role["staff_change"].stored_path,
                str(output_dir),
                year,
                month,
            )
        except PersonnelUpdateValidationError as exc:
            output = artifact_path(job_id, f"{self.info.code}_校验问题.xlsx")
            write_workbook(output, {"校验问题": _issue_frame(exc.issues)})
            return WorkflowResult(
                status="needs_review",
                summary={
                    "input_files": len(files),
                    "issues": len(exc.issues),
                    "artifacts": 1,
                    "shared_staff_info": used_shared_staff_info,
                },
                artifact_paths=[("validation_issues", str(output))],
            )

        report = result.get("report", {})
        non_blocking_issues = [
            *report.get("duplicate_additions", []),
            *report.get("multiple_matches", []),
            *report.get("headcount_reconciliation", {}).get("items", []),
        ]
        report_output = artifact_path(job_id, f"{self.info.code}_更新报告.xlsx")
        write_workbook(report_output, {"校验问题": _issue_frame(non_blocking_issues)})

        artifact_paths: list[tuple[str, str]] = [
            ("staff_info_current", result["updated_staff_path"]),
            ("update_report", str(report_output)),
        ]
        artifact_paths.extend(
            ("personnel_collection", collection_file)
            for collection_file in result.get("collection_files", [])
        )

        return WorkflowResult(
            status=self._issue_status(non_blocking_issues),
            summary={
                "input_files": len(files),
                "issues": len(non_blocking_issues),
                "collection_files": len(result.get("collection_files", [])),
                "artifacts": len(artifact_paths),
                "shared_staff_info": used_shared_staff_info,
            },
            artifact_paths=artifact_paths,
        )


class GeneralSalaryTaxWorkflow(TaxTransformWorkflow):
    info = WorkflowInfo(
        code="general_salary_tax",
        name="通用工资个税申报",
        domain="个税申报",
        description="汇总工资单，关联人员信息和专项扣除，生成工资薪金个税申报底稿。",
        required_file_roles=["salary_sheet"],
    )
    transform = staticmethod(general_salary_tax_transform)
    artifact_type = "working_sheet"
    output_label = "工资个税底稿"
    split_file_label = "3-个税申报表"
    person_type = "employee"
    role_aliases = {
        "salary_sheet": [
            "marketing_salary_sheet",
            "rank_salary_sheet",
            "branch_salary_sheet",
            "headquarters_salary_sheet",
            "digital_ops_salary_sheet",
            "advisor_salary_sheet",
        ],
    }


class AnnualBonusTaxWorkflow(TaxTransformWorkflow):
    info = WorkflowInfo(
        code="annual_bonus_tax",
        name="年终奖个税申报",
        domain="个税申报",
        description="处理全年一次性奖金个税申报数据，按机构输出申报文件。",
        required_file_roles=["bonus_sheet", "staff_info"],
    )
    transform = staticmethod(annual_bonus_transform)
    artifact_type = "annual_bonus_result"
    output_label = "年终奖处理结果"
    split_file_label = "全年一次性奖金申报表"
    person_type = "employee"
    role_aliases = {"annual_bonus_sheet": ["bonus_sheet"]}


class RestrictedStockInterestTaxWorkflow(TaxTransformWorkflow):
    info = WorkflowInfo(
        code="restricted_stock_interest_tax",
        name="限售股、利息税申报",
        domain="个税申报",
        description="处理限售股、利息股息红利所得申报，并与余额表核对。",
        required_file_roles=[],
    )
    transform = staticmethod(restricted_stock_interest_transform)
    artifact_type = "restricted_stock_interest_result"
    output_label = "限售股利息税处理结果"
    person_type = None
    supports_balance_reconciliation = True
    split_file_label = None
    role_aliases = {
        "restricted_stock_sheet": ["tax_sheet", "restricted_stock_tax"],
        "interest_tax_sheet": ["interest_tax"],
        "balance_sheet": ["balance", "ledger_balance"],
    }

    def _input_issues(self, files: list[UploadedFile], operation: str) -> list[dict[str, Any]]:
        source_roles = {"tax_sheet", "restricted_stock_tax", "interest_tax"}
        if any(file.file_role in source_roles for file in files):
            return []
        return [{
            "issue_type": "missing_declaration_source",
            "message": "请至少上传限售股申报表或利息税申报表",
        }]

    @staticmethod
    def _declaration_text(row: pd.Series, candidates: list[str], default: str = "") -> str:
        return _row_first_text(row, candidates) or default

    @staticmethod
    def _declaration_number(row: pd.Series, candidates: list[str], default: Any = "") -> Any:
        for candidate in candidates:
            if candidate not in row.index:
                continue
            value = row.get(candidate)
            if value is None or pd.isna(value) or str(value).strip() == "":
                continue
            number = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
            if not pd.isna(number):
                return float(number)
        return default

    @classmethod
    def _restricted_stock_declaration(cls, source: pd.DataFrame) -> pd.DataFrame:
        columns = [
            "工号", "*姓名", "*证件类型", "*证件号码", "*证券账户号", "*股票代码", "*股票名称",
            "上市公司纳税人识别号", "上市公司名称", "上市公司主管税务机关", "*每股计税价格(元/股)",
            "*转让股数(股)", "限售股原值", "合理税费", "准予扣除的捐赠额", "协定减免",
        ]
        rows: list[dict[str, Any]] = []
        for _, row in source.fillna("").iterrows():
            cert_type = cls._declaration_text(row, ["证件类型", "*证件类型"])
            rows.append({
                "工号": cls._declaration_text(row, ["工号", "员工编号"]),
                "*姓名": cls._declaration_text(row, ["客户姓名", "姓名", "*姓名"]),
                "*证件类型": "居民身份证" if cert_type == "身份证" else cert_type,
                "*证件号码": cls._declaration_text(row, ["证件号码", "*证件号码", "身份证号码"]),
                "*证券账户号": cls._declaration_text(row, ["证券账户号", "证券账号", "资产账户", "证券账户"]),
                "*股票代码": cls._declaration_text(row, ["证券代码", "股票代码", "*股票代码"]),
                "*股票名称": cls._declaration_text(row, ["证券名称", "股票名称", "*股票名称"]),
                "上市公司纳税人识别号": cls._declaration_text(row, ["上市公司纳税人识别号"]),
                "上市公司名称": cls._declaration_text(row, ["企业名称", "上市公司名称"]),
                "上市公司主管税务机关": cls._declaration_text(row, ["上市公司主管税务机关"]),
                "*每股计税价格(元/股)": cls._declaration_number(row, ["成交价格", "*每股计税价格(元/股)"]),
                "*转让股数(股)": cls._declaration_number(row, ["成交数量", "*转让股数(股)"]),
                "限售股原值": cls._declaration_number(row, ["原值总金额", "限售股原值"], 0.0),
                "合理税费": cls._declaration_number(row, ["合理税费"], 0.0),
                "准予扣除的捐赠额": cls._declaration_number(row, ["准予扣除的捐赠额"]),
                "协定减免": cls._declaration_number(row, ["协定减免"]),
            })
        return pd.DataFrame(rows, columns=columns)

    @classmethod
    def _interest_declaration(cls, source: pd.DataFrame) -> pd.DataFrame:
        columns = [
            "工号", "*姓名", "*证件类型", "*证件号码", "*所得项目", "上市板块", "*收入", "免税收入",
            "准予扣除的捐赠额", "*税率", "协定税率", "减免税额", "协定减免", "备注",
        ]
        rows: list[dict[str, Any]] = []
        for _, row in source.fillna("").iterrows():
            cert_type = cls._declaration_text(row, ["证件类型", "*证件类型"])
            rows.append({
                "工号": cls._declaration_text(row, ["工号", "员工编号"]),
                "*姓名": cls._declaration_text(row, ["客户姓名", "姓名", "*姓名"]),
                "*证件类型": "居民身份证" if cert_type == "身份证" else cert_type,
                "*证件号码": cls._declaration_text(row, ["证件号码", "*证件号码", "身份证号码"]),
                "*所得项目": cls._declaration_text(row, ["所得项目", "*所得项目"], "其他利息、股息、红利所得"),
                "上市板块": cls._declaration_text(row, ["上市板块"]),
                "*收入": cls._declaration_number(row, ["利息税申报金额", "债券兑息", "*收入"]),
                "免税收入": cls._declaration_number(row, ["免税收入"]),
                "准予扣除的捐赠额": cls._declaration_number(row, ["准予扣除的捐赠额"]),
                "*税率": "20%",
                "协定税率": cls._declaration_text(row, ["协定税率"]),
                "减免税额": cls._declaration_number(row, ["减免税额"]),
                "协定减免": cls._declaration_number(row, ["协定减免"]),
                "备注": cls._declaration_text(row, ["利息税调整说明", "备注"]),
            })
        return pd.DataFrame(rows, columns=columns)

    def _write_split_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        artifacts: list[tuple[str, str]] = []
        declaration_specs = [
            ("限售股", "_7-限售股转让所得", self._restricted_stock_declaration),
            ("利息税", "_6-利息、股息、红利所得", self._interest_declaration),
        ]
        for income_type, label, builder in declaration_specs:
            source = detail[detail.get("所得类型", pd.Series(index=detail.index, dtype=str)) == income_type]
            if source.empty or "机构代码" not in source.columns:
                continue
            for org_code, group in source.groupby("机构代码", dropna=False):
                org_text = str(org_code or "").strip()
                if not org_text or org_text.lower() == "nan":
                    continue
                output = artifact_path(job_id, f"{org_text}{label}({year}年{month:02d}月).xlsx")
                write_workbook(output, {"Sheet1": builder(group)}, text_values=True)
                artifacts.append(("declaration", str(output)))
        return artifacts

    def _write_additional_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        rows: list[dict[str, str]] = []
        for _, row in detail.fillna("").iterrows():
            is_restricted_stock = _row_first_text(row, ["所得类型"]) == "限售股"
            name = _row_first_text(row, ["客户姓名", "姓名", "*姓名"])
            id_number = _row_first_text(row, ["证件号码", "*证件号码", "身份证号码"])
            org_code = _row_first_text(row, ["机构代码", "分支机构代码", "公司段"])
            if not name or not id_number or not org_code:
                continue
            cert_type = _row_first_text(row, ["证件类型", "*证件类型"]) or "居民身份证"
            if is_restricted_stock and cert_type == "身份证":
                cert_type = "居民身份证"
            rows.append({
                "*姓名": name,
                "证件类型": cert_type,
                "证件号码": id_number,
                "国籍(地区)": _row_first_text(row, ["国籍(地区)", "国籍"]) or "中国",
                "性别": _row_first_text(row, ["性别", "客户性别"]),
                "出生日期": _row_first_text(row, ["出生日期", "生日", "出生年月日"]),
                "人员状态": "正常",
                "任职受雇从业类型": "其他",
                "其他情况说明": (
                    "申报其他所得"
                    if is_restricted_stock
                    else "扣缴申报利息股息红利所得"
                ),
                "手机号码": _row_first_text(row, ["手机号码", "客户手机号码"]),
                "任职受雇从业日期": "",
                "离职日期": "",
                "机构代码(人员信息表)": org_code,
                "机构代码(工资单)": org_code,
                "员工编号": "",
            })

        collection_files = build_personnel_collection_files(
            pd.DataFrame(rows),
            artifact_path(job_id, "personnel_collection").parent,
            year,
            month,
            person_type_label="客户",
            duplicate_keep="first",
            collection_sequence="2",
            file_extension=".xlsx",
        )
        return [("personnel_collection", path) for path in collection_files]


class InternTaxWorkflow(TaxTransformWorkflow):
    info = WorkflowInfo(
        code="intern_tax",
        name="实习生个税申报",
        domain="个税申报",
        description="处理实习生补贴，生成实习生人员采集与劳务报酬申报文件。",
        required_file_roles=["intern_salary"],
    )
    transform = staticmethod(intern_tax_transform)
    artifact_type = "intern_tax_result"
    output_label = "实习生处理结果"
    split_file_label = "4-个税申报表_实习生"
    person_type = None
    expose_issue_details = True
    role_aliases = {"intern_salary_sheet": ["intern_salary"]}
    org_column_candidates = ["分支机构名称", "分支机构代码", "机构代码", "单位编号"]

    def _frames_with_aliases(self, files: list[UploadedFile]) -> dict[str, pd.DataFrame]:
        frames = super()._frames_with_aliases(files)
        intern_files = [file for file in files if file.file_role == "intern_salary"]
        if intern_files:
            prepared = []
            for file in intern_files:
                standard = pd.read_excel(file.stored_path, dtype={"*证件号码": str})
                if {"*姓名", "*证件类型", "*证件号码"}.issubset(standard.columns):
                    standard["_source_row_number"] = range(2, len(standard) + 2)
                    prepared.append(standard)
                else:
                    legacy = pd.read_excel(file.stored_path, skiprows=1, dtype={"*证件号码": str})
                    legacy["_source_row_number"] = range(3, len(legacy) + 3)
                    prepared.append(legacy)
            frames["intern_salary_sheet"] = pd.concat(prepared, ignore_index=True, sort=False)
        return frames

    def _prepare_frames(self, db: Session, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        prepared = dict(frames)
        if db is not None:
            prepared["intern_org_mapping"] = pd.DataFrame(
                [{"营业部名称": name, "机构代码": code} for name, code in active_mapping_dict(db).items()]
            )
        return prepared

    def _write_split_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        artifacts: list[tuple[str, str]] = []
        if detail.empty or "分支机构代码" not in detail.columns:
            return artifacts
        for org_code, group in detail.groupby("分支机构代码", dropna=False):
            org_text = str(org_code or "").strip()
            if not org_text or org_text.lower() == "nan":
                continue
            output = artifact_path(job_id, f"{org_text}_4-个税申报表_实习生({year}年{month:02d}月).xlsx")
            write_workbook(
                output,
                {"Sheet1": group.reindex(columns=INTERN_DECLARATION_COLUMNS)},
                text_values=True,
            )
            artifacts.append(("declaration", str(output)))
        return artifacts

    def _write_additional_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        if detail.empty:
            return []
        collection = detail.rename(columns={
            "*证件类型": "证件类型",
            "*证件号码": "证件号码",
            "*国籍(地区)": "国籍(地区)",
            "*性别": "性别",
            "*出生日期": "出生日期",
            "分支机构代码": "机构代码(人员信息表)",
        }).copy()
        paths = build_personnel_collection_files(
            collection,
            artifact_path(job_id, "personnel_collection").parent,
            year,
            month,
            person_type_label="实习生",
            duplicate_keep="first",
            collection_sequence="2",
            file_extension=".xlsx",
        )
        return [("personnel_collection", path) for path in paths]


class BrokerTaxWorkflow(TaxTransformWorkflow):
    info = WorkflowInfo(
        code="broker_tax",
        name="经纪人个税申报",
        domain="个税申报",
        description="处理证券经纪人佣金收入个税申报与人员校验。",
        required_file_roles=["broker_income", "staff_info"],
    )
    transform = staticmethod(broker_tax_transform)
    artifact_type = "broker_tax_result"
    output_label = "经纪人处理结果"
    split_file_label = "5-个税申报_经纪人"
    person_type = "broker"
    expose_issue_details = True
    role_aliases = {
        "broker_salary_sheet": ["broker_income"],
        "broker_staff_info": ["staff_info"],
    }
    org_column_candidates = ["分支机构代码", "机构代码", "单位编号"]

    def _write_split_artifacts(
        self,
        job_id: int,
        detail: pd.DataFrame,
        year: int,
        month: int,
    ) -> list[tuple[str, str]]:
        artifacts: list[tuple[str, str]] = []
        if detail.empty or "分支机构代码" not in detail.columns:
            return artifacts
        for org_code, group in detail.groupby("分支机构代码", dropna=False):
            org_text = str(org_code or "").strip()
            if not org_text or org_text.lower() == "nan":
                continue
            output = artifact_path(job_id, f"{org_text}_5-个税申报_经纪人({year}年{month:02d}月).xlsx")
            write_workbook(
                output,
                {"Sheet1": group.reindex(columns=BROKER_DECLARATION_COLUMNS)},
                text_values=True,
            )
            artifacts.append(("declaration", str(output)))
        return artifacts


class InvoiceBookingWorkflow(InvoiceWorkflow):
    info = WorkflowInfo(
        code="invoice_booking",
        name="电子发票入账",
        domain="发票记账",
        description="清洗电子发票，合并重复发票金额，生成发票台账。",
        required_file_roles=["invoice_detail"],
    )


class VatDeductionWorkflow(CertificationWorkflow):
    info = WorkflowInfo(
        code="vat_deduction",
        name="认证抵扣核对",
        domain="发票记账",
        description="核对认证表和记账金额，输出未匹配和金额不一致记录。",
        required_file_roles=["certification_sheet", "booking_sheet"],
    )


class VoucherDraftEntry(VoucherDraftWorkflow):
    info = WorkflowInfo(
        code="voucher_draft",
        name="凭证草稿生成",
        domain="记账草稿",
        description="按发票、认证和税费结果生成可审核凭证草稿。",
        required_file_roles=["ledger_export"],
    )


_WORKFLOWS = {
    wf.info.code: wf
    for wf in [
        GeneralSalaryTaxWorkflow(),
        StaffInfoUpdateWorkflow(),
        AnnualBonusTaxWorkflow(),
        RestrictedStockInterestTaxWorkflow(),
        InternTaxWorkflow(),
        BrokerTaxWorkflow(),
        InvoiceBookingWorkflow(),
        VatDeductionWorkflow(),
        VoucherDraftEntry(),
    ]
}


def list_workflows():
    return list(_WORKFLOWS.values())


def get_workflow(code: str):
    try:
        return _WORKFLOWS[code]
    except KeyError as exc:
        raise ValueError(f"未知流程码：{code}") from exc
