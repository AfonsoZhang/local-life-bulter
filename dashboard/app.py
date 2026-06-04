#!/usr/bin/env python3
"""
生活管家 Dashboard — 全文档可视化
python3 dashboard/app.py  →  http://localhost:5050
"""

import json, re, sys, os
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "dashboard"))

from amap_api import get_cache_stats
from weather import get_weather
from md_render import render as md_render, extract_sections

app = Flask(__name__)
CONFIG = ROOT / "config"
SKILLS_DIR = ROOT / "skills"

# ── SKILL.md 解析 ──────────────────────────────────────────
def parse_skill_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    name, description, emoji = "", "", ""
    if fm_match:
        fm = fm_match.group(1)
        m = re.search(r"^name:\s*(.+)$", fm, re.M); name = m.group(1).strip() if m else ""
        m = re.search(r"^description:\s*(.+)$", fm, re.M); description = m.group(1).strip() if m else ""
        m = re.search(r'"emoji"\s*:\s*"([^"]+)"', fm); emoji = m.group(1) if m else ""

    def section(h):
        m = re.search(rf"## {re.escape(h)}\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        return m.group(1).strip() if m else ""

    trigger_raw = section("Trigger")
    kws_raw = re.findall(r"[：:]\s*(.+)", trigger_raw)
    trigger_keywords = re.split(r"[、，,\s]+", kws_raw[0]) if kws_raw else []
    trigger_keywords = [k.strip() for k in trigger_keywords if k.strip()]

    params = []
    for line in section("Input Parameters").splitlines():
        m = re.match(r"^[-*]\s+`?(\w+)`?\s*\(([^)]+)\)[：:]\s*(.+)", line)
        if m: params.append({"name": m.group(1), "type": m.group(2).strip(), "desc": m.group(3).strip()})

    commands = []
    for block in re.findall(r"```bash\n(.*?)```", section("Script"), re.DOTALL):
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("#"):
                commands.append({"type": "comment", "text": line[1:].strip()})
            elif line:
                short = re.sub(r"\{baseDir\}/\.\./core/", "core/", line)
                short = re.sub(r"\{baseDir\}/scripts/", "scripts/", short)
                commands.append({"type": "cmd", "text": short})

    multiturn = []
    for line in section("Multi-turn Support").splitlines():
        m = re.match(r'^[-*]?\s*[「""](.+?)[」""]\s*[→＞>]+\s*(.+)', line)
        if m: multiturn.append({"input": m.group(1).strip(), "action": m.group(2).strip()})

    output_items = [l.lstrip("-* ").strip() for l in section("Output").splitlines()
                    if l.strip().startswith(("-","*","•")) and l.strip()[1:].strip()]
    constraints = [l.lstrip("-* ").strip() for l in section("Constraints").splitlines()
                   if l.strip().startswith(("-","*","•")) and l.strip()[1:].strip()]

    broadcast_cmds = []
    bc = re.search(r"## Broadcast.*?\n```bash\n(.*?)```", text, re.DOTALL)
    if bc:
        for line in bc.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("#"):
                broadcast_cmds.append({"type": "comment", "text": line[1:].strip()})
            elif line:
                broadcast_cmds.append({"type": "cmd", "text": re.sub(r"\{baseDir\}/scripts/", "scripts/", line)})

    return {"name": name, "description": description, "emoji": emoji,
            "trigger_keywords": trigger_keywords, "params": params,
            "commands": commands, "multiturn": multiturn,
            "output_items": output_items, "constraints": constraints,
            "has_wiki": "wiki_image" in text, "has_web_search": "web_search" in text,
            "broadcast_cmds": broadcast_cmds}

def load_all_skills():
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        md = d / "SKILL.md"
        if md.exists():
            try: skills.append(parse_skill_md(md))
            except Exception as e: skills.append({"name": d.name, "error": str(e)})
    return skills

# ── 文档解析 ───────────────────────────────────────────────
DOC_FILES = {
    "design":        (ROOT / "DESIGN.md",                              "🏗 设计文档"),
    "soul":          (ROOT.parent / "SOUL.md",                         "🧬 灵魂"),
    "agents":        (ROOT / "AGENTS.md",                              "⚙️ 运行时约束位置"),
    "identity":      (ROOT / "IDENTITY.md",                            "🪪 身份档案"),
    "user":          (ROOT / "USER.md",                                "👤 用户档案"),
    "tools":         (ROOT / "TOOLS.md",                               "🔧 工具备注"),
    "heartbeat":     (ROOT / "HEARTBEAT.md",                           "💓 心跳任务"),
    "readme":        (ROOT / "README.md",                              "📖 项目说明"),
    "sk_calendar":   (ROOT / "skills/calendar/SKILL.md",               "📅 calendar"),
    "sk_food":       (ROOT / "skills/food-finder/SKILL.md",            "🍣 food-finder"),
    "sk_entertain":  (ROOT / "skills/entertainment/SKILL.md",          "🎭 entertainment"),
    "sk_travel":     (ROOT / "skills/travel-planner/SKILL.md",         "🗺️ travel-planner"),
    "sk_booking":    (ROOT / "skills/booking/SKILL.md",                "📋 booking"),
    "sk_review":     (ROOT / "skills/review/SKILL.md",                 "💬 review"),
    "sk_scheduler":  (ROOT / "skills/scheduler/SKILL.md",              "🧭 scheduler"),
}

def load_doc(key: str) -> dict:
    path, label = DOC_FILES[key]
    if not path.exists():
        return {"key": key, "label": label, "sections": [], "full_html": ""}
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    sections = extract_sections(text)
    full_html = md_render(text)
    return {"key": key, "label": label, "sections": sections, "full_html": full_html}

# ── 场景编排 ───────────────────────────────────────────────
SCENARIOS = [
    {"id":"weekend","emoji":"🗓","title":"周末出行规划","color_cls":"s0",
     "query":"「周六带女朋友出去玩，预算300，帮我安排一天」",
     "steps":[{"emoji":"📅","label":"日历管理","action":"查询周六空闲时段"},
              {"emoji":"🌤","label":"天气服务","action":"获取周六天气预报"},
              {"emoji":"🎭","label":"娱乐活动","action":"推荐景点/活动"},
              {"emoji":"🍣","label":"美食推荐","action":"附近餐厅推荐"},
              {"emoji":"🗺️","label":"出行规划","action":"规划景点→餐厅路线"}]},
    {"id":"dinner","emoji":"🍜","title":"今晚吃什么","color_cls":"s1",
     "query":"「想吃日料，不要太贵，最好安静一点」",
     "steps":[{"emoji":"🌤","label":"天气服务","action":"判断适合外出"},
              {"emoji":"🍣","label":"美食推荐","action":"过滤日料+安静+预算"},
              {"emoji":"🗺️","label":"出行规划","action":"推荐去餐厅路线"},
              {"emoji":"🧠","label":"记忆系统","action":"记录本次选择偏好"}]},
    {"id":"morning","emoji":"☀️","title":"早安播报","color_cls":"s2",
     "query":"「每天8点自动推送今日安排」",
     "steps":[{"emoji":"🌤","label":"天气服务","action":"获取今日/明日天气"},
              {"emoji":"📅","label":"日历管理","action":"读取今日所有日程"},
              {"emoji":"🧠","label":"记忆系统","action":"读取用户偏好提示"},
              {"emoji":"📢","label":"早安播报","action":"生成并发送播报消息"}]},
    {"id":"event","emoji":"🎟","title":"找个活动去","color_cls":"s3",
     "query":"「周末有什么好玩的，天气好就户外，天气差就室内」",
     "steps":[{"emoji":"🌤","label":"天气服务","action":"预判周末天气"},
              {"emoji":"🎭","label":"娱乐活动","action":"天气联动筛选活动"},
              {"emoji":"📡","label":"高德地图","action":"获取活动地点POI"},
              {"emoji":"🗺️","label":"出行规划","action":"规划前往路线"},
              {"emoji":"📖","label":"Wikipedia","action":"附上地点图片简介"}]},
]

# ── 运行数据 ───────────────────────────────────────────────
def _load(p):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except: return {}

def get_skill_stats():
    counts, last_used = {}, {}
    for item in _load(CONFIG/"history.json").get("interactions",[]):
        sk = item.get("skill","")
        counts[sk] = counts.get(sk,0)+1
        ts = item.get("timestamp","")
        if sk not in last_used or ts > last_used[sk]: last_used[sk] = ts[:10]
    return counts, last_used

def get_weather_data():
    try:
        city = _load(CONFIG/"preferences.json").get("user_preferences",{}).get("default_city","济南")
        w = get_weather(city)
        if w:
            return {"city":city,"weather":getattr(w,"weather",""),
                    "temperature":getattr(w,"temperature",""),
                    "wind":getattr(w,"winddirection","")+getattr(w,"windpower","")+"级",
                    "humidity":getattr(w,"humidity","")+"%"}
    except: pass
    return {}

def get_preferences():
    up = _load(CONFIG/"preferences.json").get("user_preferences",{})
    return {"cuisines":up.get("cuisine_preferences",[]),"transport":up.get("preferred_transport",[]),
            "interests":up.get("interests",[]),"budget":up.get("budget_level",""),
            "city":up.get("default_city",""),"location":up.get("default_location","")}

def get_recent(n=6):
    result = []
    for item in list(reversed(_load(CONFIG/"history.json").get("interactions",[])))[:n]:
        ts = item.get("timestamp","")
        recs = [r.get("name","") for r in item.get("recommendations",[])[:2]]
        result.append({"time":ts[11:16],"skill":item.get("skill",""),
                       "query":item.get("query",""),"recs":recs})
    return result

# 默认读脱敏示例；本地监控真实 cron 可设环境变量 BUTLER_CRON_FILE 指向实际 jobs.json
CRON_FILE = Path(os.environ.get("BUTLER_CRON_FILE", str(ROOT / "cron" / "jobs.example.json")))

CRON_EXPR_LABELS = {
    "0 9 * * *":                    "每天 09:00",
    "0 1 * * *":                    "每天 01:00",
    "0 9-23 * * *":                 "每天 09–23 点整点",
    "0 10,12,14,16,18,20,22,0 * * *": "每天 10/12/14/16/18/20/22/0 点",
}

def parse_crons() -> list:
    data = _load(CRON_FILE)
    jobs = data.get("jobs", [])
    result = []
    for job in jobs:
        sched = job.get("schedule", {})
        kind = sched.get("kind", "")
        if kind == "cron":
            expr = sched.get("expr", "")
            schedule_label = CRON_EXPR_LABELS.get(expr, expr)
            job_type = "循环"
        elif kind == "at":
            at = sched.get("at", "")
            # convert UTC to Beijing (+8)
            try:
                from datetime import timezone, timedelta
                dt_utc = datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                dt_bj  = dt_utc.astimezone(timezone(timedelta(hours=8)))
                schedule_label = dt_bj.strftime("%m/%d %H:%M")
            except Exception:
                schedule_label = at[:16]
            job_type = "一次性"
        else:
            schedule_label = kind
            job_type = "未知"

        # extract first line of message as description
        msg = job.get("payload", {}).get("message", "")
        desc = msg.strip().splitlines()[0][:60] if msg else ""

        result.append({
            "name":     job.get("name", ""),
            "enabled":  job.get("enabled", True),
            "type":     job_type,
            "schedule": schedule_label,
            "delete_after": job.get("deleteAfterRun", False),
            "desc":     desc,
        })
    return result

# ── API ────────────────────────────────────────────────────
@app.route("/api/skills")
def api_skills(): return jsonify(load_all_skills())

@app.route("/api/docs")
def api_docs(): return jsonify({k: load_doc(k) for k in DOC_FILES})

@app.route("/api/crons")
def api_crons(): return jsonify(parse_crons())

@app.route("/api/data")
def api_data():
    counts, last_used = get_skill_stats()
    return jsonify({"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "weather":get_weather_data(),"preferences":get_preferences(),
                    "recent":get_recent(),"skill_counts":counts,
                    "skill_last_used":last_used,"cache":get_cache_stats()})

# ── HTML ───────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>生活管家 · 控制台</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#cdd6e0;font-family:'PingFang SC','Microsoft YaHei',sans-serif}

/* ── Header ── */
.header{background:linear-gradient(135deg,#161b27,#1a2235);border-bottom:1px solid #21303f;padding:12px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.header h1{font-size:17px;color:#79b8ff;letter-spacing:2px;font-weight:500}
.clock{font-size:14px;color:#90caf9;font-variant-numeric:tabular-nums}
.dot{width:6px;height:6px;border-radius:50%;background:#4caf50;display:inline-block;animation:blink 2s infinite;margin-right:5px}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}

/* ── Tabs ── */
.tabs{display:flex;border-bottom:1px solid #1e2d3d;background:#111820;padding:0 28px;position:sticky;top:45px;z-index:99;overflow-x:auto}
.tab{padding:9px 18px;font-size:12px;color:#546e7a;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;transition:.15s}
.tab:hover{color:#90caf9}
.tab.active{color:#79b8ff;border-bottom-color:#79b8ff}

/* ── Pages ── */
.page{display:none;padding:18px 28px}
.page.active{display:block}
.section-label{font-size:10px;color:#546e7a;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.section-label::after{content:'';flex:1;height:1px;background:#1e2d3d}

/* ── Scenarios ── */
.scenarios{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.scenario-card{background:#111820;border:1px solid #1e2d3d;border-radius:10px;padding:16px;position:relative;overflow:hidden}
.scenario-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.s0::before{background:linear-gradient(90deg,#3ab57a,#2a8a5a)}
.s1::before{background:linear-gradient(90deg,#d4824a,#a05030)}
.s2::before{background:linear-gradient(90deg,#4a9aee,#2a6ab0)}
.s3::before{background:linear-gradient(90deg,#9a5aee,#6a30b0)}
.sc-title{font-size:14px;font-weight:600;color:#cdd6e0;margin-bottom:4px}
.sc-query{font-size:11px;color:#546e7a;margin-bottom:12px;padding-left:28px;font-style:italic}
.chain{display:flex;align-items:center;flex-wrap:wrap;gap:0}
.step-box{display:flex;flex-direction:column;align-items:center;background:#0d1117;border:1px solid #1e2d3d;border-radius:7px;padding:7px 9px;min-width:76px;transition:.15s}
.step-box:hover{border-color:#79b8ff;background:#131c25}
.step-emoji{font-size:15px;margin-bottom:3px}
.step-label{font-size:10px;color:#90caf9;font-weight:600;text-align:center}
.step-action{font-size:9px;color:#546e7a;text-align:center;margin-top:2px;line-height:1.3}
.arrow{color:#1e4060;font-size:15px;padding:0 3px}

/* ── Skill cards ── */
.skills-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.skill-card{background:#111820;border:1px solid #1e2d3d;border-radius:10px;overflow:hidden}
.skill-header{padding:14px 16px 10px;border-bottom:1px solid #1a2535;display:flex;gap:10px;align-items:flex-start}
.skill-emoji{font-size:24px;flex-shrink:0}
.skill-name{font-size:14px;font-weight:600;color:#cdd6e0;margin-bottom:3px}
.skill-desc{font-size:11px;color:#6a8aaa;line-height:1.5}
.skill-badges{display:flex;gap:5px;margin-top:6px;flex-wrap:wrap}
.badge{font-size:9px;padding:2px 6px;border-radius:7px;border:1px solid}
.badge-wiki{background:#0d1f2a;color:#4a9aee;border-color:#1a3a5a}
.badge-search{background:#1a1a0d;color:#aaaa4a;border-color:#3a3a1a}
.badge-mem{background:#0d2a1a;color:#4caf50;border-color:#1a4a2a}
.skill-body{padding:12px 16px}
.inner-tabs{display:flex;gap:0;margin-bottom:10px;border-bottom:1px solid #1a2535;overflow-x:auto}
.itab{font-size:10px;padding:4px 10px;color:#546e7a;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.itab:hover{color:#90caf9}
.itab.active{color:#79b8ff;border-bottom-color:#4a7aaa}
.ipanel{display:none}
.ipanel.active{display:block}
.kw-list{display:flex;flex-wrap:wrap;gap:4px}
.kw{font-size:10px;padding:2px 8px;border-radius:9px;background:#0d1f2a;color:#79b8ff;border:1px solid #1a3a5a}
.param-row{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid #161e28;font-size:11px}
.param-row:last-child{border:none}
.param-name{color:#90caf9;font-family:monospace;min-width:80px}
.param-type{color:#546e7a;font-size:10px;min-width:56px}
.param-desc{color:#8090a8}
.cmd-list{font-size:11px;font-family:monospace}
.cmd-comment{color:#546e7a;padding:5px 0 2px;font-style:italic}
.cmd-comment::before{content:'# '}
.cmd-line{background:#0d1117;border:1px solid #1a2535;border-radius:4px;padding:4px 9px;color:#79b8ff;margin-bottom:3px;word-break:break-all;line-height:1.5}
.mt-row{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid #161e28;font-size:11px}
.mt-row:last-child{border:none}
.mt-in{color:#cdd6e0;flex:1}
.mt-in::before{content:'「';color:#546e7a}
.mt-in::after{content:'」';color:#546e7a}
.mt-arr{color:#546e7a}
.mt-act{color:#8090a8;flex:1}
.md-items li{font-size:11px;color:#8090a8;padding:2px 0;list-style:none;padding-left:12px;position:relative}
.md-items li::before{content:'›';position:absolute;left:0;color:#546e7a}
.no-data{font-size:11px;color:#37474f;padding:4px 0}

/* ── Docs layout ── */
.doc-layout{display:grid;grid-template-columns:180px 1fr;gap:0;min-height:400px}
.doc-sidebar{border-right:1px solid #1e2d3d;padding:12px 0}
.doc-nav-item{padding:8px 16px;font-size:12px;color:#546e7a;cursor:pointer;border-left:2px solid transparent;transition:.15s}
.doc-nav-item:hover{color:#90caf9;background:#111820}
.doc-nav-item.active{color:#79b8ff;border-left-color:#79b8ff;background:#111820}
.doc-content{padding:16px 20px;overflow:auto}
.doc-sections{}
.doc-panel{display:none}
.doc-panel.active{display:block}

/* ── Markdown styles ── */
.md-h1{font-size:18px;color:#cdd6e0;margin:0 0 12px;font-weight:600}
.md-h2{font-size:14px;color:#90caf9;margin:16px 0 8px;font-weight:600;padding-bottom:4px;border-bottom:1px solid #1e2d3d}
.md-h3{font-size:13px;color:#7ab8f7;margin:12px 0 6px;font-weight:600}
.md-p{font-size:12px;color:#8090a8;line-height:1.7;margin-bottom:8px}
.md-list{padding-left:0;margin-bottom:10px}
.md-list li{font-size:12px;color:#8090a8;line-height:1.6;padding:2px 0 2px 16px;position:relative;list-style:none}
.md-list li::before{content:'›';position:absolute;left:0;color:#546e7a}
.md-table{width:100%;border-collapse:collapse;margin-bottom:12px;font-size:11px}
.md-table th{background:#1a2535;color:#90caf9;padding:6px 10px;text-align:left;border:1px solid #1e2d3d}
.md-table td{padding:5px 10px;border:1px solid #1a2535;color:#8090a8;vertical-align:top}
.md-table tr:hover td{background:#111820}
.code-block{background:#0a0f17;border:1px solid #1a2535;border-radius:6px;padding:12px;overflow-x:auto;margin-bottom:12px;font-size:11px;line-height:1.5}
.code-block code{color:#79b8ff;font-family:'JetBrains Mono','Fira Code',monospace;white-space:pre}
.inline-code{background:#1a2535;color:#f0a370;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:10px}
.md-blockquote{border-left:3px solid #3a7bd5;padding:6px 12px;background:#111820;margin-bottom:10px;font-size:12px;color:#7a9acc;font-style:italic}
.md-hr{border:none;border-top:1px solid #1e2d3d;margin:14px 0}
.md-link{color:#4a9aee;text-decoration:none}
strong{color:#c8d8f0}

/* ── Status panels ── */
.bottom-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:14px}
.panel{background:#111820;border:1px solid #1e2d3d;border-radius:10px;padding:14px}
.panel-title{font-size:10px;color:#546e7a;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px}
.w-temp{font-size:28px;color:#79b8ff;font-weight:200}
.w-desc{font-size:12px;color:#546e7a;margin-top:4px}
.w-row{display:flex;gap:14px;margin-top:8px}
.w-item{font-size:11px;color:#546e7a} .w-item b{color:#90caf9}
.rec-item{display:flex;gap:7px;padding:5px 0;border-bottom:1px solid #161e28;align-items:flex-start}
.rec-item:last-child{border:none}
.rec-time{font-size:10px;color:#37474f;font-family:monospace;min-width:34px;padding-top:1px}
.skill-pill{font-size:9px;padding:2px 5px;border-radius:7px;min-width:40px;text-align:center}
.sp-food{background:#0d2a1a;color:#4caf50;border:1px solid #1a4a2a}
.sp-travel{background:#0d1a2a;color:#4a7aaa;border:1px solid #1a304a}
.sp-entertainment{background:#1a0d2a;color:#9a4aee;border:1px solid #3a1a5a}
.sp-calendar{background:#2a2a0d;color:#aaaa4a;border:1px solid #4a4a1a}
.rec-q{font-size:11px;color:#b0c0d0}
.rec-r{font-size:10px;color:#37474f;margin-top:1px}
.cache-row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #161e28}
.cache-row:last-child{border:none}
.cache-k{font-size:11px;color:#546e7a}
.cache-v{font-size:12px;font-weight:600;color:#79b8ff;font-family:monospace}
.bar-wrap{height:3px;background:#161e28;border-radius:2px;margin-top:6px}
.bar-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,#3ab57a,#4a9aee);transition:width .6s}
.pref-row{display:flex;align-items:center;gap:7px;margin-bottom:6px}
.pref-label{font-size:10px;color:#546e7a;min-width:44px}
.tag{font-size:10px;padding:2px 7px;border-radius:9px;background:#111e2a;color:#7a9acc;border:1px solid #1a2d3d}

/* ── Cron table ── */
.cron-table{width:100%;border-collapse:collapse}
.cron-table th{font-size:10px;color:#546e7a;text-align:left;padding:5px 10px;border-bottom:1px solid #1e2d3d;letter-spacing:.5px;text-transform:uppercase}
.cron-table td{font-size:11px;padding:7px 10px;border-bottom:1px solid #161e28;vertical-align:middle}
.cron-table tr:last-child td{border:none}
.cron-table tr:hover td{background:#111820}
.cron-name{color:#cdd6e0;font-weight:500}
.cron-desc{color:#546e7a;font-size:10px;margin-top:2px}
.cron-sched{color:#79b8ff;font-family:monospace;font-size:11px}
.cron-type-loop{font-size:9px;padding:2px 7px;border-radius:8px;background:#0d2a1a;color:#4caf50;border:1px solid #1a4a2a}
.cron-type-once{font-size:9px;padding:2px 7px;border-radius:8px;background:#1a1a0d;color:#aaaa4a;border:1px solid #3a3a1a}
.cron-status-on{font-size:9px;padding:2px 7px;border-radius:8px;background:#0d2015;color:#4caf50;border:1px solid #1a4020}
.cron-status-off{font-size:9px;padding:2px 7px;border-radius:8px;background:#1a1015;color:#546e7a;border:1px solid #2a2025}
</style>
</head>
<body>
<div class="header">
  <h1>🏠 济南生活管家 · 控制台</h1>
  <div style="text-align:right;font-size:11px;color:#546e7a">
    <div class="clock" id="clock">--:--:--</div>
    <div><span class="dot"></span>实时运行中</div>
  </div>
</div>

<div class="tabs">
  <div class="tab active"  onclick="switchTab('orchestration',this)">🔗 场景编排</div>
  <div class="tab"         onclick="switchTab('skills',this)">📋 技能详情</div>
  <div class="tab"         onclick="switchTab('architecture',this)">🏗 架构设计</div>
  <div class="tab"         onclick="switchTab('identity',this)">🧬 管家档案</div>
  <div class="tab"         onclick="switchTab('status',this)">📊 运行状态</div>
</div>

<!-- 场景编排 -->
<div class="page active" id="page-orchestration">
  <div class="section-label">管家如何协调多工具完成复杂请求</div>
  <div class="scenarios" id="scenarios"></div>
</div>

<!-- 技能详情 -->
<div class="page" id="page-skills">
  <div class="section-label">技能详情 · 来自 SKILL.md</div>
  <div class="skills-grid" id="skills-grid"></div>
</div>

<!-- 架构设计 -->
<div class="page" id="page-architecture">
  <div class="doc-layout">
    <div class="doc-sidebar" id="arch-nav"></div>
    <div class="doc-content" id="arch-content"></div>
  </div>
</div>

<!-- 管家档案 -->
<div class="page" id="page-identity">
  <div class="doc-layout">
    <div class="doc-sidebar" id="ident-nav"></div>
    <div class="doc-content" id="ident-content"></div>
  </div>
</div>

<!-- 运行状态 -->
<div class="page" id="page-status">
  <div class="bottom-grid">
    <div class="panel"><div class="panel-title">🌤 实时天气</div><div id="weather"></div></div>
    <div class="panel"><div class="panel-title">🧠 用户画像</div><div id="prefs"></div></div>
    <div class="panel"><div class="panel-title">⚡ API 缓存</div><div id="cache"></div></div>
  </div>
  <div class="panel" style="margin-bottom:14px">
    <div class="panel-title">⏰ 定时任务（Cron）</div>
    <div id="crons"></div>
  </div>
  <div class="panel"><div class="panel-title">💬 近期对话</div>
    <div id="recent" style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px"></div>
  </div>
</div>

<script>
const SCENARIOS = """ + json.dumps(SCENARIOS, ensure_ascii=False) + r""";

// ── Nav ──
function switchTab(id, el) {
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('page-'+id).classList.add('active');
  el.classList.add('active');
}

// ── Inner skill tabs ──
function showInner(n, tab, el) {
  document.querySelectorAll('#sk-'+n+' .ipanel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('#sk-'+n+' .itab').forEach(t=>t.classList.remove('active'));
  document.getElementById('sk-'+n+'-'+tab).classList.add('active');
  el.classList.add('active');
}

// ── Doc nav ──
function showDoc(navId, contentId, key) {
  document.querySelectorAll('#'+navId+' .doc-nav-item').forEach(i=>i.classList.remove('active'));
  document.querySelectorAll('#'+contentId+' .doc-panel').forEach(p=>p.classList.remove('active'));
  document.querySelector('#'+navId+' [data-key="'+key+'"]').classList.add('active');
  const panel = document.getElementById('docpanel-'+key);
  if (panel) panel.classList.add('active');
}

// ── Scenarios ──
function renderScenarios() {
  document.getElementById('scenarios').innerHTML = SCENARIOS.map(s=>`
    <div class="scenario-card ${s.color_cls}">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span style="font-size:17px">${s.emoji}</span>
        <span class="sc-title">${s.title}</span>
      </div>
      <div class="sc-query">${s.query}</div>
      <div class="chain">
        ${s.steps.map((st,i)=>`
          <div style="display:flex;align-items:center">
            <div class="step-box">
              <div class="step-emoji">${st.emoji}</div>
              <div class="step-label">${st.label}</div>
              <div class="step-action">${st.action}</div>
            </div>
            ${i<s.steps.length-1?'<span class="arrow">›</span>':''}
          </div>`).join('')}
      </div>
    </div>`).join('');
}

// ── Skills ──
function renderSkills(skills) {
  document.getElementById('skills-grid').innerHTML = skills.map(sk=>{
    if(sk.error) return `<div class="skill-card" style="padding:14px;color:#f66">${sk.name}: ${sk.error}</div>`;
    const n = sk.name.replace(/-/g,'_');
    const badges = [
      sk.has_wiki?'<span class="badge badge-wiki">📖 Wiki图片</span>':'',
      sk.has_web_search?'<span class="badge badge-search">🔍 网页搜索</span>':'',
      '<span class="badge badge-mem">🧠 记忆学习</span>'
    ].filter(Boolean).join('');
    const triggerHtml = sk.trigger_keywords.length
      ? `<div class="kw-list">${sk.trigger_keywords.map(k=>`<span class="kw">${k}</span>`).join('')}</div>`
      : '<div class="no-data">—</div>';
    const paramsHtml = sk.params.length
      ? sk.params.map(p=>`<div class="param-row"><span class="param-name">${p.name}</span><span class="param-type">${p.type}</span><span class="param-desc">${p.desc}</span></div>`).join('')
      : '<div class="no-data">无必填参数</div>';
    const cmdsHtml = sk.commands.length
      ? sk.commands.map(c=>c.type==='comment'?`<div class="cmd-comment">${c.text}</div>`:`<div class="cmd-line">${c.text}</div>`).join('')
      : '<div class="no-data">—</div>';
    const mtHtml = sk.multiturn.length
      ? sk.multiturn.map(m=>`<div class="mt-row"><span class="mt-in">${m.input}</span><span class="mt-arr">→</span><span class="mt-act">${m.action}</span></div>`).join('')
      : '<div class="no-data">—</div>';
    const outHtml = sk.output_items.length?`<ul class="md-items">${sk.output_items.map(o=>`<li>${o}</li>`).join('')}</ul>`:'<div class="no-data">—</div>';
    const conHtml = sk.constraints.length?`<ul class="md-items">${sk.constraints.map(c=>`<li>${c}</li>`).join('')}</ul>`:'<div class="no-data">—</div>';
    const bcTab = sk.broadcast_cmds.length?`<div class="itab" onclick="showInner('${n}','bc',this)">播报</div>`:'';
    const bcPanel = sk.broadcast_cmds.length
      ? `<div class="ipanel" id="sk-${n}-bc"><div class="cmd-list">${sk.broadcast_cmds.map(c=>c.type==='comment'?`<div class="cmd-comment">${c.text}</div>`:`<div class="cmd-line">${c.text}</div>`).join('')}</div></div>` : '';
    return `<div class="skill-card" id="sk-${n}">
      <div class="skill-header">
        <div class="skill-emoji">${sk.emoji}</div>
        <div>
          <div class="skill-name">${sk.name}</div>
          <div class="skill-desc">${sk.description}</div>
          <div class="skill-badges">${badges}</div>
        </div>
      </div>
      <div class="skill-body">
        <div class="inner-tabs">
          <div class="itab active" onclick="showInner('${n}','trigger',this)">触发词</div>
          <div class="itab" onclick="showInner('${n}','params',this)">参数</div>
          <div class="itab" onclick="showInner('${n}','cmds',this)">命令</div>
          <div class="itab" onclick="showInner('${n}','mt',this)">多轮示例</div>
          <div class="itab" onclick="showInner('${n}','out',this)">输出</div>
          <div class="itab" onclick="showInner('${n}','con',this)">约束</div>
          ${bcTab}
        </div>
        <div class="ipanel active" id="sk-${n}-trigger">${triggerHtml}</div>
        <div class="ipanel" id="sk-${n}-params">${paramsHtml}</div>
        <div class="ipanel" id="sk-${n}-cmds"><div class="cmd-list">${cmdsHtml}</div></div>
        <div class="ipanel" id="sk-${n}-mt">${mtHtml}</div>
        <div class="ipanel" id="sk-${n}-out">${outHtml}</div>
        <div class="ipanel" id="sk-${n}-con">${conHtml}</div>
        ${bcPanel}
      </div>
    </div>`;
  }).join('');
}

// ── Docs ──
const ARCH_KEYS  = ['design','readme'];
const IDENT_KEYS = ['soul','agents','identity','user','tools','heartbeat'];

function buildDocNav(navId, contentId, docs, keys) {
  const nav = document.getElementById(navId);
  const content = document.getElementById(contentId);
  const EMPTY = """ + json.dumps(list({"identity","user","tools","heartbeat"}), ensure_ascii=False) + r""";
  nav.innerHTML = keys.map((k,i)=>`
    <div class="doc-nav-item${i===0?' active':''}" data-key="${k}" onclick="showDoc('${navId}','${contentId}','${k}')">
      ${docs[k].label}${EMPTY.includes(k)?'<span style="font-size:9px;color:#37474f;margin-left:4px">未填写</span>':''}
    </div>`).join('');
  content.innerHTML = keys.map((k,i)=>`
    <div class="doc-panel${i===0?' active':''}" id="docpanel-${k}">
      <div class="doc-sections">${docs[k].full_html||''}</div>
    </div>`).join('');
}

// ── Status ──
function renderWeather(w) {
  if(!w||!w.weather){document.getElementById('weather').innerHTML='<div style="color:#37474f;font-size:12px">暂无</div>';return}
  document.getElementById('weather').innerHTML=`<div class="w-temp">${w.temperature}°C</div><div class="w-desc">${w.city} · ${w.weather}</div><div class="w-row"><div class="w-item">💨 <b>${w.wind}</b></div><div class="w-item">💧 <b>${w.humidity}</b></div></div>`;
}
function renderPrefs(p){
  if(!p)return;
  document.getElementById('prefs').innerHTML=[['菜系',p.cuisines],['出行',p.transport],['兴趣',p.interests],['预算',[p.budget]],['位置',[p.city+' · '+p.location]]].map(([l,t])=>`<div class="pref-row"><span class="pref-label">${l}</span><div style="display:flex;flex-wrap:wrap;gap:3px">${(t||[]).filter(Boolean).map(x=>`<span class="tag">${x}</span>`).join('')}</div></div>`).join('');
}
function renderCache(c){
  if(!c)return;
  const rate=Math.round((c.hit_rate||0)*100);
  const saved=Math.round((c.hits||0)*0.35*10)/10;
  document.getElementById('cache').innerHTML=`<div class="cache-row"><span class="cache-k">命中率</span><span class="cache-v">${rate}%</span></div><div class="bar-wrap"><div class="bar-fill" style="width:${rate}%"></div></div><div style="height:5px"></div><div class="cache-row"><span class="cache-k">累计命中</span><span class="cache-v">${c.hits||0}次</span></div><div class="cache-row"><span class="cache-k">缓存条目</span><span class="cache-v">${c.size||0}/${c.max_size||512}</span></div><div class="cache-row"><span class="cache-k">节省耗时</span><span class="cache-v">~${saved}s</span></div>`;
}
function renderRecent(items){
  const PILL={'food-finder':'sp-food','travel-planner':'sp-travel','entertainment':'sp-entertainment','calendar':'sp-calendar'};
  const SHORT={'food-finder':'美食','travel-planner':'出行','entertainment':'娱乐','calendar':'日历'};
  if(!items.length){document.getElementById('recent').innerHTML='<div style="color:#37474f;font-size:11px">暂无</div>';return}
  document.getElementById('recent').innerHTML=items.map(it=>{
    const recs=it.recs.filter(Boolean).join('、');
    return `<div class="rec-item"><span class="rec-time">${it.time}</span><span class="skill-pill ${PILL[it.skill]||'sp-calendar'}">${SHORT[it.skill]||it.skill}</span><div><div class="rec-q">${it.query}</div>${recs?`<div class="rec-r">→ ${recs}</div>`:''}</div></div>`;
  }).join('');
}

function renderCrons(jobs) {
  const el = document.getElementById('crons');
  if (!jobs.length) { el.innerHTML='<div style="color:#37474f;font-size:11px">无任务</div>'; return; }
  el.innerHTML = `<table class="cron-table">
    <thead><tr><th>任务名称</th><th>触发时间</th><th>类型</th><th>状态</th></tr></thead>
    <tbody>${jobs.map(j=>`
      <tr>
        <td><div class="cron-name">${j.name}</div><div class="cron-desc">${j.desc}</div></td>
        <td><span class="cron-sched">${j.schedule}</span></td>
        <td><span class="${j.type==='循环'?'cron-type-loop':'cron-type-once'}">${j.type}${j.delete_after?' · 执行后删除':''}</span></td>
        <td><span class="${j.enabled?'cron-status-on':'cron-status-off'}">${j.enabled?'启用':'禁用'}</span></td>
      </tr>`).join('')}
    </tbody></table>`;
}

function tick(){document.getElementById('clock').textContent=new Date().toLocaleString('zh-CN',{hour12:false}).replace(/\//g,'-');}

async function init() {
  renderScenarios();
  tick(); setInterval(tick,1000);

  const [skills, docs, data, crons] = await Promise.all([
    fetch('/api/skills').then(r=>r.json()),
    fetch('/api/docs').then(r=>r.json()),
    fetch('/api/data').then(r=>r.json()),
    fetch('/api/crons').then(r=>r.json()),
  ]);

  renderSkills(skills);
  buildDocNav('arch-nav',  'arch-content',  docs, ['design','readme']);
  buildDocNav('ident-nav', 'ident-content', docs, ['agents','sk_calendar','sk_food','sk_entertain','sk_travel','sk_booking','sk_review','sk_scheduler']);
  renderWeather(data.weather);
  renderPrefs(data.preferences);
  renderCache(data.cache);
  renderCrons(crons||[]);
  renderRecent(data.recent||[]);

  setInterval(async()=>{
    const d = await fetch('/api/data').then(r=>r.json());
    renderWeather(d.weather); renderPrefs(d.preferences);
    renderCache(d.cache); renderRecent(d.recent||[]);
  }, 30000);
}
init();
</script>
</body>
</html>"""

@app.route("/")
def index(): return render_template_string(HTML)

if __name__ == "__main__":
    print("Dashboard: http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
