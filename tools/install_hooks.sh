#!/usr/bin/env bash
# 装本地 pre-commit 闸门：提交前跑 tools/check_skills.py，不过就拦下。
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
hook="$root/.git/hooks/pre-commit"
cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
exec python3 "$(git rev-parse --show-toplevel)/tools/check_skills.py"
HOOK
chmod +x "$hook"
echo "已装 $hook（撤销：rm $hook）"
