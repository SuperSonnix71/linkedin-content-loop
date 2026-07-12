"""
LangGraph pipeline: multi-step LLM workflow for LinkedIn post generation.

Nodes: Analyzer → Thinker → Writer → Judge (with loop back on rejection)
Each node has ONE focused job. State passes as typed JSON between nodes.
"""

from __future__ import annotations

import os
import random
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.ai_client import get_client, get_model


class PipelineState(TypedDict):
    """Shared state flowing through all pipeline nodes."""

    # Input from main.py
    research_data: str  # serialized research: YouTube + Reddit + Web + channels
    skip_subjects: list[str]  # subjects to avoid (from DB)
    selection_mode: str  # "insight" or "volume"
    configured_subjects: list[str]  # all configured subjects from config.yaml
    content_config: dict  # tone, style, language, custom_instructions from config.yaml

    # Analyzer output
    candidates: list[dict]  # [{subject, reason, relevant_subject}]

    # Thinker output
    subject: str  # chosen subject
    chains: dict  # {positive_chain, negative_chain, verdict}
    relevant_subject: str  # clean subject name for DB/URL matching

    # Writer output
    post_raw: str  # unvalidated post text
    title: str  # chosen title
    hashtags_raw: str  # space-separated #tags

    # Judge output
    approved: bool  # did the judge approve?
    fixes: list[str]  # specific fix instructions if rejected
    retry_count: int  # number of judge→writer retries


# --- Node stubs (filled in Tasks 3-6) ---

_SELECTION_RULES = {
    "volume": (
        "Pick candidates by research volume — most videos, most views, most Reddit "
        "activity. This is data-driven. Never pick a skipped subject."
    ),
    "insight": (
        "Mine Reddit for the most interesting angle. Look at what real people are "
        "discussing with real engagement — hot takes, concerns, breakthroughs. A "
        "5000-upvote Reddit thread often reveals more interesting angles than 50M "
        "YouTube views. Find the discussion with the deepest tension between positive "
        "and negative impact. Never pick a skipped subject."
    ),
}

_ANALYZER_PROMPT = """You are a research analyst. Your ONLY job is to pick the 3 most interesting candidate subjects from the research data below.

{selection_rule}

List "candidates" in order from most interesting (best) to least interesting — the first entry in the list must be your top pick.

SKIP these subjects (exact or overlapping): {skip_subjects}

Output ONLY a JSON object with this exact structure:
{{"candidates": [{{"subject": "short subject name", "reason": "one-line explanation of why this is interesting", "relevant_subject": "the closest matching configured subject name"}}]}}

Research data:
{research_data}"""


def analyzer_node(state: PipelineState) -> dict:
    """Pick top 3 candidate subjects from research data, ranked best-first."""
    import json as _json

    client = get_client()
    model = get_model()

    skip_str = ", ".join(state.get("skip_subjects", [])) or "(none)"
    selection_rule = _SELECTION_RULES.get(
        state.get("selection_mode", "insight"), _SELECTION_RULES["insight"]
    )
    prompt = _ANALYZER_PROMPT.format(
        selection_rule=selection_rule,
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

Each chain must be logical consequences of the previous link — do NOT invent a new causal mechanism or drag in a subject the research never covered just to keep the chain going. Do NOT fabricate — only use what's in the research. Pure logical projection from facts is fine, and state each level plainly and confidently; the concern is inventing an unsupported link or subject, not the confidence of the phrasing.

After exploring, choose exactly TWO angles for the final post: the single strongest angle, plus one that creates real tension or contrast with it (a counterpoint, a complication, an opposing force). These two chains are the ONLY ones that will reach the writer — do not pick two angles that just restate each other.

Subject: {subject}
Reason this is interesting: {reason}

Research context:
{research_data}

Output ONLY a JSON object:
{{"subject": "the chosen subject name", "relevant_subject": "closest configured subject", "chains": [{{"angle": "short angle name", "chain": ["level 1", "level 2", ...], "verdict": "this angle's dominant outcome and why"}}], "chosen_angles": ["angle name 1", "angle name 2 — the contrasting one"]}}"""


def thinker_node(state: PipelineState) -> dict:
    """Trace consequence chains from multiple perspectives for the chosen subject."""
    import json as _json

    candidates = state.get("candidates", [])
    if not candidates:
        print("      Thinker: no candidates, using fallback")
        return {"subject": "AI", "chains": {}, "relevant_subject": "AI"}

    # Weighted random pick, biased toward the analyzer's top ranking but not
    # locked to it — otherwise near-identical research across nearby runs
    # (same subjects, "top of week" sources) always resurfaces the same
    # subject and thus the same angles, run after run.
    weights_by_count = {1: [1.0], 2: [0.65, 0.35], 3: [0.55, 0.30, 0.15]}
    top = candidates[:3]
    weights = weights_by_count[len(top)]
    chosen = random.choices(top, weights=weights, k=1)[0]
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

    # Narrow to the two angles the Thinker itself picked, so the Writer physically
    # cannot blend in the other explored angles — passing all 4-6 chains downstream
    # was why posts read as a scattershot list of unrelated claims instead of one
    # coherent argument.
    chosen_angles = data.get("chosen_angles", [])
    selected = chains_list
    if isinstance(chosen_angles, list) and chosen_angles:
        chosen_lower = {a.lower() for a in chosen_angles if isinstance(a, str)}
        matched = [
            c
            for c in chains_list
            if isinstance(c, dict) and c.get("angle", "").lower() in chosen_lower
        ]
        if matched:
            selected = matched
    selected = selected[:2] if selected else chains_list[:2]
    # The Thinker is asked for two angles in tension; if its chosen_angles field
    # only names one (typo, or it just returned one), pad back up to 2 from the
    # remaining explored chains so a single angle doesn't silently become the
    # whole post's frame — losing the "counterpoint" that keeps it one argument
    # rather than a flat, uncontested claim.
    if len(selected) < 2:
        selected_ids = {id(c) for c in selected}
        for c in chains_list:
            if len(selected) >= 2:
                break
            if id(c) not in selected_ids:
                selected.append(c)
    print(f"      Thinker: writing with {[c.get('angle', '?') for c in selected]}")

    return {
        "subject": data.get("subject", subject),
        "chains": {
            **data,
            "chains": selected,
        },  # only the chosen angle(s) reach the Writer
        "relevant_subject": data.get("relevant_subject", relevant),
    }


def writer_node(state: PipelineState) -> dict:
    """Write the LinkedIn post using the Thinker's chains."""
    import json as _json

    chains_data = state.get("chains", {})
    research_data = state.get("research_data", "")
    fixes = state.get("fixes", [])
    previous_post = state.get("post_raw", "")
    content_config = state.get("content_config") or {}
    is_retry = bool(fixes and previous_post)

    if not chains_data:
        return {"post_raw": "", "title": "", "hashtags_raw": ""}

    client = get_client()
    model = get_model()

    # Format chains and research for the Writer
    chains_json = _json.dumps(chains_data, indent=2)

    tone = content_config.get("tone", "direct and conversational")
    style = content_config.get("style", "personal and raw")
    language = content_config.get("language", "English")
    custom = content_config.get("custom_instructions", "")

    retry_block = (
        f"""
This is a REVISION, not a fresh draft. Here is the post you wrote last time:

{previous_post}

The Judge flagged these specific issues with it:
{"; ".join(fixes)}

Make the SMALLEST edit that resolves each flagged issue — rewrite or cut only the sentences/clauses named above. Keep every other sentence, claim, and the overall structure exactly as they were. Do not rewrite the post from scratch and do not touch anything the Judge didn't flag.
"""
        if is_retry
        else ""
    )

    prompt = f"""You write LinkedIn posts. Your ONLY job: take this strategic analysis and turn it into a post.

{custom}

Analysis (from the Thinker):
{chains_json}

Research context:
{research_data}

WRITING RULES:
- Title in **bold** as first line (≤120 chars).
- You've been given exactly two angles above, chosen because they create tension with each other. Weave them into ONE coherent argument with a clear throughline — do not treat them as separate sections, and do not introduce a third angle.
- Write like you're texting a smart friend. Short sentences. Fragments. Contractions.
- No \"The [noun] is [adjective]\" openers. No \"However\", \"Furthermore\". No transitions.
- No hyperbole. No apocalyptic language. No fabricated anecdotes. Every concrete fact must trace to research.
- When you're drawing a conclusion, connecting two facts, or projecting forward, state it with the same confident, decisive voice as everything else — don't invent a causal link the research doesn't support, and don't smuggle in a new subject the research never covered, but a flat, no-hedge sentence is the house style, not a violation.
- No section headers (like \"The Upside\" or \"The Downside\").
- **Bold** for 2-4 key phrases. *Italic* for internal thoughts.
- Bullet points plain text. No parallel structure.
- End with a strong thought, not engagement bait.
- Include 5-6 hashtags at the end. At least one link from the research on its own line before hashtags.
- Length: 1200-1800 chars. No emojis, no dashes, no name-drops.
- Tone: {tone}. Style: {style}. Language: {language}.

{retry_block}

Output ONLY a JSON object:
{{"title": "THE BOLD TITLE — max 120 chars, first line of the post", "post": "the full post text starting with the bold title on line 1", "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6"}}

The post field MUST start with the title in **bold** as its very first line. No exceptions. Example:
"**Agents Are Building Themselves**\n\nThe shift is real..." — title on line 1, blank line, then body."""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4 if is_retry else 0.85,
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

    # Ensure title is the first line of the post. Compare with markdown/whitespace
    # stripped from both sides so paraphrasing or a missing "**" doesn't trip a
    # false negative (title[:30] truncation was prone to that).
    def _normalize(text: str) -> str:
        return re.sub(r"[\s*]+", " ", text).strip().lower()

    if title and post:
        first_line = post.strip().split("\n", 1)[0]
        if not _normalize(first_line).startswith(_normalize(title)[:40]):
            post = "**" + title.strip(" *") + "**\n\n" + post

    print(
        f"      Writer: {len(post) if post else 0} chars, {len(hashtags.split()) if hashtags else 0} tags"
    )
    return {"post_raw": post, "title": title, "hashtags_raw": hashtags}


def judge_node(state: PipelineState) -> dict:
    """Verify every claim against research. Flag fabricated URLs and claims."""
    import json as _json

    post_raw = state.get("post_raw", "")
    research_data = state.get("research_data", "")

    # retry_count is bumped here (inside a node) rather than in the should_retry
    # router: LangGraph only persists state updates returned from nodes, so a
    # mutation made inside a conditional-edge function is silently discarded.
    def _result(approved: bool, fixes: list[str]) -> dict:
        retry_count = state.get("retry_count", 0)
        if not approved:
            retry_count += 1
        return {"approved": approved, "fixes": fixes, "retry_count": retry_count}

    if not post_raw:
        # An empty post means the Writer failed (API error, JSON parse failure,
        # or missing chains) — that's a rejection to retry, not an approval.
        print("      Judge: REJECTED — empty post from Writer")
        return _result(False, ["Writer produced an empty post — try again."])

    # Code-level check: any URL in the post that isn't in the research is FABRICATED
    fix_list = []
    urls_in_post = re.findall(r"https?://[^\s<>\"\']+", post_raw)
    for url in urls_in_post:
        clean_url = url.rstrip(".,;:!?")
        if clean_url not in research_data:
            fix_list.append(
                f"FABRICATED URL: {clean_url} — does not exist in research. Remove or replace with a real URL from research."
            )

    def _strip_fences(raw: str) -> str:
        raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        return raw.strip()

    def _parse_json_loose(raw: str, bracket_pattern: str):
        raw = _strip_fences(raw)
        try:
            return _json.loads(raw)
        except _json.JSONDecodeError:
            match = re.search(bracket_pattern, raw, re.DOTALL)
            if not match:
                return None
            try:
                return _json.loads(match.group(0))
            except _json.JSONDecodeError:
                return None

    claim_types = """   - Fact (stated plainly, no hedge)
   - Calculation (arithmetic/aggregation over reported numbers)
   - Interpretation (a hedged reading of what a fact means: "may," "suggests," "could indicate")
   - Causal inference (asserts X caused/causes Y)
   - Forecast (a projection about the future)
   - Recommendation (advice — what someone should do)
   - Rhetorical framing (a maxim, aphorism, or slogan-style restatement, e.g. "whoever controls X controls Y")"""

    def _classify_claims(client, model) -> list[dict]:
        """Separate structured pass: extract each substantive claim, its type as
        stated in the post, and the closest research statement (and its type) for
        the same underlying point. Kept separate from the fabrication/coherence
        judgment below so classification doesn't get done silently, inline, and
        unverifiably as a side effect of a differently-focused prompt."""
        prompt = f"""Extract every substantive claim from this LinkedIn post — every sentence or clause asserting something (skip filler, greetings, hashtags).

For each claim, classify its TYPE as it appears in the post, using exactly one of:
{claim_types}

Then find the closest matching statement in the research data for the same underlying point, quote it (or write "NONE" if the research says nothing related), and classify ITS type using the same list.

Research data:
{research_data}

Post:
{post_raw}

Output ONLY a JSON array, one object per claim:
[{{"claim": "exact claim text from the post", "post_type": "...", "research_basis": "quoted research sentence or NONE", "research_type": "... or NONE"}}]"""

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            raw = resp.choices[0].message.content or ""
        except Exception as e:
            print(f"      Judge claim classification failed: {e}")
            return []

        claims = _parse_json_loose(raw, r"\[.*\]")
        return claims if isinstance(claims, list) else []

    def _format_claims(claims: list[dict]) -> str:
        if not claims:
            return "(classification unavailable — judge claims directly against research data below)"
        lines = [
            f'- CLAIM: "{c.get("claim", "")}" | post_type={c.get("post_type", "?")} '
            f'| research_basis="{c.get("research_basis", "NONE")}" | research_type={c.get("research_type", "NONE")}'
            for c in claims
        ]
        return "\n".join(lines)

    # LLM-level check: verify concrete claims against research
    if research_data:
        client = get_client()
        model = get_model()

        claims = _classify_claims(client, model)
        claims_block = _format_claims(claims)

        prompt = f"""You are an editor. Your ONLY job: scan this post for three kinds of problems.

A separate classification pass already extracted each substantive claim in the post, its rhetorical TYPE, and the closest research statement supporting it (if any):
{claims_block}

1. UNSUPPORTED CLAIM — using the classification above (re-derive it yourself if it says "unavailable"), apply a DIFFERENT bar depending on post_type:

   For Fact or Calculation claims (things presented as directly-reported information), first check: is this a specific, checkable assertion (a number, a named event, an action a named entity took/is taking) — or is it general, well-known, definitional background about what a tool/company/technology already does (e.g. "Claude Code writes code," "LLMs generate text," "ChatGPT is a chatbot")? Background/definitional statements are common knowledge, not claims that could be fabricated, and do NOT need a research_basis — never flag these just because research_basis is NONE. For the specific/checkable kind, flag it if:
   - research_basis is NONE — the entities/numbers/events don't appear in the research at all
   - it broadens the scope beyond what research_basis supports (e.g. research covers one company/segment, post generalizes to "the industry")
   - research_basis exists but is a DIFFERENT type (e.g. research_type=Recommendation "companies should adopt X") and the post states it as something already happening/true (post_type=Fact "companies are adopting X") — this converts a suggestion into a reported fact, which is a real fabrication even though a research_basis string is present

   For Interpretation, Causal inference, Forecast, Recommendation, or Rhetorical framing claims — these are the post's OWN synthesis/argument built on top of the facts, and are NOT required to have a literal matching sentence in the research, and are NOT required to be hedged. A confident, declarative "pick a side" voice is the intended house style — do not flag a claim just because it's stated flatly instead of with "may"/"suggests"/"could." Flag one of these ONLY if:
   - it invents a causal or mechanistic link between two facts the research only reports side-by-side or as correlated (e.g. research says "X launched" and separately "Y rose 15%"; post says "X caused Y to rise 15%" — the entities and number are real, but the causation is invented)
   - it generalizes an interpretation into a claim about a DIFFERENT subject the research never addressed (e.g. research_type=Interpretation "infrastructure ownership may improve strategic control" [about control] → post_type=Rhetorical framing "Whoever controls the chips controls the margin" [a new, broader claim about profit margins the research never discussed] — the confident delivery is fine, the smuggled-in new subject is not)
   - it directly contradicts something the research states as fact
   Confident synthesis that stays within the topic and relationships the research actually supports is exactly what this pipeline is for — only flag genuine invention (new causal links, new subjects, contradictions), not confident tone.

2. INCOHERENCE — the post should build ONE coherent argument around two angles that create tension with each other. Flag it as incoherent if it instead reads as a list of disconnected claims stitched together — e.g. jumping between unrelated topics (a technical breakthrough, then labor markets, then legal liability, then market consolidation) with no logical throughline connecting them, or drawing a conclusion that doesn't actually follow from the claim before it. This includes a subtler version: check whether a single repeated word or phrase (e.g. "trust," "governance," "velocity") is the ONLY thing connecting two or more research threads that are otherwise unrelated — if two paragraphs each cite a different news item and the only link between them is that both use the same buzzword, that is buzzword-glued, not argued, and counts as incoherent even though every individual sentence reads smoothly. A real throughline means the SECOND claim is a consequence, complication, or contrast of the FIRST — not just a claim that happens to share a keyword with it.

3. SELF-CONTRADICTION — flag any pair of claims within the post that directly conflict with each other (e.g. "not replacing coders" and "stripping execution roles") when the post never reconciles the tension. Quote both conflicting passages.

Style, tone, and formatting are NOT your concern. Only check factual accuracy and argumentative coherence.

Research data:
{research_data}

Post to verify:
{post_raw}

Output ONLY a JSON object:
{{"approved": true or false, "unsupported_claims": ["exact passage — what the research actually supports vs. what the post asserts"], "incoherence_issues": ["specific description of the logical gap or unrelated jump 1"], "self_contradictions": ["passage A vs. passage B — how they conflict"]}}

approved=true only if EVERY fact traces to the research, no claim invents a causal link or smuggles in a new subject the research never covered, no two claims in the post contradict each other unreconciled, AND the post reads as one coherent argument (unsupported_claims=[], incoherence_issues=[], self_contradictions=[])."""

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
            return _result(approved, fix_list)

        data = _parse_json_loose(raw, r"\{.*\}")
        if data is None:
            approved = len(fix_list) == 0
            return _result(approved, fix_list)

        llm_fixes = (
            data.get("unsupported_claims", [])
            + data.get("incoherence_issues", [])
            + data.get("self_contradictions", [])
        )
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

    return _result(approved, fix_list)


def should_retry(state: PipelineState) -> str:
    """Decision: loop back to writer if judge rejected and retry count <= max.

    retry_count is incremented by judge_node itself (a real node, so the update
    persists) the moment a rejection happens, so by the time we get here it
    already reflects how many rejections have occurred so far. Reading it here
    is purely a routing decision — this function must NOT mutate state.
    """
    max_retries = 2
    approved = state.get("approved", True)
    retries = state.get("retry_count", 0)
    if not approved and retries <= max_retries:
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
    # Resolved AI client config (env vars still win — ai_config already encodes
    # that precedence per main.py) — only the *values*, so the cached client
    # picks them up on first use without needing get_client()/get_model() to
    # take arguments.
    if ai_config:
        if ai_config.get("base_url"):
            os.environ["AI_BASE_URL"] = ai_config["base_url"]
        if ai_config.get("api_key"):
            os.environ["AI_API_KEY"] = ai_config["api_key"]
        if ai_config.get("model"):
            os.environ["AI_MODEL"] = ai_config["model"]

    # Build research data string
    parts = []
    for v in youtube_videos[:20]:
        parts.append(
            f"YT [{getattr(v, 'source_subject', '')}]: {v.title} ({v.views} views)"
        )
    for p in reddit_posts[:20]:
        parts.append(
            f"Reddit r/{getattr(p, 'subreddit', '')} ({getattr(p, 'score', 0)} upvotes): {getattr(p, 'title', '')}"
        )
    for t in twitter_posts[:10]:
        parts.append(
            f"Twitter @{getattr(t, 'author', '')}: {getattr(t, 'text', '')[:200]}"
        )
    for n in news_items[:20]:
        parts.append(
            f"Web [{getattr(n, 'source_subject', '')}]: {getattr(n, 'title', '')} — {getattr(n, 'snippet', '')[:100]} ({getattr(n, 'url', '')})"
        )
    for ci in channel_insights or []:
        parts.append(
            f"Channel {ci.get('channel', '')} [{ci.get('topic_tag', '')}] "
            f"({ci.get('count', 0)} videos): {ci.get('videos', '')}"
        )
    research_data = "\n".join(parts)

    state = {
        "research_data": research_data,
        "skip_subjects": skip_subjects or [],
        "selection_mode": selection_mode,
        "configured_subjects": subjects,
        "content_config": content_config or {},
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

    # If the Judge never approved the post even after exhausting retries,
    # do not publish it — a flagged (possibly fabricated) post is worse than
    # no post at all.
    if post_raw and not final.get("approved", True):
        print("[!] Judge did not approve the post after max retries — discarding.")
        return "", ""

    # Apply formatting (Unicode bold/italic) — same as old _format_for_linkedin
    from src.generate import _format_for_linkedin

    post_formatted = _format_for_linkedin(post_raw)

    # Inject hashtags if missing
    if "#" not in post_formatted and hashtags_raw:
        post_formatted = post_formatted.rstrip() + "\n\n" + hashtags_raw.strip()

    # Link validation: only keep URLs from actual research.
    # NOTE: word-overlap must be computed from the *raw* (pre-Unicode-bold/
    # italic) text — _to_unicode_bold/_to_unicode_italic map ASCII letters to
    # Mathematical Alphanumeric Symbols, which `[a-z]` and `.lower()` don't
    # recognize at all, so matching against post_formatted silently drops
    # every bolded/italicized word from the overlap count.
    if news_items:
        chosen_lower = (relevant_subject or "").lower()
        relevant_subjects = {
            s.lower()
            for s in subjects
            if s.lower() in chosen_lower or chosen_lower in s.lower()
        }
        if not relevant_subjects:
            relevant_subjects = {s.lower() for s in subjects}

        fetched_urls = {n.url for n in news_items if n.url}
        post_words = set(re.findall(r"[a-z]{4,}", post_raw.lower()))
        post_words -= {"that", "this", "with", "from", "have", "they", "will"}
        valid_urls = set()
        for n in news_items:
            if not n.url or n.url not in fetched_urls:
                continue
            article_words = set(
                re.findall(r"[a-z]{4,}", (n.title + " " + n.snippet).lower())
            )
            overlap = post_words & article_words
            # High overlap alone is enough (cross-cutting article); moderate
            # overlap needs subject agreement too, matching the old generate().
            if len(overlap) >= 5 or (
                len(overlap) >= 3
                and getattr(n, "source_subject", "").lower() in relevant_subjects
            ):
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

                new_line = url_pattern.sub(_replace_url, line)
                stripped = new_line.strip()
                # If every URL on the line got stripped and what's left is just
                # a dangling reference ("Check this out:"), drop the line
                # entirely instead of leaving an orphaned sentence.
                if not url_pattern.search(new_line) and (
                    (len(stripped) < 60 and stripped.rstrip(".").endswith(":"))
                    or stripped.lower().rstrip(".")
                    in {"link", "source", "reference", "here"}
                ):
                    continue
                line = new_line
            filtered_lines.append(line)
        post_formatted = "\n".join(filtered_lines)

    return post_formatted, relevant_subject or "AI"
