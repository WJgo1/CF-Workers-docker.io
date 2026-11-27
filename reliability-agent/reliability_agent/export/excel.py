"""Excel 导出：概览 / 分析结果 / 数据快照 / 运行日志 / 图表。"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from ..analysis.base import AnalysisResult

_INVALID_SHEET_CHARS = set('[]:*?/\\')


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = "".join(ch for ch in str(name) if ch not in _INVALID_SHEET_CHARS).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        index += 1
    used.add(candidate)
    return candidate


def _format_date_columns(df: pd.DataFrame, date_fields: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for col in date_fields:
        if col not in out.columns:
            continue
        numeric = pd.to_numeric(out[col], errors="coerce")
        converted = pd.to_datetime(numeric, unit="ms", errors="coerce")
        formatted = converted.dt.strftime("%Y-%m-%d %H:%M:%S")
        out[col] = formatted.where(converted.notna(), out[col])
    return out


def _autofit(ws: Any, max_scan_rows: int = 500) -> None:
    for column_cells in ws.columns:
        column_index = column_cells[0].column or 1
        width = 8
        for row_index, cell in enumerate(column_cells):
            if row_index > max_scan_rows:
                break
            if cell.value is None:
                continue
            text = str(cell.value)
            display_width = sum(2 if ord(char) > 127 else 1 for char in text)
            width = max(width, display_width + 2)
        ws.column_dimensions[get_column_letter(column_index)].width = min(width, 50)


def export_excel(
    path: Path,
    *,
    dataframe: pd.DataFrame,
    result: AnalysisResult,
    overview: dict[str, Any],
    date_fields: Iterable[str] = (),
    max_preview_rows: int = 20000,
    runs_df: pd.DataFrame | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = _format_date_columns(dataframe, date_fields)
    preview = data.head(max_preview_rows) if len(data) > max_preview_rows else data

    overview_df = pd.DataFrame(
        [(key, value) for key, value in overview.items()], columns=["项目", "内容"]
    )

    used: set[str] = set()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        overview_df.to_excel(writer, sheet_name=_safe_sheet_name("概览", used), index=False)

        if result.summary is not None and not result.summary.empty:
            result.summary.to_excel(
                writer, sheet_name=_safe_sheet_name("分析结果", used), index=False
            )
        for name, extra in (result.extra_sheets or {}).items():
            if extra is not None and not extra.empty:
                extra.to_excel(writer, sheet_name=_safe_sheet_name(name, used), index=False)
        if not preview.empty:
            preview.to_excel(writer, sheet_name=_safe_sheet_name("数据快照", used), index=False)
        if runs_df is not None and not runs_df.empty:
            runs_df.to_excel(writer, sheet_name=_safe_sheet_name("运行日志", used), index=False)

        if result.figures:
            chart_ws = writer.book.create_sheet(_safe_sheet_name("图表", used))
            anchor_row = 1
            for figure in result.figures:
                chart_ws.cell(row=anchor_row, column=1, value=figure.name).font = Font(bold=True)
                image = XLImage(io.BytesIO(figure.png))
                original_width = image.width or 640
                original_height = image.height or 400
                image.width = 640
                image.height = max(int(original_height * 640 / original_width), 1)
                chart_ws.add_image(image, f"A{anchor_row + 1}")
                anchor_row += int(image.height / 20) + 3

        for ws in writer.book.worksheets:
            if ws.title == "图表":
                continue
            _autofit(ws)
            ws.freeze_panes = "A2"

    return path


def prune_old_excel(directory: Path, *, prefix: str, keep_days: int) -> int:
    """删除超过保留期的历史 Excel（只匹配 template 前缀）。"""
    if keep_days <= 0 or not prefix or not directory.is_dir():
        return 0
    deadline = datetime.now().timestamp() - keep_days * 86400
    removed = 0
    for file in directory.glob(f"{prefix}*.xlsx"):
        try:
            if file.stat().st_mtime < deadline:
                file.unlink()
                removed += 1
        except OSError:
            continue
    return removed
