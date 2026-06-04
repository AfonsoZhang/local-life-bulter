#!/usr/bin/env python3
"""出行规划脚本 - 高德地图 API + 模拟数据 fallback

优先使用高德地图路径规划 API 获取真实路线数据，
API 不可用时自动降级到本地模拟数据。

支持：驾车、公交、步行、骑行
"""

import json
import os
import argparse
import sys
from typing import List, Dict, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from memory import (
    record_interaction,
    get_last_recommendations,
    get_learned_preferences,
    get_top_preferences,
)

# 尝试导入高德 API
try:
    from amap_api import (
        geocode,
        plan_driving,
        plan_walking,
        plan_transit,
        plan_bicycling,
        resolve_location,
        save_user_location,
    )
    HAS_AMAP = True
except ImportError:
    HAS_AMAP = False

DATA_FILE = os.path.join(SCRIPT_DIR, "..", "data", "routes.json")
DEFAULT_CITY = "济南"

# 多轮追问关键词
FOLLOWUP_KEYWORDS = [
    "太贵了", "便宜点", "有没有便宜", "省钱",
    "赶时间", "快一点", "最快", "来不及",
    "堵车", "路上堵", "路况",
    "下雨", "下雨了", "天气不好",
    "就这个", "就坐这个", "定了",
]


def is_followup_query(query: str) -> bool:
    query_lower = query.lower()
    return any(kw in query_lower for kw in FOLLOWUP_KEYWORDS)


def load_mock_routes() -> List[Dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["routes"]


def _format_duration(seconds: int) -> str:
    """秒转可读时间"""
    if seconds < 60:
        return f"{seconds}秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟"
    hours = minutes // 60
    mins = minutes % 60
    if mins:
        return f"{hours}小时{mins}分钟"
    return f"{hours}小时"


def _format_distance(meters: int) -> str:
    """米转可读距离"""
    if meters < 1000:
        return f"{meters}m"
    return f"{meters / 1000:.1f}km"


def _build_amap_route(origin_name: str, dest_name: str, origin_geo: Dict, dest_geo: Dict, city: str) -> Optional[Dict]:
    """通过高德 API 构建完整路线信息"""
    origin_loc = origin_geo["location"]
    dest_loc = dest_geo["location"]

    options = []

    # 1. 步行
    walk = plan_walking(origin_loc, dest_loc)
    if walk:
        dist_km = round(walk["distance_m"] / 1000, 1)
        options.append({
            "mode": "walk",
            "time_min": walk["duration_s"] // 60,
            "cost_yuan": 0,
            "distance_km": dist_km,
            "description": f"步行 {_format_duration(walk['distance_m'] and walk['duration_s'] or 0)}，距离 {_format_distance(walk['distance_m'] or 0)}",
            "steps_summary": " → ".join(
                s.get("instruction", "")[:20] for s in walk.get("steps", [])[:5]
            ) if walk.get("steps") else "",
            "source": "amap",
        })

    # 2. 公交/地铁
    transit = plan_transit(origin_loc, dest_loc, city=city)
    if transit and transit.get("transits"):
        for i, t in enumerate(transit["transits"][:3]):
            seg_names = []
            total_cost = 0
            for seg in t.get("segments", []):
                if seg.get("type") == "bus" and seg.get("name"):
                    seg_names.append(seg["name"])
                    total_cost += seg.get("price_yuan", 0) or 0
                elif seg.get("type") == "railway" and seg.get("name"):
                    seg_names.append(seg["name"])
                    total_cost += 3  # 地铁起步价
                elif seg.get("type") == "walk":
                    pass  # 步行段不显示

            desc_parts = []
            if seg_names:
                desc_parts.append("乘坐 " + " → ".join(seg_names[:3]))
            walking_m = t.get("walking_m", 0) or 0
            if walking_m > 0:
                desc_parts.append(f"步行 {_format_distance(walking_m)}")

            options.append({
                "mode": "transit" if i == 0 else f"transit_{i+1}",
                "time_min": (t.get("duration_s", 0) or 0) // 60,
                "cost_yuan": round(total_cost or t.get("cost_yuan", 0) or 0, 1),
                "distance_km": 0,  # 公交不提供总距离
                "description": "，".join(desc_parts) if desc_parts else "公交/地铁出行",
                "transit_detail": t.get("segments", []),
                "source": "amap",
            })

    # 3. 驾车
    drive = plan_driving(origin_loc, dest_loc)
    if drive:
        dist_km = round(drive["distance_m"] / 1000, 1)
        tolls = drive.get("tolls_yuan", 0) or 0
        desc = f"驾车 {_format_duration(drive['duration_s'] or 0)}，距离 {_format_distance(drive['distance_m'] or 0)}"
        if tolls > 0:
            desc += f"，过路费 ¥{tolls}"
        if drive.get("traffic_lights"):
            desc += f"，{drive['traffic_lights']}个红绿灯"

        options.append({
            "mode": "taxi",
            "time_min": (drive.get("duration_s", 0) or 0) // 60,
            "cost_yuan": round(tolls + max(10, dist_km * 2.5), 1),  # 估算打车费
            "distance_km": dist_km,
            "description": desc,
            "source": "amap",
        })

        # 自驾
        options.append({
            "mode": "drive",
            "time_min": (drive.get("duration_s", 0) or 0) // 60,
            "cost_yuan": round(tolls + dist_km * 0.6, 1),  # 油费估算
            "distance_km": dist_km,
            "description": desc + "（自驾）",
            "source": "amap",
        })

    # 4. 骑行
    bike = plan_bicycling(origin_loc, dest_loc)
    if bike:
        dist_km = round(bike["distance_m"] / 1000, 1)
        options.append({
            "mode": "bike",
            "time_min": (bike.get("duration_s", 0) or 0) // 60,
            "cost_yuan": 0,
            "distance_km": dist_km,
            "description": f"骑行约 {(bike.get('duration_s', 0) or 0) // 60} 分钟，距离 {_format_distance(bike['distance_m'] or 0)}",
            "source": "amap",
        })

    if not options:
        return None

    # 推荐：时间最短的非步行方案
    non_walk = [o for o in options if o["mode"] not in ("walk",)]
    if non_walk:
        best = min(non_walk, key=lambda x: x["time_min"])
    else:
        best = options[0]

    # 估算公交费用（如果有的话）
    transit_options = [o for o in options if "transit" in o["mode"]]
    rec_reason = "综合时间与费用"
    if transit_options:
        rec_reason = "公共交通性价比最高"
    elif best["mode"] == "taxi":
        rec_reason = "打车最快捷"
    elif best["mode"] == "walk":
        rec_reason = "距离很近，步行即可"

    return {
        "origin": origin_name,
        "destination": dest_name,
        "options": options,
        "recommendation": best["mode"],
        "reason": rec_reason,
        "data_source": "amap",
    }


def find_route(origin: str, destination: str, mode: str = "", priority: str = "", use_amap: bool = True) -> Dict:
    """查找路线，优先使用高德 API"""
    # 尝试高德 API
    if use_amap and HAS_AMAP:
        try:
            # 读取用户配置的城市
            user_loc = resolve_location()
            user_city = user_loc.get("city", DEFAULT_CITY)
            origin_geo = geocode(origin, city=user_city)
            dest_geo = geocode(destination, city=user_city)

            if origin_geo and dest_geo:
                route = _build_amap_route(origin, destination, origin_geo, dest_geo, user_city)
                if route:
                    return route
        except Exception as e:
            print(f"[amap] 路线规划失败: {e}")

    # fallback 到模拟数据
    routes = load_mock_routes()
    for route in routes:
        if (origin.lower() in route["origin"].lower() and
            destination.lower() in route["destination"].lower()):
            route["data_source"] = "mock"
            return route

    for route in routes:
        if destination.lower() in route["destination"].lower():
            route["data_source"] = "mock"
            return route

    # 生成默认路线
    return {
        "origin": origin,
        "destination": destination,
        "options": [
            {"mode": "walk", "time_min": 30, "cost_yuan": 0, "distance_km": 2.0,
             "description": "步行 30 分钟"},
            {"mode": "subway", "time_min": 20, "cost_yuan": 3, "distance_km": 3.0,
             "description": "地铁约 20 分钟"},
            {"mode": "taxi", "time_min": 12, "cost_yuan": 15, "distance_km": 2.5,
             "description": "打车约 12 分钟"},
        ],
        "recommendation": "subway",
        "reason": "综合时间与费用，地铁是最佳选择",
        "data_source": "mock",
    }


def format_output(route: Dict, mode_filter: str = "", priority: str = "", preference_hint: str = "") -> str:
    mode_names = {
        "walk": "🚶 步行", "subway": "🚇 地铁", "bus": "🚌 公交",
        "taxi": "🚕 打车", "drive": "🚗 自驾", "bike": "🚲 骑行",
        "transit": "🚇 公交/地铁", "transit_2": "🚇 方案二", "transit_3": "🚇 方案三",
    }

    data_source = route.get("data_source", "mock")
    lines = [f"🗺 从 {route['origin']} 到 {route['destination']}：\n"]

    if data_source == "amap":
        lines.append("📍 数据来源：高德地图（实时）\n")
    else:
        lines.append("📦 数据来源：本地推荐（模拟数据）\n")

    if preference_hint:
        lines.append(f"💡 {preference_hint}\n")

    options = route["options"]
    if mode_filter:
        mode_map = {"walk": "walk", "subway": "subway", "地铁": "subway",
                     "bus": "bus", "公交": "bus", "taxi": "taxi", "打车": "taxi",
                     "drive": "drive", "自驾": "drive", "bike": "bike", "骑行": "bike"}
        filtered = mode_map.get(mode_filter.lower(), mode_filter)
        options = [o for o in options if o["mode"] == filtered or o["mode"].startswith(filtered)]
        if not options:
            options = route["options"]

    if priority:
        pri_map = {"cost": "cost_yuan", "time": "time_min",
                    "费用": "cost_yuan", "时间": "time_min"}
        pri_key = pri_map.get(priority.lower(), "time_min")
        options = sorted(options, key=lambda x: x.get(pri_key, 0) or 0)

    for opt in options:
        name = mode_names.get(opt["mode"], opt["mode"])
        time_min = opt.get("time_min", 0) or 0
        cost = opt.get("cost_yuan", 0) or 0
        dist = opt.get("distance_km", 0) or 0

        lines.append(f"**{name}**")
        lines.append(f"   ⏱ {time_min} 分钟  |  💰 {cost} 元  |  📏 {dist}km")
        lines.append(f"   📝 {opt.get('description', '')}")

        # 显示换乘详情（公交）
        if opt.get("transit_detail"):
            for seg in opt["transit_detail"]:
                if seg.get("type") == "bus" and seg.get("name"):
                    lines.append(f"      🚌 {seg['name']} ({seg.get('depart_stop', '')} → {seg.get('arrive_stop', '')})")
                elif seg.get("type") == "railway" and seg.get("name"):
                    lines.append(f"      🚇 {seg['name']} ({seg.get('depart_stop', '')} → {seg.get('arrive_stop', '')})")

        # 显示驾车步骤摘要
        if opt.get("steps_summary"):
            lines.append(f"      📋 {opt['steps_summary']}")

        lines.append("")

    rec_mode = route.get("recommendation", "subway")
    rec_name = mode_names.get(rec_mode, rec_mode)
    lines.append(f"✅ **推荐：{rec_name}**")
    lines.append(f"💡 {route.get('reason', '综合时间与费用，这是最佳选择')}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="出行规划")
    parser.add_argument("--origin", required=True, help="出发地")
    parser.add_argument("--destination", required=True, help="目的地")
    parser.add_argument("--mode", default="", help="出行方式偏好")
    parser.add_argument("--priority", default="", help="优先考虑")
    parser.add_argument("--query", default="", help="自然语言查询（多轮对话用）")
    parser.add_argument("--no_amap", action="store_true", help="不使用高德 API")
    parser.add_argument("--set_location", default="", help="设置默认位置（如'武林广场'）")

    # 多轮对话参数
    parser.add_argument("--choice", default="", help="用户选择的出行方式（记录选择）")
    parser.add_argument("--recall", action="store_true", help="查看上次推荐")
    parser.add_argument("--no_record", action="store_true", help="不记录此次交互")

    args = parser.parse_args()

    # ── 查看上次推荐 ──
    if args.recall:
        last = get_last_recommendations("travel-planner")
        if not last:
            print("没有上次推荐记录")
            return
        print("📋 上次推荐的路线：\n")
        for r in last:
            print(f"  {r.get('name', r.get('origin', ''))} → {r.get('destination', '')}")
        return

    # ── 处理用户选择 ──
    if args.choice:
        last = get_last_recommendations("travel-planner")
        if last:
            record_interaction("travel-planner", "", last, user_choice=args.choice)
            print(f"✅ 已记录你的选择: {args.choice}")
        return

    # ── 处理多轮追问 ──
    query = f"{args.origin} → {args.destination}"

    if args.query and is_followup_query(args.query):
        last = get_last_recommendations("travel-planner")
        if last:
            query_lower = args.query.lower() if args.query else ""
            if any(kw in query_lower for kw in ["太贵了", "便宜点", "省钱"]):
                args.priority = "cost"
            elif any(kw in query_lower for kw in ["赶时间", "快一点", "最快"]):
                args.priority = "time"
            elif any(kw in query_lower for kw in ["下雨", "天气不好"]):
                args.mode = "taxi"

    # ── 设置默认位置 ──
    if args.set_location:
        geo = geocode(args.set_location)
        if geo and geo.get("location"):
            save_user_location(
                city=geo.get("city", ""),
                location_name=args.set_location,
                center=geo["location"],
            )
            print(f"✅ 默认位置已设为: {args.set_location} ({geo.get('city', '')} {geo.get('district', '')})")
        else:
            print(f"⚠️ 无法识别位置: {args.set_location}")
        return

    # ── 正常规划 ──
    route = find_route(args.origin, args.destination, args.mode, args.priority,
                       use_amap=not args.no_amap)

    # 学习偏好提示
    preferred_modes = get_top_preferences("preferred_transport_modes", 2)
    preference_hint = ""
    if preferred_modes:
        mode_name_map = {"subway": "地铁", "taxi": "打车", "bus": "公交", "walk": "步行", "transit": "公交"}
        names = [mode_name_map.get(m, m) for m in preferred_modes]
        preference_hint = f"你通常偏好{'/'.join(names)}出行"

    if not args.no_record:
        route_as_list = [{"name": f"{route['origin']}→{route['destination']}", "options": route["options"]}]
        record_interaction(
            skill="travel-planner",
            query=query,
            recommendations=route_as_list,
        )

    print(format_output(route, args.mode, args.priority, preference_hint))


if __name__ == "__main__":
    main()
