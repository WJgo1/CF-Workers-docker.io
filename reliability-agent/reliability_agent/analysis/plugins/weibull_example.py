"""内置韦布尔分析示例插件。

说明：该文件仅用于演示插件契约和端到端流程，请按你的可靠性预计模型
替换为正式代码（可复制本文件到项目 plugins/ 目录后修改）。
"""

from __future__ import annotations

import io
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

from ..base import AnalysisContext, AnalysisResult, Figure

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

_TRUE_VALUES = {"1", "true", "yes", "y", "是", "失效", "失败", "f", "fail", "failed", "坏"}
_FALSE_VALUES = {"", "0", "false", "no", "n", "否", "未失效", "正常", "s", "pass", "ok", "好"}


def _to_failure(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) != 0
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return bool(text)


def _fit_weibull(times: np.ndarray, failed: np.ndarray) -> tuple[float, float]:
    """右删失数据下的两参数韦布尔 MLE（loc=0）。"""
    mask = np.isfinite(times) & (times > 0)
    times = times[mask]
    failed = failed[mask]
    failures = times[failed]
    if failures.size == 0:
        raise ValueError("没有失效样本，无法拟合韦布尔分布")

    log_t = np.log(times)

    def negative_log_likelihood(params: np.ndarray) -> float:
        beta, eta = np.exp(params)
        log_eta = math.log(eta)
        log_z = beta * (log_t - log_eta)
        z = np.exp(np.clip(log_z, -700.0, 50.0))
        log_pdf_failed = math.log(beta) - log_eta + (beta - 1.0) * (log_t - log_eta)
        return float(-np.sum(log_pdf_failed[failed] - z[failed]) + np.sum(z[~failed]))

    initial_eta = float(np.median(failures)) if failures.size else float(np.median(times))
    x0 = np.array(
        [
            math.log(1.5),
            math.log(max(min(initial_eta, 1e11), 1e-3)),
        ]
    )
    result = optimize.minimize(
        negative_log_likelihood,
        x0=x0,
        method="L-BFGS-B",
        bounds=[(math.log(1e-3), math.log(1e3)), (math.log(1e-3), math.log(1e12))],
    )
    if result.success and np.isfinite(result.fun):
        beta, eta = np.exp(result.x)
    else:  # 数值优化失败时退回 scipy 内置拟合（仅失效样本）
        beta, _loc, eta = stats.weibull_min.fit(failures, floc=0)

    beta = float(beta)
    eta = float(eta)
    if not (np.isfinite(beta) and np.isfinite(eta)) or beta <= 0 or eta <= 0:
        raise ValueError("韦布尔参数拟合失败")
    return beta, eta


def _figure_to_png(fig: Any, name: str) -> Figure:
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return Figure(name=name, png=buffer.getvalue())


def _probability_plot(group: str, times: np.ndarray, failed: np.ndarray, beta: float, eta: float) -> Figure | None:
    fail_times = np.sort(times[failed])
    n = fail_times.size
    if n < 3:
        return None
    ranks = (np.arange(1, n + 1) - 0.3) / (n + 0.4)
    x = np.log(fail_times)
    y = np.log(-np.log(1.0 - ranks))

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=130)
    ax.plot(x, y, "o", ms=4, label="经验点（中位秩）")
    xx = np.linspace(x.min() - 0.2, x.max() + 0.2, 50)
    ax.plot(xx, beta * (xx - math.log(eta)), "-", lw=1.6, label=f"拟合 β={beta:.3f}, η={eta:.1f}")
    ax.set_xlabel("ln(时间)")
    ax.set_ylabel("ln(-ln(1-F))")
    ax.set_title(f"{group} 韦布尔概率图")
    ax.grid(alpha=0.3)
    ax.legend()
    return _figure_to_png(fig, f"{group}-概率图")


def _reliability_plot(
    group: str,
    times: np.ndarray,
    beta: float,
    eta: float,
    b10: float,
    reliability_times: list[float],
) -> Figure:
    max_t = max(float(np.max(times)), b10) * 1.2
    grid = np.linspace(max(max_t * 0.001, 0.01), max_t, 300)
    reliability = np.exp(-((grid / eta) ** beta))

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=130)
    ax.plot(grid, reliability, lw=1.8, label=f"R(t), β={beta:.3f}, η={eta:.1f}")
    ax.axvline(b10, color="#d9534f", ls="--", lw=1.2, label=f"B10={b10:.1f}")
    for t in reliability_times:
        r = math.exp(-((t / eta) ** beta))
        ax.plot([t], [r], "o", ms=3.5, color="#5bc0de")
        ax.annotate(f"{int(t)}h: {r:.3f}", (t, r), textcoords="offset points", xytext=(4, 6), fontsize=8)
    ax.set_xlabel("时间")
    ax.set_ylabel("可靠度 R(t)")
    ax.set_ylim(0, 1.02)
    ax.set_title(f"{group} 可靠度曲线")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    return _figure_to_png(fig, f"{group}-可靠度曲线")


def analyze(df: pd.DataFrame, ctx: AnalysisContext) -> AnalysisResult:
    options = ctx.options or {}
    time_field = str(options.get("time_field", "使用时长(h)"))
    failure_field = str(options.get("failure_field", "是否失效"))
    group_field = options.get("group_field")
    reliability_times = [float(item) for item in (options.get("reliability_times") or [1000, 3000, 5000])]
    max_groups = int(options.get("max_groups", 8))
    plots = str(options.get("plots", "both")).lower()

    for field in (time_field, failure_field):
        if field not in df.columns:
            raise ValueError(
                f"数据中缺少字段「{field}」。当前字段: {', '.join(map(str, df.columns))}；"
                "请检查 analysis.options 或 source.column_map"
            )

    work = pd.DataFrame(
        {
            "time": pd.to_numeric(df[time_field], errors="coerce"),
            "failed": df[failure_field].map(_to_failure).astype(bool),
        }
    )
    if group_field and group_field in df.columns:
        work["group"] = df[group_field].fillna("未知").astype(str)
    else:
        work["group"] = "全部"
        if group_field:
            work.attrs["group_missing"] = True

    work = work[np.isfinite(work["time"]) & (work["time"] > 0)]
    if work.empty:
        raise ValueError(f"字段「{time_field}」中没有可用的正数时间数据")

    groups = sorted(work["group"].unique().tolist())
    notes: list[str] = ["内置韦布尔插件仅作示例，请替换为正式可靠性预计代码。"]
    if len(groups) > max_groups:
        notes.append(f"分组数 {len(groups)} 超过上限 {max_groups}，仅分析前 {max_groups} 组。")
        groups = groups[:max_groups]

    summary_rows: list[dict[str, Any]] = []
    figures: list[Figure] = []
    total_failures = 0

    for group in groups:
        subset = work[work["group"] == group]
        times = subset["time"].to_numpy(dtype=float)
        failed = subset["failed"].to_numpy(dtype=bool)
        n_fail = int(failed.sum())
        if n_fail == 0:
            notes.append(f"分组「{group}」没有失效样本，已跳过。")
            continue
        beta, eta = _fit_weibull(times, failed)
        total_failures += n_fail

        b10 = eta * (-math.log(0.9)) ** (1.0 / beta)
        mtbf = eta * math.gamma(1.0 + 1.0 / beta)
        row: dict[str, Any] = {
            "分组": group,
            "样本数": int(times.size),
            "失效数": n_fail,
            "删失数": int(times.size - n_fail),
            "形状参数β": round(beta, 4),
            "尺度参数η": round(eta, 2),
            "B10寿命(h)": round(b10, 1),
            "MTBF(h)": round(mtbf, 1),
        }
        for t in reliability_times:
            row[f"R({int(t)}h)"] = round(math.exp(-((t / eta) ** beta)), 6)
        summary_rows.append(row)

        if plots in {"both", "prob"}:
            figure = _probability_plot(group, times, failed, beta, eta)
            if figure is not None:
                figures.append(figure)
        if plots in {"both", "reliability"}:
            figures.append(_reliability_plot(group, times, beta, eta, b10, reliability_times))

    if not summary_rows:
        raise ValueError("所有分组都没有失效样本，无法完成韦布尔分析")

    summary = pd.DataFrame(summary_rows)
    metrics: dict[str, Any] = {
        "分析模型": "Weibull 2参数（右删失 MLE）",
        "时间字段": time_field,
        "失效字段": failure_field,
        "分组字段": group_field if group_field in df.columns else "无",
        "参与分析样本": int(work.shape[0]),
        "失效样本": total_failures,
        "有效分组数": len(summary_rows),
    }
    if work.attrs.get("group_missing"):
        notes.append(f"数据中不存在分组字段「{group_field}」，已按全部样本分析。")
    notes.append("参数基于右删失样本做极大似然估计；如需置信区间或加速寿命模型，请在正式插件中实现。")

    return AnalysisResult(summary=summary, metrics=metrics, figures=figures, notes=notes)
