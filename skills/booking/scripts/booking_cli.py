#!/usr/bin/env python3
"""对话式预订管理 - 替代传统 App 表单流程

完整闭环：创建预订 → 模拟支付 → 日程联动 → 到店完成 → 触发评价
"""

import json
import os
import sys
import argparse
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
BOOKINGS_FILE = os.path.join(DATA_DIR, "bookings.json")

CALENDAR_CLI = os.path.join(
    PROJECT_ROOT, "skills", "calendar", "scripts", "calendar_cli.py"
)

# ── 数据读写 ──────────────────────────────────────────────

def _load_bookings() -> Dict:
    if not os.path.exists(BOOKINGS_FILE):
        return {"bookings": []}
    with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_bookings(data: Dict):
    os.makedirs(os.path.dirname(BOOKINGS_FILE), exist_ok=True)
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 预订操作 ──────────────────────────────────────────────

def create_booking(
    venue: str,
    date: str,
    time: str,
    party_size: int,
    contact: str = "",
    notes: str = "",
    venue_type: str = "restaurant",
    estimated_cost: float = 0,
    location: str = "",
    auto_calendar: bool = True,
) -> Dict:
    """创建预订"""
    data = _load_bookings()

    booking_id = f"BK{datetime.now().strftime('%m%d')}{str(uuid.uuid4())[:4].upper()}"

    booking = {
        "id": booking_id,
        "venue": venue,
        "venue_type": venue_type,
        "date": date,
        "time": time,
        "party_size": party_size,
        "contact": contact or "用户本人",
        "notes": notes,
        "estimated_cost": estimated_cost,
        "location": location,
        "status": "confirmed",
        "payment_status": "pending",
        "calendar_event_id": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    # 自动创建日程
    if auto_calendar and os.path.exists(CALENDAR_CLI):
        cal_desc = f"{date} {time} {venue}"
        if location:
            cal_desc += f" 地点:{location}"
        try:
            import subprocess
            result = subprocess.run(
                ["python3", CALENDAR_CLI, "add", cal_desc, "--location", location or venue],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                for line in output.split("\n"):
                    if "ID:" in line or "id:" in line:
                        event_id = line.split(":")[-1].strip()
                        booking["calendar_event_id"] = event_id
                        break
        except Exception:
            pass

    data["bookings"].append(booking)

    if len(data["bookings"]) > 100:
        data["bookings"] = data["bookings"][-100:]

    _save_bookings(data)
    return booking


def list_bookings(
    status: str = "",
    upcoming: bool = False,
    limit: int = 10,
) -> List[Dict]:
    """查看预订列表"""
    data = _load_bookings()
    bookings = data.get("bookings", [])

    if status:
        bookings = [b for b in bookings if b.get("status") == status]

    if upcoming:
        now = datetime.now()
        future = []
        for b in bookings:
            try:
                booking_dt = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
                if booking_dt > now and b.get("status") in ("confirmed", "paid"):
                    future.append(b)
            except (ValueError, KeyError):
                continue
        bookings = sorted(future, key=lambda b: f"{b['date']} {b['time']}")

    return bookings[-limit:]


def get_booking(booking_id: str) -> Optional[Dict]:
    """获取预订详情"""
    data = _load_bookings()
    for b in data.get("bookings", []):
        if b["id"] == booking_id:
            return b
    return None


def cancel_booking(booking_id: str = "", venue: str = "") -> Optional[Dict]:
    """取消预订"""
    data = _load_bookings()
    target = None

    for b in data.get("bookings", []):
        if booking_id and b["id"] == booking_id:
            target = b
            break
        if venue and venue in b.get("venue", "") and b.get("status") in ("confirmed", "paid"):
            target = b
            break

    if not target:
        return None

    target["status"] = "cancelled"
    target["updated_at"] = datetime.now().isoformat()

    # 同步取消日程
    if target.get("calendar_event_id") and os.path.exists(CALENDAR_CLI):
        try:
            import subprocess
            subprocess.run(
                ["python3", CALENDAR_CLI, "delete", target["calendar_event_id"]],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass

    _save_bookings(data)
    return target


def pay_booking(booking_id: str) -> Optional[Dict]:
    """模拟支付"""
    data = _load_bookings()
    target = None

    for b in data.get("bookings", []):
        if b["id"] == booking_id:
            target = b
            break

    if not target:
        return None

    if target.get("status") == "cancelled":
        return {"error": "预订已取消，无法支付"}

    target["payment_status"] = "paid"
    target["status"] = "paid"
    target["paid_at"] = datetime.now().isoformat()
    target["payment_method"] = "模拟支付"
    target["updated_at"] = datetime.now().isoformat()

    _save_bookings(data)
    return target


def complete_booking(booking_id: str) -> Optional[Dict]:
    """标记预订已完成（到店消费后）"""
    data = _load_bookings()
    target = None

    for b in data.get("bookings", []):
        if b["id"] == booking_id:
            target = b
            break

    if not target:
        return None

    target["status"] = "completed"
    target["completed_at"] = datetime.now().isoformat()
    target["updated_at"] = datetime.now().isoformat()

    _save_bookings(data)
    return target


def get_reminders() -> List[Dict]:
    """获取即将到来的预订（2小时内）"""
    now = datetime.now()
    window = now + timedelta(hours=2)
    upcoming = []

    data = _load_bookings()
    for b in data.get("bookings", []):
        if b.get("status") not in ("confirmed", "paid"):
            continue
        try:
            booking_dt = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
            if now <= booking_dt <= window:
                minutes_until = int((booking_dt - now).total_seconds() / 60)
                upcoming.append({**b, "minutes_until": minutes_until})
        except (ValueError, KeyError):
            continue

    return sorted(upcoming, key=lambda b: b.get("minutes_until", 999))


def auto_complete_past_bookings() -> List[Dict]:
    """自动标记已过时间的预订为已完成（预订时间超过30分钟后）"""
    now = datetime.now()
    data = _load_bookings()
    auto_completed = []

    for b in data.get("bookings", []):
        if b.get("status") not in ("confirmed", "paid"):
            continue
        try:
            booking_dt = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
            # 预订时间过了30分钟后自动标记完成
            if now > booking_dt + timedelta(minutes=30):
                b["status"] = "completed"
                b["completed_at"] = now.isoformat()
                b["auto_completed"] = True
                auto_completed.append(b)
        except (ValueError, KeyError):
            continue

    if auto_completed:
        _save_bookings(data)

    return auto_completed


def get_completed_without_review() -> List[Dict]:
    """获取已完成但未评价的预订"""
    data = _load_bookings()
    return [
        b for b in data.get("bookings", [])
        if b.get("status") == "completed" and not b.get("reviewed")
    ]


def mark_reviewed(booking_id: str):
    """标记预订已评价"""
    data = _load_bookings()
    for b in data.get("bookings", []):
        if b["id"] == booking_id:
            b["reviewed"] = True
            b["updated_at"] = datetime.now().isoformat()
            break
    _save_bookings(data)


# ── 格式化输出 ──────────────────────────────────────────────

def format_booking_card(booking: Dict) -> str:
    """格式化预订确认卡片"""
    status_map = {
        "confirmed": "已确认",
        "paid": "已支付",
        "completed": "已完成",
        "cancelled": "已取消",
    }
    payment_map = {
        "pending": "待支付",
        "paid": "已支付",
    }

    venue_emoji = {"restaurant": "🍽️", "entertainment": "🎭", "movie": "🎬"}.get(
        booking.get("venue_type", ""), "📋"
    )

    lines = []
    lines.append(f"{'─' * 28}")
    lines.append(f"  {venue_emoji} {booking['venue']}")
    lines.append(f"  📋 预订号：{booking['id']}")
    lines.append(f"  🕐 时间：{booking['date']} {booking['time']}")
    lines.append(f"  👥 人数：{booking['party_size']}位")

    if booking.get("location"):
        lines.append(f"  📍 地点：{booking['location']}")

    if booking.get("estimated_cost") and booking["estimated_cost"] > 0:
        lines.append(f"  💰 预估：¥{booking['estimated_cost']:.0f}")

    if booking.get("notes"):
        lines.append(f"  📝 备注：{booking['notes']}")

    lines.append(f"  📌 状态：{status_map.get(booking.get('status', ''), booking.get('status', ''))}")
    lines.append(f"  💳 支付：{payment_map.get(booking.get('payment_status', ''), booking.get('payment_status', ''))}")
    lines.append(f"{'─' * 28}")

    return "\n".join(lines)


def format_booking_list(bookings: List[Dict]) -> str:
    """格式化预订列表"""
    if not bookings:
        return "暂无预订记录"

    status_emoji = {
        "confirmed": "🟢",
        "paid": "💳",
        "completed": "✅",
        "cancelled": "❌",
    }

    lines = ["📋 预订记录：\n"]
    for i, b in enumerate(bookings, 1):
        emoji = status_emoji.get(b.get("status", ""), "📋")
        lines.append(f"{i}. {emoji} {b['venue']}")
        lines.append(f"   {b['date']} {b['time']} · {b['party_size']}位 · {b['id']}")
        if b.get("estimated_cost") and b["estimated_cost"] > 0:
            lines.append(f"   💰 预估 ¥{b['estimated_cost']:.0f}")
        lines.append("")

    return "\n".join(lines)


def format_reminder(reminders: List[Dict]) -> str:
    """格式化到店提醒"""
    if not reminders:
        return ""

    lines = []
    for r in reminders:
        mins = r.get("minutes_until", 0)
        if mins <= 30:
            urgency = "⚠️"
        elif mins <= 60:
            urgency = "⏰"
        else:
            urgency = "🔔"

        lines.append(f"{urgency} {r['venue']} - {r['time']}")
        lines.append(f"   还有 {mins} 分钟 · {r['party_size']}位")
        if r.get("location"):
            lines.append(f"   📍 {r['location']}")
        lines.append("")

    if lines:
        return "📋 即将到来的预订：\n\n" + "\n".join(lines)
    return ""


# ── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="预订管理")
    subparsers = parser.add_subparsers(dest="command", help="操作类型")

    # create
    p_create = subparsers.add_parser("create", help="创建预订")
    p_create.add_argument("--venue", required=True, help="餐厅/场所名称")
    p_create.add_argument("--date", required=True, help="日期 YYYY-MM-DD")
    p_create.add_argument("--time", required=True, help="时间 HH:MM")
    p_create.add_argument("--party_size", type=int, required=True, help="人数")
    p_create.add_argument("--contact", default="", help="联系方式")
    p_create.add_argument("--notes", default="", help="备注")
    p_create.add_argument("--venue_type", default="restaurant", help="场所类型")
    p_create.add_argument("--cost", type=float, default=0, help="预估费用")
    p_create.add_argument("--location", default="", help="地址")
    p_create.add_argument("--no_calendar", action="store_true", help="不创建日程")

    # list
    p_list = subparsers.add_parser("list", help="查看预订列表")
    p_list.add_argument("--status", default="", help="按状态筛选")
    p_list.add_argument("--upcoming", action="store_true", help="仅显示即将到来的")
    p_list.add_argument("--limit", type=int, default=10, help="数量限制")

    # detail
    p_detail = subparsers.add_parser("detail", help="预订详情")
    p_detail.add_argument("booking_id", help="预订 ID")

    # cancel
    p_cancel = subparsers.add_parser("cancel", help="取消预订")
    p_cancel.add_argument("booking_id", nargs="?", default="", help="预订 ID")
    p_cancel.add_argument("--venue", default="", help="按餐厅名取消")

    # pay
    p_pay = subparsers.add_parser("pay", help="模拟支付")
    p_pay.add_argument("booking_id", help="预订 ID")

    # complete
    p_complete = subparsers.add_parser("complete", help="标记已完成")
    p_complete.add_argument("booking_id", help="预订 ID")

    # remind
    subparsers.add_parser("remind", help="查看即将到来的预订提醒")

    # pending-reviews
    subparsers.add_parser("pending-reviews", help="查看待评价的预订")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "create":
        booking = create_booking(
            venue=args.venue,
            date=args.date,
            time=args.time,
            party_size=args.party_size,
            contact=args.contact,
            notes=args.notes,
            venue_type=args.venue_type,
            estimated_cost=args.cost,
            location=args.location,
            auto_calendar=not args.no_calendar,
        )
        print("✅ 预订成功！\n")
        print(format_booking_card(booking))
        if booking.get("calendar_event_id"):
            print(f"\n📋 已自动添加到日程")
        if booking.get("estimated_cost") and booking["estimated_cost"] > 0:
            print(f"\n💳 待支付 ¥{booking['estimated_cost']:.0f}")
            print(f"   回复「支付」完成付款")

    elif args.command == "list":
        bookings = list_bookings(
            status=args.status,
            upcoming=args.upcoming,
            limit=args.limit,
        )
        print(format_booking_list(bookings))

    elif args.command == "detail":
        booking = get_booking(args.booking_id)
        if booking:
            print(format_booking_card(booking))
        else:
            print(f"未找到预订：{args.booking_id}")

    elif args.command == "cancel":
        result = cancel_booking(
            booking_id=args.booking_id,
            venue=args.venue,
        )
        if result:
            print(f"✅ 已取消预订：{result['venue']}")
            if result.get("calendar_event_id"):
                print(f"📋 已同步取消日程")
        else:
            print("未找到匹配的预订")

    elif args.command == "pay":
        result = pay_booking(args.booking_id)
        if not result:
            print(f"未找到预订：{args.booking_id}")
        elif "error" in result:
            print(f"⚠️ {result['error']}")
        else:
            print(f"✅ 支付成功！")
            print(f"\n{format_booking_card(result)}")

    elif args.command == "complete":
        result = complete_booking(args.booking_id)
        if result:
            print(f"✅ 预订已完成：{result['venue']}")
            print(f"   感觉怎么样？回复评价帮我下次推荐更准")
        else:
            print(f"未找到预订：{args.booking_id}")

    elif args.command == "remind":
        reminders = get_reminders()
        output = format_reminder(reminders)
        if output:
            print(output)
        else:
            print("近期没有即将到来的预订")

    elif args.command == "pending-reviews":
        pending = get_completed_without_review()
        if pending:
            print("📝 以下预订已完成但未评价：\n")
            for b in pending:
                print(f"  - {b['venue']}（{b['date']}）· {b['id']}")
            print(f"\n回复评价帮我下次推荐更准！")
        else:
            print("没有待评价的预订")


if __name__ == "__main__":
    main()
