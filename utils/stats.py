"""
통계 계산 유틸리티
- 전환률 통계, 이동 평균, 트렌드 차트, 레이더 차트, 분포 히스토그램
"""
import os
import statistics
from typing import Optional


def calculate_basic_stats(conversion_rates: list[float]) -> dict:
    """기본 통계 (평균, 중앙값, 표준편차, 최소, 최대)"""
    if not conversion_rates:
        return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0, "count": 0}
    return {
        "mean": round(statistics.mean(conversion_rates), 2),
        "median": round(statistics.median(conversion_rates), 2),
        "std": round(statistics.stdev(conversion_rates) if len(conversion_rates) > 1 else 0, 2),
        "min": round(min(conversion_rates), 2),
        "max": round(max(conversion_rates), 2),
        "count": len(conversion_rates),
    }


def calculate_moving_average(data: list[float], window: int = 3) -> list[float]:
    """이동 평균 계산 (데이터가 window보다 짧으면 누적 평균)"""
    result = []
    for i in range(len(data)):
        start = max(0, i - window + 1)
        result.append(round(statistics.mean(data[start: i + 1]), 3))
    return result


def classify_conversion_tier(rate: float, avg: float, std: float) -> str:
    """전환률 구간 분류"""
    if rate >= avg + std:
        return "상"
    if rate <= avg - std:
        return "하"
    return "중"


def calculate_percentile(rate: float, all_rates: list[float]) -> float:
    """전환률 백분위 계산"""
    if not all_rates:
        return 50.0
    below = sum(1 for r in all_rates if r < rate)
    return round(below / len(all_rates) * 100, 1)


def generate_trend_chart(
    labels: list[str],
    rates: list[float],
    ma3: list[float],
    output_path: str = "outputs/charts/trend.png",
) -> str:
    """전환률 추이 그래프 생성 (이동평균 포함)"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm

        # 한글 폰트 설정 (macOS)
        _set_korean_font()

        fig, ax = plt.subplots(figsize=(12, 5))
        x = range(len(rates))

        ax.plot(x, rates, "o-", label="전환률", color="#3498db", linewidth=2)
        ax.plot(x, ma3, "--", label="3개 이동평균", color="#e74c3c", linewidth=1.5, alpha=0.8)

        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("전환률 (%)")
        ax.set_title("생각구독 채널 구독전환률 추이")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        return output_path
    except Exception as e:
        return f"차트 생성 실패: {e}"


def generate_score_radar_chart(
    scores: dict,
    avg_scores: dict,
    video_label: str = "이번 영상",
    output_path: str = "outputs/charts/radar.png",
) -> str:
    """개별 영상 점수 vs 역대 평균 레이더 차트"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        _set_korean_font()

        categories = ["후킹", "스토리", "핵심가치", "CTA", "감정", "주제적합", "차별화"]
        score_keys = ["hook", "story", "value", "cta", "emotion", "topic", "diff"]

        values = [scores.get(k, 0) for k in score_keys]
        avg_values = [avg_scores.get(k, 0) for k in score_keys]

        angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
        angles += angles[:1]
        values += values[:1]
        avg_values += avg_values[:1]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"polar": True})
        ax.plot(angles, values, "o-", label=video_label, color="#3498db")
        ax.fill(angles, values, alpha=0.25, color="#3498db")
        ax.plot(angles, avg_values, "s--", label="역대 평균", color="#e74c3c")
        ax.fill(angles, avg_values, alpha=0.1, color="#e74c3c")
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories)
        ax.set_ylim(0, 10)
        ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
        ax.set_title("7개 차원 점수 비교", pad=20)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path
    except Exception as e:
        return f"레이더 차트 생성 실패: {e}"


def generate_score_distribution(
    all_scores: list[dict],
    output_path: str = "outputs/charts/distribution.png",
) -> str:
    """점수 분포 히스토그램"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _set_korean_font()

        score_keys = ["hook", "story", "value", "cta", "emotion", "topic", "diff", "overall"]
        labels = ["후킹", "스토리", "핵심가치", "CTA", "감정", "주제적합", "차별화", "종합"]

        fig, axes = plt.subplots(2, 4, figsize=(14, 7))
        axes = axes.flatten()

        for i, (key, label) in enumerate(zip(score_keys, labels)):
            vals = [s.get(key, 0) for s in all_scores if s.get(key, 0) > 0]
            if vals:
                axes[i].hist(vals, bins=range(1, 12), color="#3498db", alpha=0.7, edgecolor="white")
            axes[i].set_title(label)
            axes[i].set_xlim(1, 10)
            axes[i].set_xlabel("점수")
            axes[i].set_ylabel("영상 수")

        fig.suptitle("점수 분포 현황", fontsize=14)
        fig.tight_layout()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        return output_path
    except Exception as e:
        return f"분포 차트 생성 실패: {e}"


def _set_korean_font():
    """macOS 한글 폰트 설정"""
    try:
        import matplotlib.pyplot as plt
        import platform
        if platform.system() == "Darwin":
            plt.rcParams["font.family"] = "AppleGothic"
        elif platform.system() == "Windows":
            plt.rcParams["font.family"] = "Malgun Gothic"
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
