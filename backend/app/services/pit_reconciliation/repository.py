from __future__ import annotations

from datetime import datetime

from app.models.pit_reconciliation import (PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail, PitReconciliationOrgSummary, PitReconciliationSource, PitReconciliationWorkpaper, PitTaxAmountCheck)
from .constants import RULE_VERSION


class PitReconciliationRepository:
    def __init__(self, db, company_id: int, period_id: int): self.db,self.company_id,self.period_id=db,company_id,period_id
    def get_or_create_workpaper(self):
        row=self.db.query(PitReconciliationWorkpaper).filter_by(company_id=self.company_id,period_id=self.period_id,tax_type="pit").first()
        if row is None: row=PitReconciliationWorkpaper(company_id=self.company_id,period_id=self.period_id,tax_type="pit",stage="pre_payment",data_status="incomplete",calculation_status="idle",rule_version=RULE_VERSION); self.db.add(row); self.db.flush()
        return row
    def _manual(self, model, keys, fields, workpaper_id):
        result={}
        for row in self.db.query(model).filter_by(workpaper_id=workpaper_id): result[tuple(getattr(row,key) for key in keys)]={field:getattr(row,field) for field in fields}
        return result
    def replace(self, workpaper, result):
        manual={PitTaxAmountCheck:self._manual(PitTaxAmountCheck,("org_code","subject_code"),("current_manual_reason","cumulative_manual_reason","business_declared_manual_reason","remark"),workpaper.id),PitOccurrenceCheck:self._manual(PitOccurrenceCheck,("org_code","subject_code"),("broker_occurrence_manual_reason","declared_income_manual_reason","remark"),workpaper.id),PitReconciliationOrgSummary:self._manual(PitReconciliationOrgSummary,("org_code",),("difference_1_manual_reason","difference_2_manual_reason","difference_3_manual_reason","difference_4_manual_reason","difference_5_manual_reason","difference_6_manual_reason","difference_7_manual_reason","remark"),workpaper.id),PitReconciliationDifferenceDetail:self._manual(PitReconciliationDifferenceDetail,("detail_type","org_code","identity_key"),("manual_reason","remark"),workpaper.id)}
        for model in (PitReconciliationSource,PitDeclarationSummary,PitTaxAmountCheck,PitOccurrenceCheck,PitReconciliationOrgSummary,PitReconciliationDifferenceDetail,PitBankTaxMatch): self.db.query(model).filter_by(workpaper_id=workpaper.id).delete(synchronize_session=False)
        self.db.flush()
        # Bulk replacement may reuse SQLite row ids.  Clear stale ORM identities before
        # inserting the recomputed rows, while the manual values are already cached.
        self.db.expunge_all()
        workpaper = self.db.get(PitReconciliationWorkpaper, workpaper.id)
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
        workpaper.stage=result["stage"]; workpaper.data_status=result["data_status"]; workpaper.calculation_status="success"; workpaper.missing_sources_json=result["missing_sources"]; workpaper.source_snapshot_json={row["source_type"]:row for row in result["sources"]}; workpaper.last_calculated_at=datetime.utcnow(); workpaper.last_error=None
        self.db.flush(); return workpaper
