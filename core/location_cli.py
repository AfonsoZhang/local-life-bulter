#!/usr/bin/env python3
"""location_cli.py — 对话式默认地址管理

替代传统 App「设置 → 位置管理」页面。位置有三种来源：
  confirmed → 用户明确告知，可当事实直接用
  ip_guess  → IP 定位猜测，搜索可用但必须向用户确认，禁止当事实陈述
  default   → 无信息，硬编码兜底，必须问用户

命令：
  status              查看当前位置状态（含来源）
  bootstrap           首次定位（IP 猜测，不覆盖已确认位置）
  bootstrap --force   强制重新 IP 定位（换城市场景）
  confirm "我在和谐广场"   用户确认/修正位置 → 标记 confirmed
  confirm --city 济南 --location 和谐广场

所有命令支持 --json 输出结构化结果。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amap_api import (
    get_location_state,
    bootstrap_location,
    confirm_location,
)


def cmd_status(as_json: bool):
    state = get_location_state()
    if as_json:
        print(json.dumps(state, ensure_ascii=False))
        return
    label = {
        "confirmed": "✅ 已确认（用户告知）",
        "ip_guess": "📍 IP 猜测（待确认）",
        "default": "⚙️ 默认兜底（未设置）",
    }.get(state["source"], state["source"])
    name = state["location_name"] or "（无具体地点）"
    print(f"当前位置：{state['city']} · {name}")
    print(f"来源：{label}")
    print(f"坐标：{state['center']}")
    if state["updated_at"]:
        print(f"更新于：{state['updated_at']}")


def cmd_bootstrap(force: bool, as_json: bool):
    result = bootstrap_location(force=force)
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    status = result["status"]
    if status == "confirmed":
        name = result["location_name"] or "（无具体地点）"
        print(f"已有确认位置：{result['city']} · {name}，直接使用，无需询问。")
    elif status == "guessed":
        prov = result.get("province", "")
        print(f"IP 猜测位置：{prov} {result['city']}")
        print("⚠️ 这是网络位置猜测，未确认。请向用户反问确认，禁止断言「你在XX」。")
        print(f"建议话术：看你的网络位置像是在{result['city']}，我先按这儿帮你找？也可以告诉我具体在哪个商圈。")
    else:  # need_ask
        print("IP 定位失败，需直接询问用户。")
        print("建议话术：你现在在哪个城市/商圈？告诉我我帮你找附近的。")


def cmd_confirm(args, as_json: bool):
    query = ""
    city = ""
    location_name = ""
    i = 0
    positional = []
    while i < len(args):
        if args[i] == "--city" and i + 1 < len(args):
            city = args[i + 1]
            i += 2
        elif args[i] == "--location" and i + 1 < len(args):
            location_name = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1
    if positional:
        query = " ".join(positional)

    result = confirm_location(query=query, city=city, location_name=location_name)
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    if result["status"] == "ok":
        name = result["location_name"] or "（无具体地点）"
        print(f"✅ 位置已确认：{result['city']} · {name}")
    else:
        print("❌ 无法解析位置，请让用户说得更具体（城市名或商圈名）。")


def main():
    args = sys.argv[1:]
    as_json = False
    if "--json" in args:
        as_json = True
        args = [a for a in args if a != "--json"]

    if not args or args[0] == "status":
        cmd_status(as_json)
    elif args[0] == "bootstrap":
        force = "--force" in args[1:]
        cmd_bootstrap(force, as_json)
    elif args[0] == "confirm":
        cmd_confirm(args[1:], as_json)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
