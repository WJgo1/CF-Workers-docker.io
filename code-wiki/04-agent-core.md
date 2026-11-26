# 04 Agent 核心

Agent 相关代码位于 `trae_agent/agent/`，由三个层次组成：

| 类 | 文件 | 角色 |
| --- | --- | --- |
| `Agent` | [agent.py](file:///workspace/trae-agent/trae_agent/agent/agent.py#L14) | 门面 / 装配器 |
| `BaseAgent` | [base_agent.py](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L24) | 执行循环与通用能力 |
| `TraeAgent` | [trae_agent.py](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L30) | 软件工程任务策略 |

## 4.1 `Agent`：对外门面

`Agent` 是 CLI 唯一直接构造的对象，负责「按类型选择实现 + 注入依赖」。

```python
class AgentType(Enum):
    TraeAgent = "trae_agent"
```

构造流程（[agent.py#L15-L57](file:///workspace/trae-agent/trae_agent/agent/agent.py#L15-L57)）：

1. 若传入字符串 `agent_type`，转换为 `AgentType`；
2. 设置轨迹：传入路径则用 `TrajectoryRecorder(path)`，否则自动生成；
3. `match agent_type`：
   - `TraeAgent`：校验 `config.trae_agent` 非空 → 构造 `TraeAgent(config, docker_config, docker_keep)`；
   - 设置 `agent_config`、`agent`、`cli_console`；
4. 根据 `enable_lakeview` 给 console 注入 / 清除 Lakeview 配置；
5. `agent.set_trajectory_recorder(self.trajectory_recorder)`（同时下发给 LLM Client）。

`run()`（[#L59-L99](file:///workspace/trae-agent/trae_agent/agent/agent.py#L59-L99)）：

```python
self.agent.new_task(task, extra_args, tool_names)
if self.agent.allow_mcp_servers:
    await self.agent.initialise_mcp()
if self.agent.cli_console:
    ... print_task_details(...)
cli_console_task = asyncio.create_task(self.agent.cli_console.start()) if console else None
try:
    execution = await self.agent.execute_task()
finally:
    await self.agent.cleanup_mcp_clients()
if cli_console_task:
    await cli_console_task
return execution
```

要点：

- **MCP 初始化在 `new_task` 之后**，因此 MCP 工具会被追加到已按配置构建的工具列表末尾；
- Console 与执行**并行**运行（Rich TUI 需要持续刷新）；
- `finally` 保证 MCP 客户端即使执行失败也会清理（`BaseAgent.execute_task` 内还有一次兜底清理）。

## 4.2 `AgentStep` / `AgentExecution`

定义于 [agent_basics.py](file:///workspace/trae-agent/trae_agent/agent/agent_basics.py)。

### `AgentStep`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `step_number` | `int` | 步序号（从 1 开始） |
| `state` | `AgentStepState` | 当前步状态 |
| `thought` | `str \| None` | 思考内容（预留） |
| `tool_calls` | `list[ToolCall] \| None` | 本步调用的工具 |
| `tool_results` | `list[ToolResult] \| None` | 工具执行结果 |
| `llm_response` | `LLMResponse \| None` | 原始 LLM 响应 |
| `reflection` | `str \| None` | 反思文本 |
| `error` | `str \| None` | 错误信息 |
| `extra` | `dict \| None` | 扩展字段 |
| `llm_usage` | `LLMUsage \| None` | 本步 token 用量 |

### `AgentExecution`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `task` | `str` | 原始任务 |
| `steps` | `list[AgentStep]` | 所有步 |
| `final_result` | `str \| None` | 最终文本 |
| `success` | `bool` | 是否成功 |
| `total_tokens` | `LLMUsage \| None` | 累计 token |
| `execution_time` | `float` | 总耗时（秒） |
| `agent_state` | `AgentState` | 最终状态 |

### 状态枚举

- `AgentStepState`：`THINKING` / `CALLING_TOOL` / `REFLECTING` / `COMPLETED` / `ERROR`
- `AgentState`：`IDLE` / `RUNNING` / `COMPLETED` / `ERROR`

### `AgentError`

统一的 Agent 异常类型，携带 `message`，用于参数缺失、配置错误等场景。

## 4.3 `BaseAgent`：执行引擎

### 4.3.1 构造与依赖注入

[base_agent.py#L29-L81](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L29-L81)：

```python
self._llm_client = LLMClient(agent_config.model)
self._model_config = agent_config.model
self._max_steps = agent_config.max_steps
self._tools = [tools_registry[name](model_provider=provider)
               for name in agent_config.tools]
original_tool_executor = ToolExecutor(self._tools)

if docker_config:
    self.docker_manager = DockerManager(...)
    self._tool_caller = DockerToolExecutor(
        original_executor=original_tool_executor,
        docker_manager=self.docker_manager,
        docker_tools=["bash", "str_replace_based_edit_tool", "json_edit_tool"],
        ...
    )
else:
    self._tool_caller = original_tool_executor
```

要点：

- **工具根据配置实例化**，因此 `agent_config.tools` 中的名字必须存在于 `tools_registry`；
- `model_provider` 会传入每个工具，用于生成 Provider 兼容的 JSON Schema（尤其 OpenAI strict 模式）；
- Docker 模式**不替换工具对象**，而是用 `DockerToolExecutor` 做调用路由：三类工具进容器，其余（如 `sequentialthinking`、`task_done`）仍在宿主执行；
- 构造时调用 `clear_older_ckg()` 清理过期代码知识图谱缓存。

### 4.3.2 关键方法一览

| 方法 | 位置 | 作用 |
| --- | --- | --- |
| `execute_task()` | [#L147-L200](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L147-L200) | 主循环：执行 → 记录 → 清理 → 返回 `AgentExecution` |
| `_run_llm_step()` | [#L209-L236](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L209-L236) | 单步：LLM 调用、完成判定、工具分发 |
| `_finalize_step()` | [#L238-L244](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L238-L244) | 置 COMPLETED、记录轨迹、更新控制台、加入 `execution.steps` |
| `_tool_call_handler()` | [#L314-L351](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L314-L351) | 并行/顺序执行工具，包装结果与反思 |
| `reflect_on_result()` | [#L246-L257](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L246-L257) | 默认对失败的 ToolResult 生成反思（子类可覆写） |
| `llm_indicates_task_completed()` | [#L259-L270](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L259-L270) | 默认基于关键词判断完成（子类覆写） |
| `_is_task_completed()` | [#L272-L274](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L272-L274) | 默认返回 True，供子类加校验 |
| `task_incomplete_message()` | [#L276-L278](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L276-L278) | 未完成时回给模型的提示 |
| `_close_tools()` | [#L202-L207](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L202-L207) | 释放工具资源（主要是 bash 进程） |
| `_update_llm_usage()` | [#L291-L299](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L291-L299) | 累加 token 用量 |
| `_record_handler()` | [#L301-L312](file:///workspace/trae-agent/trae_agent/agent/base_agent.py#L301-L312) | 把 step 写入轨迹 |

### 4.3.3 属性（只读接口）

`llm_client`、`trajectory_recorder`、`cli_console`、`tools`、`task`、`initial_messages`、`model_config`、`max_steps`。`task` 支持 setter，其余通过 `set_xxx()` 注入。

### 4.3.4 异常与资源管理

- 单步异常：标记 `agent_state=ERROR`、`step.state=ERROR`、记录 `step.error`，执行 `_finalize_step` 后 `break`；
- 超过 `max_steps` 仍未完成：`final_result = "Task execution exceeded maximum steps without completion."`，状态置 `ERROR`；
- 外层异常：`final_result = f"Agent execution failed: {e}"`；
- `finally`：按 `docker_keep` 决定是否停止容器；`_close_tools()` 释放资源；`cleanup_mcp_clients()` 兜底清理；
- 最后计算 `execution_time` 并刷新控制台。

## 4.4 `TraeAgent`：软件工程策略

### 4.4.1 构造与新任务

[trae_agent.py#L30-L170](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L30-L170)

```python
TraeAgentToolNames = [
    "str_replace_based_edit_tool",
    "sequentialthinking",
    "json_edit_tool",
    "task_done",
    "bash",
]
```

`new_task(task, extra_args, tool_names)` 行为：

1. 保存 `task`；
2. **仅当** `tool_names is None` 且当前 `_tools` 为空时，才用 `TraeAgentToolNames` 动态构建工具（正常路径下工具已在 `BaseAgent.__init__` 中根据配置构建）；
3. 构造初始消息：
   - `system`：`TRAE_AGENT_SYSTEM_PROMPT`；
   - `user`：`[Project root path]...`，若 `extra_args` 含 `issue` 则追加 `[Problem statement]...`；
   - Docker 模式下项目根路径固定写成 `/workspace`；
4. 从 `extra_args` 可选设置 `base_commit`、`must_patch`、`patch_path`；
5. 若存在轨迹记录器，调用 `start_recording(task, provider, model, max_steps)`。

参数约束：

- `extra_args` 必填；
- 必须包含 `project_path`，否则抛 `AgentError`。

### 4.4.2 完成判定

`llm_indicates_task_completed()` 覆写为：**响应中存在名为 `task_done` 的 tool_call**（[#L228-L233](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L228-L233)）。

`_is_task_completed()` 增加 patch 校验（[#L235-L244](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L235-L244)）：

```python
if self.must_patch == "true":
    model_patch = self.get_git_diff()
    patch = self.remove_patches_to_tests(model_patch)
    if not patch.strip():
        return False
return True
```

即 `--must-patch` 时，必须产生**剔除测试文件后的非空 diff**才算完成；否则返回 `task_incomplete_message()`：

> `ERROR! Your Patch is empty. Please provide a patch that fixes the problem.`

### 4.4.3 Patch 生成

`get_git_diff()`（[#L180-L197](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L180-L197)）：

- 切换到 `project_path`，执行 `git --no-pager diff`；
- 若设置了 `base_commit`，执行 `git --no-pager diff <base_commit> HEAD`；
- 捕获 `CalledProcessError` / `FileNotFoundError` 返回空串；
- 无论成功失败都 `chdir` 回原目录。

`remove_patches_to_tests()`（[#L199-L226](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L199-L226)）按 `diff --git a/` 分块，过滤路径含 `/test/`、`/tests/`、`/testing/`、`test_`、`tox.ini` 的块，避免模型改动测试影响验收。

`execute_task()` 覆写（[#L155-L170](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L155-L170)）：

```python
execution = await super().execute_task()
if self._trajectory_recorder:
    self._trajectory_recorder.finalize_recording(
        success=execution.success, final_result=execution.final_result)
if self.patch_path is not None:
    with open(self.patch_path, "w") as f:
        f.write(self.get_git_diff())
return execution
```

### 4.4.4 MCP 工具发现

[trae_agent.py#L65-L100](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L65-L100)：

- `initialise_mcp()` 调用 `discover_mcp_tools()`，若发现工具则 `self._tools.extend(self.mcp_tools)`；
- 遍历 `mcp_servers_config`，仅处理在 `allow_mcp_servers` 白名单内的服务；
- 每个服务新建 `MCPClient`，`connect_and_discover(...)` 成功后保存客户端用于清理；失败或被取消则跳过并清理；
- `cleanup_mcp_clients()` 遍历所有客户端 `cleanup("cleanup")`，异常被抑制。

## 4.5 新增一种 Agent 需要做什么

1. 新建 `MyAgent(BaseAgent)`，实现抽象方法 `new_task`、`cleanup_mcp_clients`，按需覆写 `get_system_prompt`（如有）、`llm_indicates_task_completed`、`_is_task_completed`、`reflect_on_result`。
2. 在 `AgentType` 枚举中加入类型。
3. 在 `Agent.__init__` 的 `match` 分支中构造 `MyAgent`，并在 `Config` 中增加对应配置段（可参考 `TraeAgentConfig` 与 `Config.create()` 的 `match agent_name` 分支）。
4. 在 CLI 的 `--agent-type` `click.Choice` 中加入新类型。

> 当前仓库只注册了 `trae_agent` 一种 Agent，`Config.create()` 对未知 agent 名会抛 `ConfigError`。

## 4.6 关键边界与注意点

- **工具集合在构造期固定**（`agent_config.tools`），MCP 工具是运行时追加；`new_task` 的 `tool_names` 仅在工具为空时生效。
- **`messages` 只是增量**，完整上下文在 Provider 客户端；不要在 `_run_llm_step` 里假设 `messages` 是完整历史。
- **`must_patch` 是字符串**（`"true"` / `"false"`），来自 CLI 的布尔转换，不是 Python bool。
- **轨迹 finalize 在 `TraeAgent` 层**，因此直接用 `BaseAgent` 时不会自动 finalize。
- **Docker 模式下 `project_path` 提示为 `/workspace`**，但宿主实际目录由 `DockerManager` 挂载映射。
