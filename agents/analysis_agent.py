"""
콘텐츠 분석 에이전트
- Claude API로 7개 차원 점수 + 패턴 추출
- rapidfuzz로 유사 패턴 병합
- reanalyze=True 시 기존 패턴을 제거한 뒤 새 패턴 저장
"""
import json
import logging
import os
import re
import statistics

from openai import OpenAI
from rapidfuzz import fuzz

from models.content import AnalysisResult, VideoContent
from database.db_manager import DBManager
from utils.script_analyzer import compute_script_metrics

logger = logging.getLogger(__name__)

THRESHOLD = int(os.getenv("PATTERN_SIMILARITY_THRESHOLD", "80"))


def _load_system_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "analysis_prompt.txt")
    try:
        with open(prompt_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return _default_system_prompt()


def _default_system_prompt() -> str:
    return """당신은 유튜브 콘텐츠 → 유료 구독 전환을 전문으로 분석하는 마케팅 분석가입니다.
"생각구독"은 매달 발행하는 온라인 도서 구독 서비스입니다.

아래 7가지 관점에서 영상 스크립트를 분석해주세요.
각 관점마다 반드시 1~10점 정량 점수와 점수 근거를 함께 제시하세요.

1. 후킹(Hook) 분석 → hook_score (1-10)
   - 첫 후킹 문구가 스크립트 전체의 몇 % 위치에서 등장하는지 추정 (hook_position_pct)
2. 스토리텔링 구조 → story_score (1-10)
3. 핵심 가치 전달 → value_score (1-10)
4. CTA(Call-to-Action) 분석 → cta_score (1-10)
   - CTA 문구가 몇 % 위치에서 처음 등장하는지 추정 (first_cta_position_pct)
   - 스크립트 내 CTA 등장 횟수 (cta_count)
5. 감정 곡선 분석 → emotion_score (1-10)
6. 주제 & 타겟 적합성 → topic_score (1-10)
7. 차별화 요소 → diff_score (1-10)

마지막에 overall_score (1-10)를 7개 점수 수치와 무관하게 독립적인 종합 판단으로 평가해주세요.
(단순 평균이 아닌 전체 맥락, 시너지, 약점의 임팩트 등을 종합적으로 고려한 심층 평가)

반드시 분석 결과 마지막에 아래 JSON 블록을 출력하세요:
```json
{
  "scores": {
    "hook_score": 0,
    "story_score": 0,
    "value_score": 0,
    "cta_score": 0,
    "emotion_score": 0,
    "topic_score": 0,
    "diff_score": 0,
    "overall_score": 0
  },
  "patterns": [
    {"category": "hook", "description": "패턴 설명"},
    {"category": "cta", "description": "패턴 설명"}
  ],
  "strengths": ["강점1", "강점2"],
  "weaknesses": ["약점1", "약점2"],
  "key_hooks": ["스크립트에서 실제로 사용된 후킹 문구 (직접 인용)"],
  "cta_analysis": "CTA 분석 텍스트",
  "topic_relevance": "주제 적합성 분석",
  "emotional_triggers": ["스크립트에서 실제로 사용된 감정 자극 표현 (직접 인용)"],
  "high_impact_phrases": [
    {"text": "실제 인용 문구", "type": "hook", "effect": "이 문구가 전환에 미친 영향"},
    {"text": "실제 인용 문구", "type": "cta", "effect": "이 문구가 전환에 미친 영향"},
    {"text": "실제 인용 문구", "type": "emotion", "effect": "이 문구가 전환에 미친 영향"}
  ],
  "ai_script_metrics": {
    "hook_position_pct": 5,
    "first_cta_position_pct": 75,
    "cta_count": 2,
    "narrative_structure": "문제제기→공감→해결→CTA"
  }
}
```"""


class AnalysisAgent:
    def __init__(self, db: DBManager):
        self.db = db
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0"))
        self.system_prompt = _load_system_prompt()

    # ----------------------------------------------------------
    # 공개 메서드
    # ----------------------------------------------------------

    def analyze_single_video(
        self, video: VideoContent, historical_context: dict = None
    ) -> AnalysisResult:
        """단일 영상 분석 (축적 데이터 컨텍스트 선택적 포함)"""
        # Python 자동 계산 (AI 호출 전, 비용 없음)
        py_metrics = compute_script_metrics(video.transcript, video.duration_seconds)

        user_content = self._build_analysis_prompt(video, historical_context)
        logger.debug(f"Claude API 호출: model={self.model}, 스크립트 길이={len(video.transcript)}")

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content
        logger.debug(f"Claude 응답 수신: {len(raw)}자")
        result = self._parse_response(video, raw)
        # Python 지표 + AI 지표 병합
        result.script_metrics = {**py_metrics, **result.script_metrics}
        return result

    def compare_videos(
        self,
        videos: list[VideoContent],
        analyses: list[AnalysisResult],
        historical_patterns: dict = None,
    ) -> str:
        """여러 영상 비교 분석"""
        if len(analyses) < 2:
            return ""

        comparison_text = self._build_comparison_prompt(videos, analyses, historical_patterns)
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": "당신은 유튜브 콘텐츠 비교 분석 전문가입니다. '생각구독' 채널의 영상들을 비교하여 공통점과 차이점을 분석합니다."},
                {"role": "user", "content": comparison_text},
            ],
        )
        return response.choices[0].message.content

    def extract_and_save_patterns(
        self,
        analysis: AnalysisResult,
        reanalyze: bool = False,
    ) -> None:
        """패턴 라이브러리에 패턴을 저장한다.
        - reanalyze=True 시: 이 video_id가 기여한 기존 패턴을 먼저 정리한 뒤 신규 저장
        - rapidfuzz로 유사 패턴 병합 (PATTERN_SIMILARITY_THRESHOLD 기준)
        """
        if reanalyze:
            self.db.remove_patterns_for_video(analysis.video.video_id)
            logger.debug(f"재분석: 기존 패턴 정리 완료 [{analysis.video.video_id}]")

        # 전환률 구간으로 success/failure 분류
        stats = self.db.get_stats_summary()
        avg = stats.get("avg_rate", 0)
        std = stats.get("std_dev", 0)
        if analysis.video.conversion_rate >= avg + std:
            pattern_type = "success"
        elif analysis.video.conversion_rate <= avg - std:
            pattern_type = "failure"
        else:
            pattern_type = "neutral"

        # full_analysis에서 패턴 JSON 추출
        raw_patterns = self._extract_patterns_from_analysis(analysis.full_analysis)
        existing_patterns = self.db.get_all_patterns()

        for p in raw_patterns:
            category = p.get("category", "structure")
            description = p.get("description", "").strip()
            if not description:
                continue

            # 유사 패턴 탐색
            match = self._find_similar_pattern(description, existing_patterns)
            self.db.save_or_merge_pattern(
                pattern_type=pattern_type,
                category=category,
                description=description,
                video_id=analysis.video.video_id,
                conversion_rate=analysis.video.conversion_rate,
                pattern_id=match["id"] if match else None,
            )

    # ----------------------------------------------------------
    # 내부 헬퍼
    # ----------------------------------------------------------

    def _build_analysis_prompt(self, video: VideoContent, historical_context: dict = None) -> str:
        lines = [
            f"# 분석 대상 영상",
            f"- 제목: {video.title or '(제목 없음)'}",
            f"- URL: {video.url}",
            f"- 구독전환률: {video.conversion_rate}%",
            f"- 영상 길이: {video.duration_seconds // 60}분 {video.duration_seconds % 60}초",
        ]
        if video.tags:
            lines.append(f"- 태그: {', '.join(video.tags[:10])}")
        lines.append("")
        lines.append("## 스크립트")
        lines.append(video.transcript or "(스크립트를 가져올 수 없습니다)")

        if historical_context:
            lines.append("")
            lines.append("## 축적 데이터 컨텍스트 (참고)")
            lines.append(f"- 분석된 총 영상 수: {historical_context.get('total_videos', 0)}개")
            lines.append(f"- 역대 평균 전환률: {historical_context.get('avg_conversion_rate', 0)}%")
            if historical_context.get("success_patterns_top5"):
                lines.append("- 역대 성공 패턴 TOP5:")
                for pat in historical_context["success_patterns_top5"][:5]:
                    lines.append(f"  * [{pat.get('category')}] {pat.get('description')}")

        return "\n".join(lines)

    def _build_comparison_prompt(
        self,
        videos: list[VideoContent],
        analyses: list[AnalysisResult],
        historical_patterns: dict = None,
    ) -> str:
        lines = ["# 영상 비교 분석 요청", ""]
        for i, (v, a) in enumerate(zip(videos, analyses), 1):
            lines.append(f"## 영상 {i}: {v.title or v.url}")
            lines.append(f"- 전환률: {v.conversion_rate}%")
            scores = (
                f"hook={a.hook_score}, story={a.story_score}, value={a.value_score}, "
                f"cta={a.cta_score}, emotion={a.emotion_score}, topic={a.topic_score}, "
                f"diff={a.diff_score}, overall={a.overall_score}"
            )
            lines.append(f"- 점수: {scores}")
            lines.append(f"- 강점: {', '.join(a.strengths[:3])}")
            lines.append(f"- 약점: {', '.join(a.weaknesses[:3])}")
            lines.append("")

        if historical_patterns:
            lines.append("## 역대 성공 패턴 참고")
            for pat in (historical_patterns.get("success_patterns_top5") or [])[:5]:
                lines.append(f"- [{pat.get('category')}] {pat.get('description')} (빈도: {pat.get('frequency')})")
            lines.append("")

        lines.append(
            "위 영상들을 비교하여:\n"
            "1. 공통점과 차이점\n"
            "2. 전환률 차이의 원인 분석\n"
            "3. 역대 성공 패턴과의 공통점/차이점\n"
            "4. 각 영상에서 배울 수 있는 핵심 인사이트\n"
            "를 분석해주세요."
        )
        return "\n".join(lines)

    def _parse_response(self, video: VideoContent, raw: str) -> AnalysisResult:
        """Claude 응답에서 JSON 블록을 파싱하여 AnalysisResult로 변환한다."""
        result = AnalysisResult(video=video, full_analysis=raw)

        # JSON 블록 추출
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if not json_match:
            logger.warning("JSON 블록을 찾을 수 없습니다. 원문 분석만 저장합니다.")
            return result

        try:
            data = json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패: {e}")
            return result

        scores = data.get("scores", {})
        result.hook_score = float(scores.get("hook_score", 0))
        result.story_score = float(scores.get("story_score", 0))
        result.value_score = float(scores.get("value_score", 0))
        result.cta_score = float(scores.get("cta_score", 0))
        result.emotion_score = float(scores.get("emotion_score", 0))
        result.topic_score = float(scores.get("topic_score", 0))
        result.diff_score = float(scores.get("diff_score", 0))
        result.overall_score = float(scores.get("overall_score", 0))

        result.strengths = data.get("strengths", [])
        result.weaknesses = data.get("weaknesses", [])
        result.key_hooks = data.get("key_hooks", [])
        result.cta_analysis = data.get("cta_analysis", "")
        result.topic_relevance = data.get("topic_relevance", "")
        result.emotional_triggers = data.get("emotional_triggers", [])

        # AI가 추출한 구체적 문구 + 스크립트 구조 지표
        ai_sm = data.get("ai_script_metrics", {})
        result.script_metrics = {
            "hook_position_pct": ai_sm.get("hook_position_pct", 0),
            "first_cta_position_pct": ai_sm.get("first_cta_position_pct", 0),
            "cta_count": ai_sm.get("cta_count", 0),
            "narrative_structure": ai_sm.get("narrative_structure", ""),
            "high_impact_phrases": data.get("high_impact_phrases", []),
        }
        return result

    def _extract_patterns_from_analysis(self, full_analysis: str) -> list[dict]:
        """full_analysis 텍스트에서 patterns 배열을 추출한다."""
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", full_analysis, re.DOTALL)
        if not json_match:
            return []
        try:
            data = json.loads(json_match.group(1))
            return data.get("patterns", [])
        except Exception:
            return []

    @staticmethod
    def _find_similar_pattern(new_desc: str, existing_patterns: list[dict]) -> dict | None:
        """기존 패턴 중 new_desc와 가장 유사한 것을 반환 (임계값 미만이면 None)"""
        best_match = None
        best_score = 0
        for pat in existing_patterns:
            score = fuzz.ratio(new_desc, pat.get("description", ""))
            if score >= THRESHOLD and score > best_score:
                best_score = score
                best_match = pat
        return best_match
