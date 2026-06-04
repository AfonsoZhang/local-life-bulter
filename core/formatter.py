#!/usr/bin/env python3
"""结构化消息格式化 - 微信友好的卡片式输出

替代传统 App 的 UI 卡片，在纯文本环境中实现高信息密度展示。
所有技能共用此模块保证输出风格统一。

设计原则：
- 微信不支持 markdown 表格，用分隔线和缩进替代
- 每条消息 < 1500 字符（微信限制）
- 关键信息前置，细节后置
- 用 emoji 做视觉锚点，但不滥用
"""

from typing import Dict, List, Optional


# ── 单项卡片 ──────────────────────────────────────────────

def restaurant_card(r: Dict, index: int = 0, show_actions: bool = True) -> str:
    """餐厅推荐卡片"""
    lines = []
    lines.append(f"{'─' * 26}")
    lines.append(f"  {index}. {r.get('name', '')}")
    lines.append(f"  ⭐ {r.get('rating', '')}  |  💰 {r.get('price_range', '')}  |  📏 {r.get('distance_km', '?')}km")

    if r.get("cuisine"):
        lines.append(f"  🍴 {r['cuisine']}")
    if r.get("location"):
        lines.append(f"  📍 {r['location']}")
    if r.get("open_hours"):
        lines.append(f"  🕐 {r['open_hours']}")

    tags = r.get("tags", [])
    if tags:
        lines.append(f"  🏷️ {'·'.join(tags[:4])}")

    wait = r.get("wait_time_min", 0)
    if wait > 0:
        lines.append(f"  ⏳ 约等 {wait} 分钟")

    lines.append(f"{'─' * 26}")

    if show_actions:
        lines.append(f"  回复 {index} 预订  |  回复「导航」前往")

    return "\n".join(lines)


def event_card(e: Dict, index: int = 0, show_actions: bool = True) -> str:
    """活动/娱乐推荐卡片"""
    lines = []
    lines.append(f"{'─' * 26}")
    lines.append(f"  {index}. {e.get('name', '')}")

    info_parts = []
    if e.get("type"):
        info_parts.append(e["type"])
    if e.get("price_yuan") or e.get("price_range"):
        price = e.get("price_yuan") or e.get("price_range")
        info_parts.append(f"💰 {price}")
    if e.get("rating"):
        info_parts.append(f"⭐ {e['rating']}")
    if info_parts:
        lines.append(f"  {'  |  '.join(info_parts)}")

    if e.get("time") or e.get("date"):
        time_str = e.get("time") or e.get("date", "")
        lines.append(f"  🕐 {time_str}")
    if e.get("location") or e.get("venue"):
        loc = e.get("location") or e.get("venue", "")
        lines.append(f"  📍 {loc}")
    if e.get("description"):
        desc = e["description"][:60]
        lines.append(f"  📝 {desc}")

    lines.append(f"{'─' * 26}")

    if show_actions:
        lines.append(f"  回复 {index} 报名  |  回复「详情」了解更多")

    return "\n".join(lines)


def booking_card(b: Dict) -> str:
    """预订确认卡片"""
    status_text = {
        "confirmed": "已确认 🟢",
        "paid": "已支付 💳",
        "completed": "已完成 ✅",
        "cancelled": "已取消 ❌",
    }.get(b.get("status", ""), b.get("status", ""))

    lines = []
    lines.append(f"{'─' * 26}")
    lines.append(f"  📋 预订确认")
    lines.append(f"  {b.get('venue', '')}")
    lines.append(f"  🕐 {b.get('date', '')} {b.get('time', '')}")
    lines.append(f"  👥 {b.get('party_size', '')}位")

    if b.get("location"):
        lines.append(f"  📍 {b['location']}")
    if b.get("estimated_cost") and b["estimated_cost"] > 0:
        lines.append(f"  💰 预估 ¥{b['estimated_cost']:.0f}")
    if b.get("notes"):
        lines.append(f"  📝 {b['notes']}")

    lines.append(f"  {status_text}")
    lines.append(f"{'─' * 26}")

    return "\n".join(lines)


# ── 列表格式 ──────────────────────────────────────────────

def recommendation_list(
    items: List[Dict],
    item_type: str = "restaurant",
    header: str = "",
    preference_hint: str = "",
    show_actions: bool = True,
) -> str:
    """推荐列表（多项卡片 + 操作提示）"""
    if not items:
        return "暂无推荐结果，换个条件试试？"

    lines = []

    if header:
        lines.append(header)
        lines.append("")

    if preference_hint:
        lines.append(f"💡 {preference_hint}")
        lines.append("")

    for i, item in enumerate(items, 1):
        if item_type == "restaurant":
            lines.append(restaurant_card(item, i, show_actions=False))
        else:
            lines.append(event_card(item, i, show_actions=False))
        lines.append("")

    if show_actions and len(items) > 0:
        lines.append("─" * 26)
        if item_type == "restaurant":
            lines.append("回复数字选择 → 预订")
            lines.append("回复「换一批」→ 其他推荐")
        else:
            lines.append("回复数字选择 → 报名")
            lines.append("回复「换一批」→ 其他推荐")

    return "\n".join(lines)


# ── 流程卡片 ──────────────────────────────────────────────

def payment_card(booking: Dict) -> str:
    """支付确认卡片"""
    lines = []
    lines.append(f"{'─' * 26}")
    lines.append(f"  💳 支付确认")
    lines.append(f"  {booking.get('venue', '')}")
    lines.append(f"  金额：¥{booking.get('estimated_cost', 0):.0f}")
    lines.append(f"  [模拟支付链接]")
    lines.append(f"{'─' * 26}")
    lines.append(f"回复「支付」确认  |  回复「取消」")
    return "\n".join(lines)


def reminder_card(booking: Dict, minutes_until: int = 0) -> str:
    """到店提醒卡片"""
    if minutes_until <= 30:
        urgency = "⚠️ 马上要到了！"
    elif minutes_until <= 60:
        urgency = f"⏰ 还有 {minutes_until} 分钟"
    else:
        urgency = f"🔔 还有 {minutes_until} 分钟"

    lines = []
    lines.append(f"{'─' * 26}")
    lines.append(f"  {urgency}")
    lines.append(f"  {booking.get('venue', '')}")
    lines.append(f"  🕐 {booking.get('time', '')}")
    lines.append(f"  👥 {booking.get('party_size', '')}位")
    if booking.get("location"):
        lines.append(f"  📍 {booking['location']}")
    lines.append(f"{'─' * 26}")
    lines.append(f"回复「导航」前往  |  回复「取消」")
    return "\n".join(lines)


def review_prompt_card(venue: str, date: str = "") -> str:
    """评价邀请卡片"""
    lines = []
    date_hint = f"（{date}）" if date else ""
    lines.append(f"💬 {venue}{date_hint}感觉怎么样？")
    lines.append(f"   随便说两句就行，帮我下次推荐更准")
    return "\n".join(lines)


# ── 对比展示 ──────────────────────────────────────────────

def versus_traditional_app(action: str) -> str:
    """展示对话式 vs 传统App的对比（演示用）"""
    comparisons = {
        "search": (
            "传统App：打开→搜索→筛选距离→筛选价格→筛选评分→浏览列表→点进详情",
            "Echo：「想吃日料，两个人，别太贵」→ 3个推荐",
        ),
        "booking": (
            "传统App：点预订→选日期→选时间→填人数→填手机号→确认→支付",
            "Echo：「帮我订第二家，明天晚上7点，4个人」→ 已预订",
        ),
        "review": (
            "传统App：找到订单→点评价→选星级→写文字→上传照片→提交",
            "Echo：「昨天那家不错，就是有点咸」→ 已记录，下次注意",
        ),
        "plan": (
            "传统App：分别打开美团+高德+日历，手动对比时间路线价格",
            "Echo：「周末带女朋友出去玩」→ 活动+餐厅+路线+日程一条龙",
        ),
    }

    if action not in comparisons:
        return ""

    traditional, conversational = comparisons[action]
    lines = [
        "📱 传统App vs 💬 对话式",
        f"{'─' * 26}",
        f"📱 {traditional}",
        f"💬 {conversational}",
        f"{'─' * 26}",
    ]
    return "\n".join(lines)
