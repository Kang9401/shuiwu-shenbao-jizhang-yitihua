from ..client import FmssClient


def get_approval_log(client: FmssClient, branch_code: str, month: str):
    return client.approval_log(branch_code, month)
