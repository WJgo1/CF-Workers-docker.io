"""飞书开放平台 HTTP 客户端：tenant_access_token 缓存、重试、统一错误处理。"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from ..config import FeishuConfig


class FeishuError(RuntimeError):
    """飞书接口调用失败。"""

    def __init__(self, message: str, *, code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.code = code
        self.payload = payload


class FeishuClient:
    def __init__(self, config: FeishuConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger("reliability_agent.feishu")
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expire_at = 0.0

    # ------------------------------------------------------------------ 鉴权
    def _fetch_token(self) -> None:
        url = f"{self.config.base_url}/open-apis/auth/v3/tenant_access_token/internal"
        body = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
        resp = self._raw_request("POST", url, json_body=body, need_token=False)
        if resp.get("code") != 0:
            raise FeishuError(
                f"获取 tenant_access_token 失败: {resp.get('msg')}",
                code=resp.get("code"),
                payload=resp,
            )
        self._token = str(resp["tenant_access_token"])
        expire = int(resp.get("expire", 7200))
        self._token_expire_at = time.time() + max(expire - 120, 60)
        self.logger.debug("tenant_access_token 已刷新，有效期 %ss", expire)

    def _ensure_token(self) -> str:
        if not self._token or time.time() >= self._token_expire_at:
            self._fetch_token()
        assert self._token is not None
        return self._token

    # -------------------------------------------------------------- 底层请求
    def _raw_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        need_token: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            headers["Authorization"] = f"Bearer {self._ensure_token()}" if need_token else ""
            if not need_token:
                headers.pop("Authorization", None)
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise FeishuError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    raise FeishuError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise FeishuError(f"飞书返回非 JSON: {resp.text[:300]}") from exc
                if data.get("code") not in (0, None):
                    raise FeishuError(
                        f"飞书接口错误 code={data.get('code')}: {data.get('msg')}",
                        code=data.get("code"),
                        payload=data,
                    )
                return data
            except (requests.RequestException, FeishuError) as exc:
                last_error = exc
                message = str(exc)
                retryable = isinstance(exc, requests.RequestException) or "HTTP 5" in message or "HTTP 429" in message
                if not retryable or attempt >= self.config.max_retries:
                    raise
                sleep_seconds = self.config.retry_backoff_seconds * attempt
                self.logger.warning(
                    "飞书请求失败（第 %s/%s 次）: %s，%.1fs 后重试",
                    attempt,
                    self.config.max_retries,
                    exc,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)

        raise last_error if last_error else FeishuError("未知错误")

    def api(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        resp = self._raw_request(method, url, params=params, json_body=body)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    # -------------------------------------------------------------- 连通性
    def ping(self) -> None:
        """验证应用凭证是否可用。"""
        self._ensure_token()
