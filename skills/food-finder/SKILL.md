---
name: food-finder
description: 本地生活美食推荐 - 根据口味、预算、场景推荐餐厅
metadata: {"openclaw":{"emoji":"🍣","requires":{"bins":["python3"]}}}
---

# Food Finder Skill

## Description
本地生活美食推荐技能。根据用户的口味偏好、预算、位置、时间段等条件，推荐合适的餐厅。支持多轮对话细化需求，集成记忆系统学习用户偏好。

## Trigger
当用户提到：吃、餐厅、美食、饿了、午餐、晚餐、夜宵、火锅、烧烤、小吃等餐饮相关关键词时触发。

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
- 所有数据来自本地模拟数据集，不调用外部 API
- 不收集任何真实用户信息
- 推荐结果不超过 3 家，附带对比说明
- 历史记录保留最近 200 条
