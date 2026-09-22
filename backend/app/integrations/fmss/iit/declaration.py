from ..client import FmssClient


def get_declaration(client: FmssClient, branch_code: str, month: str, stage: str):
    return client.declaration(branch_code, month, stage)
