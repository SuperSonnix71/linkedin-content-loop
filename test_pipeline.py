#!/usr/bin/env python3
"""
Test pipeline: runs research + generation WITHOUT posting to LinkedIn.

Reads configuration from:
  - config.yaml  — subjects, tone, style, subreddits, schedule, etc.
  - .env         — AI_BASE_URL, AI_API_KEY, AI_MODEL (secrets)

Usage:
    python test_pipeline.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from dotenv import load_dotenv

from src.generate import generate
from src.research import run as run_research

# Load .env
load_dotenv()

# Load config.yaml
config_path = Path(__file__).resolve().parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# Build AI config from .env (overrides config.yaml ai section)
ai_config = {
    "base_url": os.getenv("AI_BASE_URL", config.get("ai", {}).get("base_url", "http://localhost:11434/v1")),
    "api_key": os.getenv("AI_API_KEY", config.get("ai", {}).get("api_key", "ollama")),
    "model": os.getenv("AI_MODEL", config.get("ai", {}).get("model", "llama3.2")),
}


def hr(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def main() -> int:
    hr("LINKEDIN CONTENT LOOP — PIPE TEST")
    print(f"  Model: {ai_config['model']}")
    print(f"  Server: {ai_config['base_url']}")
    print(f"  Subjects: {config['subjects']}")
    print(f"  Reddit: {config.get('reddit', {}).get('subreddits', [])}")

    fail_count = 0

    def fail(msg: str) -> None:
        nonlocal fail_count
        fail_count += 1
        print(f"  ✗  {msg}")

    # ── 1. Research ───────────────────────────────────────────────────

    hr("1/3 RESEARCH")
    try:
        result = run_research(
            subjects=config["subjects"],
            youtube_config=config.get("youtube", {}),
            reddit_config=config.get("reddit", {}),
            twitter_config=config.get("twitter", {}),
            searxng_config=config.get("searxng", {}),
        )
    except Exception as e:
        fail(f"Research raised exception: {e}")
        return 1

    yt = result.videos
    rd = result.reddit_posts
    tw = result.twitter_posts
    nw = result.news_items
    print(f"  YouTube:   {len(yt)} videos")
    for v in yt[:5]:
        print(f"    - {v.title[:80]} ({v.views:,} views)")
    print(f"  Reddit:    {len(rd)} posts")
    for p in rd[:5]:
        print(f"    - r/{p.subreddit}: {p.title[:80]} ({p.score}↑)")
    print(f"  Twitter/X: {len(tw)} posts")
    for t in tw[:3]:
        print(f"    - @{t.author}: {t.text[:80]}...")
    print(f"  Web news:  {len(nw)} articles")

    if yt:
        print(f"  ✓  YouTube returned {len(yt)} videos")
        # Show per-subject breakdown
        from collections import defaultdict
        subj_views = defaultdict(int)
        for v in yt:
            s = getattr(v, "source_subject", "?")
            subj_views[s] += v.views
        for s, views in sorted(subj_views.items(), key=lambda x: x[1], reverse=True):
            print(f"      {s}: {views:,} views")
    else:
        print("  ⚠  YouTube returned 0 videos")

    if rd:
        print(f"  ✓  Reddit returned {len(rd)} posts")
    else:
        print("  ⚠  Reddit returned 0 posts")

    # ── 2. Generation ─────────────────────────────────────────────────

    hr("2/3 GENERATION")
    try:
        start = time.time()
        post, _chosen = generate(
            youtube_videos=yt,
            reddit_posts=rd,
            twitter_posts=tw,
            news_items=nw,
            subjects=config["subjects"],
            content_config=config.get("content", {}),
            ai_config=ai_config,
            selection_mode="insight",
        )
        elapsed = time.time() - start
        print(f"  Generated in {elapsed:.1f}s")
    except Exception as e:
        fail(f"Generation failed: {e}")
        return 1

    # ── 3. Validate ───────────────────────────────────────────────────

    hr("3/3 VALIDATION")
    checks = 0

    if not post or not post.strip():
        fail("Post is empty")
        return 1
    checks += 1
    print("  ✓  Post is non-empty")

    if 100 <= len(post) <= 2500:
        checks += 1
        print(f"  ✓  Post length is reasonable ({len(post)} chars)")
    else:
        fail(f"Post length out of range ({len(post)} chars)")

    if "#" in post:
        checks += 1
        print("  ✓  Post includes hashtags")
    else:
        print("  ⚠  No hashtags found")

    for bp in ["Here's a post", "POST INSTRUCTIONS", "RESEARCH —", "Phase 1"]:
        if bp.lower() in post.lower():
            fail(f"Post contains prompt artifact: '{bp}'")
            break
    else:
        checks += 1
        print("  ✓  No prompt artifacts found")

    # ── 4. Display ────────────────────────────────────────────────────

    hr("FINAL POST")
    print(post)

    hr("RESULT")
    print(f"  {checks}/4 checks passed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
