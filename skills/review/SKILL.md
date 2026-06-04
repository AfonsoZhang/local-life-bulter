---
name: review
description: 对话式评价系统 - 用自然语言替代传统打分+写评论的 UI
metadata: {"openclaw":{"emoji":"💬","requires":{"bins":["python3"]}}}
---

# Review Skill

## Description
对话式评价技能。用户随口一句话就能完成评价，替代传统 App 中"打星 + 写评论 + 上传照片"的多步骤流程。评价结果自动融入偏好学习系统，直接影响下次推荐。

## Trigger
- 用户主动评价："上次那家不错"、"那个烧烤太咸了"、"昨天的电影一般"
- 预订完成后主动询问
- 心跳任务中检测到待评价的已完成预订

## ⚠️ 评价交互约束

### 主动询问规则
- 预订完成当天或次日，**主动询问一次**体验如何
- 用户回复后立即记录，**不要追问细节**
- 用户不回复或说"还行"/"一般" → 记录中性评价，不追问

### 评价解析
从自然语言中提取：
- **情感倾向**：正面/中性/负面
- **具体属性**：口味、服务、环境、价格、位置等
- **关键词**：辣、咸、安静、排队、便宜等

### 禁止
- 禁止要求用户打1-5星（这是传统App的交互方式）
- 禁止要求用户写长评（简短对话就够了）
- 禁止同一次体验反复追问

## Script
```bash
# 记录评价（从自然语言解析）
python {baseDir}/scripts/review_cli.py add --venue "<餐厅/活动名>" --comment "<用户原话>" --skill "<food-finder|entertainment>"

# 记录评价并关联预订
python {baseDir}/scripts/review_cli.py add --venue "<名称>" --comment "<评价>" --booking_id "<BK...>"

# 查看评价历史
python {baseDir}/scripts/review_cli.py list
python {baseDir}/scripts/review_cli.py list --venue "<名称>"
python {baseDir}/scripts/review_cli.py list --sentiment negative

# 查看待评价列表（关联 booking）
python {baseDir}/scripts/review_cli.py pending

# 偏好影响摘要
python {baseDir}/scripts/review_cli.py impact
```

## Output
- 评价确认消息（简短，一句话）
- 偏好更新提示（如"记住了，下次少推荐辣的"）
- 评价历史列表

## 与偏好学习的关系

### 正面评价 → 强化偏好
"那家日料很好吃" → preferred_cuisines["日料"] 权重 +1

### 负面评价 → 抑制偏好
"太辣了受不了" → rejected_food_tags["辣"] 权重 +1
"环境太吵" → rejected_environments["noisy"] +1

### 属性评价 → 细化偏好画像
"服务特别好" → preferred_food_tags["服务好"] +1
"性价比高" → preferred_budgets["low/medium"] +1

## 与其他技能联动

### booking → review
预订标记 complete → review 检测到待评价 → 主动询问

### review → memory.py
评价结果 → 调用 record_rejection() 或 _update_preferences_from_choice()

### review → food-finder / entertainment
下次推荐时，search() 自动读取更新后的偏好

## Constraints
- 不收集真实用户信息
- 评价数据仅用于本地偏好学习
- 保留最近 200 条评价记录
