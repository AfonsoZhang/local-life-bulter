#!/usr/bin/env python3
"""统一数据模型 — 本地生活管家核心 schema

所有模块共用的数据结构定义，替代散装 dict。
使用 Python dataclass（零外部依赖），提供 from_dict/to_dict 互转。

设计原则：
1. 自底向上：先定义基础模型（Location），再组合复杂模型
2. 渐进迁移：新代码用模型，旧 dict 通过 from_dict() 适配
3. 不破坏现有接口：to_dict() 确保序列化兼容
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


# ═══════════════════════════════════════════════════════════════
# 基础模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class Location:
    """经纬度坐标"""
    longitude: float = 0.0   # 经度
    latitude: float = 0.0    # 纬度
    address: str = ""        # 文字地址

    @property
    def amap_str(self) -> str:
        """高德 API 格式: "lng,lat" """
        return f"{self.longitude},{self.latitude}"

    @classmethod
    def from_amap(cls, location_str: str, address: str = "") -> Optional[Location]:
        """从高德 "lng,lat" 字符串创建"""
        if not location_str:
            return None
        parts = location_str.split(",")
        if len(parts) != 2:
            return None
        try:
            return cls(
                longitude=float(parts[0]),
                latitude=float(parts[1]),
                address=address,
            )
        except ValueError:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "longitude": self.longitude,
            "latitude": self.latitude,
            "address": self.address,
            "amap_str": self.amap_str,
        }


# ═══════════════════════════════════════════════════════════════
# 餐饮模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class Restaurant:
    """餐厅/餐饮推荐"""
    id: str = ""
    name: str = ""
    cuisine: str = ""                        # 菜系: 火锅/川菜/西餐...
    rating: float = 0.0                      # 评分 0-5
    price_range: str = ""                    # 价格描述: "人均80"
    budget_level: str = "medium"             # low / medium / high
    address: str = ""
    location: Optional[Location] = None
    distance_km: Optional[float] = None      # 距用户距离
    zone: str = ""                           # 区域标识
    zone_label: str = ""                     # 区域显示名
    good_for: List[str] = field(default_factory=list)    # 适合场景: ["约会", "朋友"]
    meal_type: List[str] = field(default_factory=list)   # 适合餐段: ["lunch", "dinner"]
    nearby_zones: List[str] = field(default_factory=list)  # 附近区域（本地数据用）
    tel: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    source: str = ""                         # amap / local
    opening_hours: str = ""

    # ── 转换 ──

    @classmethod
    def from_amap_poi(cls, poi: Dict) -> Optional[Restaurant]:
        """从高德 POI dict 创建（原 _poi_to_restaurant 逻辑）"""
        name = poi.get("name", "")
        if not name:
            return None

        poi_type = poi.get("type", "")
        cuisine = _infer_cuisine(poi_type, name)
        budget_level = _infer_budget(poi.get("cost", ""))
        dist_m = poi.get("distance_m")
        dist_km = round(dist_m / 1000, 1) if dist_m else None
        rating = poi.get("rating") or 4.0

        loc = None
        lng, lat = poi.get("lng"), poi.get("lat")
        if lng is not None and lat is not None:
            loc = Location(longitude=lng, latitude=lat, address=poi.get("address", ""))

        return cls(
            id=f"amap_{poi.get('location', '').replace(',', '_')}",
            name=name,
            cuisine=cuisine,
            rating=rating,
            price_range=poi.get("cost", "") or "人均未知",
            budget_level=budget_level,
            address=poi.get("address", ""),
            location=loc,
            distance_km=dist_km,
            zone=poi.get("district", ""),
            zone_label=poi.get("district", ""),
            good_for=_infer_good_for(name, poi_type),
            meal_type=_infer_meal_type(poi.get("opening_hours", "")),
            tel=poi.get("tel", ""),
            description=f"{name}，{poi.get('address', '')}",
            tags=[cuisine],
            source="amap",
            opening_hours=poi.get("opening_hours", ""),
        )

    @classmethod
    def from_local_dict(cls, d: Dict) -> Restaurant:
        """从本地 JSON 数据创建"""
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            cuisine=d.get("cuisine", ""),
            rating=d.get("rating", 0),
            price_range=d.get("price_range", ""),
            budget_level=d.get("budget_level", "medium"),
            address=d.get("address", ""),
            location=Location.from_amap(d.get("location", ""), d.get("address", "")) if d.get("location") else None,
            distance_km=d.get("distance_km"),
            zone=d.get("zone", ""),
            zone_label=d.get("zone_label", ""),
            good_for=d.get("good_for", []),
            meal_type=d.get("meal_type", []),
            nearby_zones=d.get("nearby_zones", []),
            description=d.get("description", ""),
            tags=d.get("tags", []),
            source="local",
        )

    def to_dict(self) -> Dict[str, Any]:
        """转为 dict（向后兼容旧代码）"""
        d = asdict(self)
        # Location 对象也展平
        if self.location:
            d["location"] = self.location.amap_str
            d["lng"] = self.location.longitude
            d["lat"] = self.location.latitude
        else:
            d["location"] = ""
            d["lng"] = None
            d["lat"] = None
        return d


# ═══════════════════════════════════════════════════════════════
# 娱乐/活动模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class EntertainmentEvent:
    """娱乐活动/景点"""
    id: str = ""
    name: str = ""
    type: str = ""                           # movie/exhibition/performance/game/sports/outdoor/nightlife/shopping/other
    venue: str = ""                          # 场馆名
    address: str = ""
    location: Optional[Location] = None
    distance_km: Optional[float] = None
    zone: str = ""
    zone_label: str = ""
    time: str = ""                           # 营业/演出时间
    duration_min: int = 120                  # 建议游览时长
    price_yuan: int = 0                      # 门票/费用
    rating: float = 0.0
    description: str = ""
    tags: List[str] = field(default_factory=list)
    companion: List[str] = field(default_factory=list)     # 适合同行人: solo/couple/family/friends
    weather_independent: bool = False        # 是否不受天气影响
    nearby_zones: List[str] = field(default_factory=list)  # 附近区域（本地数据用）
    date: str = ""                           # 活动日期（有期限的活动）
    source: str = ""                         # amap / local

    # ── 转换 ──

    @classmethod
    def from_amap_poi(cls, poi: Dict) -> Optional[EntertainmentEvent]:
        """从高德 POI dict 创建（原 _poi_to_event 逻辑）"""
        name = poi.get("name", "")
        if not name:
            return None

        poi_type = poi.get("type", "")
        event_type = _infer_event_type(poi_type, name)

        # 过滤非娱乐场所
        exclude_keywords = [
            "酒店", "宾馆", "民宿", "公寓", "商店", "服装", "女装", "男装", "超市",
            "便利店", "药店", "银行", "诊所", "医院", "学校", "幼儿园", "公司",
            "写字楼", "办公", "房产", "中介", "维修", "家政",
        ]
        if any(kw in name for kw in exclude_keywords):
            return None
        if event_type == "other":
            entertainment_keywords = [
                "电影", "展", "剧场", "演出", "音乐", "运动", "健身",
                "游泳", "公园", "景区", "密室", "剧本杀", "KTV", "酒吧",
                "高尔夫", "球", "滑冰", "滑雪", "马术", "射箭", "攀岩",
            ]
            if not any(kw in name for kw in entertainment_keywords):
                return None

        dist_m = poi.get("distance_m")
        dist_km = round(dist_m / 1000, 1) if dist_m else None
        rating = poi.get("rating") or 4.0
        cost = poi.get("cost", "")
        price_yuan = _parse_cost(cost)

        loc = None
        lng, lat = poi.get("lng"), poi.get("lat")
        if lng is not None and lat is not None:
            loc = Location(longitude=lng, latitude=lat, address=poi.get("address", ""))

        return cls(
            id=f"amap_{poi.get('location', '').replace(',', '_')}",
            name=name,
            type=event_type,
            venue=name,
            address=poi.get("address", ""),
            location=loc,
            distance_km=dist_km,
            zone=poi.get("district", ""),
            zone_label=poi.get("district", ""),
            time=poi.get("opening_hours", "营业时间未知"),
            duration_min=120,
            price_yuan=price_yuan,
            rating=rating,
            description=f"{name}，{poi.get('address', '')}",
            tags=[event_type],
            companion=["solo", "couple", "family", "friends"],
            weather_independent=event_type in ("movie", "shopping", "exhibition"),
            source="amap",
        )

    @classmethod
    def from_local_dict(cls, d: Dict) -> EntertainmentEvent:
        """从本地 JSON 数据创建"""
        loc = None
        if d.get("location"):
            loc = Location.from_amap(d["location"], d.get("address", ""))

        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            type=d.get("type", ""),
            venue=d.get("venue", ""),
            address=d.get("address", ""),
            location=loc,
            distance_km=d.get("distance_km"),
            zone=d.get("zone", ""),
            zone_label=d.get("zone_label", ""),
            time=d.get("time", ""),
            duration_min=d.get("duration_min", 120),
            price_yuan=d.get("price_yuan", 0),
            rating=d.get("rating", 0),
            description=d.get("description", ""),
            tags=d.get("tags", []),
            companion=d.get("companion", []),
            weather_independent=d.get("weather_independent", False),
            nearby_zones=d.get("nearby_zones", []),
            date=d.get("date", ""),
            source="local",
        )

    def to_dict(self) -> Dict[str, Any]:
        """转为 dict（向后兼容）"""
        d = asdict(self)
        if self.location:
            d["location"] = self.location.amap_str
            d["lng"] = self.location.longitude
            d["lat"] = self.location.latitude
        else:
            d["location"] = ""
            d["lng"] = None
            d["lat"] = None
        return d


# ═══════════════════════════════════════════════════════════════
# 出行/路线模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class RouteOption:
    """单个出行方案"""
    mode: str = ""           # walk / transit / taxi / bike
    time_min: int = 0
    cost_yuan: float = 0.0
    distance_km: float = 0.0
    description: str = ""
    source: str = ""         # amap / local

    @classmethod
    def from_dict(cls, d: Dict) -> RouteOption:
        return cls(
            mode=d.get("mode", ""),
            time_min=d.get("time_min", 0),
            cost_yuan=d.get("cost_yuan", 0),
            distance_km=d.get("distance_km", 0),
            description=d.get("description", ""),
            source=d.get("source", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RouteInfo:
    """完整路线信息"""
    origin: str = ""
    destination: str = ""
    dest_location: Optional[Location] = None
    dest_city: str = ""
    options: List[RouteOption] = field(default_factory=list)
    recommendation: str = ""     # 推荐的出行方式 mode
    reason: str = ""
    data_source: str = ""

    @classmethod
    def from_dict(cls, d: Dict) -> RouteInfo:
        dest_loc = None
        if d.get("dest_location"):
            dest_loc = Location.from_amap(d["dest_location"])

        return cls(
            origin=d.get("origin", ""),
            destination=d.get("destination", ""),
            dest_location=dest_loc,
            dest_city=d.get("dest_city", ""),
            options=[RouteOption.from_dict(o) for o in d.get("options", [])],
            recommendation=d.get("recommendation", ""),
            reason=d.get("reason", ""),
            data_source=d.get("data_source", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "origin": self.origin,
            "destination": self.destination,
            "dest_location": self.dest_location.amap_str if self.dest_location else "",
            "dest_city": self.dest_city,
            "options": [o.to_dict() for o in self.options],
            "recommendation": self.recommendation,
            "reason": self.reason,
            "data_source": self.data_source,
        }
        return d


# ═══════════════════════════════════════════════════════════════
# 推荐结果包装
# ═══════════════════════════════════════════════════════════════


@dataclass
class ActivityPlan:
    """活动 + 用餐方案"""
    event: Optional[EntertainmentEvent] = None
    restaurants: List[Restaurant] = field(default_factory=list)
    route: Optional[RouteInfo] = None
    timeline: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event.to_dict() if self.event else None,
            "restaurants": [r.to_dict() for r in self.restaurants],
            "route": self.route.to_dict() if self.route else None,
            "timeline": self.timeline,
        }


@dataclass
class DayPlan:
    """一天行程"""
    events: List[EntertainmentEvent] = field(default_factory=list)
    lunch: List[Restaurant] = field(default_factory=list)
    dinner: List[Restaurant] = field(default_factory=list)
    route: Optional[RouteInfo] = None
    timeline: List[Dict] = field(default_factory=list)
    existing_events: List[Dict] = field(default_factory=list)   # 日历已有日程（保持 dict，来自 cal_manager）
    free_slots: List[Dict] = field(default_factory=list)         # 空闲时段（同上）
    calendar_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "lunch": [r.to_dict() for r in self.lunch],
            "dinner": [r.to_dict() for r in self.dinner],
            "route": self.route.to_dict() if self.route else None,
            "timeline": self.timeline,
            "existing_events": self.existing_events,
            "free_slots": self.free_slots,
            "calendar_warnings": self.calendar_warnings,
        }


@dataclass
class NearbyPlan:
    """目的地附近推荐"""
    destination: str = ""
    route: Optional[RouteInfo] = None
    events: List[EntertainmentEvent] = field(default_factory=list)
    restaurants: List[Restaurant] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "destination": self.destination,
            "route": self.route.to_dict() if self.route else None,
            "events": [e.to_dict() for e in self.events],
            "restaurants": [r.to_dict() for r in self.restaurants],
        }


@dataclass
class ChainResult:
    """交叉联动完整结果"""
    plans: List[Any] = field(default_factory=list)   # List[ActivityPlan | DayPlan | NearbyPlan]
    chain_type: str = ""           # after_activity / plan_day / nearby
    weather_info: Any = None       # WeatherInfo from weather.py（保持原类型）
    calendar_context: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plans": [p.to_dict() for p in self.plans],
            "chain_type": self.chain_type,
            "weather_info": self.weather_info,  # WeatherInfo 已有 __dict__
            "calendar_context": self.calendar_context,
        }


# ═══════════════════════════════════════════════════════════════
# 推断函数（从 chains.py 迁移，集中管理）
# ═══════════════════════════════════════════════════════════════


def _infer_cuisine(poi_type: str, name: str) -> str:
    """从 POI 类型和名称推断菜系"""
    cuisine_map = [
        ("火锅", "火锅"), ("烧烤", "烧烤"), ("日料", "日本料理"),
        ("日", "日本料理"), ("韩", "韩国料理"), ("西餐", "西餐"),
        ("面", "面食"), ("咖啡", "咖啡"), ("奶茶", "茶饮"),
        ("甜品", "甜品"), ("海鲜", "海鲜"),
        ("川菜", "川菜"), ("湘菜", "湘菜"), ("粤菜", "粤菜"),
        ("浙菜", "浙菜"), ("本帮", "本帮菜"), ("杭帮", "杭帮菜"),
        ("东北菜", "东北菜"), ("新疆菜", "新疆菜"), ("泰国菜", "泰国菜"),
        ("意大利", "意大利菜"), ("快餐", "快餐"), ("小吃", "小吃"),
        ("串", "烧烤"), ("烤", "烧烤"), ("炸鸡", "西式快餐"),
        ("包子", "面食"), ("饺子", "面食"), ("拉面", "面食"),
        ("麻辣烫", "小吃"), ("米线", "小吃"), ("粥", "粥店"),
        ("茶", "茶馆"), ("酒", "酒馆"), ("酒吧", "酒吧"),
    ]
    for keyword, cuisine in cuisine_map:
        if keyword in name:
            return cuisine
    if "050000" in poi_type or "餐饮" in poi_type:
        return "餐饮"
    return "其他"


def _infer_budget(cost_str: str) -> str:
    """从费用字符串推断预算等级"""
    if not cost_str:
        return "medium"
    nums = re.findall(r"\d+", cost_str)
    if not nums:
        return "medium"
    avg = sum(int(n) for n in nums) / len(nums)
    if avg < 40:
        return "low"
    elif avg < 120:
        return "medium"
    else:
        return "high"


def _parse_cost(cost_str: str) -> int:
    """从费用字符串解析价格"""
    if not cost_str:
        return 0
    nums = re.findall(r"\d+", cost_str)
    if not nums:
        return 0
    return int(sum(int(n) for n in nums) / len(nums))


def _infer_good_for(name: str, poi_type: str) -> List[str]:
    """推断餐厅适合的场景"""
    good_for = []
    if any(kw in name for kw in ["咖啡", "甜品", "奶茶"]):
        good_for.extend(["约会", "一个人"])
    if any(kw in name for kw in ["火锅", "烧烤", "聚"]):
        good_for.extend(["朋友", "聚餐"])
    if any(kw in name for kw in ["家庭", "亲子", "粥", "面"]):
        good_for.append("家庭")
    if not good_for:
        good_for = ["朋友", "一个人"]
    return good_for


def _infer_meal_type(hours: str) -> List[str]:
    """从营业时间推断适合的餐段"""
    if not hours:
        return ["lunch", "dinner"]
    meal_types = []
    if any(kw in hours for kw in ["06:", "07:", "08:", "早餐"]):
        meal_types.append("breakfast")
    if any(kw in hours for kw in ["11:", "12:", "午餐"]):
        meal_types.append("lunch")
    if any(kw in hours for kw in ["14:", "15:", "16:", "下午"]):
        meal_types.append("afternoon")
    if any(kw in hours for kw in ["17:", "18:", "19:", "晚餐"]):
        meal_types.append("dinner")
    if any(kw in hours for kw in ["20:", "21:", "22:", "23:", "夜"]):
        meal_types.append("late_night")
    return meal_types if meal_types else ["lunch", "dinner"]


def _infer_event_type(poi_type: str, name: str) -> str:
    """从 POI 类型和名称推断活动类型"""
    if any(kw in name for kw in ["电影", "影城", "影院", "IMAX"]):
        return "movie"
    if any(kw in name for kw in ["展", "美术馆", "博物馆", "画廊"]):
        return "exhibition"
    if any(kw in name for kw in ["剧院", "演出", "话剧", "音乐"]):
        return "performance"
    if any(kw in name for kw in ["密室", "剧本杀", "桌游"]):
        return "game"
    if any(kw in name for kw in ["运动", "健身", "游泳", "球"]):
        return "sports"
    if any(kw in name for kw in ["公园", "景区", "风景"]):
        return "outdoor"
    if any(kw in name for kw in ["KTV", "酒吧", "夜店"]):
        return "nightlife"
    if any(kw in name for kw in ["商场", "购物", "mall"]):
        return "shopping"
    return "other"


# ═══════════════════════════════════════════════════════════════
# 批量转换工具
# ═══════════════════════════════════════════════════════════════


def restaurants_from_pois(pois: List[Dict]) -> List[Restaurant]:
    """批量将高德 POI 列表转为 Restaurant 列表"""
    results = []
    for poi in pois:
        r = Restaurant.from_amap_poi(poi)
        if r:
            results.append(r)
    return results


def events_from_pois(pois: List[Dict]) -> List[EntertainmentEvent]:
    """批量将高德 POI 列表转为 EntertainmentEvent 列表"""
    results = []
    for poi in pois:
        e = EntertainmentEvent.from_amap_poi(poi)
        if e:
            results.append(e)
    return results


def restaurants_to_dicts(restaurants: List[Restaurant]) -> List[Dict]:
    """批量将 Restaurant 转为 dict（向后兼容）"""
    return [r.to_dict() for r in restaurants]


def events_to_dicts(events: List[EntertainmentEvent]) -> List[Dict]:
    """批量将 EntertainmentEvent 转为 dict（向后兼容）"""
    return [e.to_dict() for e in events]
