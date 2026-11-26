# 03 安装与运行

## 3.1 环境要求

- **Python 3.12+**（见 [.python-version](file:///workspace/trae-agent/.python-version) 与 [pyproject.toml](file:///workspace/trae-agent/pyproject.toml#L6)）。
- **uv**：官方推荐的包与虚拟环境管理工具（<https://docs.astral.sh/uv/>）。
- 至少一个模型 Provider 的 API Key（OpenAI / Anthropic / Google / OpenRouter / Doubao 等）。
- 可选：**Docker**（仅 Docker 运行模式需要，且需 daemon 可用）。
- 可选：**Git**（用于 `git diff` 生成 patch、CKG 版本判定等）。

## 3.2 安装

```bash
git clone https://github.com/bytedance/trae-agent.git
cd trae-agent
uv sync --all-extras          # 含 test / evaluation 可选依赖
source .venv/bin/activate
```

或使用 Makefile：

```bash
make install-dev              # = uv venv && uv sync --all-extras
```

安装后获得入口命令 `trae-cli`（由 [pyproject.toml#L44-L45](file:///workspace/trae-agent/pyproject.toml#L44-L45) 定义）：

```toml
[project.scripts]
trae-cli = "trae_agent.cli:main"
```

## 3.3 配置

### 3.3.1 YAML（推荐）

```bash
cp trae_config.yaml.example trae_config.yaml
```

最小配置结构（完整示例见 [trae_config.yaml.example](file:///workspace/trae-agent/trae_config.yaml.example)）：

```yaml
agents:
  trae_agent:
    enable_lakeview: true          # 是否启用步骤摘要
    model: trae_agent_model        # 引用 models 中的键
    max_steps: 200                 # 最大执行步数
    tools:                         # 启用的工具名（须在 tools_registry 中）
      - bash
      - str_replace_based_edit_tool
      - sequentialthinking
      - task_done

lakeview:                          # enable_lakeview 为 true 时必填
  model: lakeview_model

model_providers:
  anthropic:
    api_key: your_anthropic_api_key
    provider: anthropic
    # base_url: https://...        # 可选，自定义网关
  openai:
    api_key: your_openai_api_key
    provider: openai

models:
  trae_agent_model:
    model_provider: anthropic      # 必须存在于 model_providers
    model: claude-sonnet-4-20250514
    max_tokens: 4096
    temperature: 0.5
    top_p: 1
    top_k: 0
    max_retries: 10
    parallel_tool_calls: true
  lakeview_model:
    model_provider: anthropic
    model: claude-3.5-sonnet
    max_tokens: 4096
    temperature: 0.5
    top_p: 1
    top_k: 0
    max_retries: 10
    parallel_tool_calls: true
```

> 注意：YAML 只允许空格缩进，**不允许 Tab**。`trae_config.yaml` 已被 `.gitignore` 忽略，避免密钥入库。

### 3.3.2 环境变量（替代方案）

```bash
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="..."          # 可选
export ANTHROPIC_API_KEY="..."
export ANTHROPIC_BASE_URL="..."       # 可选
export GOOGLE_API_KEY="..."
export OPENROUTER_API_KEY="..."
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
export DOUBAO_API_KEY="..."
export DOUBAO_BASE_URL="https://ark.cn-beijing.volces.com/api/v3/"
```

CLI 启动时通过 `load_dotenv()` 读取 `.env`（见 [cli.py#L26](file:///workspace/trae-agent/trae_agent/cli.py#L26)）。

### 3.3.3 配置优先级

`resolve_config_value()`（[config.py#L394-L410](file:///workspace/trae-agent/trae_agent/utils/config.py#L394-L410)）的实现是：

```text
CLI 参数  >  环境变量  >  配置文件  >  默认值
```

> 仓库 README 写作「CLI > 配置文件 > 环境变量 > 默认」，与代码实现略有出入；本 Wiki 以源码为准。

### 3.3.4 旧版 JSON 兼容

`Config.create()` 在 `config_file.endswith(".json")` 时走 `create_from_legacy_config()`，解析旧结构 `model_providers + default_provider` 并映射为新的 `TraeAgentConfig`。详见 [07 配置系统](./07-configuration.md) 与 [docs/legacy_config.md](file:///workspace/trae-agent/docs/legacy_config.md)。

## 3.4 CLI 命令

CLI 定义于 [cli.py](file:///workspace/trae-agent/trae_agent/cli.py)，包含四个子命令：

```bash
trae-cli run "<task>"          # 执行单次任务
trae-cli interactive           # 交互式会话
trae-cli show-config           # 查看当前生效配置
trae-cli tools                 # 列出已注册工具及描述
trae-cli --version             # 版本号
```

### 3.4.1 `run`

关键参数（[cli.py#L126-L213](file:///workspace/trae-agent/trae_agent/cli.py#L126-L213)）：

| 参数 | 说明 |
| --- | --- |
| `<task>` 或 `--file/-f` | 任务文本；二者只能选其一 |
| `--provider/-p` | 覆盖 Provider，如 `openai`、`anthropic` |
| `--model/-m` | 覆盖模型名 |
| `--model-base-url` | 覆盖 API Base URL |
| `--api-key/-k` | 覆盖 API Key |
| `--max-steps` | 最大步数（覆盖配置） |
| `--working-dir/-w` | 项目根目录（不存在会自动创建） |
| `--must-patch/-mp` | 仅在产生非空非测试 patch 时判定完成 |
| `--config-file` | 配置文件，默认 `trae_config.yaml`，也可用 `TRAE_CONFIG_FILE` |
| `--trajectory-file/-t` | 轨迹输出路径（默认 `trajectories/trajectory_<ts>.json`） |
| `--patch-path/-pp` | 结束后把 `git diff` 写入该文件 |
| `--console-type/-ct` | `simple`（默认）或 `rich` |
| `--agent-type/-at` | 目前仅 `trae_agent` |

Docker 相关参数：

| 参数 | 说明 |
| --- | --- |
| `--docker-image` | 从镜像启动新容器 |
| `--docker-container-id` | 附着已有容器（不可与 `--working-dir` 同用） |
| `--dockerfile-path` | 从绝对路径 Dockerfile 构建镜像 |
| `--docker-image-file` | 从 tar 归档加载镜像 |
| `--docker-keep` | 任务结束后是否保留容器，默认 `true` |

> `--docker-image` / `--docker-container-id` / `--dockerfile-path` / `--docker-image-file` **四者互斥**；CLI 会校验 Docker CLI 与 daemon，并在 `trae_agent/dist` 不存在时自动调用 `build_with_pyinstaller()` 打包工具（见 [cli.py#L262-L275](file:///workspace/trae-agent/trae_agent/cli.py#L262-L275)）。

示例：

```bash
# 基本任务
trae-cli run "Create a hello world Python script"

# 指定 provider / model
trae-cli run "Fix the bug in main.py" --provider openai --model gpt-4o
trae-cli run "Add unit tests" --provider anthropic --model claude-sonnet-4-20250514
trae-cli run "Optimize this algorithm" --provider google --model gemini-2.5-flash
trae-cli run "Review this code" --provider openrouter --model "anthropic/claude-3-5-sonnet"

# 指定工作目录与轨迹
trae-cli run "Add tests for utils module" --working-dir /path/to/project \
  --trajectory-file debug_session.json

# 必须产出 patch，并落盘
trae-cli run "Update API endpoints" --must-patch --patch-path fix.patch
```

### 3.4.2 `interactive`

参数与 `run` 类似（[cli.py#L414-L513](file:///workspace/trae-agent/trae_agent/cli.py#L414-L513)），但不接收初始 task，进入会话循环。Simple 控制台支持以下命令：

- 任意文本：作为任务执行；
- `status`：显示 Provider / Model / 工具数量 / 配置路径 / 当前目录；
- `help`：帮助面板；
- `clear`：清屏；
- `exit` / `quit`：退出。

Rich 控制台基于 Textual，会启动完整 TUI（含 token 展示、步骤日志、输入框），由 `RichCLIConsole` 自行接管交互。

### 3.4.3 `show-config`

打印 General Settings 与 Provider 配置（API Key 只显示首尾各 4 位），用于快速确认运行时生效配置。

### 3.4.4 `tools`

遍历 `tools_registry` 实例化工具并打印 `name + description`；若某工具初始化失败会显示错误信息。

## 3.5 运行流程图（CLI 视角）

```text
cli.run
  ├─ 校验 docker 参数互斥性
  ├─ 解析 --file / <task>
  ├─ Config.create(config_file).resolve_config_values(...)
  ├─ 创建 Console（simple / rich）
  ├─ 解析 working_dir 为绝对路径
  ├─ Agent(agent_type, config, trajectory_file, console, docker_config, docker_keep)
  ├─ 非 Docker 模式：os.chdir(working_dir)
  └─ asyncio.run(agent.run(task, task_args))
       task_args = { project_path, issue, must_patch, patch_path }
```

## 3.6 常见问题

| 现象 | 排查方向 |
| --- | --- |
| `ModuleNotFoundError` / 导入失败 | 在仓库根目录执行，或 `PYTHONPATH=. trae-cli ...` |
| `trae-cli: command not found` | 使用 `uv run trae-cli ...`，或确认虚拟环境已激活、已 `uv sync` |
| API Key 无效 | `echo $OPENAI_API_KEY`、`trae-cli show-config` 检查生效值 |
| 配置文件找不到 | 默认寻找 `trae_config.yaml`；YAML 不存在时会回退同名 `.json`（[cli.py#L31-L50](file:///workspace/trae-agent/trae_agent/cli.py#L31-L50)） |
| Docker 报错 | 确认 daemon 运行、有权限；`--docker-container-id` 与 `--working-dir` 不可同用 |
| 任务一直不结束 | 检查 `max_steps`；`must_patch` 为真时要求非空 patch，否则会反复提示 |
| 权限错误 | `chmod +x` 目标目录/脚本，确认工作目录可写 |

更多运行方式（测试、评测、Docker 细节）见 [11 评测与测试](./11-evaluation-and-tests.md) 与 [10 Docker 与 MCP](./10-docker-and-mcp.md)。
