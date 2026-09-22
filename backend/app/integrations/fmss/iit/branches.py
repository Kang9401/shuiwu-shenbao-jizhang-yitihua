from ..client import FmssClient


def list_branches(client: FmssClient):
    return client.branches()
