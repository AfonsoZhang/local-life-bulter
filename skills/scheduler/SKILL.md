---
name: scheduler
description: 多地点行程编排——把 2 个及以上候选活动/餐厅算成一条含出行时间、游览顺序、午晚餐和预算的时间线，算法是纯代码不含 LLM。触发场景：① 用户说安排周末/某天、一日游、帮我规划行程、怎么玩、几个地方怎么排；② 已由 entertainment / food-finder 拿到多个候选、要落成时间表。单个地点或纯推荐不要走这里。
metadata: {"openclaw":{"emoji":"📋","requires":{"bins":["python3"]}}}
---

# Scheduler Skill

## Description
智能行程编排技能。当用户要"安排某天/一日游/规划行程"且涉及 **2 个及以上** 候选地点时，把候选交给排期器，由它计算出行时间、优化游览顺序、自动插入午晚餐、估算预算，输出一条微信友好的时间线。算法是纯代码（`core/scheduler.py`），不含 LLM。

## Trigger
当用户提到：安排周末/某天、一日游、帮我规划行程、怎么玩、路线安排、几个地方怎么排等，**且已有/将有多个候选地点**时触发。

## ⚠️ 核心硬约束：不要自己心算时间线
时间线 = 事实性数据（出行分钟、游览顺序、总花费），和日期、坐标一样——**必须从工具拿，禁止 LLM 自行推算**。
- **禁止**自己编造"X 点到 Y 点"的时间安排
- **禁止**把排期器算出的时间、花费改写成别的数字
- 多地点行程**一律**走 `schedule_cli.py`；单个地点或纯推荐不需要排期，直接答即可

## 流程
1. 先用 entertainment / food-finder 搜出候选（它们输出含 `location` 坐标的 JSON）
2. 组装成 schedule 输入 JSON，喂给排期器
3. 把输出**原样转发**给用户（已是微信格式），可在前面加一句自己的话

## Script
```bash
# 从 stdin 读候选 JSON（最常用）
echo '<候选JSON>' | python {baseDir}/scripts/schedule_cli.py --input -

# 从文件读
python {baseDir}/scripts/schedule_cli.py --input plan.json

# 结构化输出（程序处理用）
python {baseDir}/scripts/schedule_cli.py --input - --json

# 跑内置样例（济南一日游）
python {baseDir}/scripts/schedule_cli.py --demo
```

### 输入 JSON 结构
```json
{
  "events": [
    {"name":"趵突泉","type":"outdoor","location":"116.997,36.664",
     "duration_min":90,"price_yuan":40,"rating":4.7}
  ],
  "lunch":  [{"name":"草包包子铺","cuisine":"面食","location":"117.02,36.67"}],
  "dinner": [{"name":"城南往事","cuisine":"鲁菜"}],
  "start_hour": 9
}
```
- `events` 必填（≥1），`location` 用高德 "lng,lat" 字符串，缺坐标也能跑（降级到默认出行时间）
- `lunch`/`dinner`/`start_hour` 可选

## Output
默认输出格式化时间线文本（适配微信，已遵循禁 markdown 加粗/禁带数字 emoji），加 `--json` 输出结构化结果。

## 排期器做了什么（core/scheduler.py）
1. 并行用坐标计算活动间实际出行时间矩阵（高德 API，失败降级距离估算）
2. 贪心算法优化游览顺序，最小化总出行时间
3. 在 11:00-14:00 / 17:00-21:00 自动插入午/晚餐
4. 按营业时间校验，估算总预算
5. 输出带时间戳的完整时间线 + 统计摘要

## 与其他技能联动
- **entertainment / food-finder → scheduler**：搜出候选 → 排期成时间线
- **scheduler → booking**：用户对某条时间线满意 → 自然衔接"要帮你把这几家都订了吗"
- **scheduler → calendar**：确定行程后可逐项写入日历

## Constraints
- 所有排期通过 `schedule_cli.py`，不直接操作 scheduler.py 内部函数
- 用 `exec` 工具调用脚本，输出原样转发，禁止改写时间/花费

## 坑与降级
- **候选缺 `location` 也能跑**，但出行时间会退化成默认估算值；高德不可用时同样降级到距离估算。这两种情况下的分钟数是估算而非实测，别当准确路程报给用户。
- **只有一个地点就不要走这里**：直接答即可，走排期器反而会给出一条假的时间线。
- 输出已是微信格式（无 markdown 加粗、无数字 emoji），**原样转发**，不要重排、不要补 emoji、不要把时间改写成整点。
- 营业时间校验依赖候选自带字段，候选来自本地示例数据时营业时间也是示例值。
