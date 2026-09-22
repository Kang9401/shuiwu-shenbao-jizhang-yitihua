from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd

from app.core.config import settings
from app.integrations.fmss.iit.schemas import FmssSheet


class PitFmssExcelBuilder:
    def build(self, sheets: list[FmssSheet], rows_by_key: dict[str, list[list[object]]]) -> Path:
        directory = settings.temp_dir / "fmss"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"iit-pre-{uuid4().hex}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for sheet in sheets:
                rows = rows_by_key.get(sheet.key, [])
                if any(len(row) != len(sheet.headers) for row in rows):
                    raise ValueError(f"FMSS sheet row shape invalid: {sheet.key}")
                pd.DataFrame(rows, columns=list(sheet.headers)).to_excel(writer, sheet_name=sheet.title[:31], index=False)
        return path
