# TASKS.md

## 目标
基于 LangGraph 实现一个可配置的多 Agent 狼人杀系统，支持：
- 6 / 9 / 12 人局
- 12 人标准板（预女猎白）
- 后续扩展守卫、警长、人机混战
- 开局前配置每个 Agent 的能力画像（聪明程度、记忆能力、经验、模型档位、上下文档位等）
- 全程结构化日志
- 前端观战 UI
- 纯 AI 对战 / 人机混战

---

## 开发原则
- 规则引擎必须由代码实现，不能交给 LLM 裁决
- Agent 只能决策，不能修改规则
- 每个 Agent 必须严格信息隔离
- 所有 Agent 输出必须结构化
- 先做 MVP，再扩展复杂角色和玩法

---

## 里程碑 1：项目骨架初始化

### 任务 1.1：初始化项目目录
创建目录结构：

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
└── TASKS.md