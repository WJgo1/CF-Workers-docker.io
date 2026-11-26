# 02 整体架构

## 2.1 分层视图

Trae Agent 采用清晰的五层结构，自上而下依赖，禁止反向依赖（除少量 `TYPE_CHECKING` / 延迟导入外）：

```text
┌────────────────────────────────────────────────────────────┐
│  表现层 / 入口层                                             │
│  cli.py  ·  utils/cli/ (CLIConsole, Simple, Rich TUI)       │
└───────────────────────────┬────────────────────────────────┘
                            │ 创建 / 驱动
┌───────────────────────────▼────────────────────────────────┐
│  门面与编排层                                                 │
│  agent/agent.py (Agent)  ·  utils/trajectory_recorder.py     │
└───────────────────────────┬────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────┐
│  Agent 核心层                                                │
│  agent/base_agent.py (BaseAgent 执行循环)                     │
│  agent/trae_agent.py (TraeAgent 策略)                        │
│  agent/agent_basics.py (状态与数据结构)                        │
└───────┬───────────────────────────────────┬────────────────┘
        │ 调用模型                           │ 调用工具
┌───────▼────────────────────┐   ┌──────────▼──────────────────┐
│  模型接入层                 │   │  工具体系                     │
│  utils/llm_clients/        │   │  tools/                      │
│  LLMClient + Providers     │   │  Tool / ToolExecutor / 各工具 │
└───────┬────────────────────┘   └──────────┬──────────────────┘
        │                                    │
┌───────▼────────────────────────────────────▼────────────────┐
│  基础设施层                                                  │
│  utils/config.py · utils/mcp_client.py · agent/docker_manager│
│  prompt/ · utils/constants.py · tools/ckg/                   │
└──────────────────────────────────────────────────────────────┘
```

## 2.2 核心组件职责

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `Agent` | [agent.py](file:///workspace/trae-agent/trae_agent/agent/agent.py#L14-L99) | 对外门面：按 `AgentType` 选择 Agent 实现，装配 trajectory / console，暴露 `run()` |
| `BaseAgent` | [base_agent.py](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L24-L351) | 实现通用执行循环、工具调度、LLM 调用、步状态推进、资源清理 |
| `TraeAgent` | [trae_agent.py](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L30-L258) | 软件工程策略：初始消息、System Prompt、完成判定、git diff / patch、MCP 工具发现 |
| `AgentStep` / `AgentExecution` | [agent_basics.py](file:///workspace/trae-agent/trae_agent/agent/agent_basics.py#L19-L100) | 执行过程的数据载体与状态枚举 |
| `LLMClient` | [llm_client.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/llm_client.py#L27-L85) | Provider 工厂 + 统一 `chat()` 接口 |
| `BaseLLMClient` 及子类 | `utils/llm_clients/*.py` | 各 Provider 的请求构造、消息格式转换、工具 schema 转换、响应解析 |
| `Tool` / `ToolExecutor` | [tools/base.py](file:///workspace/trae-agent/trae_agent/tools/base.py#L74-L244) | 工具统一抽象、JSON Schema 生成、并发/顺序执行与错误封装 |
| `tools_registry` | [tools/__init__.py](file:///workspace/trae-agent/trae_agent/tools/__init__.py#L27-L34) | 工具名 → 工具类 的注册表，是扩展工具的唯一入口 |
| `Config` | [config.py](file:///workspace/trae-agent/trae_agent/utils/config.py#L193-L391) | YAML 解析、模型/Provider/MCP/Agent 配置装配、CLI/ENV 覆盖 |
| `CLIConsole` | [cli_console.py](file:///workspace/trae-agent/trae_agent/utils/cli/cli_console.py#L51-L171) | 展示抽象：步骤状态、工具调用、Lakeview 摘要 |
| `TrajectoryRecorder` | [trajectory_recorder.py](file:///workspace/trae-agent/trae_agent/utils/trajectory_recorder.py#L20-L266) | 持久化轨迹 JSON |
| `DockerManager` / `DockerToolExecutor` | [docker_manager.py](file:///workspace/trae-agent/trae_agent/agent/docker_manager.py#L10-L242)、[docker_tool_executor.py](file:///workspace/trae-agent/trae_agent/tools/docker_tool_executor.py#L9-L165) | 容器生命周期、路径映射、把工具调用代理进容器 |
| `MCPClient` / `MCPTool` | [mcp_client.py](file:///workspace/trae-agent/trae_agent/utils/mcp_client.py#L26-L104)、[mcp_tool.py](file:///workspace/trae-agent/trae_agent/tools/mcp_tool.py#L8-L58) | stdio MCP 连接、工具发现与调用适配 |
| `LakeView` | [lake_view.py](file:///workspace/trae-agent/trae_agent/utils/lake_view.py#L78-L209) | 调小模型生成步骤摘要与标签 |

## 2.3 执行主循环

执行逻辑集中在 `BaseAgent.execute_task()`（[base_agent.py#L147-L200](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L147-L200)）：

```python
execution = AgentExecution(task=self._task, steps=[])
messages = self._initial_messages
step_number = 1
while step_number <= self._max_steps:
    step = AgentStep(step_number=step_number, state=AgentStepState.THINKING)
    try:
        messages = await self._run_llm_step(step, messages, execution)
        await self._finalize_step(step, messages, execution)
        if execution.agent_state == AgentState.COMPLETED:
            break
        step_number += 1
    except Exception as error:
        execution.agent_state = AgentState.ERROR
        ...
        break
```

`_run_llm_step()`（[#L209-L236](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L209-L236)）单步逻辑：

1. 置状态 `THINKING` 并刷新控制台；
2. `LLMClient.chat(messages, model_config, tools)` 获取 `LLMResponse`；
3. 累加 token 使用量；
4. 若 `llm_indicates_task_completed()` 为真：
   - `_is_task_completed()` 通过 → 置 `COMPLETED`、`success=True`、写入 `final_result`；
   - 不通过 → 返回一条提示消息（如 patch 为空），继续循环；
5. 否则提取 `tool_calls`，交给 `_tool_call_handler()`。

`_tool_call_handler()`（[#L314-L351](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L314-L351)）：

- 没有工具调用 → 返回「任务未完成」提示消息；
- 有工具调用 → 按 `parallel_tool_calls` 选择 `parallel_tool_call()` / `sequential_tool_call()`；
- 每个 `ToolResult` 包装成 `LLMMessage(role="user", tool_result=...)`；
- 可选 `reflect_on_result()` 生成反思消息（`TraeAgent` 默认返回 `None`，即不做额外反思）。

### 关键设计：对话历史由 LLM Client 持有

注意 `_run_llm_step()` 的返回值**不是**完整历史，而是「本步新增消息」：

- 首轮返回 `[system, user]`；
- 工具轮返回仅包含工具结果的增量消息；
- 各 Provider 客户端内部维护 `message_history`，且调用 `chat()` 时默认 `reuse_history=True`，会把自己维护的历史与本次增量拼接后发给模型。

因此 `messages` 变量更像「本轮 delta」，真正的长上下文在 `BaseLLMClient` 子类中。这是阅读源码时最容易误解的一点。

## 2.4 状态机

定义于 [agent_basics.py](file:///workspace/trae-agent/trae_agent/agent/agent_basics.py#L19-L36)：

```text
AgentState:       IDLE ──► RUNNING ──► COMPLETED
                              └──────► ERROR

AgentStepState:   THINKING ──► CALLING_TOOL ──► REFLECTING ──► COMPLETED
                       │                            │
                       └──────────► ERROR ◄─────────┘
```

- **Agent 级**：`AgentExecution.agent_state`，由 `execute_task()` 维护。
- **Step 级**：`AgentStep.state`，由 `_run_llm_step()` / `_tool_call_handler()` / `_finalize_step()` 推进。
- 无论成功与否，`finally` 中都会释放工具资源（关闭 bash 进程）并清理 MCP 客户端。

## 2.5 一次完整调用的时序

```text
CLI.run
  ├─ Config.create(...).resolve_config_values(...)
  ├─ ConsoleFactory.create_console(...)
  └─ Agent(...).run(task, task_args)
       ├─ TraeAgent.new_task(task, extra_args)
       │    ├─ 初始化工具（若尚未初始化）
       │    ├─ 构造 initial_messages: [system, user(project_path + issue)]
       │    └─ trajectory.start_recording(...)
       ├─ TraeAgent.initialise_mcp()（若 allow_mcp_servers 非空）
       ├─ console.print_task_details(...)
       ├─ asyncio.create_task(console.start())      # 与执行并行
       └─ TraeAgent.execute_task()
            ├─ BaseAgent.execute_task()             # 主循环
            │    ├─ _run_llm_step → LLMClient.chat → ProviderClient.chat
            │    ├─ _tool_call_handler → ToolExecutor → Tool.execute
            │    └─ _finalize_step → recorder.record_agent_step
            ├─ trajectory.finalize_recording(...)
            └─ 若 patch_path: 写 git diff
```

## 2.6 模块依赖关系

### 2.6.1 依赖方向（简化）

```text
cli.py
 ├── agent.agent.Agent
 │    ├── agent.trae_agent.TraeAgent
 │    │    ├── agent.base_agent.BaseAgent
 │    │    │    ├── utils.llm_clients.llm_client.LLMClient
 │    │    │    ├── tools (tools_registry / ToolExecutor / DockerToolExecutor)
 │    │    │    ├── utils.cli.CLIConsole
 │    │    │    ├── utils.trajectory_recorder.TrajectoryRecorder
 │    │    │    └── agent.docker_manager.DockerManager
 │    │    ├── prompt.agent_prompt
 │    │    ├── utils.mcp_client.MCPClient
 │    │    └── tools.mcp_tool.MCPTool
 │    ├── utils.config.Config
 │    └── utils.trajectory_recorder
 └── utils.cli.ConsoleFactory
```

### 2.6.2 依赖矩阵（模块 → 主要被依赖方）

| 模块 | 依赖 | 被谁依赖 |
| --- | --- | --- |
| `utils/config.py` | `yaml`、`legacy_config` | `cli`、`agent`、`llm_clients` |
| `tools/base.py` | 标准库、`asyncio` | 所有工具、`llm_basics`（类型）、`base_agent` |
| `tools/__init__.py` | 所有工具实现 | `base_agent`、`trae_agent`、`cli` |
| `utils/llm_clients/*` | 各模型 SDK、`tools.base`（schema） | `base_agent`、`lake_view` |
| `utils/cli/*` | `rich`、`textual`、`lake_view` | `cli`、`base_agent`、`agent` |
| `agent/base_agent.py` | `llm_clients`、`tools`、`cli`、`config`、`trajectory_recorder` | `trae_agent` |
| `agent/trae_agent.py` | `base_agent`、`prompt`、`mcp_client` | `agent/agent.py` |
| `agent/docker_manager.py` | `docker`、`pexpect` | `base_agent`、`docker_tool_executor` |
| `utils/lake_view.py` | `llm_clients`、`agent_basics` | `utils/cli/cli_console` |

### 2.6.3 循环依赖规避

- Provider 客户端采用**延迟导入**（`LLMClient.__init__` 内 `from .openai_client import OpenAIClient`），避免「工厂 ↔ 具体客户端」相互导入。
- `tools/base.py` 不反向导入 `llm_clients`；是 `llm_basics` 依赖 `tools.base` 的 `ToolCall/ToolResult`，方向单一。
- `TraeAgent` 在 `Agent.run()` 内部才被导入，避免 `agent/__init__.py` 提前触发重依赖。

## 2.7 设计取舍

1. **薄门面 + 厚基类**：`Agent` 只做装配；`BaseAgent` 承担循环；`TraeAgent` 只覆写策略方法，便于新增 Agent 类型。
2. **工具即插件**：工具通过 `get_name/description/parameters/execute` 四件套自描述，`Tool.get_input_schema()` 统一生成 JSON Schema，并按 Provider 做兼容（OpenAI strict 模式把可选参数改为 nullable）。
3. **能力按需装配**：MCP 工具在运行时发现后才追加到 `_tools`；Docker 模式用 `DockerToolExecutor` 装饰原执行器，对上层透明。
4. **可观测优先**：控制台、轨迹、Lakeview 三条可观测链路互不耦合，可独立开启/关闭。

## 2.8 与 `server/` 的关系

[server/Readme.md](file:///workspace/trae-agent/server/Readme.md) 描述了未来 HTTP 服务的目标（无状态、并发、JSON 响应、可重放轨迹），但当前目录**没有实现代码**。因此现有所有能力均通过 CLI 进程内调用，不涉及网络服务层。
