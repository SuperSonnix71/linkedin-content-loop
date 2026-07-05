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
) -> tuple[str, str]:
    client = OpenAI(base_url=ai_config["base_url"], api_key=ai_config["api_key"])
    model = ai_config["model"]
    tone = content_config.get("tone", "direct and conversational")
    style = content_config.get("style", "personal and raw")
    language = content_config.get("language", "English")
    custom = content_config.get("custom_instructions", "")

    from collections import defaultdict

    subject_stats: dict[str, dict] = defaultdict(lambda: {"videos": 0, "total_views": 0, "reddit_posts": 0})
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
        subject_stats[p.subreddit]["reddit_posts"] += 1

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

    volume_lines = []
    for name, stats in sorted(subject_stats.items(), key=lambda x: x[1]["total_views"] + x[1]["reddit_posts"] * 10000, reverse=True):
        parts = []
        if stats["videos"]:
            parts.append(f"{stats['videos']} videos ({stats['total_views']:,} views)")
        if stats["reddit_posts"]:
            parts.append(f"{stats['reddit_posts']} Reddit posts")
        if parts:
            volume_lines.append(f"  {name}: {', '.join(parts)}")
    volume_summary = "\n".join(volume_lines)

    subject_list = ", ".join(subjects)

    # Selection mode: use the value passed in by the caller (already handles env var priority)
    if selection_mode == "volume":
        selection_rule = "Pick the subject with the highest research volume — most videos, most views, most Reddit activity. This is data-driven. Never pick a skipped subject."
        subject_format = 'which subject — MUST be the one with the highest research volume. Include the volume data that justifies it: "X videos, Y views, Z Reddit posts"'
    else:
        selection_rule = "Pick the subject with the most surprising or counter-intuitive finding — not the most views. What gap between belief and evidence is widest? Pick what matters, not what's popular. Never pick a skipped subject."
        subject_format = "which subject and WHY — explain the surprising or counter-intuitive insight that made you choose it"

    system_prompt = f"""You are the author of a LinkedIn post. Follow the instructions below.

{custom}

---

PROCESS:

STEP 1 — EXPLORE FREELY:
Read the research. What patterns jump out? What numbers stop you? Let your mind branch naturally. Ask: "If this is true, what happens next? And then what? Who gets hurt? Who wins?"

STEP 2 — PICK YOUR AXES (3-5):
Identify the 3-5 most important axes. Examples: cost, data privacy, power concentration, future of work, vendor lock-in, security. Pick what matters most.

STEP 3 — GO DEEP (2-3 levels per axis, BOTH sides):
For each axis, trace BOTH the positive and negative chain:
  Positive: what improves? who benefits? what new possibilities open up?
  Negative: what breaks? who gets hurt? what's the hidden cost?
Go 2-3 levels deep on each side. Use specific timeframes.

STEP 4 — WEIGH BY IMPACT (not by count):
For every finding — positive or negative — assess its TANGIBLE IMPACT:
  • SCOPE: How many people/companies/industries are affected?
  • SEVERITY: How bad or good is the outcome? Gradual improvement or existential threat?
  • IRREVERSIBILITY: Can it be undone? Or is it permanent?
  • TIMEFRAME: 3 months, 1 year, 5 years?

A single high-impact finding can outweigh three moderate ones. Don't count — weigh.
  Example: "$25T credit collapse = global recession, millions of jobs lost" has more impact than "inference costs dropped 30% = teams save money."
  If the worst-case negative has 100x the impact of the best-case positive, the negatives dominate — regardless of count.

State which side wins AND why the impact magnitude tipped the scale.

STEP 5 — PICK SUBJECT BY INSIGHT:
Look at your tree-of-thought exploration. Which subject produced the most surprising, counter-intuitive, or disturbing finding? Pick the subject where the gap between what people believe and what the evidence shows is the widest. Not the most popular — the most important.

STEP 6 — FIND THE THREAD:
Where do your weighted axes and chosen angle intersect? If warning: the impact of the negatives is the story — explain why the magnitude matters. If optimistic: the positive impact is genuinely transformative — explain why it outweighs the risks.

STEP 7 — WRITE 3 TITLE OPTIONS (each ≤120 chars, use **bold**):
  If warning: a sharp observation, a blunt warning, an uncomfortable truth.
  If optimistic: a bold claim, a surprising insight, a contrarian take.
  If balanced: present the tension honestly.
Pick the best one.

STEP 8 — WRITE THE POST:
  - First line: the chosen TITLE wrapped in **bold**.
  - Voice: write exactly like you speak. Short sentences. Natural pauses. Fragments are fine. Contractions (don't, can't, I've). Read it out loud — if it sounds like an essay, rewrite it.
  - Absorb research insights. Never name-drop individuals.
  - Back claims with evidence: when you cite a fact or statistic from web research, include the URL. All links MUST go at the END of the post, each on its own new line. Never inline links mid-paragraph. One or two links max. Real sources only, never invented.
  - End with a concrete CTA. No fake links or downloads.
  - Length: 1200-1800 chars.

FORMATTING:
  - **bold** for 2-4 key phrases. Also use **bold** for any transitional phrase that introduces a section or bullet list — the phrase alone in bold on its own line, then the content in regular text below.
  - *italic* for internal thoughts, asides.
  - • bullet points: plain text ONLY.
  - NEVER emojis. NEVER section headers. NEVER name-drops. NEVER rhetorical questions. NEVER dashes. NEVER corporate speak (no "leveraging", "synergies", "ecosystem", "scaling", "optimizing"). Write like a human talking.
  - Links: max 1-2, only from web research. Must be news articles, official docs, or research papers. NEVER YouTube, Twitter, or creator content.
  - Hashtags: 5-6 at end. Choose tags with the highest audience reach that are still relevant to the post. Combine broad high-reach tags with niche specific ones. Pick them yourself based on the content — they must fit what you actually wrote.

Tone: {tone}. Style: {style}. Language: {language}."""

    user_prompt = f"""Research findings:

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

ALL SUBJECTS: {subject_list}

SKIP THESE (recently posted): {', '.join(skip_subjects) if skip_subjects else '(none)'}
If any subject in the skip list is also in your subjects, pick a DIFFERENT subject. Do not repeat what was recently posted.

SELECTION RULE: {selection_rule}

You MUST output ONLY this exact format:

SUBJECT PICKED: [{subject_format}]
AXES PICKED: [list the 3-5 axes you chose]
POSITIVES: [key positive findings with tangible impact estimates: scope, severity, irreversibility]
NEGATIVES: [key negative findings with tangible impact estimates: scope, severity, irreversibility]
WEIGHT: [explain which side dominates — weigh by IMPACT MAGNITUDE, not count. A single existential threat can outweigh three moderate benefits. Be specific about which finding tipped the scale and why.]
HASHTAGS CHOSEN: [list hashtags and briefly explain why each was chosen — based on reach, relevance]
TITLE 1: [use **bold**]
TITLE 2: [use **bold**]
TITLE 3: [use **bold**]
BEST: [1, 2, or 3]

THE CHOSEN TITLE repeated in **bold**, then the post:
[post starts here]

Never name-drop."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
            max_tokens=8192,
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

        # Parse output sections
        titles = {}
        best_num = None
        axes = positives = negatives = weight = subject_picked = hashtags_reasoning = ""
        post_start = 0
        lines = raw.split("\n")
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("AXES PICKED:") or s.startswith("AXES PICKED "):
                axes = s.partition(":")[2].strip() if ":" in s else s[12:].strip()
            elif s.startswith("POSITIVES:") or s.startswith("POSITIVES "):
                positives = s.partition(":")[2].strip() if ":" in s else s[10:].strip()
            elif s.startswith("NEGATIVES:") or s.startswith("NEGATIVES "):
                negatives = s.partition(":")[2].strip() if ":" in s else s[10:].strip()
            elif s.startswith("WEIGHT:") or s.startswith("WEIGHT "):
                weight = s.partition(":")[2].strip() if ":" in s else s[7:].strip()
            elif s.startswith("SUBJECT PICKED:") or s.startswith("SUBJECT PICKED "):
                subject_picked = s.partition(":")[2].strip() if ":" in s else s[15:].strip()
            elif s.startswith("HASHTAGS CHOSEN:") or s.startswith("HASHTAGS CHOSEN "):
                hashtags_reasoning = s.partition(":")[2].strip() if ":" in s else s[16:].strip()
            elif s.startswith("TITLE 1:") or s.startswith("TITLE 1 "):
                titles["1"] = s.partition(":")[2].strip() if ":" in s else s[8:].strip()
            elif s.startswith("TITLE 2:") or s.startswith("TITLE 2 "):
                titles["2"] = s.partition(":")[2].strip() if ":" in s else s[8:].strip()
            elif s.startswith("TITLE 3:") or s.startswith("TITLE 3 "):
                titles["3"] = s.partition(":")[2].strip() if ":" in s else s[8:].strip()
            elif s.startswith("BEST:"):
                best_str = s.partition("BEST:")[2].strip().rstrip(".")
                best_num = best_str if best_str in ("1","2","3") else None
                post_start = i + 1
                # Skip blank lines after BEST
                while post_start < len(lines) and not lines[post_start].strip():
                    post_start += 1
                # Skip instruction artifacts like "CHOSEN TITLE" or "[post starts here]" lines
                while post_start < len(lines) and any(
                    w in lines[post_start].lower() for w in
                    ["chosen title", "post starts here", "[post", "the chosen"]
                ):
                    post_start += 1

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
        if hashtags_reasoning:
            print(f"      Hashtags: {hashtags_reasoning}")
        if titles:
            print(f"      Titles considered ({len(titles)}):")
            for num, t in titles.items():
                marker = " ▶" if num == best_num else "  "
                print(f"      {marker} {num}. {t}")

        if post_start > 0:
            post_body = "\n".join(lines[post_start:]).strip()
            # If the post body doesn't start with the chosen title, prepend it
            chosen_title = titles.get(best_num, "") if best_num else ""
            if chosen_title and not post_body.startswith(chosen_title[:30]):
                post_body = chosen_title + "\n\n" + post_body
            raw = post_body
        else:
            # Model didn't output BEST: — strip metadata lines from raw
            metadata_prefixes = ("AXES PICKED", "POSITIVES", "NEGATIVES", "WEIGHT",
                                 "SUBJECT PICKED", "HASHTAGS", "TITLE 1",
                                 "TITLE 2", "TITLE 3", "BEST", "SELECTION RULE",
                                 "[POST", "[THE CHOSEN", "THE CHOSEN")
            raw = "\n".join(
                line for line in lines
                if not any(line.strip().upper().startswith(p) for p in metadata_prefixes)
            ).strip()

        post = _format_for_linkedin(raw)
        return post, subject_picked
    except Exception as e:
        raise RuntimeError(f"LLM generation failed: {e}") from e
