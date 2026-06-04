#!/usr/bin/env python3
"""播报消息生成器 — 生成统一格式的播报消息

用法：
  python broadcast.py morning       # 早安播报
  python broadcast.py evening       # 晚安播报
  python broadcast.py alert         # 天气预警（无异常则不输出）
  python broadcast.py booking       # 预订到店提醒（2小时内有预订时输出）
  python broadcast.py review        # 待评价提醒（有未评价的已完成预订时输出）
  python broadcast.py weather-check # 天气-日程冲突检测（有户外日程+恶劣天气时输出）

输出：纯文本，适配微信，emoji 位置固定。
"""

import sys
import os
import json
import urllib.request
from datetime import datetime, timedelta

# ── 配置 ──────────────────────────────────────────────

CITY = "济南"
CITY_EN = "Jinan"

# ── 天气获取 ──────────────────────────────────────────────


def get_weather():
    """获取济南当前天气和明目预报"""
    try:
        url = f"https://wttr.in/{CITY_EN}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        current = data.get("current_condition", [{}])[0]
        today_weather = data.get("weather", [{}])[0]
        tomorrow_weather = data.get("weather", [{}])[1] if len(data.get("weather", [])) > 1 else None

        # 当前天气
        curr_desc_en = current.get("weatherDesc", [{}])[0].get("value", "")
        curr_desc = _translate_desc(curr_desc_en)
        curr_temp = current.get("temp_C", "?")
        curr_feel = current.get("FeelsLikeC", "?")
        curr_humidity = current.get("humidity", "?")

        # 今日
        today_max = today_weather.get("maxtempC", "?")
        today_min = today_weather.get("mintempC", "?")
        today_desc_en = today_weather.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if len(today_weather.get("hourly", [])) > 4 else ""
        today_desc = _translate_desc(today_desc_en)

        # 明日
        tomorrow = {}
        if tomorrow_weather:
            t_desc_en = tomorrow_weather.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if len(tomorrow_weather.get("hourly", [])) > 4 else ""
            tomorrow = {
                "desc": _translate_desc(t_desc_en),
                "max": tomorrow_weather.get("maxtempC", "?"),
                "min": tomorrow_weather.get("mintempC", "?"),
            }

        # 判断是否需要带伞
        rain_keywords = ["雨", "雨雪", "雷", "drizzle", "rain", "thunder"]
        need_umbrella = any(k in curr_desc_en.lower() or k in today_desc_en.lower() for k in rain_keywords)

        return {
            "current": {
                "desc": curr_desc,
                "temp": curr_temp,
                "feel": curr_feel,
                "humidity": curr_humidity,
            },
            "today": {
                "desc": today_desc,
                "max": today_max,
                "min": today_min,
            },
            "tomorrow": tomorrow,
            "need_umbrella": need_umbrella,
            "raw_desc": curr_desc_en,
        }
    except Exception as e:
        return {"error": str(e)}


def _translate_desc(desc_en):
    """将英文天气描述翻译为中文"""
    desc_map = {
        "Clear": "晴天", "Sunny": "晴天",
        "Partly cloudy": "多云", "Partly Cloudy": "多云",
        "Cloudy": "阴天", "Overcast": "阴天",
        "Light rain": "小雨", "Light Rain": "小雨",
        "Moderate rain": "中雨", "Heavy rain": "大雨",
        "Patchy rain possible": "可能有小雨",
        "Patchy rain nearby": "零星小雨",
        "Light drizzle": "毛毛雨",
        "Thundery outbreaks possible": "可能有雷阵雨",
        "Mist": "薄雾", "Fog": "雾",
        "Light snow": "小雪", "Moderate snow": "中雪",
        "Heavy snow": "大雪",
        "Sunny Intervals": "晴间多云",
        "Light rain shower": "阵雨",
        "Moderate or heavy rain shower": "大阵雨",
    }
    desc = desc_map.get(desc_en, "")
    if not desc:
        dl = desc_en.lower()
        if "rain" in dl:
            desc = "有雨"
        elif "snow" in dl:
            desc = "有雪"
        elif "cloud" in dl:
            desc = "多云"
        elif "thunder" in dl:
            desc = "雷阵雨"
        elif "fog" in dl or "mist" in dl:
            desc = "雾"
        elif "clear" in dl or "sunny" in dl:
            desc = "晴天"
        else:
            desc = "天气变化"
    return desc


def weather_emoji(desc):
    """根据天气描述返回固定 emoji"""
    rain_words = ["雨", "drizzle", "rain", "thunder"]
    snow_words = ["雪", "snow"]
    cloud_words = ["多云", "阴", "cloudy", "overcast"]
    clear_words = ["晴", "clear", "sunny"]

    desc_lower = desc.lower()
    for w in rain_words:
        if w in desc_lower:
            return "🌧️"
    for w in snow_words:
        if w in desc_lower:
            return "❄️"
    for w in cloud_words:
        if w in desc_lower:
            return "🌤️"
    for w in clear_words:
        if w in desc_lower:
            return "☀️"
    return "🌤️"


# ── 日历获取 ──────────────────────────────────────────────


def get_calendar(date_str):
    """获取指定日期的日程"""
    import subprocess
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_cli.py")
    try:
        result = subprocess.run(
            ["python3", script, "--json", "list", "--date", date_str],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception:
        pass
    return []


# ── 播报生成 ──────────────────────────────────────────────


def generate_morning():
    """生成早安播报"""
    w = get_weather()
    today = datetime.now().strftime("%Y-%m-%d")
    events = get_calendar(today)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[datetime.now().weekday()]

    if "error" in w:
        return f"早安！今天是{weekday}，天气信息暂时获取失败，出门前看看窗外吧。"

    emoji = weather_emoji(w["current"]["desc"])
    lines = []

    # 天气
    umbrella = "记得带伞" if w["need_umbrella"] else "不需要带伞"
    lines.append(f"早安！{emoji} 济南今天{w['today']['desc']}，{w['today']['min']}-{w['today']['max']}度，{umbrella}。")

    # 日程
    lines.append("")
    if events:
        lines.append("📋 今天的安排：")
        for e in events:
            title = e.get("title", "")
            start = e.get("start_time", "")
            location = e.get("location", "")
            try:
                t = datetime.fromisoformat(start).strftime("%H:%M")
                time_str = f"{t}"
            except (ValueError, AttributeError):
                time_str = ""
            loc_str = f"，地点{location}" if location else ""
            lines.append(f"  · {title}（{time_str}{loc_str}）")
    else:
        lines.append("📋 今天没有安排，自由的一天。")

    # 每日打卡提醒（示例，可换成自己的习惯）
    lines.append("")
    lines.append("🎯 别忘了今天的学习打卡，保持连胜！")

    # 建议
    if not events:
        lines.append("")
        lines.append("💡 今天有空，要不要安排点什么？")

    # 结尾
    lines.append("")
    lines.append(f"💪 {weekday}加油！")

    return "\n".join(lines)


def generate_evening():
    """生成晚安播报"""
    w = get_weather()
    # 晚安播报查当天日程（凌晨触发时"当天"就是醒来那天）
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    events = get_calendar(today_str)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[now.weekday()]

    if "error" in w:
        return f"晚安！明天是{weekday}，天气信息暂时获取失败，早点休息吧。🌙"  # 保留"明天"因为这是问候语

    lines = []

    # 天气（明日预报）
    if w.get("tomorrow"):
        t = w["tomorrow"]
        emoji = weather_emoji(t["desc"])
        lines.append(f"晚安！{emoji} 明天济南{t['desc']}，{t['min']}-{t['max']}度。")
    else:
        emoji = weather_emoji(w["current"]["desc"])
        lines.append(f"晚安！{emoji} 今天济南{w['today']['desc']}，{w['today']['min']}-{w['today']['max']}度。")

    # 日程（明日）
    lines.append("")
    if events:
        lines.append(f"📋 今天（{weekday}）的安排：")
        for e in events:
            title = e.get("title", "")
            start = e.get("start_time", "")
            location = e.get("location", "")
            try:
                t = datetime.fromisoformat(start).strftime("%H:%M")
                time_str = f"{t}"
            except (ValueError, AttributeError):
                time_str = ""
            loc_str = f"，地点{location}" if location else ""
            lines.append(f"  · {title}（{time_str}{loc_str}）")
    else:
        lines.append(f"📋 今天（{weekday}）没有安排。")

    # 每日打卡提醒（示例，可换成自己的习惯）
    lines.append("")
    lines.append("🎯 今天的学习打卡了吗？别忘了哦。")

    # 结尾
    lines.append("")
    lines.append("🌙 好梦，明天见！")

    return "\n".join(lines)


def generate_alert():
    """生成天气预警（无异常返回空字符串）"""
    w = get_weather()
    if "error" in w:
        return ""

    desc = w["raw_desc"].lower()
    curr_temp = int(w["current"]["temp"]) if w["current"]["temp"] != "?" else None

    # 判断异常天气
    alert_reasons = []
    rain_words = ["rain", "thunder", "drizzle", "shower"]
    storm_words = ["heavy rain", "torrential", "storm"]
    wind_words = ["gale", "strong wind"]

    if any(k in desc for k in storm_words):
        alert_reasons.append("暴雨")
    elif any(k in desc for k in rain_words):
        alert_reasons.append("下雨")
    elif any(k in desc for k in wind_words):
        alert_reasons.append("大风")

    if curr_temp is not None:
        if curr_temp >= 35:
            alert_reasons.append("高温")
        elif curr_temp <= 0:
            alert_reasons.append("严寒")

    if not alert_reasons:
        return ""

    emoji = weather_emoji(w["current"]["desc"])
    reason = "、".join(alert_reasons)

    lines = []
    lines.append(f"⚠️ 天气预警：济南当前{w['current']['desc']}，{curr_temp}度。")

    # 出行影响
    if "雨" in reason or "暴雨" in reason:
        lines.append("🌧️ 出行注意：路面湿滑，建议带伞，尽量减少户外活动。")
    elif "大风" in reason:
        lines.append("🌤️ 出行注意：风力较大，注意防风，远离高空坠物区域。")
    elif "高温" in reason:
        lines.append("☀️ 出行注意：天气炎热，注意防暑，多喝水。")
    elif "严寒" in reason:
        lines.append("❄️ 出行注意：天气严寒，注意保暖。")

    lines.append("")
    lines.append("💡 出门前做好防护，安全第一。")

    return "\n".join(lines)


# ── 预订提醒 ──────────────────────────────────────────────

BOOKING_CLI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "skills", "booking", "scripts", "booking_cli.py",
)


def generate_booking_reminder():
    """生成预订到店提醒（2小时内有预订时输出）"""
    if not os.path.exists(BOOKING_CLI):
        return ""

    import subprocess
    try:
        sys.path.insert(0, os.path.dirname(BOOKING_CLI))
        from booking_cli import get_reminders
        reminders = get_reminders()
    except (ImportError, Exception):
        return ""

    if not reminders:
        return ""

    lines = []
    for r in reminders:
        mins = r.get("minutes_until", 0)
        if mins <= 30:
            lines.append(f"⚠️ {r['venue']} 快到了！")
        elif mins <= 60:
            lines.append(f"⏰ {r['venue']} 还有 {mins} 分钟")
        else:
            lines.append(f"🔔 {r['venue']} 还有约 {mins // 60} 小时")

        lines.append(f"   🕐 {r['time']} · 👥 {r['party_size']}位")
        if r.get("location"):
            lines.append(f"   📍 {r['location']}")
        lines.append("")

    if lines:
        lines.insert(0, "📋 预订提醒：\n")
        lines.append("回复「导航」前往 | 回复「取消」")
    return "\n".join(lines)


# ── 评价提醒 ──────────────────────────────────────────────


def generate_review_prompt():
    """生成待评价提醒（有已完成但未评价的预订时输出）"""
    if not os.path.exists(BOOKING_CLI):
        return ""

    try:
        sys.path.insert(0, os.path.dirname(BOOKING_CLI))
        from booking_cli import get_completed_without_review
        pending = get_completed_without_review()
    except (ImportError, Exception):
        return ""

    if not pending:
        return ""

    # 只提醒最近一个
    latest = pending[-1]
    venue = latest.get("venue", "")
    date = latest.get("date", "")

    return f"💬 {venue}（{date}）感觉怎么样？随便说两句就行，帮我下次推荐更准"


# ── 天气-日程冲突检测 ──────────────────────────────────────


OUTDOOR_KEYWORDS = [
    "户外", "跑步", "骑行", "爬山", "登山", "徒步", "野餐",
    "公园", "游泳", "钓鱼", "烧烤", "露营", "景区", "游乐",
    "散步", "遛弯", "运动", "球", "广场",
]


def generate_weather_conflict():
    """检测天气与日程的冲突（户外日程+恶劣天气时输出）"""
    w = get_weather()
    if "error" in w:
        return ""

    # 检查是否有恶劣天气
    desc = w.get("raw_desc", "").lower()
    bad_weather = any(k in desc for k in ["rain", "thunder", "storm", "snow", "heavy"])
    curr_temp = None
    try:
        curr_temp = int(w["current"]["temp"])
    except (ValueError, TypeError, KeyError):
        pass
    extreme_temp = curr_temp is not None and (curr_temp >= 37 or curr_temp <= -5)

    if not bad_weather and not extreme_temp:
        return ""

    # 检查今天是否有户外日程
    today = datetime.now().strftime("%Y-%m-%d")
    events = get_calendar(today)
    if not events:
        return ""

    outdoor_events = []
    for e in events:
        title = e.get("title", "").lower()
        location = e.get("location", "").lower()
        combined = title + " " + location
        if any(kw in combined for kw in OUTDOOR_KEYWORDS):
            outdoor_events.append(e)

    if not outdoor_events:
        return ""

    lines = []
    weather_desc = w["current"]["desc"]
    lines.append(f"⚠️ 天气提醒：今天济南{weather_desc}，但你有户外安排：\n")

    for e in outdoor_events:
        title = e.get("title", "")
        start = e.get("start_time", "")
        try:
            t = datetime.fromisoformat(start).strftime("%H:%M")
        except (ValueError, AttributeError):
            t = ""
        lines.append(f"  · {title}（{t}）")

    lines.append("")

    if bad_weather:
        lines.append("💡 建议改到室内，或者换个时间？")
        lines.append("   回复「帮我改」，我推荐室内替代方案")
    elif extreme_temp:
        temp_word = "高温" if curr_temp >= 37 else "严寒"
        lines.append(f"💡 今天{temp_word}（{curr_temp}度），户外活动注意防护")

    return "\n".join(lines)


# ── 早安播报增强：预订提醒 ──────────────────────────────────


def _get_today_bookings():
    """获取今天的预订"""
    if not os.path.exists(BOOKING_CLI):
        return []
    try:
        sys.path.insert(0, os.path.dirname(BOOKING_CLI))
        from booking_cli import list_bookings
        today = datetime.now().strftime("%Y-%m-%d")
        all_bookings = list_bookings(upcoming=True)
        return [b for b in all_bookings if b.get("date") == today]
    except (ImportError, Exception):
        return []


# ── 主入口 ──────────────────────────────────────────────


def main():
    if len(sys.argv) < 2:
        print("用法: python broadcast.py [morning|evening|alert|booking|review|weather-check]")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "morning":
        output = generate_morning()
        # 早安播报附加今日预订
        today_bookings = _get_today_bookings()
        if today_bookings:
            output += "\n\n📋 今天的预订："
            for b in today_bookings:
                output += f"\n  · {b['venue']}（{b['time']}，{b['party_size']}位）"
        print(output)

    elif mode == "evening":
        print(generate_evening())

    elif mode == "alert":
        result = generate_alert()
        if result:
            print(result)

    elif mode == "booking":
        result = generate_booking_reminder()
        if result:
            print(result)

    elif mode == "review":
        result = generate_review_prompt()
        if result:
            print(result)

    elif mode == "weather-check":
        result = generate_weather_conflict()
        if result:
            print(result)

    else:
        print(f"未知模式: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
