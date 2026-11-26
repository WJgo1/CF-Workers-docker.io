# Trae Agent Code Wiki

> 本套文档基于 [bytedance/trae-agent](https://github.com/bytedance/trae-agent) 仓库 `e839e559`（2026-02-05）版本源码分析整理，面向希望**阅读理解、二次开发、扩展工具或研究 Agent 架构**的开发者。

Trae Agent 是一个基于 LLM 的通用软件工程 Agent。它通过 CLI 接收自然语言任务，在多轮「思考 → 调用工具 → 观察结果」的循环中自主完成代码定位、复现、修复、验证，并输出 patch 与完整执行轨迹（trajectory）。其设计强调**透明、模块化、可研究性**。

---

## 文档目录

| 章节 | 内容 |
| --- | --- |
| [01 项目总览](./01-project-overview.md) | 项目定位、核心特性、技术栈、仓库结构、快速上手 |
| [02 整体架构](./02-architecture.md) | 分层架构、核心执行循环、模块依赖关系、数据流与时序 |
| [03 安装与运行](./03-installation-and-usage.md) | 环境准备、安装、配置、CLI 命令与运行方式、排错 |
| [04 Agent 核心](./04-agent-core.md) | `Agent` / `BaseAgent` / `TraeAgent`、状态机、完成判定、patch 生成 |
| [05 工具体系](./05-tool-system.md) | `Tool` 抽象、工具注册表、`ToolExecutor`、各内置工具、MCP / CKG |
| [06 LLM 客户端](./06-llm-client.md) | `LLMClient`、Provider 适配矩阵、消息模型、重试与 Token 统计 |
| [07 配置系统](./07-configuration.md) | YAML 配置结构、优先级、模型/Provider/MCP 配置、旧版 JSON 兼容 |
| [08 Prompt 与 Lakeview](./08-prompt-and-lakeview.md) | System Prompt、Lakeview 步骤摘要与标签 |
| [09 控制台与轨迹记录](./09-console-and-trajectory.md) | Console 抽象、Simple/Rich(TUI)、TrajectoryRecorder |
| [10 Docker 与 MCP](./10-docker-and-mcp.md) | Docker 运行模式、路径映射与工具代理、MCP 客户端 |
| [11 评测与测试](./11-evaluation-and-tests.md) | SWE-bench 评测框架、Patch Selection、pytest 测试体系 |
| [12 API 速查与开发指南](./12-api-reference-and-development.md) | 关键类/函数速查、扩展点、依赖清单、开发与贡献流程 |

---

## 三分钟读懂项目

1. **入口**：`trae-cli run "<task>"` → [cli.py](file:///workspace/trae-agent/trae_agent/cli.py) 解析参数、加载 `trae_config.yaml`。
2. **装配**：`Agent` 根据 `agent_type` 创建 `TraeAgent`，注入 `LLMClient`、工具集合、`CLIConsole`、`TrajectoryRecorder`。
3. **执行**：`BaseAgent.execute_task()` 驱动「LLM 调用 → 解析工具调用 → 执行工具 → 回填结果」循环，直至 `task_done` 或达到 `max_steps`。
4. **落地**：结果写回 trajectory JSON；若指定 `--patch-path` 或 `must_patch`，通过 `git diff` 生成 patch。
5. **可扩展**：新增工具只需实现 `Tool` 并注册到 `tools_registry`；新增模型只需实现 `BaseLLMClient` 并接入 `LLMClient` 工厂。

---

## 阅读路线建议

- **只想起步使用**：01 → 03。
- **想理解 Agent 如何跑起来**：02 → 04 → 05 → 06。
- **想接入新模型 / 新工具**：05 → 06 → 07 → 12。
- **想做研究 / 复现 benchmark**：02 → 09 → 11。

---

## 代码引用约定

文档中的类名、文件名会尽量附上可点击源码链接，格式为 `file:///workspace/trae-agent/...`，在 IDE / 支持的 Markdown 查看器中可直接跳转到对应文件与行号（如 `#L147-L200`）。仓库原始文档（`README.md`、`docs/`、`evaluation/README.md`）与本 Wiki 互为补充，涉及配置示例时以仓库示例文件为准。

## 已知边界

- `server/` 目录仅包含 HTTP Server 设计说明，尚无可运行实现。
- MCP 目前仅实现 **stdio** 传输；HTTP / WebSocket 传输会抛出 `NotImplementedError`。
- 仓库自带的 `docs/` 中部分链接/字段描述可能落后于源码，本 Wiki 以源码为准并标注了实现细节。
