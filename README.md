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
