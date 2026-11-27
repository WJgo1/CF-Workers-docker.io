"""电子表格回写：按标题定位/创建 sheet，清空后分块写入分析结果。"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter

from ..analysis.base import AnalysisResult
from .client import FeishuClient


def to_cell(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def dataframe_to_matrix(df: pd.DataFrame) -> list[list[Any]]:
    if df is None or df.empty:
        return []
    header = [str(col) for col in df.columns]
    rows = [[to_cell(value) for value in record] for record in df.itertuples(index=False, name=None)]
    return [header] + rows


def build_sheet_matrix(result: AnalysisResult, meta: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = [["可靠性分析结果"], []]
    for key, value in meta.items():
        rows.append([key, to_cell(value)])
    rows.append([])
    rows.append(["关键指标"])
    for key, value in (result.metrics or {}).items():
        rows.append([key, to_cell(value)])
    rows.append([])
    rows.append(["分析结果"])
    rows.extend(dataframe_to_matrix(result.summary))
    for name, extra in (result.extra_sheets or {}).items():
        rows.append([])
        rows.append([name])
        rows.extend(dataframe_to_matrix(extra))
    if result.notes:
        rows.append([])
        rows.append(["说明"])
        rows.extend([[note] for note in result.notes])

    width = max((len(row) for row in rows), default=1)
    return [row + [None] * (width - len(row)) for row in rows]


class SheetWriter:
    def __init__(self, client: FeishuClient, spreadsheet_token: str):
        self.client = client
        self.token = spreadsheet_token
        self.logger = logging.getLogger("reliability_agent.sheet")

    def list_sheets(self) -> list[dict[str, Any]]:
        path = f"/open-apis/sheets/v3/spreadsheets/{self.token}/sheets/query"
        data = self.client.api("GET", path)
        return data.get("sheets") or []

    def ensure_sheet(self, title: str) -> str:
        sheets = self.list_sheets()
        for sheet in sheets:
            if sheet.get("title") == title:
                return str(sheet.get("sheet_id"))
        self.logger.info("电子表格中不存在 sheet「%s」，自动创建", title)
        path = f"/open-apis/sheets/v2/spreadsheets/{self.token}/sheets_batch_update"
        body = {"requests": [{"addSheet": {"properties": {"title": title, "index": len(sheets)}}}]}
        data = self.client.api("POST", path, body=body)
        replies = data.get("replies") or []
        try:
            return str(replies[0]["addSheet"]["properties"]["sheetId"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"创建 sheet「{title}」失败，返回: {data}") from exc

    def clear(self, sheet_id: str, *, rows: int = 2000, cols: int = 30) -> None:
        last_col = get_column_letter(max(cols, 1))
        path = f"/open-apis/sheets/v2/spreadsheets/{self.token}/values_batch_clear"
        body = {"ranges": [{"range": f"{sheet_id}!A1:{last_col}{max(rows, 1)}"}]}
        self.client.api("POST", path, body=body)

    def push_matrix(
        self,
        title: str,
        matrix: list[list[Any]],
        *,
        clear_before_write: bool = True,
        chunk_rows: int = 500,
    ) -> str:
        if not matrix:
            raise ValueError("待写入内容为空")
        sheet_id = self.ensure_sheet(title)
        width = max(len(row) for row in matrix)
        if clear_before_write:
            self.clear(sheet_id, rows=max(len(matrix) + 50, 2000), cols=max(width + 5, 20))

        path = f"/open-apis/sheets/v2/spreadsheets/{self.token}/values_batch_update"
        last_col = get_column_letter(max(width, 1))
        step = max(chunk_rows, 1)
        for start in range(0, len(matrix), step):
            chunk = matrix[start : start + step]
            row_start = start + 1
            row_end = start + len(chunk)
            value_range = {
                "range": f"{sheet_id}!A{row_start}:{last_col}{row_end}",
                "values": [[("" if cell is None else cell) for cell in row] for row in chunk],
            }
            self.client.api("POST", path, body={"valueRange": [value_range]})
            self.logger.debug("写入 %s 行 %s-%s", title, row_start, row_end)
        self.logger.info("飞书电子表格「%s」写入完成，共 %s 行", title, len(matrix))
        return sheet_id
