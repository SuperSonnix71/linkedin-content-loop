"""
Content research: fetches trending/engaged content from YouTube (via yt-dlp)
and Reddit (via public JSON API). No API keys required.
"""

import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class VideoItem:
    title: str
    url: str
    channel: str
    views: int
    duration: int | None = None
    description: str = ""
    source_subject: str = ""

    def summary(self) -> str:
        return (
            f"YouTube: \"{self.title}\" by {self.channel} "
            f"({self.views:,} views) — {self.url}"
        )


@dataclass
class RedditItem:
    title: str
    url: str
    subreddit: str
    score: int
    num_comments: int
    selftext: str = ""

    def summary(self) -> str:
        return (
            f"Reddit r/{self.subreddit}: \"{self.title}\" "
            f"({self.score} upvotes, {self.num_comments} comments) — {self.url}"
        )


@dataclass
class NewsItem:
    title: str
    url: str
    snippet: str
    source_subject: str = ""

    def summary(self) -> str:
        return (
            f"Web [{self.source_subject}]: \"{self.title}\" — {self.snippet[:200]}... "
            f"({self.url})"
        )


@dataclass
class TwitterItem:
    text: str
    url: str
    author: str
    likes: int
    retweets: int

    def summary(self) -> str:
        return (
            f"X/Twitter: @{self.author}: \"{self.text[:120]}...\" "
            f"({self.likes} likes, {self.retweets} RT) — {self.url}"
        )


@dataclass
class ResearchResult:
    videos: list[VideoItem] = field(default_factory=list)
    reddit_posts: list[RedditItem] = field(default_factory=list)
    twitter_posts: list[TwitterItem] = field(default_factory=list)
    news_items: list[NewsItem] = field(default_factory=list)
    channel_insights: list[dict] = field(default_factory=list)


def _search_youtube(query: str, max_results: int) -> list[VideoItem]:
    """Search YouTube via yt-dlp. No API key required."""
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                f"ytsearch{max_results}:{query}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("[!] yt-dlp not found. Install it: pip install yt-dlp")
        return []
    except subprocess.TimeoutExpired:
        print(f"[!] yt-dlp search timed out for query: {query}")
        return []

    if result.returncode != 0:
        print(f"[!] yt-dlp error: {result.stderr.strip()}")
        return []

    videos: list[VideoItem] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = data.get("id", "")
        if not video_id:
            continue

        videos.append(
            VideoItem(
                title=data.get("title", "Untitled"),
                url=f"https://www.youtube.com/watch?v={video_id}",
                channel=data.get("channel") or data.get("uploader", "Unknown"),
                views=data.get("view_count") or 0,
                duration=data.get("duration"),
                description=(data.get("description") or "")[:500],
                source_subject=query,
            )
        )

    return videos


def _fetch_youtube_channels(
    channel_urls: list[str], max_per_channel: int
) -> list[VideoItem]:
    """Pull recent videos from specific YouTube channels."""
    all_videos: list[VideoItem] = []
    for url in channel_urls:
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--flat-playlist",
                    "--dump-json",
                    "--no-warnings",
                    "--playlist-end",
                    str(max_per_channel),
                    f"{url}/videos",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            vid_id = data.get("id", "")
            if not vid_id:
                continue
            all_videos.append(
                VideoItem(
                    title=data.get("title", "Untitled"),
                    url=f"https://www.youtube.com/watch?v={vid_id}",
                    channel=data.get("channel") or data.get("uploader", "Unknown"),
                    views=data.get("view_count") or 0,
                    description=(data.get("description") or "")[:500],
                    source_subject=url,  # track which channel this came from
                )
            )
    return all_videos


def _fetch_reddit(subreddits: list[str], max_per: int) -> list[RedditItem]:
    """Fetch top posts from Reddit via Playwright browser."""
    import time
    from playwright.sync_api import sync_playwright

    posts: list[RedditItem] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
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
                time.sleep(3 + (i % 3) * 2)
            url = f"https://old.reddit.com/r/{sub}/top/?sort=top&t=week&limit={max_per}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                entries = page.locator("div.thing[data-type=link]").all()
                for entry in entries[:max_per]:
                    try:
                        title_el = entry.locator("a.title").first
                        title = (title_el.text_content() or "").strip()
                        link = title_el.get_attribute("href") or ""
                        score_str = (entry.get_attribute("data-score") or "0")
                        score = int(score_str) if score_str.lstrip("-").isdigit() else 0
                        if title:
                            posts.append(RedditItem(
                                title=title,
                                url=f"https://old.reddit.com{link}" if link.startswith("/") else link,
                                subreddit=sub, score=score, num_comments=0,
                            ))
                    except Exception:
                        continue
                print(f"      r/{sub}: {min(len(entries), max_per)} posts")
            except Exception as e:
                print(f"[!] Reddit fetch failed for r/{sub}: {e}")
                continue
        browser.close()
    return posts
def _scrape_twitter(accounts: list[str], max_per: int) -> list[TwitterItem]:
    """Fetch recent tweets via Nitter RSS feeds. No API key, no browser."""
    import time
    import urllib.request
    import xml.etree.ElementTree as ET

    items: list[TwitterItem] = []

    for i, account in enumerate(accounts):
        if i > 0:
            time.sleep(1)

        url = f"https://nitter.net/{account}/rss"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8")
        except Exception as e:
            print(f"[!] Twitter fetch failed for @{account}: {e}")
            continue

        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            print(f"[!] Twitter RSS parse error for @{account}: {e}")
            continue

        count = 0
        for item in root.findall(".//item"):
            if count >= max_per:
                break
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")

            title = title_el.text if title_el is not None else ""
            link = link_el.text if link_el is not None else ""
            desc = desc_el.text if desc_el is not None else ""

            # Nitter RSS titles sometimes start with "R to @user:" for replies — skip those
            if title.startswith("R to @"):
                continue

            # Clean description HTML
            import re
            clean = re.sub(r"<[^>]+>", "", desc).strip()
            text = clean if clean else title

            if len(text) > 10:
                items.append(
                    TwitterItem(
                        text=text[:500],
                        url=link if link else f"https://x.com/{account}",
                        author=account,
                        likes=0,
                        retweets=0,
                    )
                )
                count += 1

    return items


def _search_searxng(
    subjects: list[str], max_per: int, base_url: str
) -> list[NewsItem]:
    """Search web via SearXNG for each subject. No API key required."""
    import time
    import urllib.parse
    import urllib.request

    items: list[NewsItem] = []

    for i, subject in enumerate(subjects):
        if i > 0:
            time.sleep(1.5)

        params = urllib.parse.urlencode({
            "q": subject,
            "format": "json",
            "categories": "news,general",
            "language": "en",
        })
        url = f"{base_url.rstrip('/')}?{params}"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[!] SearXNG fetch failed for '{subject}': {e}")
            continue

        for count, result in enumerate(data.get("results", [])):
            if count >= max_per:
                break
            items.append(
                NewsItem(
                    title=result.get("title", ""),
                    url=result.get("url", ""),
                    snippet=(result.get("content") or result.get("snippet", "")),
                    source_subject=subject,
                )
            )

    return items


def run(
    subjects: list[str],
    youtube_config: dict,
    reddit_config: dict,
    twitter_config: dict | None = None,
    searxng_config: dict | None = None,
) -> ResearchResult:
    """Run the full research pipeline and return structured results."""
    max_videos = youtube_config.get("max_videos_per_topic", 5)
    channels = youtube_config.get("channels", [])
    max_reddit = reddit_config.get("max_posts_per_subreddit", 5)
    subreddits = reddit_config.get("subreddits", [])

    videos: list[VideoItem] = []
    channel_insights: list[dict] = []

    # Fetch from specific channels if configured
    if channels:
        chan_max = max(1, max_videos // max(1, len(channels)))
        channel_videos = _fetch_youtube_channels(channels, chan_max)
        videos.extend(channel_videos)

        # Auto-extract topics PER CHANNEL (not combined) so smaller channels
        # like Matthew Berman don't get drowned out by Lex Fridman's views
        import re as _re
        from collections import Counter as _Counter

        stopwords = {
            "the","a","an","is","in","to","of","and","for","on","with","it","this","that",
            "how","what","why","i","you","we","be","are","vs","your","my","or","by","its",
            "not","can","has","been","will","just","all","but","from","was","new","more",
            "one","have","get","like","about","when","out","up","so","no","if","do","at",
            "need","right","now","only","best","ever","here","going","happened","every",
            "believe","these","those","they","them","their","into","over","after","before",
            "still","also","way","back","make","made","making","use","using","used","think",
            "know","see","say","said","really","actually","insane","wtf","try","watch",
            # narrative/movie words that pollute non-AI YouTube results
            "rise","fall","empire","india","create","largest","thing","since","episode",
            "part","series","season","full","story","world","first","last","next","top",
        }

        # Extract per channel
        for channel_url in channels:
            chan_vids = [v for v in channel_videos if v.source_subject == channel_url]
            if not chan_vids:
                continue

            word_counts: _Counter = _Counter()
            for v in chan_vids:
                words = _re.findall(r"[A-Za-z0-9]+", v.title.lower())
                for w in words:
                    if len(w) > 2 and w not in stopwords and not w.isdigit():
                        word_counts[w] += 1

            # Take top 3 per channel as auto-subjects
            chan_subjects = [w for w, _ in word_counts.most_common(3) if w not in subjects]
            if chan_subjects:
                print(f"      Auto-subjects from {channel_url}: {chan_subjects}")
                subjects = list(subjects) + chan_subjects

            # Build channel insights: top videos with their own subject tags
            chan_name = channel_url.rsplit("/", 1)[-1] if "/" in channel_url else channel_url
            top_ids = ", ".join(f"{v.title} ({v.views:,} views)" for v in chan_vids[:5])
            # Determine best topic tag for this channel (use highest-count word that overlaps with video titles)
            topic_tag = chan_subjects[0] if chan_subjects else chan_name
            channel_insights.append({
                "channel": chan_name,
                "topic_tag": topic_tag,
                "videos": top_ids,
                "count": len(chan_vids),
            })
            # Retro-tag channel videos with their topic so they show up under a real subject
            for v in chan_vids:
                v.source_subject = topic_tag

    # Also search by subject keywords
    for subject in subjects:
        subject_videos = _search_youtube(subject, max_videos)
        videos.extend(subject_videos)

    # Deduplicate by URL
    seen_urls = set()
    unique_videos: list[VideoItem] = []
    for v in videos:
        if v.url not in seen_urls:
            seen_urls.add(v.url)
            unique_videos.append(v)

    # SearXNG web search
    news_items: list[NewsItem] = []
    if searxng_config:
        sx_url = searxng_config.get("base_url", "")
        sx_max = searxng_config.get("max_results_per_subject", 3)
        if sx_url:
            news_items = _search_searxng(subjects, sx_max, sx_url)

    # Twitter
    twitter_posts: list[TwitterItem] = []
    if twitter_config:
        tw_accounts = twitter_config.get("accounts", [])
        tw_max = twitter_config.get("max_tweets_per_account", 3)
        twitter_posts = _scrape_twitter(tw_accounts, tw_max)

    return ResearchResult(
        videos=unique_videos[:max_videos * len(subjects) * 2],
        reddit_posts=_fetch_reddit(subreddits, max_reddit),
        twitter_posts=twitter_posts,
        news_items=news_items,
        channel_insights=channel_insights,
    )
