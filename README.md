# 🏠 全天候私人管家 — 基于 OpenClaw 的本地生活服务

> 通过自然语言对话，重新定义本地生活 App 的交互方式。

## 🎯 项目亮点

- **对话式交互**：不需要翻页筛选，说一句话就行
- **多轮对话**：支持追问、选择、换一批等细化交互，越聊越精准
- **记忆能力**：记住你的偏好，下次推荐更懂你
- **场景感知**：考虑天气、时间、同行人等因素
- **访问去重**：自动排除已去过的地方
- **偏好学习**：从你的选择和评价中学习口味、环境、预算偏好
- **天气感知**：下雨天自动推荐室内活动，好天气优先户外
- **时间过滤**：自动排除已过期活动，根据当前时段推荐餐厅
- **交叉联动**： "看完电影吃什么"自动串联多个技能

## 🛠 技能列表

| 技能 | 功能 | 状态 |
|------|------|------|
| 🍣 Food Finder | 美食推荐 — 按口味/预算/场景推荐餐厅 | ✅ 高德API |
| 🗺 Travel Planner | 出行规划 — 路线与出行方式推荐 | ✅ 高德API |
| 🎭 Entertainment | 休闲娱乐 — 电影/活动/展览推荐 | ✅ 高德API+模拟数据 |
| 📋 Booking | 对话式预订 — 餐厅/活动预订、模拟支付、日程联动 | ✅ |
| 📅 Calendar | 日程管理 — 增删改查、冲突检测、空闲查询 | ✅ |
| 💬 Review | 对话式评价 — 一句话完成评价并反哺偏好学习 | ✅ |
| 🧭 Scheduler | 智能行程编排 — 多地点排成最优时间线（出行优化+用餐插入+预算） | ✅ |

## 🚀 快速开始

### 0. 配置高德 API
```bash
# 在 config/amap_config.json 中填入你的 Key
{"key": "你的高德API Key"}

# 或通过环境变量
export AMAP_API_KEY=你的Key
```

### 1. 设置默认位置
```bash
# 设置你的默认位置（所有技能共用）
python skills/food-finder/scripts/search_restaurants.py --set_location "武林广场"

# 也可以在对话中指定位置
python skills/food-finder/scripts/search_restaurants.py --query "我在西湖附近有什么好吃的"
```

### 2. 测试脚本
```bash
# 美食推荐
python skills/food-finder/scripts/search_restaurants.py --query "辣的" --budget "中"

# 出行规划
python skills/travel-planner/scripts/plan_route.py --origin "家里" --destination "西湖景区"

# 休闲娱乐
python skills/entertainment/scripts/find_events.py --interest "电影" --companion "情侣"
```

### 3. 集成到 OpenClaw
将 skills/ 目录下的 Skill 配置到 OpenClaw，即可通过 IM 对话使用。

### 4. 交叉联动与行程编排
多技能联动由 Echo（OpenClaw agent）在对话中编排：理解意图 → 调用各技能搜候选 → 串联结果。
涉及多地点的行程，再交给排期器算最优时间线：

```bash
# 智能行程编排：候选活动+餐厅 → 最优时间线（出行优化+用餐插入+预算）
python skills/scheduler/scripts/schedule_cli.py --demo

# 从 stdin 喂候选 JSON
echo '{"events":[...],"lunch":[...],"start_hour":9}' \
  | python skills/scheduler/scripts/schedule_cli.py --input -
```

### 5. 记忆系统
```bash
# 查看交互历史
python core/memory.py history

# 查看偏好
python core/memory.py prefs

# 查看偏好摘要
python core/memory.py summary
```

## 📁 项目结构

```
local-life-butler/
├── README.md              # 项目说明（本文件）
├── DESIGN.md              # 设计文档（架构/技术亮点）
├── AGENTS.md              # 运行时约束位置说明（指针）
├── core/                  # 共享模块（不含 LLM，纯工具/算法）
│   ├── amap_api.py        # 高德地图（POI/路线/地理编码/天气/IP定位）
│   ├── memory.py          # 记忆模块（历史/偏好/时间衰减/场景化）
│   ├── cal_manager.py     # 日程管理底层
│   ├── date_resolver.py   # 日期解析（防 LLM 推算）
│   ├── location_cli.py    # 对话式默认地址（IP猜测+确认）
│   ├── scheduler.py       # 智能排期算法（出行矩阵+贪心+用餐+预算）
│   ├── schemas.py         # 统一数据模型（dataclass）
│   ├── weather.py         # 天气感知
│   ├── time_utils.py      # 时间感知（有效期/时段）
│   └── formatter.py       # 卡片式消息格式化（适配微信）
├── skills/                # 7 个技能，每个含 SKILL.md + 实现代码
│   ├── food-finder/       # 🍣 美食推荐
│   ├── travel-planner/    # 🗺 出行规划
│   ├── entertainment/     # 🎭 休闲娱乐
│   ├── booking/           # 📋 对话式预订 + 模拟支付
│   ├── calendar/          # 📅 日程管理 + 播报
│   ├── review/            # 💬 对话式评价
│   └── scheduler/         # 🧭 智能行程编排（schedule_cli.py）
└── config/                # 全部为模拟数据 / 用户显式输入
    ├── preferences.json   # 用户偏好（模拟 + 学习）
    ├── history.json       # 交互历史 + 访问记录
    ├── calendar.json      # 日程数据
    ├── amap_config.json   # 高德 API Key
    └── session_state.json # 多轮对话上下文
```

## 🔗 交叉联动架构

联动由 **Echo（OpenClaw agent）** 在对话中编排，不再依赖独立的规则引擎：

- **意图理解** → Echo 识别请求涉及哪些技能、串联顺序、场景（同行人/时段/预算）
- **偏好共享** → 各技能统一读写 `core/memory.py`，美食偏好会影响娱乐推荐
- **行程编排** → 多地点行程交给 `scheduler` 技能算最优时间线（出行优化 + 用餐插入 + 预算）
- **交易闭环** → 选定后可衔接 `booking`（预订+模拟支付）→ `calendar`（写日程）→ `review`（评价反哺偏好）

| 查询模式 | 串联方式 | 示例 |
|---------|---------|------|
| 活动+用餐 | entertainment → food-finder | "看完电影吃什么" |
| 一日行程 | entertainment + food-finder → scheduler | "周末带孩子出去玩" |
| 目的地推荐 | travel-planner + entertainment + food-finder | "去西湖有什么好玩的" |
| 约会/请客 | entertainment → food-finder → booking | "约会安排" |

## 💬 对话示例

> 演示"自然语言对话替代 App UI"：用户说人话，Echo 串联技能、给出结构化结果。

### 场景 1：交叉联动（活动 → 用餐）
```
用户：看完电影吃什么
Echo：为你规划了活动+用餐方案：

方案 1：《流浪地球 3》上映
   📍 万达影城  |  💰 ¥45  |  ⭐ 4.6
   🚗 步行 10 分钟
   🍽 看完吃什么：日式拉面·一兰（附近，⭐ 4.8）

方案 2：脱口秀开放麦
   📍 步行街小剧场  |  💰 ¥39  |  ⭐ 4.3
   🍽 看完吃什么：川味老火锅（附近，⭐ 4.5）

想选哪个方案？
```

### 场景 2：一日行程（多技能 + 排期）
```
用户：周末带孩子出去玩
Echo：为你规划了一天行程：

🏃 上午：亲子乐园·海洋球（万象城 3 楼）
🍜 午餐：万象城美食广场（亲子友好）
🏃 下午：城市艺术展·光影之间（市美术馆）
🍽 晚餐：潮汕牛肉火锅（清淡鲜美，适合家庭）

觉得怎么样？需要调整哪个环节？
```

### 场景 3：目的地推荐（出行 + 娱乐 + 美食）
```
用户：去西湖有什么好玩的，附近有啥吃的
Echo：西湖附近：

🚗 怎么去：打车 25 分钟 / 35 元
🎭 附近活动：1. 西湖游船（¥55，⭐ 4.5） 2. 城市艺术展（¥30，⭐ 4.3）
🍽 附近餐厅：1. 西湖边·楼外楼（杭帮菜，⭐ 4.6）

想去哪个？我帮你安排具体行程。
```

### 场景 4：单技能 + 偏好
```
用户：今晚吃什么
Echo：推荐 2 家：
1. 潮汕牛肉火锅（清淡，4.7 分，1.2km，人均 78）
2. 川味老火锅（微辣，4.5 分，0.8km，人均 65）
你想去哪家？
```

> 以上对话、店名、数据均为**示例/模拟**，用于演示交互范式。

## ⚠️ 数据说明

本项目所有数据均为**模拟数据**，不包含任何真实用户信息。
用于展示对话式本地生活服务的交互范式。

## 📝 技术栈

- **框架**: OpenClaw 2026.5.20（Agent 运行时 + Cron 调度 + IM 路由）
- **技能**: 7 个，遵循 OpenClaw 插件规范（SKILL.md + 实现代码）
- **脚本**: Python 3
- **数据**: JSON 模拟数据（不含任何真实用户信息）
- **交互**: IM 对话（微信为主，兼容 Telegram/Discord）

---

> 🔊 Echo — 你说，我听，我回应。
