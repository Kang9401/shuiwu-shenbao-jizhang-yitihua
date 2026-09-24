from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from .config import api_base_url
from .errors import FmssApiError, FmssNotAuthenticated, FmssPermissionDenied
from .session import FmssSession, fmss_session


class FmssClient:
    """Small authenticated FMSS client. GET may retry once; writes never retry."""

    def __init__(self, session: FmssSession = fmss_session, *, timeout: float = 30.0) -> None:
        self.session = session
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: Any = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        authorization, generation = self.session.authorization_header()
        url = f"{api_base_url()}/{path.lstrip('/')}"
        attempts = 2 if method == "GET" else 1
        error: Exception | None = None
        for _ in range(attempts):
            try:
                response = httpx.request(
                    method,
                    url,
                    params=params,
                    headers={"Authorization": authorization},
                    json=json,
                    files=files,
                    data=data,
                    timeout=300.0 if files is not None else self.timeout,
                )
                if response.status_code == 401:
                    self.session.clear()
                    raise FmssNotAuthenticated()
                if response.status_code in {403, 404}:
                    raise FmssPermissionDenied()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("code") not in (0, 200, "0", "200"):
                    raise FmssApiError(str(payload.get("msg") if isinstance(payload, dict) else "FMSS响应格式异常"))
                if self.session.snapshot().generation != generation:
                    raise FmssNotAuthenticated()
                return payload.get("data")
            except (FmssNotAuthenticated, FmssPermissionDenied, FmssApiError):
                raise
            except (httpx.HTTPError, ValueError) as exc:
                error = exc
        raise FmssApiError("FMSS网络连接失败") from error

    def branches(self) -> Any:
        return self._request("GET", "/iit/branches")

    def sheets(self, stage: str) -> Any:
        return self._request("GET", "/iit/sheets", params={"stage": stage})

    def declaration(self, branch_code: str, month: str, stage: str) -> Any:
        return self._request("GET", "/iit/declaration", params={"branchCode": branch_code, "month": month, "stage": stage})

    def approval_log(self, branch_code: str, month: str) -> Any:
        return self._request("GET", "/iit/approval-log", params={"branchCode": branch_code, "month": month})

    def review(self, declaration_id: str | int) -> Any:
        return self._request("GET", f"/iit/review/{declaration_id}")

    def reviewers(self, branch_code: str, month: str, stage: str) -> Any:
        return self._request("GET", "/iit/reviewers", params={"branchCode": branch_code, "month": month, "stage": stage})

    def current_user(self, path: str) -> Any:
        """Call only a configured, confirmed current-user endpoint."""
        return self._request("GET", path)

    def import_iit_workbook(self, branch_code: str, month: str, stage: str, file_path: Path) -> Any:
        with file_path.open("rb") as handle:
            return self._request(
                "POST",
                "/iit/import",
                data={"branchCode": branch_code, "month": month, "stage": stage},
                files={"file": (file_path.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

    def upload_iit_attachment(
        self,
        branch_code: str,
        month: str,
        stage: str,
        file_path: Path,
        *,
        file_name: str | None = None,
    ) -> Any:
        with file_path.open("rb") as handle:
            return self._request(
                "POST",
                "/iit/attachment/upload",
                data={"branchCode": branch_code, "month": month, "stage": stage},
                files={"file": (file_name or file_path.name, handle, "application/pdf")},
            )

    def submit_iit_declaration(self, declaration_id: str | int, reviewer: str) -> Any:
        return self._request("POST", "/iit/submit", json={"id": int(declaration_id), "reviewer": reviewer.strip()})

    def withdraw_iit_declaration(self, declaration_id: str | int) -> Any:
        return self._request("POST", f"/iit/withdraw/{int(declaration_id)}")

    def decide_iit_declaration(self, declaration_id: str | int, passed: bool, comment: str) -> Any:
        return self._request(
            "POST",
            "/iit/decision",
            json={"id": int(declaration_id), "pass": bool(passed), "comment": comment.strip()},
        )

    def upload_iit_certificates(self, declaration_id: str | int, file_paths: list[Path]) -> Any:
        if not file_paths:
            raise FmssApiError("没有可绑定的完税凭证文件")
        with ExitStack() as stack:
            files = [
                ("files", (path.name, stack.enter_context(path.open("rb")), "application/pdf"))
                for path in file_paths
            ]
            return self._request("POST", f"/iit/certificate/{declaration_id}/batch", files=files)

    def certificates(self, declaration_id: str | int) -> Any:
        return self._request("GET", f"/iit/certificate/{declaration_id}")

    def get_iit_config(self, version: str = "") -> Any:
        return self._request("GET", "/iit/config", params={"version": version})
