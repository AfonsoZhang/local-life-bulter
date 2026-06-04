---
name: booking
description: 对话式预订管理 - 餐厅/活动预订、模拟支付、自动日程联动
metadata: {"openclaw":{"emoji":"📋","requires":{"bins":["python3"]}}}
---

# Booking Skill

## Description
对话式预订技能。通过自然语言完成餐厅预订、活动报名等操作，替代传统 App 的表单填写流程。自动关联日程管理，模拟支付闭环。

## Trigger
当用户提到：订、预订、预约、留座、报名、定位子、订餐、book 等预订相关关键词时触发。
也在用户通过 food-finder / entertainment 选定目标后自动衔接。

## ⚠️ 预订流程约束（硬约束）

### 必须确认的字段
预订前**必须**拥有以下信息，缺一不可：
- **目标**：餐厅名/活动名（从上次推荐中获取或用户直接说）
- **时间**：具体日期和时段（必须用 date_resolver.py 解析）
- **人数**：几位

### 流程
1. 从对话中提取已有信息
2. 缺少信息时**逐项补问**，不要一次问三个问题
3. 信息完整后，生成预订确认卡片
4. 用户确认后执行预订
5. 自动创建日程条目
6. 生成模拟支付信息（如需要）

### 禁止
- 禁止在信息不完整时直接创建预订
- 禁止跳过确认步骤
- 禁止自行推断时间（必须用 date_resolver.py）

### 日期解析 fallback（硬约束）
用户提到的时间描述必须经过 `date_resolver.resolve_date()` 转换为 ISO 日期后才能使用。
- **解析成功** → 用返回的 ISO 日期继续流程
- **解析失败（返回 None）** → 向用户反问具体日期，禁止自行猜测。示例回复："你说的具体是哪天？给我一个日期就行，比如'6月10号'或者'下周六'"
- **模糊表达**（"月底"、"端午节"、"有空的时候"）→ 同样反问，不要自行推算节假日或模糊时间

## Script
```bash
# 创建预订
python {baseDir}/scripts/booking_cli.py create --venue "<餐厅/场所名>" --date "<YYYY-MM-DD>" --time "<HH:MM>" --party_size <人数> --contact "<联系方式>" --notes "<备注>"

# 查看预订列表
python {baseDir}/scripts/booking_cli.py list
python {baseDir}/scripts/booking_cli.py list --status pending
python {baseDir}/scripts/booking_cli.py list --upcoming

# 查看预订详情
python {baseDir}/scripts/booking_cli.py detail <booking_id>

# 取消预订
python {baseDir}/scripts/booking_cli.py cancel <booking_id>
python {baseDir}/scripts/booking_cli.py cancel --venue "<餐厅名>"

# 模拟支付
python {baseDir}/scripts/booking_cli.py pay <booking_id>

# 标记已完成（到店消费后）
python {baseDir}/scripts/booking_cli.py complete <booking_id>

# 查看即将到来的预订（用于提醒）
python {baseDir}/scripts/booking_cli.py remind
```

## Output
返回结构化预订信息：
- 预订确认卡片（场所、时间、人数、预估费用）
- 支付状态和模拟支付链接
- 自动创建的日程条目 ID
- 到店提醒信息

## 与其他技能联动

### food-finder → booking
用户说"就去这家" → food-finder 记录选择 → 自动询问是否预订

### entertainment → booking
用户选定活动 → 自动询问是否报名/购票

### booking → calendar
预订成功 → 自动在日历中创建对应日程

### booking → review
预订完成（到店后）→ 触发 review 技能主动询问体验

## Constraints
- 所有数据为模拟数据，不调用真实预订 API
- 不收集真实用户个人信息
- 联系方式使用模拟数据或用户显式输入
- 支付为模拟流程，不涉及真实交易
