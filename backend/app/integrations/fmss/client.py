from __future__ import annotations

from pathlib import Path
from typing import Any
from calendar import monthrange
from datetime import date
from copy import deepcopy

import httpx

from .config import api_base_url
from .errors import FmssApiError, FmssNotAuthenticated, FmssPermissionDenied
from .session import FmssSession, fmss_session


class FmssClient:
    """Small authenticated FMSS client. GET may retry once; writes never retry."""

    def __init__(self, session: FmssSession = fmss_session, *, timeout: float = 30.0) -> None:
        self.session = session
        self.timeout = timeout
        self._balance_schema: dict[str, Any] | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: Any = None,
        data: dict[str, Any] | None = None,
        response_kind: str = "iit",
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
                if response_kind == "dsp":
                    if not isinstance(payload, dict) or payload.get("retcode") != "0000":
                        if isinstance(payload, dict) and str(payload.get("code")) == "401":
                            self.session.clear()
                            raise FmssNotAuthenticated()
                        message = payload.get("retmsg") or payload.get("msg") if isinstance(payload, dict) else None
                        raise FmssApiError("支撑平台数据查询失败：" + str(message or "响应格式异常"))
                    if self.session.snapshot().generation != generation:
                        raise FmssNotAuthenticated()
                    return payload
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

    def security_tax_rows(self, kind: str, branch_code: str, year: int, month: int) -> list[dict[str, Any]]:
        paths = {"interest_tax": "fin_bond_interest_pay_tax", "tax_sheet": "fin_rstk_tax"}
        path = paths[kind]
        begin = date(year, month, 1).strftime("%Y%m%d")
        end = date(year, month, monthrange(year, month)[1]).strftime("%Y%m%d")
        rows: list[dict[str, Any]] = []
        total: int | None = None
        page = 1
        while True:
            payload = self._request("POST", f"/dspapi/{path}", response_kind="dsp", json={
                "pageNum": page, "pageSize": 500, "branchNos": [branch_code],
                "initDate": [begin, end], "beginDate": begin, "endDate": end,
                "clientId": "", "fundAccount": "", "stockAccount": "", "clientName": "",
            })
            batch = payload.get("response_body")
            try:
                count = int(payload["totalrecords"])
                index = int(payload["pageindex"])
            except (KeyError, TypeError, ValueError) as exc:
                raise FmssApiError("支撑平台分页信息异常，未保存不完整数据") from exc
            if (not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch)
                    or count < 0 or index != page or (total is not None and total != count)):
                raise FmssApiError("支撑平台分页数据发生变化或格式异常，请重新提取")
            total = count
            rows.extend(batch)
            if len(rows) == total:
                return rows
            if not batch or len(rows) > total or page >= 1000:
                raise FmssApiError("支撑平台分页不完整，未保存查询结果")
            page += 1

    def balance_preview(self, org_code: str, year: int, month: int) -> Any:
        period = f"{year}-{month:02d}"
        path = "/report/sub/v2/formula/preview/794"
        if self._balance_schema is None:
            initial = self._request("POST", path, json={})
            if not isinstance(initial, dict) or not isinstance(initial.get("schema"), dict):
                raise FmssApiError("支撑平台余额表模板读取失败")
            self._balance_schema = initial["schema"]
        schema = deepcopy(self._balance_schema)
        # FMSS preview takes effective parameters from schema, overriding dataMap.
        parameters = schema.get("workbook", {}).get("fmssReportParams") or schema.get("report", {}).get("reportParams", [])
        if not {"segment1", "busiDate"}.issubset({param.get("refKey") for param in parameters}):
            raise FmssApiError("支撑平台余额表查询参数已变化")
        schema.setdefault("report", {})["reportParams"] = deepcopy(parameters)
        schema.setdefault("workbook", {})["fmssReportParams"] = deepcopy(parameters)
        for parameters in [schema["report"]["reportParams"], schema["workbook"]["fmssReportParams"]]:
            for param in parameters:
                if param.get("refKey") == "segment1":
                    param.update(value=org_code, displayName="")
                elif param.get("refKey") == "busiDate":
                    param.update(value=period, year=str(year), periodCode=f"{month:02d}")
        result = self._request("POST", path, json={"schema": schema, "dataMap": {
            "segment1": org_code, "company": org_code,
            "busiDate": period, "busDate": period, "busi_date": period, "period": period,
            "year": str(year), "month": f"{month:02d}", "currencyCode": "CNY",
            "currencyUnit": "0", "deptType": "T", "periodType": "M", "judge": "0",
        }})
        trace = result.get("queryTrace") if isinstance(result, dict) else None
        if not isinstance(trace, list) or not trace or any(
            not isinstance(item, dict) or item.get("segment1") != org_code or item.get("period") != period for item in trace
        ):
            raise FmssApiError("余额表实际查询机构或期间不匹配，未保存查询结果")
        return result

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

    def get_iit_config(self, version: str = "") -> Any:
        return self._request("GET", "/iit/config", params={"version": version})
