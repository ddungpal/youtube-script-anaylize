"""
전략 수립 에이전트
- 개별 분석 결과 + 비교 분석 + 축적 데이터 컨텍스트를 종합하여 전략 리포트를 생성한다.
"""
import logging
import os

from openai import OpenAI

from models.content import AnalysisResult, StrategyReport, VideoContent
from database.db_manager import DBManager

logger = logging.getLogger(__name__)


def _load_strategy_prompt() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "strategy_prompt.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return _default_strategy_prompt()


def _default_strategy_prompt() -> str:
    return """당신은 "생각구독" 채널의 전략 컨설턴트입니다.
분석 데이터를 바탕으로 다음 영상 제작을 위한 구체적이고 실행 가능한 전략을 수립해주세요.

아래 요소를 반드시 포함하세요:
1. 비교 분석 요약 — 영상들의 공통점/차이점, 전환률 차이 원인
2. 성공 패턴 — 이번 영상에서 확인된 효과적인 요소
3. 개선 포인트 — 즉시 적용 가능한 개선 사항 (우선순위 포함)
4. 다음 영상 전략 — 주제 추천, 구조 가이드, CTA 전략
5. 역대 벤치마크 비교 — 이번 영상들의 점수를 역대 평균과 비교한 갭 분석
6. 패턴 라이브러리 활용 — 아직 시도하지 않은 유망 패턴, 반드시 피해야 할 실패 패턴
7. 트렌드 기반 방향성 — 전환률 추이를 기반으로 한 단기 전략"""


class StrategyAgent:
    def __init__(self, db: DBManager):
        self.db = db
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0"))
        self.system_prompt = _load_strategy_prompt()

    def generate_strategy(
        self,
        analyses: list[AnalysisResult],
        comparison: str = "",
        historical_context: dict = None,
        benchmark: list[dict] = None,
    ) -> StrategyReport:
        """전략 리포트 생성"""
        user_content = self._build_strategy_prompt(analyses, comparison, historical_context, benchmark)
        logger.debug(f"Claude 전략 수립 API 호출")

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        report_text = response.choices[0].message.content
        return StrategyReport(
            comparative_summary=report_text,
            historical_benchmark=historical_context or {},
        )

    def _build_strategy_prompt(
        self,
        analyses: list[AnalysisResult],
        comparison: str,
        historical_context: dict = None,
        benchmark: list[dict] = None,
    ) -> str:
        lines = ["# 전략 수립 요청", ""]

        lines.append("## 분석 영상 요약")
        for i, a in enumerate(analyses, 1):
            lines.append(
                f"### 영상 {i}: {a.video.title or a.video.url}\n"
                f"- 전환률: {a.video.conversion_rate}%\n"
                f"- 점수: hook={a.hook_score}, story={a.story_score}, value={a.value_score}, "
                f"cta={a.cta_score}, emotion={a.emotion_score}, topic={a.topic_score}, "
                f"diff={a.diff_score}, overall={a.overall_score}\n"
                f"- 강점: {', '.join(a.strengths[:3])}\n"
                f"- 약점: {', '.join(a.weaknesses[:3])}"
            )
        lines.append("")

        if comparison:
            lines.append("## 비교 분석 결과")
            lines.append(comparison)
            lines.append("")

        if historical_context:
            lines.append("## 축적 데이터 컨텍스트")
            lines.append(f"- 총 영상 수: {historical_context.get('total_videos', 0)}개")
            lines.append(f"- 역대 평균 전환률: {historical_context.get('avg_conversion_rate', 0)}%")
            lines.append(f"- 최근 추세: {historical_context.get('recent_trend', '정보 없음')}")

            if historical_context.get("success_patterns_top5"):
                lines.append("- 역대 성공 패턴 TOP5:")
                for p in historical_context["success_patterns_top5"][:5]:
                    lines.append(f"  * [{p.get('category')}] {p.get('description')} (빈도: {p.get('frequency')}, 평균전환률: {p.get('avg_conversion', 0):.1f}%)")

            if historical_context.get("failure_patterns_top5"):
                lines.append("- 역대 실패 패턴 TOP5:")
                for p in historical_context["failure_patterns_top5"][:5]:
                    lines.append(f"  * [{p.get('category')}] {p.get('description')}")
            lines.append("")

        if benchmark:
            lines.append("## 역대 벤치마크")
            for b in benchmark:
                lines.append(
                    f"- {b.get('video_title', '')}: 전환률 {b.get('your_conversion', 0)}% "
                    f"(역대 평균 {b.get('historical_avg', 0)}%, 백분위 {b.get('percentile', 0)}%)"
                )
            lines.append("")

        lines.append("위 데이터를 바탕으로 다음 영상 제작을 위한 구체적인 전략을 수립해주세요.")
        return "\n".join(lines)
