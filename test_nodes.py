#!/usr/bin/env python3
"""Quick test: Analyzer → Thinker → Writer."""
import yaml
from dotenv import load_dotenv; load_dotenv()

from src.research import run as run_research
from src.pipeline import analyzer_node, thinker_node, writer_node, judge_node

with open('config.yaml') as f:
    config = yaml.safe_load(f)

result = run_research(
    subjects=config['subjects'][:6],
    youtube_config=config.get('youtube', {}),
    reddit_config=config.get('reddit', {}),
    twitter_config=config.get('twitter', {}),
    searxng_config=config.get('searxng', {}),
)

parts = []
for v in result.videos[:10]:
    parts.append(f'YT [{v.source_subject}]: {v.title} ({v.views} views)')
for p in result.reddit_posts[:10]:
    parts.append(f'Reddit r/{p.subreddit} ({p.score}\u2191): {p.title}')
research = "\n".join(parts)

state = {
    'research_data': research,
    'skip_subjects': ['LLM', 'agents', 'AI coding assistants'],
    'configured_subjects': config['subjects'][:6],
    'fixes': [],
}
state.update(analyzer_node(state))
state.update(thinker_node(state))
state.update(writer_node(state))
state.update(judge_node(state))

print(f"\n=== POST ({len(state['post_raw'])} chars, approved={state['approved']}) ===")
print(state['post_raw'])
print(f"\n=== TAGS: {state['hashtags_raw']} ===")
