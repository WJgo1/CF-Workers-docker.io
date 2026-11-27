# 可靠性分析自动化 Agent（飞书多维表格版）

本地化部署的可靠性数据分析工具：定时从**企业飞书多维表格（Bitable）**增量拉取数据，调用**你可自定义的可靠性预计插件**（内置韦布尔示例）完成分析，结果导出为**本地 Excel**并**回写飞书电子表格**。

- 鉴权方式：飞书企业自建应用 `App ID / App Secret`（可无人值守）
- 数据形态：多维表格 Base（记录 / 字段 / 视图）
- 增量同步：SQLite 本地镜像，按记录指纹只处理新增/变更，定期全量对账清理删除
- 执行方式：常驻定时（APScheduler）或单次执行（Windows 计划任务 / Linux cron）
- 结果输出：本地多 sheet Excel（含图表）+ 飞书电子表格回写
- 数据不外泄：除飞书开放平台地址外不访问任何外部服务，无遥测

## 工作流程

```
飞书多维表格 (Base)
      │  App ID/Secret 鉴权
      ▼
增量同步 ──► 本地 SQLite 镜像 (records / sync_state / runs)
      │
      ▼
可靠性预计插件  analyze(df, ctx) -> AnalysisResult
（内置示例：两参数韦布尔，右删失 MLE；正式模型由你实现）
      │
      ├──► 本地 Excel：概览 / 分析结果 / 数据快照 / 运行日志 / 图表
      └──► 飞书电子表格：写入指定 sheet（可自动创建）
```

## 目录结构

```
reliability-agent/
├─ config.example.yaml        # 配置模板，复制为 config.yaml 后修改
├─ .env.example               # 飞书应用凭证模板，复制为 .env
├─ requirements.txt
├─ run_once.bat               # Windows：执行一次
├─ start_scheduler.bat        # Windows：常驻定时
├─ install_scheduled_task.ps1 # Windows：注册计划任务
├─ reliability_agent/
│  ├─ cli.py                  # 命令行入口
│  ├─ config.py               # 配置加载 / 校验
│  ├─ pipeline.py             # 同步 -> 分析 -> 导出 -> 回写 编排
│  ├─ scheduler.py            # APScheduler 常驻调度
│  ├─ demo.py                 # 内置模拟数据
│  ├─ feishu/                 # 鉴权、Bitable 读取、电子表格回写
│  ├─ storage/state.py        # SQLite 增量状态库
│  ├─ analysis/               # 插件契约 / 加载器 / 内置韦布尔示例
│  └─ export/excel.py         # Excel 导出
├─ tests/                     # 离线测试（无需飞书凭证）
├─ docs/ANALYSIS_PLUGIN.md    # 自定义分析插件开发说明
└─ output/ logs/ data/        # 运行后自动生成
```

## 快速开始（Windows 本地化）

### 1. 准备 Python 环境

安装 Python 3.11 / 3.12（安装时勾选 `Add Python to PATH`），在项目目录执行：

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

内网环境可指定镜像：

```bat
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 复制配置

```bat
copy config.example.yaml config.yaml
copy .env.example .env
```

在 `.env` 中填写飞书应用凭证，在 `config.yaml` 中填写多维表格与电子表格 token（见下文）。

### 3. 先用模拟数据跑通全流程（不需要飞书凭证）

```bat
run_once.bat --demo
```

或：

```bat
python -m reliability_agent --config config.yaml run-once --demo
```

运行后会在 `output/` 生成 Excel，其中包含 3 个模拟产品型号组的韦布尔分析结果、概率图、可靠度曲线。

### 4. 配置飞书并自检

```bat
python -m reliability_agent --config config.yaml test-connection
```

输出鉴权成功、数据表字段列表、电子表格已有 sheet，即表示配置可用。

### 5. 正式执行与定时

```bat
run_once.bat
```

定时二选一（不要同时开，避免重复执行）：

- **常驻调度**（推荐，按 `schedule.cron` 触发）：双击 `start_scheduler.bat`，或做成开机启动项。
- **Windows 计划任务**（由系统每天拉起单次执行）：

```powershell
# 管理员 PowerShell
powershell -ExecutionPolicy Bypass -File install_scheduled_task.ps1 -Time "08:00"
```

Linux / 内网服务器可用 cron：

```bash
0 8 * * * cd /opt/reliability-agent && .venv/bin/python -m reliability_agent --config config.yaml run-once >> logs/cron.log 2>&1
```

## 飞书应用配置

1. 登录[飞书开放平台](https://open.feishu.cn/app) → 创建**企业自建应用**。
2. 在「权限管理」开通最小权限：
   - `bitable:app:readonly`（查看多维表格）
   - `sheets:spreadsheet`（查看、评论、编辑和管理电子表格）
   - 如提示云文档相关权限不足，再补 `drive:drive`（按企业实际策略）
3. 在「版本管理与发布」创建并发布版本，由管理员审核通过。
4. 在「凭证与基础信息」获取 `App ID` / `App Secret`，写入 `.env`。
5. **关键一步**：把目标多维表格和目标电子表格**添加到应用协作者**（文档分享面板添加应用/机器人，名称即应用名称）。未添加时报无权限错误。
6. 从浏览器地址栏获取 token：
   - 多维表格：`https://xxx.feishu.cn/base/{app_token}?table={table_id}&view={view_id}`
   - 电子表格：`https://xxx.feishu.cn/sheets/{spreadsheet_token}`

## 配置说明（config.yaml）

| 配置项 | 说明 |
| --- | --- |
| `feishu.base_url` | 企业飞书默认 `https://open.feishu.cn`；如走企业网关/代理改成对应地址 |
| `feishu.request.*` | 超时、重试次数、退避秒数 |
| `source.app_token` / `table_id` / `view_id` | 多维表格定位；`view_id` 可选 |
| `source.date_fields` | 日期字段名，导出 Excel 时毫秒时间戳转可读时间 |
| `source.column_map` | 原始列名 → 分析用列名（插件字段名对不上时使用） |
| `source.incremental.mode` | `hash`：全量拉取、按指纹增量落库（默认，稳妥）；`field`：按更新时间字段服务端过滤（大表更快） |
| `source.incremental.updated_field` | 时间字段名，`field` 模式必填 |
| `source.incremental.full_refresh_every` | 每 N 次同步做全量对账，清理源表已删除记录 |
| `analysis.plugin` | 插件定位，`module:function` 或 `path/to/file.py:function` |
| `analysis.options` | 传给插件的参数（时间字段、失效字段、分组字段、可靠度时间点等） |
| `output.excel.*` | 输出目录、文件名模板、保留天数、快照行数上限 |
| `output.feishu_sheet.*` | 是否回写、spreadsheet_token、sheet 名称、写前清空、分块行数 |
| `schedule.cron` | 5 段 cron，例如 `0 8 * * *` 每天 08:00 |
| `storage.db_path` | SQLite 状态库路径 |
| `storage.mirror_dir` | 每次同步后导出的本地 CSV 快照目录（审计用，可留空） |

## 增量同步与数据流

- `records` 表保存每条记录的归一化 JSON 与内容指纹；只有指纹变化的记录才会更新。
- `sync_state` 保存上次成功时间与运行次数，决定本次走增量还是全量对账。
- `runs` 保存每次运行历史，最终写入 Excel「运行日志」sheet。
- `hash` 模式：每次全量拉取，但只增量落库；实现简单、不会漏数据。
- `field` 模式：按 `updated_field` 服务端过滤拉取，失败会自动回退全量。
- 源表删除的记录：`full_refresh_every` 指定每 N 次全量对账时清理；N=0 表示只在首次全量。
- 分析始终使用**本地镜像的全量最新数据**，保证韦布尔等统计模型输入完整。

## 自定义分析（你的可靠性预计代码）

插件契约很简单：

```python
def analyze(df: pandas.DataFrame, ctx: AnalysisContext) -> AnalysisResult:
    ...
```

`AnalysisResult` 包含 `summary`（结果表）、`metrics`（关键指标）、`extra_sheets`（附加表）、`figures`（PNG 图片）、`notes`（说明）。

完整接口、示例代码与调试方法见 [docs/ANALYSIS_PLUGIN.md](docs/ANALYSIS_PLUGIN.md)。内置的 `weibull_example.py` 仅用于演示，请替换为你的正式模型：

```yaml
analysis:
  plugin: "plugins/my_reliability.py:analyze"
```

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `run_once.bat --demo` | 用模拟数据跑通全流程（不访问飞书） |
| `run_once.bat` | 正式执行一次：同步 + 分析 + Excel + 回写 |
| `run_once.bat --skip-sheet` | 执行但不回写飞书表格 |
| `run_once.bat --skip-sync` | 用本地镜像数据重新分析（不访问多维表格） |
| `start_scheduler.bat` | 常驻调度，按 `schedule.cron` 定时执行 |
| `test-connection` | 校验应用凭证、数据表字段、电子表格 sheet |
| `sync-only` | 只同步数据到本地镜像 |

## 数据安全

- 工具只调用 `feishu.base_url` 指向的飞书开放平台接口，没有第三方上报、遥测或云端中转。
- `App Secret` 仅存于本地 `.env`，日志不会输出 token/secret。
- 数据镜像（SQLite + CSV）与 Excel 全部落在本机 `data/`、`output/` 目录，可结合企业磁盘加密与目录 ACL 管理。
- 建议在专用账号/内网服务器运行，并限制 `output/`、`data/` 的访问权限。
- 如需更严格隔离，可将 `feishu.base_url` 指向企业内网网关地址。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 提示缺少 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 检查 `.env` 是否与 `config.yaml` 同目录，或系统环境变量已设置 |
| 权限错误 / `Forbidden`（如 91403） | 目标多维表格、电子表格需把应用加为协作者；确认权限范围与版本已发布 |
| `test-connection` 找不到字段 | 检查 `app_token`、`table_id` 是否取反，或 view 是否限制了字段 |
| 回写后 sheet 内容错位 | 检查 `sheet_name` 是否与已有 sheet 重名；工具会按名称定位并整表覆盖 |
| 图表中文显示为方块 | Windows 默认有微软雅黑；Linux 服务器需安装中文字体（如 Noto Sans CJK） |
| Excel 中时间显示为数字 | 把该列名加入 `source.date_fields` |
| 定时任务重复跑 | 常驻调度与 Windows 计划任务只保留一种 |
| 中文控制台乱码 | 使用项目自带 `.bat`（已执行 `chcp 65001`），或在 PowerShell 中设置 UTF-8 |

## 免责说明

内置韦布尔插件仅用于演示与流程验证，参数估计（右删失 MLE）不含置信区间、加速模型与行业规范修正。生产使用请以你的可靠性预计代码为准。
