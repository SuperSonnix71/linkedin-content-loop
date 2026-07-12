#!/usr/bin/env python3
"""Quick check: does post have a bold title as first line?"""

from dotenv import load_dotenv

load_dotenv()
import yaml

from src.pipeline import generate_post
from src.research import run as run_research

with open("config.yaml") as f:
    config = yaml.safe_load(f)

result = run_research(
    subjects=config["subjects"][:6],
    youtube_config=config.get("youtube", {}),
    reddit_config=config.get("reddit", {}),
    twitter_config=config.get("twitter", {}),
    searxng_config=config.get("searxng", {}),
)

post, _ = generate_post(
    result.videos[:20],
    result.reddit_posts[:20],
    result.twitter_posts[:10],
    result.news_items[:20],
    config["subjects"][:6],
    skip_subjects=["LLM", "agents"],
)

lines = post.strip().split("\n")
print(f"First 5 lines ({len(post)} chars total):")
for l in lines[:5]:
    print(f"  {l[:100]}")
