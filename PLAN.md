# PLAN.md

## 1. 当前状态

| 项目 | 状态 |
|------|------|
| 项目阶段 | 第一阶段骨架初始化已完成 |
| 最新提交 | `chore: initialize project skeleton` |
| 分支 | `main` |
| 可运行 | 是（`uvicorn app.main:app --reload` 可启动，`pytest` 通过） |
| 虚拟环境 | `.venv`（Python 3.11+） |
| 包管理 | `pyproject.toml` + `setuptools`（可编辑安装 `pip install -e ".[test]"`） |

## 2. 已完成阶段

### 里程碑 1：项目骨架初始化

- 项目目录结构已按 `PROJECT.md` / `TASKS.md` / `AGENTS.md` 创建完成
- 所有 Python 包目录均含 `__init__.py`
- 最小可运行 FastAPI 入口 `app/main.py`（含 `GET /health`，返回 `{"status": "ok"}`）
- 最小测试 `tests/test_health.py`（使用 `httpx.AsyncClient` / `TestClient` 验证 `/health`）
- `pyproject.toml` 声明 Python 3.11+ 及核心依赖：
  - `fastapi>=0.115.0`、`pydantic>=2.0`、`sqlalchemy>=2.0`、`langgraph>=0.2`、`uvicorn>=0.30.0`
  - 测试依赖 `pytest>=8.0`、`httpx>=0.27.0`
- `README.md` 包含项目简介、运行方式、测试方式
- `.gitignore` 排除 `.venv/`、`__pycache__/`、构建产物、缓存目录、`TEMP_TASK_*.md`
- 文档文件名已对齐：`TASKS.md`、`AGENTS.md`

### 目录结构

```
werewolf-agent-team/
├── app/
│   ├── api/            # FastAPI 路由、WebSocket
│   ├── agents/         # Agent 工厂及各身份 Agent
│   ├── config/         # 板子配置、规则配置、人物画像配置
│   ├── engine/         # 规则引擎、结算、投票、胜负判定
│   ├── graph/          # LangGraph 主图、子图、节点
│   │   └── nodes/
│   ├── logging/        # 结构化日志与回放
│   ├── state/          # GameState schema、视图构建器、记忆
│   └── main.py         # FastAPI 入口
├── tests/
├── frontend/
├── README.md
├── PROJECT.md
├── TASKS.md
├── AGENTS.md
├── PLAN.md             # 本文件
└── pyproject.toml
```

## 3. 开发原则

以下原则来自 `AGENTS.md` 和 `PROJECT.md`，适用于所有后续开发：

1. **规则引擎与 Agent 决策解耦**：游戏规则必须由代码硬实现，LLM 只做推理、发言、投票、技能选择，不得裁决胜负或结算夜间行动
2. **严格信息隔离**：每个 Agent 仅能看到公共信息、自身身份、自身记忆、自身私有信息、当前允许的行动空间。任何 Agent 不得直接访问 `TruthState`
3. **所有输出必须结构化**：Agent 发言、投票、技能选择必须是 JSON / Pydantic 结构，禁止只返回自由文本
4. **先 MVP，再扩展**：6 人局 → LangGraph 主流程 → API 与日志 → 12 人标准板 → 白痴 / 猎人 → 守卫 / 警长 → 人机混战 → 前端 UI
5. **每次提交必须可运行**：禁止一次性大改导致系统长期不可用，优先产出可验证的小版本

## 4. 本地环境

| 配置项 | 值 |
|--------|-----|
| Python 版本 | 3.11+ |
| 虚拟环境路径 | `.venv/`（项目根目录） |
| PyCharm 解释器 | 选择 `.venv/bin/python` |
| 安装命令 | `.venv/bin/python -m pip install -e ".[test]"` |
| 启动命令 | `.venv/bin/uvicorn app.main:app --reload` |
| 测试命令 | `.venv/bin/python -m pytest` |

## 5. 大模型接入约定

### 5.1 模型供应商

本项目使用**阿里云百炼（DashScope）**平台，通过 OpenAI 兼容 API 调用**通义千问（Qwen）**系列模型。

### 5.2 默认配置

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 平台 | 阿里云百炼 DashScope | — |
| 地域 | **北京** | `dashscope.aliyuncs.com` |
| 默认测试模型 | **`qwen-plus`** | 性价比高，适合开发调试 |
| 生产候选模型 | `qwen-max`、`qwen-turbo` | 按场景选用 |
| API 风格 | OpenAI 兼容接口 | `base_url` 指向百炼 endpoint |

### 5.3 模型档位规划

| 档位 | 模型 | 适用角色 |
|------|------|----------|
| 高档位 | `qwen-max` | 预言家、高智商狼人、高配置 Agent |
| 中档位 | `qwen-plus` | 女巫、猎人、守卫 |
| 低档位 | `qwen-turbo` | 平民、低配置 Agent |

不同 Agent 在开局前可通过 `PersonaProfile` 绑定不同模型档位。

### 5.4 接入方式

- 使用 `openai>=1.0` Python SDK，`base_url` 指向百炼兼容端点
- API Key 从环境变量 `DASHSCOPE_API_KEY` 读取
- 代码中不硬编码任何 API Key
- 后续可以封装统一的 `LLMClient` 或 `ModelFactory`，按 Agent 配置分发不同模型

## 6. 密钥管理原则

| 规则 | 说明 |
|------|------|
| **禁止提交 API Key** | `DASHSCOPE_API_KEY` 或任何密钥、token、密码不得出现在 Git 历史中 |
| **本地使用 `.env`** | 开发者本地在项目根目录创建 `.env` 文件，写入 `DASHSCOPE_API_KEY=your-key` |
| **`.env` 已在 `.gitignore`** | `.env` 文件不会被 Git 跟踪 |
| **仓库提供 `.env.example`** | 提交 `.env.example` 作为模板（仅含变量名，不含真实值），新开发者复制为 `.env` 后填入自己的 Key |
| **代码读取方式** | 通过 `os.getenv("DASHSCOPE_API_KEY")` 或 `python-dotenv` 加载，不硬编码 |

### `.env.example` 示例内容

```
# 阿里云百炼 DashScope API Key
# 获取地址：https://dashscope.console.aliyun.com/apiKey
DASHSCOPE_API_KEY=your-api-key-here
```

## 7. 测试与交付标准

| 标准 | 要求 |
|------|------|
| 测试框架 | `pytest>=8.0` |
| HTTP 测试 | `httpx>=0.27.0`（FastAPI `TestClient` / `AsyncClient`） |
| 测试目录 | `tests/` |
| 运行方式 | `.venv/bin/python -m pytest` |
| 每次提交前 | 所有测试必须通过 |
| 提交粒度 | 小步提交，每步可运行、可验证 |
| 不可合并条件 | 测试失败 / 无法启动 / 引入真实密钥 |
| 日志 | 关键节点必须输出结构化日志 |

## 8. 后续里程碑

### 里程碑 2：6 人局 MVP

**目标**：跑通完整狼人杀对局流程的最小闭环。

- 实现 `GameState` schema（`PublicState`、`PrivateState`、`TruthState`）
- 实现 `ViewBuilder`，按玩家身份构建可见视图
- 实现 6 人局规则引擎（身份分配、夜晚结算、投票放逐、胜负判定）
- 实现 LangGraph 主流程图（夜晚子图 + 白天子图）
- 实现基础 Agent（狼人、预言家、女巫、平民）
- 接入百炼 `qwen-plus` 模型
- 实现结构化日志记录
- 创建 `.env.example`

### 里程碑 3：API 与日志

**目标**：通过 FastAPI 暴露对局接口，支持 HTTP 创建/查看对局。

- REST API：创建对局、查询对局状态、获取日志
- WebSocket：实时推送对局事件
- 数据库模型（SQLAlchemy + SQLite）
- 对局日志持久化

### 里程碑 4：12 人标准板（预女猎白）

**目标**：支持经典 12 人标准板，角色齐全。

- 新增角色 Agent：猎人、白痴
- 新增规则：猎人开枪、白痴翻牌
- 板子配置系统（可通过配置文件切换板子）

### 里程碑 5：扩展角色与机制

- 守卫 Agent
- 警长竞选机制
- 平票 PK 机制
- 女巫首夜自救、守卫自守/连守等规则细项可配置

### 里程碑 6：人机混战

- 支持座位配置为人类玩家
- 人类玩家通过 Web UI 参与发言、投票、技能选择
- 超时机制

### 里程碑 7：前端观战 UI

- React / Next.js 前端
- 实时观战页面
- 对局回放页面
- 评测与统计页面

### 里程碑 8：Agent 能力画像系统

- 完整 `PersonaProfile` 配置
- 模型档位绑定
- 上下文预算 / 推理预算分配
- 不同画像 Agent 对比评测

## 9. 交接注意事项

- **必须先读**：接手项目前，按顺序阅读 `README.md` → `PROJECT.md` → `AGENTS.md` → `PLAN.md`（本文件） → `TASKS.md`
- **环境准备**：创建 `.venv` → 安装依赖 → 复制 `.env.example` 为 `.env` → 填入 `DASHSCOPE_API_KEY`
- **验证可用**：运行 `pytest` 确认测试通过，启动 `uvicorn` 确认服务可访问 `/health`
- **开发顺序**：严格按照里程碑顺序，不得跳过前置里程碑
- **提交规范**：小步提交，每步可运行；禁止提交 `.env` 和真实密钥
- **文档更新**：每完成一个里程碑，更新本文件的"当前状态"和"已完成阶段"
