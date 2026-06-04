#!/usr/bin/env python3
"""日期解析工具 — 把自然语言日期描述转换为确定的 ISO 日期

所有涉及日期的场景都应调用此模块，禁止 LLM 自行推算日期。

用法：
  from date_resolver import resolve_date, resolve_date_range
  resolve_date("下周周一") → "2026-06-01"
  resolve_date_range("下周") → ("2026-06-01", "2026-06-07")
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple


def resolve_date(text: str, reference: Optional[datetime] = None) -> Optional[str]:
    """把自然语言日期描述转换为 ISO 日期字符串

    Args:
        text: 自然语言日期描述，如"明天"、"下周周一"、"6月5号"
        reference: 参考时间点，默认为当前时间

    Returns:
        ISO 日期字符串 "YYYY-MM-DD"，解析失败返回 None
    """
    if reference is None:
        reference = datetime.now()
    text = text.strip()
    now = reference

    # ── 相对日期 ──

    if "今天" in text:
        return now.strftime("%Y-%m-%d")

    if "明天" in text:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if "大后天" in text:
        return (now + timedelta(days=3)).strftime("%Y-%m-%d")

    if "后天" in text:
        return (now + timedelta(days=2)).strftime("%Y-%m-%d")

    if "昨天" in text:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")

    if "前天" in text:
        return (now - timedelta(days=2)).strftime("%Y-%m-%d")

    # ── 周X ──

    weekday_map = {
        "周一": 0, "周二": 1, "周三": 2, "周四": 3,
        "周五": 4, "周六": 5, "周日": 6, "周天": 6,
        "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
        "星期五": 4, "星期六": 5, "星期日": 6, "星期天": 6,
        "礼拜一": 0, "礼拜二": 1, "礼拜三": 2, "礼拜四": 3,
        "礼拜五": 4, "礼拜六": 5, "礼拜天": 6, "礼拜日": 6,
    }

    for name, wd in weekday_map.items():
        if name in text:
            # 先算出不加"下周"等前缀时的 days_ahead
            days_ahead = wd - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7

            # "下周" 前缀：找到下周一，再加 weekday 偏移
            if "下周" in text or "下个" in text:
                days_to_next_monday = (7 - now.weekday()) % 7
                if days_to_next_monday == 0:
                    days_to_next_monday = 7
                days_ahead = days_to_next_monday + wd

            # "这周" / "本周"
            if "这周" in text or "本周" in text or "这个" in text:
                days_ahead = wd - now.weekday()
                if days_ahead < 0:
                    days_ahead += 7

            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # ── X月X号/日 ──

    m = re.search(r"(\d{1,2})月(\d{1,2})[号日]", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = now.year
        try:
            candidate = datetime(year, month, day).date()
            if candidate < now.date():
                year += 1
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # ── N天后 / N天前 ──

    m = re.search(r"(\d+)\s*天[以后]", text)
    if m:
        return (now + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    # ── 下个月 ──

    if "下个月" in text:
        m = re.search(r"下个月(\d{1,2})[号日]", text)
        if m:
            day = int(m.group(1))
            month = now.month + 1
            year = now.year
            if month > 12:
                month = 1
                year += 1
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    return None


def resolve_date_range(text: str, reference: Optional[datetime] = None) -> Optional[Tuple[str, str]]:
    """解析日期范围

    Args:
        text: 自然语言描述，如"下周"、"这周"、"下周一到周五"
        reference: 参考时间点

    Returns:
        (start_date, end_date) ISO 格式元组，解析失败返回 None
    """
    if reference is None:
        reference = datetime.now()
    text = text.strip()
    now = reference

    # "下周"
    if "下周" in text or "下个周" in text:
        # 下周一
        days_to_monday = (7 - now.weekday()) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        next_monday = now + timedelta(days=days_to_monday)
        next_friday = next_monday + timedelta(days=4)
        return (next_monday.strftime("%Y-%m-%d"), next_friday.strftime("%Y-%m-%d"))

    # "这周" / "本周"
    if "这周" in text or "本周" in text:
        days_to_monday = now.weekday()
        this_monday = now - timedelta(days=days_to_monday)
        this_friday = this_monday + timedelta(days=4)
        return (this_monday.strftime("%Y-%m-%d"), this_friday.strftime("%Y-%m-%d"))

    # "X到Y" 范围
    m = re.search(r"(\d{1,2})月(\d{1,2})[号日]\s*[到至\-~]\s*(\d{1,2})[号日月]", text)
    if m:
        start_month = int(m.group(1))
        start_day = int(m.group(2))
        # 结束日期的月份
        end_month_str = m.group(3)
        end_day_str = re.search(r"[到至\-~]\s*(\d{1,2})月?(\d{1,2})?[号日]?", text[m.end()-5:])
        if end_day_str:
            end_month = int(end_day_str.group(1)) if end_day_str.group(1) else start_month
            end_day = int(end_day_str.group(2)) if end_day_str.group(2) else start_day
        else:
            end_month = start_month
            end_day = start_day
        year = now.year
        try:
            start = datetime(year, start_month, start_day)
            end = datetime(year, end_month, end_day)
            if start.date() < now.date():
                start = start.replace(year=year + 1)
                end = end.replace(year=year + 1)
            return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        except ValueError:
            pass

    return None


def get_weekday(date_str: str) -> str:
    """获取日期对应的星期几

    Args:
        date_str: ISO 日期字符串 "YYYY-MM-DD"

    Returns:
        中文星期几，如"周一"
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return names[dt.weekday()]
    except ValueError:
        return ""


# ── CLI ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python date_resolver.py '下周周一'")
        print("      python date_resolver.py '明天'")
        print("      python date_resolver.py '6月5号'")
        print("      python date_resolver.py --range '下周'")
        sys.exit(0)

    if sys.argv[1] == "--range" and len(sys.argv) >= 3:
        result = resolve_date_range(sys.argv[2])
        if result:
            print(f"{result[0]} ~ {result[1]} ({get_weekday(result[0])} ~ {get_weekday(result[1])})")
        else:
            print("无法解析")
    else:
        result = resolve_date(sys.argv[1])
        if result:
            weekday = get_weekday(result)
            print(f"{result} ({weekday})")
        else:
            print("无法解析")
