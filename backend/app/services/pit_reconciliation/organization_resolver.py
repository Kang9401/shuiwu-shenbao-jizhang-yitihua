from app.services.bank_accounts import normalize_bank_account
from app.models.accounting import OrganizationMapping
from .domain import OrganizationRow


class PitOrganizationResolver:
    def __init__(self, db, company_id: int):
        rows = db.query(OrganizationMapping).filter(OrganizationMapping.company_id == company_id, OrganizationMapping.active == 1).all()
        self.items = {row.org_code.strip(): OrganizationRow(row.org_code.strip(), row.branch_name or "", row.rpa_org_name or row.branch_name or "", row.taxpayer_id or "", row.rpa_org_name or "") for row in rows}
        self.code_to_name = {key: value.org_name for key, value in self.items.items()}; self.code_to_full_name = {key: value.full_name for key, value in self.items.items()}
        self.name_to_code = {value.org_name: key for key, value in self.items.items() if value.org_name}; self.full_name_to_code = {value.full_name: key for key, value in self.items.items() if value.full_name}; self.taxpayer_id_to_code = {value.taxpayer_id: key for key, value in self.items.items() if value.taxpayer_id}; self.rpa_name_to_code = {value.rpa_name: key for key, value in self.items.items() if value.rpa_name}
        self.bank_account_to_code = {
            normalize_bank_account(row.bank_account or getattr(row, "bank_subaccount", "")): row.org_code.strip()
            for row in rows
            if (row.bank_account or getattr(row, "bank_subaccount", "")) and normalize_bank_account(row.bank_account or getattr(row, "bank_subaccount", "")).lower() not in {"none", "nan"}
        }
    def get_org(self, code: str | None): return self.items.get((code or "").strip())
    def resolve_by_org_code(self, value: str | None): return self.get_org(value)
    def resolve_by_branch_name(self, value: str | None): return self.get_org(self.name_to_code.get((value or "").strip()))
    def resolve_by_full_name(self, value: str | None): return self.get_org(self.full_name_to_code.get((value or "").strip()))
    def resolve_by_taxpayer_id(self, value: str | None): return self.get_org(self.taxpayer_id_to_code.get((value or "").strip()))
    def resolve_by_rpa_name(self, value: str | None): return self.get_org(self.rpa_name_to_code.get((value or "").strip()))
    def resolve_by_bank_account(self, value: str | None): return self.get_org(self.bank_account_to_code.get(normalize_bank_account(value)))
