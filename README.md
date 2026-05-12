# Werewolf Agent Team

基于 LangGraph 的多 Agent 狼人杀博弈系统。

## 快速开始

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
cp .env.example .env
# 编辑 .env 填入你的 DASHSCOPE_API_KEY
.venv/bin/uvicorn app.main:app --reload
```

启动后访问：
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

## API 体验（里程碑 3）

本项目提供完整的 REST API 和 WebSocket，使用内置的脚本 Agent（不调用真实 LLM）：

### 创建对局
```bash
curl -X POST http://127.0.0.1:8000/games \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 创建 12 人标准板
```bash
curl -X POST http://127.0.0.1:8000/games \
  -H "Content-Type: application/json" \
  -d '{"player_count": 12}'
```

### 使用 Qwen Agent 创建对局
```bash
curl -X POST http://127.0.0.1:8000/games \
  -H "Content-Type: application/json" \
  -d '{"player_count": 12, "agent_mode": "llm", "model": "qwen3.5-27b"}'
```

> `agent_mode="llm"` 需要本地 `.env` 或环境变量里设置 `DASHSCOPE_API_KEY`。默认 `scripted` 模式不会调用真实大模型。

### 运行一轮
```bash
curl -X POST http://127.0.0.1:8000/games/{game_id}/run-cycle
```

### 运行至结束
```bash
curl -X POST http://127.0.0.1:8000/games/{game_id}/run-until-finished \
  -H "Content-Type: application/json" \
  -d '{"max_cycles": 50}'
```

### 查询对局状态
```bash
curl http://127.0.0.1:8000/games/{game_id}
```

### 查询事件日志
```bash
curl http://127.0.0.1:8000/games/{game_id}/events
```

### WebSocket 事件快照
```
ws://127.0.0.1:8000/ws/games/{game_id}/events
```

### 运行完整体验流程
```bash
# 1) 创建对局
GAME=$(curl -s -X POST http://127.0.0.1:8000/games -H "Content-Type: application/json" -d '{}')
GAME_ID=$(echo $GAME | python -c "import sys,json; print(json.load(sys.stdin)['game_id'])")

# 2) 运行一轮看看
curl -s -X POST http://127.0.0.1:8000/games/$GAME_ID/run-cycle | python -m json.tool

# 3) 继续跑到结束
curl -s -X POST http://127.0.0.1:8000/games/$GAME_ID/run-until-finished \
  -H "Content-Type: application/json" \
  -d '{"max_cycles": 50}' | python -m json.tool

# 4) 查看事件日志
curl -s http://127.0.0.1:8000/games/$GAME_ID/events | python -m json.tool
```

### Qwen smoke 脚本
```bash
.venv/bin/python scripts/qwen_smoke_game.py --model qwen3.5-27b --player-count 6 --cycles 1
```

脚本只在显式运行时调用真实模型，不会打印 API Key。为控制费用，默认只跑 6 人 1 轮。

## 配置大模型 API Key

本项目使用阿里云百炼（DashScope）通义千问（Qwen）系列模型。

1. 复制模板：`cp .env.example .env`
2. 打开 `.env`，将 `DASHSCOPE_API_KEY=your-api-key-here` 替换为你的真实 Key
   - 获取地址：https://dashscope.console.aliyun.com/apiKey
3. `.env` 已在 `.gitignore` 中，不会被提交到 Git

## PyCharm 配置

选择项目目录下的 `.venv/bin/python` 作为项目解释器：

- `Preferences → Project → Python Interpreter → Add Local Interpreter`
- 选择 `Existing`，路径指向 `<项目根目录>/.venv/bin/python`

## 测试

```bash
.venv/bin/python -m pytest
```

## 前端观战台

```bash
# 后端（前端默认连接 8001）
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001

# 前端
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

打开：http://127.0.0.1:5173

观战台会通过 WebSocket 连接 `/ws/games/{game_id}/events`，运行对局时事件会逐条推送到圆桌和发言顺序列表，不必等 HTTP 请求完成后才刷新。

如需连接其他后端地址：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173
```
