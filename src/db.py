"""
Database layer: auto-creates DB + tables on first run.
Tracks posts, subjects, and content to avoid repeats.
"""

import os
from datetime import datetime, timedelta

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor


def _get_config() -> dict:
    """Read DB config from environment variables."""
    return {
        "host": os.getenv("DB_HOST", "192.168.1.234"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "user": os.getenv("DB_USER", "sonny"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
        "dbname": os.getenv("DB_NAME", "linkedin_loop"),
    }


def _connect(dbname_override: str | None = None) -> "psycopg2.connection":
    """Connect to Postgres. If dbname_override is None, connects to target DB."""
    cfg = _get_config()
    if dbname_override:
        cfg["dbname"] = dbname_override
    return psycopg2.connect(**cfg)


def initialize() -> None:
    """Create database and tables if they don't exist. Safe to call on every startup."""
    cfg = _get_config()
    target_db = cfg["dbname"]

    # Step 1: connect to 'postgres' to check/create the target database
    try:
        conn = _connect(dbname_override="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target_db,)
        )
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db))
            )
            print(f"[DB] Created database '{target_db}'")
        cur.close()
        conn.close()
    except psycopg2.OperationalError as e:
        print(f"[DB] Warning: could not create database: {e}")
        return

    # Step 2: connect to target DB and create tables
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW(),
                subject TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                hashtags TEXT,
                char_count INTEGER,
                selection_mode TEXT DEFAULT 'insight',
                posted BOOLEAN DEFAULT FALSE
            )
        """)
        try:
            cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS selection_mode TEXT DEFAULT 'insight'")
        except Exception:
            pass
        conn.commit()
        cur.close()
        print(f"[DB] Connected to '{target_db}', table 'posts' ready")
    except psycopg2.OperationalError as e:
        print(f"[DB] Warning: could not connect to '{target_db}': {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def log_post(subject: str, title: str = "", content: str = "", hashtags: str = "", selection_mode: str = "insight") -> None:
    """Record a posted LinkedIn post."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO posts (subject, title, content, hashtags, char_count, selection_mode, posted)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (subject, title, content, hashtags, len(content), selection_mode, True),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[DB] Failed to log post: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_recent_subjects(days: int = 7) -> list[str]:
    """Get subjects posted in the last N days to avoid repeats."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cutoff = datetime.now() - timedelta(days=days)
        cur.execute(
            "SELECT DISTINCT subject FROM posts WHERE created_at >= %s AND posted = TRUE",
            (cutoff,),
        )
        subjects = [row["subject"] for row in cur.fetchall()]
        cur.close()
        return subjects
    except Exception as e:
        print(f"[DB] Failed to query recent subjects: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_recent_posts(limit: int = 5) -> list[dict]:
    """Get the most recent posts for context (what was already written about)."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT subject, title, content, created_at FROM posts WHERE posted = TRUE ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        posts = [dict(row) for row in cur.fetchall()]
        cur.close()
        return posts
    except Exception as e:
        print(f"[DB] Failed to query recent posts: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_selection_balance(days: int = 7) -> str:
    """Check recent post mode distribution. Returns the mode that needs more posts to balance."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cutoff = datetime.now() - timedelta(days=days)
        cur.execute(
            "SELECT selection_mode, COUNT(*) as cnt FROM posts WHERE created_at >= %s AND posted = TRUE GROUP BY selection_mode",
            (cutoff,),
        )
        rows = {r["selection_mode"]: r["cnt"] for r in cur.fetchall()}
        cur.close()
        # Bias toward insight: 2 insight posts per 1 volume post
        if rows.get("insight", 0) >= rows.get("volume", 0) * 2:
            return "volume"
        return "insight"
    except Exception:
        return "insight"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
