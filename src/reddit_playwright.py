"""
Reddit research via Playwright stealth browser — no API, no auth.
Scrapes old.reddit.com top posts from each subreddit.
"""
import time
import re
from playwright.sync_api import sync_playwright
from dataclasses import dataclass, field


@dataclass
class RedditPost:
    title: str
    url: str
    score: int = 0
    comments: int = 0
    subreddit: str = ""


def fetch_reddit_playwright(subreddits: list[str], max_per: int = 5) -> list[RedditPost]:
    """Fetch top posts from Reddit subreddits using Playwright browser."""
    posts: list[RedditPost] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = {runtime: {}};
        """)
        page = context.new_page()

        for i, sub in enumerate(subreddits):
            if i > 0:
                time.sleep(3 + (i % 3) * 2)  # gentle delay

            url = f"https://old.reddit.com/r/{sub}/top/?sort=top&t=week&limit={max_per}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)

                # Extract posts from the site table
                entries = page.locator("div.thing[data-type=link]").all()
                for entry in entries[:max_per]:
                    try:
                        title_el = entry.locator("a.title").first
                        title = (title_el.text_content() or "").strip()
                        link = title_el.get_attribute("href") or ""
                        score_str = (entry.get_attribute("data-score") or "0")
                        score = int(score_str) if score_str.lstrip("-").isdigit() else 0
                        comments_el = entry.locator("a.comments").first
                        comments_str = (comments_el.text_content() or "0").split()[0]
                        comments = int(comments_str) if comments_str.isdigit() else 0

                        if title:
                            posts.append(RedditPost(
                                title=title,
                                url=f"https://old.reddit.com{link}" if link.startswith("/") else link,
                                score=score,
                                comments=comments,
                                subreddit=sub,
                            ))
                    except Exception:
                        continue

                print(f"  r/{sub}: {min(len(entries), max_per)} posts")
            except Exception as e:
                print(f"  r/{sub}: failed — {e}")
                continue

        browser.close()

    return posts


if __name__ == "__main__":
    subreddits = ["ClaudeAI", "LocalLLaMA", "artificial", "MachineLearning",
                  "OpenAI", "opensource", "AIethics", "singularity",
                  "AIMemory", "LLMDevs", "GithubCopilot"]
    results = fetch_reddit_playwright(subreddits)
    print(f"\nTotal: {len(results)} posts")
    for p in results[:10]:
        print(f"  ({p.score}↑, {p.comments}💬) r/{p.subreddit}: {p.title[:80]}")
