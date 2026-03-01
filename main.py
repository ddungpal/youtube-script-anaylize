"""
생각구독 콘텐츠 분석 에이전시 v2
메인 진입점 — 7개 모드 CLI 인터페이스

실행:
    python main.py
    python main.py --debug
"""
import argparse
import logging
import os
import sys
import uuid
from datetime import datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import print as rprint

load_dotenv()

console = Console()

# ============================================================
# 로깅 설정
# ============================================================

def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ============================================================
# 지연 임포트 (DB·에이전트는 .env 로드 후 초기화)
# ============================================================

def _get_db():
    from database.db_manager import DBManager
    db_path = os.getenv("DB_PATH", "database/saenggak.db")
    return DBManager(db_path)


# ============================================================
# 헬퍼
# ============================================================

def _check_min_data(db, required: int, feature: str) -> bool:
    stats = db.get_stats_summary()
    total = stats.get("total_videos", 0)
    if total < required:
        console.print(
            f"[yellow]⚠️  {feature}은 최소 [bold]{required}개[/bold] 영상이 필요합니다. "
            f"현재: [bold]{total}개[/bold][/yellow]"
        )
        return False
    return True


def _print_header():
    console.print(Panel(
        "[bold cyan]🧠 생각구독 콘텐츠 분석 에이전시 v2[/bold cyan]",
        subtitle="유튜브 → 유료 구독 전환 최적화",
        border_style="cyan",
    ))


def _print_menu():
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("키", style="bold yellow", width=4)
    table.add_column("메뉴", style="white")
    entries = [
        ("1", "📹 신규 분석     — 유튜브 영상 분석 + DB 저장"),
        ("2", "📊 대시보드       — 축적 데이터 전체 현황"),
        ("3", "📈 트렌드 분석    — 전환률 추이 & 패턴 분석"),
        ("4", "🔍 영상 검색      — 키워드/전환률/점수로 과거 영상 검색"),
        ("5", "💡 심화 인사이트   — 축적 데이터 기반 종합 전략"),
        ("6", "📤 데이터 내보내기 — CSV / JSON / 마크다운 아카이브"),
        ("7", "⚙️  설정          — 전환률 수정, 영상 삭제 등"),
        ("0", "종료"),
    ]
    for k, v in entries:
        table.add_row(f"[{k}]", v)
    console.print(table)


# ============================================================
# 모드 1: 신규 분석
# ============================================================

def mode_1_new_analysis(db) -> None:
    from agents.transcript_agent import TranscriptAgent
    from agents.analysis_agent import AnalysisAgent
    from agents.strategy_agent import StrategyAgent
    from agents.history_agent import HistoryAgent
    from utils.helpers import save_report
    from utils.stats import generate_score_radar_chart

    console.print("\n[bold]📹 신규 분석[/bold]")
    console.print("유튜브 링크와 구독전환률을 입력하세요. (최대 10개, 빈 줄 입력 시 종료)\n")

    inputs = []
    for i in range(1, 11):
        console.print(f"[영상 {i}]")
        url = console.input("  유튜브 링크 (빈 줄 = 종료): ").strip()
        if not url:
            break
        try:
            rate_str = console.input("  구독전환률 (%): ").strip()
            rate = float(rate_str)
        except ValueError:
            console.print("  [red]숫자를 입력하세요.[/red]")
            continue

        reanalyze = False
        ta_check = TranscriptAgent(db)
        vid_id = ta_check.extract_video_id(url)
        if vid_id and db.video_exists(vid_id):
            last_a = db.get_latest_analysis(vid_id)
            last_date = ""
            if last_a:
                video = db.get_video(vid_id)
                last_date = f" (마지막 분석: {str(video.created_at)[:10]})"
            console.print(f"  [blue]ℹ️  이미 DB에 있는 영상입니다.{last_date}[/blue]")
            ans = console.input("  재분석 하시겠습니까? (y/n): ").strip().lower()
            reanalyze = ans == "y"

        inputs.append({"url": url, "conversion_rate": rate, "reanalyze": reanalyze})
        console.print()

    if not inputs:
        console.print("[yellow]입력된 영상이 없습니다.[/yellow]")
        return

    # DB 현황 표시
    stats = db.get_stats_summary()
    if stats["total_videos"] > 0:
        console.print(
            f"[dim]📦 현재 DB: 총 {stats['total_videos']}개 영상 축적 | "
            f"평균 전환률 {stats['avg_rate']}%[/dim]\n"
        )

    # 스크립트 추출
    console.print("⏳ 스크립트 추출 중...")
    ta = TranscriptAgent(db)
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
        task = prog.add_task("스크립트 추출", total=len(inputs))
        successes, failures = ta.process_videos_batch(inputs)
        prog.advance(task, len(inputs))

    if failures:
        console.print(f"\n[yellow]⚠️  스크립트 추출 실패 영상 ({len(failures)}/{len(inputs)}개):[/yellow]")
        for f in failures:
            console.print(f"  - {f['url'][:60]} → [red]{f['reason']}[/red]")
        if successes:
            ans = console.input(f"\n나머지 {len(successes)}개 영상으로 분석을 계속 진행할까요? (y/n): ").strip().lower()
            if ans != "y":
                console.print("[yellow]분석을 중단합니다.[/yellow]")
                return
        else:
            console.print("[red]분석 가능한 영상이 없습니다.[/red]")
            return

    if not successes:
        return

    # 역사 컨텍스트
    ha = HistoryAgent(db)
    hist_ctx = ha.generate_historical_context() if stats["total_videos"] >= 5 else None

    # 개별 분석
    aa = AnalysisAgent(db)
    analyses = []
    session_id = str(uuid.uuid4())

    console.print()
    for i, video in enumerate(successes, 1):
        reanalyze_flag = next(
            (inp.get("reanalyze", False) for inp in inputs if inp["url"] == video.url),
            False,
        )
        with Progress(SpinnerColumn(), TextColumn(f"[{i}/{len(successes)}] 🔍 분석 중: {video.title[:30] or video.url[:40]}"), console=console) as prog:
            t = prog.add_task("", total=1)
            analysis = aa.analyze_single_video(video, historical_context=hist_ctx)
            db.save_analysis(analysis, session_id)
            aa.extract_and_save_patterns(analysis, reanalyze=reanalyze_flag)
            analyses.append(analysis)
            prog.advance(t, 1)
        console.print(f"  ✅ 완료 — overall: [bold]{analysis.overall_score}[/bold]/10")

    # 비교 분석 (2개 이상)
    comparison = ""
    if len(analyses) >= 2:
        console.print("\n[dim]🔄 비교 분석 중...[/dim]")
        comparison = aa.compare_videos(successes, analyses, historical_patterns=hist_ctx)

    # 벤치마크
    benchmark = []
    if stats["total_videos"] >= 5:
        console.print("[dim]📊 벤치마크 분석 중...[/dim]")
        benchmark = ha.generate_benchmark(successes)

    # 전략 수립
    sa = StrategyAgent(db)
    console.print("[dim]💡 전략 수립 중...[/dim]")
    strategy = sa.generate_strategy(analyses, comparison, hist_ctx, benchmark)

    # 리포트 저장
    report_path = save_report(analyses, strategy, comparison, benchmark)

    # 레이더 차트 (첫 번째 영상)
    if analyses and hist_ctx and hist_ctx.get("top_5_avg_scores"):
        a = analyses[0]
        score_dict = {
            "hook": a.hook_score, "story": a.story_score, "value": a.value_score,
            "cta": a.cta_score, "emotion": a.emotion_score, "topic": a.topic_score,
            "diff": a.diff_score,
        }
        chart_path = f"outputs/charts/radar_{datetime.now().strftime('%Y-%m-%d')}.png"
        generate_score_radar_chart(score_dict, hist_ctx["top_5_avg_scores"],
                                   video_label=a.video.title[:20] or "이번 영상", output_path=chart_path)

    # 세션 저장
    db.save_session({
        "session_id": session_id,
        "video_ids": [v.video_id for v in successes],
        "strategy_report": strategy.comparative_summary[:500],
        "report_path": report_path,
    })

    # 결과 출력
    console.print()
    _print_analysis_summary(analyses, benchmark)
    console.print(f"\n[green]📁 리포트 저장: {report_path}[/green]")

    # 전략 미리보기
    console.print(Panel(
        strategy.comparative_summary[:800] + ("..." if len(strategy.comparative_summary) > 800 else ""),
        title="💡 전략 요약 (일부)",
        border_style="green",
    ))


def _print_analysis_summary(analyses, benchmark):
    table = Table(title="📊 분석 결과 요약", show_lines=True)
    table.add_column("영상", style="cyan", max_width=25)
    table.add_column("전환률", justify="center")
    table.add_column("hook", justify="center")
    table.add_column("story", justify="center")
    table.add_column("value", justify="center")
    table.add_column("cta", justify="center")
    table.add_column("emotion", justify="center")
    table.add_column("topic", justify="center")
    table.add_column("diff", justify="center")
    table.add_column("overall", justify="center", style="bold")

    for a in analyses:
        title = (a.video.title or a.video.url)[:25]
        overall_color = "green" if a.overall_score >= 7 else "yellow" if a.overall_score >= 5 else "red"
        table.add_row(
            title,
            f"{a.video.conversion_rate}%",
            str(a.hook_score),
            str(a.story_score),
            str(a.value_score),
            str(a.cta_score),
            str(a.emotion_score),
            str(a.topic_score),
            str(a.diff_score),
            f"[{overall_color}]{a.overall_score}[/{overall_color}]",
        )
    console.print(table)


# ============================================================
# 모드 2: 대시보드
# ============================================================

def mode_2_dashboard(db) -> None:
    console.print("\n[bold]📊 대시보드[/bold]\n")
    stats = db.get_stats_summary()

    if stats["total_videos"] == 0:
        console.print("[yellow]아직 분석된 영상이 없습니다. 모드 1에서 영상을 분석하세요.[/yellow]")
        return

    # 전체 현황 테이블
    overview = Table(title="전체 현황", show_header=False, box=None)
    overview.add_column("항목", style="dim")
    overview.add_column("값", style="bold")
    items = [
        ("총 분석 영상 수", str(stats["total_videos"])),
        ("평균 전환률", f"{stats['avg_rate']}%"),
        ("중앙값 전환률", f"{stats['median_rate']}%"),
        ("최고 전환률", f"{stats['max_rate']}%"),
        ("최저 전환률", f"{stats['min_rate']}%"),
        ("표준편차", str(stats["std_dev"])),
        ("총 분석 세션 수", str(stats["total_sessions"])),
        ("패턴 라이브러리 크기", str(stats["total_patterns"])),
    ]
    for k, v in items:
        overview.add_row(k, v)
    console.print(overview)
    console.print()

    # TOP 5
    _print_video_table(db.get_top_videos(5), "🏆 전환률 TOP 5")
    console.print()
    _print_video_table(db.get_bottom_videos(5), "📉 전환률 BOTTOM 5")
    console.print()

    # 최근 세션
    sessions = db.get_session_history(5)
    if sessions:
        console.print("[bold]🔄 최근 분석 세션[/bold]")
        for s in sessions:
            console.print(
                f"  • {s['created_at'][:16]}  |  "
                f"{len(s['video_ids'])}개 영상  |  "
                f"리포트: {s.get('report_path', '없음')[:50]}"
            )


def _print_video_table(videos, title: str):
    table = Table(title=title, show_lines=False)
    table.add_column("#", width=3, justify="center")
    table.add_column("제목", style="cyan", max_width=30)
    table.add_column("전환률", justify="center")
    table.add_column("종합점수", justify="center")
    table.add_column("등록일", justify="center")
    for i, v in enumerate(videos, 1):
        from database.db_manager import DBManager
        analysis = None
        try:
            from database.db_manager import DBManager as _DBM
        except Exception:
            pass
        # overall score from DB
        import sqlite3
        conn = sqlite3.connect(os.getenv("DB_PATH", "database/saenggak.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT overall_score FROM analyses WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
            (v.video_id,)
        ).fetchone()
        conn.close()
        overall = row["overall_score"] if row else "-"
        table.add_row(str(i), (v.title or v.url)[:30], f"{v.conversion_rate}%",
                      str(overall), str(v.created_at)[:10] if v.created_at else "")
    console.print(table)


# ============================================================
# 모드 3: 트렌드 분석
# ============================================================

def mode_3_trend(db) -> None:
    console.print("\n[bold]📈 트렌드 분석[/bold]\n")
    if not _check_min_data(db, 8, "트렌드 분석"):
        return

    from agents.history_agent import HistoryAgent
    ha = HistoryAgent(db)

    with Progress(SpinnerColumn(), TextColumn("📈 트렌드 분석 중..."), console=console) as prog:
        t = prog.add_task("", total=1)
        trend_text = ha.analyze_trend()
        prog.advance(t, 1)

    console.print(Panel(trend_text, title="📈 트렌드 인사이트", border_style="blue"))

    with Progress(SpinnerColumn(), TextColumn("🔄 패턴 상관관계 분석 중..."), console=console) as prog:
        t = prog.add_task("", total=1)
        corr_text = ha.analyze_patterns_correlation()
        prog.advance(t, 1)

    console.print(Panel(corr_text, title="🔄 패턴 상관관계", border_style="blue"))


# ============================================================
# 모드 4: 영상 검색
# ============================================================

def mode_4_search(db) -> None:
    console.print("\n[bold]🔍 영상 검색[/bold]\n")

    console.print("검색 방법을 선택하세요:")
    console.print("  [1] 키워드 검색 (제목/스크립트/태그)")
    console.print("  [2] 전환률 범위 검색")
    console.print("  [3] 점수 기준 검색 (7개 점수 AND 조건)")
    console.print("  [4] 전체 목록 보기")

    choice = console.input("\n선택: ").strip()

    if choice == "1":
        kw = console.input("키워드: ").strip()
        results = db.search_videos(kw)
    elif choice == "2":
        try:
            min_r = float(console.input("최솟값 (%): ").strip() or "0")
            max_r = float(console.input("최댓값 (%): ").strip() or "100")
        except ValueError:
            console.print("[red]잘못된 입력입니다.[/red]")
            return
        results = db.get_videos_by_conversion_range(min_r, max_r)
    elif choice == "3":
        results = _score_search(db)
    elif choice == "4":
        results = db.get_all_videos()
    else:
        console.print("[red]잘못된 선택입니다.[/red]")
        return

    if not results:
        console.print("[yellow]검색 결과가 없습니다.[/yellow]")
        return

    console.print(f"\n[green]🔍 검색 결과 ({len(results)}건)[/green]")
    table = Table(show_lines=True)
    table.add_column("#", width=3, justify="center")
    table.add_column("제목", style="cyan", max_width=35)
    table.add_column("전환률", justify="center")
    table.add_column("종합점수", justify="center")
    table.add_column("등록일", justify="center")

    for i, v in enumerate(results, 1):
        import sqlite3
        conn = sqlite3.connect(os.getenv("DB_PATH", "database/saenggak.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT overall_score FROM analyses WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
            (v.video_id,)
        ).fetchone()
        conn.close()
        overall = row["overall_score"] if row else "-"
        table.add_row(str(i), (v.title or v.url)[:35], f"{v.conversion_rate}%",
                      str(overall), str(v.created_at)[:10] if v.created_at else "")
    console.print(table)

    # 상세 보기
    sel = console.input("\n상세 분석을 볼 영상 번호를 입력하세요 (0: 돌아가기): ").strip()
    try:
        idx = int(sel) - 1
        if 0 <= idx < len(results):
            _show_video_detail(db, results[idx])
    except ValueError:
        pass


def _score_search(db):
    console.print("\n[검색 방법 3] 점수 기준 검색 (AND 조건, 빈 줄 = 조건 없음)")
    score_prompts = [
        ("hook_score", "후킹 점수 최솟값"),
        ("story_score", "스토리 점수 최솟값"),
        ("value_score", "핵심가치 점수 최솟값"),
        ("cta_score", "CTA 점수 최솟값"),
        ("emotion_score", "감정 점수 최솟값"),
        ("topic_score", "주제적합 점수 최솟값"),
        ("diff_score", "차별화 점수 최솟값"),
        ("overall_score", "종합 점수 최솟값"),
    ]
    conditions = {}
    applied = []
    for col, label in score_prompts:
        val = console.input(f"  {label:20s} (1-10, 빈 줄=없음): ").strip()
        if val:
            try:
                conditions[col] = float(val)
                applied.append(f"{col.replace('_score', '')}≥{val}")
            except ValueError:
                pass
    if applied:
        console.print(f"\n→ 적용 조건: {', '.join(applied)} (AND)")
    return db.search_by_scores(conditions)


def _show_video_detail(db, video):
    analysis = db.get_latest_analysis(video.video_id)
    console.print(Panel(
        f"[bold]{video.title or video.url}[/bold]\n"
        f"URL: {video.url}\n"
        f"전환률: {video.conversion_rate}%\n"
        f"길이: {video.duration_seconds // 60}분 {video.duration_seconds % 60}초\n"
        + (f"\n## 최신 분석\n{analysis.full_analysis[:600]}..." if analysis else "\n분석 기록 없음"),
        title="상세 정보",
        border_style="cyan",
    ))


# ============================================================
# 모드 5: 심화 인사이트
# ============================================================

def mode_5_deep_insight(db) -> None:
    console.print("\n[bold]💡 심화 인사이트[/bold]\n")
    if not _check_min_data(db, 10, "심화 인사이트"):
        return

    from agents.history_agent import HistoryAgent
    ha = HistoryAgent(db)

    steps = [
        "📊 통계 데이터 수집 중...",
        "🔄 패턴 상관관계 분석 중...",
        "📈 트렌드 분석 중...",
        "💡 종합 인사이트 생성 중...",
    ]
    for step in steps:
        with Progress(SpinnerColumn(), TextColumn(step), console=console) as prog:
            t = prog.add_task("", total=1)
            if "트렌드" in step:
                ha.analyze_trend()
            prog.advance(t, 1)

    insight, report_path = ha.generate_deep_insight_report()
    console.print(Panel(
        insight.actionable_insights[0][:1000] if insight.actionable_insights else "(결과 없음)",
        title="💡 심화 인사이트 리포트 (일부)",
        border_style="magenta",
    ))
    console.print(f"\n[green]📁 리포트 저장: {report_path}[/green]")


# ============================================================
# 모드 6: 데이터 내보내기
# ============================================================

def mode_6_export(db) -> None:
    console.print("\n[bold]📤 데이터 내보내기[/bold]\n")
    console.print("내보내기 형식을 선택하세요:")
    console.print("  [1] CSV (스프레드시트용)")
    console.print("  [2] JSON (개발/백업용)")
    console.print("  [3] 마크다운 아카이브")

    choice = console.input("\n선택: ").strip()
    ts = datetime.now().strftime("%Y-%m-%d")

    if choice == "1":
        path = f"data/export_{ts}.csv"
        if db.export_to_csv(path):
            console.print(f"[green]📁 저장 완료: {path}[/green]")
        else:
            console.print("[red]CSV 내보내기 실패[/red]")

    elif choice == "2":
        path = f"data/export_{ts}.json"
        if db.export_to_json(path):
            console.print(f"[green]📁 저장 완료: {path}[/green]")
        else:
            console.print("[red]JSON 내보내기 실패[/red]")

    elif choice == "3":
        from utils.helpers import export_markdown_archive
        all_videos = db.get_all_videos()
        pairs = []
        for v in all_videos:
            a = db.get_latest_analysis(v.video_id)
            if a:
                pairs.append((v, a))
        if not pairs:
            console.print("[yellow]분석 데이터가 없습니다.[/yellow]")
            return
        index_path = export_markdown_archive(pairs, output_dir="data")
        console.print(f"[green]📁 인덱스 저장: {index_path}[/green]")
        console.print(f"[green]📁 영상별 분석: data/videos/ ({len(pairs)}개 파일)[/green]")
    else:
        console.print("[red]잘못된 선택입니다.[/red]")


# ============================================================
# 모드 7: 설정
# ============================================================

def mode_7_settings(db) -> None:
    console.print("\n[bold]⚙️  설정[/bold]\n")
    console.print("  [1] 전환률 수정    — 기존 영상의 전환률 업데이트")
    console.print("  [2] 영상 삭제      — DB에서 영상 제거 (패턴 cascade 처리)")
    console.print("  [3] 패턴 초기화    — 패턴 라이브러리 전체 리셋")
    console.print("  [4] DB 백업       — 데이터베이스 파일 복사")
    console.print("  [5] DB 통계       — 테이블별 레코드 수 확인")

    choice = console.input("\n선택: ").strip()

    if choice == "1":
        _settings_update_rate(db)
    elif choice == "2":
        _settings_delete_video(db)
    elif choice == "3":
        _settings_reset_patterns(db)
    elif choice == "4":
        dest = db.backup_db("data")
        console.print(f"[green]✅ 백업 완료: {dest}[/green]")
    elif choice == "5":
        _settings_db_stats(db)
    else:
        console.print("[red]잘못된 선택입니다.[/red]")


def _settings_update_rate(db):
    url = console.input("유튜브 링크 (또는 video_id): ").strip()
    from agents.transcript_agent import TranscriptAgent
    ta = TranscriptAgent(db)
    vid_id = ta.extract_video_id(url) or url
    video = db.get_video(vid_id)
    if not video:
        console.print("[red]해당 영상을 찾을 수 없습니다.[/red]")
        return
    console.print(f"현재 전환률: {video.conversion_rate}%")
    try:
        new_rate = float(console.input("새 전환률 (%): ").strip())
        if db.update_conversion_rate(vid_id, new_rate):
            console.print(f"[green]✅ 전환률 업데이트: {video.conversion_rate}% → {new_rate}%[/green]")
    except ValueError:
        console.print("[red]잘못된 입력입니다.[/red]")


def _settings_delete_video(db):
    _print_video_table(db.get_all_videos()[:20], "전체 영상 목록")
    url = console.input("\n삭제할 영상의 유튜브 링크 (또는 video_id): ").strip()
    from agents.transcript_agent import TranscriptAgent
    ta = TranscriptAgent(db)
    vid_id = ta.extract_video_id(url) or url
    video = db.get_video(vid_id)
    if not video:
        console.print("[red]해당 영상을 찾을 수 없습니다.[/red]")
        return
    confirm = console.input(
        f"[yellow]'{video.title or vid_id}' 을(를) 삭제합니까? (yes 입력 확인): [/yellow]"
    ).strip()
    if confirm.lower() == "yes":
        if db.delete_video(vid_id):
            console.print("[green]✅ 영상 및 연관 패턴 정리 완료[/green]")
    else:
        console.print("취소되었습니다.")


def _settings_reset_patterns(db):
    confirm = console.input("[red]패턴 라이브러리를 모두 삭제합니까? (yes 입력 확인): [/red]").strip()
    if confirm.lower() == "yes":
        db._execute("DELETE FROM patterns")
        db._conn.commit()
        console.print("[green]✅ 패턴 라이브러리가 초기화되었습니다.[/green]")
    else:
        console.print("취소되었습니다.")


def _settings_db_stats(db):
    import sqlite3
    conn = sqlite3.connect(os.getenv("DB_PATH", "database/saenggak.db"))
    tables = ["videos", "analyses", "patterns", "sessions", "tags_index"]
    table = Table(title="DB 통계")
    table.add_column("테이블", style="cyan")
    table.add_column("레코드 수", justify="center")
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        table.add_row(t, str(count))
    conn.close()
    console.print(table)


# ============================================================
# 메인 루프
# ============================================================

def main(debug: bool = False) -> None:
    os.makedirs("outputs/reports", exist_ok=True)
    os.makedirs("outputs/trends", exist_ok=True)
    os.makedirs("outputs/charts", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    db = _get_db()

    while True:
        console.clear()
        _print_header()
        console.print()
        _print_menu()
        console.print()

        choice = console.input("선택: ").strip()

        try:
            if choice == "1":
                mode_1_new_analysis(db)
            elif choice == "2":
                mode_2_dashboard(db)
            elif choice == "3":
                mode_3_trend(db)
            elif choice == "4":
                mode_4_search(db)
            elif choice == "5":
                mode_5_deep_insight(db)
            elif choice == "6":
                mode_6_export(db)
            elif choice == "7":
                mode_7_settings(db)
            elif choice == "0":
                console.print("\n[cyan]안녕히 가세요! 👋[/cyan]")
                db.close()
                sys.exit(0)
            else:
                console.print("[red]잘못된 선택입니다.[/red]")
        except KeyboardInterrupt:
            console.print("\n[yellow]모드를 종료합니다.[/yellow]")
        except Exception as e:
            logging.exception(e)
            console.print(f"[red]오류가 발생했습니다: {e}[/red]")

        console.input("\n[dim]Enter를 눌러 메인 메뉴로 돌아가기...[/dim]")


# ============================================================
# 진입점
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="생각구독 콘텐츠 분석 에이전시 v2")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="DEBUG 모드: API 호출/DB 쿼리 상세 로그 출력",
    )
    args = parser.parse_args()
    setup_logging(debug=args.debug)
    main(debug=args.debug)
