# 08 Prompt 与 Lakeview

## 8.1 System Prompt

`TraeAgent.get_system_prompt()` 返回 [agent_prompt.py](file:///workspace/trae-agent/trae_agent/prompt/agent_prompt.py#L4-L53) 中的 `TRAE_AGENT_SYSTEM_PROMPT`。它不是简单的「你是一个助手」，而是一份**软件工程作业指导书**，包含：

1. **文件路径规则**：所有 `file_path` 参数必须是绝对路径，需用 `[Project root path]` 与相对路径拼接，禁止相对路径。
2. **七步工作法**：
   - 理解问题；
   - 探索定位相关文件；
   - **复现 Bug（关键步骤）**：改代码前先写复现脚本 / 测试用例；
   - 调试诊断根因；
   - 实施最小、精准修复；
   - 严格验证（复现脚本、既有测试、新增测试、边界情况）；
   - 总结工作。
3. **行为准则**：像资深工程师一样，优先正确性、安全性与测试驱动。
4. **`sequential_thinking` 使用指南**：建议 `total_thoughts` 至少 5、可到 25；可在思考之间穿插 bash 命令。
5. **收尾信号**：确认问题解决后应调用 `task_done`。

该 Prompt 在 `TraeAgent.new_task()` 中被包装为 `LLMMessage(role="system", content=...)`，作为初始消息的第一条（[trae_agent.py#L122-L123](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L122-L123)）。

随后追加的 user 消息包含：

```text
[Project root path]:
<absolute project path>

[Problem statement]: We're currently solving the following issue within our repository. Here's the issue text:
<issue text>
```

> Docker 模式下 `[Project root path]` 固定为 `/workspace`（[trae_agent.py#L132-L135](file:///workspace/trae-agent/trae_agent/agent/trae_agent.py#L132-L135)）。

### Prompt 与工具的耦合

System Prompt 中提到的工具名（`sequential_thinking`、`task_done`）必须与 `tools_registry` 一致，否则模型会调用不存在的工具。修改 Prompt 或工具名时需同步检查：

- `agents.trae_agent.tools` 配置；
- `TraeAgentToolNames` 列表；
- `llm_indicates_task_completed()` 中硬编码的 `"task_done"`。

## 8.2 Lakeview：步骤摘要

Lakeview 的目标是**用一个小模型为每个 Agent 步骤生成人可读的简短摘要与标签**，避免终端里刷满冗长的 LLM 原文。实现位于 [lake_view.py](file:///workspace/trae-agent/trae_agent/utils/lake_view.py)。

### 8.2.1 数据模型

```python
@dataclass
class LakeViewStep:
    desc_task: str      # 简短任务（≤10 词，不含 bug 细节）
    desc_details: str   # 补充细节（≤30 词，含 bug 细节）
    tags_emoji: str     # 例如 "👁️ EXAMINE_CODE · 📝 WRITE_FIX"
```

### 8.2.2 两次 LLM 调用

`create_lakeview_step(agent_step)`（[#L194-L209](file:///workspace/trae-agent/trae_agent/utils/lake_view.py#L194-L209)）：

1. `_agent_step_str(step)`：取 `llm_response.content`，若有工具调用则拼接 `Tool calls: [name] arguments`；
2. `extract_task_in_step(prev, this)`：
   - 使用 `EXTRACTOR_PROMPT`，要求输出 `<task>...</task><details>...</details>`；
   - 通过 few-shot 示例约束风格；
   - 最多重试 10 次直到格式合法；
3. `extract_tag_in_step(this)`：
   - 使用 `TAGGER_PROMPT`，从固定标签集选择；
   - 若历史步骤拼接超过 **300,000 字符**则跳过打标；
   - 解析 `<tags>A,B</tags>`，校验全部属于 `KNOWN_TAGS`，否则重试最多 10 次；
4. `get_label(tags, emoji=True)`：把标签映射为 emoji + 名称，用 ` · ` 连接。

### 8.2.3 标签集

| 标签 | emoji | 含义 |
| --- | --- | --- |
| `WRITE_TEST` | ☑️ | 编写复现测试 / 修复测试脚本 |
| `VERIFY_TEST` | ✅ | 运行复现测试验证环境 |
| `EXAMINE_CODE` | 👁️ | 查看、搜索、探索代码 |
| `WRITE_FIX` | 📝 | 修改源码修复 bug |
| `VERIFY_FIX` | 🔥 | 运行测试验证修复 |
| `REPORT` | 📣 | 向用户报告完成 / 进展 |
| `THINK` | 🧠 | 纯思考，无具体动作 |
| `OUTLIER` | ⁉️ | 不属于以上类别的重大动作（如装依赖） |

### 8.2.4 调用约束

- 使用**独立的** `LLMClient`（`LakeviewConfig.model`），不会污染主对话；
- 每次调用显式 `reuse_history=False`；
- 临时把 `temperature` 设为 `0.1` 以稳定输出；
- 两次调用都是 `async`，在 Simple/Rich 控制台中作为后台任务执行；
- 生成结果可通过 `TrajectoryRecorder.update_lakeview(step_number, summary)` 回写轨迹。

### 8.2.5 启用与关闭

- 配置：`agents.trae_agent.enable_lakeview: true` 且提供 `lakeview.model`；
- 装配：`Agent.__init__` 根据开关调用 `cli_console.set_lakeview(config.lakeview | None)`；
- 控制台：`SimpleCLIConsole` / `RichCLIConsole` 在步骤完成后异步生成并展示摘要；
- 若 Lakeview 关闭，`CLIConsole.lake_view` 为 `None`，控制台直接展示原始步骤信息。

## 8.3 Prompt 定制建议

| 目标 | 修改点 | 注意事项 |
| --- | --- | --- |
| 改变工作流（如先写测试） | `agent_prompt.py` | 与工具能力保持一致 |
| 改变完成信号 | `TraeAgent.llm_indicates_task_completed()` + Prompt | 工具名必须真实存在 |
| 改变未完成提示 | `task_incomplete_message()` | 提示要能引导模型继续 |
| 增加领域约束（安全 / 规范） | System Prompt 追加段落 | 过长会挤占上下文 |
| 关闭摘要 | 配置 `enable_lakeview: false` | 无需改代码 |

> Prompt 是 Agent 行为的「软约束」，而工具注册、完成判定、patch 校验是「硬约束」。调试行为异常时，优先检查硬约束是否与 Prompt 一致。
