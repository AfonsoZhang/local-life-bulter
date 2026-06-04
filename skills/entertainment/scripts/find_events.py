#!/usr/bin/env python3
"""休闲娱乐推荐脚本 - 高德地图 API + 模拟数据 fallback

优先使用高德地图 POI 搜索获取真实场所数据（电影院、景点、运动场馆等），
对于高德无法覆盖的活动（演唱会、展览、脱口秀）保留模拟数据。

API 不可用时自动降级到全部使用本地模拟数据。
"""

import json
import os
import argparse
import sys
from typing import List, Dict, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from memory import (
    record_interaction,
    record_visit,
    get_last_recommendations,
    get_learned_preferences,
    get_top_preferences,
    infer_context_from_query,
    format_preference_summary,
)
from weather import get_weather, get_weather_score_boost, format_weather_for_recommendation
from time_utils import (
    filter_valid_events,
    get_event_time_score_boost,
    get_current_meal_type,
    get_meal_type_label,
    is_weekend,
    get_time_context_description,
)

# 尝试导入高德 API
try:
    from amap_api import search_poi, geocode, resolve_location, save_user_location
    HAS_AMAP = True
except ImportError:
    HAS_AMAP = False

DATA_FILE = os.path.join(SCRIPT_DIR, "..", "data", "events.json")
DEFAULT_CITY = "济南"
DEFAULT_CENTER = "120.155747,30.275815"
DEFAULT_RADIUS = 10000  # 娱乐场所搜索范围更大

# 高德 POI 类型映射
AMAP_TYPE_MAP = {
    "movie": {"types": "080101", "keywords": "电影院 电影"},       # 电影院
    "cinema": {"types": "080101", "keywords": "电影院"},
    "exhibition": {"types": "140000", "keywords": "展览 美术馆 博物馆"},  # 展览
    "museum": {"types": "140000", "keywords": "博物馆"},
    "concert": {"types": "080300", "keywords": "音乐 演出"},       # 娱乐场所
    "sports": {"types": "080000", "keywords": "运动 健身"},        # 体育休闲
    "outdoor": {"types": "110000", "keywords": "公园 景点"},       # 风景名胜
    "park": {"types": "110101", "keywords": "公园"},
    "scenic": {"types": "110000", "keywords": "景区 景点"},
    "shopping": {"types": "060000", "keywords": "商场 购物"},      # 购物
    "ktv": {"types": "080302", "keywords": "KTV"},
    "bar": {"types": "080301", "keywords": "酒吧"},
    "cafe": {"types": "050301", "keywords": "咖啡"},
    "activity": {"types": "080000", "keywords": "娱乐 休闲"},
    "indoor_play": {"types": "080000", "keywords": "儿童乐园 游乐场"},
    "gym": {"types": "080200", "keywords": "健身房"},
    "swimming": {"types": "080200", "keywords": "游泳馆"},
}

# 兴趣关键词映射
INTEREST_KEYWORD_MAP = {
    "movie": "movie", "电影": "movie",
    "cinema": "cinema", "影院": "cinema",
    "exhibition": "exhibition", "展览": "exhibition", "看展": "exhibition",
    "museum": "museum", "博物馆": "museum",
    "concert": "concert", "音乐": "concert", "演唱会": "concert", "演出": "concert",
    "sports": "sports", "运动": "sports", "健身": "sports",
    "outdoor": "outdoor", "户外": "outdoor", "公园": "park",
    "scenic": "scenic", "景点": "scenic", "景区": "scenic", "旅游": "scenic",
    "shopping": "shopping", "购物": "shopping", "逛街": "shopping",
    "ktv": "ktv", "唱歌": "ktv",
    "bar": "bar", "酒吧": "bar", "喝酒": "bar",
    "cafe": "cafe", "咖啡": "cafe", "下午茶": "cafe",
    "activity": "activity", "活动": "activity", "密室": "activity", "剧本杀": "activity",
    "indoor": "indoor_play", "室内": "indoor_play", "亲子": "indoor_play",
    "gym": "gym", "健身": "gym",
    "swimming": "swimming", "游泳": "swimming",
}


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点间距离（km）"""
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _amap_to_event(poi: Dict, event_type: str, index: int = 0, center_lng: float = None, center_lat: float = None) -> Dict:
    """将高德 POI 数据转换为内部活动格式"""
    rating = poi.get("rating")
    if rating is None:
        rating = 4.0
    else:
        try:
            rating = float(rating)
        except (ValueError, TypeError):
            rating = 4.0

    distance_m = poi.get("distance_m")
    if distance_m:
        distance_km = round(distance_m / 1000, 1)
    elif poi.get("lng") and poi.get("lat") and center_lng and center_lat:
        distance_km = round(_haversine_km(center_lng, center_lat, poi["lng"], poi["lat"]), 1)
    else:
        distance_km = 0.0

    # 价格
    cost = poi.get("cost", "")
    price_yuan = 0
    if cost:
        try:
            price_yuan = int("".join(filter(str.isdigit, str(cost).split("-")[0])))
        except (ValueError, IndexError):
            price_yuan = 0

    # 根据类型设置标签
    type_config = {
        "movie": {"emoji": "🎬", "tags": ["电影", "室内"], "weather_independent": True, "duration": 120},
        "cinema": {"emoji": "🎬", "tags": ["电影", "室内"], "weather_independent": True, "duration": 120},
        "exhibition": {"emoji": "🖼", "tags": ["展览", "艺术", "拍照"], "weather_independent": True, "duration": 90},
        "museum": {"emoji": "🏛", "tags": ["博物馆", "文化"], "weather_independent": True, "duration": 120},
        "concert": {"emoji": "🎵", "tags": ["音乐", "演出"], "weather_independent": True, "duration": 180},
        "sports": {"emoji": "🏃", "tags": ["运动", "健身"], "weather_independent": True, "duration": 90},
        "outdoor": {"emoji": "🌳", "tags": ["户外", "风景"], "weather_independent": False, "duration": 120},
        "park": {"emoji": "🌳", "tags": ["公园", "散步"], "weather_independent": False, "duration": 90},
        "scenic": {"emoji": "🏞", "tags": ["景区", "观光"], "weather_independent": False, "duration": 180},
        "shopping": {"emoji": "🛍", "tags": ["购物", "逛街"], "weather_independent": True, "duration": 120},
        "ktv": {"emoji": "🎤", "tags": ["唱歌", "KTV"], "weather_independent": True, "duration": 180},
        "bar": {"emoji": "🍺", "tags": ["酒吧", "夜生活"], "weather_independent": True, "duration": 120},
        "cafe": {"emoji": "☕", "tags": ["咖啡", "下午茶"], "weather_independent": True, "duration": 60},
        "activity": {"emoji": "🎭", "tags": ["活动", "娱乐"], "weather_independent": True, "duration": 90},
        "indoor_play": {"emoji": "🎪", "tags": ["亲子", "室内"], "weather_independent": True, "duration": 180},
        "gym": {"emoji": "💪", "tags": ["健身", "运动"], "weather_independent": True, "duration": 60},
        "swimming": {"emoji": "🏊", "tags": ["游泳", "运动"], "weather_independent": True, "duration": 60},
    }

    config = type_config.get(event_type, type_config["activity"])

    # 营业时间
    hours = poi.get("opening_hours", "")
    time_str = hours if hours else "全天"

    return {
        "id": f"amap_e_{index:03d}",
        "name": poi.get("name", ""),
        "type": event_type,
        "venue": poi.get("name", ""),
        "zone": poi.get("district", "").replace("区", ""),
        "zone_label": poi.get("district", ""),
        "date": "每天",
        "time": time_str,
        "duration_min": config["duration"],
        "price_yuan": price_yuan,
        "rating": rating,
        "description": f"{poi.get('name', '')}，位于{poi.get('address', '')}",
        "tags": config["tags"],
        "companion": ["couple", "friends", "family"],
        "weather_independent": config["weather_independent"],
        "after_activity": ["dinner", "coffee"],
        "nearby_zones": [poi.get("district", "").replace("区", "")],
        "source": "amap",
        "address": poi.get("address", ""),
        "tel": poi.get("tel", ""),
        "distance_km": distance_km,
    }


def search_from_amap(
    interest: str = "",
    city: str = DEFAULT_CITY,
    center: str = DEFAULT_CENTER,
    radius: int = DEFAULT_RADIUS,
    limit: int = 10,
) -> Optional[List[Dict]]:
    """通过高德 API 搜索娱乐场所"""
    if not HAS_AMAP:
        return None

    # 确定搜索类型和关键词
    interest_key = INTEREST_KEYWORD_MAP.get(interest.lower(), interest.lower())
    type_config = AMAP_TYPE_MAP.get(interest_key)

    if type_config:
        poi_types = ""  # 不使用 types 过滤，高德的 types+location 组合容易返回空
        keywords = type_config["keywords"]
    else:
        poi_types = ""
        keywords = interest or "娱乐 休闲"

    try:
        pois = search_poi(
            keywords=keywords,
            types=poi_types,
            city=city,
            location=center,
            radius=radius,
            sort_rule="distance",
            page_size=min(limit * 2, 25),
        )
        if not pois:
            return None

        events = []
        clng, clat = None, None
        if center:
            parts = center.split(",")
            if len(parts) == 2:
                try:
                    clng, clat = float(parts[0]), float(parts[1])
                except ValueError:
                    pass
        for i, poi in enumerate(pois[:limit]):
            events.append(_amap_to_event(poi, interest_key, i, clng, clat))

        return events if events else None

    except Exception as e:
        print(f"[amap] 搜索失败: {e}")
        return None


def load_mock_events() -> List[Dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)["events"]
    for e in data:
        e["source"] = "mock"
    return data


# 多轮追问关键词
FOLLOWUP_KEYWORDS = [
    "换一个", "换一批", "其他的", "还有吗", "再看看",
    "不想看了", "不想去", "不感兴趣",
    "就这个", "就去这个", "定了", "去这个",
    "第一个", "第二个", "第三个",
]


def is_followup_query(query: str) -> bool:
    query_lower = query.lower()
    return any(kw in query_lower for kw in FOLLOWUP_KEYWORDS)


def resolve_followup(query: str, last_results: List[Dict]) -> Optional[Dict]:
    query_lower = query.lower()
    choose_keywords = ["就这个", "就去这个", "定了", "去这个", "第一个", "第二个", "第三个"]
    for kw in choose_keywords:
        if kw in query_lower:
            if "第一" in kw and len(last_results) >= 1:
                return last_results[0]
            elif "第二" in kw and len(last_results) >= 2:
                return last_results[1]
            elif "第三" in kw and len(last_results) >= 3:
                return last_results[2]
            elif kw in ["就这个", "就去这个", "定了", "去这个"]:
                return last_results[0] if last_results else None
    for r in last_results:
        if r.get("name", "") in query:
            return r
    return None


def search(
    interest: str = "",
    time_range: str = "",
    budget: str = "",
    companion: str = "",
    weather: str = "",
    weather_info=None,
    limit: int = 3,
    location: str = "",
    use_amap: bool = True,
) -> Dict:
    """搜索活动，返回 {results, preference_hint, weather_info, time_context, data_source}"""
    data_source = "mock"
    all_events = []

    # 尝试从高德 API 获取数据
    if use_amap and HAS_AMAP:
        # 位置解析：location 参数 > 配置默认位置
        location_query = location or f"{interest} {companion}".strip()
        user_loc = resolve_location(location_query)
        center = user_loc["center"]
        if location:
            geo = geocode(location, city=user_loc["city"])
            if geo and geo.get("location"):
                center = geo["location"]

        amap_events = search_from_amap(
            interest=interest,
            city=user_loc["city"],
            center=center,
            limit=limit * 2,
        )
        if amap_events:
            all_events.extend(amap_events)
            data_source = "amap"

    # 补充模拟数据（高德无法覆盖的活动类型：演唱会、展览、脱口秀等）
    mock_events = load_mock_events()
    if interest:
        # 只补充高德搜不到的类型
        amap_types = set(e.get("type") for e in all_events)
        for me in mock_events:
            if me.get("type") not in amap_types:
                # 检查兴趣匹配
                interest_lower = interest.lower()
                if (interest_lower in me.get("type", "").lower() or
                    any(interest_lower in t for t in me.get("tags", [])) or
                    any(INTEREST_KEYWORD_MAP.get(interest_lower, interest_lower) == me.get("type", "") for _ in [1])):
                    all_events.append(me)
                    if data_source == "amap":
                        data_source = "mixed"
                    else:
                        data_source = "mock"
    else:
        # 没有指定兴趣时，混合模拟数据
        all_events.extend(mock_events[:limit])
        if all_events and data_source == "amap":
            data_source = "mixed"

    # 如果既没有 API 数据也没有模拟数据
    if not all_events:
        all_events = load_mock_events()
        data_source = "mock"

    # 时间过滤：排除已过期的活动
    valid_events = filter_valid_events(all_events)

    # 获取学习到的偏好
    preferred_types = set(get_top_preferences("preferred_event_types", 3))
    preferred_tags = set(get_top_preferences("preferred_event_tags", 3))

    results = []

    for e in valid_events:
        score = 0

        # 类型匹配
        if interest:
            interest_key = INTEREST_KEYWORD_MAP.get(interest.lower(), interest.lower())
            if interest_key == e.get("type") or interest.lower() in e.get("type", ""):
                score += 3
            for tag in e.get("tags", []):
                if interest.lower() in tag.lower():
                    score += 2
                    break

        # 偏好加权
        if preferred_types and e.get("type") in preferred_types:
            score += 2
        for tag in e.get("tags", []):
            if tag in preferred_tags:
                score += 1

        # 同行人匹配
        if companion:
            comp_map = {
                "solo": "solo", "一个人": "solo", "独处": "solo",
                "couple": "couple", "情侣": "couple", "约会": "couple",
                "family": "family", "家人": "family", "亲子": "family",
                "friends": "friends", "朋友": "friends", "团建": "friends",
            }
            comp_key = comp_map.get(companion.lower(), companion)
            if comp_key in e.get("companion", []):
                score += 3

        # 天气匹配
        if weather_info:
            score += get_weather_score_boost(weather_info, e)
        elif weather:
            weather_lower = weather.lower()
            if any(w in weather_lower for w in ["雨", "下雨", "rain"]):
                if e.get("weather_independent", False):
                    score += 2
            elif any(w in weather_lower for w in ["晴", "好", "sunny"]):
                if not e.get("weather_independent", True):
                    score += 2

        # 时间有效期加权
        score += get_event_time_score_boost(e)

        # 预算匹配
        if budget:
            try:
                budget_num = int("".join(filter(str.isdigit, budget)))
                price = e.get("price_yuan", 0) or 0
                if price <= budget_num:
                    score += 2
                elif price <= budget_num * 1.2:
                    score += 1
            except ValueError:
                pass

        # 免费活动加分
        if e.get("price_yuan", 0) == 0:
            score += 1

        # 距离加分（高德数据有距离信息）
        dist = e.get("distance_km", 99)
        if dist <= 2:
            score += 2
        elif dist <= 5:
            score += 1

        # 评分加权
        score += e.get("rating", 4.0)

        results.append({"event": e, "score": score})

    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = [item["event"] for item in results[:limit]]

    return {
        "results": top_results,
        "preference_hint": format_preference_summary(),
        "weather_info": weather_info,
        "time_context": get_time_context_description(),
        "data_source": data_source,
    }


def format_output(search_result: Dict) -> str:
    events = search_result["results"]
    preference_hint = search_result.get("preference_hint", "")
    weather_info = search_result.get("weather_info")
    time_context = search_result.get("time_context", "")
    data_source = search_result.get("data_source", "mock")

    if not events:
        return "抱歉，没有找到合适的活动。换个条件试试？"

    type_emoji = {"movie": "🎬", "exhibition": "🖼", "concert": "🎵",
                  "indoor_play": "🎪", "activity": "🎭", "outdoor": "🏃",
                  "scenic": "🏞", "park": "🌳", "shopping": "🛍",
                  "ktv": "🎤", "bar": "🍺", "cafe": "☕", "museum": "🏛",
                  "sports": "💪", "gym": "💪", "swimming": "🏊"}

    lines = ["🎭 为你推荐：\n"]

    # 数据来源标识
    if data_source == "amap":
        lines.append("📍 数据来源：高德地图（实时）\n")
    elif data_source == "mixed":
        lines.append("📍📦 数据来源：高德地图 + 本地推荐（混合）\n")
    else:
        lines.append("📦 数据来源：本地推荐（模拟数据）\n")

    # 天气信息
    if weather_info:
        weather_line = format_weather_for_recommendation(weather_info)
        if weather_line:
            lines.append(weather_line)
            lines.append("")

    # 时间上下文
    if time_context:
        lines.append(f"🕐 {time_context}")
        lines.append("")

    if preference_hint:
        lines.append(f"💡 {preference_hint}\n")

    for i, e in enumerate(events, 1):
        emoji = type_emoji.get(e.get("type", ""), "📌")
        price = "免费" if (e.get("price_yuan", 0) or 0) == 0 else f"¥{e.get('price_yuan', 0)}"
        outdoor_tag = " 🌳户外" if not e.get("weather_independent", True) else ""

        lines.append(f"**{i}. {emoji} {e['name']}**{outdoor_tag}")
        lines.append(f"   📍 {e.get('venue', e.get('address', ''))}  |  💰 {price}  |  ⭐ {e.get('rating', '')}")
        lines.append(f"   🕐 {e.get('time', '')}  |  📅 {e.get('date', '')}")

        if e.get("distance_km"):
            lines.append(f"   📏 距离 {e['distance_km']}km")

        if e.get("tel"):
            lines.append(f"   📞 {e['tel']}")

        lines.append(f"   📝 {e.get('description', '')}")
        lines.append("")

    lines.append("💬 回复「就去这个」选定，或说「换一个」看其他推荐")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="休闲娱乐推荐")
    parser.add_argument("--interest", default="", help="兴趣类型")
    parser.add_argument("--time_range", default="", help="时间范围")
    parser.add_argument("--budget", default="", help="预算")
    parser.add_argument("--companion", default="", help="同行人")
    parser.add_argument("--weather", default="", help="天气")
    parser.add_argument("--location", default="", help="位置/区域")
    parser.add_argument("--limit", type=int, default=3, help="返回数量")
    parser.add_argument("--query", default="", help="自然语言查询（多轮对话用）")
    parser.add_argument("--no_amap", action="store_true", help="不使用高德 API")
    parser.add_argument("--set_location", default="", help="设置默认位置（如'武林广场'）")

    # 多轮对话参数
    parser.add_argument("--choice", default="", help="用户选择的活动名称（记录选择）")
    parser.add_argument("--visit", default="", help="记录一次实际访问（活动名称）")
    parser.add_argument("--visit_rating", type=float, default=0, help="访问评分")
    parser.add_argument("--recall", action="store_true", help="查看上次推荐")
    parser.add_argument("--no_record", action="store_true", help="不记录此次交互")

    args = parser.parse_args()

    # ── 记录访问 ──
    if args.visit:
        record_visit("entertainment", args.visit, rating=args.visit_rating if args.visit_rating else None)
        print(f"✅ 已记录访问: {args.visit}")
        return

    # ── 查看上次推荐 ──
    if args.recall:
        last = get_last_recommendations("entertainment")
        if not last:
            print("没有上次推荐记录")
            return
        print("📋 上次推荐的活动：\n")
        for i, r in enumerate(last, 1):
            print(f"  {i}. {r['name']} ({r.get('type', '')})")
        return

    # ── 处理用户选择 ──
    if args.choice:
        last = get_last_recommendations("entertainment")
        chosen = None
        for r in last:
            if r["name"] == args.choice:
                chosen = r
                break
        if chosen:
            record_interaction("entertainment", "", last, user_choice=args.choice)
            print(f"✅ 已记录你的选择: {args.choice}")
        else:
            print(f"⚠️ 「{args.choice}」不在上次推荐中")
        return

    # ── 处理多轮追问 ──
    if args.query and is_followup_query(args.query):
        last = get_last_recommendations("entertainment")
        if last:
            chosen = resolve_followup(args.query, last)
            if chosen:
                record_interaction("entertainment", args.query, last, user_choice=chosen["name"])
                print(f"✅ 好的，选择 {chosen['name']}！")
                return

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
    query = f"{args.interest} {args.companion} {args.budget}".strip()
    context = infer_context_from_query(query) if query else {}

    # 获取天气信息
    weather_info = get_weather("济南")

    result = search(
        interest=args.interest,
        time_range=args.time_range,
        budget=args.budget,
        companion=args.companion,
        weather=args.weather,
        weather_info=weather_info,
        limit=args.limit,
        location=args.location,
        use_amap=not args.no_amap,
    )

    if not args.no_record:
        record_interaction(
            skill="entertainment",
            query=query or "(browse)",
            recommendations=result["results"],
            context=context,
        )

    print(format_output(result))


if __name__ == "__main__":
    main()
