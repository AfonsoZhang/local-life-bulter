#!/usr/bin/env python3
"""智能排期器 — 给定候选活动 + 餐厅，生成最优时间线

核心能力：
1. 用坐标计算活动间的实际出行时间（并行）
2. 贪心算法优化活动顺序（最小化总出行时间）
3. 自动在合适时段插入午餐/晚餐
4. 计算总预算
5. 输出结构化时间线

使用场景：
- "帮我安排周末" → 推荐了 3 个活动 + 2 家餐厅 → 自动排期
- "去趵突泉玩" → 推荐了附近景点 → 优化游览顺序
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from schemas import (
    Location, Restaurant, EntertainmentEvent,
    RouteInfo, RouteOption, DayPlan,
)


# ═══════════════════════════════════════════════════════════════
# 出行时间矩阵
# ═══════════════════════════════════════════════════════════════


def _estimate_travel_time(loc_a: Optional[Location], loc_b: Optional[Location]) -> Tuple[int, str]:
    """估算两点之间的出行时间

    Returns:
        (time_min, mode) — 分钟数和推荐出行方式
    """
    if not loc_a or not loc_b:
        return 30, "walk"  # 无坐标时默认 30 分钟

    # 先算直线距离
    lng_a, lat_a = loc_a.longitude, loc_a.latitude
    lng_b, lat_b = loc_b.longitude, loc_b.latitude

    if lng_a == 0 or lng_b == 0:
        return 30, "walk"

    # 简单距离估算（度 → 公里，1度纬度 ≈ 111km）
    dlat = abs(lat_a - lat_b) * 111
    dlng = abs(lng_a - lng_b) * 111 * 0.85  # 济南纬度 cos 修正
    dist_km = (dlat ** 2 + dlng ** 2) ** 0.5

    # 尝试用高德 API 获取精确时间
    try:
        from amap_api import plan_walking, plan_driving, plan_bicycling
        origin = loc_a.amap_str
        dest = loc_b.amap_str

        if dist_km < 1.5:
            walk = plan_walking(origin, dest)
            if walk:
                return max(1, walk["duration_s"] // 60), "walk"
        elif dist_km < 5:
            bike = plan_bicycling(origin, dest)
            if bike:
                return max(1, bike["duration_s"] // 60), "bike"
        else:
            drive = plan_driving(origin, dest)
            if drive:
                return max(1, drive["duration_s"] // 60), "drive"
    except Exception:
        pass

    # fallback：根据距离估算
    if dist_km < 1:
        return max(5, int(dist_km * 15)), "walk"
    elif dist_km < 3:
        return max(10, int(dist_km * 8)), "bike"
    elif dist_km < 10:
        return max(15, int(dist_km * 3)), "drive"
    else:
        return max(20, int(dist_km * 2)), "drive"


def build_travel_matrix(venues: List[Dict]) -> List[List[Tuple[int, str]]]:
    """并行计算所有场馆间的出行时间矩阵

    Args:
        venues: [{"name": str, "location": Location}, ...]

    Returns:
        matrix[i][j] = (time_min, mode) 从场馆 i 到 j 的出行时间
    """
    n = len(venues)
    matrix = [[(30, "walk")] * n for _ in range(n)]

    # 收集所有需要计算的 pair
    tasks = []
    for i in range(n):
        for j in range(i + 1, n):
            tasks.append((i, j, venues[i].get("location"), venues[j].get("location")))

    if not tasks:
        return matrix

    # 并行计算
    def _calc(args):
        i, j, loc_a, loc_b = args
        time_ab, mode = _estimate_travel_time(loc_a, loc_b)
        return i, j, time_ab, mode

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_calc, t) for t in tasks]
        for future in as_completed(futures):
            try:
                i, j, time_min, mode = future.result()
                matrix[i][j] = (time_min, mode)
                matrix[j][i] = (time_min, mode)  # 对称
            except Exception:
                pass

    return matrix


def _parse_business_hours(time_str: str, activity_type: str = "") -> Optional[Tuple[int, int]]:
    """解析营业时间，返回 (开门小时, 关门小时)

    优先使用 time_str，如果为空则按活动类型推断默认值。

    支持格式：
    - "09:00-17:00" → (9, 17)
    - "09:00-22:00" → (9, 22)
    - "10:00-18:00" → (10, 18)
    - "每天" / "" / "营业时间未知" → 按类型推断
    """
    if time_str and time_str not in ("每天", "营业时间未知", "预约制", ""):
        import re
        match = re.search(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})", time_str)
        if match:
            open_h = int(match.group(1))
            close_h = int(match.group(3))
            return (open_h, close_h)

    # 按活动类型推断默认营业时间
    type_defaults = {
        "exhibition": (9, 17),   # 博物馆、展览馆
        "movie": (9, 23),       # 电影院
        "outdoor": (6, 21),     # 公园、景区
        "sports": (8, 22),      # 运动健身
        "game": (10, 23),       # 密室、剧本杀
        "shopping": (10, 22),   # 商场
        "performance": (14, 22),  # 演出
        "nightlife": (18, 2),  # 酒吧、KTV
    }
    return type_defaults.get(activity_type, None)


def _is_within_hours(start_hour: int, duration_min: int, business_hours: Optional[Tuple[int, int]]) -> bool:
    """检查活动是否在营业时间内

    Args:
        start_hour: 活动开始小时
        duration_min: 活动时长（分钟）
        business_hours: (开门小时, 关门小时)，None 表示无限制

    Returns:
        True 表示可以安排
    """
    if business_hours is None:
        return True

    open_h, close_h = business_hours
    duration_hours = (duration_min + 59) // 60  # 向上取整
    available_hours = close_h - start_hour

    # 还没开门
    if start_hour < open_h:
        return False

    # 关门前无法完成（可用时间 < 活动时长）
    if available_hours < duration_hours:
        return False

    return True


# ═══════════════════════════════════════════════════════════════
# 优化算法
# ═══════════════════════════════════════════════════════════════


def _greedy_order(events: List[Dict], matrix: List[List[Tuple[int, str]]]) -> List[int]:
    """贪心排序：从第一个活动开始，每次选最近的未访问活动

    Args:
        events: 活动列表
        matrix: 出行时间矩阵

    Returns:
        排序后的索引列表
    """
    n = len(events)
    if n <= 1:
        return list(range(n))

    # 如果活动有固定时间，按时间排序
    has_time = []
    no_time = []
    for i, e in enumerate(events):
        time_str = e.get("time", "")
        if time_str and any(c.isdigit() for c in time_str):
            has_time.append(i)
        else:
            no_time.append(i)

    if has_time:
        # 有固定时间的排前面，按时间排序
        has_time.sort(key=lambda i: events[i].get("time", ""))
        # 无固定时间的用贪心排后面
        if no_time:
            # 从最后一个有时间的活动出发
            start = has_time[-1]
            remaining = set(no_time)
            current = start
            while remaining:
                nearest = min(remaining, key=lambda j: matrix[current][j][0])
                has_time.append(nearest)
                remaining.remove(nearest)
                current = nearest
        return has_time

    # 全部无固定时间 → 纯贪心（从第一个开始）
    visited = [0]
    remaining = set(range(1, n))
    current = 0

    while remaining:
        nearest = min(remaining, key=lambda j: matrix[current][j][0])
        visited.append(nearest)
        remaining.remove(nearest)
        current = nearest

    return visited


def _insert_meals(
    timeline: List[Dict],
    lunch_candidates: List[Restaurant],
    dinner_candidates: List[Restaurant],
    start_hour: int = 9,
) -> List[Dict]:
    """在时间线中插入用餐

    Args:
        timeline: 已排好序的活动时间线
        lunch_candidates: 午餐候选
        dinner_candidates: 晚餐候选
        start_hour: 出发时间（小时）

    Returns:
        插入用餐后的完整时间线
    """
    result = []
    current_minutes = start_hour * 60

    lunch_inserted = False
    dinner_inserted = False

    for entry in timeline:
        entry_start = entry.get("start_minutes", current_minutes)

        # 检查是否该插入午餐（11:00-14:00 之间）
        if not lunch_inserted and lunch_candidates and entry_start >= 11 * 60:
            lunch = lunch_candidates[0]
            result.append({
                "type": "meal",
                "meal_type": "lunch",
                "name": lunch.name if isinstance(lunch, Restaurant) else lunch.get("name", ""),
                "cuisine": lunch.cuisine if isinstance(lunch, Restaurant) else lunch.get("cuisine", ""),
                "location": "当前区域",
                "start_minutes": max(entry_start, 11 * 60),
                "duration_min": 60,
            })
            lunch_inserted = True
            current_minutes = max(entry_start, 11 * 60) + 60

        # 检查是否该插入晚餐（17:00-21:00 之间）
        if not dinner_inserted and dinner_candidates and entry_start >= 17 * 60:
            dinner = dinner_candidates[0]
            result.append({
                "type": "meal",
                "meal_type": "dinner",
                "name": dinner.name if isinstance(dinner, Restaurant) else dinner.get("name", ""),
                "cuisine": dinner.cuisine if isinstance(dinner, Restaurant) else dinner.get("cuisine", ""),
                "location": "当前区域",
                "start_minutes": max(entry_start, 17 * 60),
                "duration_min": 60,
            })
            dinner_inserted = True
            current_minutes = max(entry_start, 17 * 60) + 60

        entry["start_minutes"] = max(entry_start, current_minutes)
        result.append(entry)
        current_minutes = entry["start_minutes"] + entry.get("duration_min", 120)

    # 如果到结束还没插入用餐，补到最后
    if not lunch_inserted and lunch_candidates:
        lunch = lunch_candidates[0]
        result.append({
            "type": "meal",
            "meal_type": "lunch",
            "name": lunch.name if isinstance(lunch, Restaurant) else lunch.get("name", ""),
            "cuisine": lunch.cuisine if isinstance(lunch, Restaurant) else lunch.get("cuisine", ""),
            "location": "当前区域",
            "start_minutes": 12 * 60,
            "duration_min": 60,
        })

    if not dinner_inserted and dinner_candidates:
        dinner = dinner_candidates[0]
        result.append({
            "type": "meal",
            "meal_type": "dinner",
            "name": dinner.name if isinstance(dinner, Restaurant) else dinner.get("name", ""),
            "cuisine": dinner.cuisine if isinstance(dinner, Restaurant) else dinner.get("cuisine", ""),
            "location": "当前区域",
            "start_minutes": 18 * 60,
            "duration_min": 60,
        })

    # 按时间排序
    result.sort(key=lambda e: e.get("start_minutes", 0))
    return result


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════


def schedule_day(
    events: List,
    lunch: List = None,
    dinner: List = None,
    start_hour: int = 9,
) -> Dict:
    """智能排期：给定候选活动 + 餐厅，生成最优时间线

    Args:
        events: 活动列表（EntertainmentEvent 或 dict）
        lunch: 午餐候选（Restaurant 或 dict）
        dinner: 晚餐候选（Restaurant 或 dict）
        start_hour: 出发时间（小时，默认 9）

    Returns:
        {
            "timeline": [...],
            "total_time_min": int,
            "total_travel_min": int,
            "total_activity_min": int,
            "total_cost_yuan": int,
            "order_changed": bool,
            "summary": str,
        }
    """
    lunch = lunch or []
    dinner = dinner or []

    if not events:
        return {
            "timeline": [],
            "total_time_min": 0,
            "total_travel_min": 0,
            "total_activity_min": 0,
            "total_cost_yuan": 0,
            "order_changed": False,
            "summary": "没有候选活动",
        }

    # 去重（按名称）
    seen_names = set()
    unique_events = []
    for e in events:
        name = e.name if isinstance(e, EntertainmentEvent) else e.get("name", "")
        if name not in seen_names:
            seen_names.add(name)
            unique_events.append(e)
    events = unique_events

    if not events:
        return {
            "timeline": [],
            "total_time_min": 0,
            "total_travel_min": 0,
            "total_activity_min": 0,
            "total_cost_yuan": 0,
            "order_changed": False,
            "summary": "没有候选活动（去重后为空）",
        }

    # 标准化输入
    event_dicts = []
    for e in events:
        if isinstance(e, EntertainmentEvent):
            event_dicts.append({
                "name": e.name,
                "type": e.type,
                "venue": e.venue,
                "location": e.location,
                "time": e.time,
                "duration_min": e.duration_min,
                "price_yuan": e.price_yuan,
                "rating": e.rating,
                "description": e.description,
                "source_type": "EntertainmentEvent",
            })
        else:
            event_dicts.append({
                "name": e.get("name", ""),
                "type": e.get("type", ""),
                "venue": e.get("venue", ""),
                "location": e.get("location"),
                "time": e.get("time", ""),
                "duration_min": e.get("duration_min", 120),
                "price_yuan": e.get("price_yuan", 0),
                "rating": e.get("rating", 0),
                "description": e.get("description", ""),
                "source_type": "dict",
            })

    # 计算出行时间矩阵
    matrix = build_travel_matrix(event_dicts)

    # 贪心排序
    order = _greedy_order(event_dicts, matrix)
    original_order = list(range(len(event_dicts)))
    order_changed = order != original_order

    # 构建带出行时间的时间线
    timeline = []
    current_minutes = start_hour * 60
    total_travel = 0

    for step, idx in enumerate(order):
        event = event_dicts[idx]

        # 出行时间（从上一个活动到当前）
        if step > 0:
            prev_idx = order[step - 1]
            travel_min, travel_mode = matrix[prev_idx][idx]
            total_travel += travel_min

            # 出行条目
            timeline.append({
                "type": "travel",
                "from": event_dicts[prev_idx]["name"],
                "to": event["name"],
                "duration_min": travel_min,
                "mode": travel_mode,
                "start_minutes": current_minutes,
            })
            current_minutes += travel_min

        # 检查营业时间
        duration = event.get("duration_min", 120) or 120
        business_hours = _parse_business_hours(event.get("time", ""), event.get("type", ""))
        start_h = current_minutes // 60

        if not _is_within_hours(start_h, duration, business_hours):
            # 尝试调整到营业时间内
            if business_hours:
                open_h, close_h = business_hours
                if open_h > start_h:
                    # 还没开门，等到开门
                    current_minutes = open_h * 60
                elif close_h - start_h < 1:
                    # 关门了，跳过
                    continue

        # 活动条目
        timeline.append({
            "type": "activity",
            "name": event["name"],
            "venue": event.get("venue", ""),
            "duration_min": duration,
            "price_yuan": event.get("price_yuan", 0),
            "rating": event.get("rating", 0),
            "description": event.get("description", ""),
            "start_minutes": current_minutes,
        })
        current_minutes += duration

    # 插入用餐
    timeline = _insert_meals(timeline, lunch, dinner, start_hour)

    # 计算统计
    total_activity = sum(
        e.get("duration_min", 0) for e in timeline if e["type"] == "activity"
    )
    total_cost = sum(
        e.get("price_yuan", 0) for e in timeline if e["type"] == "activity"
    )
    # 加上用餐费用估算
    for e in timeline:
        if e["type"] == "meal":
            if e.get("meal_type") == "lunch":
                total_cost += 40  # 午餐估 40
            else:
                total_cost += 80  # 晚餐估 80

    total_time = timeline[-1]["start_minutes"] + timeline[-1].get("duration_min", 0) - start_hour * 60 if timeline else 0

    # 格式化时间
    for entry in timeline:
        mins = entry.get("start_minutes", 0)
        entry["start_time_str"] = f"{mins // 60:02d}:{mins % 60:02d}"
        end_mins = mins + entry.get("duration_min", 0)
        entry["end_time_str"] = f"{end_mins // 60:02d}:{end_mins % 60:02d}"

    # 生成摘要
    summary_parts = []
    summary_parts.append(f"共 {len(events)} 个活动")
    if order_changed:
        summary_parts.append("已优化顺序以减少出行时间")
    summary_parts.append(f"总出行时间 {total_travel} 分钟")
    summary_parts.append(f"预计总花费 ¥{total_cost}")

    return {
        "timeline": timeline,
        "total_time_min": total_time,
        "total_travel_min": total_travel,
        "total_activity_min": total_activity,
        "total_cost_yuan": total_cost,
        "order_changed": order_changed,
        "summary": "，".join(summary_parts),
    }


# ═══════════════════════════════════════════════════════════════
# 格式化输出
# ═══════════════════════════════════════════════════════════════


def format_schedule(result: Dict) -> str:
    """格式化排期结果（适配微信）"""
    timeline = result.get("timeline", [])
    if not timeline:
        return "没有可安排的活动"

    # 微信规范：禁 markdown 加粗、禁带数字 emoji（📅）。用 📋 + 纯文本。
    lines = ["📋 今日行程安排\n"]

    for entry in timeline:
        start = entry.get("start_time_str", "??:??")
        end = entry.get("end_time_str", "??:??")
        entry_type = entry["type"]

        if entry_type == "activity":
            name = entry["name"]
            venue = entry.get("venue", "")
            price = entry.get("price_yuan", 0)
            rating = entry.get("rating", 0)
            desc = entry.get("description", "")

            emoji = "🎨" if "展" in name else "🎬" if "电影" in name else "🎮" if "密室" in name else "🏃"
            lines.append(f"{emoji} {start}-{end} {name}")
            if venue:
                lines.append(f"   📍 {venue}")
            parts = []
            if price > 0:
                parts.append(f"💰 ¥{price}")
            if rating > 0:
                parts.append(f"⭐ {rating}")
            if parts:
                lines.append(f"   {' | '.join(parts)}")
            if desc:
                lines.append(f"   📝 {desc}")
            lines.append("")

        elif entry_type == "meal":
            meal_type = entry.get("meal_type", "")
            name = entry["name"]
            cuisine = entry.get("cuisine", "")
            emoji = "🍜" if meal_type == "lunch" else "🍽"
            label = "午餐" if meal_type == "lunch" else "晚餐"
            lines.append(f"{emoji} {start}-{end} {label}：{name}")
            if cuisine:
                lines.append(f"   🥘 {cuisine}")
            lines.append("")

        elif entry_type == "travel":
            duration = entry.get("duration_min", 0)
            mode = entry.get("mode", "walk")
            mode_emoji = {"walk": "🚶", "bike": "🚲", "drive": "🚗", "transit": "🚌"}.get(mode, "🚶")
            mode_name = {"walk": "步行", "bike": "骑行", "drive": "驾车", "transit": "公交"}.get(mode, "出行")
            lines.append(f"   {mode_emoji} {mode_name} {duration}分钟（{entry.get('from', '')} → {entry.get('to', '')}）")

    # 统计
    lines.append("─" * 20)
    stats = []
    if result.get("total_activity_min"):
        hours = result["total_activity_min"] // 60
        stats.append(f"活动 {hours}小时")
    if result.get("total_travel_min"):
        stats.append(f"出行 {result['total_travel_min']}分钟")
    if result.get("total_cost_yuan"):
        stats.append(f"预计花费 ¥{result['total_cost_yuan']}")
    if stats:
        lines.append(f"📊 {' | '.join(stats)}")

    if result.get("order_changed"):
        lines.append("✨ 已优化活动顺序，减少出行时间")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI 测试
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from schemas import EntertainmentEvent, Restaurant, Location

    # 模拟活动
    events = [
        EntertainmentEvent(
            name="趵突泉", type="outdoor", venue="趵突泉公园",
            location=Location(116.997, 36.664),
            duration_min=90, price_yuan=40, rating=4.7,
            description="天下第一泉",
        ),
        EntertainmentEvent(
            name="大明湖", type="outdoor", venue="大明湖景区",
            location=Location(117.024, 36.678),
            duration_min=120, price_yuan=0, rating=4.5,
            description="免费开放的城市湖泊公园",
        ),
        EntertainmentEvent(
            name="山东省博物馆", type="exhibition", venue="山东省博物馆",
            location=Location(117.101, 36.651),
            duration_min=120, price_yuan=0, rating=4.8,
            description="了解山东历史文化",
        ),
    ]

    lunch = [
        Restaurant(name="草包包子铺", cuisine="面食", rating=4.3,
                    price_range="人均30", zone="历下区"),
    ]
    dinner = [
        Restaurant(name="城南往事", cuisine="鲁菜", rating=4.5,
                    price_range="人均80", zone="历下区"),
    ]

    print("=== 智能排期测试 ===\n")
    result = schedule_day(events, lunch=lunch, dinner=dinner, start_hour=9)
    print(format_schedule(result))
    print()
    print(f"摘要: {result['summary']}")
