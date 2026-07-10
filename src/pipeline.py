"""
LangGraph pipeline: multi-step LLM workflow for LinkedIn post generation.

Nodes: Analyzer → Thinker → Writer → Judge (with loop back on rejection)
Each node has ONE focused job. State passes as typed JSON between nodes.
"""

from __future__ import annotations

import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.ai_client import get_client, get_model


class PipelineState(TypedDict):
    """Shared state flowing through all pipeline nodes."""

    # Input from main.py
    research_data: str          # serialized research: YouTube + Reddit + Web + channels
    skip_subjects: list[str]    # subjects to avoid (from DB)
    selection_mode: str         # "insight" or "volume"
    configured_subjects: list[str]  # all configured subjects from config.yaml

    # Analyzer output
    candidates: list[dict]      # [{subject, reason, relative_subject}]

    # Thinker output
    subject: str                # chosen subject
    chains: dict                # {positive_chain, negative_chain, verdict}
    relative_subject: str       # clean subject name for DB/URL matching

    # Writer output
    post_raw: str               # unvalidated post text
    title: str                  # chosen title
    hashtags_raw: str           # space-separated #tags

    # Judge output
    approved: bool              # did the judge approve?
    fixes: list[str]            # specific fix instructions if rejected

    # Final output
    post_final: str             # validated, formatted post ready to publish
    retry_count: int            # number of judge→writer retries


# --- Node stubs (filled in Tasks 3-6) ---

_ANALYZER_PROMPT = """You are a research analyst. Your ONLY job is to pick the 3 most interesting candidate subjects from the research data below.

Look at Reddit for what real people are discussing with real engagement. A 5000-upvote Reddit thread reveals more interesting angles than 50M YouTube views. Look for deep tension between positive and negative impact.

SKIP these subjects (exact or overlapping): {skip_subjects}

Output ONLY a JSON object with this exact structure:
{{"candidates": [{{"subject": "short subject name", "reason": "one-line explanation of why this is interesting", "relevant_subject": "the closest matching configured subject name"}}]}}

Research data:
{research_data}"""


def analyzer_node(state: PipelineState) -> dict:
    """Pick top 3 candidate subjects from research data."""
    import json as _json

    client = get_client()
    model = get_model()

    skip_str = ", ".join(state.get("skip_subjects", [])) or "(none)"
    prompt = _ANALYZER_PROMPT.format(
        skip_subjects=skip_str,
        research_data=state["research_data"],
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"      Analyzer failed: {e}")
        return {"candidates": []}

    # Parse JSON
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    raw = raw.strip()

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = _json.loads(match.group(0))
            except _json.JSONDecodeError:
                print("      Analyzer JSON parse failed")
                return {"candidates": []}
        else:
            print("      Analyzer JSON parse failed")
            return {"candidates": []}

    candidates = data.get("candidates", [])
    # Filter: only keep candidates whose relevant_subject matches a configured subject
    configured = state.get("configured_subjects", [])
    configured_lower = {s.lower() for s in configured}
    filtered = []
    for c in candidates:
        rel = c.get("relevant_subject", "").lower()
        if any(rel == cs or cs in rel or rel in cs for cs in configured_lower):
            filtered.append(c)
        else:
            print(f"      Analyzer rejected (not AI-relevant): {c.get('subject', '?')}")
    candidates = filtered
    if candidates:
        print(f"      Analyzer found {len(candidates)} candidates:")
        for c in candidates:
            print(f"        - {c.get('subject', '?')}: {c.get('reason', '?')[:80]}")
    return {"candidates": candidates}


_THINKER_PROMPT = """You are a strategic analyst. Your ONLY job: trace consequence chains from MULTIPLE perspectives for ONE subject.

Start with this candidate subject and its research context. Explore consequences from 4-6 different angles. For EACH angle, chain the effects 5-8 levels deep: if this happens, then what? And then what? Who gets affected? What new conditions emerge?

Example angles: economic impact, power consolidation, workforce/labor, security/privacy, competitive dynamics, societal/governance, infrastructure/deployment.

Each chain must be logical consequences of the previous link. Do NOT fabricate — only use what's in the research. Pure logical projection from facts is fine.

Subject: {subject}
Reason this is interesting: {reason}

Research context:
{research_data}

Output ONLY a JSON object:
{{"subject": "the chosen subject name", "relevant_subject": "closest configured subject", "chains": [{{"angle": "short angle name", "chain": ["level 1", "level 2", ...], "verdict": "this angle's dominant outcome and why"}}]}}"""


def thinker_node(state: PipelineState) -> dict:
    """Trace consequence chains from multiple perspectives for the chosen subject."""
    import json as _json

    candidates = state.get("candidates", [])
    if not candidates:
        print("      Thinker: no candidates, using fallback")
        return {"subject": "AI", "chains": {}, "relevant_subject": "AI"}

    chosen = candidates[0]
    subject = chosen.get("subject", "AI")
    reason = chosen.get("reason", "")
    relevant = chosen.get("relevant_subject", "AI")

    client = get_client()
    model = get_model()

    prompt = _THINKER_PROMPT.format(
        subject=subject,
        reason=reason,
        research_data=state["research_data"],
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"      Thinker failed: {e}")
        return {"subject": subject, "chains": {}, "relevant_subject": relevant}

    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    raw = raw.strip()

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = _json.loads(match.group(0))
            except _json.JSONDecodeError:
                print("      Thinker JSON parse failed")
                return {"subject": subject, "chains": {}, "relevant_subject": relevant}
        else:
            print("      Thinker JSON parse failed")
            return {"subject": subject, "chains": {}, "relevant_subject": relevant}

    chains_list = data.get("chains", [])
    if isinstance(chains_list, list):
        print(f"      Thinker: {len(chains_list)} angles explored")
        for c in chains_list:
            chain = c.get("chain", [])
            print(f"        {c.get('angle', '?')}: {len(chain)} levels")
    return {
        "subject": data.get("subject", subject),
        "chains": data,  # pass the full response for the Writer
        "relevant_subject": data.get("relevant_subject", relevant),
    }


    """Write the LinkedIn post using the Thinker's chains."""
    import json as _json

def writer_node(state: PipelineState) -> dict:
    """Write the LinkedIn post using the Thinker's chains."""
    import json as _json

    chains_data = state.get("chains", {})
    research_data = state.get("research_data", "")
    fixes = state.get("fixes", [])

    if not chains_data:
        return {"post_raw": "", "title": "", "hashtags_raw": ""}

    client = get_client()
    model = get_model()

    # Format chains and research for the Writer
    chains_json = _json.dumps(chains_data, indent=2)

    prompt = f"""You write LinkedIn posts. Your ONLY job: take this strategic analysis and turn it into a post.

Analysis (from the Thinker):
{chains_json}

Research context:
{research_data}

WRITING RULES:
- Title in **bold** as first line (≤120 chars). Pick 2-3 most important angles — not all of them.
- Show the most interesting angles, the tension between them, and a clear verdict.
- Write like you're texting a smart friend. Short sentences. Fragments. Contractions.
- No \"The [noun] is [adjective]\" openers. No \"However\", \"Furthermore\". No transitions.
- No hyperbole. No apocalyptic language. No fabricated anecdotes. Every concrete claim must trace to research.
- No section headers (like \"The Upside\" or \"The Downside\").
- **Bold** for 2-4 key phrases. *Italic* for internal thoughts.
- Bullet points plain text. No parallel structure.
- End with a strong thought, not engagement bait.
- Include 5-6 hashtags at the end. At least one link from the research on its own line before hashtags.
- Length: 1200-1800 chars. No emojis, no dashes, no name-drops.

{"Fix these issues: " + "; ".join(fixes) if fixes else ""}

Output ONLY a JSON object:
{{"title": "THE BOLD TITLE — max 120 chars, first line of the post", "post": "the full post text starting with the bold title on line 1", "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6"}}

The post field MUST start with the title in **bold** as its very first line. No exceptions. Example:
"**Agents Are Building Themselves**\n\nThe shift is real..." — title on line 1, blank line, then body."""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"      Writer failed: {e}")
        return {"post_raw": "", "title": "", "hashtags_raw": ""}

    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    raw = raw.strip()

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = _json.loads(match.group(0))
            except _json.JSONDecodeError:
                print("      Writer JSON parse failed")
                return {"post_raw": "", "title": "", "hashtags_raw": ""}
        else:
            print("      Writer JSON parse failed")
            return {"post_raw": "", "title": "", "hashtags_raw": ""}

    title = data.get("title", "")
    post = data.get("post", "")
    hashtags = data.get("hashtags", "")

    # Ensure title is the first line of the post
    if title and post and not post.strip().startswith(title[:30]):
        post = "**" + title.strip(" *") + "**\n\n" + post

    print(f"      Writer: {len(post) if post else 0} chars, {len(hashtags.split()) if hashtags else 0} tags")
    return {"post_raw": post, "title": title, "hashtags_raw": hashtags}


def judge_node(state: PipelineState) -> dict:
    """Verify every claim against research. Flag fabricated URLs and claims."""
    import json as _json

    post_raw = state.get("post_raw", "")
    research_data = state.get("research_data", "")

    if not post_raw:
        return {"approved": True, "fixes": []}

    # Code-level check: any URL in the post that isn't in the research is FABRICATED
    fix_list = []
    urls_in_post = re.findall(r"https?://[^\s<>\"\']+", post_raw)
    for url in urls_in_post:
        clean_url = url.rstrip(".,;:!?")
        if clean_url not in research_data:
            fix_list.append(f"FABRICATED URL: {clean_url} — does not exist in research. Remove or replace with a real URL from research.")

    # LLM-level check: verify concrete claims against research
    if research_data:
        client = get_client()
        model = get_model()

        prompt = f"""You are a fact-checker. Your ONLY job: scan this post and flag any VERIFIABLY fabricated claims.

A claim is fabricated if it mentions specific events, names, companies, or numbers that do NOT appear in the research data.
Tree-of-thought projections are fine ("if this continues, the pipeline breaks").
Style issues, tone, and formatting are NOT your concern. Only check factual accuracy.

Research data:
{research_data}

Post to verify:
{post_raw}

Output ONLY a JSON object:
{{"approved": true or false, "fabrications": ["exact fabricated passage 1", "exact fabricated passage 2"]}}

If EVERY concrete claim traces back to something in the research, approved=true and fabrications=[]."""

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # lower temp for fact-checking
            )
            raw = resp.choices[0].message.content or ""
        except Exception as e:
            print(f"      Judge LLM call failed: {e}")
            # Fall back to URL-only check
            approved = len(fix_list) == 0
            return {"approved": approved, "fixes": fix_list}

        raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = _json.loads(match.group(0))
                except _json.JSONDecodeError:
                    approved = len(fix_list) == 0
                    return {"approved": approved, "fixes": fix_list}
            else:
                approved = len(fix_list) == 0
                return {"approved": approved, "fixes": fix_list}

        llm_fixes = data.get("fabrications", [])
        fix_list.extend(llm_fixes)
        llm_approved = data.get("approved", True)
        approved = llm_approved and len(fix_list) == 0
    else:
        approved = len(fix_list) == 0

    if fix_list:
        print(f"      Judge: REJECTED — {len(fix_list)} issues found")
        for f in fix_list[:3]:
            print(f"        - {f[:100]}")
    else:
        print("      Judge: APPROVED")

    return {"approved": approved, "fixes": fix_list}


def should_retry(state: PipelineState) -> str:
    """Decision: loop back to writer if judge rejected and retry count < max."""
    max_retries = 2
    approved = state.get("approved", True)
    retries = state.get("retry_count", 0)
    if not approved and retries < max_retries:
        state["retry_count"] = retries + 1
        return "writer"
    return "end"


def build_graph() -> StateGraph:
    """Build and compile the LangGraph pipeline."""
    workflow = StateGraph(PipelineState)

    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("thinker", thinker_node)
    workflow.add_node("writer", writer_node)
    workflow.add_node("judge", judge_node)

    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "thinker")
    workflow.add_edge("thinker", "writer")
    workflow.add_edge("writer", "judge")

    workflow.add_conditional_edges(
        "judge",
        should_retry,
        {
            "writer": "writer",
            "end": END,
        },
    )

    return workflow.compile()


# Singleton graph instance
_graph: StateGraph | None = None


def run_pipeline(initial_state: dict) -> dict:
    """Execute the full pipeline and return the final state."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph.invoke(initial_state)


# ─── Public API (matches old generate.py interface) ────────────────────────

def generate_post(
    youtube_videos: list,
    reddit_posts: list,
    twitter_posts: list,
    news_items: list,
    subjects: list[str],
    content_config: dict | None = None,
    ai_config: dict | None = None,
    skip_subjects: list[str] | None = None,
    selection_mode: str = "insight",
    channel_insights: list[dict] | None = None,
) -> tuple[str, str]:
    """
    Generate a LinkedIn post using the LangGraph pipeline.
    Returns (post_text, chosen_subject) — same signature as old generate().
    """
    # Build research data string
    parts = []
    for v in youtube_videos[:20]:
        parts.append(f"YT [{getattr(v, 'source_subject', '')}]: {v.title} ({v.views} views)")
    for p in reddit_posts[:20]:
        parts.append(f"Reddit r/{getattr(p, 'subreddit', '')} ({getattr(p, 'score', 0)} upvotes): {getattr(p, 'title', '')}")
    for t in twitter_posts[:10]:
        parts.append(f"Twitter @{getattr(t, 'account', '')}: {getattr(t, 'text', '')[:200]}")
    for n in news_items[:20]:
        parts.append(f"Web [{getattr(n, 'source_subject', '')}]: {getattr(n, 'title', '')} — {getattr(n, 'snippet', '')[:100]} ({getattr(n, 'url', '')})")
    research_data = "\n".join(parts)

    state = {
        "research_data": research_data,
        "skip_subjects": skip_subjects or [],
        "selection_mode": selection_mode,
        "configured_subjects": subjects,
        "candidates": [],
        "chains": {},
        "post_raw": "",
        "title": "",
        "hashtags_raw": "",
        "approved": True,
        "fixes": [],
        "retry_count": 0,
        "subject": "",
        "relevant_subject": "",
        "post_final": "",
    }

    # Run the pipeline
    try:
        final = run_pipeline(state)
    except Exception as e:
        print(f"[!] Pipeline failed: {e}")
        return "", ""

    post_raw = final.get("post_raw", "")
    relevant_subject = final.get("relevant_subject", "")
    hashtags_raw = final.get("hashtags_raw", "")

    # Apply formatting (Unicode bold/italic) — same as old _format_for_linkedin
    from src.generate import _format_for_linkedin
    post_formatted = _format_for_linkedin(post_raw)

    # Inject hashtags if missing
    if "#" not in post_formatted and hashtags_raw:
        post_formatted = post_formatted.rstrip() + "\n\n" + hashtags_raw.strip()

    # Link validation: only keep URLs from actual research
    if news_items:
        fetched_urls = {n.url for n in news_items if n.url}
        post_words = set(re.findall(r"[a-z]{4,}", post_formatted.lower()))
        post_words -= {"that", "this", "with", "from", "have", "they", "will"}
        valid_urls = set()
        for n in news_items:
            if not n.url or n.url not in fetched_urls:
                continue
            article_words = set(re.findall(r"[a-z]{4,}", (n.title + " " + n.snippet).lower()))
            overlap = post_words & article_words
            if len(overlap) >= 3:
                valid_urls.add(n.url)
        url_pattern = re.compile(r'https?://[^\s<>"\']+')
        lines = post_formatted.split("\n")
        filtered_lines = []
        for line in lines:
            urls_in_line = url_pattern.findall(line)
            if urls_in_line:
                def _replace_url(m):
                    url = m.group(0).rstrip(".,")
                    return url if url in valid_urls else ""
                line = url_pattern.sub(_replace_url, line)
            filtered_lines.append(line)
        post_formatted = "\n".join(filtered_lines)

    return post_formatted, relevant_subject or "AI"
