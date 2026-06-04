---
name: travel-planner
description: 本地出行规划 - 综合时间、费用、天气推荐最优路线
metadata: {"openclaw":{"emoji":"🗺️","requires":{"bins":["python3"]}}}
---

# Travel Planner Skill

## Description
本地出行规划技能。综合考虑时间、距离、费用、天气等因素，为用户推荐最优出行方案。集成记忆系统学习出行偏好。

## Trigger
当用户提到：怎么去、路线、出行、打车、地铁、公交、导航、路上、交通等关键词时触发。

## Input Parameters
- `origin` (string): 出发地
- `destination` (string): 目的地
- `time` (string, optional): 出发时间或到达时间
- `mode` (string, optional): 出行方式偏好 (walk/bus/subway/taxi/drive)
- `priority` (string, optional): 优先考虑 (cost/time/comfort)
- `query` (string, optional): 自然语言查询（多轮对话用）

## Script
```bash
# 出行规划
python {baseDir}/scripts/plan_route.py --origin "<origin>" --destination "<destination>" --time "<time>" --mode "<mode>"

# 按优先级排序
python {baseDir}/scripts/plan_route.py --origin "<origin>" --destination "<destination>" --priority "cost"

# 记录用户选择
python {baseDir}/scripts/plan_route.py --origin "<origin>" --destination "<destination>" --choice "地铁"

# 查看上次推荐
python {baseDir}/scripts/plan_route.py --origin "x" --destination "y" --recall

# 获取景点/目的地的 Wikipedia 图片和简介
python {baseDir}/../core/wiki_image.py "<景点名称>"
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
python {baseDir}/../core/wiki_image.py "<景点名称>"
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
- 所有路线数据基于模拟数据集
- 不收集真实位置信息
