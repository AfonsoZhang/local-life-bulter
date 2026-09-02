---
name: travel-planner
description: 点到点出行方案对比——步行/公交/地铁/打车的时间、费用、距离对比与推荐，默认取高德路径规划，失败降级本地示例数据。触发场景：① 用户提到怎么去、路线、打车、地铁、公交、导航、多久到、路上；② 用户嫌贵或赶时间要换一个方案。把多个地点排成一整天归 scheduler。
metadata: {"openclaw":{"emoji":"🗺️","requires":{"bins":["python3"]}}}
---

# Travel Planner Skill

## Description
本地出行规划技能。综合考虑时间、距离、费用、天气等因素，为用户推荐最优出行方案。集成记忆系统学习出行偏好。

## Trigger
当用户提到：怎么去、路线、出行、打车、地铁、公交、导航、路上、交通等关键词时触发。

## ⚠️ 数据真实性硬约束
脚本**默认调高德实时数据**，失败才降级本地示例数据，返回体里的 `data_source` 就是这次数据的出处：
- `amap` → 真实数据，可以直接当真店/真活动/真路线报给用户
- `mock`（entertainment 还可能是 `mixed`，即两种混在一起）→ 含本地示例数据，**必须在回复里说明这是示例数据**，禁止说成「附近真有这家」
名称、地址、价格、评分、营业时间、路线时间与费用**一律照抄脚本输出**：禁止自己编、禁止补全脚本没给的字段、禁止把数字润色成整数。搜不到就说搜不到，不要拿印象里的店名凑数。

## Input Parameters
- `origin` (string): 出发地
- `destination` (string): 目的地
- `time`：**没有 --time 这个参数**，出发/到达时间随用户原话走 `--query` 传入
- `mode` (string, optional): 出行方式偏好 (walk/bus/subway/taxi/drive)
- `priority` (string, optional): 优先考虑 (cost/time/comfort)
- `query` (string, optional): 自然语言查询（多轮对话用）

## Script
```bash
# 出行规划
python {baseDir}/scripts/plan_route.py --origin "<origin>" --destination "<destination>" --mode "<mode>" --query "<用户原话，含出发时间等>"

# 按优先级排序
python {baseDir}/scripts/plan_route.py --origin "<origin>" --destination "<destination>" --priority "cost"

# 记录用户选择
python {baseDir}/scripts/plan_route.py --origin "<origin>" --destination "<destination>" --choice "地铁"

# 查看上次推荐
python {baseDir}/scripts/plan_route.py --origin "x" --destination "y" --recall

# 获取景点/目的地的 Wikipedia 图片和简介
python {baseDir}/../../core/wiki_image.py "<景点名称>"
```

## Output
返回对比方案：
- 多种出行方式的时间、费用、距离对比
- 推荐最优方案及理由
- 偏好提示（基于历史学习）
- 到达时间预估

## Memory System
集成 `core/memory.py` 共享记忆模块：
- 自动记录每次路线规划交互
- 学习用户偏好的出行方式
- 支持多轮追问调整

## Multi-turn Support
- "太贵了，有没有便宜点的？" → 优先推荐公交/地铁
- "赶时间" → 推荐最快方案
- "下雨了怎么办？" → 推荐打车
- "就坐这个" → 记录选择

## 配图（推荐景点时执行）
当推荐涉及景点/目的地时，附带一张图片。

### 主力方案：Wikipedia API
使用 `core/wiki_image.py` 获取图片，速度快、URL 稳定。

```bash
python {baseDir}/../../core/wiki_image.py "<景点名称>"
```

- 返回 `image_url` 直链，用 `message` 工具发送
- 同时返回 `summary`（简介）和 `wiki_url`（页面链接）
- 多个景点时并行调用

### 兜底：web_search
当 wiki_image 返回 `found: false` 时，用 web_search 搜索，**必须用 `site:` 限定可信站点**：
- `web_search("<景点名> 实景图 site:ctrip.com")`
- 备选：`site:mafengwo.cn`（马蜂窝）

从结果页面中提取图片 URL。优先用可信站点的结果，不要用未知来源的图片。

### 适用场景
- 推荐景点目的地时 → 必须用 wiki_image 搜图
- 纯路线规划（A到B）→ 不需要图
- 每个景点最多 1 张图
- 搜不到图片时直接跳过，文字推荐照常输出

### ⚠️ 搜了就必须发（防浪费规则）
- 如果已经调用了 `wiki_image.py` 并且返回 `found: true` 且 `image_url` 不为空，**必须用 message 工具把这张图发出去**
- 搜了不发 = 白搜，浪费了一次 API 调用和用户等待时间
- 这条规则不强制每次都搜图，但如果搜了就必须发

## Constraints
- 路线数据默认来自高德路径规划，失败降级本地示例路线（看 `data_source`）
- 不收集真实位置信息

## 坑与降级
- **`--origin` / `--destination` 必填**；地名解析不出来会降级到本地示例路线，此时时间与票价只是示例值，**必须说明**，禁止当实测报。
- 单纯 A→B 才走这里；用户要把一天里几个地方串起来，交给 `scheduler`（它自带出行时间矩阵与顺序优化）。
- 纯路线规划不配图，只有推荐景点目的地时才用 `wiki_image.py`。
