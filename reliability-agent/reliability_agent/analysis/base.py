"""分析插件契约：用户的可靠性预计代码实现 analyze(df, ctx) -> AnalysisResult。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


@dataclass
class Figure:
    """待嵌入 Excel/报告的图片。"""

    name: str
    png: bytes


@dataclass
class AnalysisContext:
    run_id: str
    options: dict[str, Any] = field(default_factory=dict)
    output_dir: Path = Path(".")


@dataclass
class AnalysisResult:
    summary: pd.DataFrame
    metrics: dict[str, Any] = field(default_factory=dict)
    extra_sheets: dict[str, pd.DataFrame] = field(default_factory=dict)
    figures: list[Figure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Analyzer(Protocol):
    def __call__(self, df: pd.DataFrame, ctx: AnalysisContext) -> AnalysisResult: ...
