"""
유틸리티 함수
- 리포트 생성, 마크다운 아카이브, 날짜 포맷 등
"""
import os
import json
from datetime import datetime
from typing import Optional

from models.content import AnalysisResult, StrategyReport, VideoContent


def save_report(
    analyses: list[AnalysisResult],
    strategy: StrategyReport,
    comparison: str = "",
    benchmark: list[dict] = None,
    output_dir: str = "outputs/reports",
) -> str:
    """회차별 분석 리포트를 마크다운으로 저장하고 경로를 반환한다."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(output_dir, f"report_{ts}.md")

    lines = [
        f"# 생각구독 콘텐츠 분석 리포트",
        f"생성일: {ts}",
        "",
    ]

    # 개별 분석 요약
    for i, a in enumerate(analyses, 1):
        lines += [
            f"---",
            f"## 영상 {i}: {a.video.title or a.video.url}",
            f"- URL: {a.video.url}",
            f"- 구독전환률: {a.video.conversion_rate}%",
            f"",
            f"### 점수",
            f"| 후킹 | 스토리 | 핵심가치 | CTA | 감정 | 주제적합 | 차별화 | 종합 |",
            f"|------|--------|---------|-----|------|---------|-------|------|",
            f"| {a.hook_score} | {a.story_score} | {a.value_score} | {a.cta_score} | "
            f"{a.emotion_score} | {a.topic_score} | {a.diff_score} | {a.overall_score} |",
            "",
            f"### 강점",
            *[f"- {s}" for s in a.strengths],
            "",
            f"### 약점",
            *[f"- {w}" for w in a.weaknesses],
            "",
            f"### 상세 분석",
            a.full_analysis,
            "",
        ]

    # 비교 분석
    if comparison:
        lines += ["---", "## 비교 분석", comparison, ""]

    # 벤치마크
    if benchmark:
        lines += [
            "---",
            "## 📦 축적 데이터 기반 벤치마크",
            "| 영상 | 전환률 | 역대 평균 | 백분위 | 갭 분석 |",
            "|------|-------|---------|-------|--------|",
        ]
        for b in benchmark:
            lines.append(
                f"| {b.get('video_title', '')[:30]} | {b.get('your_conversion', 0)}% | "
                f"{b.get('historical_avg', 0)}% | {b.get('percentile', 0)}% | "
                f"{b.get('gap_analysis', '')} |"
            )
        lines.append("")

    # 전략 리포트
    lines += [
        "---",
        "## 💡 전략 리포트",
        strategy.comparative_summary or "(전략 없음)",
        "",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


def export_markdown_archive(
    analyses_by_video: list[tuple[VideoContent, AnalysisResult]],
    output_dir: str = "data",
) -> str:
    """마크다운 아카이브 생성
    - data/archive_index.md  : 전체 인덱스
    - data/videos/{id}_analysis.md : 영상별 상세
    """
    videos_dir = os.path.join(output_dir, "videos")
    os.makedirs(videos_dir, exist_ok=True)

    index_lines = [
        "# 생각구독 영상 분석 아카이브",
        f"생성일: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "| # | 제목 | 전환률 | hook | story | value | cta | emotion | topic | diff | overall | 등록일 |",
        "|---|------|-------|------|-------|-------|-----|---------|-------|------|---------|--------|",
    ]

    for i, (video, analysis) in enumerate(analyses_by_video, 1):
        vid_path = os.path.join(videos_dir, f"{video.video_id}_analysis.md")
        relative_path = f"videos/{video.video_id}_analysis.md"

        # 개별 영상 md
        vid_lines = [
            f"# {video.title or video.url}",
            f"- URL: {video.url}",
            f"- 구독전환률: {video.conversion_rate}%",
            f"- 등록일: {str(video.created_at)[:10] if video.created_at else ''}",
            "",
            "## 점수",
            "| 후킹 | 스토리 | 핵심가치 | CTA | 감정 | 주제적합 | 차별화 | 종합 |",
            "|------|--------|---------|-----|------|---------|-------|------|",
            f"| {analysis.hook_score} | {analysis.story_score} | {analysis.value_score} | "
            f"{analysis.cta_score} | {analysis.emotion_score} | {analysis.topic_score} | "
            f"{analysis.diff_score} | {analysis.overall_score} |",
            "",
            "## 상세 분석",
            analysis.full_analysis or "(분석 없음)",
        ]
        with open(vid_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vid_lines))

        # 인덱스 row
        created = str(video.created_at)[:7] if video.created_at else ""
        title_link = f"[{(video.title or video.url)[:30]}]({relative_path})"
        index_lines.append(
            f"| {i} | {title_link} | {video.conversion_rate}% | "
            f"{analysis.hook_score} | {analysis.story_score} | {analysis.value_score} | "
            f"{analysis.cta_score} | {analysis.emotion_score} | {analysis.topic_score} | "
            f"{analysis.diff_score} | {analysis.overall_score} | {created} |"
        )

    index_path = os.path.join(output_dir, "archive_index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines))

    return index_path


def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}분 {s}초"


def truncate(text: str, max_len: int = 40) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text
