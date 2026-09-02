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
python skills/food-finder/scripts/search_restaurants.py --set_location "泉城广场"

# 也可以在对话中指定位置
python skills/food-finder/scripts/search_restaurants.py --query "我在大明湖附近有什么好吃的"
```

### 2. 测试脚本
```bash
# 美食推荐
python skills/food-finder/scripts/search_restaurants.py --query "辣的" --budget "中"

# 出行规划
python skills/travel-planner/scripts/plan_route.py --origin "家里" --destination "趵突泉景区"

# 休闲娱乐
python skills/entertainment/scripts/find_events.py --interest "电影" --companion "情侣"
```

### 3. 集成到 OpenClaw
将 skills/ 目录下的 Skill 配置到 OpenClaw，即可通过 IM 对话使用。

### 4. 交叉联动与行程编排
多技能联动由 管家（基于 OpenClaw agent）在对话中编排：理解意图 → 调用各技能搜候选 → 串联结果。
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
├── AGENTS.md              # 运行时约束 + 技能路由收口层
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
│                          # 每个 SKILL.md 含：路由化 description / 硬约束 / 坑与降级
├── tools/                 # 规范闸门（check_skills.py + 装 pre-commit 的脚本）
├── .github/workflows/     # CI：skills-gate（静态校验）+ Claude Code（@claude 触发）
└── config/                # 用户侧数据（本地存储 / 用户显式输入）
    ├── preferences.json   # 用户偏好（模拟 + 学习）
    ├── history.json       # 交互历史 + 访问记录
    ├── calendar.json      # 日程数据
    ├── amap_config.json   # 高德 API Key
    └── session_state.json # 多轮对话上下文
```

## 🚦 技能规范与闸门

7 个 SKILL.md 是管家唯一的操作依据——它写错一条命令，管家就会照错的调一整轮。所以规范不靠自觉，靠一道机械闸门 `tools/check_skills.py`（纯静态校验，不调模型）：

| 规则 | 拦什么 |
|---|---|
| R1 | frontmatter 完整、`name` 与目录一致、`metadata` 是合法 JSON |
| R2 | `description` 必须写明触发场景——它是唯一常驻上下文的部分，正文命中后才加载 |
| R3 | 必须有硬约束段和「坑与降级」段 |
| R4/R5 | **文档写的脚本必须存在，写的子命令和 `--flag` 必须真在脚本源码里** |
| R6 | 不许引用不存在的技能 |
| R7 | `AGENTS.md` 的路由收口层必须覆盖全部技能 |

R4/R5 是核心：它抓的是文档与代码的漂移。上线时这道闸门当场抓出 3 处真实故障——两个技能的 `wiki_image.py` 路径少写一层（指向不存在的 `skills/core/`）、`plan_route.py` 的 `--time` 参数压根不存在（照文档跑直接 argparse 报错退出）。

```bash
python3 tools/check_skills.py     # 手动跑
bash tools/install_hooks.sh       # 装成 pre-commit，提交前自动拦
```

CI 上同样跑（`.github/workflows/skills-gate.yml`），8 秒出结果。

## 🔗 交叉联动架构

联动由 **管家（基于 OpenClaw agent）** 在对话中编排，不再依赖独立的规则引擎：

- **意图理解** → 管家识别请求涉及哪些技能、串联顺序、场景（同行人/时段/预算）
- **偏好共享** → 各技能统一读写 `core/memory.py`，美食偏好会影响娱乐推荐
- **行程编排** → 多地点行程交给 `scheduler` 技能算最优时间线（出行优化 + 用餐插入 + 预算）
- **交易闭环** → 选定后可衔接 `booking`（预订+模拟支付）→ `calendar`（写日程）→ `review`（评价反哺偏好）

| 查询模式 | 串联方式 | 示例 |
|---------|---------|------|
| 活动+用餐 | entertainment → food-finder | "看完电影吃什么" |
| 一日行程 | entertainment + food-finder → scheduler | "周末带孩子出去玩" |
| 目的地推荐 | travel-planner + entertainment + food-finder | "去趵突泉有什么好玩的" |
| 约会/请客 | entertainment → food-finder → booking | "约会安排" |

## 💬 对话示例

> 演示"自然语言对话替代 App UI"：用户说人话，管家串联技能、完成从推荐到交易的全流程。

### 场景 1：对话式交易闭环（找店 → 订 → 付 → 自动写日历）
```
用户：订今晚的海底捞，俩人
管家：好，帮你确认一下 👇
   🏪 海底捞（济南恒隆广场店）⭐4.7 · 人均 ¥120
   🕐 今天 19:00 · 2 位
   回复「确认」下单，或告诉我换时间 / 人数

用户：确认
管家：✅ 订好了！已自动写入你的日历，18:30 提醒你出发
   回复「支付」完成预订金 ¥50

用户：支付
管家：✅ 支付成功，订单号 BK20260605。到店报手机号即可
```
> 传统 App：搜店 → 选时段 → 填人数 → 确认 → 跳支付 → 手动记日历（6+ 步，跨 2 个 App）。管家：3 句话。

### 场景 2：越用越懂你（偏好学习）
```
用户：中午吃啥
管家：按你口味挑了 2 家（已自动避开「辣」和「要排队」的）：
   1. 怀石日料 ⭐4.6 · 人均 90 · 480m
   2. 鲁香源·鲁菜 ⭐4.5 · 人均 65 · 600m
用户：第一个不错，就是上次那家有点贵
管家：记下了，下次往人均 70 以内给你挑 👌
```
> 不用每次设置筛选条件——它从你的选择和评价里学，越用越准。

### 场景 3：全天候主动服务（不用你开口，管家替你盯着）
```
〔早 9:00 自动推送〕
☀️ 早安！济南今天晴 18~27℃，适合出门
📋 今日日程：14:00 山东省博物馆
🎯 别忘了今天的学习打卡

〔下午自动预警〕
⚠️ 你周六下午有「趵突泉露天写生」，但预报有阵雨
   要不要帮你改到室内场馆？
```
> 传统 App 都是你主动去查；管家通过 Cron 主动盯着天气、日程、预订、待评价。

### 场景 4：一句话排一天（多技能 + 智能排期）
```
用户：周六帮我安排一天，想去趵突泉那边
管家：📋 周六行程（已按出行最优排序）
   09:00-10:30  趵突泉 ⭐4.7 · ¥40
   🚲 骑行 12 分钟
   10:42-12:00  五龙潭公园 ⭐4.5
   🍜 12:00 午餐：草包包子铺（步行 5 分钟）
   14:00-16:00  山东省博物馆 ⭐4.8 · 免费
   ──────────────
   总出行 25 分钟 · 预计花费 ¥130
   要顺便把午餐订了吗？
```
> 出行顺序、时间、预算都是算出来的（`scheduler` 排期器），不是模型编的。

> 以上对话、店名、数据均为**示例 / 模拟**，用于演示交互范式。

## ⚠️ 数据说明

**不包含任何真实用户信息**：偏好、历史、日程、预订、评价全部是本地数据或用户自己输入的内容，运行时数据不入库。

**外部数据默认是实时的**：餐厅、活动、路线取高德地图接口，API 不可用时自动降级到本地示例数据集。每次返回都带 `data_source` 字段标明本次来源（`amap` / `mixed` / `mock`），格式化输出里也会直接印出来——mock 时管家必须声明是示例数据，不会把示例店说成真店。

**预订与支付是模拟闭环**，不对接真实商户、不涉及真实交易。

## 📝 技术栈

- **框架**: OpenClaw 2026.5.20（Agent 运行时 + Cron 调度 + IM 路由）
- **技能**: 7 个，遵循 OpenClaw 插件规范（SKILL.md + 实现代码）
- **脚本**: Python 3
- **数据**: 外部 POI/路线取高德实时接口、失败降级本地 JSON 示例集；用户侧数据全部本地存储，不含真实用户信息
- **交互**: IM 对话（微信为主，兼容 Telegram/Discord）

---

> 🔊 全天候私人管家 — 你说，我听，我回应。
