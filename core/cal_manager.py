#!/usr/bin/env python3
"""日程管理模块 - 管家自建日历 + iCal 文件导入

功能：
1. 自建日程：用户告诉管家"周六下午有事"，管家存储管理
2. iCal 导入：支持 .ics 文件导入外部日程
3. 冲突检测：推荐活动时自动检查时间冲突
4. 智能提醒：基于日程的提前提醒
5. 空闲时段查询：找出可用时间窗口
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict

from date_resolver import resolve_date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CALENDAR_PATH = os.path.join(PROJECT_ROOT, "config", "calendar.json")

# ── 数据结构 ──────────────────────────────────────────────


@dataclass
class CalendarEvent:
    """日程事件"""
    id: str = ""
    title: str = ""
    start_time: str = ""       # ISO 格式: 2026-05-26T14:00:00
    end_time: str = ""         # ISO 格式: 2026-05-26T17:00:00
    location: str = ""
    description: str = ""
    source: str = "manual"     # manual / ical / system
    tags: List[str] = field(default_factory=list)
    reminder_min: int = 30     # 提前提醒（分钟）
    created_at: str = ""
    all_day: bool = False


# ── 存储 ──────────────────────────────────────────────


def _load_calendar() -> List[Dict]:
    """加载日历数据"""
    if not os.path.exists(CALENDAR_PATH):
        return []
    try:
        with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("events", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _save_calendar(events: List[Dict]):
    """保存日历数据"""
    os.makedirs(os.path.dirname(CALENDAR_PATH), exist_ok=True)
    data = {
        "updated_at": datetime.now().isoformat(),
        "events": events,
    }
    with open(CALENDAR_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 时间解析 ──────────────────────────────────────────────


def _parse_relative_time(text: str) -> Optional[Tuple[datetime, datetime]]:
    """从自然语言解析时间范围

    日期部分委托给 date_resolver.resolve_date()，
    时段部分（上午/下午/具体时间点）在本函数处理。
    """
    now = datetime.now()
    text = text.strip()

    # ── 解析日期（委托给 date_resolver）──
    date_str = resolve_date(text, reference=now)
    if date_str is None:
        return None
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # ── 解析时段 ──
    all_day = False

    # 检测时段前缀（下午/晚上等，适用于后面的时间点）
    period_prefix = ""
    for p in ["上午", "下午", "晚上", "早上", "中午", "傍晚"]:
        if p in text:
            period_prefix = p
            break

    def _apply_period(hour: int, period: str) -> int:
        """应用时段偏移"""
        if period == "下午" and hour < 12:
            hour += 12
        elif period == "晚上" and hour < 12:
            hour += 12
        return hour

    # 具体时间 "X点到Y点" / "X:00-Y:00"（带时段前缀）
    # 支持"半"表示30分钟，如"2点半到5点半"
    m = re.search(r"(\d{1,2})[点时:](\d{1,2}|半)?\s*[到至\-~]\s*(\d{1,2})[点时:](\d{1,2}|半)?", text)
    if m:
        sh = int(m.group(1))
        sm = 30 if m.group(2) == "半" else (int(m.group(2)) if m.group(2) else 0)
        eh = int(m.group(3))
        em = 30 if m.group(4) == "半" else (int(m.group(4)) if m.group(4) else 0)
        # 如果有"下午"前缀，且小时数较小，应用偏移
        sh = _apply_period(sh, period_prefix)
        eh = _apply_period(eh, period_prefix)
        start = datetime.combine(target_date, datetime.min.time().replace(hour=sh, minute=sm))
        end = datetime.combine(target_date, datetime.min.time().replace(hour=eh, minute=em))
        return start, end

    # 单个时间点 "下午3点" → 3点到5点（默认2小时）
    m = re.search(r"(\d{1,2})[点时:](\d{1,2}|半)?", text)
    if m:
        hour = int(m.group(1))
        minute = 30 if m.group(2) == "半" else (int(m.group(2)) if m.group(2) else 0)
        hour = _apply_period(hour, period_prefix)
        start = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=minute))
        end = start + timedelta(hours=2)
        return start, end

    # 时段关键词
    if "全天" in text:
        start = datetime.combine(target_date, datetime.min.time())
        end = start + timedelta(days=1)
        all_day = True
        return start, end

    period_ranges = {
        "上午": (9, 12), "早上": (8, 10), "中午": (11, 13),
        "下午": (14, 18), "傍晚": (17, 19), "晚上": (19, 22),
        "夜里": (21, 24),
    }
    for kw, (sh, eh) in period_ranges.items():
        if kw in text:
            start = datetime.combine(target_date, datetime.min.time().replace(hour=sh))
            end = datetime.combine(target_date, datetime.min.time().replace(hour=eh))
            return start, end

    # 只有日期，没有时段 → 返回 None，让 LLM 询问用户具体时间
    return None


# ── 日程操作 ──────────────────────────────────────────────


def _validate_event_time(start_time: str, end_time: str) -> Optional[str]:
    """校验日程时间的合理性

    Returns:
        None 表示通过，否则返回错误信息
    """
    try:
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)
    except ValueError:
        return "时间格式无效，请使用 ISO 格式（如 2026-05-30T15:00:00）"

    # 1. 结束时间必须晚于开始时间
    if end_dt <= start_dt:
        return f"结束时间（{end_dt.strftime('%H:%M')}）不能早于或等于开始时间（{start_dt.strftime('%H:%M')}）"

    # 2. 时长不能超过 24 小时
    duration = (end_dt - start_dt).total_seconds() / 3600
    if duration > 24:
        return f"日程时长（{duration:.0f}小时）超过 24 小时，请检查时间是否正确"

    # 3. 时长不能少于 15 分钟
    if duration < 0.25:
        return f"日程时长（{duration * 60:.0f}分钟）少于 15 分钟，请检查时间是否正确"

    # 4. 不允许 00:00-06:00 之间的日程（除非是全天日程）
    start_hour = start_dt.hour
    end_hour = end_dt.hour
    if 0 <= start_hour < 6 and 0 < end_hour <= 6:
        return f"日程时间（{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}）在凌晨 0-6 点之间，请确认是否正确"

    return None


def add_event(
    title: str,
    start_time: str = "",
    end_time: str = "",
    location: str = "",
    description: str = "",
    tags: List[str] = None,
    reminder_min: int = 30,
    source: str = "manual",
    natural_time: str = "",
) -> Dict:
    """添加日程

    Args:
        title: 事件标题
        start_time: 开始时间（ISO格式），如果提供 natural_time 则可省略
        end_time: 结束时间（ISO格式）
        location: 地点
        description: 描述
        tags: 标签列表
        reminder_min: 提前提醒分钟数
        source: 来源 manual/ical
        natural_time: 自然语言时间描述，如"周六下午"

    Returns:
        创建的日程事件 dict
    """
    # 如果提供了自然语言时间，解析它
    if natural_time and not start_time:
        parsed = _parse_relative_time(natural_time)
        if parsed:
            start_time = parsed[0].isoformat()
            end_time = parsed[1].isoformat()

    if not start_time:
        return {"error": "无法解析时间，请提供具体时间（如'周六下午3点'或 ISO 格式）"}

    # 如果没有 end_time，默认 +2 小时
    if not end_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_time = (start_dt + timedelta(hours=2)).isoformat()
        except ValueError:
            end_time = start_time

    # 时间合理性校验
    time_error = _validate_event_time(start_time, end_time)
    if time_error:
        return {"error": time_error}

    event = CalendarEvent(
        id=str(uuid.uuid4())[:8],
        title=title,
        start_time=start_time,
        end_time=end_time,
        location=location,
        description=description,
        source=source,
        tags=tags or [],
        reminder_min=reminder_min,
        created_at=datetime.now().isoformat(),
    )

    events = _load_calendar()
    events.append(asdict(event))
    _save_calendar(events)

    return asdict(event)


def list_events(
    days_ahead: int = 7,
    start_date: str = "",
    end_date: str = "",
    tags: List[str] = None,
) -> List[Dict]:
    """查询日程

    Args:
        days_ahead: 查询未来几天（默认7天）
        start_date: 起始日期（ISO格式，优先于 days_ahead）
        end_date: 结束日期（ISO格式）
        tags: 按标签过滤

    Returns:
        日程列表，按时间排序
    """
    events = _load_calendar()
    now = datetime.now()

    if start_date:
        filter_start = datetime.fromisoformat(start_date)
    else:
        filter_start = now

    if end_date:
        filter_end = datetime.fromisoformat(end_date)
    else:
        filter_end = filter_start + timedelta(days=days_ahead)

    result = []
    for e in events:
        try:
            event_start = datetime.fromisoformat(e["start_time"])
            event_end = datetime.fromisoformat(e["end_time"])
        except (ValueError, KeyError):
            continue

        # 时间范围过滤
        if event_end < filter_start or event_start > filter_end:
            continue

        # 标签过滤
        if tags:
            if not any(t in e.get("tags", []) for t in tags):
                continue

        result.append(e)

    # 按开始时间排序
    result.sort(key=lambda x: x.get("start_time", ""))
    return result


def delete_event(event_id: str) -> bool:
    """删除日程"""
    events = _load_calendar()
    original_len = len(events)
    events = [e for e in events if e.get("id") != event_id]
    if len(events) < original_len:
        _save_calendar(events)
        return True
    return False


def update_event(event_id: str, **kwargs) -> Optional[Dict]:
    """更新日程"""
    events = _load_calendar()
    for e in events:
        if e.get("id") == event_id:
            for k, v in kwargs.items():
                if k in e:
                    e[k] = v
            _save_calendar(events)
            return e
    return None


# ── 冲突检测 ──────────────────────────────────────────────


def check_conflict(
    start_time: str,
    end_time: str,
    buffer_min: int = 30,
) -> List[Dict]:
    """检查时间冲突

    Args:
        start_time: 拟定开始时间（ISO格式）
        end_time: 拟定结束时间（ISO格式）
        buffer_min: 前后缓冲时间（分钟），默认30分钟

    Returns:
        冲突的日程列表，空列表表示无冲突
    """
    try:
        new_start = datetime.fromisoformat(start_time) - timedelta(minutes=buffer_min)
        new_end = datetime.fromisoformat(end_time) + timedelta(minutes=buffer_min)
    except ValueError:
        return []

    events = _load_calendar()
    conflicts = []

    for e in events:
        try:
            e_start = datetime.fromisoformat(e["start_time"])
            e_end = datetime.fromisoformat(e["end_time"])
        except (ValueError, KeyError):
            continue

        # 重叠检测：两个时间段有交集
        if e_start < new_end and e_end > new_start:
            conflicts.append(e)

    return conflicts


def has_conflict(start_time: str, end_time: str, buffer_min: int = 30) -> bool:
    """快速检查是否有冲突"""
    return len(check_conflict(start_time, end_time, buffer_min)) > 0


# ── 空闲时段查询 ──────────────────────────────────────────────


def find_free_slots(
    date: str = "",
    slot_duration_min: int = 120,
    day_start_hour: int = 9,
    day_end_hour: int = 22,
) -> List[Dict]:
    """找出某天的空闲时段

    Args:
        date: 目标日期（ISO格式），默认今天
        slot_duration_min: 最小空闲时段长度（分钟），默认2小时
        day_start_hour: 一天开始时间（小时）
        day_end_hour: 一天结束时间（小时）

    Returns:
        空闲时段列表 [{"start": "ISO", "end": "ISO", "duration_min": int}]
    """
    if date:
        target_date = datetime.fromisoformat(date).date()
    else:
        target_date = datetime.now().date()

    day_start = datetime.combine(target_date, datetime.min.time().replace(hour=day_start_hour))
    day_end = datetime.combine(target_date, datetime.min.time().replace(hour=day_end_hour))

    # 获取当天所有日程
    events = list_events(
        start_date=day_start.isoformat(),
        end_date=day_end.isoformat(),
    )

    # 排序并合并已占用时段
    occupied = []
    for e in events:
        try:
            e_start = datetime.fromisoformat(e["start_time"])
            e_end = datetime.fromisoformat(e["end_time"])
            occupied.append((e_start, e_end))
        except (ValueError, KeyError):
            continue

    occupied.sort()

    # 找空闲时段
    free_slots = []
    cursor = day_start

    for occ_start, occ_end in occupied:
        # cursor 到 occ_start 之间是空闲的
        if occ_start > cursor:
            duration = (occ_start - cursor).total_seconds() / 60
            if duration >= slot_duration_min:
                free_slots.append({
                    "start": cursor.isoformat(),
                    "end": occ_start.isoformat(),
                    "duration_min": int(duration),
                })
        # cursor 移到 occ_end 之后
        if occ_end > cursor:
            cursor = occ_end

    # 最后一段到 day_end
    if cursor < day_end:
        duration = (day_end - cursor).total_seconds() / 60
        if duration >= slot_duration_min:
            free_slots.append({
                "start": cursor.isoformat(),
                "end": day_end.isoformat(),
                "duration_min": int(duration),
            })

    return free_slots


# ── iCal 导入 ──────────────────────────────────────────────


def import_ical(ical_content: str) -> List[Dict]:
    """解析 iCal (.ics) 格式内容并导入日程

    支持基本的 VEVENT 字段：
    - SUMMARY → title
    - DTSTART / DTEND → start_time / end_time
    - LOCATION → location
    - DESCRIPTION → description

    Args:
        ical_content: .ics 文件内容字符串

    Returns:
        导入的日程列表
    """
    imported = []
    events = _load_calendar()

    # 按 VEVENT 分割
    vevents = re.split(r"BEGIN:VEVENT", ical_content)

    for vevent in vevents[1:]:  # 跳过第一个（VEVENT 之前的内容）
        # 截取到 END:VEVENT
        end_idx = vevent.find("END:VEVENT")
        if end_idx == -1:
            continue
        vevent = vevent[:end_idx]

        event_data = _parse_vevent(vevent)
        if event_data:
            # 检查是否已存在（按标题+开始时间去重）
            duplicate = False
            for existing in events:
                if (existing.get("title") == event_data["title"]
                        and existing.get("start_time") == event_data["start_time"]):
                    duplicate = True
                    break

            if not duplicate:
                events.append(event_data)
                imported.append(event_data)

    if imported:
        _save_calendar(events)

    return imported


def import_ical_file(file_path: str) -> List[Dict]:
    """从文件路径导入 iCal"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return import_ical(content)


def _parse_vevent(vevent_text: str) -> Optional[Dict]:
    """解析单个 VEVENT 块"""
    def _get_field(text: str, field_name: str) -> str:
        """提取 iCal 字段值（处理多行折叠）"""
        # 先展开折叠行（以空格或 tab 开头的行是前一行的延续）
        unfolded = re.sub(r"\r?\n[ \t]", "", text)
        pattern = rf"^{field_name}(?:;[^:]*)?:(.*)$"
        m = re.search(pattern, unfolded, re.MULTILINE)
        return m.group(1).strip() if m else ""

    summary = _get_field(vevent_text, "SUMMARY")
    if not summary:
        return None

    # 解析时间
    dtstart_str = _get_field(vevent_text, "DTSTART")
    dtend_str = _get_field(vevent_text, "DTEND")

    start_time = _parse_ical_datetime(dtstart_str)
    end_time = _parse_ical_datetime(dtend_str)

    if not start_time:
        return None

    # 如果没有结束时间，默认 +1 小时
    if not end_time:
        try:
            end_time = (datetime.fromisoformat(start_time) + timedelta(hours=1)).isoformat()
        except ValueError:
            end_time = start_time

    location = _get_field(vevent_text, "LOCATION")
    description = _get_field(vevent_text, "DESCRIPTION")
    # iCal 中的换义
    description = description.replace("\\n", "\n").replace("\\,", ",")

    return {
        "id": str(uuid.uuid4())[:8],
        "title": summary,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "description": description,
        "source": "ical",
        "tags": [],
        "reminder_min": 30,
        "created_at": datetime.now().isoformat(),
    }


def _parse_ical_datetime(dt_str: str) -> Optional[str]:
    """解析 iCal 日期时间格式

    支持：
    - 20260526T140000Z (UTC)
    - 20260526T140000 (本地时间)
    - 20260526 (全天)
    - TZID=Asia/Shanghai:20260526T140000
    """
    if not dt_str:
        return None

    # 移除 TZID 前缀
    m = re.search(r"(\d{8}(?:T\d{6})?Z?)$", dt_str)
    if not m:
        return None

    clean = m.group(1)

    try:
        if len(clean) == 8:  # 全天 20260526
            dt = datetime.strptime(clean, "%Y%m%d")
            return dt.isoformat()
        elif clean.endswith("Z"):  # UTC 20260526T140000Z
            dt = datetime.strptime(clean, "%Y%m%dT%H%M%SZ")
            return dt.isoformat()
        else:  # 本地时间 20260526T140000
            dt = datetime.strptime(clean, "%Y%m%dT%H%M%S")
            return dt.isoformat()
    except ValueError:
        return None


# ── 格式化输出 ──────────────────────────────────────────────


def format_event(e: Dict, index: int = 0) -> str:
    """格式化单个日程（适配微信）"""
    prefix = f"{index}. " if index > 0 else ""

    try:
        start = datetime.fromisoformat(e["start_time"])
        end = datetime.fromisoformat(e["end_time"])
        # 人性化时间
        now = datetime.now()
        if start.date() == now.date():
            day_label = "今天"
        elif start.date() == (now + timedelta(days=1)).date():
            day_label = "明天"
        else:
            day_label = start.strftime("%m月%d日")

        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_names[start.weekday()]

        time_str = f"{day_label}({weekday}) {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    except (ValueError, KeyError):
        time_str = e.get("start_time", "时间未知")

    lines = [f"{prefix}📋 {e['title']}"]
    lines.append(f"   🕐 {time_str}")
    if e.get("location"):
        lines.append(f"   📍 {e['location']}")
    if e.get("tags"):
        lines.append(f"   🏷 {', '.join(e['tags'])}")

    return "\n".join(lines)


def format_events(events: List[Dict], title: str = "日程安排") -> str:
    """格式化日程列表（适配微信）"""
    if not events:
        return "📋 暂无日程安排"

    lines = [f"📋 **{title}：**", ""]
    for i, e in enumerate(events, 1):
        lines.append(format_event(e, i))
        lines.append("")

    return "\n".join(lines)


def format_free_slots(slots: List[Dict], date_str: str = "") -> str:
    """格式化空闲时段（适配微信）"""
    if not slots:
        return "😅 这天看起来排满了，没有足够长的空闲时段"

    if date_str:
        lines = [f"🕐 **{date_str} 的空闲时段：**", ""]
    else:
        lines = ["🕐 **空闲时段：**", ""]

    for i, slot in enumerate(slots, 1):
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        duration = slot["duration_min"]
        hours = duration // 60
        mins = duration % 60
        dur_str = f"{hours}小时" if mins == 0 else f"{hours}小时{mins}分钟"
        lines.append(f"{i}. {start.strftime('%H:%M')}-{end.strftime('%H:%M')} ({dur_str})")

    return "\n".join(lines)


def format_conflict_info(conflicts: List[Dict]) -> str:
    """格式化冲突信息（适配微信）"""
    if not conflicts:
        return "✅ 这个时间段没有冲突"

    lines = ["⚠️ 和以下日程有冲突："]
    for e in conflicts:
        try:
            start = datetime.fromisoformat(e["start_time"])
            end = datetime.fromisoformat(e["end_time"])
            time_str = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
        except (ValueError, KeyError):
            time_str = ""
        lines.append(f"  · {e['title']} ({time_str})")

    return "\n".join(lines)


# ── 自然语言解析入口 ──────────────────────────────────────────────


def parse_and_add(natural_input: str) -> Dict:
    """从自然语言添加日程

    支持：
    - "周六下午有事" → 标题"有事"，时间周六下午
    - "周六下午3点到5点开会" → 标题"开会"，具体时间
    - "明天上午去医院，地点：浙一医院" → 标题+地点
    """
    # 提取地点
    location = ""
    loc_match = re.search(r"(?:地点[是：:]?|在|去)\s*([^\s,，。、]+)", natural_input)
    if loc_match:
        location = loc_match.group(1)

    # 提取时间（传给解析器的原文）
    time_text = natural_input

    # 提取标题：去掉时间词，保留动作和对象
    title = natural_input
    # 去掉常见时间词
    time_patterns = [
        r"(今天|明天|后天|大后天)",
        r"(下|这|本)?(?:周|星期)[一二三四五六日天]",
        r"\d{1,2}月\d{1,2}[号日]",
        r"(上午|下午|晚上|中午|早上|傍晚|夜里)",
        r"\d{1,2}[点时:](\d{1,2}|半)?\s*[到至\-~]\s*\d{1,2}[点时:]?(\d{1,2}|半)?",
        r"\d{1,2}[点时:](\d{1,2}|半)?",
        r"(全天|整天)",
        r"有(?=事|安排|活动|会议|约会)",
        r"帮我(记一下?|提醒|备注)",
        r"(记一下|提醒我|别忘了|帮我记)",
        r"一下",
        r"地点[是：:]*\s*[^\s,，。、]+",
    ]
    for p in time_patterns:
        title = re.sub(p, "", title)
    # 清理标点和空格
    title = re.sub(r"[，,。.、\s]+", "", title).strip()
    if not title or len(title) < 2:
        # 尝试用动作+地点作为标题
        if location:
            action_match = re.search(r"(去|到|上)" + re.escape(location), natural_input)
            if action_match:
                title = action_match.group(0)
            else:
                title = f"去{location}"
        else:
            title = "有安排"
    return add_event(
        title=title,
        location=location,
        source="manual",
        natural_time=time_text,
    )


# ── CLI 测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python calendar.py add '周六下午3点到5点开会'")
        print("  python calendar.py list")
        print("  python calendar.py free [日期]")
        print("  python calendar.py import <file.ics>")
        print("  python calendar.py check '2026-05-26T15:00:00' '2026-05-26T17:00:00'")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 3:
            print("需要提供日程描述")
            sys.exit(1)
        result = parse_and_add(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "list":
        events = list_events()
        print(format_events(events))

    elif cmd == "free":
        date = sys.argv[2] if len(sys.argv) > 2 else ""
        slots = find_free_slots(date)
        print(format_free_slots(slots))

    elif cmd == "import":
        if len(sys.argv) < 3:
            print("需要提供 .ics 文件路径")
            sys.exit(1)
        imported = import_ical_file(sys.argv[2])
        print(f"导入了 {len(imported)} 个日程")
        for e in imported:
            print(format_event(e))

    elif cmd == "check":
        if len(sys.argv) < 4:
            print("需要提供开始和结束时间")
            sys.exit(1)
        conflicts = check_conflict(sys.argv[2], sys.argv[3])
        print(format_conflict_info(conflicts))

    else:
        print(f"未知命令: {cmd}")
