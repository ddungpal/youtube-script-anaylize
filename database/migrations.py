"""
DB 스키마 마이그레이션
- 앱 시작 시 db_manager에서 호출하여 테이블을 자동 생성한다.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT UNIQUE NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    tags            TEXT DEFAULT '[]',
    transcript      TEXT DEFAULT '',
    duration_seconds INTEGER DEFAULT 0,
    conversion_rate FLOAT NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id          TEXT NOT NULL,
    session_id        TEXT NOT NULL,
    strengths         TEXT DEFAULT '[]',
    weaknesses        TEXT DEFAULT '[]',
    key_hooks         TEXT DEFAULT '[]',
    cta_analysis      TEXT DEFAULT '',
    topic_relevance   TEXT DEFAULT '',
    emotional_triggers TEXT DEFAULT '[]',
    hook_score        FLOAT DEFAULT 0,
    story_score       FLOAT DEFAULT 0,
    value_score       FLOAT DEFAULT 0,
    cta_score         FLOAT DEFAULT 0,
    emotion_score     FLOAT DEFAULT 0,
    topic_score       FLOAT DEFAULT 0,
    diff_score        FLOAT DEFAULT 0,
    overall_score     FLOAT DEFAULT 0,
    full_analysis     TEXT DEFAULT '',
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE IF NOT EXISTS patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type    TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT NOT NULL,
    frequency       INTEGER DEFAULT 1,
    avg_conversion  FLOAT DEFAULT 0,
    example_videos  TEXT DEFAULT '[]',
    first_seen      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT UNIQUE NOT NULL,
    video_ids       TEXT NOT NULL,
    strategy_report TEXT DEFAULT '',
    report_path     TEXT DEFAULT '',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    tag         TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE INDEX IF NOT EXISTS idx_tags ON tags_index(tag);
CREATE INDEX IF NOT EXISTS idx_analyses_video ON analyses(video_id);
CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(pattern_type);
"""


def run_migrations(conn) -> None:
    """테이블 및 인덱스 생성 + 스키마 마이그레이션"""
    conn.executescript(SCHEMA_SQL)
    # 기존 DB에 신규 컬럼 추가 (이미 있으면 무시)
    try:
        conn.execute("ALTER TABLE analyses ADD COLUMN script_metrics TEXT DEFAULT '{}'")
    except Exception:
        pass
    conn.commit()
