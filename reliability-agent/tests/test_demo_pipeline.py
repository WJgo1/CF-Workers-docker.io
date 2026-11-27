from pathlib import Path

import pandas as pd
import pytest
import yaml

from reliability_agent.config import load_config
from reliability_agent.pipeline import execute


def _write_config(tmp_path: Path) -> Path:
    config = {
        "app": {"timezone": "Asia/Shanghai"},
        "source": {
            "app_token": "demo",
            "table_id": "demo",
            "date_fields": ["更新时间"],
        },
        "analysis": {
            "plugin": "reliability_agent.analysis.plugins.weibull_example:analyze",
            "options": {
                "time_field": "使用时长(h)",
                "failure_field": "是否失效",
                "group_field": "产品型号",
                "reliability_times": [1000, 3000, 5000],
            },
        },
        "output": {
            "excel": {"dir": str(tmp_path / "output"), "keep_days": 90},
            "feishu_sheet": {"enabled": False},
        },
        "schedule": {"enabled": False},
        "storage": {"db_path": str(tmp_path / "state.db")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


def test_demo_pipeline_end_to_end(tmp_path):
    config = load_config(_write_config(tmp_path))
    report = execute(config, demo=True, skip_sheet=True)

    assert report.status == "success"
    assert report.rows_total > 0
    excel_path = Path(report.excel_path or "")
    assert excel_path.is_file()

    workbook = pd.ExcelFile(excel_path)
    assert "概览" in workbook.sheet_names
    assert "分析结果" in workbook.sheet_names
    assert "数据快照" in workbook.sheet_names

    summary = pd.read_excel(excel_path, sheet_name="分析结果")
    assert len(summary) == 3
    assert (summary["形状参数β"] > 0).all()
    assert (summary["尺度参数η"] > 0).all()
    assert summary["样本数"].sum() > 0

    snapshot = pd.read_excel(excel_path, sheet_name="数据快照")
    assert "产品型号" in snapshot.columns
    assert snapshot["更新时间"].astype(str).str.match(r"\d{4}-\d{2}-\d{2}").all()


def test_demo_requires_analysis_fields(tmp_path):
    config = load_config(_write_config(tmp_path))
    config.analysis.options["time_field"] = "不存在的字段"
    with pytest.raises(ValueError):
        execute(config, demo=True, skip_sheet=True)
