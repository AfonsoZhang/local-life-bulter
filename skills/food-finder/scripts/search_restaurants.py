#!/usr/bin/env python3
"""美食推荐搜索脚本 - 高德地图 API + 模拟数据 fallback

优先使用高德地图 POI 搜索获取真实餐厅数据，
API 不可用时自动降级到本地模拟数据。

改进点：
- 支持排除机制（负面关键词 → 直接剔除）
- 语义关键词映射（"和父母吃" → family_friendly + 安静环境）
- 负面关键词自动检测（"不吃辣" → 排除辣的餐厅）
- 集成记忆模块：记录交互、学习偏好、多轮追问
"""

import json
import os
import argparse
import re
import sys
from typing import List, Dict, Optional, Set

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from memory import (
    record_interaction,
    record_visit,
    get_last_recommendations,
    get_learned_preferences,
    get_top_preferences,
    get_visited_ids,
    get_visited_names,
    infer_context_from_query,
    format_preference_summary,
)
from time_utils import (
    get_current_meal_type,
    get_meal_type_label,
    get_restaurant_meal_score_boost,
    get_time_context_description,
)

# 尝试导入高德 API
try:
    from amap_api import search_poi, geocode, resolve_location, save_user_location
    HAS_AMAP = True
except ImportError:
    HAS_AMAP = False

DATA_FILE = os.path.join(SCRIPT_DIR, "..", "data", "restaurants.json")

# ── 高德 API 配置 ──────────────────────────────────────────────

# 餐饮类 POI 类型编码
AMAP_FOOD_TYPES = "050000"  # 餐饮服务
# 默认城市
DEFAULT_CITY = "济南"
# 默认中心坐标（西湖附近，可改为用户实际位置）
DEFAULT_CENTER = "120.155747,30.275815"
# 搜索半径（米）
DEFAULT_RADIUS = 5000

# 高德菜系关键词映射
CUISINE_KEYWORDS = {
    "四川火锅": "火锅",
    "潮汕火锅": "牛肉火锅",
    "北京小吃": "炸酱面 面馆",
    "湖南菜": "湘菜",
    "烧烤": "烧烤",
    "日料": "日料 拉面",
    "咖啡轻食": "咖啡",
    "综合美食": "美食",
    "四川串串": "串串",
    "杭帮菜": "杭帮菜 浙菜",
    "火锅": "火锅",
    "川菜": "川菜",
    "粤菜": "粤菜",
    "西餐": "西餐",
    "韩餐": "韩餐 烤肉",
}


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点间距离（km）"""
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _amap_to_restaurant(poi: Dict, index: int = 0, center_lng: float = None, center_lat: float = None) -> Dict:
    """将高德 POI 数据转换为内部餐厅格式"""
    # 解析价格范围
    cost = poi.get("cost", "")
    budget_level = "medium"
    price_range = "人均 40-80"
    if cost:
        try:
            # 高德 cost 格式通常是 "60" 或 "60-120"
            if "-" in str(cost):
                parts = str(cost).split("-")
                avg = (int(parts[0]) + int(parts[1])) / 2
            else:
                avg = int(cost)
            if avg <= 30:
                budget_level = "low"
                price_range = f"人均 {cost}"
            elif avg <= 80:
                budget_level = "medium"
                price_range = f"人均 {cost}"
            else:
                budget_level = "high"
                price_range = f"人均 {cost}"
        except (ValueError, IndexError):
            pass

    # 解析评分
    rating = poi.get("rating")
    if rating is None:
        rating = 4.0
    else:
        try:
            rating = float(rating)
        except (ValueError, TypeError):
            rating = 4.0

    # 距离
    distance_m = poi.get("distance_m")
    if distance_m:
        distance_km = round(distance_m / 1000, 1)
    elif poi.get("lng") and poi.get("lat") and center_lng and center_lat:
        distance_km = round(_haversine_km(center_lng, center_lat, poi["lng"], poi["lat"]), 1)
    else:
        distance_km = 0.0

    # 根据类型推断标签
    raw_type = poi.get("raw_type", "")
    tags = []
    features = []
    if "火锅" in raw_type or "火锅" in poi.get("name", ""):
        tags.extend(["火锅", "聚餐"])
    if "烧烤" in raw_type or "烧烤" in poi.get("name", ""):
        tags.extend(["烧烤", "夜宵"])
    if "咖啡" in raw_type or "咖啡" in poi.get("name", ""):
        tags.extend(["咖啡", "安静"])
        features.extend(["安静", "wifi"])
    if "面" in poi.get("name", ""):
        tags.extend(["面食", "快餐"])
    if rating >= 4.5:
        features.append("高评分")
    if distance_km <= 0.5:
        tags.append("近")

    return {
        "id": f"amap_{index:03d}",
        "name": poi.get("name", ""),
        "cuisine": poi.get("type", "").split(";")[-1] if poi.get("type") else "美食",
        "rating": rating,
        "price_range": price_range,
        "budget_level": budget_level,
        "location": poi.get("address", ""),
        "zone": poi.get("district", "").replace("区", ""),
        "zone_label": poi.get("district", ""),
        "distance_km": distance_km,
        "features": features if features else ["真实数据"],
        "environment": "moderate",
        "family_friendly": True,
        "open_hours": poi.get("opening_hours", ""),
        "wait_time_min": 0,
        "description": f"{poi.get('name', '')}，位于{poi.get('address', '')}",
        "tags": tags if tags else ["美食"],
        "good_for": ["聚餐", "朋友"],
        "meal_type": ["lunch", "dinner"],
        "tel": poi.get("tel", ""),
        "source": "amap",
        "amap_location": poi.get("location", ""),
    }


def search_from_amap(
    query: str = "",
    cuisine: str = "",
    city: str = DEFAULT_CITY,
    center: str = DEFAULT_CENTER,
    radius: int = DEFAULT_RADIUS,
    limit: int = 10,
) -> Optional[List[Dict]]:
    """通过高德 API 搜索餐厅"""
    if not HAS_AMAP:
        return None

    # 构建搜索关键词
    keywords = query or cuisine
    if not keywords:
        keywords = "美食"
    # 如果有菜系映射，使用映射的关键词
    for key, mapped in CUISINE_KEYWORDS.items():
        if key in keywords:
            keywords = mapped
            break

    try:
        pois = search_poi(
            keywords=keywords,
            types=AMAP_FOOD_TYPES,
            city=city,
            location=center,
            radius=radius,
            sort_rule="distance",
            page_size=min(limit * 2, 25),  # 多取一些，后面会过滤
        )
        if not pois:
            return None

        # 解析中心坐标
        clng, clat = None, None
        if center:
            parts = center.split(",")
            if len(parts) == 2:
                try:
                    clng, clat = float(parts[0]), float(parts[1])
                except ValueError:
                    pass

        restaurants = []
        for i, poi in enumerate(pois[:limit]):
            restaurants.append(_amap_to_restaurant(poi, i, clng, clat))

        return restaurants if restaurants else None

    except Exception as e:
        print(f"[amap] 搜索失败: {e}")
        return None


# ── 模拟数据 fallback ──────────────────────────────────────────

def load_mock_restaurants() -> List[Dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)["restaurants"]
    # 标记数据来源
    for r in data:
        r["source"] = "mock"
    return data


# ── 语义映射表 ──────────────────────────────────────────────

NEGATIVE_KEYWORD_MAP = {
    "不吃辣": ["辣"],
    "不要辣": ["辣"],
    "忌辣": ["辣"],
    "免辣": ["辣"],
    "不辣": ["辣"],
    "不吃烧烤": ["烧烤"],
    "不要烧烤": ["烧烤"],
    "不吃火锅": ["火锅"],
    "不要火锅": ["火锅"],
    "不喝酒": ["啤酒", "酒"],
    "不喝啤酒": ["啤酒"],
    "不排队": ["排队"],
    "不想排队": ["排队"],
    "不吵": ["热闹", "noisy"],
    "不要吵": ["热闹", "noisy"],
}

SCENARIO_MAP = {
    "和父母": {"family_friendly": True, "prefer_env": "quiet"},
    "带父母": {"family_friendly": True, "prefer_env": "quiet"},
    "和长辈": {"family_friendly": True, "prefer_env": "quiet"},
    "带长辈": {"family_friendly": True, "prefer_env": "quiet"},
    "和家人": {"family_friendly": True, "prefer_env": "quiet"},
    "带家人": {"family_friendly": True, "prefer_env": "quiet"},
    "家庭聚餐": {"family_friendly": True, "prefer_env": "quiet"},
    "一个人": {"prefer_env": "quiet", "prefer_tags": ["一个人"]},
    "独自": {"prefer_env": "quiet", "prefer_tags": ["一个人"]},
    "约会": {"prefer_env": "quiet", "exclude_env": ["noisy"]},
    "请客": {"prefer_env": "quiet", "exclude_env": ["noisy"]},
    "聚餐": {"prefer_tags": ["聚餐"], "prefer_env": "moderate"},
    "朋友聚餐": {"prefer_tags": ["聚餐"], "prefer_env": "moderate"},
    "夜宵": {"prefer_tags": ["夜宵"], "prefer_time": "late_night"},
    "宵夜": {"prefer_tags": ["夜宵"], "prefer_time": "late_night"},
    "快餐": {"prefer_tags": ["快餐", "实惠"]},
    "工作餐": {"prefer_tags": ["快餐", "实惠"]},
    "便宜": {"prefer_budget": "low"},
    "实惠": {"prefer_budget": "low"},
    "省钱": {"prefer_budget": "low"},
}

FOLLOWUP_KEYWORDS = [
    "换一家", "换一批", "其他的", "还有吗", "再看看",
    "上次", "之前", "那个", "第一家", "第二家", "第三家",
    "就这家", "就去这家", "定了", "去这家",
]


def is_followup_query(query: str) -> bool:
    query_lower = query.lower()
    return any(kw in query_lower for kw in FOLLOWUP_KEYWORDS)


def resolve_followup(query: str, last_results: List[Dict]) -> Optional[Dict]:
    query_lower = query.lower()
    choose_keywords = ["就这家", "就去这家", "定了", "去这家", "第一家", "第二家", "第三家"]
    for kw in choose_keywords:
        if kw in query_lower:
            if "第一" in kw and len(last_results) >= 1:
                return last_results[0]
            elif "第二" in kw and len(last_results) >= 2:
                return last_results[1]
            elif "第三" in kw and len(last_results) >= 3:
                return last_results[2]
            elif kw in ["就这家", "就去这家", "定了", "去这家"]:
                return last_results[0] if last_results else None
    for r in last_results:
        if r["name"] in query:
            return r
    return None


def extract_negative_tags(query: str) -> Set[str]:
    negative_tags: Set[str] = set()
    query_lower = query.lower()
    for keyword, tags in NEGATIVE_KEYWORD_MAP.items():
        if keyword in query_lower:
            negative_tags.update(tags)
    for match in re.finditer(r"不[要想吃来]*(\w+)", query_lower):
        word = match.group(1)
        negative_tags.add(word)
    return negative_tags


def extract_scenario_filters(query: str) -> Dict:
    filters: Dict = {}
    query_lower = query.lower()
    for keyword, scenario_filters in SCENARIO_MAP.items():
        if keyword in query_lower:
            for key, value in scenario_filters.items():
                if key == "prefer_tags":
                    filters.setdefault("prefer_tags", []).extend(value)
                elif key not in filters:
                    filters[key] = value
                elif isinstance(value, list) and isinstance(filters[key], list):
                    filters[key].extend(value)
    return filters


def has_negative_match(restaurant: Dict, negative_tags: Set[str]) -> bool:
    if not negative_tags:
        return False
    r_tags = set(t.lower() for t in restaurant.get("tags", []))
    r_features = set(f.lower() for f in restaurant.get("features", []))
    r_all = r_tags | r_features
    for neg_tag in negative_tags:
        if neg_tag.lower() in r_all:
            return True
    return False


def search(
    query: str = "",
    location: str = "",
    budget: str = "",
    cuisine: str = "",
    time_of_day: str = "",
    mood: str = "",
    environment: str = "",
    family_friendly: bool = None,
    limit: int = 3,
    exclude_visited: bool = False,
    use_amap: bool = True,
) -> Dict:
    """搜索并过滤餐厅，返回 {results, excluded, reasons, preference_hint, data_source}"""
    data_source = "mock"

    # 尝试从高德 API 获取数据
    restaurants = None
    if use_amap and HAS_AMAP:
        # 位置解析：查询中的位置 > 配置 > 默认
        user_loc = resolve_location(query)
        center = user_loc["center"]
        if location:
            geo = geocode(location, city=user_loc["city"])
            if geo and geo.get("location"):
                center = geo["location"]

        restaurants = search_from_amap(
            query=query,
            cuisine=cuisine,
            city=user_loc["city"],
            center=center,
            limit=limit * 3,
        )
        if restaurants:
            data_source = "amap"

    # fallback 到模拟数据
    if not restaurants:
        restaurants = load_mock_restaurants()
        data_source = "mock"

    # 提取排除条件和场景条件
    negative_tags = extract_negative_tags(query)
    scenario_filters = extract_scenario_filters(query)

    if family_friendly is None and scenario_filters.get("family_friendly"):
        family_friendly = True

    visited_ids = get_visited_ids("food-finder") if exclude_visited else set()
    visited_names = get_visited_names("food-finder") if exclude_visited else set()

    learned = get_learned_preferences()
    preferred_cuisines = set(get_top_preferences("preferred_cuisines", 3))
    preferred_envs = set(get_top_preferences("preferred_environments", 3))

    results = []
    excluded = []

    for r in restaurants:
        if exclude_visited and (r.get("id") in visited_ids or r.get("name") in visited_names):
            excluded.append({"name": r["name"], "reason": "已去过"})
            continue

        if has_negative_match(r, negative_tags):
            excluded.append({
                "name": r["name"],
                "reason": f"含排除关键词: {negative_tags & (set(t.lower() for t in r.get('tags', [])) | set(f.lower() for f in r.get('features', [])))}"
            })
            continue

        exclude_env = scenario_filters.get("exclude_env", [])
        if r.get("environment") in exclude_env:
            excluded.append({"name": r["name"], "reason": "环境不符合场景要求"})
            continue

        if family_friendly and not r.get("family_friendly", False):
            excluded.append({"name": r["name"], "reason": "不适合家庭/亲子"})
            continue

        score = 0

        if cuisine and cuisine.lower() in r.get("cuisine", "").lower():
            score += 3

        if preferred_cuisines and r.get("cuisine") in preferred_cuisines:
            score += 2

        if budget:
            budget_map = {"低": "low", "中": "medium", "高": "high",
                          "low": "low", "medium": "medium", "high": "high"}
            budget_level = budget_map.get(budget.lower(), budget)
            if budget_level in r.get("price_range", "").lower() or budget_level == r.get("budget_level"):
                score += 3

        target_env = environment or scenario_filters.get("prefer_env")
        if target_env:
            env_map = {"安静": "quiet", "热闹": "noisy", "一般": "moderate",
                       "quiet": "quiet", "noisy": "noisy"}
            if env_map.get(target_env, target_env) == r.get("environment"):
                score += 2
        elif preferred_envs and r.get("environment") in preferred_envs:
            score += 1

        if family_friendly and r.get("family_friendly"):
            score += 2

        prefer_tags = scenario_filters.get("prefer_tags", [])
        for tag in prefer_tags:
            for r_tag in r.get("tags", []):
                if tag.lower() in r_tag.lower():
                    score += 2
            for r_feat in r.get("features", []):
                if tag.lower() in r_feat.lower():
                    score += 1

        if query:
            query_lower = query.lower()
            clean_query = query_lower
            for neg_kw in NEGATIVE_KEYWORD_MAP:
                clean_query = clean_query.replace(neg_kw, "")
            for scenario_kw in SCENARIO_MAP:
                clean_query = clean_query.replace(scenario_kw, "")
            for tag in r.get("tags", []):
                if tag.lower() in clean_query:
                    score += 2
            for feature in r.get("features", []):
                if feature.lower() in clean_query:
                    score += 1
            if clean_query.strip() and clean_query.strip() in r.get("description", "").lower():
                score += 1

        if r.get("distance_km", 99) <= 1:
            score += 2
        elif r.get("distance_km", 99) <= 2:
            score += 1

        meal_type = time_of_day or get_current_meal_type()
        score += get_restaurant_meal_score_boost(r, meal_type)

        score += r.get("rating", 4.0)

        results.append({"restaurant": r, "score": score})

    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = [item["restaurant"] for item in results[:limit]]

    preference_hint = format_preference_summary()

    return {
        "results": top_results,
        "excluded": excluded,
        "negative_tags": list(negative_tags),
        "scenario_filters": {k: v for k, v in scenario_filters.items() if k != "prefer_tags"},
        "preference_hint": preference_hint,
        "time_context": get_time_context_description(),
        "current_meal_type": get_meal_type_label(get_current_meal_type()),
        "data_source": data_source,
    }


def format_output(search_result: Dict) -> str:
    results = search_result["results"]
    excluded = search_result["excluded"]
    negative_tags = search_result["negative_tags"]
    preference_hint = search_result.get("preference_hint", "")
    time_context = search_result.get("time_context", "")
    current_meal_type = search_result.get("current_meal_type", "")
    data_source = search_result.get("data_source", "mock")

    if not results:
        msg = "抱歉，没有找到符合条件的餐厅。换个条件试试？"
        if excluded:
            msg += f"\n\n被排除的餐厅："
            for ex in excluded:
                msg += f"\n  ❌ {ex['name']} — {ex['reason']}"
        return msg

    lines = ["🍽 为你推荐以下餐厅：\n"]

    # 数据来源标识
    if data_source == "amap":
        lines.append("📍 数据来源：高德地图（实时）\n")
    else:
        lines.append("📦 数据来源：本地推荐（模拟数据）\n")

    if time_context:
        lines.append(f"🕐 {time_context}")
        lines.append("")

    if preference_hint:
        lines.append(f"💡 {preference_hint}\n")

    for i, r in enumerate(results, 1):
        meal_type = r.get("meal_type", [])
        meal_tag = ""
        if meal_type:
            meal_labels = {"breakfast": "🌅早餐", "lunch": "🍜午餐", "dinner": "🍽晚餐",
                           "late_night": "🌙夜宵", "afternoon_tea": "☕下午茶"}
            tags = [meal_labels.get(m, m) for m in meal_type]
            meal_tag = " " + " ".join(tags)

        lines.append(f"**{i}. {r['name']}**{meal_tag}")
        lines.append(f"   🍴 {r.get('cuisine', '')}  |  ⭐ {r.get('rating', '')}  |  💰 {r.get('price_range', '')}")
        lines.append(f"   📍 {r.get('location', '')}")

        if r.get("distance_km"):
            lines.append(f"   📏 距离 {r['distance_km']}km")

        if r.get("open_hours"):
            lines.append(f"   🕐 营业时间: {r['open_hours']}")

        if r.get("tel"):
            lines.append(f"   📞 {r['tel']}")

        lines.append(f"   📝 {r.get('description', '')}")

        wait = r.get("wait_time_min", 0)
        if wait > 0:
            lines.append(f"   ⏳ 预计等待 {wait} 分钟")
        else:
            lines.append(f"   ✅ 现在不用排队")
        lines.append("")

    if negative_tags:
        lines.append(f"🚫 已排除含 {', '.join(negative_tags)} 的餐厅")
    if excluded:
        lines.append(f"   排除了 {len(excluded)} 家: {', '.join(ex['name'] for ex in excluded)}")

    lines.append("\n💬 回复「就去这家」选定，或说「换一家」看其他推荐")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="美食推荐搜索")
    parser.add_argument("--query", default="", help="用户查询")
    parser.add_argument("--location", default="", help="位置")
    parser.add_argument("--budget", default="", help="预算")
    parser.add_argument("--cuisine", default="", help="菜系")
    parser.add_argument("--time_of_day", default="", help="用餐时段")
    parser.add_argument("--mood", default="", help="心情/场景")
    parser.add_argument("--environment", default="", help="环境偏好")
    parser.add_argument("--family_friendly", action="store_true", help="亲子友好")
    parser.add_argument("--limit", type=int, default=3, help="返回数量")
    parser.add_argument("--exclude_visited", action="store_true", help="排除已去过的")
    parser.add_argument("--no_amap", action="store_true", help="不使用高德 API，仅用模拟数据")
    parser.add_argument("--set_location", default="", help="设置默认位置（如'武林广场'）")

    # 多轮对话参数
    parser.add_argument("--choice", default="", help="用户选择的餐厅名称（记录选择）")
    parser.add_argument("--visit", default="", help="记录一次实际访问（餐厅名称）")
    parser.add_argument("--visit_rating", type=float, default=0, help="访问评分")
    parser.add_argument("--recall", action="store_true", help="查看上次推荐")
    parser.add_argument("--no_record", action="store_true", help="不记录此次交互")

    args = parser.parse_args()

    # ── 记录访问 ──
    if args.visit:
        record_visit("food-finder", args.visit, rating=args.visit_rating if args.visit_rating else None)
        print(f"✅ 已记录访问: {args.visit}")
        return

    # ── 查看上次推荐 ──
    if args.recall:
        last = get_last_recommendations("food-finder")
        if not last:
            print("没有上次推荐记录")
            return
        print("📋 上次推荐的餐厅：\n")
        for i, r in enumerate(last, 1):
            print(f"  {i}. {r['name']} ({r.get('cuisine', '')})")
        return

    # ── 处理用户选择 ──
    if args.choice:
        last = get_last_recommendations("food-finder")
        chosen = None
        for r in last:
            if r["name"] == args.choice:
                chosen = r
                break
        if chosen:
            record_interaction("food-finder", "", last, user_choice=args.choice)
            print(f"✅ 已记录你的选择: {args.choice}")
            print(f"   下次我会更懂你的口味！")
        else:
            print(f"⚠️ 「{args.choice}」不在上次推荐中")
        return

    # ── 处理多轮追问 ──
    if args.query and is_followup_query(args.query):
        last = get_last_recommendations("food-finder")
        if last:
            chosen = resolve_followup(args.query, last)
            if chosen:
                record_interaction("food-finder", args.query, last, user_choice=chosen["name"])
                print(f"✅ 好的，选择 {chosen['name']}！")
                print(f"   📍 {chosen.get('location', '位置见导航')}")
                return
            query_clean = args.query
            for kw in FOLLOWUP_KEYWORDS:
                query_clean = query_clean.replace(kw, "")
            args.query = query_clean.strip() or args.query

    # ── 设置默认位置 ──
    if args.set_location:
        geo = geocode(args.set_location)
        if geo and geo.get("location"):
            save_user_location(
                city=geo.get("city", ""),
                location_name=args.set_location,
                center=geo["location"],
            )
            print(f"✅ 默认位置已设为: {args.set_location} ({geo.get('city', '')} {geo.get('district', '')})")
        else:
            print(f"⚠️ 无法识别位置: {args.set_location}")
        return

    # ── 正常搜索 ──
    context = infer_context_from_query(args.query) if args.query else {}

    result = search(
        query=args.query,
        location=args.location,
        budget=args.budget,
        cuisine=args.cuisine,
        time_of_day=args.time_of_day,
        mood=args.mood,
        environment=args.environment,
        family_friendly=True if args.family_friendly else None,
        limit=args.limit,
        exclude_visited=args.exclude_visited,
        use_amap=not args.no_amap,
    )

    if not args.no_record:
        record_interaction(
            skill="food-finder",
            query=args.query or "(browse)",
            recommendations=result["results"],
            context=context,
        )

    print(format_output(result))


if __name__ == "__main__":
    main()
