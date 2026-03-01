"""
DB 매니저
- SQLite DB의 모든 CRUD 작업을 관리한다.
- 앱 시작 시 자동으로 테이블을 생성한다.
"""
import sqlite3
import json
import logging
import os
import shutil
from datetime import datetime
from typing import Optional

from models.content import VideoContent, AnalysisResult
from database.migrations import run_migrations

logger = logging.getLogger(__name__)


class DBManager:
    def __init__(self, db_path: str = "database/saenggak.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        run_migrations(self._conn)
        logger.debug(f"DB 연결: {db_path}")

    def _execute(self, sql: str, params=()) -> sqlite3.Cursor:
        logger.debug(f"DB 쿼리: {sql[:120]} | params={params}")
        return self._conn.execute(sql, params)

    def close(self):
        self._conn.close()

    # ============================================================
    # 영상 CRUD
    # ============================================================

    def save_video(self, video: VideoContent) -> bool:
        """영상 데이터 저장 (이미 존재하면 전환률만 업데이트)"""
        try:
            tags_json = json.dumps(video.tags, ensure_ascii=False)
            self._conn.execute(
                """
                INSERT INTO videos (video_id, url, title, description, tags, transcript,
                                    duration_seconds, conversion_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    conversion_rate = excluded.conversion_rate,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video.video_id, video.url, video.title, video.description,
                 tags_json, video.transcript, video.duration_seconds, video.conversion_rate),
            )
            # 태그 인덱스 갱신
            self._conn.execute("DELETE FROM tags_index WHERE video_id = ?", (video.video_id,))
            for tag in video.tags:
                self._conn.execute(
                    "INSERT INTO tags_index (video_id, tag) VALUES (?, ?)",
                    (video.video_id, tag.lower()),
                )
            self._conn.commit()
            logger.debug(f"영상 저장 완료: {video.video_id}")
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"영상 저장 실패: {e}")
            return False

    def get_video(self, video_id: str) -> Optional[VideoContent]:
        """video_id로 영상 조회"""
        row = self._execute(
            "SELECT * FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_video(row)

    def get_all_videos(self) -> list:
        """전체 영상 목록 조회 (전환률 내림차순)"""
        rows = self._execute(
            "SELECT * FROM videos ORDER BY conversion_rate DESC"
        ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def video_exists(self, video_id: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
        return row is not None

    def update_conversion_rate(self, video_id: str, rate: float) -> bool:
        try:
            self._execute(
                "UPDATE videos SET conversion_rate = ?, updated_at = CURRENT_TIMESTAMP WHERE video_id = ?",
                (rate, video_id),
            )
            self._conn.commit()
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"전환률 업데이트 실패: {e}")
            return False

    def delete_video(self, video_id: str) -> bool:
        """영상 삭제 + 패턴 라이브러리 정리 (트랜잭션)"""
        try:
            # 1) 연관 패턴에서 해당 video_id 제거
            patterns = self._execute(
                "SELECT id, example_videos, frequency FROM patterns"
            ).fetchall()
            for p in patterns:
                examples = json.loads(p["example_videos"] or "[]")
                if video_id in examples:
                    examples.remove(video_id)
                    new_freq = p["frequency"] - 1
                    if new_freq <= 0:
                        self._execute("DELETE FROM patterns WHERE id = ?", (p["id"],))
                    else:
                        self._execute(
                            "UPDATE patterns SET example_videos = ?, frequency = ? WHERE id = ?",
                            (json.dumps(examples, ensure_ascii=False), new_freq, p["id"]),
                        )
            # 2) 나머지 테이블 삭제
            self._execute("DELETE FROM analyses WHERE video_id = ?", (video_id,))
            self._execute("DELETE FROM tags_index WHERE video_id = ?", (video_id,))
            self._execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            self._conn.commit()
            logger.debug(f"영상 삭제 완료: {video_id}")
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"영상 삭제 실패: {e}")
            return False

    # ============================================================
    # 분석 CRUD
    # ============================================================

    def save_analysis(self, analysis: AnalysisResult, session_id: str) -> bool:
        try:
            self._execute(
                """
                INSERT INTO analyses (
                    video_id, session_id, strengths, weaknesses, key_hooks,
                    cta_analysis, topic_relevance, emotional_triggers,
                    hook_score, story_score, value_score, cta_score,
                    emotion_score, topic_score, diff_score, overall_score,
                    full_analysis, script_metrics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis.video.video_id,
                    session_id,
                    json.dumps(analysis.strengths, ensure_ascii=False),
                    json.dumps(analysis.weaknesses, ensure_ascii=False),
                    json.dumps(analysis.key_hooks, ensure_ascii=False),
                    analysis.cta_analysis,
                    analysis.topic_relevance,
                    json.dumps(analysis.emotional_triggers, ensure_ascii=False),
                    analysis.hook_score,
                    analysis.story_score,
                    analysis.value_score,
                    analysis.cta_score,
                    analysis.emotion_score,
                    analysis.topic_score,
                    analysis.diff_score,
                    analysis.overall_score,
                    analysis.full_analysis,
                    json.dumps(analysis.script_metrics, ensure_ascii=False),
                ),
            )
            self._conn.commit()
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"분석 저장 실패: {e}")
            return False

    def get_analyses_for_video(self, video_id: str) -> list:
        rows = self._execute(
            "SELECT * FROM analyses WHERE video_id = ? ORDER BY created_at ASC",
            (video_id,),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_latest_analysis(self, video_id: str) -> Optional[AnalysisResult]:
        row = self._execute(
            "SELECT * FROM analyses WHERE video_id = ? ORDER BY created_at DESC LIMIT 1",
            (video_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_analysis(row)

    def remove_patterns_for_video(self, video_id: str) -> None:
        """재분석 시: 해당 video_id가 기여한 패턴에서 video_id를 제거하고 frequency 감소"""
        patterns = self._execute(
            "SELECT id, example_videos, frequency FROM patterns"
        ).fetchall()
        for p in patterns:
            examples = json.loads(p["example_videos"] or "[]")
            if video_id in examples:
                examples.remove(video_id)
                new_freq = p["frequency"] - 1
                if new_freq <= 0:
                    self._execute("DELETE FROM patterns WHERE id = ?", (p["id"],))
                else:
                    self._execute(
                        "UPDATE patterns SET example_videos = ?, frequency = ? WHERE id = ?",
                        (json.dumps(examples, ensure_ascii=False), new_freq, p["id"]),
                    )
        self._conn.commit()

    # ============================================================
    # 패턴 라이브러리
    # ============================================================

    def get_all_patterns(self) -> list:
        rows = self._execute(
            "SELECT * FROM patterns ORDER BY frequency DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def save_or_merge_pattern(self, pattern_type: str, category: str,
                              description: str, video_id: str,
                              conversion_rate: float, pattern_id: int = None) -> None:
        """기존 패턴(pattern_id)이 있으면 frequency 증가, 없으면 신규 저장"""
        if pattern_id is not None:
            row = self._execute(
                "SELECT example_videos, frequency, avg_conversion FROM patterns WHERE id = ?",
                (pattern_id,),
            ).fetchone()
            if row:
                examples = json.loads(row["example_videos"] or "[]")
                if video_id not in examples:
                    examples.append(video_id)
                new_freq = row["frequency"] + 1
                # 이동 평균 전환률 업데이트
                new_avg = (row["avg_conversion"] * row["frequency"] + conversion_rate) / new_freq
                self._execute(
                    """
                    UPDATE patterns
                    SET frequency = ?, avg_conversion = ?, example_videos = ?, last_seen = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_freq, new_avg, json.dumps(examples, ensure_ascii=False), pattern_id),
                )
        else:
            self._execute(
                """
                INSERT INTO patterns (pattern_type, category, description, frequency,
                                      avg_conversion, example_videos)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (pattern_type, category, description, conversion_rate,
                 json.dumps([video_id], ensure_ascii=False)),
            )
        self._conn.commit()

    def get_success_patterns(self, min_frequency: int = 2) -> list:
        rows = self._execute(
            "SELECT * FROM patterns WHERE pattern_type = 'success' AND frequency >= ? ORDER BY frequency DESC",
            (min_frequency,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_failure_patterns(self, min_frequency: int = 2) -> list:
        rows = self._execute(
            "SELECT * FROM patterns WHERE pattern_type = 'failure' AND frequency >= ? ORDER BY frequency DESC",
            (min_frequency,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_patterns_by_category(self, category: str) -> list:
        rows = self._execute(
            "SELECT * FROM patterns WHERE category = ? ORDER BY frequency DESC",
            (category,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # 세션
    # ============================================================

    def save_session(self, session: dict) -> bool:
        try:
            self._execute(
                """
                INSERT INTO sessions (session_id, video_ids, strategy_report, report_path)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    json.dumps(session.get("video_ids", []), ensure_ascii=False),
                    session.get("strategy_report", ""),
                    session.get("report_path", ""),
                ),
            )
            self._conn.commit()
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"세션 저장 실패: {e}")
            return False

    def get_session_history(self, limit: int = 10) -> list:
        rows = self._execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["video_ids"] = json.loads(d.get("video_ids") or "[]")
            result.append(d)
        return result

    # ============================================================
    # 통계 쿼리
    # ============================================================

    def get_stats_summary(self) -> dict:
        row = self._execute(
            """
            SELECT
                COUNT(*) as total_videos,
                AVG(conversion_rate) as avg_rate,
                MIN(conversion_rate) as min_rate,
                MAX(conversion_rate) as max_rate
            FROM videos
            """
        ).fetchone()
        if not row or row["total_videos"] == 0:
            return {"total_videos": 0, "avg_rate": 0, "min_rate": 0, "max_rate": 0,
                    "median_rate": 0, "std_dev": 0, "total_sessions": 0, "total_patterns": 0}

        rates = [r[0] for r in self._execute("SELECT conversion_rate FROM videos").fetchall()]
        import statistics
        median = statistics.median(rates) if rates else 0
        std_dev = statistics.stdev(rates) if len(rates) > 1 else 0

        sessions_count = self._execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        patterns_count = self._execute("SELECT COUNT(*) FROM patterns").fetchone()[0]

        return {
            "total_videos": row["total_videos"],
            "avg_rate": round(row["avg_rate"] or 0, 2),
            "min_rate": round(row["min_rate"] or 0, 2),
            "max_rate": round(row["max_rate"] or 0, 2),
            "median_rate": round(median, 2),
            "std_dev": round(std_dev, 2),
            "total_sessions": sessions_count,
            "total_patterns": patterns_count,
        }

    def get_conversion_trend(self) -> list:
        rows = self._execute(
            "SELECT video_id, title, conversion_rate, created_at FROM videos ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_top_videos(self, n: int = 5) -> list:
        rows = self._execute(
            "SELECT * FROM videos ORDER BY conversion_rate DESC LIMIT ?", (n,)
        ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def get_bottom_videos(self, n: int = 5) -> list:
        rows = self._execute(
            "SELECT * FROM videos ORDER BY conversion_rate ASC LIMIT ?", (n,)
        ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def get_videos_by_conversion_range(self, min_rate: float, max_rate: float) -> list:
        rows = self._execute(
            "SELECT * FROM videos WHERE conversion_rate BETWEEN ? AND ? ORDER BY conversion_rate DESC",
            (min_rate, max_rate),
        ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def search_videos(self, keyword: str) -> list:
        kw = f"%{keyword.lower()}%"
        rows = self._execute(
            """
            SELECT DISTINCT v.* FROM videos v
            LEFT JOIN tags_index t ON v.video_id = t.video_id
            WHERE LOWER(v.title) LIKE ?
               OR LOWER(v.transcript) LIKE ?
               OR LOWER(t.tag) LIKE ?
            ORDER BY v.conversion_rate DESC
            """,
            (kw, kw, kw),
        ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def search_by_scores(self, score_conditions: dict) -> list:
        """7개 점수 AND 조건 검색 (조건이 없는 점수는 건너뜀)"""
        score_cols = ["hook_score", "story_score", "value_score", "cta_score",
                      "emotion_score", "topic_score", "diff_score", "overall_score"]
        where_clauses = []
        params = []
        for col in score_cols:
            val = score_conditions.get(col)
            if val is not None:
                where_clauses.append(f"a.{col} >= ?")
                params.append(float(val))

        if not where_clauses:
            return self.get_all_videos()

        sql = f"""
            SELECT DISTINCT v.* FROM videos v
            JOIN analyses a ON v.video_id = a.video_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY v.conversion_rate DESC
        """
        rows = self._execute(sql, params).fetchall()
        return [self._row_to_video(r) for r in rows]

    def get_avg_scores_by_conversion_tier(self) -> dict:
        stats = self.get_stats_summary()
        avg = stats["avg_rate"]
        std = stats["std_dev"]
        high_min = avg + std
        low_max = avg - std

        tiers = {}
        for tier, condition in [
            ("상", f"conversion_rate >= {high_min}"),
            ("중", f"conversion_rate > {low_max} AND conversion_rate < {high_min}"),
            ("하", f"conversion_rate <= {low_max}"),
        ]:
            row = self._execute(
                f"""
                SELECT AVG(a.hook_score) as hook, AVG(a.story_score) as story,
                       AVG(a.value_score) as value, AVG(a.cta_score) as cta,
                       AVG(a.emotion_score) as emotion, AVG(a.topic_score) as topic,
                       AVG(a.diff_score) as diff, AVG(a.overall_score) as overall,
                       COUNT(DISTINCT v.video_id) as cnt
                FROM videos v
                JOIN analyses a ON v.video_id = a.video_id
                WHERE v.{condition}
                """
            ).fetchone()
            if row and row["cnt"]:
                tiers[tier] = {k: round(row[k] or 0, 2) for k in
                               ["hook", "story", "value", "cta", "emotion", "topic", "diff", "overall"]}
                tiers[tier]["count"] = row["cnt"]
        return tiers

    # ============================================================
    # 데이터 내보내기
    # ============================================================

    def export_to_csv(self, filepath: str) -> bool:
        try:
            import pandas as pd
            rows = self._execute(
                """
                SELECT v.video_id, v.title, v.url, v.conversion_rate, v.duration_seconds,
                       v.created_at,
                       a.hook_score, a.story_score, a.value_score, a.cta_score,
                       a.emotion_score, a.topic_score, a.diff_score, a.overall_score
                FROM videos v
                LEFT JOIN (
                    SELECT video_id, MAX(created_at) as max_date,
                           hook_score, story_score, value_score, cta_score,
                           emotion_score, topic_score, diff_score, overall_score
                    FROM analyses GROUP BY video_id
                ) a ON v.video_id = a.video_id
                ORDER BY v.conversion_rate DESC
                """
            ).fetchall()
            df = pd.DataFrame([dict(r) for r in rows])
            df.to_csv(filepath, index=False, encoding="utf-8-sig")
            return True
        except Exception as e:
            logger.error(f"CSV 내보내기 실패: {e}")
            return False

    def export_to_json(self, filepath: str) -> bool:
        try:
            videos = self.get_all_videos()
            data = []
            for v in videos:
                analysis = self.get_latest_analysis(v.video_id)
                entry = {
                    "video_id": v.video_id,
                    "url": v.url,
                    "title": v.title,
                    "conversion_rate": v.conversion_rate,
                    "tags": v.tags,
                    "duration_seconds": v.duration_seconds,
                }
                if analysis:
                    entry["scores"] = {
                        "hook": analysis.hook_score,
                        "story": analysis.story_score,
                        "value": analysis.value_score,
                        "cta": analysis.cta_score,
                        "emotion": analysis.emotion_score,
                        "topic": analysis.topic_score,
                        "diff": analysis.diff_score,
                        "overall": analysis.overall_score,
                    }
                data.append(entry)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"JSON 내보내기 실패: {e}")
            return False

    def backup_db(self, backup_dir: str = "data") -> str:
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"saenggak_backup_{ts}.db")
        shutil.copy2(self.db_path, dest)
        return dest

    # ============================================================
    # 내부 헬퍼
    # ============================================================

    def _row_to_video(self, row) -> VideoContent:
        d = dict(row)
        tags = json.loads(d.get("tags") or "[]")
        return VideoContent(
            url=d["url"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            tags=tags,
            transcript=d.get("transcript", ""),
            duration_seconds=d.get("duration_seconds", 0),
            conversion_rate=d.get("conversion_rate", 0.0),
            video_id=d["video_id"],
            created_at=d.get("created_at"),
        )

    def get_all_script_metrics(self) -> list[dict]:
        """모든 영상의 전환율 + script_metrics 반환 (키워드 상관관계 분석용)"""
        rows = self._execute(
            """
            SELECT v.video_id, v.title, v.conversion_rate,
                   a.script_metrics
            FROM videos v
            JOIN (
                SELECT video_id, MAX(created_at) as max_date, script_metrics
                FROM analyses GROUP BY video_id
            ) a ON v.video_id = a.video_id
            WHERE a.script_metrics IS NOT NULL AND a.script_metrics != '{}'
            ORDER BY v.conversion_rate DESC
            """
        ).fetchall()
        result = []
        for r in rows:
            sm = json.loads(r["script_metrics"] or "{}")
            if sm:
                result.append({
                    "video_id": r["video_id"],
                    "title": r["title"] or r["video_id"],
                    "conversion_rate": r["conversion_rate"],
                    "script_metrics": sm,
                })
        return result

    def _row_to_analysis(self, row) -> AnalysisResult:
        d = dict(row)
        video = self.get_video(d["video_id"]) or VideoContent(url="", video_id=d["video_id"])
        return AnalysisResult(
            video=video,
            strengths=json.loads(d.get("strengths") or "[]"),
            weaknesses=json.loads(d.get("weaknesses") or "[]"),
            key_hooks=json.loads(d.get("key_hooks") or "[]"),
            cta_analysis=d.get("cta_analysis", ""),
            topic_relevance=d.get("topic_relevance", ""),
            emotional_triggers=json.loads(d.get("emotional_triggers") or "[]"),
            hook_score=d.get("hook_score", 0.0),
            story_score=d.get("story_score", 0.0),
            value_score=d.get("value_score", 0.0),
            cta_score=d.get("cta_score", 0.0),
            emotion_score=d.get("emotion_score", 0.0),
            topic_score=d.get("topic_score", 0.0),
            diff_score=d.get("diff_score", 0.0),
            overall_score=d.get("overall_score", 0.0),
            full_analysis=d.get("full_analysis", ""),
            script_metrics=json.loads(d.get("script_metrics") or "{}"),
        )
