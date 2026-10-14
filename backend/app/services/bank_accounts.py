import re
import unicodedata


def normalize_bank_account(value) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return re.sub(r"\s+", "", text)
