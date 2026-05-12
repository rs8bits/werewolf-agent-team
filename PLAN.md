# PLAN.md

## 1. 当前状态

| 项目 | 状态 |
|------|------|
| 项目阶段 | 里程碑 2C-4 Runner / LangGraph 雏形已完成 |
| 最新提交 | 以 `git log -1 --oneline` 为准 |
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

### 里程碑 2A：百炼/Qwen 大模型接入层

- `app/config/settings.py` 从 `.env` / 环境变量读取 DashScope 配置
- `app/llm/schemas.py` 定义模型调用的基础 Pydantic 数据结构
- `app/llm/client.py` 封装 OpenAI-compatible 客户端，惰性初始化，不在 import 时发起网络请求
- `.env.example` 提供本地配置模板，不包含真实密钥
- `tests/test_settings.py` / `tests/test_llm_client.py` 覆盖配置读取、缺失密钥错误、mock 模型调用

### 里程碑 2B：核心领域模型与 6 人板子配置

- `app/state/schemas.py` 定义核心领域模型与角色阵营映射
- `app/config/persona_config.py` 定义 `PersonaProfile` 能力画像
- `app/config/role_setups.py` 定义 6 人局预设板子与座位配置
- `tests/test_schemas.py` / `tests/test_persona_config.py` / `tests/test_role_setups.py` 覆盖核心模型、画像和板子配置

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

# 阿里云百炼 OpenAI 兼容接口（北京地域）
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 默认测试模型
DASHSCOPE_MODEL=qwen-plus

# 请求超时（秒）
DASHSCOPE_TIMEOUT_SECONDS=60
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

### 里程碑 2A：百炼/Qwen 大模型接入层 ✅

**状态**：已完成基础接入层。

已交付：
- `app/config/settings.py` — 配置模块，从环境变量 / `.env` 读取 DashScope 配置
- `app/llm/schemas.py` — Pydantic 数据结构（ChatMessage, ChatRequest, ChatResponse）
- `app/llm/client.py` — `LLMClient` 封装，基于 OpenAI Python SDK，惰性初始化，不在 import 时发起网络请求
- `.env.example` — 环境变量模板（仅变量名，无真实 Key）
- `tests/test_settings.py` — 配置读取测试
- `tests/test_llm_client.py` — mock client 测试（不调用真实百炼接口）

约定：
- 真实 `DASHSCOPE_API_KEY` 仅存于本地 `.env`，禁止提交
- 新开发者复制 `.env.example` 为 `.env` 后填入自己的 Key

### 里程碑 2B：核心领域模型与 6 人板子配置 ✅

**状态**：已完成核心数据结构与预设板配置。

已交付：
- `app/state/schemas.py` — 核心领域模型（`Camp`、`Role`、`GamePhase`、`PlayerType`、`PlayerStatus`、`PlayerState`、`PublicState`、`TruthState`、`GameState`），全部使用 Pydantic v2
- `app/config/persona_config.py` — `PersonaProfile` 能力画像模型（intelligence / memory / experience / rhetoric / risk_appetite / discipline / model / context_window / reasoning_budget），含默认值与范围校验
- `app/config/role_setups.py` — 6 人局预设板子（2 狼人 / 1 预言家 / 1 女巫 / 2 平民），提供 `get_role_setup()` / `six_player_setup()` / `SeatConfig` / `RoleSetup` 结构化对象
- `tests/test_schemas.py` — Role↔Camp 映射、GameState 6 人初始化、序列化测试
- `tests/test_persona_config.py` — 默认值校验、范围校验、自定义配置测试
- `tests/test_role_setups.py` — 6 人局角色数量、座位生成、不支持人数报错测试

### 里程碑 2C-1：信息隔离 View Builder ✅

**状态**：已完成私有视图构建器，支持 6 人局 MVP 的严格信息隔离。

已交付：
- `app/state/view_builder.py` — Pydantic 视图模型（`VisiblePlayer`、`PlayerView`）与 `build_player_view()` 构建函数
- `tests/test_view_builder.py` — 覆盖狼人视图、好人隔离、公开信息不含身份、无效座位号、各 phase/role 动作空间、序列化无 truth_state 泄露

信息隔离保证：
- 狼人可见 `known_wolf_team`（狼队成员）
- 好人 `known_wolf_team` 永远为空
- `VisiblePlayer` 不暴露角色和阵营
- `PlayerView` 不含 `truth_state`
- 无效座位号抛出 `ValueError`

`available_actions` 最小规则：
- `setup` / `ended`：空
- `night`：狼人 `["werewolf_kill"]`，预言家 `["seer_check"]`，女巫 `["witch_save", "witch_poison"]`，平民空
- `day`：`["speak"]`
- `vote`：存活且可投票 `["vote"]`，否则空

### 里程碑 2C-2：规则引擎 MVP ✅

**状态**：已完成 6 人局规则引擎最小闭环。

已交付：
- `app/engine/initializer.py` — `initialize_game()` 6 人局初始化，生成 `GameState`、`TruthState`、存活列表和初始公共事件
- `app/engine/death.py` — `kill_player()` 玩家死亡处理，更新状态、公共事件，校验存在性与存活
- `app/engine/vote.py` — `Vote` / `VoteResult` Pydantic 模型，`tally_votes()` 投票统计（平票处理），`apply_vote_result()` 执行放逐
- `app/engine/wincheck.py` — `check_winner()` 胜负判定（好人胜：狼全死；狼人胜：神全死或民全死）
- `app/engine/resolver.py` — `NightActionSet` / `NightResult` Pydantic 模型，`resolve_night()` 最小夜间结算（狼杀、女巫救/毒、预言家查验）
- `app/engine/__init__.py` — 统一导出
- `tests/test_engine.py` — 覆盖 kill_player、投票统计/平票/无效票、胜负判定、夜间结算

规则保证：
- 6 人预设可初始化为完整 `GameState`
- 只能杀存活玩家，不存在座位号抛异常
- 死亡玩家/无投票权玩家投票被忽略
- 弃票（target=None）不计数
- 最高票唯一放逐，平票不放逐且记录 tied_seats
- 同玩家被杀且被毒只生成一次死亡事件
- 女巫救中狼人杀目标则该玩家不死

### 里程碑 2C-3：基础 Agent 输出结构与中文 LLM 调用 ✅

**状态**：已完成各身份 Agent 的结构化输出、中文提示词、Mock LLM 测试。

已交付：
- `app/agents/schemas.py` — Agent 决策 Pydantic schema（`ActionType` enum、`SpeakAction`、`VoteAction`、`WerewolfKillAction`、`SeerCheckAction`、`WitchAction`、`AgentDecision` 判别联合体）
- `app/agents/prompts.py` — 中文系统提示词模块（基础提示词 + 狼人/预言家/女巫/平民角色提示词），所有提示词使用中文，强调信息隔离与 JSON 输出
- `app/agents/base_agent.py` — `BaseAgent` 基类，接收 `LLMClient` + `PlayerView`，构造中文 messages，调 `chat_json(...)`，解析 JSON 为 `AgentDecision`，校验动作在 `available_actions` 中，校验失败抛 `AgentDecisionError`
- `app/agents/werewolf_agent.py` — 狼人 Agent（继承 `BaseAgent`）
- `app/agents/seer_agent.py` — 预言家 Agent（继承 `BaseAgent`）
- `app/agents/witch_agent.py` — 女巫 Agent（继承 `BaseAgent`）
- `app/agents/villager_agent.py` — 平民 Agent（继承 `BaseAgent`）
- `app/agents/factory.py` — Agent 工厂，根据 `Role` 创建对应 Agent 实例，不支持角色抛 `ValueError`
- `app/agents/__init__.py` — 统一导出公共类
- `tests/test_agents.py` — 覆盖 schema 序列化、中文提示词断言、Mock LLM 合法/非法 JSON、动作不在可用空间被拒绝、prompt 不含 truth_state、factory 四种 MVP 角色、中文发言内容

Agent 调用约定：
- Agent 输入仅使用 `PlayerView`，不直接读取 `GameState` / `TruthState`
- `_build_user_message()` 仅序列化 `PlayerView` 字段，信息隔离由设计保证
- 所有角色提示词使用中文，要求返回 JSON、发言内容中文、不声称知道不可见身份

### 里程碑 2C-4：Runner / LangGraph 雏形 ✅

**状态**：已完成 6 人局对局 runner 与 LangGraph 主流程雏形。

已交付：
- `app/graph/main_graph.py` — Runner 核心模块：Phase 函数（`run_night_phase`、`run_day_phase`、`run_vote_phase`）、循环函数（`run_one_cycle`、`run_until_finished`）、LangGraph 图构建（`build_main_graph` + `GraphState` TypedDict）
- `app/graph/__init__.py` — 统一导出 runner 公共接口
- `tests/test_runner.py` — 覆盖夜晚狼杀/女巫救/女巫毒、狼人多数票+平票打破、白天中文发言事件、投票放逐/平票不放逐、胜负终局 phase=ended、信息隔离验证、LangGraph 编译/调用

Runner 核心约定：
- 所有阶段函数接受 `GameState` + `dict[int, Agent]`，Agent 只需实现 `decide(view: PlayerView) -> AgentDecision` 协议
- 夜晚阶段：依次收集狼人击杀（多数票，平票取最小座位号）→ 预言家查验 → 女巫救/毒（女巫通过公共事件获知被杀目标），调用 `resolve_night()` 结算，写入 `night_resolved` 事件
- 白天阶段：存活玩家按座位顺序发言，每条发言写入 `speech` 事件（含 `seat_no`、`content`、`reasoning_summary`）
- 投票阶段：存活且可投票玩家依次投票，调用 `tally_votes()` + `apply_vote_result()`，写入 `vote_cast` + `vote_resolved` 事件
- 每阶段结束后调用 `check_winner()`，若胜负已定则 `phase=ended`
- LangGraph `build_main_graph()` 返回可编译/调用的 StateGraph（nodes: night/day/vote，conditional routing: night→day→vote→night|ended）
- 测试全部使用 FakeAgent 脚本 Agent，不调用真实 LLM

### 里程碑 2：6 人局 MVP

**目标**：跑通完整狼人杀对局流程的最小闭环。

- ✅ 实现 `GameState` schema（`PublicState`、`TruthState`）- 已在 2B 完成
- ✅ 实现 `ViewBuilder`，按玩家身份构建可见视图 - 已在 2C-1 完成
- ✅ 实现 6 人局规则引擎（身份分配、夜晚结算、投票放逐、胜负判定）- 已在 2C-2 完成
- ✅ 实现 LangGraph 主流程图（夜晚子图 + 白天子图）- 已在 2C-4 完成
- ✅ 实现基础 Agent（狼人、预言家、女巫、平民）- 已在 2C-3 完成
- ✅ 接入百炼 `qwen-plus` 模型 - 已在 2A 完成
- ✅ 实现结构化日志记录 - 已在 2C-4 完成（公共事件写入）
- ✅ 创建 `.env.example` - 已在 2A 完成

**下一步建议（里程碑 3）**：API 层与日志持久化 — 通过 FastAPI 暴露对局接口，支持 HTTP 创建/查看对局，WebSocket 实时推送对局事件，数据库模型（SQLAlchemy + SQLite），对局日志持久化。

注意：所有 Agent 提示词和发言内容均使用中文，后续 Agent 扩展（猎人、白痴、守卫等）也必须遵循此约定。

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
