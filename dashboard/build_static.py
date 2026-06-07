#!/usr/bin/env python3
"""
生成静态快照 dashboard/index.html —— 双击即开、零依赖、无需 Flask 后端。

做法：复用 app.py 的数据函数，把 /api/skills、/api/docs、/api/data、/api/crons
四个接口的 JSON 烘焙进 HTML，替换掉前端的 fetch 调用并关闭 30s 轮询。
数据均为已脱敏的演示数据。

    python3 dashboard/build_static.py   →   dashboard/index.html
"""
import json
from pathlib import Path

import app as A  # 复用 app.py 的 HTML 模板与数据函数

OUT = Path(__file__).parent / "index.html"

# 仅这些文档会被前端真正渲染（架构页 + 管家档案页）。
# 其余 DOC_FILES（soul/identity/user/tools/heartbeat）不展示，
# 不内联——既减体积，也避免把未展示文档的内容（含本机绝对路径）烘焙进文件。
DISPLAYED_DOCS = [
    "design", "readme", "agents",
    "sk_calendar", "sk_food", "sk_entertain", "sk_travel",
    "sk_booking", "sk_review", "sk_scheduler",
]


def build_payloads():
    skills = A.load_all_skills()
    docs = {k: A.load_doc(k) for k in DISPLAYED_DOCS}
    crons = A.parse_crons()
    counts, last_used = A.get_skill_stats()
    data = {
        "time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "weather": A.get_weather_data(),
        "preferences": A.get_preferences(),
        "recent": A.get_recent(),
        "skill_counts": counts,
        "skill_last_used": last_used,
        "cache": A.get_cache_stats(),
    }
    return skills, docs, data, crons


# ── 前端改造：把 fetch 换成内联常量，去掉轮询 ──────────────────
FETCH_BLOCK = """  const [skills, docs, data, crons] = await Promise.all([
    fetch('/api/skills').then(r=>r.json()),
    fetch('/api/docs').then(r=>r.json()),
    fetch('/api/data').then(r=>r.json()),
    fetch('/api/crons').then(r=>r.json()),
  ]);"""

POLL_BLOCK = """  setInterval(async()=>{
    const d = await fetch('/api/data').then(r=>r.json());
    renderWeather(d.weather); renderPrefs(d.preferences);
    renderCache(d.cache); renderRecent(d.recent||[]);
  }, 30000);"""


def main():
    skills, docs, data, crons = build_payloads()
    html = A.HTML

    def j(obj):
        return json.dumps(obj, ensure_ascii=False)

    inline = (
        "  const skills = " + j(skills) + ";\n"
        "  const docs = " + j(docs) + ";\n"
        "  const data = " + j(data) + ";\n"
        "  const crons = " + j(crons) + ";"
    )

    assert FETCH_BLOCK in html, "fetch 块未匹配——app.py 结构可能已改，请同步更新本脚本"
    assert POLL_BLOCK in html, "轮询块未匹配——app.py 结构可能已改，请同步更新本脚本"

    html = html.replace(FETCH_BLOCK, inline)
    html = html.replace(POLL_BLOCK, "  // 静态快照：无后端轮询")

    # 角标提示这是静态快照
    html = html.replace("实时运行中", "静态快照")

    # 安全网：脱敏任何残留的本机绝对路径（用户名/家目录），
    # 把 .../local-life-butler 收敛为项目相对根，其余家目录用 ~ 代替。
    html = html.replace(str(A.ROOT), ".")
    html = html.replace(str(Path.home()), "~")

    OUT.write_text(html, encoding="utf-8")
    print(f"已生成静态快照: {OUT}")
    print(f"  技能: {len(skills)} 个 | Cron: {len(crons)} 条 | "
          f"近期对话: {len(data.get('recent', []))} 条 | "
          f"天气: {data.get('weather', {}).get('city', '—')}")


if __name__ == "__main__":
    main()
