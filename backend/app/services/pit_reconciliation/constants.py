from decimal import Decimal

RULE_VERSION = "pit_legacy_v1"
TAX_SUBJECT_CODES = ("21510006", "21510008", "21510009", "21510016")
OCCURRENCE_SUBJECT_CODES = ("21131042", "45019006", "21210037", "21210038", "21210012")
SOURCE_TYPES = ("organization_mapping", "salary", "pit_declaration", "balance_sheet", "broker", "bond_interest", "restricted_stock", "tax_certificate", "bank_statement")
TOLERANCE = Decimal("0.01")
BANK_TOLERANCE = Decimal("0.02")
VAT_THRESHOLD = Decimal("1010")
VAT_RATE = Decimal("0.01")
OCCURRENCE_INCOME_TYPES = {
    "21131042": "证券经纪人佣金收入", "45019006": "证券经纪人佣金收入",
    "21210037": "其他连续劳务报酬", "21210038": "一般劳务报酬所得", "21210012": "解除劳动合同一次性补偿金",
}
TAX_SUBJECT_NAMES = {"21510006": "工资薪金个人所得税", "21510008": "利息、股息、红利个人所得税", "21510009": "限售股转让个人所得税", "21510016": "证券经纪人个人所得税"}
BALANCE_FIELD_ALIASES = {
    "opening_balance": ("期初余额(N)", "期初余额"), "debit_amount": ("借方金额(N)", "借方金额"),
    "credit_amount": ("贷方金额(N)", "贷方金额"), "closing_balance": ("期末余额(N)", "期末余额"),
}
