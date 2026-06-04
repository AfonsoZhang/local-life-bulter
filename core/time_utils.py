#!/usr/bin/env python3
"""时间感知模块 - 时间过滤、活动有效期检查、用餐时段匹配

功能：
1. 获取当前时间/日期
2. 检查活动是否在有效期内
3. 根据当前时间推荐合适的用餐时段
4. 智能排期（根据活动时间+耗时生成时间线）
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re


def now() -> datetime:
    """获取当前时间"""
    return datetime.now()


def current_hour() -> int:
    """获取当前小时（24h）"""
    return now().hour


def current_date_str() -> str:
    """获取当前日期字符串 YYYY-MM-DD"""
    return now().strftime("%Y-%m-%d")


def weekday_name() -> str:
    """获取当前星期名"""
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return days[now().weekday()]


def is_weekend() -> bool:
    """是否周末"""
    return now().weekday() >= 5


# ── 用餐时段 ──────────────────────────────────────────────

def get_current_meal_type() -> str:
    """根据当前时间判断用餐时段

    Returns:
        breakfast / morning_snack / lunch / afternoon_tea / dinner / late_night
    """
    hour = current_hour()
    if 6 <= hour < 9:
        return "breakfast"
    elif 9 <= hour < 11:
        return "morning_snack"
    elif 11 <= hour < 14:
        return "lunch"
    elif 14 <= hour < 17:
        return "afternoon_tea"
    elif 17 <= hour < 21:
        return "dinner"
    else:
        return "late_night"


def get_meal_type_label(meal_type: str) -> str:
    """获取用餐时段的中文标签"""
    labels = {
        "breakfast": "早餐",
        "morning_snack": "上午茶",
        "lunch": "午餐",
        "afternoon_tea": "下午茶",
        "dinner": "晚餐",
        "late_night": "夜宵",
    }
    return labels.get(meal_type, "")


def get_meal_type_from_text(text: str) -> Optional[str]:
    """从文本中提取用餐时段"""
    text = text.lower()
    meal_map = {
        "早餐": "breakfast", "早饭": "breakfast", "早上吃": "breakfast",
        "午餐": "lunch", "午饭": "lunch", "中午吃": "lunch", "工作餐": "lunch",
        "下午茶": "afternoon_tea", "喝咖啡": "afternoon_tea", "喝下午茶": "afternoon_tea",
        "晚餐": "dinner", "晚饭": "dinner", "晚上吃": "dinner",
        "夜宵": "late_night", "宵夜": "late_night", "深夜": "late_night",
    }
    for kw, meal_type in meal_map.items():
        if kw in text:
            return meal_type
    return None


def filter_restaurants_by_meal(restaurants: List[Dict], meal_type: str = None) -> List[Dict]:
    """根据用餐时段过滤餐厅

    Args:
        restaurants: 餐厅列表
        meal_type: 用餐时段，None 则使用当前时间

    Returns:
        符合时段的餐厅列表（保持原顺序）
    """
    if meal_type is None:
        meal_type = get_current_meal_type()

    filtered = []
    for r in restaurants:
        available = r.get("meal_type", [])
        # 没有 meal_type 字段的餐厅默认全时段可用
        if not available or meal_type in available:
            filtered.append(r)

    return filtered


def get_restaurant_meal_score_boost(restaurant: Dict, meal_type: str = None) -> float:
    """根据用餐时段给餐厅评分加权

    Args:
        restaurant: 餐厅数据
        meal_type: 用餐时段，None 则使用当前时间

    Returns:
        评分加权值
    """
    if meal_type is None:
        meal_type = get_current_meal_type()

    available = restaurant.get("meal_type", [])
    if not available:
        return 0.0  # 没有 meal_type 信息，不加不减

    if meal_type in available:
        return 1.5  # 当前时段可用，加分
    else:
        return -3.0  # 当前时段不可用，大幅减分


# ── 活动有效期 ──────────────────────────────────────────────

def parse_date_range(date_str: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """解析日期字符串，返回 (开始日期, 结束日期)

    支持格式：
    - "每天" → (None, None) 表示无限期
    - "每周五、六" → (None, None) 表示周期性
    - "2026-05-20" → (date, date) 单日
    - "2026-05-20 至 2026-06-15" → (start, end) 日期范围
    """
    if not date_str:
        return None, None

    date_str = date_str.strip()

    # "每天"、"每周" 等 → 无限期
    if any(kw in date_str for kw in ["每天", "每周", "每日", "长期"]):
        return None, None

    # 日期范围 "2026-05-20 至 2026-06-15"
    range_match = re.search(r"(\d{4}-\d{2}-\d{2})\s*[-至到]\s*(\d{4}-\d{2}-\d{2})", date_str)
    if range_match:
        try:
            start = datetime.strptime(range_match.group(1), "%Y-%m-%d")
            end = datetime.strptime(range_match.group(2), "%Y-%m-%d")
            return start, end
        except ValueError:
            pass

    # 单日 "2026-05-20"
    single_match = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
    if single_match:
        try:
            date = datetime.strptime(single_match.group(1), "%Y-%m-%d")
            return date, date
        except ValueError:
            pass

    return None, None


def is_event_valid(event: Dict) -> bool:
    """检查活动是否在有效期内

    Args:
        event: 活动数据

    Returns:
        True 表示活动仍然有效（未过期）
    """
    date_str = event.get("date", "")
    start, end = parse_date_range(date_str)

    # 无法解析日期 → 保守认为有效
    if start is None and end is None:
        return True

    today = now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 单日活动：检查是否已过
    if start == end:
        return start >= today

    # 日期范围：只要活动还没完全结束就有效
    if start and end:
        return today <= end + timedelta(days=1)

    return True


def is_event_upcoming(event: Dict, days: int = 7) -> bool:
    """检查活动是否在近期（N天内）

    Args:
        event: 活动数据
        days: 天数范围

    Returns:
        True 表示活动在近期有效
    """
    date_str = event.get("date", "")
    start, end = parse_date_range(date_str)

    # 无限期活动 → 总是近期有效
    if start is None and end is None:
        return True

    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    future = today + timedelta(days=days)

    # 单日活动
    if start == end:
        return today <= start <= future

    # 日期范围：与近期有交集
    if start and end:
        return start <= future and end >= today

    return True


def filter_valid_events(events: List[Dict]) -> List[Dict]:
    """过滤掉已过期的活动"""
    return [e for e in events if is_event_valid(e)]


def get_event_time_score_boost(event: Dict) -> float:
    """根据活动时间给评分加权

    - 当天的活动加分
    - 近期（3天内）的活动小幅加分
    - 已过期的活动大幅减分
    """
    date_str = event.get("date", "")
    start, end = parse_date_range(date_str)

    # 无限期活动不加不减
    if start is None and end is None:
        return 0.0

    today = now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 已过期
    if end and end < today:
        return -10.0

    # 当天
    if start and start == today:
        return 3.0

    # 近期（3天内）
    if start and (start - today).days <= 3:
        return 1.5

    return 0.0


# ── 智能排期 ──────────────────────────────────────────────

def parse_event_time(event: Dict) -> Optional[Tuple[int, int]]:
    """解析活动的开始时间，返回 (hour, minute)

    Args:
        event: 活动数据

    Returns:
        (hour, minute) 或 None
    """
    time_str = event.get("time", "")
    if not time_str or time_str in ["预约制", "每天", "傍晚-夜晚"]:
        return None

    # "19:30" 格式
    match = re.search(r"(\d{1,2}):(\d{2})", time_str)
    if match:
        return int(match.group(1)), int(match.group(2))

    # "10:00-17:00" 格式 → 取开始时间
    match = re.search(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})", time_str)
    if match:
        return int(match.group(1)), int(match.group(2))

    return None


def estimate_end_time(event: Dict) -> Optional[Tuple[int, int]]:
    """估算活动结束时间

    Args:
        event: 活动数据

    Returns:
        (hour, minute) 或 None
    """
    time_str = event.get("time", "")
    duration = event.get("duration_min", 0)

    # "10:00-17:00" 格式 → 直接取结束时间
    match = re.search(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})", time_str)
    if match:
        return int(match.group(3)), int(match.group(4))

    # 有开始时间和持续时间 → 计算结束时间
    start = parse_event_time(event)
    if start and duration:
        start_minutes = start[0] * 60 + start[1]
        end_minutes = start_minutes + duration
        return end_minutes // 60, end_minutes % 60

    return None


def build_smart_timeline(
    events: List[Dict],
    lunch: List[Dict],
    dinner: List[Dict],
) -> List[Dict]:
    """智能排期：根据活动实际时间和耗时生成时间线

    Args:
        events: 活动列表
        lunch: 午餐候选
        dinner: 晚餐候选

    Returns:
        时间线条目列表
    """
    timeline = []

    # 按活动开始时间排序（无时间的排在后面）
    sorted_events = sorted(events, key=lambda e: parse_event_time(e) or (99, 0))

    last_end_hour = 8  # 默认早上 8 点开始

    for event in sorted_events:
        start_time = parse_event_time(event)
        end_time = estimate_end_time(event)

        # 活动条目
        entry = {
            "type": "activity",
            "name": event["name"],
            "venue": event.get("venue", ""),
            "duration_min": event.get("duration_min", 0),
            "price": event.get("price_yuan", 0),
        }

        if start_time:
            entry["start_time"] = f"{start_time[0]:02d}:{start_time[1]:02d}"
            last_end_hour = end_time[0] if end_time else start_time[0] + 2
            if end_time:
                entry["end_time"] = f"{end_time[0]:02d}:{end_time[1]:02d}"
        else:
            # 没有明确时间，根据上一个活动结束时间推算
            entry["start_time"] = f"{last_end_hour:02d}:00"
            duration = event.get("duration_min", 120)
            end_minutes = last_end_hour * 60 + duration
            entry["end_time"] = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            last_end_hour = end_minutes // 60

        timeline.append(entry)

        # 如果下一个活动之前有空档，插入用餐
        next_start = None
        idx = sorted_events.index(event)
        if idx + 1 < len(sorted_events):
            next_start = parse_event_time(sorted_events[idx + 1])

        # 午餐：11:00-14:00 之间
        if lunch and 11 <= last_end_hour <= 14:
            r = lunch[0]
            timeline.append({
                "type": "lunch",
                "name": r["name"],
                "cuisine": r.get("cuisine", ""),
                "time": f"{last_end_hour:02d}:00",
            })

        # 晚餐：17:00-21:00 之间
        if dinner and 17 <= last_end_hour <= 21:
            r = dinner[0]
            timeline.append({
                "type": "dinner",
                "name": r["name"],
                "cuisine": r.get("cuisine", ""),
                "time": f"{last_end_hour:02d}:00",
            })

    # 如果没有在活动中插入用餐，补充到最后
    if lunch and not any(t["type"] == "lunch" for t in timeline):
        r = lunch[0]
        timeline.append({
            "type": "lunch",
            "name": r["name"],
            "cuisine": r.get("cuisine", ""),
            "time": "12:00",
        })

    if dinner and not any(t["type"] == "dinner" for t in timeline):
        r = dinner[0]
        timeline.append({
            "type": "dinner",
            "name": r["name"],
            "cuisine": r.get("cuisine", ""),
            "time": "18:00",
        })

    # 按时间排序
    def sort_key(entry):
        time_str = entry.get("start_time") or entry.get("time", "99:99")
        try:
            parts = time_str.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return 9999

    timeline.sort(key=sort_key)
    return timeline


# ── 时间描述 ──────────────────────────────────────────────

def get_time_context_description() -> str:
    """生成当前时间上下文描述"""
    hour = current_hour()
    meal = get_current_meal_type()
    meal_label = get_meal_type_label(meal)
    day = weekday_name()
    weekend = "（周末）" if is_weekend() else ""

    if 6 <= hour < 12:
        period = "上午"
    elif 12 <= hour < 14:
        period = "中午"
    elif 14 <= hour < 18:
        period = "下午"
    elif 18 <= hour < 22:
        period = "晚上"
    else:
        period = "深夜"

    return f"{day}{weekend} {period}，当前适合 {meal_label}"


def format_time_for_display(hour: int, minute: int = 0) -> str:
    """格式化时间用于显示"""
    if hour < 6:
        return f"凌晨 {hour:02d}:{minute:02d}"
    elif hour < 12:
        return f"上午 {hour:02d}:{minute:02d}"
    elif hour < 14:
        return f"中午 {hour:02d}:{minute:02d}"
    elif hour < 18:
        return f"下午 {hour:02d}:{minute:02d}"
    elif hour < 22:
        return f"晚上 {hour:02d}:{minute:02d}"
    else:
        return f"深夜 {hour:02d}:{minute:02d}"


# ── CLI 测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    print(f"当前时间: {now().strftime('%Y-%m-%d %H:%M')}")
    print(f"星期: {weekday_name()}")
    print(f"用餐时段: {get_meal_type_label(get_current_meal_type())}")
    print(f"时间描述: {get_time_context_description()}")
    print(f"是否周末: {is_weekend()}")

    # 测试日期解析
    test_dates = ["每天", "2026-05-20", "2026-05-20 至 2026-06-15", "每周五、六"]
    print("\n日期解析测试:")
    for d in test_dates:
        start, end = parse_date_range(d)
        valid = is_event_valid({"date": d})
        print(f"  {d} → start={start}, end={end}, valid={valid}")
