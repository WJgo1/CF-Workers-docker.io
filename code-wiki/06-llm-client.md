# 06 LLM 客户端

模型接入层位于 `trae_agent/utils/llm_clients/`，目标是把不同 Provider 的 SDK 差异收敛成统一的 `chat()` 契约。

## 6.1 统一消息与响应模型

文件：[llm_basics.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/llm_basics.py)

```python
@dataclass
class LLMMessage:
    role: str                          # system / user / assistant
    content: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None

@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    reasoning_tokens: int = 0
    # 支持 __add__ 累加

@dataclass
class LLMResponse:
    content: str
    usage: LLMUsage | None = None
    model: str | None = None
    finish_reason: str | None = None
    tool_calls: list[ToolCall] | None = None
```

`LLMUsage.__add__` 让 `AgentExecution.total_tokens` 能跨步累加；`LLMResponse.tool_calls` 是 `ToolCall` 列表，为空表示纯文本回复。

## 6.2 `LLMClient`：Provider 工厂

[llm_client.py#L15-L85](file:///workspace/trae-agent/trae_agent/utils/llm_clients/llm_client.py#L15-L85)

```python
class LLMProvider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    DOUBAO = "doubao"
    GOOGLE = "google"
```

`LLMClient.__init__` 根据 `model_config.model_provider.provider` 选择具体客户端，并采用**延迟导入**避免循环依赖：

| provider | 客户端类 | 底层 SDK / 接口 |
| --- | --- | --- |
| `openai` | `OpenAIClient` | `openai.OpenAI().responses.create`（Responses API） |
| `anthropic` | `AnthropicClient` | `anthropic.Anthropic().messages.create` |
| `azure` | `AzureClient` | `OpenAICompatibleClient` + `AzureProvider` |
| `openrouter` | `OpenRouterClient` | `OpenAICompatibleClient` + `OpenRouterProvider` |
| `doubao` | `DoubaoClient` | `OpenAICompatibleClient` + `DoubaoProvider` |
| `ollama` | `OllamaClient` | `ollama.chat`（本地默认 `http://localhost:11434`） |
| `google` | `GoogleClient` | `google-genai` 的 `client.models.generate_content` |

对外方法：

```python
def chat(messages, model_config, tools=None, reuse_history=True) -> LLMResponse
def set_chat_history(messages) -> None
def set_trajectory_recorder(recorder) -> None
def supports_tool_calling(model_config) -> bool
```

`supports_tool_calling()` 先看客户端是否实现该方法，否则回退到 `model_config.supports_tool_calling`。

## 6.3 `BaseLLMClient` 契约

[base_client.py#L13-L43](file:///workspace/trae-agent/trae_agent/utils/llm_clients/base_client.py#L13-L43)

- 保存 `api_key`、`base_url`、`api_version`、`trajectory_recorder`；
- 抽象 `set_chat_history()` 与 `chat()`；
- 默认 `supports_tool_calling()` 返回 `model_config.supports_tool_calling`。

所有子类的 `chat()` 共同职责：

1. 把内部 `LLMMessage` 转成 Provider 原生格式；
2. 根据 `reuse_history` 合并 / 替换内部 `message_history`；
3. 把 `Tool` 列表转换为 Provider 的工具 schema；
4. 通过 `retry_with()` 调用真实 API；
5. 解析响应为 `LLMResponse`（含 `usage`、`tool_calls`）；
6. 把 assistant 文本 / 工具调用追加回历史；
7. 若挂了 `TrajectoryRecorder`，调用 `record_llm_interaction(...)`。

## 6.4 各 Provider 实现要点

### 6.4.1 OpenAI（Responses API）

[openai_client.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/openai_client.py)

- 使用 `client.responses.create(input=..., tools=..., max_output_tokens=...)`；
- 工具 schema 用 `FunctionToolParam(..., strict=True, type="function")`；
- 对 `o3` / `o4-mini` / `gpt-5` 系列**不传 temperature**（这些模型不支持该参数）；
- 解析 `response.output`：
  - `function_call` → `ToolCall`，并把 `ResponseFunctionToolCallParam` 追加到历史；
  - `message` → 拼接 `output_text`；
- `call_id` / `id` 都保留，便于工具结果回填。

### 6.4.2 Anthropic（Messages API）

[anthropic_client.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/anthropic_client.py)

- 使用 `client.messages.create(..., max_tokens, system, tools, temperature, top_p, top_k)`；
- **工具 schema 特殊处理**：
  - `str_replace_based_edit_tool` → `TextEditor20250429(type="text_editor_20250429")`；
  - `bash` → `ToolBash20250124Param(type="bash_20250124")`；
  - 其他 → 普通 `ToolParam(input_schema=...)`；
- 解析 `response.content`：`text` 拼入 content，`tool_use` 转 `ToolCall`（`call_id=content_block.id`）；
- `system` 消息单独抽出，不放进 `messages`。

### 6.4.3 OpenAI-Compatible（Azure / OpenRouter / Doubao）

[openai_compatible_base.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/openai_compatible_base.py)

- 抽象 `ProviderConfig`：`create_client`、`get_service_name`、`get_provider_name`、`get_extra_headers`、`supports_tool_calling`；
- `OpenAICompatibleClient` 使用 `chat.completions.create`（Chat Completions API）；
- Token 参数按 `ModelConfig.should_use_max_completion_tokens()` 选择 `max_completion_tokens` 或 `max_tokens`；
- 各 Provider 只需实现 `ProviderConfig`：
  - `AzureProvider`：处理 `api_version` 与 Azure endpoint；
  - `OpenRouterProvider`：附加 `HTTP-Referer` / `X-Title` 等 headers；
  - `DoubaoProvider`：默认 base_url 为火山方舟地址。

### 6.4.4 Ollama

[ollama_client.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/ollama_client.py)

- 直接使用 `ollama.chat(messages, model, tools)`；
- 默认 base_url 为 `http://localhost:11434/v1`；无 API Key 时可用 `"ollama"` 占位；
- 工具 schema 转成 Ollama 期望的 `{"type": "function", "function": {...}}` 结构；
- 与 OpenAI Responses 消息结构相似（`ResponseInputParam`）。

### 6.4.5 Google Gemini

[google_client.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/google_client.py)

- 使用 `genai.Client(api_key=...)` 与 `models.generate_content(contents=..., config=...)`；
- `parse_messages()` 返回 `(contents, system_instruction)`；
- 支持 `candidate_count`、`stop_sequences` 等 Gemini 特有配置；
- 由于 Gemini 工具调用没有 `call_id`，客户端侧用 `uuid` 生成以配对结果。

## 6.5 重试机制

[retry_utils.py](file:///workspace/trae-agent/trae_agent/utils/llm_clients/retry_utils.py#L13-L55)：

```python
retry_with(func, provider_name, max_retries)
```

- 最多尝试 `max_retries + 1` 次；
- 每次失败打印异常与 traceback，随机 `sleep(3~30s)`；
- 最后一次仍失败则抛出原异常。
- 由各客户端在 `chat()` 内包裹真实 API 调用，`max_retries` 来自 `ModelConfig.max_retries`。

## 6.6 上下文与历史管理

这是理解 Agent 行为的关键：

- **历史在客户端**：各客户端维护 `self.message_history`；`chat()` 默认 `reuse_history=True`，会追加本次增量。
- **Agent 只传增量**：`BaseAgent._run_llm_step()` 首轮传 `[system, user]`，后续只传工具结果 / 提示消息。
- **`set_chat_history()`**：允许外部整体重置历史。
- **Lakeview** 使用独立 `LLMClient`，且显式 `reuse_history=False`，避免污染主对话。

> 如果未来要支持「压缩上下文」或「重放历史」，应改在客户端层统一处理，而不是在 Agent 层拼接。

## 6.7 扩展一个新 Provider

1. 新建 `xxx_client.py`：
   - 若是 OpenAI 兼容，继承 `OpenAICompatibleClient` 并实现 `ProviderConfig`；
   - 否则继承 `BaseLLMClient`，实现 `set_chat_history()` / `chat()`。
2. 在 `LLMProvider` 枚举中加入值。
3. 在 `LLMClient.__init__` 的 `match` 中增加分支（保持延迟导入）。
4. 配置中 `model_providers.<name>.provider` 使用新枚举值；环境变量命名约定为 `<PROVIDER>_API_KEY` / `<PROVIDER>_BASE_URL`。
5. 如需特殊工具 schema（如 Anthropic 的 text editor / bash），在 `chat()` 中做名称到 schema 的映射。
6. 增加单测（可参考 `tests/utils/test_google_client.py`、`test_openrouter_client_utils.py`、`test_ollama_client_utils.py`）。
