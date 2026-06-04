#!/usr/bin/env python3
"""高德地图 API 共享模块

封装高德地图 Web 服务 API，供各技能调用。
所有方法在 API 不可用时返回 None，调用方自行 fallback 到模拟数据。

配置：在 config/amap_config.json 中设置 key
"""

import json
import os
import urllib.request
import urllib.parse
import urllib.error
import threading
import time
from typing import List, Dict, Optional, Tuple

# ── 配置 ──────────────────────────────────────────────────────

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CORE_DIR)
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "amap_config.json")

# 默认城市（用于搜索）
DEFAULT_CITY = "济南"
# 默认中心坐标（济南市中心 — 省体育中心附近）
DEFAULT_CENTER = "117.054,36.651"

# 高德 API 基础 URL
BASE_URL = "https://restapi.amap.com/v3"


# ── 请求限流 ──────────────────────────────────────────────────

class _RateLimiter:
    """简单限流器：限制每秒请求数

    高德 API 限制：个人认证 3000次/秒，但并行调用容易触发瞬时峰值。
    保守设置：每秒最多 8 次请求，间隔至少 120ms。
    """
    def __init__(self, max_per_second: int = 8):
        self._interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter(max_per_second=4)


# ── 结果缓存 ──────────────────────────────────────────────────

class _TTLCache:
    """简单的 TTL + 容量上限缓存。线程安全。

    用 monotonic() 防系统时间变化干扰。
    超容量时驱逐最旧条目。
    """
    def __init__(self, ttl_seconds: int = 300, max_size: int = 256):
        self._ttl = ttl_seconds
        self._max = max_size
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[float, dict]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                self._misses += 1
                return None
            ts, val = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return val

    def set(self, key: str, val: dict):
        with self._lock:
            if len(self._store) >= self._max:
                # 驱逐最旧
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
            self._store[key] = (time.monotonic(), val)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._store),
                "max_size": self._max,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            }


# 可通过环境变量调整 TTL：OPENCLAW_AMAP_CACHE_TTL=600
_cache_ttl = int(os.environ.get("OPENCLAW_AMAP_CACHE_TTL", "300"))
_cache_enabled = os.environ.get("OPENCLAW_AMAP_CACHE_DISABLE", "") != "1"
_response_cache = _TTLCache(ttl_seconds=_cache_ttl, max_size=512)


def get_cache_stats() -> dict:
    """暴露给外部检查缓存命中情况"""
    return _response_cache.stats()


def _load_api_key() -> Optional[str]:
    """加载 API Key"""
    # 1. 先从环境变量读
    key = os.environ.get("AMAP_API_KEY")
    if key:
        return key.strip()

    # 2. 从配置文件读
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("key", "").strip()
        except Exception:
            pass

    return None


def _request(url: str, params: dict, timeout: int = 10) -> Optional[dict]:
    """发起 GET 请求，返回 JSON 或 None。命中缓存则直接返回。"""
    params["key"] = _load_api_key()
    if not params["key"]:
        return None

    # 过滤空值
    params = {k: v for k, v in params.items() if v is not None and v != ""}
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"

    # 缓存 key（排除 API key，防止泄露 + 支持后续切 key）
    cache_key = ""
    if _cache_enabled:
        cache_params = {k: v for k, v in params.items() if k != "key"}
        cache_key = url + "?" + json.dumps(cache_params, sort_keys=True, ensure_ascii=False)
        hit = _response_cache.get(cache_key)
        if hit is not None:
            return hit

    # 限流（仅当 cache miss 时才走）
    _rate_limiter.acquire()

    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "local-life-butler/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "1":
                if _cache_enabled and cache_key:
                    _response_cache.set(cache_key, data)
                return data
            else:
                print(f"[amap_api] API error: {data.get('info', 'unknown')}")
                return None
    except urllib.error.URLError as e:
        print(f"[amap_api] Network error: {e}")
        return None
    except Exception as e:
        print(f"[amap_api] Error: {e}")
        return None


# ── POI 搜索 ──────────────────────────────────────────────────

def search_poi(
    keywords: str = "",
    types: str = "",
    city: str = DEFAULT_CITY,
    location: str = "",
    radius: int = 5000,
    sort_rule: str = "distance",  # distance | weight
    page_size: int = 20,
    page: int = 1,
) -> Optional[List[Dict]]:
    """搜索 POI（兴趣点）

    Args:
        keywords: 搜索关键词（如 "火锅" "电影院"）
        types: POI 类型编码（如 "050000"=餐饮, "080101"=电影院）
        city: 城市名称
        location: 中心点坐标 "lng,lat"（用于距离排序）
        radius: 搜索半径（米），需配合 location 使用
        sort_rule: 排序规则 distance=距离 weight=权重
        page_size: 每页数量（最多25）
        page: 页码

    Returns:
        POI 列表，每项包含 name, type, address, location, distance, tel, rating 等
    """
    params = {
        "keywords": keywords,
        "types": types,
        "city": city,
        "citylimit": "true",
        "offset": min(page_size, 25),
        "page": page,
        "extensions": "all",  # 获取详细信息
        "output": "json",
    }

    if location:
        params["location"] = location
        params["sortrule"] = sort_rule
        if radius:
            params["radius"] = radius

    data = _request(f"{BASE_URL}/place/text", params)
    if not data:
        return None

    pois = data.get("pois", [])
    results = []
    for poi in pois:
        # 解析坐标
        loc = poi.get("location", "")
        lng, lat = (None, None)
        if loc:
            parts = loc.split(",")
            if len(parts) == 2:
                try:
                    lng, lat = float(parts[0]), float(parts[1])
                except ValueError:
                    pass

        result = {
            "name": poi.get("name", ""),
            "type": poi.get("type", ""),
            "typecode": poi.get("typecode", ""),
            "address": poi.get("address", ""),
            "location": loc,
            "lng": lng,
            "lat": lat,
            "distance_m": _safe_int(poi.get("distance")),
            "tel": poi.get("tel", ""),
            "city": poi.get("cityname", ""),
            "district": poi.get("adname", ""),
            "business_area": poi.get("business_area", ""),
            "rating": _extract_rating(poi),
            "cost": poi.get("cost", ""),
            "opening_hours": _extract_hours(poi),
            "photos": [p.get("url", "") for p in poi.get("photos", [])[:3]],
            "navi_info": poi.get("navi", {}),
            "raw_type": poi.get("type", ""),
        }
        results.append(result)

    return results


def search_poi_around(
    keywords: str = "",
    types: str = "",
    location: str = "",
    radius: int = 3000,
    sort_rule: str = "distance",
    page_size: int = 20,
) -> Optional[List[Dict]]:
    """周边搜索（基于坐标）"""
    params = {
        "keywords": keywords,
        "types": types,
        "location": location,
        "radius": radius,
        "sortrule": sort_rule,
        "offset": min(page_size, 25),
        "extensions": "all",
        "output": "json",
    }

    data = _request(f"{BASE_URL}/place/around", params)
    if not data:
        return None

    pois = data.get("pois", [])
    results = []
    for poi in pois:
        loc = poi.get("location", "")
        lng, lat = (None, None)
        if loc:
            parts = loc.split(",")
            if len(parts) == 2:
                try:
                    lng, lat = float(parts[0]), float(parts[1])
                except ValueError:
                    pass

        result = {
            "name": poi.get("name", ""),
            "type": poi.get("type", ""),
            "typecode": poi.get("typecode", ""),
            "address": poi.get("address", ""),
            "location": loc,
            "lng": lng,
            "lat": lat,
            "distance_m": _safe_int(poi.get("distance")),
            "tel": poi.get("tel", ""),
            "rating": _extract_rating(poi),
            "cost": poi.get("cost", ""),
            "opening_hours": _extract_hours(poi),
        }
        results.append(result)

    return results


# ── 距离校验 ──────────────────────────────────────────────────

def validate_distance(
    pois: List[Dict],
    origin: str = "",
    max_distance_m: int = 5000,
    max_duration_s: int = 0,
    mode: str = "straight",  # straight | driving | walking
) -> List[Dict]:
    """校验并过滤 POI 列表的距离

    Args:
        pois: POI 列表（需含 location 字段）
        origin: 起点坐标 "lng,lat"，为空则用用户默认位置
        max_distance_m: 最大直线距离（米），默认 5km
        max_duration_s: 最大出行时间（秒），仅 mode=driving/walking 时生效
        mode: 校验模式
            - straight: 直线距离（快速，无需额外 API 调用）
            - driving: 驾车距离和时间（需 API 调用，较慢）
            - walking: 步行距离和时间（需 API 调用，较慢）

    Returns:
        过滤后的 POI 列表，每项增加 _distance_m 字段
    """
    if not origin:
        origin = load_user_location().get("center", DEFAULT_CENTER)

    origin_parts = origin.split(",")
    if len(origin_parts) != 2:
        return pois
    try:
        o_lng, o_lat = float(origin_parts[0]), float(origin_parts[1])
    except ValueError:
        return pois

    filtered = []
    for poi in pois:
        loc = poi.get("location", "")
        if not loc:
            continue

        if mode == "straight":
            # 直线距离：用 Haversine 公式快速计算，无需 API 调用
            p_parts = loc.split(",")
            if len(p_parts) != 2:
                continue
            try:
                p_lng, p_lat = float(p_parts[0]), float(p_parts[1])
            except ValueError:
                continue
            dist = _haversine_m(o_lng, o_lat, p_lng, p_lat)
            if dist <= max_distance_m:
                poi["_straight_distance_m"] = int(dist)
                filtered.append(poi)

        elif mode == "driving":
            result = plan_driving(origin, loc)
            if result and result.get("distance_m"):
                if max_duration_s and result.get("duration_s", 0) > max_duration_s:
                    continue
                if result["distance_m"] <= max_distance_m:
                    poi["_driving_distance_m"] = result["distance_m"]
                    poi["_driving_duration_s"] = result["duration_s"]
                    filtered.append(poi)

        elif mode == "walking":
            result = plan_walking(origin, loc)
            if result and result.get("distance_m"):
                if max_duration_s and result.get("duration_s", 0) > max_duration_s:
                    continue
                if result["distance_m"] <= max_distance_m:
                    poi["_walking_distance_m"] = result["distance_m"]
                    poi["_walking_duration_s"] = result["duration_s"]
                    filtered.append(poi)

    return filtered


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Haversine 公式：计算两点间直线距离（米）"""
    import math
    R = 6371000  # 地球半径（米）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def search_nearby_validated(
    keywords: str = "",
    types: str = "",
    city: str = DEFAULT_CITY,
    origin: str = "",
    radius: int = 5000,
    max_straight_m: int = 0,
    max_driving_m: int = 0,
    max_driving_s: int = 0,
    max_walking_m: int = 0,
    max_walking_s: int = 0,
    page_size: int = 20,
) -> Optional[List[Dict]]:
    """搜索 POI 并自动校验距离

    便捷函数：先搜索，再按距离过滤。

    Args:
        keywords: 搜索关键词
        types: POI 类型编码
        city: 城市
        origin: 起点坐标，为空则用用户默认位置
        radius: 搜索半径（米）
        max_straight_m: 最大直线距离过滤（米），0=不过滤
        max_driving_m: 最大驾车距离过滤（米），0=不过滤
        max_driving_s: 最大驾车时间过滤（秒），0=不过滤
        max_walking_m: 最大步行距离过滤（米），0=不过滤
        max_walking_s: 最大步行时间过滤（秒），0=不过滤
        page_size: 返回数量

    Returns:
        过滤后的 POI 列表，或 None
    """
    if not origin:
        origin = load_user_location().get("center", DEFAULT_CENTER)

    # 第一步：POI 搜索（用 origin 做距离排序）
    pois = search_poi(
        keywords=keywords,
        types=types,
        city=city,
        location=origin,
        radius=radius,
        sort_rule="distance",
        page_size=page_size,
    )
    if not pois:
        return None

    # 第二步：直线距离过滤（快速，无 API 调用）
    if max_straight_m:
        pois = validate_distance(pois, origin=origin, max_distance_m=max_straight_m, mode="straight")

    # 第三步：驾车距离过滤（需 API 调用）
    if max_driving_m or max_driving_s:
        pois = validate_distance(
            pois, origin=origin,
            max_distance_m=max_driving_m or 999999,
            max_duration_s=max_driving_s,
            mode="driving",
        )

    # 第四步：步行距离过滤（需 API 调用）
    if max_walking_m or max_walking_s:
        pois = validate_distance(
            pois, origin=origin,
            max_distance_m=max_walking_m or 999999,
            max_duration_s=max_walking_s,
            mode="walking",
        )

    return pois if pois else None


# ── 推荐去重 ──────────────────────────────────────────────────

def deduplicate_pois(
    pois: List[Dict],
    history_file: str = "",
    name_threshold: float = 0.8,
    location_threshold_m: int = 50,
) -> List[Dict]:
    """POI 推荐去重

    三种去重策略：
    1. 按名称完全匹配去重（同一个店）
    2. 按坐标距离去重（50m 内视为同一地点）
    3. 按历史记录去重（排除用户已去过的地方）

    Args:
        pois: POI 列表（需含 name, location 字段）
        history_file: 历史记录文件路径，为空则跳过历史去重
        name_threshold: 名称相似度阈值（0-1），用于模糊匹配
        location_threshold_m: 坐标距离阈值（米），小于此距离视为同一地点

    Returns:
        去重后的 POI 列表
    """
    if not pois:
        return []

    # 加载历史记录（已去过的地方）
    visited_names = set()
    visited_locs = set()
    if history_file and os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            for record in history.get("visits", []):
                name = record.get("name", "")
                loc = record.get("location", "")
                if name:
                    visited_names.add(name.lower())
                if loc:
                    visited_locs.add(loc)
        except Exception:
            pass

    seen_names = set()
    seen_locs = []  # [(lng, lat, name)]
    result = []

    for poi in pois:
        name = poi.get("name", "").strip()
        loc = poi.get("location", "")

        if not name:
            continue

        name_lower = name.lower()

        # 策略 1：名称完全匹配去重
        if name_lower in seen_names:
            continue

        # 策略 2：坐标距离去重
        if loc:
            parts = loc.split(",")
            if len(parts) == 2:
                try:
                    lng, lat = float(parts[0]), float(parts[1])
                    is_dup = False
                    for seen_lng, seen_lat, _ in seen_locs:
                        if _haversine_m(lng, lat, seen_lng, seen_lat) < location_threshold_m:
                            is_dup = True
                            break
                    if is_dup:
                        continue
                    seen_locs.append((lng, lat, name))
                except ValueError:
                    pass

        # 策略 3：历史记录去重
        if name_lower in visited_names:
            poi["_visited"] = True
            # 不跳过，但标记为已去过，让调用方决定是否展示

        if loc in visited_locs:
            poi["_visited"] = True

        seen_names.add(name_lower)
        result.append(poi)

    return result


# ── 路径规划 ──────────────────────────────────────────────────

def plan_driving(
    origin: str,
    destination: str,
    strategy: int = 0,
    extensions: str = "all",
) -> Optional[Dict]:
    """驾车路径规划

    Args:
        origin: 起点坐标 "lng,lat"
        destination: 终点坐标 "lng,lat"
        strategy: 驾车策略 0=速度优先 2=距离优先 4=避免拥堵

    Returns:
        {distance_m, duration_s, tolls_yuan, traffic_lights, steps}
    """
    params = {
        "origin": origin,
        "destination": destination,
        "strategy": strategy,
        "extensions": extensions,
        "output": "json",
    }

    data = _request(f"{BASE_URL}/direction/driving", params)
    if not data:
        return None

    route = data.get("route", {})
    paths = route.get("paths", [])
    if not paths:
        return None

    best = paths[0]
    return {
        "distance_m": _safe_int(best.get("distance")),
        "duration_s": _safe_int(best.get("duration")),
        "tolls_yuan": _safe_float(best.get("tolls")),
        "traffic_lights": _safe_int(best.get("trafficlights")),
        "steps": _parse_driving_steps(best.get("steps", [])),
        "raw": best,
    }


def plan_walking(
    origin: str,
    destination: str,
) -> Optional[Dict]:
    """步行路径规划"""
    params = {
        "origin": origin,
        "destination": destination,
        "output": "json",
    }

    data = _request(f"{BASE_URL}/direction/walking", params)
    if not data:
        return None

    route = data.get("route", {})
    paths = route.get("paths", [])
    if not paths:
        return None

    best = paths[0]
    return {
        "distance_m": _safe_int(best.get("distance")),
        "duration_s": _safe_int(best.get("duration")),
        "steps": _parse_walk_steps(best.get("steps", [])),
    }


def plan_transit(
    origin: str,
    destination: str,
    city: str = DEFAULT_CITY,
    strategy: int = 0,
) -> Optional[Dict]:
    """公交路径规划

    Args:
        origin: 起点坐标 "lng,lat"
        destination: 终点坐标 "lng,lat"
        city: 城市名称
        strategy: 0=综合最优 1=换乘少 2=步行少 3=不坐地铁 5=不坐公交

    Returns:
        {transits: [{duration_s, walking_m, cost_yuan, segments}]}
    """
    params = {
        "origin": origin,
        "destination": destination,
        "city": city,
        "strategy": strategy,
        "extensions": "all",
        "output": "json",
    }

    data = _request(f"{BASE_URL}/direction/transit/integrated", params)
    if not data:
        return None

    route = data.get("route", {})
    transits = route.get("transits", [])
    results = []
    for t in transits[:5]:
        segments = []
        for seg in t.get("segments", []):
            bus = seg.get("bus", {})
            if bus and bus.get("buslines"):
                line = bus["buslines"][0]
                segments.append({
                    "type": "bus",
                    "name": line.get("name", ""),
                    "depart_stop": line.get("departure_stop", {}).get("name", ""),
                    "arrive_stop": line.get("arrival_stop", {}).get("name", ""),
                    "stops": _safe_int(line.get("via_num")),
                    "price_yuan": _safe_float(line.get("price")),
                })
            railway = seg.get("railway", {})
            if railway and railway.get("name"):
                segments.append({
                    "type": "railway",
                    "name": railway.get("name", ""),
                    "depart_stop": railway.get("departure_stop", {}).get("name", ""),
                    "arrive_stop": railway.get("arrival_stop", {}).get("name", ""),
                })
            walking = seg.get("walking", {})
            if walking and walking.get("distance"):
                segments.append({
                    "type": "walk",
                    "distance_m": _safe_int(walking.get("distance")),
                    "duration_s": _safe_int(walking.get("duration")),
                })

        results.append({
            "duration_s": _safe_int(t.get("duration")),
            "walking_m": _safe_int(t.get("walking_distance")),
            "cost_yuan": _safe_float(t.get("cost")),
            "segments": segments,
        })

    return {"transits": results}


def plan_bicycling(
    origin: str,
    destination: str,
) -> Optional[Dict]:
    """骑行路径规划"""
    params = {
        "origin": origin,
        "destination": destination,
        "output": "json",
    }

    data = _request(f"{BASE_URL}/direction/bicycling", params)
    if not data:
        return None

    route = data.get("route", {})
    paths = route.get("paths", [])
    if not paths:
        return None

    best = paths[0]
    return {
        "distance_m": _safe_int(best.get("distance")),
        "duration_s": _safe_int(best.get("duration")),
    }


# ── 地理编码 ──────────────────────────────────────────────────

def geocode(address: str, city: str = DEFAULT_CITY) -> Optional[Dict]:
    """地址转坐标

    Returns:
        {lng, lat, formatted_address, province, city, district}
    """
    params = {
        "address": address,
        "city": city,
        "output": "json",
    }

    data = _request(f"{BASE_URL}/geocode/geo", params)
    if not data:
        return None

    geocodes = data.get("geocodes", [])
    if not geocodes:
        return None

    g = geocodes[0]
    loc = g.get("location", "")
    lng, lat = (None, None)
    if loc:
        parts = loc.split(",")
        if len(parts) == 2:
            try:
                lng, lat = float(parts[0]), float(parts[1])
            except ValueError:
                pass

    return {
        "lng": lng,
        "lat": lat,
        "location": loc,
        "formatted_address": g.get("formatted_address", ""),
        "province": g.get("province", ""),
        "city": g.get("city", ""),
        "district": g.get("district", ""),
    }


def reverse_geocode(location: str) -> Optional[Dict]:
    """坐标转地址

    Args:
        location: "lng,lat"

    Returns:
        {formatted_address, province, city, district}
    """
    params = {
        "location": location,
        "output": "json",
    }

    data = _request(f"{BASE_URL}/geocode/regeo", params)
    if not data:
        return None

    regeocode = data.get("regeocode", {})
    address = regeocode.get("addressComponent", {})

    return {
        "formatted_address": regeocode.get("formatted_address", ""),
        "province": address.get("province", ""),
        "city": address.get("city", ""),
        "district": address.get("district", ""),
        "township": address.get("township", ""),
        "neighborhood": address.get("neighborhood", {}).get("name", ""),
    }


# ── IP 定位 ──────────────────────────────────────────────────

def ip_location(ip: str = "") -> Optional[Dict]:
    """IP 定位，返回城市和坐标"""
    params = {"output": "json"}
    if ip:
        params["ip"] = ip

    data = _request(f"{BASE_URL}/ip", params)
    if not data:
        return None

    return {
        "province": data.get("province", ""),
        "city": data.get("city", ""),
        "adcode": data.get("adcode", ""),
        "lng": _safe_float(data.get("rectangle", "").split(";")[0].split(",")[0]) if data.get("rectangle") else None,
        "lat": _safe_float(data.get("rectangle", "").split(";")[0].split(",")[1]) if data.get("rectangle") else None,
    }


# ── 天气查询 ──────────────────────────────────────────────────

def get_weather_info(city: str = DEFAULT_CITY) -> Optional[Dict]:
    """查询实时天气

    Args:
        city: 城市名称（如 "济南"、"杭州"）

    Returns:
        {
            "city": 城市名,
            "weather": 天气状况（晴/多云/小雨等）,
            "temperature": 当前温度,
            "temperature_float": 浮点温度,
            "winddirection": 风向,
            "windpower": 风力,
            "humidity": 湿度,
            "reporttime": 报告时间,
        }
    """
    params = {
        "city": city,
        "extensions": "base",  # base=实况 weather=预报
        "output": "json",
    }
    data = _request(f"{BASE_URL}/weather/weatherInfo", params)
    if not data:
        return None

    lives = data.get("lives", [])
    if not lives:
        return None

    live = lives[0]
    return {
        "city": live.get("city", city),
        "weather": live.get("weather", ""),
        "temperature": live.get("temperature", "0"),
        "temperature_float": _safe_float(live.get("temperature")) or 0.0,
        "winddirection": live.get("winddirection", ""),
        "windpower": live.get("windpower", ""),
        "humidity": live.get("humidity", "0"),
        "reporttime": live.get("reporttime", ""),
    }


def get_weather_forecast(city: str = DEFAULT_CITY) -> Optional[List[Dict]]:
    """查询天气预报（未来4天）

    Returns:
        [{date, dayweather, nightweather, daytemp, nighttemp, daywind, nightwind, daypower, nightpower}]
    """
    params = {
        "city": city,
        "extensions": "all",
        "output": "json",
    }
    data = _request(f"{BASE_URL}/weather/weatherInfo", params)
    if not data:
        return None

    forecasts = data.get("forecasts", [])
    if not forecasts:
        return None

    casts = forecasts[0].get("casts", [])
    return casts


# ── 辅助函数 ──────────────────────────────────────────────────

def _name_overlaps(target: str, poi_name: str, min_len: int = 3) -> bool:
    """判断 POI 名称与用户输入的目标名是否有实质重叠

    用于校验 search_poi 模糊降级结果，过滤无关匹配（如乱码输入返回的随机 POI）。
    规则：一方完整包含另一方（处理短名/全称），或存在长度 >= min_len 的公共子串。
    min_len=3 是为了避开"广场/商城/大厦/中心"等 2 字通用后缀造成的假阳性。
    """
    import re
    def clean(s):
        return re.sub(r"[^一-龥A-Za-z0-9]", "", s or "").lower()
    t, p = clean(target), clean(poi_name)
    if not t or not p:
        return False
    if t in p or p in t:
        return True
    # 滑动窗口找公共子串
    for i in range(len(t) - min_len + 1):
        if t[i:i + min_len] in p:
            return True
    return False


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_rating(poi: dict) -> Optional[float]:
    """从 POI 数据中提取评分"""
    # 尝试多种字段
    for field in ["rating", "biz_ext.rating", "deep_info.rating"]:
        val = poi
        for key in field.split("."):
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def _extract_hours(poi: dict) -> str:
    """提取营业时间"""
    for field in ["biz_ext.opening_hours", "deep_info.opening_hours"]:
        val = poi
        for key in field.split("."):
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val and isinstance(val, str):
            return val
    return ""


def _parse_driving_steps(steps: list) -> list:
    """解析驾车步骤"""
    result = []
    for step in steps:
        result.append({
            "instruction": step.get("instruction", ""),
            "road": step.get("road", ""),
            "distance_m": _safe_int(step.get("distance")),
            "duration_s": _safe_int(step.get("duration")),
            "tolls_yuan": _safe_float(step.get("tolls")),
            "toll_distance_m": _safe_int(step.get("toll_distance")),
        })
    return result


def _parse_walk_steps(steps: list) -> list:
    """解析步行步骤"""
    result = []
    for step in steps:
        result.append({
            "instruction": step.get("instruction", ""),
            "road": step.get("road", ""),
            "distance_m": _safe_int(step.get("distance")),
            "duration_s": _safe_int(step.get("duration")),
        })
    return result


# ── 测试 ──────────────────────────────────────────────────────

# ── 用户位置管理 ──────────────────────────────────────────────

PREFERENCES_FILE = os.path.join(PROJECT_ROOT, "config", "preferences.json")


def load_user_location() -> Dict:
    """从 preferences.json 读取用户默认位置

    Returns:
        {city, location_name, center}  center 格式 "lng,lat"
    """
    city = DEFAULT_CITY
    location_name = ""
    center = ""

    if os.path.exists(PREFERENCES_FILE):
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            user_prefs = prefs.get("user_preferences", {})
            city = user_prefs.get("default_city", DEFAULT_CITY)
            location_name = user_prefs.get("default_location", "")
            center = user_prefs.get("default_center", "")
        except Exception:
            pass

    return {
        "city": city,
        "location_name": location_name,
        "center": center or DEFAULT_CENTER,
    }


def save_user_location(city: str = "", location_name: str = "", center: str = "", source: str = ""):
    """保存用户位置到 preferences.json

    Args:
        source: 位置来源标记 'confirmed'（用户确认）/ 'ip_guess'（IP定位猜测）/ ''（不改变）
                用于区分"用户明确告知"和"系统猜测"，避免把猜测当事实
    """
    from datetime import datetime
    prefs = {}
    if os.path.exists(PREFERENCES_FILE):
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                prefs = json.load(f)
        except Exception:
            pass

    user_prefs = prefs.setdefault("user_preferences", {})
    if city:
        user_prefs["default_city"] = city
    if location_name:
        user_prefs["default_location"] = location_name
    if center:
        user_prefs["default_center"] = center
    if source:
        user_prefs["location_source"] = source
        user_prefs["location_updated_at"] = datetime.now().isoformat(timespec="seconds")

    # 记录位置历史
    history = user_prefs.setdefault("location_history", [])
    entry = {"city": city or user_prefs.get("default_city", ""), "location": location_name or user_prefs.get("default_location", "")}
    if entry not in history:
        history.append(entry)
        # 只保留最近 10 条
        user_prefs["location_history"] = history[-10:]

    os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)
    with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


# ── 位置 bootstrap（对话式默认地址）────────────────────────────
# 设计：对话替代 App「设置 → 位置管理」。位置有三种来源：
#   confirmed → 用户明确告知，可当事实直接用
#   ip_guess  → IP 定位猜测，搜索可用但需向用户确认，禁止当事实陈述
#   default   → 无任何信息，硬编码兜底，必须问用户
# 硬约束：ip_guess / default 状态下，禁止对用户断言"你在XX"，只能反问确认。

def get_location_state() -> Dict:
    """读取完整位置状态（含来源标记），供 agent 判断是否需要确认

    Returns:
        {city, location_name, center, source, is_confirmed, updated_at}
        source: 'confirmed' / 'ip_guess' / 'default'
    """
    loc = load_user_location()
    source = "default"
    updated_at = ""
    if os.path.exists(PREFERENCES_FILE):
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            up = prefs.get("user_preferences", {})
            source = up.get("location_source", "default")
            updated_at = up.get("location_updated_at", "")
        except Exception:
            pass
    loc["source"] = source
    loc["is_confirmed"] = (source == "confirmed")
    loc["updated_at"] = updated_at
    return loc


def bootstrap_location(force: bool = False) -> Dict:
    """首次使用时通过 IP 定位猜测位置（绝不覆盖已确认的位置）

    Args:
        force: True 时即使已确认也重新 IP 定位（用于"我换城市了"场景）

    Returns:
        {status, city, location_name, center, source}
        status: 'confirmed'（已有确认位置，直接用）
                'guessed'  （IP 定位成功，已存为 ip_guess，需向用户确认）
                'need_ask' （IP 定位失败，需直接问用户在哪个城市）
    """
    state = get_location_state()
    if state["is_confirmed"] and not force:
        return {
            "status": "confirmed",
            "city": state["city"],
            "location_name": state["location_name"],
            "center": state["center"],
            "source": "confirmed",
        }

    ip = ip_location()
    if ip and ip.get("city"):
        center = ""
        if ip.get("lng") is not None and ip.get("lat") is not None:
            center = f"{ip['lng']},{ip['lat']}"
        save_user_location(city=ip["city"], center=center, source="ip_guess")
        return {
            "status": "guessed",
            "city": ip["city"],
            "province": ip.get("province", ""),
            "location_name": "",
            "center": center,
            "source": "ip_guess",
        }

    return {
        "status": "need_ask",
        "city": "",
        "location_name": "",
        "center": "",
        "source": "default",
    }


def confirm_location(query: str = "", city: str = "", location_name: str = "") -> Dict:
    """确认/修正位置（用户显式输入），标记为 confirmed

    Args:
        query: 用户自然语言（如"我在和谐广场"），会自动提取+地理编码
        city / location_name: 直接指定（query 为空时使用）

    Returns:
        {status: 'ok'|'failed', city, location_name, center, source}
    """
    resolved_city = city
    resolved_name = location_name
    center = ""

    # 城市作用域：显式指定 > 当前已知城市 > 默认。
    # 关键：裸地名（如"和谐广场"）必须限定在已知城市内，否则会跨省误匹配。
    scope_city = city or get_location_state().get("city") or DEFAULT_CITY

    target = ""
    if query:
        target = extract_location_from_query(query)
        if not target:
            # 提取失败时剥离常见前缀（"我在/我现在在/在"），避免脏字符进入地名
            import re
            target = re.sub(r"^(我现在在|我在|现在在|我|在)", "", query.strip()).strip()
    elif location_name:
        target = location_name

    if target:
        resolved_name = target
        # 先 geocode（适合地址），失败则降级 search_poi（适合商圈/商场等 POI），均限定城市
        geo = geocode(target, city=scope_city)
        if geo and geo.get("location"):
            center = geo["location"]
            resolved_city = geo.get("city") or scope_city
        else:
            pois = search_poi(keywords=target, city=scope_city, page_size=1)
            # 校验：POI 名称须与目标名有重叠，否则可能是无关的模糊匹配（防乱码静默"确认"）
            if pois and pois[0].get("location") and _name_overlaps(target, pois[0].get("name", "")):
                center = pois[0]["location"]
                resolved_name = pois[0].get("name", target)
                resolved_city = scope_city
        # 解析不到坐标时，不沿用旧坐标冒充确认
        if not center:
            return {"status": "failed", "city": "", "location_name": target, "center": "", "source": "default"}
    else:
        # 仅确认城市（无具体地点）
        resolved_city = scope_city

    if not resolved_city and not center:
        return {"status": "failed", "city": "", "location_name": "", "center": "", "source": "default"}

    save_user_location(
        city=resolved_city,
        location_name=resolved_name,
        center=center,
        source="confirmed",
    )
    return {
        "status": "ok",
        "city": resolved_city or load_user_location()["city"],
        "location_name": resolved_name,
        "center": center,
        "source": "confirmed",
    }


def extract_location_from_query(query: str) -> Optional[str]:
    """从自然语言查询中提取位置信息

    匹配模式：
    - "我在XXX附近"
    - "我在XXX"
    - "XXX附近"
    - "从XXX到XXX"
    """
    import re
    patterns = [
        r"我在(.{2,10}?)(?:附近|旁边|这儿|这里|周边)",
        r"我在(.{2,10})$",
        r"(.{2,10}?)(?:附近|旁边|周边)",
        r"从(.{2,10}?)(?:到|去)",
    ]
    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            return match.group(1).strip()
    return None


def resolve_location(query: str = "") -> Dict:
    """解析用户位置：查询 > 配置 > 默认

    Args:
        query: 用户的自然语言查询

    Returns:
        {city, location_name, center}  center 格式 "lng,lat"
    """
    # 1. 尝试从查询中提取位置
    if query:
        extracted = extract_location_from_query(query)
        if extracted:
            geo = geocode(extracted)
            if geo and geo.get("location"):
                return {
                    "city": geo.get("city", DEFAULT_CITY),
                    "location_name": extracted,
                    "center": geo["location"],
                }

    # 2. 从配置读取
    loc = load_user_location()
    # 如果配置的 center 无效，尝试地理编码
    if loc["location_name"] and loc["center"] == DEFAULT_CENTER:
        geo = geocode(loc["location_name"], city=loc["city"])
        if geo and geo.get("location"):
            loc["center"] = geo["location"]
    return loc


def test_api():
    """快速测试 API 是否可用"""
    key = _load_api_key()
    if not key:
        print("❌ 未配置 API Key")
        print(f"   请设置环境变量 AMAP_API_KEY 或创建 {CONFIG_FILE}")
        return False

    print(f"✅ API Key: {key[:8]}...{key[-4:]}")

    # 测试 IP 定位
    print("\n📍 测试 IP 定位...")
    loc = ip_location()
    if loc:
        print(f"   位置: {loc.get('province')} {loc.get('city')}")
    else:
        print("   ❌ IP 定位失败")

    # 测试 POI 搜索
    print("\n🍽  测试 POI 搜索（火锅）...")
    pois = search_poi(keywords="火锅", city="杭州", page_size=3)
    if pois:
        for p in pois[:3]:
            print(f"   {p['name']} - {p['address']} ({p.get('distance_m', '?')}m)")
    else:
        print("   ❌ POI 搜索失败")

    # 测试地理编码
    print("\n🗺  测试地理编码（西湖）...")
    geo = geocode("西湖景区", city="杭州")
    if geo:
        print(f"   坐标: {geo['location']} | {geo['formatted_address']}")
    else:
        print("   ❌ 地理编码失败")

    return True


if __name__ == "__main__":
    test_api()
