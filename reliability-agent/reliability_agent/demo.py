"""Demo 数据：生成带删失的韦布尔寿命数据，用于无飞书凭证时跑通全流程。"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def generate_demo_dataframe(seed: int = 42, now: datetime | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    now = now or datetime.now()
    groups = [
        ("A型电源模块", 1.8, 5200.0, 240),
        ("B型电源模块", 2.4, 7800.0, 260),
        ("C型电源模块", 3.1, 4200.0, 220),
    ]

    rows: list[dict[str, object]] = []
    for name, beta, eta, count in groups:
        failure_time = eta * rng.weibull(beta, count)
        censor_time = rng.exponential(scale=eta * 0.85, size=count)
        failed = failure_time <= censor_time
        observed = np.where(failed, failure_time, censor_time)
        batches = rng.integers(1, 6, size=count)
        ages = rng.integers(0, 30 * 86400, size=count)

        for index in range(count):
            updated = now - timedelta(seconds=int(ages[index]))
            rows.append(
                {
                    "产品型号": name,
                    "批次": f"B{batches[index]:02d}",
                    "使用时长(h)": round(float(observed[index]), 1),
                    "是否失效": bool(failed[index]),
                    "更新时间": int(updated.timestamp() * 1000),
                }
            )

    return pd.DataFrame(rows)
