"""
생각구독 콘텐츠 분석 에이전시 v2 — 웹 서버
FastAPI 기반. 기존 agents/database/utils 코드를 그대로 재사용한다.

실행:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# ── 디렉터리 보장 (Vercel 등 읽기 전용 FS에서는 조용히 무시) ──────────────────
for _d in ["outputs/reports", "outputs/trends", "outputs/charts", "data", "static"]:
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

# ── FastAPI 앱 ────────────────────────────────────────────────────────────────
app = FastAPI(title="생각구독 분석 에이전시", version="2.0")

# 디렉터리가 존재할 때만 마운트 (Vercel read-only FS 대응)
if os.path.isdir("outputs"):
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
if os.path.isdir("data"):
    app.mount("/data_files", StaticFiles(directory="data"), name="data_files")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── 태스크 저장소 (메모리) ────────────────────────────────────────────────────
TASKS: dict = {}
_lock = threading.Lock()


# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────
def _db():
    from database.db_manager import DBManager
    return DBManager(os.getenv("DB_PATH", "database/saenggak.db"))


def _video_to_dict(v, db):
    a = db.get_latest_analysis(v.video_id)
    return {
        "video_id": v.video_id,
        "title": v.title or v.url,
        "url": v.url,
        "conversion_rate": v.conversion_rate,
        "duration_seconds": v.duration_seconds,
        "created_at": str(v.created_at)[:10] if v.created_at else "",
        "overall_score": a.overall_score if a else None,
        "hook_score": a.hook_score if a else None,
        "story_score": a.story_score if a else None,
        "value_score": a.value_score if a else None,
        "cta_score": a.cta_score if a else None,
        "emotion_score": a.emotion_score if a else None,
        "topic_score": a.topic_score if a else None,
        "diff_score": a.diff_score if a else None,
    }


# ── 요청 모델 ─────────────────────────────────────────────────────────────────
class AnalyzeInput(BaseModel):
    url: str
    conversion_rate: float
    reanalyze: bool = False


class AnalyzeRequest(BaseModel):
    inputs: list[AnalyzeInput]


class UpdateRateRequest(BaseModel):
    conversion_rate: float


# ══════════════════════════════════════════════════════════════════════════════
# 정적 페이지
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ══════════════════════════════════════════════════════════════════════════════
# 대시보드 통계
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/stats")
def get_stats():
    db = _db()
    try:
        stats = db.get_stats_summary()
        top5 = db.get_top_videos(5)
        bottom5 = db.get_bottom_videos(5)
        sessions = db.get_session_history(5)
        return {
            "summary": stats,
            "top5": [_video_to_dict(v, db) for v in top5],
            "bottom5": [_video_to_dict(v, db) for v in bottom5],
            "sessions": sessions,
        }
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 영상 목록 / 상세
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/videos")
def get_videos():
    db = _db()
    try:
        return [_video_to_dict(v, db) for v in db.get_all_videos()]
    finally:
        db.close()


@app.get("/api/videos/{video_id}")
def get_video(video_id: str):
    db = _db()
    try:
        v = db.get_video(video_id)
        if not v:
            raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
        a = db.get_latest_analysis(video_id)
        return {
            "video_id": v.video_id,
            "title": v.title or v.url,
            "url": v.url,
            "description": v.description,
            "tags": v.tags,
            "duration_seconds": v.duration_seconds,
            "conversion_rate": v.conversion_rate,
            "created_at": str(v.created_at) if v.created_at else "",
            "analysis": {
                "hook_score": a.hook_score,
                "story_score": a.story_score,
                "value_score": a.value_score,
                "cta_score": a.cta_score,
                "emotion_score": a.emotion_score,
                "topic_score": a.topic_score,
                "diff_score": a.diff_score,
                "overall_score": a.overall_score,
                "strengths": a.strengths,
                "weaknesses": a.weaknesses,
                "key_hooks": a.key_hooks,
                "cta_analysis": a.cta_analysis,
                "topic_relevance": a.topic_relevance,
                "emotional_triggers": a.emotional_triggers,
                "full_analysis": a.full_analysis[:4000],
            } if a else None,
        }
    finally:
        db.close()


@app.put("/api/videos/{video_id}/rate")
def update_rate(video_id: str, body: UpdateRateRequest):
    db = _db()
    try:
        if not db.video_exists(video_id):
            raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
        db.update_conversion_rate(video_id, body.conversion_rate)
        return {"ok": True}
    finally:
        db.close()


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    db = _db()
    try:
        if not db.video_exists(video_id):
            raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
        db.delete_video(video_id)
        return {"ok": True}
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 검색
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/search")
def search_videos(
    mode: str = "all",
    keyword: str = "",
    min_rate: float = 0,
    max_rate: float = 100,
    hook_score: Optional[float] = None,
    story_score: Optional[float] = None,
    value_score: Optional[float] = None,
    cta_score: Optional[float] = None,
    emotion_score: Optional[float] = None,
    topic_score: Optional[float] = None,
    diff_score: Optional[float] = None,
    overall_score: Optional[float] = None,
):
    db = _db()
    try:
        if mode == "keyword":
            videos = db.search_videos(keyword)
        elif mode == "rate_range":
            videos = db.get_videos_by_conversion_range(min_rate, max_rate)
        elif mode == "scores":
            conditions = {}
            for k, v in [
                ("hook_score", hook_score), ("story_score", story_score),
                ("value_score", value_score), ("cta_score", cta_score),
                ("emotion_score", emotion_score), ("topic_score", topic_score),
                ("diff_score", diff_score), ("overall_score", overall_score),
            ]:
                if v is not None:
                    conditions[k] = v
            videos = db.search_by_scores(conditions)
        else:
            videos = db.get_all_videos()
        return [_video_to_dict(v, db) for v in videos]
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 패턴 라이브러리
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/patterns")
def get_patterns():
    db = _db()
    try:
        return {
            "success": db.get_success_patterns(min_frequency=1),
            "failure": db.get_failure_patterns(min_frequency=1),
        }
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 트렌드 분석 (백그라운드)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/trends")
def run_trends():
    db = _db()
    try:
        stats = db.get_stats_summary()
        if stats["total_videos"] < 8:
            raise HTTPException(
                status_code=400,
                detail=f"트렌드 분석은 최소 8개 영상이 필요합니다. (현재: {stats['total_videos']}개)",
            )
    finally:
        db.close()

    task_id = str(uuid.uuid4())
    with _lock:
        TASKS[task_id] = {"status": "running", "progress": [], "result": None, "error": None}
    threading.Thread(target=_run_trends, args=(task_id,), daemon=True).start()
    return {"task_id": task_id}


def _run_trends(task_id: str):
    try:
        from agents.history_agent import HistoryAgent
        db = _db()
        ha = HistoryAgent(db)

        _append_progress(task_id, "트렌드 차트 생성 중...")
        trend_text = ha.analyze_trend()

        _append_progress(task_id, "패턴 상관관계 분석 중...")
        corr_text = ha.analyze_patterns_correlation()

        trend_data = db.get_conversion_trend()
        labels = [r.get("title", r["video_id"])[:15] for r in trend_data]
        rates = [r["conversion_rate"] for r in trend_data]
        db.close()

        chart_url = f"/outputs/charts/trend_{datetime.now().strftime('%Y-%m-%d')}.png"
        _set_completed(task_id, {
            "trend_text": trend_text,
            "correlation_text": corr_text,
            "chart_url": chart_url,
            "labels": labels,
            "rates": rates,
        })
    except Exception as e:
        _set_error(task_id, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 키워드-전환율 상관관계 분석 (백그라운드)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/keyword-correlation")
def run_keyword_correlation():
    db = _db()
    try:
        stats = db.get_stats_summary()
        if stats["total_videos"] < 3:
            raise HTTPException(
                status_code=400,
                detail=f"키워드 상관관계 분석은 최소 3개 영상이 필요합니다. (현재: {stats['total_videos']}개)",
            )
    finally:
        db.close()

    task_id = str(uuid.uuid4())
    with _lock:
        TASKS[task_id] = {"status": "running", "progress": [], "result": None, "error": None}
    threading.Thread(target=_run_keyword_correlation, args=(task_id,), daemon=True).start()
    return {"task_id": task_id}


def _run_keyword_correlation(task_id: str):
    try:
        from agents.history_agent import HistoryAgent
        db = _db()
        ha = HistoryAgent(db)
        _append_progress(task_id, "단어 사용 패턴 분석 중...")
        report = ha.analyze_keyword_correlation()
        db.close()
        _set_completed(task_id, {"report": report})
    except Exception as e:
        _set_error(task_id, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 심화 인사이트 (백그라운드)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/insight")
def run_insight():
    db = _db()
    try:
        stats = db.get_stats_summary()
        if stats["total_videos"] < 10:
            raise HTTPException(
                status_code=400,
                detail=f"심화 인사이트는 최소 10개 영상이 필요합니다. (현재: {stats['total_videos']}개)",
            )
    finally:
        db.close()

    task_id = str(uuid.uuid4())
    with _lock:
        TASKS[task_id] = {"status": "running", "progress": [], "result": None, "error": None}
    threading.Thread(target=_run_insight, args=(task_id,), daemon=True).start()
    return {"task_id": task_id}


def _run_insight(task_id: str):
    try:
        from agents.history_agent import HistoryAgent
        db = _db()
        ha = HistoryAgent(db)

        _append_progress(task_id, "심화 인사이트 분석 중...")
        insight, report_path = ha.generate_deep_insight_report()
        db.close()

        _set_completed(task_id, {
            "text": insight.actionable_insights[0] if insight.actionable_insights else "",
            "report_path": "/" + report_path.replace("\\", "/"),
        })
    except Exception as e:
        _set_error(task_id, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 신규 분석 (백그라운드)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/analyze")
def start_analyze(body: AnalyzeRequest):
    task_id = str(uuid.uuid4())
    with _lock:
        TASKS[task_id] = {"status": "running", "progress": [], "result": None, "error": None}
    threading.Thread(target=_run_analysis, args=(task_id, body.inputs), daemon=True).start()
    return {"task_id": task_id}


def _run_analysis(task_id: str, inputs: list[AnalyzeInput]):
    try:
        from agents.transcript_agent import TranscriptAgent
        from agents.analysis_agent import AnalysisAgent
        from agents.strategy_agent import StrategyAgent
        from agents.history_agent import HistoryAgent
        from utils.helpers import save_report

        db = _db()

        # 스크립트 추출
        _append_progress(task_id, "스크립트 추출 중...")
        ta = TranscriptAgent(db)
        raw_inputs = [
            {"url": i.url, "conversion_rate": i.conversion_rate, "reanalyze": i.reanalyze}
            for i in inputs
        ]
        successes, failures = ta.process_videos_batch(raw_inputs)

        for f in failures:
            _append_progress(task_id, f"추출 실패: {f['url'][:40]} — {f['reason']}")

        if not successes:
            _set_error(task_id, "분석 가능한 영상이 없습니다.")
            db.close()
            return

        _append_progress(task_id, f"스크립트 추출 완료 ({len(successes)}/{len(inputs)}개)")

        # 역사 컨텍스트
        stats = db.get_stats_summary()
        ha = HistoryAgent(db)
        hist_ctx = ha.generate_historical_context() if stats["total_videos"] >= 5 else None

        # 개별 분석
        aa = AnalysisAgent(db)
        analyses = []
        session_id = str(uuid.uuid4())

        for i, video in enumerate(successes, 1):
            _append_progress(task_id, f"[{i}/{len(successes)}] 분석 중: {(video.title or video.url)[:35]}")
            reanalyze_flag = next(
                (inp.reanalyze for inp in inputs if inp.url == video.url), False
            )
            analysis = aa.analyze_single_video(video, historical_context=hist_ctx)
            db.save_analysis(analysis, session_id)
            aa.extract_and_save_patterns(analysis, reanalyze=reanalyze_flag)
            analyses.append(analysis)
            _append_progress(task_id, f"  ✓ overall: {analysis.overall_score}/10")

        # 비교 분석
        comparison = ""
        if len(analyses) >= 2:
            _append_progress(task_id, "비교 분석 중...")
            comparison = aa.compare_videos(successes, analyses, historical_patterns=hist_ctx)

        # 벤치마크
        benchmark = []
        if stats["total_videos"] >= 5:
            _append_progress(task_id, "벤치마크 분석 중...")
            benchmark = ha.generate_benchmark(successes)

        # 전략 수립
        _append_progress(task_id, "전략 수립 중...")
        sa = StrategyAgent(db)
        strategy = sa.generate_strategy(analyses, comparison, hist_ctx, benchmark)

        # 리포트 저장
        report_path = save_report(analyses, strategy, comparison, benchmark)
        db.save_session({
            "session_id": session_id,
            "video_ids": [v.video_id for v in successes],
            "strategy_report": strategy.comparative_summary[:500],
            "report_path": report_path,
        })
        db.close()

        _append_progress(task_id, "완료!")
        _set_completed(task_id, {
            "analyses": [
                {
                    "video_id": a.video.video_id,
                    "title": a.video.title or a.video.url,
                    "conversion_rate": a.video.conversion_rate,
                    "hook_score": a.hook_score,
                    "story_score": a.story_score,
                    "value_score": a.value_score,
                    "cta_score": a.cta_score,
                    "emotion_score": a.emotion_score,
                    "topic_score": a.topic_score,
                    "diff_score": a.diff_score,
                    "overall_score": a.overall_score,
                    "strengths": a.strengths[:3],
                    "weaknesses": a.weaknesses[:3],
                }
                for a in analyses
            ],
            "strategy": strategy.comparative_summary[:3000],
            "report_path": "/" + report_path.replace("\\", "/"),
            "failures": failures,
        })
    except Exception as e:
        _set_error(task_id, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 태스크 상태 조회
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    with _lock:
        task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="태스크를 찾을 수 없습니다.")
    return task


# ══════════════════════════════════════════════════════════════════════════════
# 내보내기
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/export/{fmt}")
def export_data(fmt: str):
    db = _db()
    ts = datetime.now().strftime("%Y-%m-%d")
    try:
        if fmt == "csv":
            path = f"data/export_{ts}.csv"
            db.export_to_csv(path)
            db.close()
            return FileResponse(path, filename=f"saenggak_export_{ts}.csv", media_type="text/csv")
        elif fmt == "json":
            path = f"data/export_{ts}.json"
            db.export_to_json(path)
            db.close()
            return FileResponse(path, filename=f"saenggak_export_{ts}.json", media_type="application/json")
        elif fmt == "markdown":
            from utils.helpers import export_markdown_archive
            all_videos = db.get_all_videos()
            pairs = [(v, db.get_latest_analysis(v.video_id)) for v in all_videos]
            pairs = [(v, a) for v, a in pairs if a]
            db.close()
            if not pairs:
                raise HTTPException(status_code=400, detail="분석 데이터가 없습니다.")
            index_path = export_markdown_archive(pairs, output_dir="data")
            return FileResponse(
                index_path,
                filename=f"saenggak_archive_{ts}.md",
                media_type="text/markdown",
            )
        else:
            db.close()
            raise HTTPException(status_code=400, detail="지원하지 않는 형식입니다.")
    except HTTPException:
        raise
    except Exception as e:
        db.close()
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 태스크 헬퍼
# ══════════════════════════════════════════════════════════════════════════════

def _append_progress(task_id: str, message: str):
    with _lock:
        if task_id in TASKS:
            TASKS[task_id]["progress"].append(message)


def _set_completed(task_id: str, result: dict):
    with _lock:
        if task_id in TASKS:
            TASKS[task_id]["status"] = "completed"
            TASKS[task_id]["result"] = result


def _set_error(task_id: str, error: str):
    with _lock:
        if task_id in TASKS:
            TASKS[task_id]["status"] = "error"
            TASKS[task_id]["error"] = error
