# CLAUDE.md

## Dashboard 重启

每次修改 `dashboard/app.py` 后需手动重启服务：

```bash
ps aux | grep "app.py" | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null; sleep 0.5 && python3 ~/.openclaw/workspace/local-life-butler/dashboard/app.py &
```

访问地址：http://localhost:5050

## 文件新鲜度

以下文件可能被 OpenClaw native agent 或手动修改：
- `skills/*/SKILL.md`
- `skills/*/scripts/*.py`
- `config/*.json`
- `AGENTS.md` / `../SOUL.md` / `../AGENTS.md`

在编辑这些文件之前，必须先用 Read 工具重新读取最新内容。
