"""Post generation: tree-of-thought → human-voice LinkedIn post with Unicode formatting."""

import re

from openai import OpenAI

# ─── LinkedIn formatting conversion ──────────────────────────────────

def _to_unicode_bold(text: str) -> str:
    bold_map = {
        "A": "𝗔","B": "𝗕","C": "𝗖","D": "𝗗","E": "𝗘","F": "𝗙","G": "𝗚","H": "𝗛",
        "I": "𝗜","J": "𝗝","K": "𝗞","L": "𝗟","M": "𝗠","N": "𝗡","O": "𝗢","P": "𝗣",
        "Q": "𝗤","R": "𝗥","S": "𝗦","T": "𝗧","U": "𝗨","V": "𝗩","W": "𝗪","X": "𝗫",
        "Y": "𝗬","Z": "𝗭","a": "𝗮","b": "𝗯","c": "𝗰","d": "𝗱","e": "𝗲","f": "𝗳",
        "g": "𝗴","h": "𝗵","i": "𝗶","j": "𝗷","k": "𝗸","l": "𝗹","m": "𝗺","n": "𝗻",
        "o": "𝗼","p": "𝗽","q": "𝗾","r": "𝗿","s": "𝘀","t": "𝘁","u": "𝘂","v": "𝘃",
        "w": "𝘄","x": "𝘅","y": "𝘆","z": "𝘇","0": "𝟬","1": "𝟭","2": "𝟮","3": "𝟯",
        "4": "𝟰","5": "𝟱","6": "𝟲","7": "𝟳","8": "𝟴","9": "𝟵",
    }
    return "".join(bold_map.get(ch, ch) for ch in text)


def _to_unicode_italic(text: str) -> str:
    italic_map = {
        "A": "𝘈","B": "𝘉","C": "𝘊","D": "𝘋","E": "𝘌","F": "𝘍","G": "𝘎","H": "𝘏",
        "I": "𝘐","J": "𝘑","K": "𝘒","L": "𝘓","M": "𝘔","N": "𝘕","O": "𝘖","P": "𝘗",
        "Q": "𝘘","R": "𝘙","S": "𝘚","T": "𝘛","U": "𝘜","V": "𝘝","W": "𝘞","X": "𝘟",
        "Y": "𝘠","Z": "𝘡","a": "𝘢","b": "𝘣","c": "𝘤","d": "𝘥","e": "𝘦","f": "𝘧",
        "g": "𝘨","h": "𝘩","i": "𝘪","j": "𝘫","k": "𝘬","l": "𝘭","m": "𝘮","n": "𝘯",
        "o": "𝘰","p": "𝘱","q": "𝘲","r": "𝘳","s": "𝘴","t": "𝘵","u": "𝘶","v": "𝘷",
        "w": "𝘸","x": "𝘹","y": "𝘺","z": "𝘻",
    }
    return "".join(italic_map.get(ch, ch) for ch in text)


def _format_for_linkedin(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: _to_unicode_bold(m.group(1)), text)
    text = re.sub(r"\*(.+?)\*", lambda m: _to_unicode_italic(m.group(1)), text)
    return text


# ─── Post generation ─────────────────────────────────────────────────

def generate(
    youtube_videos: list,
    reddit_posts: list,
    twitter_posts: list,
    news_items: list,
    subjects: list[str],
    content_config: dict,
    ai_config: dict,
    skip_subjects: list[str] | None = None,
    selection_mode: str = "insight",
    channel_insights: list[dict] | None = None,
) -> tuple[str, str]:
    client = OpenAI(base_url=ai_config["base_url"], api_key=ai_config["api_key"])
    model = ai_config["model"]
    tone = content_config.get("tone", "direct and conversational")
    style = content_config.get("style", "personal and raw")
    language = content_config.get("language", "English")
    custom = content_config.get("custom_instructions", "")

    from collections import defaultdict

    subject_stats: dict[str, dict] = defaultdict(lambda: {"videos": 0, "total_views": 0, "reddit_posts": 0, "total_upvotes": 0})
    video_list: list[str] = []
    reddit_list: list[str] = []

    for v in youtube_videos[:15]:
        video_list.append(f"  - {v.summary()}")
        subj = getattr(v, "source_subject", "") or (subjects[0] if subjects else "")
        subject_stats[subj]["videos"] += 1
        subject_stats[subj]["total_views"] += v.views

    for p in reddit_posts[:15]:
        reddit_list.append(f"  - {p.summary()}")
        if p.selftext:
            reddit_list.append(f"    Excerpt: {p.selftext[:200].replace(chr(10), ' ')}...")
        # Map subreddit name to closest configured subject
        best_subj = p.subreddit
        for s in subjects:
            if s.lower() in p.subreddit.lower() or p.subreddit.lower() in s.lower():
                best_subj = s
                break
        subject_stats[best_subj]["reddit_posts"] += 1
        subject_stats[best_subj]["total_upvotes"] += p.score

    twitter_list: list[str] = []
    for t in twitter_posts[:15]:
        twitter_list.append(f"  - {t.summary()}")

    news_list: list[str] = []
    for n in news_items[:15]:
        news_list.append(f"  - {n.summary()}")

    video_section = "\n".join(video_list)
    reddit_section = "\n".join(reddit_list)
    twitter_section = "\n".join(twitter_list)
    news_section = "\n".join(news_list)

    # Build AVAILABLE SOURCES: URLs grouped by subject
    from collections import defaultdict as _dd
    sources_by_subject: dict[str, list[str]] = _dd(list)
    for n in news_items:
        if n.url and n.source_subject:
            sources_by_subject[n.source_subject].append(f"{n.url} ({n.title[:80]})")
    sources_lines = []
    for subj, urls in sorted(sources_by_subject.items()):
        for u in urls[:3]:
            sources_lines.append(f"  [{subj}] {u}")
    sources_section = "\n".join(sources_lines) if sources_lines else "(none)"

    # Channel insights: top videos from each subscribed channel
    channel_section = ""
    if channel_insights:
        ci_lines = []
        for ci in channel_insights:
            ci_lines.append(f"  {ci['channel']} [{ci['topic_tag']}] ({ci['count']} videos): {ci['videos']}")
        channel_section = "\n".join(ci_lines)
        print(f"      Channels: {', '.join(ci['channel'] for ci in channel_insights)}")

    volume_lines = []
    for name, stats in sorted(subject_stats.items(), key=lambda x: x[1]["total_views"] + x[1]["total_upvotes"] * 1000, reverse=True):
        parts = []
        if stats["videos"]:
            parts.append(f"{stats['videos']} videos ({stats['total_views']:,} views)")
        if stats["reddit_posts"]:
            parts.append(f"{stats['reddit_posts']} Reddit posts ({stats['total_upvotes']:,} upvotes)")
        if parts:
            volume_lines.append(f"  {name}: {', '.join(parts)}")
    volume_summary = "\n".join(volume_lines)

    subject_list = ", ".join(subjects)

    # Selection mode: use the value passed in by the caller (already handles env var priority)
    if selection_mode == "volume":
        selection_rule = "Pick the subject with the highest research volume — most videos, most views, most Reddit activity. This is data-driven. Never pick a skipped subject."
        subject_format = 'which subject — MUST be the one with the highest research volume. Include the volume data that justifies it: "X videos, Y views, Z Reddit posts"'
    else:
        selection_rule = "Mine Reddit for the most interesting angle. Look at what real people are discussing with real engagement — hot takes, concerns, breakthroughs. A 5000-upvote Reddit thread often reveals more interesting angles than 50M YouTube views. Find the discussion with the deepest tension between positive and negative impact, regardless of which subject it belongs to. Never pick a skipped subject. Also avoid subjects that share words with any skipped subject — if 'agents' is skipped, don't pick 'AI coding assistants' or 'agentic work'. Reddit content trumps YouTube volume."
        subject_format = "which subject and WHY — explain what makes the tension between positive and negative so deep here"

    system_prompt = f"""You write LinkedIn posts. Your job: analyze the research, pick the subject with the deepest tension between positive and negative impact, and write a post that sounds human — not AI-generated.

{custom}

WRITING RULES — these are not optional:
- Write like you're texting a smart friend about something that matters. Short sentences. Fragments. Contractions always (don't, can't, I've, it's, they're).
- No "The [noun] is [adjective]" openers. Start with "I", "You", a verb, a number, or just jump in.
- No "However", "Furthermore", "Moreover", "While X, Y...". No transitions.
- Vary sentence length hard. A 3-word sentence. Then a 20-word one. Then a fragment.
- Never use: stark, reality, landscape, ecosystem, leverage, synergy, optimization, holistic.
- No bullet points that all start with the same word (parallel structure = AI).
- End with a strong thought. Never ask for comments, likes, or engagement.
- No hyperbole. No apocalyptic language. Be precise, not dramatic. Numbers and specifics beat adjectives.
- NEVER fabricate. Every concrete fact (number, name, event, quote) must exist in the research. You cannot invent 'a founder vibe coded a 7-figure tool' or 'a startup in Berlin just did X' — that's lying. Tree-of-thought projections are different: you CAN say 'if this continues, the pipeline breaks in 18 months' or 'the structural risk outweighs' because you're analyzing, not inventing. Distinction: analysis = valid. Fake stories = garbage.
- Read the post out loud in your head. If it sounds smooth and polished, start over.

PROCESS:
1. Read the research. Find the subject where BOTH sides carry real weight — positive impact is genuine AND negative risk is real. Surface surprise doesn't matter — substance does.
2. Trace CONSEQUENCE CHAINS, not just pros/cons. Start with the core finding, then ask: if this is true, what happens next? And then what? Who gets affected? What does that lead to? Go 5-8 levels deep. Each link must be a logical consequence of the previous one. Weigh by impact magnitude: a single deep chain with massive structural consequences outweighs three shallow ones.
3. Write the post. Show the upside first. Then the downside. Then your weighted verdict — which side wins and why.
4. SELF-CHECK: Before outputting, scan every sentence. Does each concrete claim (name, number, event) trace back to the research? If you wrote "a founder did X" or "a company just Y" and it's not in the research, delete it. Tree-of-thought projections are fine ("if this continues..."). Fabricated facts are not.

FORMAT:
- Title in **bold** as first line (≤120 chars).
- **Bold** for 2-4 key phrases and for transitional lines that introduce bullet lists.
- *Italic* for internal thoughts or asides.
- Bullet points: plain text only.
- YOU MUST include a link from the web research. No link = failed post. Put each link on its own line after the post body and before hashtags.
- 5-6 hashtags at the very end.
- Length: 1200-1800 chars.
- No emojis, no dashes, no name-drops, no rhetorical questions, no section headers like "The Upside" or "The Downside".

Tone: {tone}. Style: {style}. Language: {language}."""


    user_prompt = f"""Research findings:

CHANNEL INSIGHTS (top videos from subscribed creators — these may contain valuable niche content not captured by broad keyword search):
{channel_section}

RESEARCH VOLUME BY SUBJECT:
{volume_summary}

YouTube:
{video_section}

Reddit:
{reddit_section}

Twitter/X:
{twitter_section}

Web:
{news_section}

AVAILABLE SOURCES (URLs to cite in your post — use these, never invent URLs):
{sources_section}

ALL SUBJECTS: {subject_list}

SKIP THESE (recently posted): {', '.join(skip_subjects) if skip_subjects else '(none)'}
If any subject in the skip list is also in your subjects, pick a DIFFERENT subject. Do not repeat what was recently posted.

SELECTION RULE: {selection_rule}

You MUST output ONLY a valid JSON object. No text before or after. The JSON must have these exact keys:

{{
  "subject": "[{subject_format}]",
  "axes": "[list the 3-5 axes you chose]",
  "positives": "[key positive findings with impact estimates]",
  "negatives": "[key negative findings with impact estimates]",
  "weight": "[explain which side dominates and why]",
  "hashtags": "[5-6 hashtags as a single string, space-separated, e.g. \"#AI #LLM #Infra\"]",
  "link": "[paste ONE URL from AVAILABLE SOURCES above that matches your chosen subject and angle, or empty string if none truly fit — relevance is more important than presence]",
  "titles": ["title 1 in **bold**", "title 2 in **bold**", "title 3 in **bold**"],
  "best_title": 1,
  "post": "[the full post text with formatting — bold, italic, bullet points, link on its own line, hashtags at end]"
}}

The \"post\" field must be the complete post ready to publish — title in **bold** as first line, body, link on its own line, hashtags at the very end."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
            max_tokens=32768,
        )
        msg = response.choices[0].message
        raw = msg.content

        if not raw or not raw.strip():
            finish = response.choices[0].finish_reason
            print(f"      Empty response (finish_reason={finish})")
            return "", ""

        raw = raw.strip()
        while raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        # Sanitize: escape stray control characters that break JSON parsing
        raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)

        # Parse JSON response
        import json as _json

        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError as e:
            # Fallback: try to extract JSON from within the text
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    data = _json.loads(match.group(0))
                except _json.JSONDecodeError:
                    print(f"      JSON parse failed: {str(e)[:100]}")
                    print(f"      Raw output (first 200 chars): {raw[:200]}")
                    return "", ""
            else:
                print(f"      JSON parse failed: {str(e)[:100]}")
                print(f"      Raw output (first 200 chars): {raw[:200]}")
                return "", ""

        subject_picked = data.get("subject", "")
        # Extract just the subject name (first word/phrase, before colons, parens, or sentence breaks)
        clean_subject = subject_picked.split(":")[0].split("(")[0].split(". The")[0].split(". the")[0].strip().rstrip(".,:; ")
        if len(clean_subject) > 50:
            clean_subject = clean_subject[:50]

        # Fuzzy dedup: block if 2+ words overlap with any skip subject
        if skip_subjects:
            chosen_words = set(clean_subject.lower().split())
            for skip in skip_subjects:
                skip_words = set(skip.lower().split())
                if len(chosen_words & skip_words) >= 2:
                    print(f"      Subject '{clean_subject}' overlaps with skipped '{skip}' — picking another.")
                    return "", ""
        axes = data.get("axes", "")
        positives = data.get("positives", "")
        negatives = data.get("negatives", "")
        weight = data.get("weight", "")
        hashtags_raw = data.get("hashtags", "")
        link_url = data.get("link", "")
        titles_raw = data.get("titles", [])
        best_num = str(data.get("best_title", 1))
        post_raw = data.get("post", "")

        # Build titles dict
        titles = {}
        if isinstance(titles_raw, list):
            for idx, t in enumerate(titles_raw, 1):
                titles[str(idx)] = t
            if best_num not in titles:
                best_num = "1" if "1" in titles else next(iter(titles.keys()), "1")

        raw = post_raw

        if axes:
            print(f"\n      Axes: {axes}")
        if positives:
            print(f"      ⊕ Positives: {positives}")
        if negatives:
            print(f"      ⊖ Negatives: {negatives}")
        if weight:
            print(f"      ⚖ Weight verdict: {weight}")
        if subject_picked:
            print(f"      Subject chosen: {subject_picked}")
        if hashtags_raw:
            print(f"      Hashtags: {hashtags_raw}")
        if titles:
            print(f"      Titles considered ({len(titles)}):")
            for num, t in titles.items():
                marker = " ▶" if num == best_num else "  "
                print(f"      {marker} {num}. {t}")
        if link_url:
            print(f"      Link: {link_url}")
        else:
            print("      Link: (none)")

        post = _format_for_linkedin(raw)

        # If the model forgot hashtags in the post body, add from metadata
        if "#" not in post and hashtags_raw:
            tags = hashtags_raw.strip()
            if tags:
                post = post.rstrip() + "\n\n" + tags

        # Inject link from metadata if model provided one but forgot it in post
        if link_url and "http" not in post:
            hashtag_start = post.find("\n#")
            if hashtag_start > 0:
                post = post[:hashtag_start].rstrip() + "\n\n" + link_url + post[hashtag_start:]
            else:
                post = post.rstrip() + "\n\n" + link_url
            if "http" not in post:
                print(f"      Link injection FAILED: {link_url[:60]}")
        link_after_inject = "http" in post
        if not link_after_inject:
            link_after_inject = "http" in post

        # Validate URLs: only keep links that are both from matching subject AND relevant to the post content
        if news_items:
            # Find which original subjects relate to the chosen subject
            chosen_lower = clean_subject.lower()
            relevant_subjects = set()
            for s in subjects:
                if s.lower() in chosen_lower or chosen_lower in s.lower():
                    relevant_subjects.add(s.lower())
            if not relevant_subjects:
                relevant_subjects = {s.lower() for s in subjects}

            # Extract meaningful words from the post for relevance matching
            post_words = set(re.findall(r"[a-z]{4,}", post.lower()))
            # Remove common stopwords
            post_words -= {
                "that", "this", "with", "from", "have", "they", "will",
                "your", "what", "when", "been", "them", "then", "into",
                "than", "also", "more", "some", "such", "only", "very",
                "just", "like", "make", "know", "think", "here", "there",
            }

            # Only allow URLs from matching subject AND with keyword overlap to the post
            # ALSO: only allow URLs that actually exist in the fetched news items
            fetched_urls = {n.url for n in news_items if n.url}
            valid_urls = set()
            for n in news_items:
                if not n.url or n.url not in fetched_urls:
                    continue
                article_words = set(re.findall(r"[a-z]{4,}", (n.title + " " + n.snippet).lower()))
                overlap = post_words & article_words
                # Require high keyword overlap. Subject match is preferred but
                # 5+ shared words overrides subject mismatch (cross-cutting articles).
                if len(overlap) >= 5:
                    valid_urls.add(n.url)
                elif len(overlap) >= 3 and n.source_subject.lower() in relevant_subjects:
                    valid_urls.add(n.url)
                    valid_urls.add(n.url)

            # Strip any URL in the post that isn't relevant, AND remove the dangling
            # line that referenced it (e.g., "Review the data here:" with no link)
            url_pattern = re.compile(r'https?://[^\s<>"\']+')
            lines = post.split("\n")
            filtered_lines = []
            for line in lines:
                urls_in_line = url_pattern.findall(line)
                if urls_in_line:
                    # Replace only invalid URLs, keep valid ones
                    def _replace_url(m):
                        url = m.group(0).rstrip(".,")
                        return url if url in valid_urls else ""
                    new_line = url_pattern.sub(_replace_url, line)
                    # If all URLs were stripped and line is now just a reference
                    # to deleted links (short line ending with ":"), skip it
                    stripped = new_line.strip()
                    if not url_pattern.search(new_line) and (
                        len(stripped) < 60 and stripped.rstrip(".").endswith(":") or
                        stripped.lower().rstrip(".") in {"link", "source", "reference", "here"}
                    ):
                        continue  # drop the dangling "Review here:" line
                    line = new_line
                filtered_lines.append(line)
            post = "\n".join(filtered_lines)
            if link_after_inject and "http" not in post:
                print(f"      Link stripped by validation. valid_urls count: {len(valid_urls)}")

        return post, clean_subject
    except Exception as e:
        raise RuntimeError(f"LLM generation failed: {e}") from e
