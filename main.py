#!/usr/bin/env python3
"""
LinkedIn Content Loop — automated research + posting pipeline.

Usage:
    python main.py              # Start the scheduler
    python main.py --run-now    # Run once immediately (skip scheduler)

Configuration:
    config.yaml  — subjects, tone, subreddits, schedule, etc.
    .env         — AI_BASE_URL, AI_API_KEY, AI_MODEL (secrets)
"""

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg2
import schedule
import yaml
from dotenv import load_dotenv

from src.db import (
    get_recent_subjects,
    get_selection_balance,
    log_post,
)
from src.db import initialize as db_init
from src.pipeline import generate_post as generate
from src.post import post_to_linkedin
from src.research import run as run_research

load_dotenv()


def load_config(path: str = "config.yaml") -> dict:
    """Load and validate the YAML config file."""
    config_path = Path(path)
    if not config_path.exists():
        print(f"[!] Config file not found: {config_path}")
        print("    Copy config.yaml.example or create your own config.yaml")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate required sections
    required = ["linkedin", "subjects", "content", "schedule"]
    for key in required:
        if key not in config:
            print(f"[!] Missing required config section: '{key}'")
            sys.exit(1)

    return config


def run_pipeline(config: dict, skip_subjects: list[str] | None = None, selection_mode: str = "insight", dry_run: bool = False) -> bool:
    """Execute the full pipeline: research → generate → post. Set dry_run=True to skip posting."""
    print("\n" + "=" * 60)
    print(f"  Starting pipeline at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if skip_subjects:
        print(f"      Skipping recent subjects: {skip_subjects}")

    # 1. Research
    print("\n[1/3] Researching content...")
    try:
        result = run_research(
            subjects=config["subjects"],
            youtube_config=config.get("youtube", {}),
            reddit_config=config.get("reddit", {}),
            twitter_config=config.get("twitter", {}),
            searxng_config=config.get("searxng", {}),
        )
    except Exception as e:
        print(f"[!] Research failed: {e}")
        return False

    yt_count = len(result.videos)
    rd_count = len(result.reddit_posts)
    print(f"      Found {yt_count} YouTube videos, {rd_count} Reddit posts.")
    if yt_count == 0 and rd_count == 0:
        print("[!] No content found. Skipping post.")
        return False

    # 2. Generate post
    print("\n[2/3] Generating post with AI...")
    ai_config = {
        "base_url": os.getenv("AI_BASE_URL", config.get("ai", {}).get("base_url", "http://localhost:11434/v1")),
        "api_key": os.getenv("AI_API_KEY", config.get("ai", {}).get("api_key", "ollama")),
        "model": os.getenv("AI_MODEL", config.get("ai", {}).get("model", "llama3.2")),
    }
    try:
        post_text, chosen_subject = generate(
            youtube_videos=result.videos,
            reddit_posts=result.reddit_posts,
            twitter_posts=result.twitter_posts,
            news_items=result.news_items,
            subjects=config["subjects"],
            content_config=config["content"],
            ai_config=ai_config,
            skip_subjects=skip_subjects,
            selection_mode=selection_mode,
            channel_insights=result.channel_insights,
        )
    except Exception as e:
        print(f"[!] Generation failed: {e}")
        return False

    if not post_text.strip():
        print("[!] AI returned empty post. Skipping.")
        return False

    preview = post_text[:200] + ("..." if len(post_text) > 200 else "")
    print(f"      Generated: {preview}")
    print(f"      Length: {len(post_text)} chars")

    # 3. Post to LinkedIn (skip if dry run)
    if dry_run:
        print("\n[3/3] Testing browser automation (dry run — won't post)...")
        linkedin_config = {
            "email": os.getenv("LINKEDIN_EMAIL", config.get("linkedin", {}).get("email", "")),
            "password": os.getenv("LINKEDIN_PASSWORD", config.get("linkedin", {}).get("password", "")),
            "profile_dir": config.get("linkedin", {}).get("profile_dir", "./browser-profile"),
        }
        browser_ok = post_to_linkedin(post_text, linkedin_config, dry_run=True)
        print(f"\n      Browser test: {'PASSED' if browser_ok else 'FAILED'}")
        print("\n" + "=" * 60)
        print(post_text)
        print("=" * 60)
        print("\n[+] Dry run complete. Post was NOT published.")
        return browser_ok

    print("\n[3/3] Posting to LinkedIn...")
    print("      Running headless — will pause if 2FA is needed.")
    # LinkedIn config from .env (overrides config.yaml)
    linkedin_config = {
        "email": os.getenv("LINKEDIN_EMAIL", config.get("linkedin", {}).get("email", "")),
        "password": os.getenv("LINKEDIN_PASSWORD", config.get("linkedin", {}).get("password", "")),
        "profile_dir": config.get("linkedin", {}).get("profile_dir", "./browser-profile"),
    }
    # Log attempt to DB BEFORE posting — guardrail learns even if post fails
    title = post_text.split("\n")[0].strip() if post_text else ""
    import re as _re
    tag_matches = _re.findall(r"#\w+", post_text)
    hashtags = " ".join(tag_matches) if tag_matches else ""
    log_post(subject=chosen_subject, title=title, content=post_text, hashtags=hashtags, selection_mode=selection_mode)

    try:
        success = post_to_linkedin(post_text, linkedin_config, dry_run=dry_run)
    except Exception as e:
        print(f"[!] Posting failed: {e}")
        print("\n[-] Posting failed but subject logged to DB. Won't repeat.")
        return False

    if success:
        print("\n[+] Pipeline complete — post published.")
    else:
        print("\n[-] Pipeline finished but posting may have failed. Subject logged.")

    return success


def _quota_reached(config: dict) -> bool:
    """Check daily/weekly/monthly post quotas from the database."""
    sched = config.get("schedule", {})
    per_day = sched.get("posts_per_day", 0)
    per_week = sched.get("posts_per_week", 0)
    per_month = sched.get("posts_per_month", 0)

    if not per_day and not per_week and not per_month:
        return False

    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "192.168.1.234"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER", "sonny"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            dbname=os.getenv("DB_NAME", "linkedin_loop"),
        )
        cur = conn.cursor()

        if per_day:
            cur.execute(
                "SELECT COUNT(*) FROM posts WHERE posted = TRUE AND created_at::date = CURRENT_DATE"
            )
            today_count = cur.fetchone()[0]
            if today_count >= per_day:
                print(f"      ⏭  Daily quota reached ({today_count}/{per_day}). Skipping.")
                cur.close()
                conn.close()
                return True

        if per_week:
            cur.execute(
                "SELECT COUNT(*) FROM posts WHERE posted = TRUE AND created_at >= date_trunc('week', CURRENT_DATE)"
            )
            week_count = cur.fetchone()[0]
            if week_count >= per_week:
                print(f"      ⏭  Weekly quota reached ({week_count}/{per_week}). Skipping.")
                cur.close()
                conn.close()
                return True

        if per_month:
            cur.execute(
                "SELECT COUNT(*) FROM posts WHERE posted = TRUE AND created_at >= date_trunc('month', CURRENT_DATE)"
            )
            month_count = cur.fetchone()[0]
            if month_count >= per_month:
                print(f"      ⏭  Monthly quota reached ({month_count}/{per_month}). Skipping.")
                cur.close()
                conn.close()
                return True

        cur.close()
    except Exception as e:
        print(f"      ⚠  Quota check failed (DB unreachable?): {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return False


def _quota_job(config: dict) -> None:
    """Job wrapper: check quota, check dedup, balance selection mode, run pipeline, log to DB."""
    if _quota_reached(config):
        return

    recent = get_recent_subjects()
    if recent:
        print(f"      Recent subjects (to avoid): {recent}")

    # Auto-balance selection mode: env var takes priority, else auto-balance
    mode = os.getenv("SUBJECT_SELECTION") or get_selection_balance()
    print(f"      Selection mode: {mode}")

    run_pipeline(config, skip_subjects=recent, selection_mode=mode)
    # run_pipeline handles DB logging internally


def start_scheduler(config: dict) -> None:
    """Set up the schedule and run the pipeline with quota checks."""
    post_times = config["schedule"].get("post_times", ["09:00"])
    days = config["schedule"].get("days", ["monday", "tuesday", "wednesday", "thursday", "friday"])
    per_day = config["schedule"].get("posts_per_day", "unlimited")
    per_week = config["schedule"].get("posts_per_week", "unlimited")
    per_month = config["schedule"].get("posts_per_month", "unlimited")

    day_map = {
        "monday": schedule.every().monday,
        "tuesday": schedule.every().tuesday,
        "wednesday": schedule.every().wednesday,
        "thursday": schedule.every().thursday,
        "friday": schedule.every().friday,
        "saturday": schedule.every().saturday,
        "sunday": schedule.every().sunday,
    }

    for day in days:
        day_schedule = day_map.get(day.lower())
        if day_schedule is None:
            print(f"[!] Unknown day: {day}")
            continue
        for t in post_times:
            day_schedule.at(t).do(lambda c=config: _quota_job(c))
            print(f"[*] Scheduled: {day.title()} at {t}")

    print(f"\n[*] Quotas: {per_day}/day, {per_week}/week, {per_month}/month")
    tz = config["schedule"].get("timezone", "UTC")
    print(f"[*] Timezone: {tz}")
    print("[*] Scheduler running. Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn Content Loop")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the pipeline once immediately instead of starting the scheduler.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test the full pipeline including browser automation but does NOT post. Shows the generated post.",
    )
    parser.add_argument(
        "--test-post",
        action="store_true",
        help="Like --test but also clicks Post to verify the button works. Post WILL be published.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # Initialize database (auto-creates DB + tables if needed)
    db_init()

    if args.run_now or args.test or args.test_post:
        recent = get_recent_subjects()
        if recent:
            print(f"      Recent subjects (to avoid): {recent}")
        mode = os.getenv("SUBJECT_SELECTION") or get_selection_balance()
        print(f"      Selection mode: {mode}")
        dry = bool(args.test)  # --test: dry run, --test-post: actual post
        success = run_pipeline(config, skip_subjects=recent, selection_mode=mode, dry_run=dry)
        sys.exit(0 if success else 1)
    else:
        print("[*] Starting LinkedIn Content Loop scheduler...")
        print("    Posts will be created at the times defined in config.yaml")
        print("    Use --run-now to test immediately.\n")
        start_scheduler(config)


if __name__ == "__main__":
    main()
