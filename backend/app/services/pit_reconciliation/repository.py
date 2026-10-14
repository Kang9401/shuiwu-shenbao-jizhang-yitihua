from __future__ import annotations

from datetime import datetime
from copy import deepcopy

from app.models.pit_reconciliation import (PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail, PitReconciliationOrgSummary, PitReconciliationSource, PitReconciliationWorkpaper, PitTaxAmountCheck)
from .constants import RULE_VERSION
from .source_service import declaration_snapshot_rows


class PitReconciliationRepository:
    def __init__(self, db, company_id: int, period_id: int, stage: str): self.db,self.company_id,self.period_id,self.stage=db,company_id,period_id,stage
    def get_or_create_workpaper(self):
        row=self.db.query(PitReconciliationWorkpaper).filter_by(company_id=self.company_id,period_id=self.period_id,tax_type="pit",stage=self.stage).first()
        if row is None: row=PitReconciliationWorkpaper(company_id=self.company_id,period_id=self.period_id,tax_type="pit",stage=self.stage,workflow_status="data_preparation",data_status="incomplete",calculation_status="idle",rule_version=RULE_VERSION); self.db.add(row); self.db.flush()
        return row
    def _manual(self, model, keys, fields, workpaper_id):
        result={}
        for row in self.db.query(model).filter_by(workpaper_id=workpaper_id): result[tuple(getattr(row,key) for key in keys)]={field:getattr(row,field) for field in fields}
        return result
    def pre_payment_result(self):
        pre = self.db.query(PitReconciliationWorkpaper).filter_by(
            company_id=self.company_id, period_id=self.period_id, tax_type="pit", stage="pre_payment",
        ).first()
        if pre is None or (not pre.last_calculated_at and not pre.draft_revision):
            raise ValueError("请先完成缴款前底稿重算，缴款后申报表只能使用缴款前版本")
        excluded = {"id", "public_id", "company_id", "period_id", "workpaper_id", "created_at", "updated_at"}
        result = {}
        for model, key in ((PitDeclarationSummary, "declaration_summaries"), (PitTaxAmountCheck, "tax_checks"),
                           (PitOccurrenceCheck, "occurrence_checks"), (PitReconciliationOrgSummary, "org_summaries"),
                           (PitReconciliationDifferenceDetail, "details")):
            result[key] = [{column.name: deepcopy(getattr(row, column.name))
                            for column in model.__table__.columns if column.name not in excluded}
                           for row in self.db.query(model).filter_by(workpaper_id=pre.id, company_id=self.company_id)]
        for row in result["details"]:
            row["name"] = row.pop("person_or_customer_name")
        result["sources"] = [deepcopy(row) for key, row in (pre.source_snapshot_json or {}).items()
                             if key not in {"tax_certificate", "bank_statement"}]
        for row in result["sources"]:
            row.pop("rows", None)
        result["declaration_rows"] = deepcopy(declaration_snapshot_rows(self.db, pre))
        result["pre_payment_snapshot"] = {"workpaper_id": pre.id, "draft_revision": pre.draft_revision}
        return result
    def replace(self, workpaper, result):
        workpaper_id = workpaper.id
        manual={PitTaxAmountCheck:self._manual(PitTaxAmountCheck,("org_code","subject_code"),("current_manual_reason","cumulative_manual_reason","business_declared_manual_reason","remark"),workpaper_id),PitOccurrenceCheck:self._manual(PitOccurrenceCheck,("org_code","subject_code"),("broker_occurrence_manual_reason","declared_income_manual_reason","remark"),workpaper_id),PitReconciliationOrgSummary:self._manual(PitReconciliationOrgSummary,("org_code",),("difference_1_manual_reason","difference_2_manual_reason","difference_3_manual_reason","difference_4_manual_reason","difference_5_manual_reason","difference_6_manual_reason","difference_7_manual_reason","remark"),workpaper_id),PitReconciliationDifferenceDetail:self._manual(PitReconciliationDifferenceDetail,("detail_type","org_code","identity_key"),("manual_reason","remark"),workpaper_id)}
        for model in (PitReconciliationSource,PitDeclarationSummary,PitTaxAmountCheck,PitOccurrenceCheck,PitReconciliationOrgSummary,PitReconciliationDifferenceDetail,PitBankTaxMatch): self.db.query(model).filter_by(workpaper_id=workpaper_id).delete(synchronize_session=False)
        self.db.flush()
        # Bulk replacement may reuse SQLite row ids.  Clear stale ORM identities before
        # inserting the recomputed rows, while the manual values are already cached.
        self.db.expunge_all()
        workpaper = self.db.get(PitReconciliationWorkpaper, workpaper_id)
        mapping=((PitReconciliationSource,"sources",("source_type",)),(PitDeclarationSummary,"declaration_summaries",("org_code","declaration_type","income_item")),(PitTaxAmountCheck,"tax_checks",("org_code","subject_code")),(PitOccurrenceCheck,"occurrence_checks",("org_code","subject_code")),(PitReconciliationOrgSummary,"org_summaries",("org_code",)),(PitReconciliationDifferenceDetail,"details",("detail_type","org_code","identity_key")),(PitBankTaxMatch,"bank_matches",None))
        for model,key,natural_key in mapping:
            for row in result[key]:
                values=dict(row); values.update(workpaper_id=workpaper.id,company_id=self.company_id,period_id=self.period_id)
                if model is PitReconciliationSource:
                    values["source_status"]=values.pop("status")
                    values["required"]=int(bool(values.get("required", True)))
                if model is PitReconciliationDifferenceDetail:
                    values["person_or_customer_name"] = values.pop("name", "")
                    values.setdefault("org_name", "")
                if natural_key and model in manual: values.update(manual[model].get(tuple(values[field] for field in natural_key),{}))
                self.db.add(model(**values))
        if result.get("stage") != workpaper.stage: raise ValueError("重算阶段与底稿阶段不一致")
        workpaper.data_status=result["data_status"]; workpaper.calculation_status="success"; workpaper.workflow_status="pending_submission" if result["data_status"] == "ready" else "data_preparation"; workpaper.draft_revision += 1; workpaper.missing_sources_json=result["missing_sources"]; workpaper.source_snapshot_json={row["source_type"]:row for row in result["sources"]}; workpaper.last_calculated_at=datetime.utcnow(); workpaper.last_error=None
        snapshot = dict(workpaper.source_snapshot_json)
        if "declaration_rows" in result:
            snapshot.setdefault("pit_declaration", {})["rows"] = result["declaration_rows"]
        if "pre_payment_snapshot" in result:
            snapshot["pre_payment_snapshot"] = result["pre_payment_snapshot"]
        workpaper.source_snapshot_json = snapshot
        self.db.flush(); return workpaper
