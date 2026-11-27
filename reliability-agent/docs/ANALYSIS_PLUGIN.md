# 自定义可靠性预计插件开发

工具本身不包含你的可靠性模型，只负责「取数 → 调用插件 → 导出」。内置 `weibull_example.py` 仅用于演示接口和跑通流程。

## 1. 插件契约

插件是一个普通 Python 函数：

```python
def analyze(df: pandas.DataFrame, ctx: AnalysisContext) -> AnalysisResult: ...
```

输入 `df`：本地镜像中的全量最新数据（列名为多维表格字段名，经过 `source.column_map` 映射后；日期字段仍可能是毫秒时间戳）。

返回 `AnalysisResult`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `summary` | `pd.DataFrame` | 主结果表，写入 Excel「分析结果」并回写飞书表格 |
| `metrics` | `dict` | 关键指标，写入 Excel「概览」与飞书表格 |
| `extra_sheets` | `dict[str, DataFrame]` | 附加结果表，每项一个 Excel sheet |
| `figures` | `list[Figure]` | PNG 图片，写入 Excel「图表」sheet |
| `notes` | `list[str]` | 说明/告警，写入 Excel 与飞书表格尾部 |

`AnalysisContext`：

| 字段 | 说明 |
| --- | --- |
| `run_id` | 本次运行 ID |
| `options` | `config.yaml` 中 `analysis.options` 的字典 |
| `output_dir` | Excel 输出目录 |

`Figure(name, png)`：`png` 为 PNG 字节串，可直接由 matplotlib 生成。

## 2. 加载方式

```yaml
analysis:
  # 项目内文件（相对 config.yaml 所在目录）
  plugin: "plugins/my_reliability.py:analyze"
  # 或已安装模块
  # plugin: "my_company.reliability:analyze"
  options:
    time_field: "使用时长(h)"
    failure_field: "是否失效"
    group_field: "产品型号"
    # 自定义参数随意添加，插件内通过 ctx.options 读取
    confidence: 0.9
    mission_hours: 5000
```

## 3. 最小可运行示例

新建 `plugins/my_reliability.py`（该文件以模拟数据的列名为例）：

```python
from __future__ import annotations

import math
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from reliability_agent.analysis.base import AnalysisContext, AnalysisResult, Figure


def _to_failure(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return float(value) != 0
    return str(value).strip().lower() in {"1", "true", "是", "失效", "f", "fail"}


def analyze(df: pd.DataFrame, ctx: AnalysisContext) -> AnalysisResult:
    options = ctx.options or {}
    time_field = options.get("time_field", "使用时长(h)")
    failure_field = options.get("failure_field", "是否失效")
    group_field = options.get("group_field", "产品型号")
    mission_hours = float(options.get("mission_hours", 5000))

    for field in (time_field, failure_field):
        if field not in df.columns:
            raise ValueError(f"缺少字段: {field}；现有字段: {list(df.columns)}")

    work = pd.DataFrame({
        "time": pd.to_numeric(df[time_field], errors="coerce"),
        "failed": df[failure_field].map(_to_failure),
        "group": df[group_field].fillna("未知").astype(str),
    }).dropna(subset=["time"])
    work = work[work["time"] > 0]

    rows = []
    figures = []
    for group, subset in work.groupby("group"):
        n = len(subset)
        failures = int(subset["failed"].sum())
        total_time = float(subset["time"].sum())
        mtbf = total_time / failures if failures else float("nan")

        # ==== 这里替换成你的可靠性预计模型（韦布尔、指数、加速寿命等） ====
        estimated = {
            "分组": group,
            "样本数": n,
            "失效数": failures,
            "观测总时长": round(total_time, 1),
            "经验 MTBF(h)": round(mtbf, 1) if failures else None,
            f"任务 {int(mission_hours)}h 预计失效数": round(mission_hours / mtbf * n, 3) if failures else None,
        }
        # ==============================================================

        rows.append(estimated)

        fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=130)
        subset["time"].plot(kind="hist", bins=20, ax=ax, alpha=0.7)
        ax.set_title(f"{group} 寿命分布")
        ax.set_xlabel("时间")
        fig.tight_layout()
        import io
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        plt.close(fig)
        figures.append(Figure(name=f"{group}-寿命分布", png=buffer.getvalue()))

    summary = pd.DataFrame(rows)
    metrics = {
        "分析模型": "自定义可靠性预计",
        "参与分析样本": int(len(work)),
        "分组数": int(summary.shape[0]) if not summary.empty else 0,
    }
    notes = ["本结果由自定义插件生成，请核对模型假设。"]
    return AnalysisResult(summary=summary, metrics=metrics, figures=figures, notes=notes)
```

## 4. 调试方法

1. 用内置模拟数据直接验证插件（不需要飞书凭证）：

```bat
python -m reliability_agent --config config.yaml run-once --demo
```

2. 单独调用调试：

```python
from pathlib import Path
from reliability_agent.analysis.base import AnalysisContext
from reliability_agent.analysis.loader import load_analyzer
from reliability_agent.demo import generate_demo_dataframe

analyzer = load_analyzer("plugins/my_reliability.py:analyze")
ctx = AnalysisContext(run_id="debug", options={"mission_hours": 3000}, output_dir=Path("output"))
result = analyzer(generate_demo_dataframe(), ctx)
print(result.summary)
```

## 5. 约定与注意事项

- 必须返回 `AnalysisResult`，`summary` 不能是 `None`；无结果时抛出带说明的异常。
- 列名必须与飞书表格字段一致；不一致时用 `source.column_map` 映射，或在插件里做兼容。
- 不要修改传入 `df`（需要清洗时先 `copy()`）。
- 图表使用 `matplotlib.use("Agg")`，不要调用 `plt.show()`。
- 插件在本机进程内运行，不要在其中访问外部网络或写入数据库，避免破坏「数据不外泄」约束。
- 运行失败会记录到 `runs` 表并写入日志 `logs/agent.log`，飞书表格不会被半截覆盖（写入在分析成功之后）。
- 需要多张结果表时用 `extra_sheets`；需要团队可见的总结时，把核心数字放进 `metrics` 和 `summary`。
