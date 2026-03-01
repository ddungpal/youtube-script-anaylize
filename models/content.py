from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class VideoContent:
    """유튜브 영상 하나의 정보를 담는 모델"""
    url: str
    title: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    transcript: str = ""
    duration_seconds: int = 0
    conversion_rate: float = 0.0
    video_id: str = ""
    created_at: Optional[datetime] = None


@dataclass
class AnalysisResult:
    """분석 결과를 담는 모델"""
    video: VideoContent
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    key_hooks: list = field(default_factory=list)
    cta_analysis: str = ""
    topic_relevance: str = ""
    emotional_triggers: list = field(default_factory=list)
    # 정량 점수 (1~10) — 7개 차원 + 종합
    hook_score: float = 0.0
    story_score: float = 0.0
    value_score: float = 0.0
    cta_score: float = 0.0
    emotion_score: float = 0.0
    topic_score: float = 0.0
    diff_score: float = 0.0
    overall_score: float = 0.0    # Claude 독립 평가, 단순 평균 아님
    full_analysis: str = ""
    # 스크립트 정량 지표 (Python 자동 계산 + AI 보완)
    script_metrics: dict = field(default_factory=dict)


@dataclass
class StrategyReport:
    """최종 전략 리포트"""
    comparative_summary: str = ""
    top_patterns: list = field(default_factory=list)
    next_content_strategies: list = field(default_factory=list)
    recommended_topics: list = field(default_factory=list)
    recommended_structure: str = ""
    cta_recommendations: list = field(default_factory=list)
    historical_benchmark: dict = field(default_factory=dict)
    pattern_based_insights: list = field(default_factory=list)
    trend_insights: str = ""


@dataclass
class HistoricalInsight:
    """축적 데이터 심화 분석 결과"""
    total_videos_analyzed: int = 0
    avg_conversion_rate: float = 0.0
    conversion_trend: str = ""
    top_performing_topics: list = field(default_factory=list)
    recurring_success_patterns: list = field(default_factory=list)
    recurring_failure_patterns: list = field(default_factory=list)
    optimal_video_profile: dict = field(default_factory=dict)
    improvement_trajectory: str = ""
    actionable_insights: list = field(default_factory=list)
