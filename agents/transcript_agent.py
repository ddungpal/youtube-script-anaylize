"""
스크립트 추출 에이전트
- youtube-transcript-api로 자막을 추출한다.
- 실패하면 yt-dlp 자막 다운로드(수동+자동생성)로 폴백한다.
- DB에 이미 존재하는 영상은 중복 추출을 방지한다.
- reanalyze=True 시 기존 캐시를 재사용한다.
"""
import os
import re
import tempfile
import logging
from typing import Optional

from models.content import VideoContent
from database.db_manager import DBManager

logger = logging.getLogger(__name__)


class TranscriptAgent:
    def __init__(self, db: DBManager):
        self.db = db

    # ----------------------------------------------------------
    # 공개 메서드
    # ----------------------------------------------------------

    def process_videos_batch(
        self, inputs: list[dict], reanalyze: bool = False
    ) -> tuple[list[VideoContent], list[dict]]:
        """
        여러 영상을 처리한다.
        inputs: [{"url": ..., "conversion_rate": ..., "reanalyze": bool}, ...]

        반환: (성공한 VideoContent 리스트, 실패 정보 리스트)
        실패 정보: [{"url": ..., "reason": ...}, ...]
        """
        successes: list[VideoContent] = []
        failures: list[dict] = []

        for item in inputs:
            url = item["url"]
            rate = item["conversion_rate"]
            should_reanalyze = item.get("reanalyze", reanalyze)
            try:
                video = self.process_video(url, rate, reanalyze=should_reanalyze)
                successes.append(video)
            except Exception as e:
                reason = self._friendly_error(str(e))
                logger.debug(f"추출 실패 [{url}]: {e}")
                failures.append({"url": url, "reason": reason})

        return successes, failures

    def process_video(
        self, url: str, conversion_rate: float, reanalyze: bool = False
    ) -> VideoContent:
        """
        단일 영상을 처리한다.
        - DB에 이미 있으면 스크립트 추출을 건너뛴다.
        - reanalyze=True 이면 기존 캐시를 사용하되 전환률만 갱신한다.
        """
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError("유효하지 않은 유튜브 URL입니다.")

        if self.db.video_exists(video_id):
            if reanalyze:
                logger.debug(f"재분석 모드: DB 캐시 사용 [{video_id}]")
            else:
                logger.debug(f"DB 캐시 사용 [{video_id}]")
            video = self.db.get_video(video_id)
            if video.conversion_rate != conversion_rate:
                self.db.update_conversion_rate(video_id, conversion_rate)
                video.conversion_rate = conversion_rate
            return video

        # 신규 영상 처리
        video = self._extract_new_video(url, video_id, conversion_rate)
        self.db.save_video(video)
        return video

    def extract_video_id(self, url: str) -> Optional[str]:
        """URL에서 video_id를 추출한다."""
        patterns = [
            r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})",
            r"(?:embed/)([A-Za-z0-9_-]{11})",
            r"(?:shorts/)([A-Za-z0-9_-]{11})",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    # ----------------------------------------------------------
    # 내부 메서드
    # ----------------------------------------------------------

    def _extract_new_video(self, url: str, video_id: str, conversion_rate: float) -> VideoContent:
        meta = self._extract_metadata(url)
        transcript = self._extract_transcript(video_id)
        return VideoContent(
            url=url,
            video_id=video_id,
            title=meta.get("title", ""),
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            duration_seconds=meta.get("duration", 0),
            transcript=transcript,
            conversion_rate=conversion_rate,
        )

    def _extract_metadata(self, url: str) -> dict:
        """yt-dlp Python 모듈로 메타데이터를 추출한다."""
        try:
            import yt_dlp  # noqa: PLC0415
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            logger.debug(f"메타데이터 추출 완료: {info.get('title', '')[:50]}")
            return {
                "title": info.get("title", ""),
                "description": info.get("description", ""),
                "tags": info.get("tags") or [],
                "duration": info.get("duration", 0),
            }
        except Exception as e:
            logger.debug(f"메타데이터 추출 실패 (무시): {e}")
            return {"title": "", "description": "", "tags": [], "duration": 0}

    def _extract_transcript(self, video_id: str) -> str:
        """youtube-transcript-api v1.x API로 자막을 추출한다."""
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: PLC0415

        api = YouTubeTranscriptApi()

        # 1단계: 한국어/영어 직접 요청
        for langs in [["ko", "ko-KR"], ["en"]]:
            try:
                result = api.fetch(video_id, languages=langs)
                text = " ".join(s.text for s in result)
                logger.debug(f"자막 추출 완료: {len(text)}자 [{video_id}]")
                return self._truncate_transcript(text)
            except Exception:
                continue

        # 2단계: 전체 자막 목록 순회 (언어 무관, 있는 자막 모두 시도)
        try:
            tlist = api.list(video_id)
            for transcript in tlist:
                try:
                    result = transcript.fetch()
                    text = " ".join(s.text for s in result)
                    if text.strip():
                        logger.debug(f"자막 추출 완료 (언어:{transcript.language_code}): {len(text)}자 [{video_id}]")
                        return self._truncate_transcript(text)
                except Exception:
                    continue
        except Exception:
            pass

        # 3단계: yt-dlp 자막 다운로드 폴백 (수동 + 자동생성)
        logger.debug(f"youtube-transcript-api 실패 — yt-dlp 자막 시도 [{video_id}]")
        return self._extract_via_ytdlp_subs(video_id)

    def _extract_via_ytdlp_subs(self, video_id: str) -> str:
        """yt-dlp로 수동/자동생성 자막 파일을 다운로드해 텍스트를 추출한다.
        subtitlesformat 미지정 → YouTube 기본 형식 사용 (ffmpeg 불필요).
        """
        import yt_dlp  # noqa: PLC0415

        url = f"https://www.youtube.com/watch?v={video_id}"
        _SUB_EXTS = (".vtt", ".json3", ".srv3", ".srv2", ".srv1", ".ttml", ".xml")

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["ko", "ko-KR", "en", "en-US", "en-orig"],
                # subtitlesformat 생략 → ffmpeg 없이도 YouTube 기본 형식 다운로드
                "skip_download": True,
                "outtmpl": os.path.join(tmpdir, "%(id)s"),
                "noplaylist": True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            except Exception as e:
                raise RuntimeError(f"자막 다운로드 실패: {e}")

            sub_files = [f for f in os.listdir(tmpdir) if any(f.endswith(ext) for ext in _SUB_EXTS)]
            if not sub_files:
                raise RuntimeError("자막을 가져올 수 없습니다.")

            # 한국어 파일 우선, 없으면 첫 번째 파일 사용
            sub_files.sort(key=lambda f: (0 if ".ko" in f else 1, f))
            fname = sub_files[0]
            with open(os.path.join(tmpdir, fname), "r", encoding="utf-8") as f:
                content = f.read()

        if fname.endswith(".vtt"):
            text = self._parse_vtt(content)
        elif fname.endswith(".json3"):
            text = self._parse_json3(content)
        else:
            text = self._parse_xml_sub(content)

        if not text:
            raise RuntimeError("자막 파일이 비어 있습니다.")

        logger.debug(f"yt-dlp 자막 추출 완료: {len(text)}자 [{video_id}]")
        return self._truncate_transcript(text)

    @staticmethod
    def _parse_json3(json_content: str) -> str:
        """json3 형식 자막에서 텍스트만 추출한다."""
        import json  # noqa: PLC0415
        data = json.loads(json_content)
        lines = []
        for event in data.get("events", []):
            for seg in event.get("segs", []):
                t = seg.get("utf8", "").strip()
                if t and t != "\n":
                    lines.append(t)
        deduped = []
        prev = None
        for line in lines:
            if line != prev:
                deduped.append(line)
                prev = line
        return " ".join(deduped)

    @staticmethod
    def _parse_xml_sub(xml_content: str) -> str:
        """srv1/srv2/srv3/ttml 형식 자막에서 텍스트만 추출한다."""
        text = re.sub(r"<[^>]+>", " ", xml_content)
        text = (text
                .replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"')
                .replace("&#39;", "'"))
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _parse_vtt(vtt: str) -> str:
        """VTT 자막 파일에서 텍스트만 추출하고 연속 중복 줄을 제거한다."""
        lines = []
        for line in vtt.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
                continue
            if "-->" in line:
                continue
            if re.match(r"^\d+$", line):
                continue
            # <c>, <00:00:00.000> 등 HTML/타임스탬프 태그 제거
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line:
                lines.append(line)

        # VTT는 동일 자막이 여러 cue에 중복되므로 연속 중복 제거
        deduped = []
        prev = None
        for line in lines:
            if line != prev:
                deduped.append(line)
                prev = line
        return " ".join(deduped)

    def _truncate_transcript(self, text: str, max_chars: int = 15000) -> str:
        """스크립트가 너무 길면 앞/중/뒤를 각 5000자씩 추출한다."""
        if len(text) <= max_chars:
            return text
        chunk = max_chars // 3
        head = text[:chunk]
        mid_start = (len(text) - chunk) // 2
        middle = text[mid_start: mid_start + chunk]
        tail = text[-chunk:]
        return f"{head}\n\n[...중간 생략...]\n\n{middle}\n\n[...중간 생략...]\n\n{tail}"

    @staticmethod
    def _friendly_error(msg: str) -> str:
        msg_lower = msg.lower()
        if "자막 다운로드 실패" in msg:
            return "자막 다운로드 실패"
        if "transcript" in msg_lower or "subtitle" in msg_lower or "자막" in msg:
            return "자막 없음"
        if "private" in msg_lower or "비공개" in msg:
            return "비공개 영상"
        if "unavailable" in msg_lower or "removed" in msg_lower:
            return "삭제된 영상"
        if "invalid" in msg_lower or "url" in msg_lower:
            return "잘못된 URL"
        return "추출 실패"
