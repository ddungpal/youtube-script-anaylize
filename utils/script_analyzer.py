"""
스크립트 정량 분석 모듈
- AI 호출 없이 Python만으로 스크립트의 수치 지표를 자동 계산한다.
- 구독 전환과 관련된 언어적 신호(단어 사용 패턴)를 카테고리별로 집계한다.
"""
import re
from collections import Counter


# ── 전환 관련 키워드 카테고리 정의 ─────────────────────────────────────────
# 채널 종류에 관계없이 구독 전환에 영향을 주는 언어 패턴을 분류한다.
KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "구독_유도": [
        "구독", "신청", "가입", "멤버", "등록", "클릭", "링크", "참여",
        "구독하세요", "신청하세요", "가입하세요", "지금 바로",
    ],
    "긴박감_희소성": [
        "지금", "오늘", "한정", "마감", "기회", "놓치", "마지막", "잠깐",
        "빨리", "서둘러", "한정판", "특별", "이번만",
    ],
    "독자_직접_호칭": [
        "여러분", "당신", "구독자", "독자", "여러분들", "시청자",
        "보시는 분", "듣고 계신", "이 영상을 보는",
    ],
    "감정_공감_자극": [
        "놀랍", "충격", "중요", "핵심", "비밀", "몰랐", "알려드",
        "사실", "진짜", "실제로", "직접", "솔직히", "경험",
    ],
    "사회적_증거": [
        "명이", "분이", "사람이", "구독자가", "리뷰", "후기",
        "반응", "입증", "증명", "검증", "인정",
    ],
    "혜택_가치_제시": [
        "무료", "혜택", "할인", "절약", "이득", "장점", "효과",
        "변화", "성장", "개선", "향상", "달라", "달라질",
    ],
}


def compute_script_metrics(transcript: str, duration_seconds: int = 0) -> dict:
    """
    스크립트 텍스트에서 전환 관련 정량 지표를 자동 계산한다.

    반환 구조:
    {
        "total_words": int,
        "words_per_minute": float,
        "question_count": int,
        "number_mention_count": int,
        "exclamation_count": int,
        "category_counts": { "구독_유도": 3, "긴박감_희소성": 7, ... },
        "top_keywords": [ {"word": "지금", "count": 8}, ... ],
        "subscription_density": float,   # 전체 단어 중 구독 유도 단어 비율 (%)
    }
    """
    if not transcript:
        return _empty_metrics()

    text = transcript.lower()
    words = re.findall(r"[\w가-힣]+", text)
    total_words = len(words)

    # 분당 단어수
    wpm = 0.0
    if duration_seconds and total_words:
        wpm = round(total_words / (duration_seconds / 60), 1)

    # 질문 수
    question_count = text.count("?") + len(re.findall(r"(?:어떻게|왜|무엇|어떤|언제|누가|얼마나)\b", text))

    # 숫자/통계 언급
    number_count = len(re.findall(r"\d+", text))

    # 느낌표
    exclamation_count = text.count("!")

    # 카테고리별 키워드 집계
    category_counts: dict[str, int] = {}
    matched_words: list[str] = []
    for cat, keywords in KEYWORD_CATEGORIES.items():
        count = 0
        for kw in keywords:
            occurrences = text.count(kw)
            count += occurrences
            if occurrences > 0:
                matched_words.extend([kw] * occurrences)
        category_counts[cat] = count

    # 자주 등장한 키워드 TOP 15
    kw_counter = Counter(matched_words)
    top_keywords = [
        {"word": w, "count": c}
        for w, c in kw_counter.most_common(15)
    ]

    # 구독 유도 밀도 (%)
    sub_count = category_counts.get("구독_유도", 0)
    subscription_density = round(sub_count / total_words * 100, 3) if total_words else 0.0

    return {
        "total_words": total_words,
        "words_per_minute": wpm,
        "question_count": question_count,
        "number_mention_count": number_count,
        "exclamation_count": exclamation_count,
        "category_counts": category_counts,
        "top_keywords": top_keywords,
        "subscription_density": subscription_density,
    }


def _empty_metrics() -> dict:
    return {
        "total_words": 0,
        "words_per_minute": 0.0,
        "question_count": 0,
        "number_mention_count": 0,
        "exclamation_count": 0,
        "category_counts": {cat: 0 for cat in KEYWORD_CATEGORIES},
        "top_keywords": [],
        "subscription_density": 0.0,
    }


def compute_keyword_correlation(
    videos_metrics: list[dict],
) -> dict:
    """
    여러 영상의 script_metrics와 conversion_rate를 받아
    각 지표와 전환율 간의 상관관계를 계산한다.

    videos_metrics 예시:
    [{"conversion_rate": 3.5, "script_metrics": {...}}, ...]

    반환:
    {
        "metric_by_tier": {
            "high": { "total_words": ..., "question_count": ... },
            "low":  { "total_words": ..., "question_count": ... },
        },
        "keyword_by_tier": {
            "high": [{"word": "지금", "avg_count": 6.3}, ...],
            "low":  [{"word": "지금", "avg_count": 1.8}, ...],
        },
        "high_vs_low_ratio": [
            {"word": "지금", "high_avg": 6.3, "low_avg": 1.8, "ratio": 3.5},
        ],
    }
    """
    if not videos_metrics:
        return {}

    rates = [v["conversion_rate"] for v in videos_metrics]
    if len(rates) < 2:
        return {}

    # 상위 33% / 하위 33% 구분
    sorted_rates = sorted(rates)
    n = len(sorted_rates)
    high_threshold = sorted_rates[int(n * 0.67)]
    low_threshold = sorted_rates[int(n * 0.33)]

    high_group = [v for v in videos_metrics if v["conversion_rate"] >= high_threshold]
    low_group = [v for v in videos_metrics if v["conversion_rate"] <= low_threshold]

    if not high_group or not low_group:
        return {}

    def avg_metrics(group: list[dict]) -> dict:
        keys = ["total_words", "words_per_minute", "question_count",
                "number_mention_count", "exclamation_count", "subscription_density"]
        result = {}
        for k in keys:
            vals = [v["script_metrics"].get(k, 0) for v in group if v.get("script_metrics")]
            result[k] = round(sum(vals) / len(vals), 2) if vals else 0
        # 카테고리별 평균
        for cat in KEYWORD_CATEGORIES:
            vals = [v["script_metrics"].get("category_counts", {}).get(cat, 0)
                    for v in group if v.get("script_metrics")]
            result[f"cat_{cat}"] = round(sum(vals) / len(vals), 2) if vals else 0
        return result

    def avg_keywords(group: list[dict]) -> dict:
        """단어별 평균 등장 횟수"""
        word_totals: dict[str, float] = Counter()
        for v in group:
            sm = v.get("script_metrics") or {}
            for kw_entry in sm.get("top_keywords", []):
                word_totals[kw_entry["word"]] += kw_entry["count"]
        n_group = len(group)
        return {w: round(c / n_group, 2) for w, c in word_totals.items()}

    high_metrics = avg_metrics(high_group)
    low_metrics = avg_metrics(low_group)
    high_kw = avg_keywords(high_group)
    low_kw = avg_keywords(low_group)

    # 고/저전환율 공통 키워드 비율 계산
    all_words = set(high_kw) | set(low_kw)
    ratio_list = []
    for word in all_words:
        h = high_kw.get(word, 0.0)
        l = low_kw.get(word, 0.0)
        ratio = round(h / l, 2) if l > 0 else (h * 10 if h > 0 else 0)
        if h > 0 or l > 0:
            ratio_list.append({"word": word, "high_avg": h, "low_avg": l, "ratio": ratio})
    ratio_list.sort(key=lambda x: x["ratio"], reverse=True)

    # 영상별 개별 데이터 (전환율 내림차순)
    per_video = []
    for v in sorted(videos_metrics, key=lambda x: x["conversion_rate"], reverse=True):
        sm = v.get("script_metrics") or {}
        per_video.append({
            "video_id": v.get("video_id", ""),
            "title": v.get("title", v.get("video_id", "")),
            "conversion_rate": v["conversion_rate"],
            "total_words": sm.get("total_words", 0),
            "question_count": sm.get("question_count", 0),
            "number_mention_count": sm.get("number_mention_count", 0),
            "exclamation_count": sm.get("exclamation_count", 0),
            "subscription_density": sm.get("subscription_density", 0),
            "category_counts": sm.get("category_counts", {}),
            "top_keywords": sm.get("top_keywords", []),
        })

    return {
        "total_videos": len(videos_metrics),
        "high_group_size": len(high_group),
        "low_group_size": len(low_group),
        "high_threshold": round(high_threshold, 2),
        "low_threshold": round(low_threshold, 2),
        "metric_by_tier": {"high": high_metrics, "low": low_metrics},
        "high_vs_low_ratio": ratio_list[:20],
        "per_video": per_video,
    }
