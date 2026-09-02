---
name: food-finder
description: 本地美食与餐厅推荐——按口味、预算、场景、位置选店，默认取高德实时 POI，失败降级本地示例数据。触发场景：① 用户提到吃、餐厅、美食、饿了、午餐、晚餐、夜宵、火锅、烧烤、探店、附近有什么好吃的；② 用户对上一批推荐说换一家/就去这家/上次那家；③ 需要排除已去过的店。订座归 booking，玩的活动归 entertainment。
metadata: {"openclaw":{"emoji":"🍣","requires":{"bins":["python3"]}}}
---

# Food Finder Skill

## Description
本地生活美食推荐技能。根据用户的口味偏好、预算、位置、时间段等条件，推荐合适的餐厅。支持多轮对话细化需求，集成记忆系统学习用户偏好。

## Trigger
当用户提到：吃、餐厅、美食、饿了、午餐、晚餐、夜宵、火锅、烧烤、小吃等餐饮相关关键词时触发。

## ⚠️ 数据真实性硬约束
脚本**默认调高德实时数据**，失败才降级本地示例数据，返回体里的 `data_source` 就是这次数据的出处：
- `amap` → 真实数据，可以直接当真店/真活动/真路线报给用户
- `mock`（entertainment 还可能是 `mixed`，即两种混在一起）→ 含本地示例数据，**必须在回复里说明这是示例数据**，禁止说成「附近真有这家」
名称、地址、价格、评分、营业时间、路线时间与费用**一律照抄脚本输出**：禁止自己编、禁止补全脚本没给的字段、禁止把数字润色成整数。搜不到就说搜不到，不要拿印象里的店名凑数。

## Input Parameters
- `query` (string): 用户的自然语言描述，如"想吃辣的，人均50以内"
- `location` (string, optional): 用户位置或区域
- `budget` (string, optional): 人均预算范围
- `cuisine` (string, optional): 菜系偏好
- `time_of_day` (string, optional): 用餐时段 (breakfast/lunch/dinner/late_night)
- `mood` (string, optional): 用户当前心情或场景
- `environment` (string, optional): 环境偏好 (quiet/noisy/moderate)
- `family_friendly` (flag): 是否需要亲子友好
- `exclude_visited` (flag): 排除已去过的餐厅

## Script
```bash
# 搜索推荐
python {baseDir}/scripts/search_restaurants.py --query "<query>" --location "<location>" --budget "<budget>" --cuisine "<cuisine>"

# 排除已去过的
python {baseDir}/scripts/search_restaurants.py --query "<query>" --exclude_visited

# 记录用户选择（多轮对话）
python {baseDir}/scripts/search_restaurants.py --choice "<restaurant_name>"

# 记录一次实际访问
python {baseDir}/scripts/search_restaurants.py --visit "<restaurant_name>" --visit_rating 4.5

# 查看上次推荐
python {baseDir}/scripts/search_restaurants.py --recall
```

## Output
返回 JSON 格式的推荐结果：
- restaurant name, rating, price range, distance, cuisine type
- 推荐理由 (为什么推荐这家)
- 是否需要排队
- 偏好提示（基于历史学习）
- 可选操作：导航、预留座位

## Memory System
集成 `core/memory.py` 共享记忆模块：

### 自动记录
- 每次搜索自动记录交互历史
- 用户选择的餐厅会被学习为偏好

### 偏好学习
从用户选择中学习：
- 菜系偏好（如"喜欢潮汕火锅"）
- 环境偏好（如"喜欢安静的环境"）
- 预算偏好（如"中等消费"）
- 标签偏好（如"清淡、新鲜"）

### 多轮对话
- 支持"换一家" → 换一批推荐
- 支持"就去这家" → 记录选择
- 支持"上次那家" → 回忆上次推荐

### 访问去重
- `--exclude_visited` 自动排除已去过的餐厅
- 基于餐厅名称和 ID 双重匹配

## Multi-turn Support
支持用户追问：
- "有没有更安静的？" → 过滤环境噪音等级
- "带小孩方便吗？" → 过滤亲子友好
- "换一家试试" → 换一批推荐
- "上次那家也不错" → 回忆上次推荐
- "就去这家" → 记录选择，学习偏好
- "太辣了，不吃辣" → 排除含辣的餐厅

## 配图（推荐时必须执行）
每个推荐餐厅/菜品附带一张图片，提升推荐体验。

### 流程
1. 从推荐结果中提取餐厅名称和招牌菜名
2. 用 `web_search` 搜索图片：
   - 餐厅环境：`<餐厅名> 环境 实景图`
   - 招牌菜品：`<菜名> 美食图 高清`
3. 优先从结果中找直接图片 URL（.jpg/.png/.webp 后缀）
4. 用 `message` 工具发送图片，caption 写简短推荐理由
5. 多个推荐时并行搜索，不要串行等待

### 搜索策略
- 优先搜索环境图（用户更关心餐厅氛围）
- 有招牌菜的再搜一张菜品图
- 每家餐厅最多 1-2 张图，不要刷屏

### 兜底
- 搜不到图片时直接跳过，不要说「抱歉没找到图」
- 文字推荐照常输出，不受影响

### 可信图片源（web_search 时必须用 site: 限定）
- 餐厅环境/菜品：`<餐厅名> 美食图 site:dianping.com`
- 备选：`site:ctrip.com`（携程美食频道）
- 优先用可信站点的结果，不要用未知来源的图片

### ⚠️ 搜了就必须发（防浪费规则）
- 如果已经调用了搜索图片的操作并且拿到了可用的图片 URL，**必须用 message 工具把图发出去**
- 搜了不发 = 白搜，浪费了一次 API 调用和用户等待时间
- 这条规则不强制每次都搜图，但如果搜了就必须发

## Constraints
- 数据默认来自高德实时 POI，仅在 key 缺失或调用失败时降级本地示例数据（看 `data_source`）
- 不收集任何真实用户信息
- 推荐结果不超过 3 家，附带对比说明
- 历史记录保留最近 200 条

## 坑与降级
- **高德 key 缺失或超时** → 脚本静默降级 mock，不报错退出；唯一的判据是 `data_source`，别看输出「像真的」就当真的。
- **`--no_amap`** 可强制只用本地数据（演示、断网时用）。
- **位置解析优先级**：用户查询里的位置 > `config/amap_config.json` 的默认城市。用户没给位置也能跑，但结果是默认城市的，报的时候要说清是哪一片。
- **`--choice` 与 `--visit` 不是一回事**：`--choice` 只是这轮选中，`--visit` 才算真去过、才会进 `--exclude_visited` 的去重集合。
- 偏好与历史写在 `core/memory.py` 的共享库，food-finder / entertainment / review 共用一份，改一处三处都受影响。
