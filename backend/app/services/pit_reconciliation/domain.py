from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class OrganizationRow: org_code: str; org_name: str = ""; full_name: str = ""; taxpayer_id: str = ""; rpa_name: str = ""
@dataclass(frozen=True)
class BalanceRow: org_code: str; full_account_code: str; subject_code: str; description: str = ""; opening_balance: Decimal | None = None; debit_amount: Decimal | None = None; credit_amount: Decimal | None = None; closing_balance: Decimal | None = None; raw_data: dict[str, Any] = field(default_factory=dict)
@dataclass(frozen=True)
class SalaryRow: org_code: str; person_name: str; id_number: str = ""; employee_no: str = ""; salary_kind: str = ""; pit_tax: Decimal | None = None; cumulative_taxable_income: Decimal | None = None; cumulative_basic_deduction: Decimal | None = None; cumulative_special_deduction: Decimal | None = None; cumulative_child_education: Decimal | None = None; cumulative_elderly_support: Decimal | None = None; cumulative_housing_loan_interest: Decimal | None = None; cumulative_housing_rent: Decimal | None = None; cumulative_continuing_education: Decimal | None = None; cumulative_infant_care: Decimal | None = None; cumulative_personal_pension: Decimal | None = None; cumulative_other_deduction: Decimal | None = None
@dataclass(frozen=True)
class BrokerRow: org_code: str; person_name: str = ""; pit_tax: Decimal | None = None; gross_before_topup: Decimal | None = None; vat_amount: Decimal | None = None
@dataclass(frozen=True)
class BondInterestRow: org_code: str; customer_name: str; id_number: str = ""; interest_amount: Decimal | None = None; withheld_tax: Decimal | None = None
@dataclass(frozen=True)
class RestrictedStockRow: org_code: str; customer_name: str; id_number: str = ""; security_name: str = ""; sale_amount: Decimal | None = None; withheld_tax: Decimal | None = None
@dataclass(frozen=True)
class DeclarationRow: org_code: str; declaration_type: str; withholding_agent_name: str = ""; withholding_agent_taxpayer_id: str = ""; person_name: str = ""; id_number: str = ""; income_item: str = ""; income_amount: Decimal | None = None; tax_amount: Decimal | None = None; tax_rate: str = ""; cumulative_taxable_income: Decimal | None = None; cumulative_basic_deduction: Decimal | None = None; cumulative_special_deduction: Decimal | None = None; cumulative_child_education: Decimal | None = None; cumulative_elderly_support: Decimal | None = None; cumulative_housing_loan_interest: Decimal | None = None; cumulative_housing_rent: Decimal | None = None; cumulative_continuing_education: Decimal | None = None; cumulative_infant_care: Decimal | None = None; cumulative_personal_pension: Decimal | None = None; cumulative_other_deduction: Decimal | None = None; housing_fund_adjustment: Decimal | None = None; tax_period: str = ""; raw_data: dict[str, Any] = field(default_factory=dict)
@dataclass(frozen=True)
class TaxCertificateRow: org_code: str; org_full_name: str = ""; tax_type: str = ""; tax_period: str = ""; amount: Decimal | None = None; source_row_id: int | None = None
@dataclass(frozen=True)
class BankRow: org_code: str = ""; bank_account: str = ""; transaction_time: str = ""; summary: str = ""; debit_amount: Decimal | None = None; source_batch_id: int | None = None; source_row_id: int | None = None
@dataclass
class SourceResult: source_type: str; status: str; rows: list[Any] = field(default_factory=list); required: bool = True; source_kind: str | None = None; source_id: int | None = None; source_ref: str | None = None; issues: list[dict[str, Any]] = field(default_factory=list)
@dataclass
class PitSourceBundle: organizations: SourceResult; salary: SourceResult; declarations: SourceResult; balance: SourceResult; broker: SourceResult; bond_interest: SourceResult; restricted_stock: SourceResult; certificates: SourceResult; bank: SourceResult
