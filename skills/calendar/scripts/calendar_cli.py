#!/usr/bin/env python3
"""日历 CLI 工具 — 给 Agent 用的日程查询/管理接口

用法：
  python calendar_cli.py list [--days N] [--date YYYY-MM-DD]
  python calendar_cli.py free [--date YYYY-MM-DD]
  python calendar_cli.py add "周六下午3点到5点开会" [--location 地点]
  python calendar_cli.py delete <event_id>
  python calendar_cli.py update <event_id> [--title 标题] [--location 地点]
  python calendar_cli.py check "2026-05-26T15:00:00" "2026-05-26T17:00:00"
  python calendar_cli.py import <file.ics>
  python calendar_cli.py today
  python calendar_cli.py tomorrow
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta

# 把 core/ 加入 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from cal_manager import (
    add_event, list_events, delete_event, update_event,
    complete_event, due_reminders,
    check_conflict, find_free_slots, parse_and_add,
    import_ical_file, format_events, format_free_slots,
    format_conflict_info, format_event,
    _load_calendar, _save_calendar,
)


def cmd_list(args):
    """查询日程"""
    if args.date:
        events = list_events(start_date=args.date + "T00:00:00",
                             end_date=args.date + "T23:59:59")
        label = args.date
    else:
        events = list_events(days_ahead=args.days)
        label = f"未来{args.days}天"

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(format_events(events, f"{label}日程"))


def cmd_today(args):
    """今天日程"""
    today = datetime.now().strftime("%Y-%m-%d")
    events = list_events(start_date=today + "T00:00:00",
                         end_date=today + "T23:59:59")
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(format_events(events, "今日日程"))


def cmd_tomorrow(args):
    """明天日程"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    events = list_events(start_date=tomorrow + "T00:00:00",
                         end_date=tomorrow + "T23:59:59")
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(format_events(events, "明日日程"))


def cmd_free(args):
    """空闲时段"""
    date = args.date or ""
    slots = find_free_slots(date=date)
    if args.json:
        print(json.dumps(slots, ensure_ascii=False, indent=2))
    else:
        print(format_free_slots(slots, args.date))


def cmd_add(args):
    """添加日程"""
    result = parse_and_add(args.description)
    if "error" in result:
        print(json.dumps({"ok": False, "error": result["error"]}, ensure_ascii=False))
        sys.exit(1)
    else:
        # 结构化 JSON 输出，含 event_id，供 Agent 校验
        output = {
            "ok": True,
            "event_id": result.get("id", ""),
            "title": result.get("title", ""),
            "start_time": result.get("start_time", ""),
            "end_time": result.get("end_time", ""),
            "location": result.get("location", ""),
        }
        print(json.dumps(output, ensure_ascii=False))


def cmd_delete(args):
    """删除日程"""
    if delete_event(args.event_id):
        print(f"✅ 已删除日程 {args.event_id}")
    else:
        print(f"❌ 找不到日程 {args.event_id}")
        sys.exit(1)


def cmd_update(args):
    """更新日程"""
    kwargs = {}
    if args.title:
        kwargs["title"] = args.title
    if args.location:
        kwargs["location"] = args.location
    if args.description:
        kwargs["description"] = args.description

    result = update_event(args.event_id, **kwargs)
    if result:
        print("✅ 已更新：")
        print(format_event(result))
    else:
        print(f"❌ 找不到日程 {args.event_id}")
        sys.exit(1)


def cmd_check(args):
    """冲突检测"""
    conflicts = check_conflict(args.start, args.end)
    if args.json:
        print(json.dumps(conflicts, ensure_ascii=False, indent=2))
    else:
        print(format_conflict_info(conflicts))


def cmd_import(args):
    """导入 iCal"""
    if not os.path.exists(args.file):
        print(f"❌ 文件不存在：{args.file}")
        sys.exit(1)
    imported = import_ical_file(args.file)
    if imported:
        print(f"✅ 导入了 {len(imported)} 个日程：")
        for e in imported:
            print(format_event(e))
            print()
    else:
        print("没有新日程需要导入（可能已存在或文件为空）")


def cmd_cancel(args):
    """智能取消日程 — 通过关键词匹配，无需知道 event_id"""
    events = _load_calendar()
    if not events:
        print("📋 当前没有任何日程")
        return

    keyword = args.match.strip() if args.match else ""
    matched = []

    if args.next:
        # 取消最近一个未来的日程
        now = datetime.now().isoformat()
        future = [e for e in events if e.get("start_time", "") >= now]
        if future:
            future.sort(key=lambda x: x.get("start_time", ""))
            matched = [future[0]]
    elif args.today:
        # 取消今天所有日程
        today = datetime.now().strftime("%Y-%m-%d")
        matched = [e for e in events
                   if e.get("start_time", "").startswith(today)]
    elif keyword:
        # 模糊匹配标题/地点/描述
        kw = keyword.lower()
        matched = [e for e in events
                   if kw in e.get("title", "").lower()
                   or kw in e.get("location", "").lower()
                   or kw in e.get("description", "").lower()]

    if not matched:
        if keyword:
            print(f"❌ 没找到包含「{keyword}」的日程")
        else:
            print("❌ 没有匹配的日程")
        sys.exit(1)

    # 执行删除
    deleted = []
    remaining = []
    deleted_ids = {e["id"] for e in matched}
    for e in events:
        if e["id"] in deleted_ids:
            deleted.append(e)
        else:
            remaining.append(e)
    _save_calendar(remaining)

    # 输出结果
    if len(deleted) == 1:
        e = deleted[0]
        try:
            start = datetime.fromisoformat(e["start_time"])
            time_str = start.strftime("%m月%d日 %H:%M")
        except (ValueError, KeyError):
            time_str = ""
        print(f"✅ 已取消：{e['title']}" + (f"（{time_str}）" if time_str else ""))
    else:
        print(f"✅ 已取消 {len(deleted)} 个日程：")
        for e in deleted:
            print(f"  · {e['title']}")

    if args.json:
        print(json.dumps(deleted, ensure_ascii=False, indent=2))


def cmd_complete(args):
    """标记日程为已完成 — 关键词模糊匹配，无需 event_id。

    与 cancel 不同：完成是保留历史的状态变更（status=done），
    不删除数据，且完成后不再触发提醒。
    """
    events = _load_calendar()
    active = [e for e in events if e.get("status", "pending") == "pending"]
    if not active:
        print("📋 当前没有待办日程")
        return

    keyword = (args.match or "").strip()
    matched = []

    if args.next:
        # 完成最近一个未来（或进行中）的日程
        now = datetime.now().isoformat()
        upcoming = [e for e in active if e.get("end_time", "") >= now]
        if upcoming:
            upcoming.sort(key=lambda x: x.get("start_time", ""))
            matched = [upcoming[0]]
    elif args.today:
        today = datetime.now().strftime("%Y-%m-%d")
        matched = [e for e in active if e.get("start_time", "").startswith(today)]
    elif keyword:
        kw = keyword.lower()
        matched = [e for e in active
                   if kw in e.get("title", "").lower()
                   or kw in e.get("location", "").lower()
                   or kw in e.get("description", "").lower()]

    if not matched:
        if keyword:
            print(f"❌ 没找到包含「{keyword}」的待办日程")
        else:
            print("❌ 没有匹配的待办日程")
        sys.exit(1)

    completed = []
    for e in matched:
        result = complete_event(e["id"])
        if result:
            completed.append(result)

    if len(completed) == 1:
        e = completed[0]
        try:
            start = datetime.fromisoformat(e["start_time"])
            time_str = start.strftime("%m月%d日 %H:%M")
        except (ValueError, KeyError):
            time_str = ""
        print(f"✅ 已完成：{e['title']}" + (f"（{time_str}）" if time_str else ""))
    else:
        print(f"✅ 已完成 {len(completed)} 个日程：")
        for e in completed:
            print(f"  · {e['title']}")

    if args.json:
        print(json.dumps(completed, ensure_ascii=False, indent=2))


def cmd_due(args):
    """输出当前到期、应当提醒的日程（供定时提醒任务调用）。

    默认会把返回的日程标记为已提醒，确保每个日程至多提醒一次；
    用 --peek 可只查看不标记。无到期日程时输出空数组 []。
    """
    due = due_reminders(mark=not args.peek)
    print(json.dumps(due, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="日历 CLI 工具")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="查询日程")
    p_list.add_argument("--days", type=int, default=7, help="查询未来几天（默认7）")
    p_list.add_argument("--date", type=str, help="指定日期 YYYY-MM-DD")

    # today
    sub.add_parser("today", help="今日日程")

    # tomorrow
    sub.add_parser("tomorrow", help="明日日程")

    # free
    p_free = sub.add_parser("free", help="空闲时段")
    p_free.add_argument("--date", type=str, help="指定日期 YYYY-MM-DD")

    # add
    p_add = sub.add_parser("add", help="添加日程")
    p_add.add_argument("description", help="自然语言描述，如 '周六下午3点开会'")
    p_add.add_argument("--location", type=str, help="地点")

    # delete
    p_del = sub.add_parser("delete", help="删除日程")
    p_del.add_argument("event_id", help="日程 ID")

    # update
    p_upd = sub.add_parser("update", help="更新日程")
    p_upd.add_argument("event_id", help="日程 ID")
    p_upd.add_argument("--title", type=str, help="新标题")
    p_upd.add_argument("--location", type=str, help="新地点")
    p_upd.add_argument("--description", type=str, help="新描述")

    # check
    p_chk = sub.add_parser("check", help="冲突检测")
    p_chk.add_argument("start", help="开始时间 ISO 格式")
    p_chk.add_argument("end", help="结束时间 ISO 格式")

    # import
    p_imp = sub.add_parser("import", help="导入 .ics 文件")
    p_imp.add_argument("file", help=".ics 文件路径")

    # cancel
    p_cancel = sub.add_parser("cancel", help="智能取消日程（模糊匹配）")
    p_cancel.add_argument("match", nargs="?", default="", help="匹配关键词，如 '医院'、'开会'")
    p_cancel.add_argument("--today", action="store_true", help="取消今天所有日程")
    p_cancel.add_argument("--next", action="store_true", help="取消最近一个未来日程")

    # complete
    p_done = sub.add_parser("complete", help="标记日程已完成（模糊匹配，保留历史、不再提醒）")
    p_done.add_argument("match", nargs="?", default="", help="匹配关键词，如 '体检'、'还书'")
    p_done.add_argument("--today", action="store_true", help="完成今天所有日程")
    p_done.add_argument("--next", action="store_true", help="完成最近一个待办日程")

    # due
    p_due = sub.add_parser("due", help="输出当前到期应提醒的日程（默认标记已提醒）")
    p_due.add_argument("--peek", action="store_true", help="只查看不标记已提醒")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    cmd_map = {
        "list": cmd_list,
        "today": cmd_today,
        "tomorrow": cmd_tomorrow,
        "free": cmd_free,
        "add": cmd_add,
        "delete": cmd_delete,
        "update": cmd_update,
        "check": cmd_check,
        "import": cmd_import,
        "cancel": cmd_cancel,
        "complete": cmd_complete,
        "due": cmd_due,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
