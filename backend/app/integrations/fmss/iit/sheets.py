from ..client import FmssClient
from .schemas import FmssSheet


def list_sheets(client: FmssClient, stage: str) -> list[FmssSheet]:
    payload = client.sheets(stage)
    if not isinstance(payload, list):
        raise ValueError("FMSS工作表定义格式异常")
    return [FmssSheet.from_payload(item) for item in payload if isinstance(item, dict)]
