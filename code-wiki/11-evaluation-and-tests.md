# 11 评测与测试

仓库包含两套质量保障体系：`evaluation/` 用于在真实软件工程 benchmark 上评估 Agent，`tests/` 用于保证代码本身正确。

## 11.1 Benchmark 评测概览

评测框架位于 `evaluation/`，支持三类 benchmark：

| Benchmark | 数据集 | 说明 |
| --- | --- | --- |
| SWE-bench | `SWE-bench`、`SWE-bench_Lite`、`SWE-bench_Verified` | Python 真实 issue 修复 |
| SWE-bench-Live | `SWE-bench-Live/lite`、`SWE-bench-Live/verified`、`SWE-bench-Live/full` | 按月更新的实时 benchmark |
| Multi-SWE-bench | `Multi-SWE-bench-flash`、`Multi-SWE-bench_mini` | 7 种语言（Java/TS/JS/Go/Rust/C/C++） |

数据集与镜像映射集中在 [evaluation/utils.py](file:///workspace/trae-agent/evaluation/utils.py#L170-L260) 的 `BenchmarkConfig` / `BENCHMARK_CONFIG`：每个 benchmark 声明 `valid_datasets`、`load_dataset`、`image_name(instance_id)` 等。

### 11.1.1 前置条件

- Docker 可用（每个 instance 有独立镜像，可能数 GB）；
- Python 3.12+、Git；
- 足够的磁盘空间；
- 有效的模型 API Key；
- 安装 evaluation 依赖：`uv sync --extra evaluation`（`datasets`、`docker`、`pexpect`、`unidiff`）。

### 11.1.2 初始化 Harness

```bash
cd evaluation
chmod +x setup.sh
./setup.sh swe_bench          # 或 swe_bench_live / multi_swe_bench
```

脚本会克隆对应 harness 仓库、检出固定 commit、创建虚拟环境并安装。详细说明见 [evaluation/README.md](file:///workspace/trae-agent/evaluation/README.md)。

### 11.1.3 运行评测

入口 [evaluation/run_evaluation.py](file:///workspace/trae-agent/evaluation/run_evaluation.py)：

```bash
python run_evaluation.py \
  --benchmark SWE-bench \
  --dataset SWE-bench_Verified \
  --config-file ./trae_config.yaml \
  --working-dir ./trae-workspace \
  --benchmark-harness-path ./SWE-bench \
  --docker-env-config ./docker_env_config.json \
  --mode e2e \
  --max_workers 4 \
  --instance_ids astropy__astropy-13453
```

参数（[run_evaluation.py#L379-L440](file:///workspace/trae-agent/evaluation/run_evaluation.py#L379-L440)）：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--benchmark` | `SWE-bench` | benchmark 名称 |
| `--dataset` | `SWE-bench_Verified` | 数据集名称 |
| `--working-dir` | `./trae-workspace` | 工作目录（临时文件、构建产物） |
| `--config-file` | `trae_config.yaml` | Trae Agent 配置 |
| `--docker-env-config` | `""` | 自定义 Docker 环境变量 JSON |
| `--instance_ids` | 全部 | 只跑指定实例 |
| `--benchmark-harness-path` | `""` | harness 路径（eval 模式必需） |
| `--run-id` | `trae-agent` | 结果目录标识 |
| `--mode` | `e2e` | `e2e` / `expr` / `eval` |
| `--max_workers` | `4` | 并行 worker 数 |

### 11.1.4 `BenchmarkEvaluation` 主要流程

[run_evaluation.py#L23-L378](file:///workspace/trae-agent/evaluation/run_evaluation.py#L23-L378)：

1. 校验 benchmark / dataset，加载数据集；
2. 初始化 Docker client，`pull_images()` 拉取所需镜像；
3. 把配置文件复制到 `working_dir/trae_config.yaml`；
4. 创建 `results/<benchmark>_<dataset>_<run_id>/`；
5. `prepare_trae_agent()`：构建 `trae-agent.tar`、`uv.tar`、`uv_shared.tar` 等复用产物；
6. `prepare_experiment_container(instance)`：基于 instance 镜像准备容器；
7. `run_one_instance(instance_id)`：写 `problem_statement.txt` → 运行 Trae Agent → 收集 patch；
8. `run_all()`：`ThreadPoolExecutor` + `as_completed` 并行执行，带进度条；
9. `run_eval()` / `get_all_preds()`：调用 harness 评测，产出 `results.json`。

### 11.1.5 输出目录

```text
results/{benchmark}_{dataset}_{run_id}/
├── predictions.json          # 待评测 patch
├── results.json              # 最终评测结果
├── {instance_id}/
│   ├── problem_statement.txt # issue 文本
│   ├── {instance_id}.patch   # 生成的 patch
│   ├── {instance_id}.json    # trajectory
│   └── ...
trae-workspace/
├── trae_config.yaml
├── trae-agent.tar
├── uv.tar
└── uv_shared.tar
```

### 11.1.6 三种模式

| 模式 | 行为 |
| --- | --- |
| `expr` | 只生成 patch，不评测 |
| `eval` | 只评测已有 patch / predictions |
| `e2e` | 生成 + 评测（默认） |

### 11.1.7 Docker 环境变量

`docker_env_config.json` 支持分阶段注入：

```json
{
  "preparation_env": {"HTTP_PROXY": "...", "HTTPS_PROXY": "..."},
  "experiment_env": {"CUSTOM_VAR": "value"}
}
```

`preparation_env` 用于准备阶段，`experiment_env` 用于实例执行阶段。

## 11.2 Patch Selection（Selector Agent）

`evaluation/patch_selection/` 实现了论文中的「生成 → 剪枝 → 选择」集成推理流程，用于在多个候选 patch 中挑选最优解。

| 文件 | 作用 |
| --- | --- |
| `selector.py` | 入口 CLI：读取候选 patch，调用 Selector Agent，保存结果 |
| `analysis.py` | 结果分析 |
| `trae_selector/selector_agent.py` | `CandidatePatch`、`SelectorAgent`：候选管理与选择逻辑 |
| `trae_selector/selector_evaluation.py` | `SelectorEvaluation`：选择效果评估 |
| `trae_selector/sandbox.py` | `Sandbox`：在容器内执行验证 |
| `trae_selector/tools/` | 选择器专用工具（bash / edit / run 等） |
| `trae_selector/utils.py` | 辅助函数 |

输入为 JSONL，每条包含 `instance_id`、`issue`、`patches`、`success_id`、`regressions`（可选）。使用方式：

```bash
python3 evaluation/patch_selection/selector.py \
  --instances_path path/to/swebench-verified.json \
  --candidate_path path/to/patch_candidates.jsonl \
  --result_path path/to/save/results \
  --num_candidate N
```

注意事项：

- 需要额外下载 Python 3.12 包并解压到 `evaluation/patch_selection/trae_selector/tools/py312`；
- regression 字段可对接 Agentless 的回归测试选择结果；
- 该子目录的代码风格与主包不同（自带轻量 `Tool` 定义），`pre-commit` 中 mypy 排除了它。

## 11.3 单元测试

### 11.3.1 目录与覆盖点

| 测试文件 | 覆盖对象 |
| --- | --- |
| [tests/agent/test_trae_agent.py](file:///workspace/trae-agent/tests/agent/test_trae_agent.py) | `TraeAgent` 行为、任务完成判定、patch 逻辑 |
| `tests/test_cli.py` | CLI 参数与命令 |
| `tests/tools/test_bash_tool.py` | bash 会话、命令执行、超时/重启 |
| `tests/tools/test_edit_tool.py` | view / create / str_replace / insert |
| `tests/tools/test_json_edit_tool.py` | JSONPath view / set / add / remove |
| `tests/tools/test_mcp_tool.py` | MCP 工具适配 |
| `tests/utils/test_config.py` | 配置解析、优先级、legacy 兼容 |
| `tests/utils/test_google_client.py` | Gemini 客户端消息/工具转换 |
| `tests/utils/test_mcp_client.py` | MCP 连接状态机 |
| `tests/utils/test_ollama_client_utils.py` | Ollama 转换逻辑 |
| `tests/utils/test_openrouter_client_utils.py` | OpenRouter 转换逻辑 |

### 11.3.2 pytest 配置

[pyproject.toml#L54-L65](file:///workspace/trae-agent/pyproject.toml#L54-L65)：

- `testpaths = ["tests"]`；
- `asyncio_mode = "auto"`：async 测试无需显式 `@pytest.mark.asyncio`；
- markers：`slow`、`integration`、`unit`；
- `addopts = "-ra -q --strict-markers"`。

### 11.3.3 运行方式

```bash
# 全量（跳过外部服务相关测试）
make test
# 等价于：
SKIP_OLLAMA_TEST=true SKIP_OPENROUTER_TEST=true SKIP_GOOGLE_TEST=true uv run pytest

# 带详细输出
make uv-test
# 等价于：
SKIP_OLLAMA_TEST=true SKIP_OPENROUTER_TEST=true SKIP_GOOGLE_TEST=true \
  uv run pytest tests/ -v --tb=short --continue-on-collection-errors

# 指定文件 / 关键字
uv run pytest tests/tools/test_edit_tool.py -v
uv run pytest -k "config"
```

### 11.3.4 覆盖率

`[tool.coverage.run] source = ["trae_agent"]`，排除 `tests/*`；`[tool.coverage.report]` 忽略 `__repr__`、`if self.debug`、抽象方法等。可用：

```bash
uv run pytest --cov=trae_agent --cov-report=term-missing
```

## 11.4 代码规范与提交前检查

`.pre-commit-config.yaml` 启用：

| Hook | 作用 |
| --- | --- |
| `trailing-whitespace` / `end-of-file-fixer` | 清理空白 |
| `check-yaml` / `check-toml` | 配置文件语法 |
| `check-added-large-files` | 阻止大文件 |
| `detect-private-key` | 防止密钥泄露 |
| `ruff` (`--fix`) + `ruff-format` | Lint 与格式化 |
| `codespell` | 拼写检查（排除 `.jsonl`） |
| `mypy` | 类型检查（排除 `evaluation/patch_selection`） |

Ruff 规则在 [pyproject.toml#L86-L96](file:///workspace/trae-agent/pyproject.toml#L86-L96)：`B`、`SIM`、`C4`、`E4/E9/E7/F`、`I`，行宽 100。

常用命令：

```bash
make fix-format        # ruff format + ruff check --fix
make pre-commit        # 安装并运行所有 hook
make pre-commit-run    # 仅运行
```

## 11.5 CI 与质量门禁

仓库包含 GitHub Actions（`.github/workflows/`）用于：

- `pre-commit`：提交前规范检查；
- `unit-test`：单元测试。

本地提交前建议至少执行：

```bash
make fix-format && make test
```
