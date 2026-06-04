#!/usr/bin/env python3
"""对话式评价系统 - 用自然语言替代传统打星+写评论

从用户随口一句话中提取情感、属性、关键词，
自动更新偏好学习系统，影响下次推荐。
"""

import json
import os
import sys
import argparse
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from memory import (
    record_visit,
    record_rejection,
    get_learned_preferences,
    format_preference_summary,
)

DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
REVIEWS_FILE = os.path.join(DATA_DIR, "reviews.json")

BOOKING_CLI_DIR = os.path.join(PROJECT_ROOT, "skills", "booking", "scripts")
sys.path.insert(0, BOOKING_CLI_DIR)

# ── 情感分析 ──────────────────────────────────────────────

POSITIVE_WORDS = {
    "好吃", "不错", "推荐", "满意", "惊喜", "赞", "喜欢", "棒",
    "新鲜", "地道", "正宗", "好喝", "舒服", "干净", "热情",
    "值得", "再去", "还想去", "下次还来", "性价比高", "很好",
    "精彩", "好看", "有趣", "开心", "享受", "氛围好",
}

NEGATIVE_WORDS = {
    "难吃", "不好", "差", "失望", "踩雷", "不推荐", "太贵",
    "不值", "脏", "慢", "冷", "咸", "辣", "油腻", "排队",
    "服务差", "态度差", "不新鲜", "坑", "难看", "无聊",
    "不行", "一般般", "凑合", "后悔", "不会再去",
}

NEUTRAL_WORDS = {
    "还行", "一般", "凑合", "马马虎虎", "普通", "中规中矩", "过得去",
}

ATTRIBUTE_PATTERNS = {
    "taste": ["好吃", "难吃", "咸", "辣", "淡", "甜", "油腻", "新鲜", "地道", "正宗", "口味"],
    "service": ["服务", "态度", "热情", "冷淡", "慢", "快", "周到"],
    "environment": ["环境", "干净", "脏", "吵", "安静", "氛围", "装修", "舒服"],
    "price": ["贵", "便宜", "性价比", "值", "不值", "划算", "坑"],
    "location": ["远", "近", "方便", "难找", "停车", "交通"],
    "wait": ["排队", "等", "等位", "排号"],
}


def analyze_sentiment(comment: str) -> Tuple[str, float, List[str]]:
    """从自然语言中分析情感

    Returns:
        (sentiment, score, matched_keywords)
        sentiment: positive/negative/neutral
        score: 0.0-5.0 (映射到传统5星)
        matched_keywords: 匹配到的关键词
    """
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    matched = []

    for word in POSITIVE_WORDS:
        if word in comment:
            positive_count += 1
            matched.append(f"+{word}")

    for word in NEGATIVE_WORDS:
        if word in comment:
            negative_count += 1
            matched.append(f"-{word}")

    for word in NEUTRAL_WORDS:
        if word in comment:
            neutral_count += 1
            matched.append(f"~{word}")

    if negative_count > positive_count:
        sentiment = "negative"
        score = max(1.0, 3.0 - negative_count * 0.5)
    elif positive_count > negative_count:
        sentiment = "positive"
        score = min(5.0, 3.5 + positive_count * 0.5)
    elif neutral_count > 0:
        sentiment = "neutral"
        score = 3.0
    else:
        sentiment = "neutral"
        score = 3.5

    return sentiment, round(score, 1), matched


def extract_attributes(comment: str) -> Dict[str, str]:
    """提取评价涉及的属性维度（基于关键词周围上下文判断正负）"""
    attributes = {}

    for attr, keywords in ATTRIBUTE_PATTERNS.items():
        for kw in keywords:
            if kw in comment:
                idx = comment.index(kw)
                ctx_start = max(0, idx - 6)
                ctx_end = min(len(comment), idx + len(kw) + 6)
                context = comment[ctx_start:ctx_end]

                local_pos = any(pw in context for pw in POSITIVE_WORDS)
                local_neg = any(nw in context for nw in NEGATIVE_WORDS)
                has_neg_prefix = any(neg in context for neg in ["不", "没", "差", "太"])

                if kw in NEGATIVE_WORDS:
                    attributes[attr] = "negative"
                elif kw in POSITIVE_WORDS:
                    if has_neg_prefix:
                        attributes[attr] = "negative"
                    else:
                        attributes[attr] = "positive"
                elif has_neg_prefix or local_neg:
                    attributes[attr] = "negative"
                elif local_pos:
                    attributes[attr] = "positive"
                else:
                    attributes[attr] = "mentioned"
                break

    return attributes


def extract_tags(comment: str) -> List[str]:
    """提取可学习的标签"""
    tags = []
    tag_words = [
        "辣", "咸", "甜", "酸", "油腻", "清淡", "新鲜",
        "安静", "热闹", "吵", "干净",
        "便宜", "贵", "性价比",
        "排队", "快", "慢",
        "好吃", "难吃", "地道",
    ]
    for word in tag_words:
        if word in comment:
            tags.append(word)
    return tags


# ── 数据读写 ──────────────────────────────────────────────

def _load_reviews() -> Dict:
    if not os.path.exists(REVIEWS_FILE):
        return {"reviews": []}
    with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_reviews(data: Dict):
    os.makedirs(os.path.dirname(REVIEWS_FILE), exist_ok=True)
    with open(REVIEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 评价操作 ──────────────────────────────────────────────

def add_review(
    venue: str,
    comment: str,
    skill: str = "food-finder",
    booking_id: str = "",
) -> Dict:
    """添加评价"""
    sentiment, score, matched = analyze_sentiment(comment)
    attributes = extract_attributes(comment)
    tags = extract_tags(comment)

    review = {
        "venue": venue,
        "comment": comment,
        "skill": skill,
        "sentiment": sentiment,
        "score": score,
        "matched_keywords": matched,
        "attributes": attributes,
        "tags": tags,
        "booking_id": booking_id,
        "created_at": datetime.now().isoformat(),
    }

    # 保存评价
    data = _load_reviews()
    data["reviews"].append(review)
    if len(data["reviews"]) > 200:
        data["reviews"] = data["reviews"][-200:]
    _save_reviews(data)

    # 更新偏好系统
    if sentiment == "positive":
        record_visit(skill, venue, rating=score)
    elif sentiment == "negative":
        rejected_items = [{"cuisine": "", "tags": tags, "type": ""}]
        record_rejection(skill, rejected_items, rejected_tags=tags, reason=comment)

    # 标记预订已评价
    if booking_id:
        try:
            from booking_cli import mark_reviewed
            mark_reviewed(booking_id)
        except (ImportError, Exception):
            pass

    return review


def list_reviews(
    venue: str = "",
    sentiment: str = "",
    skill: str = "",
    limit: int = 10,
) -> List[Dict]:
    """查看评价列表"""
    data = _load_reviews()
    reviews = data.get("reviews", [])

    if venue:
        reviews = [r for r in reviews if venue in r.get("venue", "")]
    if sentiment:
        reviews = [r for r in reviews if r.get("sentiment") == sentiment]
    if skill:
        reviews = [r for r in reviews if r.get("skill") == skill]

    return reviews[-limit:]


def get_pending_reviews() -> List[Dict]:
    """获取待评价的已完成预订"""
    try:
        from booking_cli import get_completed_without_review
        return get_completed_without_review()
    except (ImportError, Exception):
        return []


def get_preference_impact() -> str:
    """生成评价对偏好的影响摘要"""
    data = _load_reviews()
    reviews = data.get("reviews", [])

    if not reviews:
        return "暂无评价记录，去体验后告诉我感觉怎么样！"

    total = len(reviews)
    positive = sum(1 for r in reviews if r.get("sentiment") == "positive")
    negative = sum(1 for r in reviews if r.get("sentiment") == "negative")
    neutral = total - positive - negative

    lines = [f"📊 评价统计（共 {total} 条）：\n"]
    lines.append(f"  👍 好评 {positive} 条")
    lines.append(f"  👎 差评 {negative} 条")
    lines.append(f"  😐 中评 {neutral} 条")

    # 高频正面标签
    pos_tags = {}
    neg_tags = {}
    for r in reviews:
        tag_list = r.get("tags", [])
        if r.get("sentiment") == "positive":
            for t in tag_list:
                pos_tags[t] = pos_tags.get(t, 0) + 1
        elif r.get("sentiment") == "negative":
            for t in tag_list:
                neg_tags[t] = neg_tags.get(t, 0) + 1

    if pos_tags:
        top_pos = sorted(pos_tags.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append(f"\n  ✅ 喜欢的特点：{'、'.join(t[0] for t in top_pos)}")

    if neg_tags:
        top_neg = sorted(neg_tags.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append(f"  ❌ 不喜欢的：{'、'.join(t[0] for t in top_neg)}")

    # 偏好摘要
    pref_summary = format_preference_summary()
    if pref_summary:
        lines.append(f"\n  💡 {pref_summary}")

    return "\n".join(lines)


# ── 格式化输出 ──────────────────────────────────────────────

def format_review_response(review: Dict) -> str:
    """生成评价确认回复"""
    sentiment = review.get("sentiment", "neutral")
    venue = review.get("venue", "")
    tags = review.get("tags", [])

    if sentiment == "positive":
        response = f"记住了！{venue} 体验不错 👍"
        if tags:
            response += f"\n下次推荐会参考你喜欢「{'、'.join(tags[:3])}」的偏好"
    elif sentiment == "negative":
        response = f"收到，{venue} 体验不太好"
        if tags:
            response += f"\n下次会避开「{'、'.join(tags[:3])}」相关的推荐"
    else:
        response = f"了解，已记录 {venue} 的体验"

    return response


def format_review_list(reviews: List[Dict]) -> str:
    """格式化评价列表"""
    if not reviews:
        return "暂无评价记录"

    sentiment_emoji = {"positive": "👍", "negative": "👎", "neutral": "😐"}
    lines = ["💬 评价记录：\n"]

    for r in reviews:
        emoji = sentiment_emoji.get(r.get("sentiment", ""), "📝")
        date = r.get("created_at", "")[:10]
        lines.append(f"  {emoji} {r['venue']}（{date}）")
        lines.append(f"     「{r['comment']}」")
        if r.get("tags"):
            lines.append(f"     标签：{'、'.join(r['tags'])}")
        lines.append("")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="评价管理")
    subparsers = parser.add_subparsers(dest="command", help="操作类型")

    # add
    p_add = subparsers.add_parser("add", help="添加评价")
    p_add.add_argument("--venue", required=True, help="餐厅/活动名称")
    p_add.add_argument("--comment", required=True, help="用户原话")
    p_add.add_argument("--skill", default="food-finder", help="关联技能")
    p_add.add_argument("--booking_id", default="", help="关联预订ID")

    # list
    p_list = subparsers.add_parser("list", help="查看评价列表")
    p_list.add_argument("--venue", default="", help="按场所筛选")
    p_list.add_argument("--sentiment", default="", help="按情感筛选")
    p_list.add_argument("--skill", default="", help="按技能筛选")
    p_list.add_argument("--limit", type=int, default=10, help="数量限制")

    # pending
    subparsers.add_parser("pending", help="查看待评价列表")

    # impact
    subparsers.add_parser("impact", help="偏好影响摘要")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "add":
        review = add_review(
            venue=args.venue,
            comment=args.comment,
            skill=args.skill,
            booking_id=args.booking_id,
        )
        print(format_review_response(review))

    elif args.command == "list":
        reviews = list_reviews(
            venue=args.venue,
            sentiment=args.sentiment,
            skill=args.skill,
            limit=args.limit,
        )
        print(format_review_list(reviews))

    elif args.command == "pending":
        pending = get_pending_reviews()
        if pending:
            print("📝 以下体验还没评价：\n")
            for b in pending:
                print(f"  - {b['venue']}（{b['date']}）")
            print(f"\n告诉我感觉怎么样就行！")
        else:
            print("没有待评价的体验")

    elif args.command == "impact":
        print(get_preference_impact())


if __name__ == "__main__":
    main()
