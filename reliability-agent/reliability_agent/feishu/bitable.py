"""多维表格（Bitable）读取与字段归一化。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterator

from ..config import SourceConfig
from .client import FeishuClient


def _flatten_value(value: Any) -> Any:
    """把多维表格的复杂字段值转成可序列化的简单值。"""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "name", "en_name", "full_name"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
                        break
                else:
                    if isinstance(item.get("link"), str):
                        parts.append(item["link"])
                    else:
                        parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "、".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "name", "link"):
            if isinstance(value.get(key), str):
                return value[key]
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _to_ms(value: Any) -> int | None:
    """把日期字段值（毫秒时间戳/字符串/日期）统一成毫秒时间戳。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:  # 微秒
            number /= 1000.0
        return int(number)
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        if number > 1e12:
            number /= 1000.0
        return int(number)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(text, fmt).timestamp() * 1000)
        except ValueError:
            continue
    return None


def normalize_record(record: dict[str, Any], *, updated_field: str = "") -> dict[str, Any]:
    """把一条多维表格记录转成 {record_id, row, updated_at_ms}。"""
    fields = record.get("fields") or {}
    row: dict[str, Any] = {key: _flatten_value(value) for key, value in fields.items()}
    row["_record_id"] = record.get("record_id", "")
    updated_ms = _to_ms(fields.get(updated_field)) if updated_field else None
    return {"record_id": record.get("record_id", ""), "row": row, "updated_at_ms": updated_ms}


class BitableSource:
    def __init__(self, client: FeishuClient, config: SourceConfig):
        self.client = client
        self.config = config
        self.logger = logging.getLogger("reliability_agent.bitable")

    @property
    def table_key(self) -> str:
        return f"{self.config.app_token}/{self.config.table_id}"

    def list_fields(self) -> list[str]:
        path = f"/open-apis/bitable/v1/apps/{self.config.app_token}/tables/{self.config.table_id}/fields"
        page_token: str | None = None
        names: list[str] = []
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self.client.api("GET", path, params=params)
            for item in data.get("items") or []:
                if item.get("field_name"):
                    names.append(str(item["field_name"]))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return names

    def iter_records(
        self,
        *,
        since_ms: int | None = None,
        updated_field: str = "",
    ) -> Iterator[dict[str, Any]]:
        """分页读取记录；since_ms 提供时按日期字段做服务端增量过滤。"""
        path = (
            f"/open-apis/bitable/v1/apps/{self.config.app_token}"
            f"/tables/{self.config.table_id}/records/search"
        )
        body: dict[str, Any] = {}
        if self.config.view_id:
            body["view_id"] = self.config.view_id
        if since_ms is not None and updated_field:
            body["filter"] = {
                "conjunction": "and",
                "conditions": [
                    {
                        "field_name": updated_field,
                        "operator": "isGreater",
                        "value": ["ExactDate", str(int(since_ms))],
                    }
                ],
            }

        page_token: str | None = None
        fetched = 0
        while True:
            params: dict[str, Any] = {"page_size": self.config.page_size}
            if page_token:
                params["page_token"] = page_token
            data = self.client.api("POST", path, params=params, body=body)
            items = data.get("items") or []
            for item in items:
                fetched += 1
                yield item
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        self.logger.debug("读取记录完成，共 %s 条", fetched)
