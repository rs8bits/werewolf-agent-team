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
