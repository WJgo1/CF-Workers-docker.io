# 10 Docker 与 MCP

## 10.1 Docker 运行模式

Docker 模式用于把文件编辑与命令执行限制在容器内，避免直接操作宿主环境。核心类：

| 类 | 文件 | 职责 |
| --- | --- | --- |
| `DockerManager` | [docker_manager.py](file:///workspace/trae-agent/trae_agent/agent/docker_manager.py#L10) | 构建/加载镜像、创建/附着容器、复制工具、持久 shell、执行命令、清理 |
| `DockerToolExecutor` | [docker_tool_executor.py](file:///workspace/trae-agent/trae_agent/tools/docker_tool_executor.py#L9) | 在宿主导航层与容器执行层之间路由工具调用 |

### 10.1.1 构造

```python
DockerManager(
    image=None, container_id=None, dockerfile_path=None, docker_image_file=None,
    workspace_dir=None, tools_dir=None, interactive=False,
)
```

- 四类来源（镜像 / 容器 ID / Dockerfile / 镜像 tar）至少要给一个，否则抛 `ValueError`；
- `client = docker.from_env()`；
- 固定路径：`container_workspace = "/workspace"`，`CONTAINER_TOOLS_PATH = "/agent_tools"`。

`BaseAgent` 在 `docker_config` 存在时构造它，`tools_dir` 指向包内 `trae_agent/dist`。

### 10.1.2 `start()` 流程

[docker_manager.py#L45-L126](file:///workspace/trae-agent/trae_agent/agent/docker_manager.py#L45-L126)：

1. **Dockerfile**：要求绝对路径，构建上下文为 Dockerfile 所在目录，镜像 tag 带 `uuid` 保证唯一；
2. **镜像 tar**：`client.images.load()` 加载后取第一个 tag；
3. **容器来源**：
   - `container_id` → `containers.get()` 附着，`_is_managed=False`（不会自动删除）；
   - `image` → `containers.run(image, command="sleep infinity", detach=True, volumes=..., working_dir="/workspace")`；
     - 若提供 `workspace_dir`，创建目录并以读写模式挂载到 `/workspace`；
     - 否则不挂载；
4. `_copy_tools_to_container()`：用 `docker cp` 把宿主的 `dist` 复制到容器 `/agent_tools`；
5. `_start_persistent_shell()`：`pexpect.spawn("docker exec -it <id> /bin/bash")`，等待 `$` / `#` 提示符。

### 10.1.3 命令执行

`execute(command, timeout=300)` 始终走 `_execute_interactive()`：

1. 若 shell 不存在或已死亡，尝试重启；
2. `sendline(command)`，再 `sendline("echo ---CMD_DONE---$?")`；
3. `expect("---CMD_DONE---(\\d+)")` 捕获退出码；
4. 过滤命令回显行，返回 `(exit_code, cleaned_output)`；
5. 超时返回 `(-1, 部分输出提示)`。

### 10.1.4 清理

`stop()`：

- 关闭 pexpect shell（`close(force=True)`）；
- 若容器由本实例创建（`_is_managed`），`container.stop()` + `container.remove()`；
- 附着的外部容器不会被删除。

`BaseAgent.execute_task()` 的 `finally` 中根据 `docker_keep` 决定是否调用 `stop()`。

### 10.1.5 工具路由与路径映射

`DockerToolExecutor` 只把以下三类工具放进容器：

```python
docker_tools = ["bash", "str_replace_based_edit_tool", "json_edit_tool"]
```

其余工具（`sequentialthinking`、`task_done`、`ckg`、MCP 工具）仍在宿主执行。

**路径翻译** `_translate_path()`：

- 若宿主路径位于 `host_workspace_dir` 下，转为相对于该目录的路径，再拼到 `container_workspace_dir`（默认 `/workspace`）；
- 否则原样返回；
- 仅处理参数名为 `path` 的字符串参数。

**命令拼装**：

| 工具 | 容器内命令 |
| --- | --- |
| `bash` | 直接执行 `command` |
| `str_replace_based_edit_tool` | `/agent_tools/edit_tool <subcommand> --key 'value' ...` |
| `json_edit_tool` | `/agent_tools/json_edit_tool --key 'value' ...`（`value` 用 `json.dumps`） |

**并行**：`parallel_tool_call()` 直接转调 `sequential_tool_call()`，因为容器共享一个 pexpect shell，无法安全并发。

### 10.1.6 工具打包

Docker 模式依赖 `trae_agent/dist/edit_tool` 与 `trae_agent/dist/json_edit_tool`。首次使用且目录缺失时，CLI 调用 `build_with_pyinstaller()`（[cli.py#L89-L116](file:///workspace/trae-agent/trae_agent/cli.py#L89-L116)）：

1. 删除 `trae_agent/dist`；
2. `pyinstaller --name edit_tool trae_agent/tools/edit_tool_cli.py`；
3. `pyinstaller --name json_edit_tool --hidden-import=jsonpath_ng trae_agent/tools/json_edit_tool_cli.py`；
4. 复制产物到 `trae_agent/dist`，清理临时 `dist/`。

`edit_tool_cli.py` / `json_edit_tool_cli.py` 是为打包而写的**自包含版本**（内置轻量 `Tool` 占位、参数解析），避免在容器里携带整个包依赖。

### 10.1.7 使用与限制

```bash
trae-cli run "Add tests" --docker-image python:3.11
trae-cli run "write a script" --docker-image python:3.12 --working-dir test_workdir/
trae-cli run "Update API" --docker-container-id 91998a56056c
trae-cli run "Debug auth" --dockerfile-path /abs/path/Dockerfile
trae-cli run "Fix bug" --docker-image-file /abs/path/custom.tar --docker-keep false
```

限制与注意：

- `--docker-container-id` 与 `--working-dir` 互斥（附着容器无法重新挂载）；
- 四类 Docker 来源互斥；
- 容器内工作目录固定 `/workspace`，System Prompt 也按此提示模型；
- 宿主机仍需安装 `docker` CLI 与 SDK；CLI 会用 `check_docker()` 校验 daemon；
- 复制工具依赖 `docker cp` 子进程，需有权限。

## 10.2 MCP（Model Context Protocol）

MCP 用于在运行时把外部服务（如 Playwright）的工具动态纳入 Agent。

### 10.2.1 组件

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `MCPClient` | [mcp_client.py](file:///workspace/trae-agent/trae_agent/utils/mcp_client.py#L26) | 建立 stdio 连接、列出工具、调用工具、清理 |
| `MCPTool` | [mcp_tool.py](file:///workspace/trae-agent/trae_agent/tools/mcp_tool.py#L8) | 把 MCP Tool 适配为内部 `Tool` |
| `MCPServerStatus` | [#L11-L15](file:///workspace/trae-agent/trae_agent/utils/mcp_client.py#L11-L15) | `DISCONNECTED` / `CONNECTING` / `CONNECTED` |
| `MCPDiscoveryState` | [#L17-L24](file:///workspace/trae-agent/trae_agent/utils/mcp_client.py#L17-L24) | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` |

### 10.2.2 连接与发现

`connect_and_discover(server_name, config, tools_container, model_provider)`：

1. 传输选择：
   - `http_url` → `NotImplementedError("HTTP transport is not implemented yet")`；
   - `url` → `NotImplementedError("WebSocket transport is not implemented yet")`；
   - `command` → 构造 `StdioServerParameters`，用 `stdio_client` 进入 `AsyncExitStack`；
   - 都没有 → `ValueError`；
2. `connect_to_server()`：状态置 `CONNECTING` → `ClientSession(...)` → `initialize()` → `CONNECTED`；异常则置 `DISCONNECTED` 并抛出；
3. `list_tools()`：获取工具列表，逐个包装成 `MCPTool` 放入容器。

### 10.2.3 与 Agent 的集成

- 配置：`mcp_servers` + `allow_mcp_servers`；
- `Agent.run()` 在 `new_task` 之后调用 `TraeAgent.initialise_mcp()`；
- 只有白名单中的 Server 会被连接；单个 Server 失败不影响其他 Server；
- 发现的工具追加到 `self._tools`，与内置工具一起参与后续 LLM 调用；
- `cleanup_mcp_clients()` 在 `finally` 与 `BaseAgent.execute_task()` 中双重兜底，关闭 `AsyncExitStack`。

### 10.2.4 配置示例

```yaml
allow_mcp_servers:
  - playwright

mcp_servers:
  playwright:
    command: npx
    args:
      - "@playwright/mcp@0.0.27"
    timeout: 60
    trust: true
    description: "Browser automation tools"
```

### 10.2.5 已知限制

- 仅 stdio 传输可用；HTTP / WebSocket 未实现；
- `MCPClient.cleanup()` 接收的是 `mcp_server_name`，但 `TraeAgent` 清理时统一传 `"cleanup"`，状态字典可能残留旧键；
- MCP 工具名直接使用 Server 暴露的名称，需注意与内置工具重名（`ToolExecutor` 归一化后同名会互相覆盖，后者生效）。

> 若需接入 HTTP MCP，可在 `connect_and_discover` 中补充对应 transport，并补一个 `Provider` 无关的测试。
