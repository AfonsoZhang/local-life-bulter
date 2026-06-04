#!/usr/bin/env python3
"""天气感知模块 - 高德天气 API + wttr.in fallback

功能：
1. 获取当前天气（温度、体感、降水、风速、天气状况）
2. 判断天气是否适合户外活动
3. 根据天气推荐室内/室外替代方案

优先使用高德天气 API（实时数据，与位置系统共享 Key），
API 不可用时自动降级到 wttr.in。
"""

import json
import subprocess
import re
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

# 尝试导入高德 API
try:
    from amap_api import get_weather_info, load_user_location
    HAS_AMAP = True
except ImportError:
    HAS_AMAP = False


@dataclass
class WeatherInfo:
    """天气信息"""
    location: str = ""
    temperature_c: int = 0          # 当前温度
    feels_like_c: int = 0           # 体感温度
    humidity: int = 0               # 湿度 %
    wind_kmph: int = 0              # 风速 km/h
    precipitation_mm: float = 0.0   # 降水量 mm
    condition: str = ""             # 天气状况描述
    condition_code: str = ""        # 天气代码
    is_rainy: bool = False          # 是否下雨
    is_snowy: bool = False          # 是否下雪
    is_outdoor_friendly: bool = True  # 是否适合户外
    comfort_level: str = "comfortable"  # comfortable / warm / cold / hot
    source: str = ""                # 数据来源：amap / wttr.in


def _get_from_amap(location: str) -> Optional[WeatherInfo]:
    """通过高德天气 API 获取天气"""
    if not HAS_AMAP:
        return None

    try:
        # 优先用用户配置的城市
        user_loc = load_user_location()
        city = user_loc.get("city", location)

        data = get_weather_info(city)
        if not data:
            return None

        weather = WeatherInfo()
        weather.location = data.get("city", location)
        weather.source = "amap"

        # 温度
        temp = data.get("temperature_float", 0)
        weather.temperature_c = int(temp)
        weather.feels_like_c = int(temp)  # 高德没有体感温度，用实际温度代替

        # 湿度
        try:
            weather.humidity = int(data.get("humidity", "0"))
        except (ValueError, TypeError):
            weather.humidity = 0

        # 风速（高德返回的是风力等级，如 "≤3"，转换为大致 km/h）
        wind_power = data.get("windpower", "≤3")
        weather.wind_kmph = _wind_power_to_kmph(wind_power)

        # 降水量（高德实况不直接提供降水量，从天气描述推断）
        weather.condition = data.get("weather", "")
        weather.condition_code = weather.condition
        weather.precipitation_mm = _estimate_precipitation(weather.condition)

        # 判断是否下雨/下雪
        rain_keywords = ["雨", "雷阵雨", "暴雨", "大雨", "中雨", "小雨", "阵雨", "毛毛雨"]
        snow_keywords = ["雪", "小雪", "中雪", "大雪", "暴雪", "雨夹雪"]
        weather.is_rainy = any(kw in weather.condition for kw in rain_keywords)
        weather.is_snowy = any(kw in weather.condition for kw in snow_keywords)

        # 判断是否适合户外
        weather.is_outdoor_friendly = (
            not weather.is_rainy
            and not weather.is_snowy
            and weather.wind_kmph < 40
            and -5 < weather.temperature_c < 38
        )

        # 舒适度
        if weather.temperature_c < 5:
            weather.comfort_level = "cold"
        elif weather.temperature_c < 15:
            weather.comfort_level = "cool"
        elif weather.temperature_c < 28:
            weather.comfort_level = "comfortable"
        elif weather.temperature_c < 35:
            weather.comfort_level = "warm"
        else:
            weather.comfort_level = "hot"

        return weather

    except Exception as e:
        print(f"[weather:amap] Error: {e}")
        return None


def _get_from_wttr(location: str) -> Optional[WeatherInfo]:
    """通过 wttr.in 获取天气（fallback）"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"wttr.in/{location}?format=j1"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        current = data.get("current_condition", [{}])[0]
        if not current:
            return None

        weather = WeatherInfo()
        weather.location = location
        weather.source = "wttr.in"

        weather.temperature_c = int(current.get("temp_C", 0))
        weather.feels_like_c = int(current.get("FeelsLikeC", 0))
        weather.humidity = int(current.get("humidity", 0))
        weather.wind_kmph = int(current.get("windspeedKmph", 0))
        weather.precipitation_mm = float(current.get("precipMM", 0))

        weather.condition = current.get("lang_zh", [{}])[0].get("value", "") if current.get("lang_zh") else current.get("weatherDesc", [{}])[0].get("value", "")
        weather.condition_code = current.get("weatherCode", "")

        weather.is_rainy = weather.precipitation_mm > 0.5 or any(
            kw in weather.condition for kw in ["雨", "rain", "Rain", "shower", "drizzle"]
        )
        weather.is_snowy = any(
            kw in weather.condition for kw in ["雪", "snow", "Snow"]
        )

        weather.is_outdoor_friendly = (
            not weather.is_rainy
            and not weather.is_snowy
            and weather.wind_kmph < 40
            and -5 < weather.temperature_c < 38
        )

        if weather.temperature_c < 5:
            weather.comfort_level = "cold"
        elif weather.temperature_c < 15:
            weather.comfort_level = "cool"
        elif weather.temperature_c < 28:
            weather.comfort_level = "comfortable"
        elif weather.temperature_c < 35:
            weather.comfort_level = "warm"
        else:
            weather.comfort_level = "hot"

        return weather

    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, IndexError, FileNotFoundError):
        return None


def get_weather(location: str = "济南") -> Optional[WeatherInfo]:
    """获取指定位置的当前天气

    优先使用高德天气 API，失败时降级到 wttr.in。

    Args:
        location: 城市名（中文或英文均可）

    Returns:
        WeatherInfo 对象，失败返回 None
    """
    # 1. 尝试高德天气
    weather = _get_from_amap(location)
    if weather:
        return weather

    # 2. fallback 到 wttr.in
    weather = _get_from_wttr(location)
    if weather:
        return weather

    return None


def _wind_power_to_kmph(wind_power: str) -> int:
    """高德风力等级转大致 km/h"""
    # 去掉非数字字符
    power = re.sub(r"[^\d]", "", wind_power)
    if not power:
        return 5  # 默认微风
    p = int(power)
    # 蒲福风级近似转换
    scale = {0: 1, 1: 3, 2: 7, 3: 13, 4: 20, 5: 29, 6: 39, 7: 50, 8: 62}
    return scale.get(p, min(p * 8, 60))


def _estimate_precipitation(condition: str) -> float:
    """从天气描述估算降水量"""
    if "暴雨" in condition or "大雨" in condition:
        return 25.0
    elif "中雨" in condition:
        return 8.0
    elif "小雨" in condition or "阵雨" in condition or "毛毛雨" in condition:
        return 2.0
    elif "雷阵雨" in condition:
        return 15.0
    elif "雨" in condition:
        return 1.0
    elif "雪" in condition:
        return 3.0
    return 0.0


def get_weather_summary(weather: WeatherInfo) -> str:
    """生成天气摘要（用于推荐中展示）"""
    if not weather:
        return ""

    parts = []
    parts.append(f"{weather.condition}")
    parts.append(f"{weather.temperature_c}°C")

    if abs(weather.temperature_c - weather.feels_like_c) > 3:
        parts.append(f"体感 {weather.feels_like_c}°C")

    if weather.is_rainy:
        parts.append(f"🌧 有雨（{weather.precipitation_mm}mm）")
    if weather.is_snowy:
        parts.append("❄️ 有雪")
    if weather.wind_kmph > 25:
        parts.append(f"💨 大风 {weather.wind_kmph}km/h")

    return " | ".join(parts)


def get_weather_advice(weather: WeatherInfo) -> str:
    """根据天气给出建议"""
    if not weather:
        return ""

    advice = []

    if weather.is_rainy:
        advice.append("今天有雨，建议室内活动，出门记得带伞")
    if weather.is_snowy:
        advice.append("今天有雪，路面可能湿滑，注意安全")
    if weather.wind_kmph > 30:
        advice.append("风很大，户外活动可能不太舒服")
    if weather.temperature_c > 35:
        advice.append("高温天气，注意防暑，尽量避免长时间户外活动")
    if weather.temperature_c < 0:
        advice.append("气温很低，注意保暖，户外活动需谨慎")

    if weather.comfort_level == "comfortable" and weather.is_outdoor_friendly:
        advice.append("天气不错，很适合户外活动")

    return "；".join(advice) if advice else ""


def should_prefer_indoor(weather: WeatherInfo) -> bool:
    """判断是否应该优先推荐室内活动"""
    if not weather:
        return False
    return not weather.is_outdoor_friendly


def get_weather_score_boost(weather: WeatherInfo, event: Dict) -> float:
    """根据天气给活动评分加权

    Args:
        weather: 天气信息
        event: 活动数据

    Returns:
        评分加权值（正数=加分，负数=减分）
    """
    if not weather:
        return 0.0

    boost = 0.0
    is_outdoor = not event.get("weather_independent", True)

    if weather.is_rainy or weather.is_snowy:
        if is_outdoor:
            boost -= 5
        else:
            boost += 2
    elif weather.is_outdoor_friendly:
        if is_outdoor:
            boost += 2
        else:
            boost += 0

    if weather.temperature_c > 35:
        if is_outdoor:
            boost -= 3
    elif weather.temperature_c < 0:
        if is_outdoor:
            boost -= 3

    return boost


def format_weather_for_recommendation(weather: WeatherInfo) -> str:
    """格式化天气信息用于推荐展示"""
    if not weather:
        return ""

    summary = get_weather_summary(weather)
    advice = get_weather_advice(weather)

    lines = [f"🌤 **当前天气：** {summary}"]
    if advice:
        lines.append(f"💡 {advice}")
    return "\n".join(lines)


# ── CLI 测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    location = sys.argv[1] if len(sys.argv) > 1 else "济南"

    print(f"正在获取 {location} 的天气...")
    weather = get_weather(location)

    if weather:
        print(f"数据来源: {weather.source}")
        print(get_weather_summary(weather))
        print(get_weather_advice(weather))
        print(f"适合户外: {weather.is_outdoor_friendly}")
        print(f"舒适度: {weather.comfort_level}")
    else:
        print("获取天气失败")
