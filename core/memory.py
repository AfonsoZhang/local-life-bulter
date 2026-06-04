#!/usr/bin/env python3
"""共享记忆模块 - 历史记录、偏好学习、多轮上下文

三个技能共用此模块，实现：
1. 交互历史记录（每次推荐 + 用户选择）
2. 偏好推断（从历史中学习）
3. 多轮上下文（记住上次推荐，支持"换一家""上次那家"等追问）
4. 访问记录（用户实际去了哪些地方）
"""

import json
import os
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")
PREFERENCES_FILE = os.path.join(CONFIG_DIR, "preferences.json")
SESSION_FILE = os.path.join(CONFIG_DIR, "session_state.json")


# ── 文件读写 ──────────────────────────────────────────────

def _load_json(path: str) -> Any:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 历史记录 ──────────────────────────────────────────────

def record_interaction(
    skill: str,
    query: str,
    recommendations: List[Dict],
    user_choice: Optional[str] = None,
    context: Optional[Dict] = None,
    companion: str = "",
):
    """记录一次交互

    Args:
        skill: 技能名称 (food-finder / entertainment / travel-planner)
        query: 用户的原始查询
        recommendations: 推荐给用户的结果列表
        user_choice: 用户选择的结果名称（如果已知）
        context: 额外上下文（天气、同行人等）
    """
    history = _load_json(HISTORY_FILE)
    if "interactions" not in history:
        history["interactions"] = []

    entry = {
        "timestamp": datetime.now().isoformat(),
        "skill": skill,
        "query": query,
        "recommendations": [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "type": r.get("cuisine", r.get("type", "")),
                "tags": r.get("tags", []),
                "budget_level": r.get("budget_level", ""),
                "price": r.get("price_yuan", r.get("price_range", "")),
                "environment": r.get("environment", ""),
                "rating": r.get("rating", 0),
            }
            for r in recommendations
        ],
        "user_choice": user_choice,
        "context": context or {},
    }
    history["interactions"].append(entry)

    # 保留最近 200 条记录
    if len(history["interactions"]) > 200:
        history["interactions"] = history["interactions"][-200:]

    _save_json(HISTORY_FILE, history)

    # 同时更新偏好
    if user_choice:
        _companion = companion or (context or {}).get("companion", "")
        _update_preferences_from_choice(skill, recommendations, user_choice, companion=_companion)

    # 更新多轮上下文
    _update_session(skill, query, recommendations)


def record_visit(
    skill: str,
    item_name: str,
    item_id: str = "",
    rating: Optional[float] = None,
    notes: str = "",
):
    """记录一次实际访问（用户真的去了/参加了）

    Args:
        skill: 技能名称
        item_name: 餐厅/活动/路线名称
        item_id: 对应 ID
        rating: 用户给的评分（可选）
        notes: 用户备注
    """
    history = _load_json(HISTORY_FILE)
    if "visits" not in history:
        history["visits"] = []

    visit = {
        "timestamp": datetime.now().isoformat(),
        "skill": skill,
        "item_id": item_id,
        "item_name": item_name,
        "rating": rating,
        "notes": notes,
    }
    history["visits"].append(visit)

    if len(history["visits"]) > 200:
        history["visits"] = history["visits"][-200:]

    _save_json(HISTORY_FILE, history)


def record_rejection(
    skill: str,
    rejected_items: List[Dict],
    rejected_tags: List[str] = "",
    reason: str = "",
    companion: str = "",
):
    """记录用户的负面反馈（不想吃/不想去/不感兴趣）

    Args:
        skill: 技能名称
        rejected_items: 被拒绝的推荐项列表
        rejected_tags: 被拒绝的标签（如"辣"、"火锅"）
        reason: 拒绝原因（如"不想吃"、"太远了"）
        companion: 当前场景的同行人
    """
    prefs = _load_json(PREFERENCES_FILE)
    if "learned" not in prefs:
        prefs["learned"] = {}

    learned = prefs["learned"]
    now = datetime.now().isoformat()

    # 初始化负面反馈存储
    if "negative_feedback" not in learned:
        learned["negative_feedback"] = {}

    neg = learned["negative_feedback"]

    # 从被拒绝的项目中提取属性
    if skill == "food-finder":
        for item in rejected_items:
            # 记录被拒绝的菜系
            cuisine = item.get("cuisine", "")
            if cuisine:
                key = "rejected_cuisines"
                neg.setdefault(key, {})
                neg[key][cuisine] = {
                    "count": neg[key].get(cuisine, {}).get("count", 0) + 1,
                    "last_rejected": now,
                    "reason": reason,
                }

            # 记录被拒绝的标签
            for tag in item.get("tags", []):
                key = "rejected_food_tags"
                neg.setdefault(key, {})
                neg[key][tag] = {
                    "count": neg[key].get(tag, {}).get("count", 0) + 1,
                    "last_rejected": now,
                }

    elif skill == "entertainment":
        for item in rejected_items:
            event_type = item.get("type", "")
            if event_type:
                key = "rejected_event_types"
                neg.setdefault(key, {})
                neg[key][event_type] = {
                    "count": neg[key].get(event_type, {}).get("count", 0) + 1,
                    "last_rejected": now,
                }

    # 记录被拒绝的标签关键词
    if rejected_tags:
        if isinstance(rejected_tags, str):
            rejected_tags = [rejected_tags]
        key = "rejected_keywords"
        neg.setdefault(key, {})
        for tag in rejected_tags:
            neg[key][tag] = {
                "count": neg[key].get(tag, {}).get("count", 0) + 1,
                "last_rejected": now,
            }

    _save_json(PREFERENCES_FILE, prefs)


def get_rejected_preferences(skill: str = "") -> Dict:
    """获取被拒绝的偏好（负面反馈）"""
    prefs = _load_json(PREFERENCES_FILE)
    neg = prefs.get("learned", {}).get("negative_feedback", {})

    if skill == "food-finder":
        return {
            "cuisines": neg.get("rejected_cuisines", {}),
            "tags": neg.get("rejected_food_tags", {}),
            "keywords": neg.get("rejected_keywords", {}),
        }
    elif skill == "entertainment":
        return {
            "types": neg.get("rejected_event_types", {}),
            "keywords": neg.get("rejected_keywords", {}),
        }
    return neg


# ── 偏好学习 ──────────────────────────────────────────────

def _update_preferences_from_choice(
    skill: str, recommendations: List[Dict], user_choice: str,
    companion: str = "",
):
    """根据用户选择更新偏好（支持时间戳记录 + 场景化）"""
    prefs = _load_json(PREFERENCES_FILE)
    if "learned" not in prefs:
        prefs["learned"] = {}

    chosen = None
    for r in recommendations:
        if r.get("name") == user_choice or r.get("id") == user_choice:
            chosen = r
            break

    if not chosen:
        return

    learned = prefs["learned"]
    now = datetime.now().isoformat()

    def _increment_with_ts(counter_dict: dict, key: str):
        """递增计数器并记录最后选择时间"""
        if key not in counter_dict:
            counter_dict[key] = {"count": 0, "last_chosen": ""}
        counter_dict[key]["count"] = counter_dict[key].get("count", 0) + 1
        counter_dict[key]["last_chosen"] = now

    def _increment_scene(scene_dict: dict, key: str, companion: str):
        """递增场景化偏好计数器"""
        if not companion:
            return
        if key not in scene_dict:
            scene_dict[key] = {}
        scene_dict[key][companion] = scene_dict[key].get(companion, 0) + 1

    if skill == "food-finder":
        # 学习菜系偏好
        cuisine = chosen.get("cuisine", "")
        if cuisine:
            cuisines = learned.setdefault("preferred_cuisines", {})
            _increment_with_ts(cuisines, cuisine)
            # 场景化
            if companion:
                scene = learned.setdefault("scene_cuisines", {})
                _increment_scene(scene, cuisine, companion)

        # 学习环境偏好
        env = chosen.get("environment", "")
        if env:
            envs = learned.setdefault("preferred_environments", {})
            _increment_with_ts(envs, env)
            if companion:
                scene = learned.setdefault("scene_environments", {})
                _increment_scene(scene, env, companion)

        # 学习预算偏好
        budget = chosen.get("budget_level", "")
        if budget:
            budgets = learned.setdefault("preferred_budgets", {})
            _increment_with_ts(budgets, budget)

        # 学习标签偏好
        for tag in chosen.get("tags", []):
            tags = learned.setdefault("preferred_food_tags", {})
            _increment_with_ts(tags, tag)

    elif skill == "entertainment":
        event_type = chosen.get("type", "")
        if event_type:
            types = learned.setdefault("preferred_event_types", {})
            _increment_with_ts(types, event_type)
            if companion:
                scene = learned.setdefault("scene_event_types", {})
                _increment_scene(scene, event_type, companion)

        for tag in chosen.get("tags", []):
            tags = learned.setdefault("preferred_event_tags", {})
            _increment_with_ts(tags, tag)

    _save_json(PREFERENCES_FILE, prefs)


def get_preferences() -> Dict:
    """获取完整偏好（静态 + 学习到的）"""
    prefs = _load_json(PREFERENCES_FILE)
    return prefs


def get_learned_preferences(decay: bool = True) -> Dict:
    """获取从历史中学习到的偏好

    Args:
        decay: 是否应用时间衰减（默认 True）
               半衰期 30 天：30天前的偏好权重降为 0.5，90天前降为 0.125

    Returns:
        偏好字典，如果 decay=True 则返回衰减后的权重
    """
    prefs = _load_json(PREFERENCES_FILE)
    learned = prefs.get("learned", {})

    if not decay or not learned:
        return learned

    now = datetime.now()
    half_life_days = 30  # 半衰期 30 天

    def _decay_counter(counter_dict: dict) -> dict:
        """对带时间戳的计数器应用时间衰减"""
        result = {}
        for key, val in counter_dict.items():
            if isinstance(val, dict) and "count" in val:
                # 新格式：{count, last_chosen, ...}
                count = val["count"]
                last_chosen = val.get("last_chosen", "")
                if last_chosen:
                    try:
                        last_dt = datetime.fromisoformat(last_chosen)
                        days_ago = (now - last_dt).total_seconds() / 86400
                        decay_factor = 0.5 ** (days_ago / half_life_days)
                        result[key] = round(count * decay_factor, 2)
                    except (ValueError, TypeError):
                        result[key] = count
                else:
                    result[key] = count
            elif isinstance(val, (int, float)):
                # 旧格式：直接是数字（没有时间戳，不衰减）
                result[key] = val
        return result

    # 对每个偏好类别应用衰减
    decayed = {}
    for category, values in learned.items():
        if category in ("preferred_cuisines", "preferred_environments",
                        "preferred_budgets", "preferred_food_tags",
                        "preferred_event_types", "preferred_event_tags"):
            if isinstance(values, dict):
                decayed[category] = _decay_counter(values)
            else:
                decayed[category] = values
        elif category.startswith("scene_"):
            # 场景化偏好不衰减，直接返回
            decayed[category] = values
        elif category == "negative_feedback":
            # 负面反馈不衰减
            decayed[category] = values
        else:
            decayed[category] = values

    return decayed


def get_top_preferences(category: str, limit: int = 3, companion: str = "") -> List[str]:
    """获取某类偏好的 Top N（支持场景化 + 时间衰减）

    Args:
        category: 偏好类别，如 "preferred_cuisines", "preferred_environments"
        limit: 返回数量
        companion: 场景（solo/couple/family/friends），如果提供则优先返回该场景的偏好

    Returns:
        按权重排序的偏好值列表
    """
    learned = get_learned_preferences(decay=True)

    # 优先使用场景化偏好
    if companion:
        scene_key = f"scene_{category.replace('preferred_', '')}"
        scene_data = learned.get(scene_key, {})
        if scene_data:
            # scene_data 格式: {key: {companion: count}}
            scene_scores = {}
            for key, companions in scene_data.items():
                if isinstance(companions, dict):
                    scene_scores[key] = companions.get(companion, 0)
            if scene_scores:
                sorted_items = sorted(scene_scores.items(), key=lambda x: x[1], reverse=True)
                return [item[0] for item in sorted_items[:limit]]

    # fallback 到全局偏好
    counter = learned.get(category, {})
    if not counter:
        return []
    sorted_items = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_items[:limit]]


# ── 多轮上下文 ──────────────────────────────────────────────

def _update_session(skill: str, query: str, recommendations: List[Dict]):
    """更新当前会话状态"""
    session = _load_json(SESSION_FILE)
    session["last_skill"] = skill
    session["last_query"] = query
    session["last_recommendations"] = [
        {
            "id": r.get("id", ""),
            "name": r.get("name", ""),
            "cuisine": r.get("cuisine", r.get("type", "")),
            "tags": r.get("tags", []),
            "budget_level": r.get("budget_level", ""),
            "environment": r.get("environment", ""),
            "price_range": r.get("price_range", r.get("price_yuan", "")),
            "rating": r.get("rating", 0),
            "distance_km": r.get("distance_km", 0),
        }
        for r in recommendations
    ]
    session["last_timestamp"] = datetime.now().isoformat()
    session["turn_count"] = session.get("turn_count", 0) + 1
    _save_json(SESSION_FILE, session)


def get_last_recommendations(skill: Optional[str] = None) -> List[Dict]:
    """获取上次推荐结果（用于多轮追问）

    Args:
        skill: 如果指定，只返回该技能的上次推荐

    Returns:
        上次推荐的项目列表
    """
    session = _load_json(SESSION_FILE)
    if not session:
        return []

    if skill and session.get("last_skill") != skill:
        return []

    return session.get("last_recommendations", [])


def get_last_query() -> str:
    """获取上次查询"""
    session = _load_json(SESSION_FILE)
    return session.get("last_query", "")


def get_session_context() -> Dict:
    """获取当前会话上下文"""
    return _load_json(SESSION_FILE)


def clear_session():
    """清除会话上下文"""
    _save_json(SESSION_FILE, {})


# ── Multi-turn 对话历史 ────────────────────────────────────

SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 分钟无操作视为新会话


def get_session_messages(max_age_seconds: int = SESSION_TIMEOUT_SECONDS) -> List[Dict]:
    """读取本会话的 Anthropic messages 历史。

    超时（默认 30 分钟无新查询）则返回空列表，等价于新开会话。
    持久化的是清洁版本：仅 {role:user|assistant, content:str}，不含 tool_use/tool_result。
    """
    session = _load_json(SESSION_FILE) or {}
    msgs_ts = session.get("messages_timestamp")
    if not msgs_ts:
        return []
    try:
        last_dt = datetime.fromisoformat(msgs_ts)
    except (ValueError, TypeError):
        return []
    if (datetime.now() - last_dt).total_seconds() > max_age_seconds:
        return []
    return session.get("messages", []) or []


def save_session_messages(messages: List[Dict]):
    """保存 messages 到 session_state.json（不覆盖其他字段）"""
    session = _load_json(SESSION_FILE) or {}
    session["messages"] = messages
    session["messages_timestamp"] = datetime.now().isoformat()
    _save_json(SESSION_FILE, session)


# ── 历史查询 ──────────────────────────────────────────────

def get_recent_history(skill: Optional[str] = None, limit: int = 10) -> List[Dict]:
    """获取最近的交互历史

    Args:
        skill: 过滤特定技能
        limit: 返回数量

    Returns:
        最近的交互记录
    """
    history = _load_json(HISTORY_FILE)
    interactions = history.get("interactions", [])

    if skill:
        interactions = [i for i in interactions if i.get("skill") == skill]

    return interactions[-limit:]


def get_visit_history(skill: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """获取访问历史"""
    history = _load_json(HISTORY_FILE)
    visits = history.get("visits", [])

    if skill:
        visits = [v for v in visits if v.get("skill") == skill]

    return visits[-limit:]


def get_visited_ids(skill: str) -> set:
    """获取已访问过的项目 ID（用于去重/避免重复推荐）"""
    visits = get_visit_history(skill=skill)
    return {v.get("item_id") for v in visits if v.get("item_id")}


def get_visited_names(skill: str) -> set:
    """获取已访问过的项目名称（用于去重）"""
    visits = get_visit_history(skill=skill)
    return {v.get("item_name") for v in visits if v.get("item_name")}


# ── 偏好推断 ──────────────────────────────────────────────

def infer_context_from_query(query: str) -> Dict:
    """从查询中推断上下文信息

    返回推断出的上下文，如同伴类型、场景等
    """
    context = {}
    query_lower = query.lower()

    # 同行人推断
    companion_map = {
        "一个人": "solo", "独自": "solo", "自己": "solo",
        "和女朋友": "couple", "和男朋友": "couple", "约会": "couple",
        "和老婆": "couple", "和老公": "couple",
        "和父母": "family", "带父母": "family", "和家人": "family",
        "带孩子": "family", "带小孩": "family", "亲子": "family",
        "和朋友": "friends", "朋友聚餐": "friends", "团建": "friends",
    }
    for keyword, companion in companion_map.items():
        if keyword in query_lower:
            context["companion"] = companion
            break

    # 场景推断
    scenario_map = {
        "约会": "date",
        "请客": "treat",
        "工作": "work",
        "庆祝": "celebration",
        "生日": "birthday",
        "周末": "weekend",
        "夜宵": "late_night",
    }
    for keyword, scenario in scenario_map.items():
        if keyword in query_lower:
            context["scenario"] = scenario
            break

    return context


def format_preference_summary(companion: str = "") -> str:
    """生成偏好摘要（支持场景化 + 负面反馈展示）

    Args:
        companion: 当前场景（solo/couple/family/friends）
    """
    prefs = get_learned_preferences(decay=True)
    if not prefs:
        return ""

    lines = []

    cuisines = prefs.get("preferred_cuisines", {})
    if cuisines:
        top = sorted(cuisines.items(), key=lambda x: x[1], reverse=True)[:3]
        names = [t[0] for t in top if t[1] > 0]
        if names:
            lines.append(f"你比较喜欢{'、'.join(names)}")

    envs = prefs.get("preferred_environments", {})
    if envs:
        top = sorted(envs.items(), key=lambda x: x[1], reverse=True)[:1]
        if top and top[0][1] > 0:
            env_name = {"quiet": "安静的", "noisy": "热闹的", "moderate": "氛围适中的"}.get(
                top[0][0], top[0][0]
            )
            lines.append(f"偏好{env_name}环境")

    budgets = prefs.get("preferred_budgets", {})
    if budgets:
        top = sorted(budgets.items(), key=lambda x: x[1], reverse=True)[:1]
        if top and top[0][1] > 0:
            budget_name = {"low": "经济实惠", "medium": "中等消费", "high": "高端消费"}.get(
                top[0][0], top[0][0]
            )
            lines.append(f"通常选{budget_name}")

    # 负面反馈
    neg = prefs.get("negative_feedback", {})
    rejected_cuisines = neg.get("rejected_cuisines", {})
    if rejected_cuisines:
        rejected_names = [k for k, v in rejected_cuisines.items() if isinstance(v, dict) and v.get("count", 0) >= 2]
        if rejected_names:
            lines.append(f"不太喜欢{'、'.join(rejected_names)}")

    # 场景化偏好
    if companion:
        scene_cuisines = prefs.get("scene_cuisines", {})
        if scene_cuisines:
            scene_top = []
            for cuisine, companions in scene_cuisines.items():
                if isinstance(companions, dict) and companions.get(companion, 0) > 0:
                    scene_top.append((cuisine, companions[companion]))
            scene_top.sort(key=lambda x: x[1], reverse=True)
            if scene_top:
                scene_names = [t[0] for t in scene_top[:2]]
                companion_label = {"solo": "一个人", "couple": "约会", "family": "带家人", "friends": "和朋友"}.get(companion, companion)
                lines.append(f"{companion_label}时倾向吃{'、'.join(scene_names)}")

    if lines:
        return "根据你的历史偏好，" + "，".join(lines) + "。"
    return ""


# ── CLI 测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python memory.py history [skill]  - 查看历史")
        print("  python memory.py visits [skill]   - 查看访问记录")
        print("  python memory.py prefs            - 查看偏好")
        print("  python memory.py session           - 查看会话状态")
        print("  python memory.py summary           - 偏好摘要")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "history":
        skill = sys.argv[2] if len(sys.argv) > 2 else None
        history = get_recent_history(skill=skill)
        for h in history[-10:]:
            ts = h["timestamp"][:16]
            choice = f" → 选择了 {h['user_choice']}" if h.get("user_choice") else ""
            print(f"[{ts}] {h['skill']}: {h['query']}{choice}")

    elif cmd == "visits":
        skill = sys.argv[2] if len(sys.argv) > 2 else None
        visits = get_visit_history(skill=skill)
        for v in visits[-10:]:
            ts = v["timestamp"][:16]
            rating = f" ⭐{v['rating']}" if v.get("rating") else ""
            print(f"[{ts}] {v['item_name']}{rating}")

    elif cmd == "prefs":
        print(json.dumps(get_learned_preferences(), ensure_ascii=False, indent=2))

    elif cmd == "session":
        print(json.dumps(get_session_context(), ensure_ascii=False, indent=2))

    elif cmd == "summary":
        print(format_preference_summary())

    else:
        print(f"未知命令: {cmd}")
