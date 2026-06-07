---
name: calendar
description: 日历日程管理 - 查询、添加、删除日程，冲突检测，空闲时段查询
metadata: {"openclaw":{"emoji":"📅","requires":{"bins":["python3"]}}}
---

# Calendar Skill

## Description
日历日程管理技能。基于 `core/cal_manager.py` 提供日程的增删改查、冲突检测、空闲时段查询。所有操作通过 CLI 工具完成，不直接读写 JSON 文件。

## Trigger
当用户提到：日程、日历、安排、提醒、空闲、忙不忙、有没有事、冲突等时间管理相关关键词时触发。

## ⚠️ 重要：禁止直接读写 calendar.json
**永远不要**用 `read`、`find`、`cat` 等方式直接读取 `calendar.json`。
**必须**通过下方的 CLI 工具操作日历。

## ⚠️ 数据呈现约束（硬约束）

播报输出中的日期、时间、地点等事实性数据，必须沿用脚本原文，禁止模型自行推算或转述。

- 脚本说"周六"，回复就必须写"周六"，不能自己改成"周五"
- 日程、天气等数据，直接引用或精简原文，不要重新组织事实
- 如果需要引用日期/时间，从工具输出中逐字复制，不要凭记忆或推算

**原因：** 模型在转述事实数据时会产生幻觉（hallucination），尤其是日期、星期、数字。沿用原文可以彻底消除这类错误。

### 微信 emoji 约束
禁止输出带数字的 emoji：❌ 📆 🔢
日程/时间统一用：✅ 📅 📋 🕐 ⏰ 📌

## ⚠️ 日期解析 fallback（硬约束）
用户提到的自然语言日期必须经过 `date_resolver.resolve_date()` 或 `cal_manager` 内部调用链解析。
- **解析成功** → 用返回的 ISO 日期继续流程
- **解析失败（返回 None）** → 向用户反问具体日期，禁止自行推算。示例："你说的具体是哪天？给我一个日期就行，比如'6月10号'或者'下周六'"
- **模糊表达**（"月底"、"端午节"、"有空的时候"）→ 同样反问，不要自行推算节假日或模糊时间
- **禁止** LLM 自行执行"今天是周一所以下周三是X号"这类推算

## Script
```bash
# 查询日程
python {baseDir}/scripts/calendar_cli.py today
python {baseDir}/scripts/calendar_cli.py tomorrow
python {baseDir}/scripts/calendar_cli.py list --days 7
python {baseDir}/scripts/calendar_cli.py list --date 2026-05-26

# 查询空闲时段
python {baseDir}/scripts/calendar_cli.py free
python {baseDir}/scripts/calendar_cli.py free --date 2026-05-26

# 添加日程（自然语言）
python {baseDir}/scripts/calendar_cli.py add "周六下午3点到5点开会" --location "公司会议室"

# 删除日程
python {baseDir}/scripts/calendar_cli.py delete <event_id>

# 更新日程
python {baseDir}/scripts/calendar_cli.py update <event_id> --title "新标题" --location "新地点"

# 冲突检测
python {baseDir}/scripts/calendar_cli.py check "2026-05-26T15:00:00" "2026-05-26T17:00:00"

# 导入 iCal 文件
python {baseDir}/scripts/calendar_cli.py import /path/to/file.ics

# 智能取消日程（模糊匹配，无需 event_id）
python {baseDir}/scripts/calendar_cli.py cancel "医院"      # 匹配标题/地点/描述含「医院」的日程
python {baseDir}/scripts/calendar_cli.py cancel "开会"      # 匹配含「开会」的日程
python {baseDir}/scripts/calendar_cli.py cancel --next    # 取消最近一个未来日程
python {baseDir}/scripts/calendar_cli.py cancel --today   # 取消今天所有日程

# 输出 JSON 格式（方便程序处理）
python {baseDir}/scripts/calendar_cli.py --json today
python {baseDir}/scripts/calendar_cli.py --json list --days 3
```

## Output
默认输出格式化文本（适配微信），加 `--json` 参数输出 JSON。

## Constraints
- 所有日历操作必须通过 CLI 工具，不直接操作 JSON 文件
- 查询类操作用 `exec` 工具调用上面的脚本
- 添加/删除/更新操作也通过 `exec` 调用

## ⚠️ 日程创建约束（硬约束）

创建日程时，**必须先确认时间再创建**：

- 如果用户明确说了时间（如"明天下午3点"）→ 直接创建
- 如果用户没说时间或表达模糊（如"明天建个日程思考XX"）→ **必须先建议时间，等用户确认后再创建**
- 建议格式："建议安排在XX点到XX点，时间要调吗？"
- **禁止：** 自行推断时间后直接创建。宁可问一句，不要猜。

`calendar_cli.py add` 输出 JSON 格式，含 `event_id`。**只有工具返回 `ok=true` 且有 `event_id` 时，才能回复"已创建"。禁止在工具返回前确认。**

## ⚠️ 日程取消约束（硬约束）

当用户表达完成/取消意图时（如"完成了"、"做完了"、"搞定了"、"不用了"、"取消"、"已经xxx了"等），**立即执行 cancel 命令，不要反问**：

```bash
python {baseDir}/scripts/calendar_cli.py cancel "<关键词>"
```

- 关键词来自用户原话（如"医院检查做完了" → 关键词"医院"）
- 如果无法确定关键词，用 `cancel --next` 取消最近一个日程
- 简短确认："已取消 ✅"
- **禁止：** 反问用户"要取消哪个"、"确认取消吗"。直接做。

## ⚠️ 日程创建防幻觉（硬约束）

`calendar_cli.py add` 始终输出结构化 JSON：
```json
{"ok": true, "event_id": "abc12345", "title": "开会", "start_time": "2026-06-05T15:00:00", "end_time": "2026-06-05T17:00:00", "location": ""}
```

### 校验规则
- **只有 `ok=true` 且有 `event_id` 时**，才能回复“已创建”
- **确认回复必须引用返回的 title 和 start_time**（沿用原文，不要自行格式化）
- **如果工具未返回 event_id 或 `ok=false`**，禁止编造“已创建”
- **禁止在工具调用结果返回前说“已创建”**

### 原因
LLM 存在“顺应性幻觉”——对话流程到了“该确认创建”的节点，会倾向于生成“已创建”，即使工具未实际执行。结构化 JSON + event_id 校验可根治此问题。

### 正确示例
```
✅ 已创建：开会，06月05日(周五) 15:00-17:00
```

### 错误示例
```
❌ "已创建" （工具未返回 event_id，禁止编造）
❌ 工具调用结果返回前就确认创建
```

---

## Broadcast（播报消息生成）

统一格式的早安/晚安/天气预警消息生成器。emoji 和格式全部写死在脚本中，模型只需调用脚本并原样发送输出。

```bash
# 早安播报（天气+今日日程+每日打卡提醒）
python {baseDir}/scripts/broadcast.py morning

# 晚安播报（明日天气+当日日程+每日打卡提醒）
python {baseDir}/scripts/broadcast.py evening

# 天气预警（异常天气时输出，正常时无输出）
python {baseDir}/scripts/broadcast.py alert
```

```bash
# 预订到店提醒（2小时内有预订时输出）
python {baseDir}/scripts/broadcast.py booking

# 待评价提醒（有已完成但未评价的预订时输出）
python {baseDir}/scripts/broadcast.py review

# 天气-日程冲突检测（恶劣天气+户外日程时输出）
python {baseDir}/scripts/broadcast.py weather-check
```

### 规则
- 调用脚本后，将输出**原样发送**给用户，不要添加、修改、省略任何内容
- alert/booking/review/weather-check 无输出时，表示没有需要提醒的内容，不要发送任何消息
- 脚本内部已处理：天气获取、日程查询、预订检查、emoji 分配、格式统一
