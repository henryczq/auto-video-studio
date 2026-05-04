"""Database connection, initialization, and migration infrastructure."""

import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def ensure_data_dir():
    """Ensure data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Get a fresh database connection for the current unit of work."""
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_cursor():
    """Get database cursor with automatic commit/rollback."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def init_db():
    """Initialize database schema."""
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                name TEXT,
                video_filename TEXT,
                source_video TEXT,
                source_start TEXT,
                source_end TEXT,
                processed_video TEXT,
                captions_initial TEXT,
                captions_initial_json TEXT,
                captions_edited TEXT,
                captions_final TEXT,
                captions_cut_marks TEXT,
                video_trimmed TEXT,
                captions_trimmed_json TEXT,
                captions_trimmed TEXT,
                optimized_audio TEXT,
                video_audio_optimized TEXT,
                final_subtitles_video TEXT,
                tts_segments_json TEXT,
                voiceover TEXT,
                final_replace_audio TEXT,
                final_subtitles_only TEXT,
                captions_version INTEGER DEFAULT 0,
                trim_version INTEGER DEFAULT 0,
                tts_version INTEGER DEFAULT 0,
                compose_version INTEGER DEFAULT 0,
                process_error TEXT,
                tts_error TEXT,
                trim_error TEXT,
                compose_error TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS social_accounts (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                account TEXT NOT NULL,
                label TEXT,
                last_check_status TEXT,
                last_check_at TEXT,
                last_error TEXT,
                cookie_path TEXT,
                profile_dir TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS upload_records (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                platform TEXT NOT NULL,
                account_id TEXT,
                title TEXT,
                desc TEXT,
                tags TEXT,
                video_path TEXT,
                success INTEGER DEFAULT 0,
                status TEXT,
                url TEXT,
                error TEXT,
                output TEXT,
                log_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_upload_records_job_created ON upload_records(job_id, created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_upload_records_platform_created ON upload_records(platform, created_at DESC)")


def run_migrations():
    """Run pending migrations."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        current_version = row["version"] if row else 0

        migrations = [
            (1, "initial_schema"),
            (2, "add_social_accounts_and_upload_records"),
            (3, "add_version_columns_to_jobs"),
            (4, "add_source_video_columns_to_jobs"),
            (5, "add_query_indexes"),
        ]

        for version, name in migrations:
            if version > current_version:
                logger.info(f"Running migration {version}: {name}")
                try:
                    if version == 3:
                        for column in (
                            "captions_version",
                            "trim_version",
                            "tts_version",
                            "compose_version",
                        ):
                            if not _column_exists(cursor, "jobs", column):
                                cursor.execute(
                                    f"ALTER TABLE jobs ADD COLUMN {column} INTEGER DEFAULT 0"
                                )
                    elif version == 4:
                        for column in (
                            ("source_video", "TEXT"),
                            ("source_start", "TEXT"),
                            ("source_end", "TEXT"),
                        ):
                            if not _column_exists(cursor, "jobs", column[0]):
                                cursor.execute(
                                    f"ALTER TABLE jobs ADD COLUMN {column[0]} {column[1]}"
                                )
                    elif version == 5:
                        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)")
                        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
                        cursor.execute("CREATE INDEX IF NOT EXISTS idx_upload_records_job_created ON upload_records(job_id, created_at DESC)")
                        cursor.execute("CREATE INDEX IF NOT EXISTS idx_upload_records_platform_created ON upload_records(platform, created_at DESC)")
                    cursor.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                        (version,),
                    )
                    conn.commit()
                    logger.info(f"Migration {version} completed")
                except Exception as e:
                    logger.error(f"Migration {version} failed: {e}")
                    conn.rollback()
                    raise
    finally:
        cursor.close()
        conn.close()


def close_connection():
    """No-op for compatibility; connections are short-lived."""
    return None
