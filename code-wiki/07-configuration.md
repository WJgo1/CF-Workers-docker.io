# 07 配置系统

配置入口是 [config.py](file:///workspace/trae-agent/trae_agent/utils/config.py)。核心类：

| 类 | 位置 | 说明 |
| --- | --- | --- |
| `ModelProvider` | [#L16-L26](file:///workspace/trae-agent/trae_agent/utils/config.py#L16-L26) | Provider 凭证与端点 |
| `ModelConfig` | [#L29-L117](file:///workspace/trae-agent/trae_agent/utils/config.py#L29-L117) | 模型参数 |
| `MCPServerConfig` | [#L119-L142](file:///workspace/trae-agent/trae_agent/utils/config.py#L119-L142) | MCP Server 传输配置 |
| `AgentConfig` | [#L145-L155](file:///workspace/trae-agent/trae_agent/utils/config.py#L145-L155) | Agent 通用配置 |
| `TraeAgentConfig` | [#L158-L181](file:///workspace/trae-agent/trae_agent/utils/config.py#L158-L181) | Trae Agent 专属配置 |
| `LakeviewConfig` | [#L184-L190](file:///workspace/trae-agent/trae_agent/utils/config.py#L184-L190) | Lakeview 模型配置 |
| `Config` | [#L193-L391](file:///workspace/trae-agent/trae_agent/utils/config.py#L193-L391) | 聚合配置 + 解析 / 兼容逻辑 |

## 7.1 YAML 顶层结构

```yaml
model_providers:   # 必填，至少一个
  <name>:
    api_key: ...
    provider: openai | anthropic | azure | openrouter | doubao | ollama | google
    base_url: ...        # 可选
    api_version: ...     # Azure 需要

models:            # 必填，至少一个
  <name>:
    model_provider: <model_providers 的键>
    model: <模型名>
    temperature: 0.5
    top_p: 1
    top_k: 0
    parallel_tool_calls: true
    max_retries: 10
    max_tokens: 4096            # 可选
    max_completion_tokens: ...  # Azure 新模型可选
    supports_tool_calling: true # 默认 true
    candidate_count: ...        # Gemini 可选
    stop_sequences: [...]       # 可选

lakeview:          # 可选；若 agent 开启 lakeview 则必填
  model: <models 的键>

mcp_servers:       # 可选
  <name>:
    command: npx
    args: ["@playwright/mcp@0.0.27"]
    env: {...}
    cwd: ...
    timeout: ...
    trust: true
    description: ...

allow_mcp_servers: # 可选，白名单
  - playwright

agents:            # 必填，至少一个
  trae_agent:
    enable_lakeview: true
    model: <models 的键>
    max_steps: 200
    tools:
      - bash
      - str_replace_based_edit_tool
      - sequentialthinking
      - task_done
```

### 字段约束

- `ModelProvider`：`api_key`、`provider` 必填；`base_url`、`api_version` 可选。
- `ModelConfig`：`model_provider`、`model`、`temperature`、`top_p`、`top_k`、`parallel_tool_calls`、`max_retries` 在 dataclass 中**没有默认值**，YAML 中必须提供（否则 `ModelConfig(**cfg)` 会报错）。
- `TraeAgentConfig`：`enable_lakeview` 默认 `True`；`tools` 有默认值（`bash`、`str_replace_based_edit_tool`、`sequentialthinking`、`task_done`），但 YAML 一旦提供 `tools` 就完全以 YAML 为准。
- `allow_mcp_servers` 为空 / 未配置时，`TraeAgent.new_task` 不会初始化 MCP（`Agent.run` 判断 `self.agent.allow_mcp_servers`）。

## 7.2 `Config.create()` 解析流程

[config.py#L205-L300](file:///workspace/trae-agent/trae_agent/utils/config.py#L205-L300)：

1. 校验 `config_file` 与 `config_string` 只给一个；
2. `config_file` 以 `.json` 结尾 → 走 `create_from_legacy_config()`；
3. 否则 `yaml.safe_load`，YAML 解析失败抛 `ConfigError`；
4. 解析 `model_providers`：缺失或为空 → `ConfigError("No model providers provided")`；
5. 解析 `models`：
   - 缺失或为空 → `ConfigError("No models provided")`；
   - 每个模型的 `model_provider` 必须在已解析 providers 中，否则 `ConfigError`；
   - 构建后把字符串替换为对应 `ModelProvider` 实例；
6. 解析 `lakeview`：存在则要求 `model` 键且能在 `models` 中找到；
7. 解析 `mcp_servers` → `dict[str, MCPServerConfig]`，`allow_mcp_servers` 默认 `[]`；
8. 解析 `agents`：
   - 缺失或为空 → `ConfigError("No agent configs provided")`；
   - 每个 agent 必须有 `model`，且能在 `models` 中找到；
   - `match agent_name`：目前仅 `"trae_agent"`，未知名称抛 `ConfigError("Unknown agent: ...")`；
   - 若 `enable_lakeview` 为真但 `config.lakeview is None` → `ConfigError`。

## 7.3 运行时覆盖与优先级

`Config.resolve_config_values()` → `TraeAgentConfig.resolve_config_values()` → `ModelConfig.resolve_config_values()`：

- `max_steps`：CLI > 配置文件；
- `model`：CLI > 配置文件；
- Provider 切换：
  - 若 `provider` 命中 `model_providers`，直接使用该 `ModelProvider`；
  - 否则必须提供 `api_key` 才能注册一个新 Provider（`base_url` 可空）；
- API Key / Base URL：`resolve_config_value(cli_value, config_value, env_var)`，优先级为 **CLI > ENV > 配置 > 默认**；
- 环境变量名：`<PROVIDER>_API_KEY`、`<PROVIDER>_BASE_URL`，其中 `<PROVIDER>` 为 `provider` 字段大写（如 `OPENAI_API_KEY`、`OPENROUTER_BASE_URL`）。

`resolve_config_value()` 实现（[#L394-L410](file:///workspace/trae-agent/trae_agent/utils/config.py#L394-L410)）：

```python
if cli_value is not None: return cli_value
if env_var and os.getenv(env_var): return os.getenv(env_var)
if config_value is not None: return config_value
return None
```

## 7.4 `ModelConfig` 的便利方法

- `get_max_tokens_param()`：优先 `max_completion_tokens` → `max_tokens` → 默认 `4096`；
- `should_use_max_completion_tokens()`：仅当 `max_completion_tokens` 非空、provider 为 `azure`、且模型名包含 `gpt-5` / `o3` / `o4-mini` 时为真。

这两个方法被 `OpenAICompatibleClient` 用于选择正确的 token 参数。

## 7.5 旧版 JSON 配置兼容

`create_from_legacy_config()`（[#L324-L391](file:///workspace/trae-agent/trae_agent/utils/config.py#L324-L391)）读取 `LegacyConfig`（[legacy_config.py](file:///workspace/trae-agent/trae_agent/utils/legacy_config.py)），做如下映射：

| 旧版 | 新版 |
| --- | --- |
| `default_provider` | 选中 `model_providers[default_provider]` 作为唯一 Provider |
| provider 的 `model` / `max_tokens` / `temperature` / `top_p` / `top_k` / `parallel_tool_calls` / `max_retries` / `candidate_count` / `stop_sequences` | 新 `ModelConfig` 同名字段 |
| `max_steps` / `enable_lakeview` / `allow_mcp_servers` / `mcp_servers` | 新 `TraeAgentConfig` 同名字段 |
| `enable_lakeview=true` | 生成 `LakeviewConfig(model=model_config)` |

生成后的 `Config` 中：

```python
Config(
    trae_agent=trae_agent_config,
    lakeview=lakeview_config,
    model_providers={default_provider: model_provider},
    models={"default_model": model_config},
)
```

旧版字段说明见 [docs/legacy_config.md](file:///workspace/trae-agent/docs/legacy_config.md)。

## 7.6 MCP 配置字段

`MCPServerConfig`（[#L119-L142](file:///workspace/trae-agent/trae_agent/utils/config.py#L119-L142)）支持多传输的字段占位：

| 字段 | 传输 | 当前实现 |
| --- | --- | --- |
| `command` / `args` / `env` / `cwd` | stdio | ✅ 已实现 |
| `url` | SSE（注释写 WebSocket） | ❌ `NotImplementedError` |
| `http_url` / `headers` | streamable HTTP | ❌ `NotImplementedError` |
| `tcp` | WebSocket | ❌ 未使用 |
| `timeout` / `trust` / `description` | 通用 / 元数据 | 透传，当前未参与连接逻辑 |

> 因此配置 MCP 时请使用 `command + args` 形式，例如 `npx @playwright/mcp@...`。

## 7.7 配置错误速查

| 错误信息 | 原因 |
| --- | --- |
| `No model providers provided` | 缺少 `model_providers` 或为空 |
| `No models provided` | 缺少 `models` 或为空 |
| `Model provider X not found` | `models.*.model_provider` 引用了不存在的 provider |
| `No model provided for <agent>` | agent 配置缺少 `model` |
| `Model X not found` | agent / lakeview 引用了不存在的模型 |
| `Unknown agent: X` | `agents` 下出现未支持的名字（目前仅 `trae_agent`） |
| `Lakeview is enabled but no lakeview config provided` | `enable_lakeview: true` 但没有 `lakeview` 段 |
| `To register a new model provider, an api_key should be provided` | CLI `--provider` 指定了未注册 provider 且无 `--api-key` |
| `Error parsing YAML config: ...` | YAML 语法错误（常见为使用 Tab 缩进） |

## 7.8 配置最佳实践

1. **一模型一命名**：`models` 用语义名（`trae_agent_model`、`lakeview_model`），便于切换。
2. **Provider 与模型解耦**：同一 `model_providers` 可被多个 `models` 复用；切换 base_url 不影响模型定义。
3. **敏感信息走环境变量**：YAML 只写占位；CI 中通过 ENV 注入，避免提交密钥。
4. **显式声明全部必填模型字段**：`temperature`、`top_p`、`top_k`、`parallel_tool_calls`、`max_retries` 不能省略。
5. **Lakeview 可关**：研究场景若不需要摘要，设 `enable_lakeview: false` 可省一次模型调用 / 步。
6. **MCP 白名单**：`allow_mcp_servers` 必须显式列出要启用的服务，避免误连。
