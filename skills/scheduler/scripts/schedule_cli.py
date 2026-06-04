#!/usr/bin/env python3
"""schedule_cli.py — 智能排期器的 Echo 可调入口

把 core/scheduler.py（纯算法）包成一个普通 CLI 工具：Echo 用 exec 调用，传入候选活动/
餐厅的简单 JSON，拿回排好的时间线文本，再转发到微信。Echo 负责理解意图+搜候选+微信收发，
本工具只负责"算最优时间线"——不含任何 LLM。

设计要点：
- 输入是简单 JSON（坐标用 "lng,lat" 字符串即可），本 CLI 自动转成 dataclass
- 输出默认是微信友好文本；加 --json 输出结构化结果
- 坐标缺失也能跑（fallback 到默认出行时间），不会崩

输入 JSON 结构：
{
  "events": [
    {"name":"趵突泉","type":"outdoor","venue":"趵突泉公园",
     "location":"116.997,36.664","duration_min":90,"price_yuan":40,
     "rating":4.7,"description":"天下第一泉"}
  ],
  "lunch":  [{"name":"草包包子铺","cuisine":"面食","location":"117.01,36.67"}],
  "dinner": [{"name":"城南往事","cuisine":"鲁菜"}],
  "start_hour": 9
}

用法：
  python schedule_cli.py --input plan.json          # 从文件读
  echo '<json>' | python schedule_cli.py --input -   # 从 stdin 读
  python schedule_cli.py --input plan.json --json    # 结构化输出
  python schedule_cli.py --demo                      # 跑内置样例
"""
import sys
import os
import json
import argparse

# 算法实现（scheduler/schemas）放在共享的 core/，本 skill 只放 CLI 入口
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from schemas import Location, Restaurant, EntertainmentEvent
from scheduler import schedule_day, format_schedule


def _to_location(raw):
    """把多种坐标写法统一成 Location 对象（坐标是算法的核心输入）

    支持： "lng,lat" 字符串 / {"longitude":..,"latitude":..} / {"location":"lng,lat"} / None
    """
    if not raw:
        return None
    if isinstance(raw, str):
        return Location.from_amap(raw)
    if isinstance(raw, dict):
        if raw.get("longitude") is not None and raw.get("latitude") is not None:
            return Location(
                longitude=float(raw["longitude"]),
                latitude=float(raw["latitude"]),
                address=raw.get("address", ""),
            )
        if raw.get("location"):
            return Location.from_amap(raw["location"])
    return None


def _to_event(d: dict) -> EntertainmentEvent:
    return EntertainmentEvent(
        name=d.get("name", ""),
        type=d.get("type", ""),
        venue=d.get("venue", "") or d.get("name", ""),
        location=_to_location(d.get("location")),
        duration_min=int(d.get("duration_min", 120) or 120),
        price_yuan=int(d.get("price_yuan", 0) or 0),
        rating=float(d.get("rating", 0) or 0),
        description=d.get("description", ""),
    )


def _to_restaurant(d: dict) -> Restaurant:
    return Restaurant(
        name=d.get("name", ""),
        cuisine=d.get("cuisine", ""),
        rating=float(d.get("rating", 0) or 0),
        price_range=d.get("price_range", ""),
        location=_to_location(d.get("location")),
        zone=d.get("zone", ""),
        description=d.get("description", ""),
    )


def build_plan(payload: dict) -> dict:
    """把输入 JSON 转成 dataclass 并调度，返回 schedule_day 的结构化结果"""
    events = [_to_event(e) for e in payload.get("events", []) if e.get("name")]
    lunch = [_to_restaurant(r) for r in payload.get("lunch", []) if r.get("name")]
    dinner = [_to_restaurant(r) for r in payload.get("dinner", []) if r.get("name")]
    start_hour = int(payload.get("start_hour", 9) or 9)
    return schedule_day(events, lunch=lunch, dinner=dinner, start_hour=start_hour)


DEMO_PAYLOAD = {
    "events": [
        {"name": "趵突泉", "type": "outdoor", "venue": "趵突泉公园",
         "location": "116.997,36.664", "duration_min": 90, "price_yuan": 40,
         "rating": 4.7, "description": "天下第一泉"},
        {"name": "大明湖", "type": "outdoor", "venue": "大明湖景区",
         "location": "117.024,36.678", "duration_min": 120, "price_yuan": 0,
         "rating": 4.5, "description": "免费开放的城市湖泊公园"},
        {"name": "山东省博物馆", "type": "exhibition", "venue": "山东省博物馆",
         "location": "117.101,36.651", "duration_min": 120, "price_yuan": 0,
         "rating": 4.8, "description": "了解山东历史文化"},
    ],
    "lunch": [{"name": "草包包子铺", "cuisine": "面食", "location": "117.02,36.67"}],
    "dinner": [{"name": "城南往事", "cuisine": "鲁菜"}],
    "start_hour": 9,
}


def main():
    parser = argparse.ArgumentParser(description="智能排期器（Echo 可调）")
    parser.add_argument("--input", help="输入 JSON 文件路径，'-' 表示从 stdin 读")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON 而非文本")
    parser.add_argument("--demo", action="store_true", help="跑内置样例")
    args = parser.parse_args()

    if args.demo:
        payload = DEMO_PAYLOAD
    elif args.input == "-":
        payload = json.load(sys.stdin)
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        parser.print_help()
        sys.exit(1)

    if not payload.get("events"):
        print("没有候选活动，无法排期。请先用 entertainment/food-finder 搜出候选。")
        sys.exit(0)

    result = build_plan(payload)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(format_schedule(result))


if __name__ == "__main__":
    main()
