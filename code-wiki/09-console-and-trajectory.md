# 09 控制台与轨迹记录

Agent 的可观测性由两条独立链路组成：**实时控制台**（给人看）与**轨迹记录**（给机器/复盘看）。二者都通过 `BaseAgent` 的 `_update_cli_console()` / `_record_handler()` 被驱动，但互不依赖。

## 9.1 Console 抽象

文件：[cli_console.py](file:///workspace/trae-agent/trae_agent/utils/cli/cli_console.py)

### 9.1.1 枚举与展示映射

```python
class ConsoleMode(Enum):
    RUN = "run"                 # 单任务执行后退出
    INTERACTIVE = "interactive" # 多任务会话

class ConsoleType(Enum):
    SIMPLE = "simple"           # 纯文本输出
    RICH = "rich"               # Textual TUI

AGENT_STATE_INFO = {
    AgentStepState.THINKING:     ("blue",    "🤔"),
    AgentStepState.CALLING_TOOL: ("yellow",  "🔧"),
    AgentStepState.REFLECTING:   ("magenta", "💭"),
    AgentStepState.COMPLETED:    ("green",   "✅"),
    AgentStepState.ERROR:        ("red",     "❌"),
}
```

### 9.1.2 `CLIConsole` 接口

| 方法 | 作用 |
| --- | --- |
| `async start()` | 启动控制台（可能阻塞到任务结束） |
| `update_status(agent_step, agent_execution)` | 根据当前步 / 整体执行刷新显示 |
| `print_task_details(details)` | 打印任务初始信息（Provider、Model、工具、轨迹路径等） |
| `print(message, color, bold)` | 通用输出 |
| `get_task_input() -> str \| None` | 交互模式获取任务，`None` 表示退出 |
| `get_working_dir_input() -> str` | 交互模式获取工作目录 |
| `stop()` | 停止并清理 |
| `set_lakeview(config)` | 注入 / 清除 Lakeview |

内部字段：

- `console_step_history: dict[int, ConsoleStep]`：按步号缓存展示状态；
- `agent_execution: AgentExecution | None`：整体执行引用；
- `lake_view: LakeView | None`。

`ConsoleStep` 记录 `agent_step`、是否已打印（`agent_step_printed`）、以及 Lakeview 面板生成任务（`lake_view_panel_generator`）。

### 9.1.3 通用步骤表格

`generate_agent_step_table(agent_step)`（[#L126-L171](file:///workspace/trae-agent/trae_agent/utils/cli/cli_console.py#L126-L171)）把一步渲染成 Rich `Table`：

- 状态行（emoji + 标题）；
- LLM Response；
- 工具调用名 + 参数 + 对应结果（按 `call_id` 匹配）；
- Reflection；
- Error。

两种控制台都复用它，保证信息一致。

## 9.2 `SimpleCLIConsole`

文件：[simple_console.py](file:///workspace/trae-agent/trae_agent/utils/cli/simple_console.py)

- `update_status()`：
  - 首次见到某步号时登记到 `console_step_history`；
  - 仅当状态为 `COMPLETED` / `ERROR` 且尚未打印时输出步骤表，避免重复刷屏；
  - 若启用 Lakeview，则用 `asyncio.create_task()` 后台生成摘要面板；
- `start()`：轮询 `agent_execution`，直到状态为 `COMPLETED` / `ERROR` 后打印最终摘要；
- 交互模式额外支持 `help` / `status` / `clear` / `exit` 等命令（命令解析在 CLI 的 `_run_simple_interactive_loop()` 中）。

## 9.3 `RichCLIConsole`（Textual TUI）

文件：[rich_console.py](file:///workspace/trae-agent/trae_agent/utils/cli/rich_console.py)

组成：

| 组件 | 说明 |
| --- | --- |
| `TokenDisplay(Static)` | 实时 token 统计（total / input / output），`reactive` 驱动刷新 |
| `RichConsoleApp(App[None])` | Textual 应用，CSS 来自 `rich_console.tcss` |
| `RichCLIConsole(CLIConsole)` | 把 Agent 事件桥接到 TUI，并管理输入 / 任务执行 |

关键能力：

- 使用 `Header` / `Footer` / `Input` / `RichLog` / `Static` 构建界面；
- `SuggestFromList` 提供命令补全；
- `set_initial_task()` / `set_agent_context()` 让 TUI 知道当前任务与 Agent 引用；
- TUI 内部可发起任务执行（交互模式下由 `RichCLIConsole.start()` 接管整个会话）。

## 9.4 `ConsoleFactory`

文件：[console_factory.py](file:///workspace/trae-agent/trae_agent/utils/cli/console_factory.py)

```python
ConsoleFactory.create_console(console_type, mode, lakeview_config)
ConsoleFactory.get_recommended_console_type(mode)
```

- `SIMPLE` / `RICH` 分别实例化对应控制台；
- 推荐策略：`INTERACTIVE → RICH`，`RUN → SIMPLE`。

> CLI 中 `--console-type` 默认是 `simple`；只有显式传 `rich` 或省略该参数且走推荐逻辑时才会启用 TUI。

## 9.5 `TrajectoryRecorder`

文件：[trajectory_recorder.py](file:///workspace/trae-agent/trae_agent/utils/trajectory_recorder.py)

### 9.5.1 初始化与路径

```python
TrajectoryRecorder(trajectory_path: str | None = None)
```

- 未传路径 → `trajectories/trajectory_<YYYYmmdd_HHMMSS>.json`；
- `Path(...).resolve()`，并尝试创建父目录（失败仅打印警告）。

### 9.5.2 轨迹数据结构

```json
{
  "task": "...",
  "start_time": "ISO8601",
  "end_time": "ISO8601",
  "provider": "anthropic",
  "model": "claude-...",
  "max_steps": 200,
  "llm_interactions": [
    {
      "timestamp": "...",
      "provider": "...",
      "model": "...",
      "input_messages": [{"role": "...", "content": "...", "tool_call": {...}, "tool_result": {...}}],
      "response": {
        "content": "...",
        "model": "...",
        "finish_reason": "...",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": null,
                  "cache_read_input_tokens": null, "reasoning_tokens": null},
        "tool_calls": [{"call_id": "...", "name": "...", "arguments": {...}, "id": "..."}]
      },
      "tools_available": ["bash", "..."]
    }
  ],
  "agent_steps": [
    {
      "step_number": 1,
      "timestamp": "...",
      "state": "completed",
      "llm_messages": [...],
      "llm_response": {...},
      "tool_calls": [...],
      "tool_results": [{"call_id": "...", "success": true, "result": "...", "error": null, "id": "..."}],
      "reflection": null,
      "error": null,
      "lakeview_summary": "..."   // update_lakeview 后出现
    }
  ],
  "success": true,
  "final_result": "...",
  "execution_time": 12.34
}
```

### 9.5.3 生命周期方法

| 方法 | 调用方 | 作用 |
| --- | --- | --- |
| `start_recording(task, provider, model, max_steps)` | `TraeAgent.new_task()` | 写入任务元数据并立即落盘 |
| `record_llm_interaction(messages, response, provider, model, tools)` | 各 LLM Client | 记录一次请求/响应 |
| `record_agent_step(...)` | `BaseAgent._record_handler()` | 记录一步的完整状态 |
| `update_lakeview(step_number, summary)` | 控制台 / Lakeview | 回写某步摘要 |
| `finalize_recording(success, final_result)` | `TraeAgent.execute_task()` | 写入结束时间、成功标志、耗时 |
| `save_trajectory()` | 各方法内部 | 每次记录后整体 `json.dump` |

### 9.5.4 实现特征与注意事项

- **每次记录都整文件重写**：便于中断时也有较完整轨迹，但大轨迹有 IO 开销；
- **序列化是手写的**：`_serialize_message/tool_call/tool_result` 只保留关键字段，`arguments` 原样写入；
- **异常仅打印警告**：`save_trajectory()` 失败不会中断 Agent；
- **finalize 在 `TraeAgent` 层**：直接使用 `BaseAgent` 不会自动 finalize；
- **CLI 中断**：`KeyboardInterrupt` 时 CLI 会提示「Partial trajectory saved to ...」，因为每次记录都已落盘；
- **Lakeview 摘要**：`update_lakeview()` 按 `step_number` 查找并写入 `lakeview_summary`，由控制台的异步任务触发。

## 9.6 两条链路的协作关系

```text
BaseAgent._run_llm_step / _tool_call_handler / _finalize_step
        │
        ├── _update_cli_console(step, execution) ──► CLIConsole.update_status
        │                                             ├─ Simple：打印表格 / 后台 Lakeview
        │                                             └─ Rich：刷新 TUI 组件
        │
        └── _record_handler(step, messages) ────────► TrajectoryRecorder.record_agent_step
                                                       └─ save_trajectory() → JSON

LLMClient.chat() ───────────────────────────────────► TrajectoryRecorder.record_llm_interaction
```

控制台关注「当前状态是否可读」，轨迹关注「全过程是否可复现」；两者都通过 `Agent.set_cli_console()` / `set_trajectory_recorder()` 注入，可分别关闭。
