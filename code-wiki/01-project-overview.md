# 01 项目总览

## 1.1 项目定位

Trae Agent 是字节跳动开源的 **LLM-based 软件工程 Agent**。它把「大模型 + 工具集 + 执行循环」封装成一个可研究的框架，核心目标不是做一个黑盒产品，而是提供一个**结构清晰、易于修改和做消融实验**的 Agent 基础设施。

典型使用方式：

```bash
trae-cli run "Create a hello world Python script"
trae-cli run "Fix the bug in main.py" --provider openai --model gpt-4o
trae-cli interactive
```

官方技术报告：arXiv:2507.23370（*Trae Agent: An LLM-based Agent for Software Engineering with Test-time Scaling*）。

## 1.2 核心特性

| 特性 | 说明 | 相关模块 |
| --- | --- | --- |
| 多 LLM Provider | OpenAI、Anthropic、Azure、OpenRouter、Doubao、Ollama、Google Gemini | `utils/llm_clients/` |
| 丰富工具生态 | Bash、字符串替换编辑、JSON 编辑、顺序思考、任务完成、代码知识图谱、MCP 工具 | `tools/` |
| 交互 / 单次执行 | `run` 单任务模式与 `interactive` 多轮会话模式 | `cli.py`、`utils/cli/` |
| 轨迹记录 | 完整记录 LLM 交互、Agent 步骤、工具调用与结果 | `utils/trajectory_recorder.py` |
| Lakeview | 用一个小模型为每一步生成「任务描述 + 标签」的简洁摘要 | `utils/lake_view.py` |
| Docker 沙箱 | 在容器内执行任务，支持镜像 / Dockerfile / 导入 tar / 附着已有容器 | `agent/docker_manager.py` |
| MCP 支持 | 通过 MCP 协议动态发现外部工具（当前仅 stdio） | `utils/mcp_client.py` |
| 灵活配置 | YAML 为主，兼容旧版 JSON，支持 CLI / 环境变量覆盖 | `utils/config.py`、`utils/legacy_config.py` |
| 可评测 | 内置 SWE-bench / SWE-bench-Live / Multi-SWE-bench 评测脚手架 | `evaluation/` |

## 1.3 技术栈

- **语言**：Python `>=3.12`（`.python-version` 锁定具体小版本）。
- **包管理 / 构建**：`uv` + `hatchling`；可执行入口 `trae-cli = trae_agent.cli:main`。
- **CLI**：`click`；终端渲染：`rich`；交互式 TUI：`textual`。
- **模型 SDK**：`openai`（Responses API / Chat Completions）、`anthropic`、`google-genai`、`ollama`。
- **工具与协议**：`mcp`（Model Context Protocol）、`jsonpath-ng`（JSONPath）、`tree-sitter` + `tree-sitter-languages`（代码解析）。
- **沙箱**：`docker` Python SDK + `pexpect`（持久 shell）。
- **测试**：`pytest` / `pytest-asyncio` / `pytest-mock` / `pytest-cov`；代码规范 `ruff` + `pre-commit`。
- **打包容器工具**：`pyinstaller`（把编辑工具编译成容器内可执行文件）。

主要依赖见 [pyproject.toml](file:///workspace/trae-agent/pyproject.toml#L1-L52)。

## 1.4 仓库结构

```text
trae-agent/
├── trae_agent/                 # 主包
│   ├── cli.py                  # Click CLI 入口：run / interactive / show-config / tools
│   ├── agent/                  # Agent 抽象与实现
│   │   ├── agent.py            # Agent：对外门面，装配 TraeAgent + recorder + console
│   │   ├── base_agent.py       # BaseAgent：Agent 执行循环骨架
│   │   ├── trae_agent.py       # TraeAgent：软件工程任务的具体策略
│   │   ├── agent_basics.py     # 状态枚举、AgentStep / AgentExecution / AgentError
│   │   └── docker_manager.py   # Docker 容器生命周期与命令执行
│   ├── tools/                  # 工具体系
│   │   ├── base.py             # Tool / ToolCall / ToolResult / ToolExecutor
│   │   ├── __init__.py         # tools_registry 注册表
│   │   ├── bash_tool.py        # 持久 bash 会话工具
│   │   ├── edit_tool.py        # str_replace_based_edit_tool
│   │   ├── json_edit_tool.py   # JSONPath 结构化编辑
│   │   ├── sequential_thinking_tool.py
│   │   ├── task_done_tool.py
│   │   ├── ckg_tool.py + ckg/  # 代码知识图谱（tree-sitter + sqlite）
│   │   ├── mcp_tool.py         # MCP 工具适配
│   │   ├── docker_tool_executor.py
│   │   └── *_cli.py            # 供 Docker 模式打包的独立工具 CLI
│   ├── prompt/agent_prompt.py  # System Prompt
│   ├── utils/
│   │   ├── config.py           # YAML 配置解析与优先级
│   │   ├── legacy_config.py    # 旧版 JSON 配置
│   │   ├── llm_clients/        # 各 Provider 客户端 + 消息模型 + 重试
│   │   ├── cli/                # Console 抽象、Simple、Rich(TUI)、工厂
│   │   ├── trajectory_recorder.py
│   │   ├── mcp_client.py
│   │   ├── lake_view.py
│   │   └── constants.py
│   └── dist/                   # Docker 模式打包产物（edit_tool / json_edit_tool）
├── evaluation/                 # SWE-bench 系列评测 + patch selection
├── tests/                      # 单元测试
├── server/                     # HTTP Server 设计说明（未实现）
├── docs/                       # 工具、轨迹、Roadmap、旧配置说明
├── trae_config.yaml.example    # 推荐 YAML 配置示例
├── trae_config.json.example    # 旧版 JSON 配置示例
├── pyproject.toml
├── Makefile
└── uv.lock
```

辅助文档：[docs/tools.md](file:///workspace/trae-agent/docs/tools.md)、[docs/TRAJECTORY_RECORDING.md](file:///workspace/trae-agent/docs/TRAJECTORY_RECORDING.md)、[docs/roadmap.md](file:///workspace/trae-agent/docs/roadmap.md)、[docs/legacy_config.md](file:///workspace/trae-agent/docs/legacy_config.md)。

## 1.5 一次任务的生命周期（鸟瞰）

```text
用户输入 task
   │
   ▼
CLI 解析参数 / 加载配置（CLI > ENV > YAML > 默认）
   │
   ▼
Agent 装配：TraeAgent + LLMClient + Tools + Console + TrajectoryRecorder
   │
   ▼
TraeAgent.new_task()：构造 system/user 初始消息，绑定 project_path / issue
   │
   ▼
BaseAgent.execute_task() 循环（≤ max_steps）：
   ├─ LLM 生成回复（可能包含 tool_calls）
   ├─ 若调用 task_done → 完成（可选 must_patch 校验）
   ├─ 否则 ToolExecutor 执行工具（并行 / 顺序）
   ├─ 工具结果作为新消息回填
   └─ 记录 step / 更新控制台 / 记录 trajectory
   │
   ▼
结束：生成 git diff（可选写 patch_path），finalize trajectory，打印结果
```

更完整的架构说明见 [02 整体架构](./02-architecture.md)，执行循环细节见 [04 Agent 核心](./04-agent-core.md)。

## 1.6 适用场景与不适用场景

**适合**：

- 研究与教学：理解 Agent 决策循环、工具调用、上下文管理。
- 二次开发：接入私有模型、私有 MCP 工具、定制 System Prompt。
- 自动化修复：在受控环境中对仓库执行 issue 修复与 patch 生成。

**暂不适合**：

- 生产级多租户 HTTP 服务：`server/` 尚未实现。
- 强隔离需求：Docker 模式已提供容器隔离，但仓库默认仍在宿主执行。
- 非软件工程领域的通用助理：System Prompt 与工具集均面向代码任务。
