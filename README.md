# Werewolf Agent Team

基于 LangGraph 的多 Agent 狼人杀博弈系统。

## 快速开始

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/uvicorn app.main:app --reload
```

PyCharm 可直接选择项目目录下的 `.venv/bin/python` 作为解释器。

## 测试

```bash
.venv/bin/python -m pytest
```
