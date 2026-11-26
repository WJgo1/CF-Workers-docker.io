# 05 工具体系

工具是 Agent 与外界交互的唯一通道。设计目标是：**自描述、可注册、Provider 无关、可并行**。

## 5.1 核心数据结构

定义于 [tools/base.py](file:///workspace/trae-agent/trae_agent/tools/base.py)：

```python
@dataclass
class ToolExecResult:       # 工具内部返回
    output: str | None = None
    error: str | None = None
    error_code: int = 0     # 0 表示成功

@dataclass
class ToolCall:             # LLM 请求的工具调用
    name: str
    call_id: str
    arguments: ToolCallArguments = field(default_factory=dict)
    id: str | None = None   # OpenAI 专用

@dataclass
class ToolResult:           # 交给 Agent 的最终结果
    call_id: str
    name: str
    success: bool
    result: str | None = None
    error: str | None = None
    id: str | None = None

@dataclass
class ToolParameter:        # 参数声明
    name: str
    type: str | list[str]
    description: str
    enum: list[str] | None = None
    items: dict[str, object] | None = None
    required: bool = True
```

- `ToolExecResult.error_code` 是成功判据：`ToolExecutor` 用 `error_code == 0` 生成 `ToolResult.success`。
- `ToolCall.call_id` 由 Provider 提供（OpenAI `call_id`、Gemini 需自行生成 `uuid`），用于把结果与调用配对。
- `ToolResult.id` 是 OpenAI Responses API 的 `function_call.id`。

## 5.2 `Tool` 抽象

[base.py#L74-L179](file:///workspace/trae-agent/trae_agent/tools/base.py#L74-L179)：

```python
class Tool(ABC):
    def __init__(self, model_provider: str | None = None): ...
    @cached_property
    def name(self) -> str: return self.get_name()
    @cached_property
    def description(self) -> str: return self.get_description()
    @cached_property
    def parameters(self) -> list[ToolParameter]: return self.get_parameters()

    @abstractmethod
    def get_name(self) -> str: ...
    @abstractmethod
    def get_description(self) -> str: ...
    @abstractmethod
    def get_parameters(self) -> list[ToolParameter]: ...
    @abstractmethod
    async def execute(self, arguments: ToolCallArguments) -> ToolExecResult: ...

    def json_definition(self) -> dict: ...
    def get_input_schema(self) -> dict: ...
    async def close(self): return None
```

### 5.2.1 JSON Schema 生成与 Provider 兼容

`get_input_schema()`（[#L127-L175](file:///workspace/trae-agent/trae_agent/tools/base.py#L127-L175)）把 `ToolParameter` 列表转换为 JSON Schema，并针对 **OpenAI strict 模式**做特殊处理：

- 所有参数都进入 `required`；
- 非必填参数的类型改为 `[type, "null"]`（nullable）；
- `type == "object"` 的参数补 `additionalProperties: false`；
- 顶层 schema 补 `additionalProperties: false`。

这就是为什么部分工具（如 `BashTool`）会根据 `model_provider == "openai"` 把 `restart` 参数设为必填。

### 5.2.2 资源释放

工具若持有长期资源（如 `BashTool` 的持久 shell），需覆写 `close()`；`ToolExecutor.close_tools()` 会用 `asyncio.gather` 并发调用所有工具的 `close()`（[#L189-L193](file:///workspace/trae-agent/trae_agent/tools/base.py#L189-L193)）。

## 5.3 `ToolExecutor`：调度与容错

[base.py#L182-L244](file:///workspace/trae-agent/trae_agent/tools/base.py#L182-L244)：

- **名称归一化**：`name.lower().replace("_", "")`。因此 `str_replace_based_edit_tool` 与 `StrReplaceBasedEditTool` 都能匹配（注册表使用归一化键）。
- **执行单个调用** `execute_tool_call()`：
  - 找不到工具 → 返回失败 `ToolResult`，并在错误信息中列出可用工具；
  - 工具抛异常 → 捕获并包装为失败结果，**不会中断 Agent 循环**。
- **并行** `parallel_tool_call()`：`asyncio.gather` 并发执行；
- **顺序** `sequential_tool_call()`：逐个 `await`。

> `ToolExecutor` 不感知 Provider，也不做参数校验（校验在各工具或 LLM schema 层完成）。

## 5.4 工具注册表

[tools/\_\_init\_\_.py#L27-L34](file:///workspace/trae-agent/trae_agent/tools/__init__.py#L27-L34)：

```python
tools_registry: dict[str, type[Tool]] = {
    "bash": BashTool,
    "str_replace_based_edit_tool": TextEditorTool,
    "json_edit_tool": JSONEditTool,
    "sequentialthinking": SequentialThinkingTool,
    "task_done": TaskDoneTool,
    "ckg": CKGTool,
}
```

**新增工具的最小步骤**：实现 `Tool` 子类 → 在 `tools_registry` 注册 → 在配置的 `agents.trae_agent.tools` 中加入名称（或通过 `new_task(tool_names=...)` 指定）。

## 5.5 内置工具详解

### 5.5.1 `bash` — 持久 Shell

文件：[bash_tool.py](file:///workspace/trae-agent/trae_agent/tools/bash_tool.py)

- 内部 `_BashSession` 使用 `asyncio.create_subprocess_shell` 启动一个常驻 `/bin/bash`（Windows 下为 `cmd.exe /v:on`）；
- 通过**哨兵字符串** `,,,,bash-command-exit-__ERROR_CODE__-banner,,,,` 标记命令结束并捕获退出码；
- 单条命令默认 **120 秒**超时（`_timeout`），超时会抛 `ToolError` 并要求重启会话；
- 状态在多次调用间保持（cwd、环境变量等）；
- `restart: true` 会停止旧会话并新建；
- 关闭时 `terminate`，5 秒未退出则 `kill`，再等 2 秒。

参数（[#L191-L210](file:///workspace/trae-agent/trae_agent/tools/bash_tool.py#L191-L210)）：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `command` | string | 是 | 要执行的 bash 命令 |
| `restart` | boolean | OpenAI 下必填 | 是否重启会话 |

实现细节上读取的是 `process.stdout._buffer`（绕过 StreamReader），并在每轮后 `clear()`，以避免等待 EOF 导致死锁。

### 5.5.2 `str_replace_based_edit_tool` — 文件编辑

文件：[edit_tool.py](file:///workspace/trae-agent/trae_agent/tools/edit_tool.py)

子命令：`view` / `create` / `str_replace` / `insert`。

| 子命令 | 行为 | 关键约束 |
| --- | --- | --- |
| `view` | 文件按 `cat -n` 格式带行号输出；目录列出 2 层内非隐藏项 | 目录不支持 `view_range` |
| `create` | 新建文件 | 路径已存在则失败，禁止覆盖 |
| `str_replace` | 精确字符串替换 | `old_str` 必须**唯一**出现；制表符会先 `expandtabs()` |
| `insert` | 在第 `insert_line` 行之后插入 | 行号范围 `[0, n_lines]` |

`validate_path()`（[#L134-L152](file:///workspace/trae-agent/trae_agent/tools/edit_tool.py#L134-L152)）强制：

- 路径必须是**绝对路径**；
- 非 `create` 时路径必须存在；
- `create` 时路径不能已存在；
- 目录只允许 `view`。

成功后返回带上下文的片段（前后各 `SNIPPET_LINES = 4` 行），方便模型确认修改。长输出由 `maybe_truncate()` 截断（上限 `MAX_RESPONSE_LEN = 16000`）。

参数：`command`（enum）、`path`（必填）、`file_text`、`old_str`、`new_str`、`insert_line`、`view_range`（`[start, end]`，`end=-1` 表示到文件末尾）。

### 5.5.3 `json_edit_tool` — JSONPath 结构化编辑

文件：[json_edit_tool.py](file:///workspace/trae-agent/trae_agent/tools/json_edit_tool.py)

操作：

| 操作 | 行为 |
| --- | --- |
| `view` | 展示整个 JSON 或指定 JSONPath 的匹配值 |
| `set` | 用 `jsonpath_ng` 的 `update()` 更新匹配位置 |
| `add` | 取 JSONPath 的父路径，向对象加键或向数组指定索引插入 |
| `remove` | 反向遍历匹配，删除对象键或数组元素（处理索引偏移） |

约束：

- `file_path` 必须为**绝对路径**；
- `set` / `add` / `remove` 必须提供 `json_path`；
- `set` / `add` 必须提供 `value`；
- 解析失败、JSON 非法、路径无匹配均返回 `error_code=-1`；
- `pretty_print` 默认 `true`。

支持的 JSONPath 子集由 `jsonpath-ng` 提供：`$`、`.key`、`[index]`、`[*]`、`..key`、`[start:end]`。

### 5.5.4 `sequentialthinking` — 结构化思考

文件：[sequential_thinking_tool.py](file:///workspace/trae-agent/trae_agent/tools/sequential_thinking_tool.py)

- 维护 `thought_history` 与 `branches`；
- 参数校验 `_validate_thought_data()`：`thought_number` / `total_thoughts` ≥ 1，布尔字段类型检查，`revises_thought` / `branch_from_thought` 为正整数；
- 若当前 `thought_number` 超过 `total_thoughts`，自动抬高总数；
- 支持修订（`is_revision` + `revises_thought`）与分支（`branch_from_thought` + `branch_id`）；
- 返回 JSON 状态（当前编号、总数、是否需要继续、分支列表、历史长度）。

它**不直接修改代码**，仅作为模型的显式推理空间；System Prompt 鼓励在复杂问题中使用 5–25 个 thoughts。

### 5.5.5 `task_done` — 完成信号

文件：[task_done_tool.py](file:///workspace/trae-agent/trae_agent/tools/task_done_tool.py)

- 无参数，返回 `"Task done."`；
- `TraeAgent` 以「是否出现 `task_done` 调用」作为任务完成的第一判据；
- 工具描述中明确要求「完成验证后才可调用」。

### 5.5.6 `ckg` — 代码知识图谱

文件：[ckg_tool.py](file:///workspace/trae-agent/trae_agent/tools/ckg_tool.py)、[ckg/ckg_database.py](file:///workspace/trae-agent/trae_agent/tools/ckg/ckg_database.py)、[ckg/base.py](file:///workspace/trae-agent/trae_agent/tools/ckg/base.py)

- 使用 `tree-sitter` + `tree-sitter-languages` 解析源码，抽取函数 / 类 / 类方法，存入 SQLite；
- 支持语言：Python、Java、C/C++、TypeScript/JavaScript（见 `extension_to_language`）；
- 按 codebase 快照哈希缓存数据库：`~/.trae-agent/ckg/<hash>.db`，默认 **7 天**过期；
- 支持 git 仓库的 clean/dirty 状态哈希，非 git 目录退化为文件元数据哈希；
- 命令：`search_function`、`search_class`、`search_class_method`；
- 可按 `print_body` 控制是否输出函数/类体，输出超过 `MAX_RESPONSE_LEN` 会截断。

> 源码注释列出已知限制：子目录会重复建库、未做增量重建、JS/TS 匿名函数与箭头函数解析不完整。

### 5.5.7 MCP 工具适配

`MCPTool`（[mcp_tool.py](file:///workspace/trae-agent/trae_agent/tools/mcp_tool.py)）把 MCP Server 暴露的 `mcp.types.Tool` 包装成内部 `Tool`：

- `name` / `description` 直接透传；
- `get_parameters()` 从 `inputSchema.properties` 映射为 `ToolParameter`，按 `required` 列表标记必填；
- `execute()` 调 `client.call_tool()`，`isError` 时返回错误，否则取 `content[0].text`。

MCP 连接、发现与生命周期见 [10 Docker 与 MCP](./10-docker-and-mcp.md)。

## 5.6 Docker 模式下的工具路由

`DockerToolExecutor`（[docker_tool_executor.py](file:///workspace/trae-agent/trae_agent/tools/docker_tool_executor.py)）对上层暴露与 `ToolExecutor` 相同的 `sequential_tool_call` / `parallel_tool_call` / `close_tools`：

- `bash` → 直接把 `command` 交给容器执行；
- `str_replace_based_edit_tool` → 拼装 `/agent_tools/edit_tool <subcommand> --key 'value'`；
- `json_edit_tool` → 拼装 `/agent_tools/json_edit_tool --key 'value'`，`value` 用 `json.dumps` 序列化；
- 其他工具 → 回退到宿主 `ToolExecutor`；
- 参数名为 `path` 时做「宿主路径 → 容器路径」翻译（见 [10 Docker 与 MCP](./10-docker-and-mcp.md)）；
- 并行调用在 Docker 模式下被**串行化**（共享一个 pexpect shell）。

## 5.7 工具开发注意事项

1. **返回而不是抛异常**：工具内部异常应转成 `ToolExecResult(error=..., error_code=-1)`；未捕获异常会被 `ToolExecutor` 兜底，但错误信息更粗。
2. **绝对路径**：编辑类工具要求绝对路径，System Prompt 会提示模型拼接 `[Project root path]`。
3. **输出截断**：长输出请使用 `maybe_truncate()` / `MAX_RESPONSE_LEN`，避免撑爆上下文。
4. **幂等与唯一性**：`str_replace` 依赖唯一匹配，文档字符串里应明确提示模型带足上下文。
5. **Provider 兼容**：若参数可选，考虑 OpenAI strict 模式需要 nullable / required 的差异，可用 `self.model_provider` 分支处理。
6. **资源清理**：持有子进程、连接、文件句柄的工具必须实现 `close()`。
