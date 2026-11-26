# 12 API 速查与开发指南

本页汇总关键类 / 函数签名、模块导入方式、扩展点与开发流程，便于二次开发时快速定位。

## 12.1 关键类速查

### 入口与编排

| 符号 | 位置 | 签名 / 说明 |
| --- | --- | --- |
| `main()` | [cli.py#L725-L731](file:///workspace/trae-agent/trae_agent/cli.py#L725-L731) | CLI 入口，调用 `cli()` |
| `run(...)` | [cli.py#L192-L411](file:///workspace/trae-agent/trae_agent/cli.py#L192-L411) | 单任务命令 |
| `interactive(...)` | [cli.py#L440-L513](file:///workspace/trae-agent/trae_agent/cli.py#L440-L513) | 交互命令 |
| `Agent` | [agent.py#L14](file:///workspace/trae-agent/trae_agent/agent/agent.py#L14) | `Agent(agent_type, config, trajectory_file=None, cli_console=None, docker_config=None, docker_keep=True)` |
| `Agent.run` | [agent.py#L59](file:///workspace/trae-agent/trae_agent/agent/agent.py#L59) | `async run(task, extra_args=None, tool_names=None) -> AgentExecution` |

### Agent 核心

| 符号 | 位置 | 说明 |
| --- | --- | --- |
| `BaseAgent` | [base_agent.py#L24](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L24) | 抽象基类 |
| `BaseAgent.execute_task` | [#L147](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L147) | 主循环，返回 `AgentExecution` |
| `BaseAgent._run_llm_step` | [#L209](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L209) | 单步 LLM 调用与完成判定 |
| `BaseAgent._tool_call_handler` | [#L314](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L314) | 工具调度 |
| `TraeAgent` | [trae_agent.py#L30](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L30) | 具体策略 |
| `TraeAgent.new_task` | [#L102](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L102) | 初始化任务与消息 |
| `TraeAgent.execute_task` | [#L155](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L155) | 执行 + trajectory finalize + patch 落盘 |
| `TraeAgent.get_git_diff` | [#L180](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L180) | 生成 git diff |
| `AgentStep` / `AgentExecution` | [agent_basics.py#L38-L84](file:///workspace/trae-agent/trae_agent/agent/agent_basics.py#L38-L84) | 执行数据结构 |

### 工具体系

| 符号 | 位置 | 说明 |
| --- | --- | --- |
| `Tool` | [tools/base.py#L74](file:///workspace/trae-agent/trae_agent/tools/base.py#L74) | 工具抽象 |
| `Tool.get_input_schema` | [#L127](file:///workspace/trae-agent/trae_agent/tools/base.py#L127) | 生成 Provider 兼容 JSON Schema |
| `ToolExecutor` | [#L182](file:///workspace/trae-agent/trae_agent/tools/base.py#L182) | `execute_tool_call` / `parallel_tool_call` / `sequential_tool_call` / `close_tools` |
| `tools_registry` | [tools/\_\_init\_\_.py#L27](file:///workspace/trae-agent/trae_agent/tools/__init__.py#L27) | 工具注册表 |
| `BashTool` | [bash_tool.py#L162](file:///workspace/trae-agent/trae_agent/tools/bash_tool.py#L162) | 持久 bash |
| `TextEditorTool` | [edit_tool.py#L27](file:///workspace/trae-agent/trae_agent/tools/edit_tool.py#L27) | 文件编辑 |
| `JSONEditTool` | [json_edit_tool.py#L17](file:///workspace/trae-agent/trae_agent/tools/json_edit_tool.py#L17) | JSONPath 编辑 |
| `SequentialThinkingTool` | [sequential_thinking_tool.py#L32](file:///workspace/trae-agent/trae_agent/tools/sequential_thinking_tool.py#L32) | 顺序思考 |
| `TaskDoneTool` | [task_done_tool.py#L9](file:///workspace/trae-agent/trae_agent/tools/task_done_tool.py#L9) | 完成信号 |
| `CKGTool` | [ckg_tool.py#L14](file:///workspace/trae-agent/trae_agent/tools/ckg_tool.py#L14) | 代码知识图谱查询 |
| `MCPTool` | [mcp_tool.py#L8](file:///workspace/trae-agent/trae_agent/tools/mcp_tool.py#L8) | MCP 工具适配 |
| `DockerToolExecutor` | [docker_tool_executor.py#L9](file:///workspace/trae-agent/trae_agent/tools/docker_tool_executor.py#L9) | Docker 路由执行器 |

### 模型接入

| 符号 | 位置 | 说明 |
| --- | --- | --- |
| `LLMClient` | [llm_client.py#L27](file:///workspace/trae-agent/trae_agent/utils/llm_clients/llm_client.py#L27) | Provider 工厂 |
| `LLMProvider` | [#L15](file:///workspace/trae-agent/trae_agent/utils/llm_clients/llm_client.py#L15) | Provider 枚举 |
| `BaseLLMClient` | [base_client.py#L13](file:///workspace/trae-agent/trae_agent/utils/llm_clients/base_client.py#L13) | 客户端抽象 |
| `OpenAICompatibleClient` | [openai_compatible_base.py#L65](file:///workspace/trae-agent/trae_agent/utils/llm_clients/openai_compatible_base.py#L65) | OpenAI 兼容基类 |
| `ProviderConfig` | [#L34](file:///workspace/trae-agent/trae_agent/utils/llm_clients/openai_compatible_base.py#L34) | Provider 差异抽象 |
| `LLMMessage` / `LLMResponse` / `LLMUsage` | [llm_basics.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/llm_basics.py) | 统一消息模型 |
| `retry_with` | [retry_utils.py#L13](file:///workspace/trae-agent/trae_agent/utils/llm_clients/retry_utils.py#L13) | 重试装饰器 |

### 配置、控制台与轨迹

| 符号 | 位置 | 说明 |
| --- | --- | --- |
| `Config.create` | [config.py#L205](file:///workspace/trae-agent/trae_agent/utils/config.py#L205) | 从 YAML / string / legacy JSON 构建 |
| `Config.resolve_config_values` | [#L302](file:///workspace/trae-agent/trae_agent/utils/config.py#L302) | CLI / ENV 覆盖 |
| `ModelConfig` | [#L29](file:///workspace/trae-agent/trae_agent/utils/config.py#L29) | 模型参数 |
| `MCPServerConfig` | [#L119](file:///workspace/trae-agent/trae_agent/utils/config.py#L119) | MCP Server 配置 |
| `CLIConsole` | [cli_console.py#L51](file:///workspace/trae-agent/trae_agent/utils/cli/cli_console.py#L51) | 控制台抽象 |
| `ConsoleFactory` | [console_factory.py#L13](file:///workspace/trae-agent/trae_agent/utils/cli/console_factory.py#L13) | 控制台工厂 |
| `TrajectoryRecorder` | [trajectory_recorder.py#L20](file:///workspace/trae-agent/trae_agent/utils/trajectory_recorder.py#L20) | 轨迹记录 |
| `LakeView` | [lake_view.py#L78](file:///workspace/trae-agent/trae_agent/utils/lake_view.py#L78) | 步骤摘要 |
| `DockerManager` | [docker_manager.py#L10](file:///workspace/trae-agent/trae_agent/agent/docker_manager.py#L10) | 容器管理 |
| `MCPClient` | [mcp_client.py#L26](file:///workspace/trae-agent/trae_agent/utils/mcp_client.py#L26) | MCP 连接 |

## 12.2 导入速查

```python
# 顶层常用导出（trae_agent/__init__.py）
from trae_agent import BaseAgent, TraeAgent, LLMClient, Tool, ToolExecutor

# 门面
from trae_agent.agent import Agent
from trae_agent.agent.agent_basics import AgentExecution, AgentState, AgentStep
from trae_agent.utils.config import Config, ModelConfig, ModelProvider

# 工具
from trae_agent.tools import tools_registry, Tool, ToolExecutor
from trae_agent.tools.base import ToolCall, ToolResult, ToolParameter, ToolExecResult

# 模型
from trae_agent.utils.llm_clients.llm_client import LLMClient, LLMProvider
from trae_agent.utils.llm_clients.llm_basics import LLMMessage, LLMResponse, LLMUsage

# 控制台 / 轨迹
from trae_agent.utils.cli import ConsoleFactory, ConsoleMode, ConsoleType
from trae_agent.utils.trajectory_recorder import TrajectoryRecorder
```

## 12.3 扩展点清单

### 12.3.1 新增工具

```python
from trae_agent.tools.base import Tool, ToolParameter, ToolCallArguments, ToolExecResult

class MyTool(Tool):
    def get_name(self) -> str: return "my_tool"
    def get_description(self) -> str: return "What it does"
    def get_parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="input", type="string", description="...", required=True)]
    async def execute(self, arguments: ToolCallArguments) -> ToolExecResult:
        return ToolExecResult(output=str(arguments["input"]))
```

1. 在 `tools/__init__.py` 的 `tools_registry` 注册；
2. 在配置 `agents.trae_agent.tools` 中加入 `"my_tool"`；
3. 如需 Docker 支持，在 `DockerToolExecutor` 增加路由并打包 CLI；
4. 补测试文件 `tests/tools/test_my_tool.py`。

### 12.3.2 新增模型 Provider

参考 [06 LLM 客户端 - 扩展](./06-llm-client.md#67-扩展一个新-provider)：

1. 实现 `ProviderConfig` 或 `BaseLLMClient`；
2. 更新 `LLMProvider` 与 `LLMClient.__init__` 的 `match`；
3. 配置 `model_providers.<name>.provider`；
4. 增加 `tests/utils/test_<name>_client_utils.py`。

### 12.3.3 新增 Agent 类型

参考 [04 Agent 核心 - 4.5](./04-agent-core.md#45-新增一种-agent-需要做什么)：

1. 继承 `BaseAgent` 实现 `new_task` / `cleanup_mcp_clients`；
2. 在 `AgentType` 与 `Agent.__init__` 注册；
3. 在 `Config.create()` 的 `match agent_name` 增加配置分支；
4. 更新 CLI `--agent-type` 选项。

### 12.3.4 新增控制台

1. 继承 `CLIConsole`，实现 7 个抽象方法；
2. 在 `ConsoleType` 与 `ConsoleFactory.create_console` 注册；
3. 更新 CLI `--console-type` 的 `click.Choice`。

### 12.3.5 定制 Prompt / 完成判定

- 修改 [prompt/agent_prompt.py](file:///workspace/trae-agent/trae_agent/prompt/agent_prompt.py)；
- 覆写 `llm_indicates_task_completed()` / `_is_task_completed()` / `task_incomplete_message()`；
- 确保 Prompt 中提到的工具名与注册表一致。

## 12.4 依赖清单

### 运行时依赖（节选）

| 包 | 用途 |
| --- | --- |
| `openai` / `anthropic` / `google-genai` / `ollama` | 各 Provider SDK |
| `click` / `rich` / `textual` | CLI 与 TUI |
| `pydantic` | 数据模型（部分场景） |
| `jsonpath-ng` | JSONPath |
| `pyyaml` / `python-dotenv` | 配置与环境变量 |
| `mcp` | MCP 协议 |
| `tree-sitter` / `tree-sitter-languages` | CKG 代码解析 |
| `docker` / `pexpect` | Docker 模式 |
| `asyncclick` / `socksio` | 异步 CLI / 代理支持 |
| `pyinstaller` | 打包容器内工具 |

### 可选依赖

- `test`：`pytest`、`pytest-asyncio`、`pytest-mock`、`pytest-cov`、`pre-commit`
- `evaluation`：`datasets`、`docker`、`pexpect`、`unidiff`

完整版本约束见 [pyproject.toml#L7-L42](file:///workspace/trae-agent/pyproject.toml#L7-L42)。

## 12.5 开发流程

```bash
# 1. 安装
make install-dev          # uv venv + uv sync --all-extras

# 2. 开发与自测
make fix-format           # ruff format + ruff check --fix
make pre-commit-run       # 全部 hook
make test                 # 单元测试（跳过外部服务）
uv run pytest tests/tools/test_bash_tool.py -v

# 3. 本地运行
uv run trae-cli show-config
uv run trae-cli run "your task" --config-file trae_config.yaml

# 4. 清理
make clean
```

### 构建 / 打包

- 包构建：`hatchling`，`[tool.hatch.build.targets.wheel] packages = ["trae_agent"]`；
- 容器工具：`build_with_pyinstaller()` 生成 `trae_agent/dist/edit_tool` 与 `json_edit_tool`；
- CLI 入口：`trae-cli = "trae_agent.cli:main"`。

## 12.6 已知限制与 Roadmap

### 当前限制

- `server/` 只有设计文档，无 HTTP 实现；
- MCP 仅 stdio；
- `DockerToolExecutor.parallel_tool_call` 串行执行；
- `TrajectoryRecorder.save_trajectory()` 每次全量写文件，超大轨迹有 IO 开销；
- CKG 不做增量重建，子目录会重复建库，JS/TS 部分语法未覆盖；
- `Config` 对未知 agent 名直接报错，新增 Agent 必须改源码。

### Roadmap（摘自 [docs/roadmap.md](file:///workspace/trae-agent/docs/roadmap.md)）

1. **SDK**：无头编程接口、流式轨迹；
2. **Sandbox**：隔离执行、并行任务；
3. **Trajectory Analysis**：Wandb Weave / MLFlow 集成与高级分析；
4. **Tools & MCP**：结构化文件（Notebook、配置）支持、MCP 标准化；
5. **Advanced Agentic Flows**：多 Agent 协作、专门化 Agent、复杂工作流。

## 12.7 调试建议

| 场景 | 建议 |
| --- | --- |
| 模型不调用工具 | 检查 Provider 是否支持 tool calling；查看 `tools_available` 与 schema |
| 工具未被找到 | 检查 `tools_registry` 与配置中的名字；`ToolExecutor` 会归一化大小写与下划线 |
| 任务不结束 | 检查 Prompt 是否引导 `task_done`；`must_patch` 是否要求非空 patch |
| 轨迹缺内容 | 确认 `TrajectoryRecorder` 已注入（`Agent` 构造时自动完成） |
| Docker 工具找不到 | 确认 `trae_agent/dist` 已生成；`docker cp` 是否成功 |
| MCP 工具未出现 | 检查 `allow_mcp_servers` 是否包含该 Server；传输是否为 stdio |
| 配置不生效 | 用 `trae-cli show-config` 对照 CLI / ENV / YAML 优先级 |
