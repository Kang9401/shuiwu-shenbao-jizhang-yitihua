from pathlib import Path

from app.integrations.fmss.client import FmssClient


def import_workpaper(client: FmssClient, branch_code: str, month: str, stage: str, file_path: Path):
    return client.import_iit_workbook(branch_code, month, stage, file_path)
