# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## 微信格式规范

- 禁止 markdown 加粗（`**文字**`），微信不渲染，会原样显示
- 禁止 markdown 标题（`#`），用 emoji + 文字代替
- 推荐列表格式：序号后紧跟店名/项目名，不要被符号隔开
- 正确示例：`1. 餐厅名 ⭐4.6 | 人均80`
- 错误示例：`1. **餐厅名** ⭐4.6 | 人均80`

## 本地生活管家 - 可用函数

### core/date_resolver.py
- `resolve_date("下周周一")` → "2026-06-01"（禁止 LLM 自行推算日期）
- `resolve_date_range("下周")` → ("2026-06-01", "2026-06-05")
- `get_weekday("2026-06-01")` → "周一"
- CLI: `python3 core/date_resolver.py "下周周一"` / `--range "下周"`

### skills/scheduler/scripts/schedule_cli.py（智能行程编排）
- 把候选活动+餐厅排成最优时间线（出行矩阵+贪心排序+自动塞午晚餐+预算），纯算法不含 LLM
- 算法在 `core/scheduler.py` + `core/schemas.py`，本脚本是 管家 可调入口
- `echo '<json>' | python3 skills/scheduler/scripts/schedule_cli.py --input -` — 从 stdin 读（管家 常用）
- `python3 skills/scheduler/scripts/schedule_cli.py --input plan.json` / `--demo`
- 加 `--json` 输出结构化结果
- 输入 JSON：`{events:[{name,type,location:"lng,lat",duration_min,price_yuan,rating}], lunch:[...], dinner:[...], start_hour}`
- ⚠️ 用法详见 `skills/scheduler/SKILL.md`「行程编排」硬约束（多地点必须走它，禁止自己心算时间线）

### core/location_cli.py（对话式默认地址）
- `status [--json]` — 查看当前位置 + 来源（confirmed/ip_guess/default）
- `bootstrap [--force]` — 首次 IP 定位猜测（不覆盖已确认位置）
- `confirm "我在和谐广场"` — 用户确认/修正 → 标记 confirmed
- `confirm --city 济南 --location 和谐广场` — 直接指定
- ⚠️ ip_guess 是猜测，禁止当事实陈述，必须反问确认（详见 AGENTS.md「默认地址」）

### core/amap_api.py
- `get_location_state()` / `bootstrap_location(force)` / `confirm_location(query/city/location_name)` — 位置状态机
- `search_poi(keyword, city, location, radius)` — POI 搜索
- `search_poi_around(keyword, location, radius)` — 周边搜索
- `geocode(address)` — 地理编码
- `reverse_geocode(location)` — 逆地理编码
- `ip_location()` — IP 定位
- `get_weather_info(city)` — 天气实况
- `get_weather_forecast(city)` — 天气预报
- `plan_driving(origin, destination)` — 驾车路线
- `plan_transit(origin, destination)` — 公交路线
- `plan_walking(origin, destination)` — 步行路线
- `plan_bicycling(origin, destination)` — 骑行路线
- `resolve_location(query)` — 解析位置
- `load_user_location()` / `save_user_location()` — 用户位置

### skills/calendar/scripts/calendar_cli.py
- `add "自然语言描述"` — 添加日程（⚠️ 一个字符串，不要拆成多个参数）
- `list [--days N] [--date YYYY-MM-DD]` — 查询日程
- `delete <event_id>` — 删除
- `update <event_id> [--title] [--location]` — 更新
- `check "ISO时间" "ISO时间"` — 冲突检测
- `free [--date YYYY-MM-DD]` — 空闲时段
- `today` / `tomorrow` — 今天/明天日程

### core/wiki_image.py
- `get_wiki_image(query)` — 返回 dict: found/title/image_url/summary/wiki_url

### skills/booking/scripts/booking_cli.py
- `create --venue "<名称>" --date "YYYY-MM-DD" --time "HH:MM" --party_size N` — 创建预订
- `list` / `list --upcoming` / `list --status confirmed` — 查看预订
- `detail <booking_id>` — 预订详情
- `cancel <booking_id>` / `cancel --venue "<名称>"` — 取消预订
- `pay <booking_id>` — 模拟支付
- `complete <booking_id>` — 标记已完成（到店消费后）
- `remind` — 查看即将到来的预订（2小时内）
- `pending-reviews` — 查看已完成但未评价的预订

### skills/review/scripts/review_cli.py
- `add --venue "<名称>" --comment "<用户原话>"` — 记录评价（自动情感分析+偏好更新）
- `add --venue "<名称>" --comment "<评价>" --booking_id "<BK...>"` — 关联预订的评价
- `list` / `list --venue "<名称>"` / `list --sentiment negative` — 查看评价历史
- `pending` — 查看待评价列表
- `impact` — 评价对偏好的影响摘要

### core/formatter.py
- `restaurant_card(r, index)` — 餐厅推荐卡片
- `event_card(e, index)` — 活动推荐卡片
- `booking_card(b)` — 预订确认卡片
- `payment_card(b)` — 支付确认卡片
- `reminder_card(b, minutes)` — 到店提醒卡片
- `review_prompt_card(venue, date)` — 评价邀请卡片
- `recommendation_list(items, type)` — 推荐列表
- `versus_traditional_app(action)` — 对话式 vs 传统App对比（演示用）

### broadcast.py 新增模式
- `python broadcast.py booking` — 预订到店提醒（2h内有预订时输出）
- `python broadcast.py review` — 待评价提醒
- `python broadcast.py weather-check` — 天气-日程冲突检测

Add whatever helps you do your job. This is your cheat sheet.

## Related

- [Agent workspace](/concepts/agent-workspace)
