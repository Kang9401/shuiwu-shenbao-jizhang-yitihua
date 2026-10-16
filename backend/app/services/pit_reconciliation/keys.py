import re
import hashlib
import json


def reliable_id_number(value: str | None) -> str:
    """Return a usable resident ID; masked/short values are not identities."""
    text = re.sub(r"\s+", "", str(value or "")).upper()
    return text if re.fullmatch(r"\d{17}[0-9X]", text) else ""


def normalized_name(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def preferred_id_number(values) -> str:
    """Return a stable identity value, preferring an unmasked ID.

    The support platform can provide a masked ID in one source and the full
    ID in another.  Selecting from a set with ``next(iter(...))`` made the
    resulting natural key depend on hash iteration order and could produce
    duplicate rows across recalculations.  Keep the full value when it is
    available and otherwise choose the lexicographically first masked value.
    """
    candidates = sorted({str(value).strip() for value in values if value and str(value).strip()})
    if not candidates:
        return ""
    unmasked = [value for value in candidates if "*" not in value and "＊" not in value]
    return unmasked[0] if unmasked else candidates[0]


def employee_identity(employee_no: str | None, id_number: str | None, org_code: str, name: str, pair_index: int = 0) -> str:
    return (f"emp:{employee_no}" if employee_no else f"id:{id_number}" if id_number else f"name:{org_code}:{normalized_name(name)}:{pair_index}")


def customer_identity(id_number: str | None, org_code: str, name: str) -> str:
    return f"id:{id_number}" if id_number else f"customer:{org_code}:{normalized_name(name)}"


def _masked_id_signature(value: str | None) -> tuple[str, str] | None:
    text = re.sub(r"\s+", "", str(value or "")).upper()
    if len(text) >= 3 and ("*" in text or "＊" in text):
        return text[0], text[-1]
    return None


def declaration_mapping_keys(rows):
    """Identify individual source rows, never a whole masked name group."""
    counts = {}
    result = []
    for row in rows:
        raw = getattr(row, "raw_data", {}) or {}
        source = [row.org_code, normalized_name(row.person_name), row.id_number,
                  raw.get("_identity_source_row"), raw.get("file_name"),
                  raw.get("sheet_name"), raw.get("序号"), raw.get("row_number")]
        base = hashlib.sha256(json.dumps(source, ensure_ascii=False, default=str).encode()).hexdigest()
        ordinal = counts.get(base, 0)
        counts[base] = ordinal + 1
        result.append(f"{base}:{ordinal}")
    return result


def _document_number(value):
    text = re.sub(r"\s+", "", str(value or "")).upper()
    return text if re.fullmatch(r"[A-Z0-9]{5,30}", text) else ""


def _salary_identity(row):
    org = str(row.org_code or "")
    full = reliable_id_number(row.id_number)
    document = _document_number(row.id_number)
    if full:
        return ("id", org, full)
    if document:
        return ("document", org, document)
    return ("name", org, normalized_name(row.person_name))


def _payroll_target_key(identity):
    return "payroll:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def payroll_mapping_options(salaries):
    """Manual choices come from this company's period, including non-resident IDs."""
    grouped = {}
    for row in salaries:
        if not _document_number(row.id_number):
            continue
        target = _payroll_target_key(_salary_identity(row))
        option = grouped.setdefault(target, {
            "target_key": target, "org_code": row.org_code, "name": row.person_name,
            "id_number": _document_number(row.id_number), "employee_nos": [],
            "tax_amount": 0, "row_count": 0,
        })
        if row.employee_no and row.employee_no not in option["employee_nos"]:
            option["employee_nos"].append(row.employee_no)
        option["tax_amount"] += row.pit_tax or 0
        option["row_count"] += 1
    return sorted(grouped.values(), key=lambda option: (option["org_code"], option["name"], option["id_number"]))


def resolve_identity_keys(left_rows, right_rows, identity_mappings=None):
    """Resolve payroll/declaration identities without guessing masked IDs.

    A masked declaration ID is joined to a complete ID only when organization,
    name, first character and last character identify exactly one candidate.
    Ambiguous or unmatched rows receive a stable per-row key so they remain
    visible for manual review instead of being merged by name.
    """
    left_rows, right_rows = list(left_rows), list(right_rows)
    rows = left_rows + right_rows
    mapping_keys = [None] * len(left_rows) + declaration_mapping_keys(right_rows)
    identity_mappings = identity_mappings or {}
    targets = {_payroll_target_key(_salary_identity(row)): _salary_identity(row)
               for row in left_rows if _document_number(row.id_number)}
    target_by_document = {_document_number(row.id_number): _salary_identity(row)
                          for row in left_rows if _document_number(row.id_number)}
    full_by_group: dict[tuple[str, str], set[str]] = {}
    for row in left_rows:
        full = reliable_id_number(getattr(row, "id_number", ""))
        if full:
            group = (str(getattr(row, "org_code", "") or ""), normalized_name(getattr(row, "person_name", "")))
            full_by_group.setdefault(group, set()).add(full)
    resolved = []
    for index, row in enumerate(rows):
        org = str(getattr(row, "org_code", "") or "")
        name = normalized_name(getattr(row, "person_name", ""))
        raw_id = re.sub(r"\s+", "", str(getattr(row, "id_number", "") or "")).upper()
        full = reliable_id_number(raw_id)
        status = "confirmed"
        candidates = []
        signature = _masked_id_signature(raw_id)
        if signature:
            candidates = sorted(value for value in full_by_group.get((org, name), set()) if value[0] == signature[0] and value[-1] == signature[1])
        chosen = identity_mappings.get(mapping_keys[index])
        target = targets.get(chosen) or target_by_document.get(chosen)
        # Keep the original same-org resident-ID mapping format usable.
        if chosen in candidates:
            target = ("id", org, chosen)
        if target is not None:
            key, status = target, "manual_confirmed"
        elif index < len(left_rows):
            key = _salary_identity(row)
            if key[0] == "name": status = "manual_review" if name else "unidentified"
        elif full and not chosen:
            key = ("id", org, full)
            if _payroll_target_key(key) not in targets: status = "manual_review"
        elif signature or _document_number(raw_id) or chosen:
            if not chosen and len(candidates) == 1:
                key = ("id", org, candidates[0])
            else:
                status = "manual_review"
                key = ("masked", org, name, raw_id, mapping_keys[index])
        else:
            status = "manual_review" if name else "unidentified"
            key = ("name", org, name)
        resolved.append((key, status, candidates))
    split = len(left_rows)
    return resolved[:split], resolved[split:]


def identity_mapping_rows(salaries, declarations, identity_mappings=None):
    declarations = [row for row in declarations if "工资薪金" in row.income_item and "证券经纪" not in row.income_item]
    _, matches = resolve_identity_keys(salaries, declarations, identity_mappings)
    options = payroll_mapping_options(salaries)
    options_by_key = {option["target_key"]: option for option in options}
    option_key_by_id = {option["id_number"]: option["target_key"] for option in options}
    output = []
    for row, row_key, match in zip(declarations, declaration_mapping_keys(declarations), matches):
        if not _masked_id_signature(row.id_number) and match[1] == "confirmed":
            continue
        raw = row.raw_data or {}
        stored_selection = (identity_mappings or {}).get(row_key, "")
        selected_target = stored_selection if stored_selection.startswith("payroll:") else option_key_by_id.get(stored_selection, "")
        if not selected_target and match[0][0] in {"id", "document"}:
            selected_target = _payroll_target_key(match[0])
        selected = options_by_key.get(selected_target)
        warnings = []
        if selected:
            if selected["org_code"] != row.org_code: warnings.append("机构不同")
            if normalized_name(selected["name"]) != normalized_name(row.person_name): warnings.append("姓名不同")
            signature = _masked_id_signature(row.id_number)
            document = selected["id_number"]
            if (signature and (document[0], document[-1]) != signature) or (not signature and document != re.sub(r"\s+", "", row.id_number).upper()):
                warnings.append("证件不同")
        output.append({"row_key": row_key, "org_code": row.org_code, "name": row.person_name,
                       "masked_id": row.id_number, "file_name": raw.get("file_name", ""),
                       "sheet_name": raw.get("sheet_name", row.declaration_type),
                       "source_row": raw.get("row_number", raw.get("序号", "")),
                       "tax_amount": row.tax_amount, "candidates": match[2], "status": match[1],
                       "selected_id": selected["id_number"] if selected else stored_selection,
                       "selected_target": selected_target,
                       "resolved_target": selected_target, "warnings": warnings,
                       "document_type": raw.get("身份证件类型") or raw.get("证件类型") or "",
                       "resolved_id": selected["id_number"] if selected else ""})
    return output


def identity_key_text(key) -> str:
    if key[0] in {"id", "document"}:
        return f"{key[0]}:{key[2]}"
    if key[0] == "masked":
        return f"manual:{key[1]}:{key[2]}:{key[3]}:{key[4]}"
    return f"name:{key[1]}:{key[2]}" + (f":{key[3]}" if len(key) > 3 else "")
