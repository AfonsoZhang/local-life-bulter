---
name: entertainment
description: 本地休闲娱乐推荐——电影、展览、演出、景点、周末活动，默认取高德实时 POI，失败降级本地示例数据。触发场景：① 用户提到电影、展览、演出、活动、景点、周末、好玩、放松、无聊、约会、带孩子去哪；② 用户对上一批推荐说换一个/就去这个/上次那个。吃饭归 food-finder，多个地点排时间线归 scheduler。
metadata: {"openclaw":{"emoji":"🎭","requires":{"bins":["python3"]}}}
---

# Entertainment Skill

## Description
本地休闲娱乐推荐技能。根据用户兴趣、时间、天气等推荐电影、展览、演出、活动等。集成记忆系统学习用户偏好。

## Trigger
当用户提到：电影、展览、演出、活动、周末、好玩、放松、无聊、约会等娱乐相关关键词时触发。

## ⚠️ 数据真实性硬约束
脚本**默认调高德实时数据**，失败才降级本地示例数据，返回体里的 `data_source` 就是这次数据的出处：
- `amap` → 真实数据，可以直接当真店/真活动/真路线报给用户
- `mock`（entertainment 还可能是 `mixed`，即两种混在一起）→ 含本地示例数据，**必须在回复里说明这是示例数据**，禁止说成「附近真有这家」
名称、地址、价格、评分、营业时间、路线时间与费用**一律照抄脚本输出**：禁止自己编、禁止补全脚本没给的字段、禁止把数字润色成整数。搜不到就说搜不到，不要拿印象里的店名凑数。

## Input Parameters
- `interest` (string, optional): 兴趣类型 (movie/exhibition/concert/sports/outdoor)
- `time_range` (string, optional): 时间范围 (today/this_weekend/this_week)
- `budget` (string, optional): 预算范围
- `companion` (string, optional): 同行人 (solo/couple/family/friends)
- `weather` (string, optional): 天气情况
- `query` (string, optional): 自然语言查询（多轮对话用）

## Script
```bash
# 搜索推荐
python {baseDir}/scripts/find_events.py --interest "<interest>" --time "<time_range>" --budget "<budget>" --companion "<companion>"

# 记录用户选择
python {baseDir}/scripts/find_events.py --choice "<event_name>"

# 记录一次实际参与
python {baseDir}/scripts/find_events.py --visit "<event_name>" --visit_rating 4.5

# 查看上次推荐
python {baseDir}/scripts/find_events.py --recall

# 获取景点/场所的 Wikipedia 图片和简介
python {baseDir}/../../core/wiki_image.py "<景点名称>"
```

## Output
返回推荐结果：
- 活动名称、时间、地点、价格、评分
- 推荐理由（为什么适合当前场景）
- 偏好提示（基于历史学习）
- 备选方案

## Memory System
集成 `core/memory.py` 共享记忆模块：
- 自动记录每次推荐交互
- 学习用户偏好的活动类型和标签
- 支持多轮对话（换一个、就去这个）
- 跨技能偏好共享（美食偏好也可用于推荐参考）

## Multi-turn Support
- "不想看电影了，还有别的吗？" → 切换推荐类型
- "室外的呢？" → 过滤户外活动
- "便宜点的" → 筛选低价活动
- "就去这个" → 记录选择
- "换一个" → 换一批推荐

## 配图（推荐时必须执行）
每个推荐活动附带一张图片，增强吸引力。

### 主力方案：Wikipedia API（景点/景区优先）
使用 `core/wiki_image.py` 获取图片，速度快、图片质量高、URL 稳定。

```bash
python {baseDir}/../../core/wiki_image.py "<景点名称>"
```

输出包含：`image_url`（直链）、`summary`（简介）、`wiki_url`（页面链接）。

- 景点/景区 → **必须用 wiki_image**，命中率高，图片质量最好
- 展览/演出场所 → 优先用 wiki_image，如有 Wikipedia 页面则命中
- 返回的 `image_url` 直接用 `message` 工具发送
- 多个推荐时并行调用脚本

### 兜底方案：web_search（电影/活动/无 Wikipedia 页面时）
当 wiki_image 返回 `found: false` 或推荐类型为电影/具体活动时，用 web_search 搜索，**必须用 `site:` 限定可信站点**：
- 景点：`<景点名> 实景图 site:ctrip.com` 或 `site:mafengwo.cn`
- 电影：`<电影名> 海报 site:douban.com`
- 演出/活动：`<活动名> site:damai.cn`
- 展览：`<展览名> site:douban.com`

从结果页面中提取图片 URL（.jpg/.png/.webp 后缀）。优先用可信站点的结果，不要用未知来源的图片。

### 发图规则
- 用 `message` 工具发送图片，caption 写简短推荐理由
- 每个活动最多 1 张图
- 搜不到图片时直接跳过，不要说「抱歉没找到图」
- 文字推荐照常输出，不受影响

### ⚠️ 搜了就必须发（防浪费规则）
- 如果已经调用了 `wiki_image.py` 并且返回 `found: true` 且 `image_url` 不为空，**必须用 message 工具把这张图发出去**
- 搜了不发 = 白搜，浪费了一次 API 调用和用户等待时间
- 发图和文字推荐可以同时进行，但图片不能省略
- 这条规则不强制每次都搜图，但如果搜了就必须发

## Constraints
- 活动数据默认来自高德实时 POI，失败降级本地示例数据（看 `data_source`：`amap` / `mixed` / `mock`）
- 不收集任何真实用户信息
- **微信 emoji 约束：** 禁止 📆 🔢（带数字），日程/时间统一用 📅 📋 🕐 ⏰ 📌

## 坑与降级
- **`data_source` 会出现 `mixed`**：一批结果里既有高德实时的、也有本地示例的，此时**按含示例数据口径说**，不要笼统说「这些都是查到的真实活动」。
- 电影/具体演出这类没有 POI 的条目本来就来自本地数据集，票价与场次是示例值，不能当今日实际排片报。
- `wiki_image.py` 返回 `found: false` 才走 web_search 兜底；两条都空就跳过配图，不要向用户解释「没找到图」。
- 偏好与历史与 food-finder / review 共用 `core/memory.py`。
