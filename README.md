# Werewolf Agent Team

一个可以真的跑起来玩的 AI 狼人杀实验场：让多个 Agent 围坐圆桌推理、发言、投票，也可以把真人玩家混进局里，和 AI 一起互相怀疑。

这个项目适合你用来体验：

- 多 Agent 博弈和长期上下文压缩
- 规则引擎与 LLM 决策解耦
- 狼人杀中的信息隔离、私有视角、结构化日志
- 真人 + AI 混战的 Web 交互
- Qwen / DashScope 模型驱动的中文发言与推理

## 现在能玩什么

- **6 人 / 12 人局**：支持 6 人 MVP 和 12 人标准板。
- **纯 AI 对战**：脚本 Agent 可离线跑通，Qwen Agent 可调用真实大模型。
- **人机混战**：创建对局时选择真人席位，系统生成玩家入口链接。
- **12 人标准流程**：预言家、女巫、猎人、白痴、警长竞选、警长 PK、白天投票 PK。
- **玩家私有视角**：玩家页面只看到自己身份、自己可行动作、公共信息，不暴露真相状态。
- **观战控制台**：圆桌座位、发言记录、系统事件、运行控制、WebSocket 实时刷新。
- **结构化事件日志**：所有关键动作都写入可审计事件，方便调试和复盘。
- **Seat Token**：真人座位链接带 token，后端只持久化 hash，避免只靠座位号访问他人视角。

## 快速开始

### 1. 后端

需要 Python 3.11+。

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"

# 可选：只有使用 Qwen Agent 时才需要
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

后端启动后：

- API 文档：http://127.0.0.1:8001/docs
- 健康检查：http://127.0.0.1:8001/health

### 2. 前端

需要 Node.js 20+。

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

打开：http://127.0.0.1:5173

前端默认连接 `http://127.0.0.1:8001`。如果后端地址不同：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173
```

## 第一次体验建议

1. 打开控制台页面。
2. 选择 **6 人** 或 **12 人**。
3. Agent 先选 **脚本**，这样不用 API Key 也能立刻跑。
4. 勾选 1-2 个真人席位，创建人机混战。
5. 复制玩家入口链接，在新窗口打开玩家页面。
6. 点击「推进到等待/结束」，当轮到真人时，在玩家页面提交行动。
7. 熟悉流程后，再切到 **Qwen**，观察大模型发言和投票逻辑。

## 使用 Qwen / DashScope

本项目使用阿里云百炼 DashScope 的 OpenAI 兼容接口。

```bash
cp .env.example .env
```

然后在 `.env` 中配置：

```bash
DASHSCOPE_API_KEY=your-api-key-here
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
```

也可以在创建对局时指定模型：

```bash
curl -X POST http://127.0.0.1:8001/games \
  -H "Content-Type: application/json" \
  -d '{"player_count": 12, "agent_mode": "llm", "model": "qwen3.5-27b"}'
```

默认 `scripted` 模式不会调用真实大模型。

## API 快速体验

### 创建 6 人局

```bash
curl -X POST http://127.0.0.1:8001/games \
  -H "Content-Type: application/json" \
  -d '{"player_count": 6}'
```

### 创建 12 人人机混战

```bash
curl -X POST http://127.0.0.1:8001/games \
  -H "Content-Type: application/json" \
  -d '{"player_count": 12, "human_seats": [1, 7]}'
```

返回里的 `human_seat_links` 会包含玩家入口：

```text
/play/{game_id}/{seat_no}?token=...
```

### 推进对局

```bash
curl -X POST http://127.0.0.1:8001/games/{game_id}/run-cycle
```

如果轮到真人操作，响应中会出现：

```json
{
  "runtime_state": {
    "pending_human_action": {
      "seat_no": 1,
      "action_type": "vote",
      "available_actions": ["vote"]
    }
  }
}
```

### 查询玩家视角

```bash
curl http://127.0.0.1:8001/games/{game_id}/players/{seat_no}/view \
  -H "X-Seat-Token: {token}"
```

### 提交真人行动

```bash
curl -X POST http://127.0.0.1:8001/games/{game_id}/players/{seat_no}/actions \
  -H "Content-Type: application/json" \
  -H "X-Seat-Token: {token}" \
  -d '{
    "action": {"action_type": "speak", "content": "我先听后置位发言。"},
    "reasoning_summary": ""
  }'
```

### 运行到结束

```bash
curl -X POST http://127.0.0.1:8001/games/{game_id}/run-until-finished \
  -H "Content-Type: application/json" \
  -d '{"max_cycles": 50}'
```

### WebSocket 事件

```text
ws://127.0.0.1:8001/ws/games/{game_id}/events
```

## 测试

```bash
.venv/bin/python -m pytest
```

前端构建：

```bash
cd frontend
npm run build
```

## 项目结构

```text
app/
  agents/      Agent 决策与 LLM 调用
  api/         FastAPI 路由与 WebSocket
  config/      规则、角色板子、环境配置
  engine/      狼人杀规则引擎
  graph/       纯 AI runner 与人机混战 runner
  state/       GameState、PlayerView、信息隔离
frontend/
  src/         React 控制台与玩家页面
tests/         后端回归测试
```

## 安全说明

- `.env`、`.env.local`、数据库文件、虚拟环境、前端依赖都已加入 `.gitignore`。
- 仓库只应该提交 `.env.example` 这类模板，不要提交真实 API Key。
- 真人座位 token 只在创建对局时明文返回；持久化状态中保存的是 hash。
- 玩家接口会校验 `X-Seat-Token` 或 `?token=`，避免知道座位号就能查看他人视角。

## 当前限制

- 语音转文字还未实现，目前玩家通过按钮和文本提交行动。
- 12 人局已经支持警长/PK，但守卫板子仍可继续扩展。
- 公网部署时需要配置前端 `VITE_API_BASE_URL`，并根据部署域名调整后端 CORS。
- 这是实验项目，不建议直接用于高并发生产环境。

## 路线图

- 控制台身份显示/隐藏切换，让观战者可以自己猜身份。
- 真人玩家自动刷新和更完整的移动端体验。
- 语音输入：浏览器录音 + STT 服务 + 文本确认后提交。
- 更多板子：9 人局、守卫局、更多角色扩展。
- 更细的赛后复盘：时间线、阵营视角、Agent 记忆摘要对比。

欢迎开局，看看 AI 到底会不会悍跳。
