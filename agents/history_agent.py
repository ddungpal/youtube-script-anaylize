"""
축적 데이터 심화 분석 에이전트
- DB에 쌓인 전체 영상 데이터를 기반으로 심화 분석을 수행한다.
- 트렌드 분석, 패턴 상관관계, 벤치마크, 예측을 제공한다.
"""
import logging
import os
import statistics
from datetime import datetime

from openai import OpenAI

from models.content import HistoricalInsight, VideoContent
from database.db_manager import DBManager

logger = logging.getLogger(__name__)


def _load_deep_prompt() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "deep_analysis_prompt.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


class HistoryAgent:
    def __init__(self, db: DBManager):
        self.db = db
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0"))

    # ----------------------------------------------------------
    # 컨텍스트 생성
    # ----------------------------------------------------------

    def generate_historical_context(self) -> dict:
        """현재 분석 시 Claude에게 전달할 축적 데이터 요약"""
        stats = self.db.get_stats_summary()
        if stats["total_videos"] == 0:
            return {"total_videos": 0}

        trend_data = self.db.get_conversion_trend()
        rates = [r["conversion_rate"] for r in trend_data]

        # 최근 추세 (최근 5개 vs 이전)
        recent_trend = "정보 없음"
        if len(rates) >= 5:
            recent_avg = statistics.mean(rates[-5:])
            earlier_avg = statistics.mean(rates[:-5]) if len(rates) > 5 else recent_avg
            diff = recent_avg - earlier_avg
            if diff > 0.3:
                recent_trend = "상승"
            elif diff < -0.3:
                recent_trend = "하락"
            else:
                recent_trend = "유지"

        # 상위/하위 5개 평균 점수
        top_analyses = self._get_tier_avg_scores("top")
        bottom_analyses = self._get_tier_avg_scores("bottom")

        success_patterns = self.db.get_success_patterns(min_frequency=2)
        failure_patterns = self.db.get_failure_patterns(min_frequency=2)

        return {
            "total_videos": stats["total_videos"],
            "avg_conversion_rate": stats["avg_rate"],
            "median_conversion_rate": stats["median_rate"],
            "std_deviation": stats["std_dev"],
            "top_5_avg_scores": top_analyses,
            "bottom_5_avg_scores": bottom_analyses,
            "success_patterns_top5": success_patterns[:5],
            "failure_patterns_top5": failure_patterns[:5],
            "recent_trend": recent_trend,
        }

    # ----------------------------------------------------------
    # 트렌드 분석
    # ----------------------------------------------------------

    def analyze_trend(self, output_dir: str = "outputs/charts") -> str:
        """시간순 전환률 추이 분석 + 차트 생성"""
        trend_data = self.db.get_conversion_trend()
        if len(trend_data) < 3:
            return "데이터가 부족합니다. 최소 3개 영상이 필요합니다."

        rates = [r["conversion_rate"] for r in trend_data]
        labels = [r.get("title", r["video_id"])[:20] for r in trend_data]

        # 이동 평균
        from utils.stats import calculate_moving_average, generate_trend_chart
        ma3 = calculate_moving_average(rates, 3)
        ma5 = calculate_moving_average(rates, 5)

        # 차트 저장
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d")
        chart_path = os.path.join(output_dir, f"trend_{ts}.png")
        generate_trend_chart(labels, rates, ma3, chart_path)

        # Claude 트렌드 인사이트
        context = (
            f"총 {len(rates)}개 영상의 전환률 데이터:\n"
            f"전체 평균: {statistics.mean(rates):.2f}%\n"
            f"최근 3개 평균: {statistics.mean(rates[-3:]):.2f}%\n"
            f"최고: {max(rates):.2f}%, 최저: {min(rates):.2f}%\n\n"
            f"3개 이동평균 (최근): {[round(v, 2) for v in ma3[-5:]]}\n"
            f"5개 이동평균 (최근): {[round(v, 2) for v in ma5[-5:]] if len(ma5) >= 5 else '데이터 부족'}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1500,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": "당신은 데이터 분석 전문가입니다. 전환률 추이 데이터를 보고 핵심 인사이트를 한국어로 간결하게 제시하세요."},
                {"role": "user", "content": context},
            ],
        )
        return response.choices[0].message.content

    # ----------------------------------------------------------
    # 패턴 상관관계
    # ----------------------------------------------------------

    def analyze_patterns_correlation(self) -> str:
        """패턴 라이브러리와 전환률 상관관계 분석"""
        success_patterns = self.db.get_success_patterns(min_frequency=2)
        failure_patterns = self.db.get_failure_patterns(min_frequency=2)

        if not success_patterns and not failure_patterns:
            return "패턴 데이터가 부족합니다."

        lines = ["## 패턴-전환률 상관관계 분석", ""]
        if success_patterns:
            lines.append("### 성공 패턴 (빈도순)")
            for p in success_patterns[:10]:
                lines.append(
                    f"- [{p['category']}] {p['description']} "
                    f"(발견 {p['frequency']}회, 평균 전환률 {p.get('avg_conversion', 0):.1f}%)"
                )
        if failure_patterns:
            lines.append("")
            lines.append("### 실패 패턴 (빈도순)")
            for p in failure_patterns[:10]:
                lines.append(
                    f"- [{p['category']}] {p['description']} "
                    f"(발견 {p['frequency']}회, 평균 전환률 {p.get('avg_conversion', 0):.1f}%)"
                )

        context = "\n".join(lines)
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": "당신은 마케팅 데이터 분석 전문가입니다. 패턴 데이터를 분석하여 전환률과의 상관관계를 파악하고 인사이트를 제공하세요."},
                {"role": "user", "content": context},
            ],
        )
        return response.choices[0].message.content

    # ----------------------------------------------------------
    # 키워드-전환율 상관관계 분석
    # ----------------------------------------------------------

    def analyze_keyword_correlation(self) -> str:
        """
        모든 영상의 script_metrics를 비교해
        어떤 언어 패턴이 구독 전환율과 연관되는지 데이터로 보여준다.
        최소 3개 영상이 필요하다.
        """
        from utils.script_analyzer import compute_keyword_correlation, KEYWORD_CATEGORIES  # noqa: PLC0415

        all_data = self.db.get_all_script_metrics()
        if len(all_data) < 3:
            return f"데이터가 부족합니다. 현재 {len(all_data)}개, 최소 3개 영상이 필요합니다."

        corr = compute_keyword_correlation(all_data)
        if not corr:
            return "상관관계를 계산할 수 없습니다."

        per_video = corr["per_video"]          # 전환율 내림차순 정렬
        high_m = corr["metric_by_tier"]["high"]
        low_m = corr["metric_by_tier"]["low"]
        ratio_list = corr["high_vs_low_ratio"]

        # ── 1. 전체 영상 개별 지표 테이블 ──
        lines = [
            "## 단어 사용 패턴과 구독 전환율 분석",
            "",
            f"분석 영상: {corr['total_videos']}개 (전환율 높은 순)",
            "",
            "### 1. 전체 영상별 스크립트 지표",
            "",
            "| 순위 | 영상 제목 | 전환율 | 총단어 | 질문수 | 숫자언급 | 느낌표 | 구독밀도(%) |",
            "|------|---------|------|------|------|--------|------|-----------|",
        ]
        for i, v in enumerate(per_video, 1):
            title_short = (v["title"] or v["video_id"])[:22]
            lines.append(
                f"| {i} | {title_short} | {v['conversion_rate']}% "
                f"| {v['total_words']} | {v['question_count']} "
                f"| {v['number_mention_count']} | {v['exclamation_count']} "
                f"| {v['subscription_density']} |"
            )

        # ── 2. 키워드 카테고리별 영상 비교 ──
        lines.append("")
        lines.append("### 2. 키워드 카테고리별 사용 횟수 (영상별)")
        lines.append("")
        cat_header = "| 카테고리 | " + " | ".join(
            (v["title"] or v["video_id"])[:10] for v in per_video
        ) + " |"
        cat_sep = "|" + "---------|" * (len(per_video) + 1)
        lines.append(cat_header)
        lines.append(cat_sep)
        for cat in KEYWORD_CATEGORIES:
            row = f"| {cat} | "
            row += " | ".join(str(v["category_counts"].get(cat, 0)) for v in per_video)
            row += " |"
            lines.append(row)

        # ── 3. 자주 쓰인 키워드 TOP (영상별) ──
        lines.append("")
        lines.append("### 3. 영상별 자주 쓰인 키워드 TOP 5")
        lines.append("")
        for v in per_video:
            title_short = (v["title"] or v["video_id"])[:25]
            top_kws = v["top_keywords"][:5]
            kw_str = ", ".join(f"{k['word']}({k['count']}회)" for k in top_kws) if top_kws else "없음"
            lines.append(f"- **{title_short}** (전환율 {v['conversion_rate']}%): {kw_str}")

        # ── 4. 고/저 전환율 그룹 평균 비교 ──
        lines.append("")
        lines.append(
            f"### 4. 고전환율 그룹 vs 저전환율 그룹 평균 비교\n"
            f"고전환율 기준: ≥{corr['high_threshold']}% ({corr['high_group_size']}개) | "
            f"저전환율 기준: ≤{corr['low_threshold']}% ({corr['low_group_size']}개)"
        )
        lines.append("")
        lines.append("| 지표 | 고전환율 평균 | 저전환율 평균 | 차이 |")
        lines.append("|------|-------------|-------------|------|")
        metric_labels = {
            "total_words": "총 단어수",
            "question_count": "질문 수",
            "number_mention_count": "숫자/통계 언급",
            "exclamation_count": "느낌표 수",
            "subscription_density": "구독 유도 밀도(%)",
        }
        for key, label in metric_labels.items():
            h = high_m.get(key, 0)
            l = low_m.get(key, 0)
            diff = round(h - l, 2)
            sign = "▲" if diff > 0 else ("▼" if diff < 0 else "-")
            lines.append(f"| {label} | {h} | {l} | {sign} {abs(diff)} |")

        lines.append("")
        lines.append("| 카테고리 | 고전환율 평균 | 저전환율 평균 | 비율 |")
        lines.append("|---------|------------|------------|------|")
        for cat in KEYWORD_CATEGORIES:
            h = high_m.get(f"cat_{cat}", 0)
            l = low_m.get(f"cat_{cat}", 0)
            ratio = round(h / l, 1) if l > 0 else ("∞" if h > 0 else "-")
            lines.append(f"| {cat} | {h}회 | {l}회 | {ratio}배 |")

        # ── 5. 고전환율에서 더 자주 등장하는 단어 ──
        lines.append("")
        lines.append("### 5. 고전환율 영상에서 더 자주 등장하는 단어 TOP 10")
        lines.append("")
        top_words = [r for r in ratio_list if r["high_avg"] > 0][:10]
        for i, r in enumerate(top_words, 1):
            lines.append(
                f"{i}. **\"{r['word']}\"** — 고전환율 평균 {r['high_avg']}회, "
                f"저전환율 평균 {r['low_avg']}회 (비율: {r['ratio']}배)"
            )

        raw_report = "\n".join(lines)

        # AI 해석 추가
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1500,
            temperature=self.temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 마케팅 데이터 분석 전문가입니다. "
                        "아래 전체 영상의 단어-전환율 데이터를 해석하여 "
                        "콘텐츠 제작자가 즉시 활용할 수 있는 구체적인 인사이트를 한국어로 제공하세요."
                    ),
                },
                {"role": "user", "content": raw_report},
            ],
        )
        ai_insight = response.choices[0].message.content

        return f"{raw_report}\n\n---\n\n### AI 해석\n\n{ai_insight}"

    # ----------------------------------------------------------
    # 벤치마크
    # ----------------------------------------------------------

    def generate_benchmark(self, current_videos: list[VideoContent]) -> list[dict]:
        """현재 분석 영상들을 역대 데이터와 비교"""
        stats = self.db.get_stats_summary()
        all_rates = [r["conversion_rate"] for r in self.db.get_conversion_trend()]

        benchmarks = []
        for video in current_videos:
            pct = self._calculate_percentile(video.conversion_rate, all_rates)
            analysis = self.db.get_latest_analysis(video.video_id)
            gap_note = ""
            if analysis:
                tier_scores = self.db.get_avg_scores_by_conversion_tier()
                top_scores = tier_scores.get("상", {})
                if top_scores:
                    weakest = min(
                        ["hook", "story", "value", "cta", "emotion", "topic", "diff"],
                        key=lambda k: getattr(analysis, f"{k}_score", 0) - top_scores.get(k, 0),
                    )
                    diff = getattr(analysis, f"{weakest}_score", 0) - top_scores.get(weakest, 0)
                    gap_note = f"상위 20% 대비 {weakest} 점수가 {abs(diff):.1f}점 낮음"

            benchmarks.append({
                "video_title": video.title or video.url,
                "your_conversion": video.conversion_rate,
                "historical_avg": stats["avg_rate"],
                "percentile": pct,
                "gap_analysis": gap_note,
            })
        return benchmarks

    # ----------------------------------------------------------
    # 심화 인사이트 리포트
    # ----------------------------------------------------------

    def generate_deep_insight_report(self, output_dir: str = "outputs/trends") -> tuple[HistoricalInsight, str]:
        """전체 축적 데이터 종합 심화 인사이트 리포트"""
        context = self.generate_historical_context()
        success_pats = self.db.get_success_patterns(min_frequency=2)
        failure_pats = self.db.get_failure_patterns(min_frequency=2)
        trend_data = self.db.get_conversion_trend()

        template = _load_deep_prompt()
        if template:
            user_content = (
                template
                .replace("{historical_context}", str(context))
                .replace("{success_patterns}", str(success_pats[:10]))
                .replace("{failure_patterns}", str(failure_pats[:10]))
                .replace("{trend_data}", str(trend_data))
            )
        else:
            user_content = self._build_deep_analysis_prompt(context, success_pats, failure_pats, trend_data)

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": "당신은 데이터 기반 콘텐츠 전략 분석가입니다. '생각구독' 채널의 축적된 데이터를 분석하여 심화 인사이트를 제공하세요."},
                {"role": "user", "content": user_content},
            ],
        )
        report_text = response.choices[0].message.content

        # 리포트 파일 저장
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = os.path.join(output_dir, f"deep_insight_{ts}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# 심화 인사이트 리포트\n생성일: {ts}\n\n")
            f.write(report_text)

        insight = HistoricalInsight(
            total_videos_analyzed=context.get("total_videos", 0),
            avg_conversion_rate=context.get("avg_conversion_rate", 0),
            conversion_trend=context.get("recent_trend", ""),
            recurring_success_patterns=success_pats[:5],
            recurring_failure_patterns=failure_pats[:5],
            actionable_insights=[report_text],
        )
        return insight, report_path

    # ----------------------------------------------------------
    # 전환률 예측
    # ----------------------------------------------------------

    def predict_conversion_potential(self, video: VideoContent) -> dict:
        """축적 데이터 기반 신규 영상 예상 전환률 범위 추정"""
        analysis = self.db.get_latest_analysis(video.video_id)
        if not analysis:
            return {"predicted_range": [0, 0], "confidence": "낮음", "similar_videos": [], "improvement_suggestions": []}

        # 유사 점수 프로필의 과거 영상 찾기
        all_videos = self.db.get_all_videos()
        similar = []
        for v in all_videos:
            if v.video_id == video.video_id:
                continue
            past_a = self.db.get_latest_analysis(v.video_id)
            if not past_a:
                continue
            diff = abs(past_a.overall_score - analysis.overall_score)
            if diff <= 1.5:
                similar.append({"video": v, "analysis": past_a})

        if not similar:
            stats = self.db.get_stats_summary()
            return {
                "predicted_range": [
                    round(stats["avg_rate"] - stats["std_dev"], 2),
                    round(stats["avg_rate"] + stats["std_dev"], 2),
                ],
                "confidence": "낮음 (유사 영상 없음)",
                "similar_videos": [],
                "improvement_suggestions": [],
            }

        similar_rates = [s["video"].conversion_rate for s in similar]
        mean_r = statistics.mean(similar_rates)
        std_r = statistics.stdev(similar_rates) if len(similar_rates) > 1 else 1.0
        confidence = "높음" if len(similar) >= 5 else "중간" if len(similar) >= 3 else "낮음"

        return {
            "predicted_range": [round(mean_r - std_r, 2), round(mean_r + std_r, 2)],
            "confidence": confidence,
            "similar_videos": [s["video"].title or s["video"].url for s in similar[:5]],
            "improvement_suggestions": [],
        }

    # ----------------------------------------------------------
    # 내부 헬퍼
    # ----------------------------------------------------------

    def _get_tier_avg_scores(self, tier: str) -> dict:
        if tier == "top":
            videos = self.db.get_top_videos(5)
        else:
            videos = self.db.get_bottom_videos(5)
        if not videos:
            return {}
        score_keys = ["hook_score", "story_score", "value_score", "cta_score",
                      "emotion_score", "topic_score", "diff_score", "overall_score"]
        totals = {k: 0.0 for k in score_keys}
        count = 0
        for v in videos:
            a = self.db.get_latest_analysis(v.video_id)
            if a:
                count += 1
                for k in score_keys:
                    totals[k] += getattr(a, k, 0)
        if count == 0:
            return {}
        return {k.replace("_score", ""): round(totals[k] / count, 2) for k in score_keys}

    @staticmethod
    def _calculate_percentile(rate: float, all_rates: list[float]) -> float:
        if not all_rates:
            return 50.0
        below = sum(1 for r in all_rates if r < rate)
        return round(below / len(all_rates) * 100, 1)

    def _build_deep_analysis_prompt(
        self, context: dict, success_pats: list, failure_pats: list, trend_data: list
    ) -> str:
        lines = [
            "# 생각구독 채널 심화 분석 요청",
            "",
            f"## 축적 데이터 요약",
            f"- 총 영상 수: {context.get('total_videos', 0)}개",
            f"- 평균 전환률: {context.get('avg_conversion_rate', 0)}%",
            f"- 최근 추세: {context.get('recent_trend', '정보 없음')}",
            "",
            "## 성공 패턴",
        ]
        for p in success_pats[:10]:
            lines.append(f"- [{p['category']}] {p['description']} (빈도: {p['frequency']}, 평균전환률: {p.get('avg_conversion', 0):.1f}%)")

        lines.append("")
        lines.append("## 실패 패턴")
        for p in failure_pats[:10]:
            lines.append(f"- [{p['category']}] {p['description']} (빈도: {p['frequency']})")

        lines.append("")
        lines.append(
            "위 데이터를 종합하여 아래 심화 분석을 수행해주세요:\n"
            "1. 핵심 성공 공식\n"
            "2. 최적 영상 프로필\n"
            "3. 숨겨진 패턴 발굴\n"
            "4. 개선 로드맵 (1개월/3개월/6개월)\n"
            "5. 위험 신호 감지"
        )
        return "\n".join(lines)
