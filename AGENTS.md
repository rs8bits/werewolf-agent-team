# AGENTS.md

## 项目名称
Werewolf Agent Team

## 项目目标
基于 LangGraph 构建一个可配置的多 Agent 狼人杀系统，支持：
- 6 / 9 / 12 人局
- 开局前配置每个 Agent 的能力画像
- 纯 AI 对战 / 人机混战
- 结构化日志
- 前端观战 UI

---

## 你的角色
你是本项目的开发代理（Codex）。  

---

## 总体开发原则

### 1. 规则引擎与 Agent 决策解耦
- 游戏规则必须由代码实现
- LLM / Agent 只能做推理、发言、投票、技能选择
- 不允许把胜负裁决、夜间结算、投票统计交给 LLM

### 2. 严格信息隔离
- 每个 Agent 只能看到：
  - 公共信息
  - 自己身份
  - 自己记忆
  - 自己私有信息
  - 当前允许的行动空间
- 任何 Agent 不能直接访问完整真相状态

### 3. 所有输出必须结构化
- Agent 发言、投票、技能选择必须是 JSON / Pydantic 结构
- 禁止只返回自由文本作为主输出
- 所有关键节点必须写结构化日志

### 4. 先做 MVP，再做扩展
优先级：
1. 6 人局 MVP
2. LangGraph 主流程跑通
3. API 和日志
4. 12 人标准板（预女猎白）
5. 白痴 / 猎人
6. 守卫 / 警长
7. 人机混战
8. 前端观战 UI

### 5. 每次改动必须可运行
- 每次提交都必须保证项目能运行
- 禁止一次性大改导致系统长期不可用
- 优先产出可验证的小版本

---

## 固定技术选型
- Python 3.11+
- FastAPI
- LangGraph
- Pydantic
- SQLAlchemy
- SQLite（后续可换 PostgreSQL）
- React / Next.js（前端）

---

## 固定目录结构
```bash
werewolf-agent/
├── app/
│   ├── api/
│   ├── agents/
│   ├── config/
│   ├── engine/
│   ├── graph/
│   │   └── nodes/
│   ├── logging/
│   ├── state/
│   └── main.py
├── tests/
├── frontend/
├── README.md
├── PROJECT.md
├── TASKS.md
└── AGENTS.md





