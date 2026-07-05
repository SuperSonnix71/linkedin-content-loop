# LinkedIn Content Loop

Automated LinkedIn content pipeline that researches trending topics across 4 sources, generates engaging posts using tree-of-thought reasoning with impact-weighted analysis, and posts via browser automation. No paid APIs required.

## How It Works

```
┌──────────────────────────────────────────────────────────────┐
│  RESEARCH (4 sources, no paid APIs)                          │
│                                                              │
│  YouTube ── yt-dlp keyword search + channel scraping         │
│  Reddit  ── RSS feeds (bypasses Cloudflare bot detection)    │
│  Twitter ── Nitter RSS (Sam Altman, Anthropic, OpenAI, etc.) │
│  Web     ── SearXNG (aggregates Google, Bing, DuckDuckGo)    │
│                                                              │
│  Auto-extracts trending topics from YouTube channel titles   │
│  and adds them as additional search subjects dynamically     │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  GENERATION (tree-of-thought reasoning)                      │
│                                                              │
│  Step 1: EXPLORE — read research, find patterns              │
│  Step 2: PICK AXES — select 3-5 dimensions to analyze        │
│  Step 3: GO DEEP — trace positive + negative chains          │
│  Step 4: WEIGH BY IMPACT — scope, severity, irreversibility  │
│  Step 5: PICK SUBJECT — by volume or by insight              │
│  Step 6: FIND THREAD — where axes intersect                  │
│  Step 7: WRITE 3 TITLES — pick the best one                  │
│  Step 8: WRITE POST — human voice, LinkedIn formatting       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  POSTING (Playwright browser automation)                     │
│                                                              │
│  Headless Chromium → LinkedIn login → "Start a post"         │
│  → type content → click Post → verify success                │
│  Session persisted in browser-profile/ for reuse              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  TRACKING (PostgreSQL)                                       │
│                                                              │
│  Logs: subject, title, content, hashtags, selection mode     │
│  Enforces: daily/weekly/monthly quotas                       │
│  Prevents: subject repetition within 7 days                  │
│  Auto-balances: volume vs insight subject selection          │
└──────────────────────────────────────────────────────────────┘
```

## Subject Selection

### Where subjects come from

1. **Config-defined** (`config.yaml` → `subjects`): You define the topics to research. Example: AI, LLM, agents, Claude, OpenAI, Anthropic, startup lessons, AI safety, etc.

2. **Auto-extracted from YouTube channels**: The pipeline scrapes video titles from configured channels (Matthew Berman, Lex Fridman, Y Combinator) and dynamically extracts the most frequent keywords. These become additional search subjects. No hardcoded word lists — fully adapts as channel content changes.

### How it picks what to write about

Two modes, controlled by `SUBJECT_SELECTION` in `.env`:

| Mode | Logic | When to use |
|------|-------|-------------|
| **volume** | Picks the subject with the most YouTube views, Reddit posts, and web articles | When you want to ride what's trending |
| **insight** | Picks the subject where the gap between what people believe and what the evidence shows is widest | When you want counter-intuitive, thought-provoking content |

**Auto-balance** (default when `SUBJECT_SELECTION` is commented out): The pipeline queries the database for how many posts used each mode in the last 7 days and automatically alternates. If 3 posts used "insight" and 1 used "volume", the next post uses "volume" to maintain a 50/50 mix.

## Tree-of-Thought Process

The LLM doesn't just write — it thinks first. The prompt enforces an 8-step reasoning process:

### Step 1 — Explore Freely
Read all research (YouTube, Reddit, Twitter, web news). What patterns jump out? What numbers stop you? Follow threads: "If this is true, what happens next? Who gets hurt? Who wins?"

### Step 2 — Pick 3-5 Axes
Identify the most important dimensions to analyze. Examples:
- Companies (who's affected, who owns the IP)
- Cost (token economics, renting vs owning)
- Future of work (unemployment, new underclass, role changes)
- Data privacy (what leaves your network, audit trails)
- Power concentration (duopoly risk, pricing control)

The model picks its own axes based on what the research surfaces — not a fixed list.

### Step 3 — Go Deep (both sides)
For each axis, trace BOTH chains:
- **Positive**: What improves? Who benefits? What new possibilities open?
- **Negative**: What breaks? Who gets hurt? What's the hidden cost?

Go 2-3 levels deep on each side with specific timeframes (3 months, 1 year, 5 years).

### Step 4 — Weigh by Impact
Not by count — by **impact magnitude**. Each finding is assessed across:
- **SCOPE**: How many people/companies/industries are affected?
- **SEVERITY**: How bad or good is the outcome?
- **IRREVERSIBILITY**: Can it be undone, or is it permanent?
- **TIMEFRAME**: When does it hit?

A single existential threat (e.g., "$25T credit collapse = global recession") can outweigh three moderate benefits (e.g., "inference costs dropped 30%"). The model explicitly states which side wins and why the impact magnitude tipped the scale.

### Step 5 — Pick Subject
Based on the weighted conclusion, pick the ONE subject that connects the strongest prediction to something happening right now.

### Step 6 — Find the Thread
Where do the axes and chosen subject intersect? That's the core idea — the insight that makes people stop scrolling.

### Step 7 — Write 3 Titles
Generate 3 distinct title options using different hook types (sharp observation, blunt warning, uncomfortable truth). Pick the best one. All output is visible in the logs so you can see what was considered.

### Step 8 — Write the Post
Using the chosen title as the first line, write in a human, conversational voice. Apply LinkedIn formatting rules (see below).

## Impact Weighting System

The pipeline doesn't produce doom-and-gloom posts every time. It weighs both sides honestly:

```
For each axis:
  Positive chain → scope, severity, irreversibility, timeframe
  Negative chain → scope, severity, irreversibility, timeframe

Tally by IMPACT MAGNITUDE (not count):
  Example:
    Positive: "Teams save 30% on inference" → moderate, gradual, reversible
    Negative: "$25T credit collapse" → global, catastrophic, permanent

  Verdict: Negatives dominate (existential > moderate)

If negatives win → warning post
If positives win → optimistic post
If balanced → explore the tension honestly
```

This prevents the "doom prophet" problem where every post is negative. The evidence decides the tone.

## LinkedIn Formatting

LinkedIn posts are plain text — no native bold, italic, or markdown. The pipeline uses Unicode characters for formatting:

| Marker in prompt | Converted to | Purpose |
|------------------|-------------|---------|
| `**bold text**` | 𝗯𝗼𝗹𝗱 𝘁𝗲𝘅𝘁 (Mathematical Sans-Serif Bold) | Titles, key phrases, transitional phrases |
| `*italic text*` | 𝘪𝘵𝘢𝘭𝘪𝘤 𝘵𝗲𝘹𝘵 (Mathematical Sans-Serif Italic) | Internal thoughts, asides, doubts |
| `•` | • (passed through) | Bullet points (always plain text) |

### Formatting rules
- **Title**: First line, always bold
- **Bold**: 2-4 key phrases max, including transitional phrases that introduce sections or bullet lists
- **Italic**: For internal dialogue, asides, "air quotes"
- **Bullet points**: Always plain text — never bold, never italic
- **Links**: Max 1-2, at the END of the post on their own lines. Only from web research (news articles, official docs, research papers). Never YouTube, Twitter, or creator content.
- **Hashtags**: 5-6 at the very end. Mix of broad high-reach (#AI, #ArtificialIntelligence) and specific niche tags. Model picks them based on the post content.
- **No emojis, no dashes, no name-drops, no rhetorical questions, no corporate speak**

### Link validation
After generation, every URL in the post is validated against the actual web research results. Any URL that doesn't exist in the SearXNG results is stripped out — even if the model hallucinated one or grabbed from a different subject.

## Research Sources

### YouTube (yt-dlp)
- Keyword search for each subject (`ytsearch5:AI`, `ytsearch5:LLM`, etc.)
- Channel scraping for specific creators (Matthew Berman, Lex Fridman, Y Combinator)
- Returns: title, URL, channel, view count, description
- No API key required

### Reddit (RSS feeds)
- Fetches top weekly posts from configured subreddits
- Uses RSS endpoint (`/r/{sub}/top.rss?t=week`) which bypasses Cloudflare bot detection
- Returns: title, URL, selftext (parsed from HTML)
- 1.5 second delay between subreddits to avoid rate limiting

### Twitter/X (Nitter RSS)
- Fetches recent tweets from configured accounts via Nitter RSS
- Tracks: Sam Altman, OpenAI, Greg Brockman, Anthropic, Dario Amodei, Andrej Karpathy, Yann LeCun, Ethan Mollick, Hugging Face, Mistral AI, Jack Clark
- No API key, no browser required

### Web Search (SearXNG)
- Searches each subject via SearXNG (aggregates Google, Bing, DuckDuckGo)
- Returns: title, URL, snippet, source_subject
- Used for evidence-based claims with real links in posts
- No API key required

## Scheduling & Quotas

Configured in `config.yaml`:

```yaml
schedule:
  posts_per_day: 1        # max posts per day
  posts_per_week: 5       # max posts per week
  posts_per_month: 20     # max posts per month
  post_times: ["09:00"]   # when to attempt posting
  days: [monday-friday]   # which days
```

Before each scheduled post, the pipeline checks the database:
- Daily quota reached? → Skip
- Weekly quota reached? → Skip
- Monthly quota reached? → Skip
- Subject already posted in last 7 days? → Skip that subject, pick another

## Database

PostgreSQL auto-creates on first run. Schema:

```sql
posts (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMP DEFAULT NOW(),
  subject         TEXT NOT NULL,
  title           TEXT,
  content         TEXT NOT NULL,
  hashtags        TEXT,
  char_count      INTEGER,
  selection_mode  TEXT DEFAULT 'insight',  -- volume or insight
  posted          BOOLEAN DEFAULT FALSE
)
```

Used for:
- **Quota tracking**: COUNT queries per day/week/month
- **Deduplication**: Subjects posted in last 7 days are skipped
- **Auto-balance**: Counts volume vs insight posts to alternate modes
- **Post history**: Full content of every post for reference

## AI Model

Any OpenAI SDK-compatible endpoint works:

| Provider | base_url | Notes |
|----------|----------|-------|
| Ollama | `http://localhost:11434/v1` | Free, local. Any non-empty API key. |
| LM Studio | `http://localhost:1234/v1` | Free, local |
| Groq | `https://api.groq.com/openai/v1` | Free tier, fast inference |
| OpenRouter | `https://openrouter.ai/api/v1` | Multiple models, free tier available |

Configured via `.env`:
```
AI_BASE_URL=http://mega:11434/v1
AI_API_KEY=ollama
AI_MODEL=qwen3.6:35b
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/SuperSonnix71/linkedin-content-loop.git
cd linkedin-content-loop

# 2. Create virtual env
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 3. Configure
cp .env.example .env
# Edit .env with your credentials
# Edit config.yaml with your subjects, channels, schedule

# 4. Test (no posting)
python test_pipeline.py

# 5. Run once (full pipeline + post)
python main.py --run-now

# 6. Start scheduler
python main.py
```

## Docker Deployment

```bash
cd docker/
docker compose up -d              # start scheduler
docker compose logs -f            # view logs
docker compose run --rm linkedin-loop python test_pipeline.py  # test
docker compose down               # stop
```

See [docker/README.md](docker/README.md) for full deployment guide.

## Configuration

### config.yaml
- **subjects**: Topics to research (AI, LLM, agents, Claude, etc.)
- **youtube.channels**: Specific YouTube channels to scrape
- **reddit.subreddits**: Subreddits to monitor
- **twitter.accounts**: Twitter/X accounts to track via Nitter
- **searxng.base_url**: SearXNG instance URL
- **content.tone/style/language**: Voice and style settings
- **content.custom_instructions**: Additional rules for the model
- **schedule**: Post frequency, times, days, quotas

### .env
- `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` — LLM endpoint
- `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD` — LinkedIn credentials
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — PostgreSQL
- `SUBJECT_SELECTION` — Optional: force `volume` or `insight` (comment out for auto-balance)

## Project Structure

```
linkedin-content-loop/
├── main.py              # Scheduler + pipeline orchestrator
├── test_pipeline.py     # Test without posting to LinkedIn
├── config.yaml          # All configuration (subjects, schedule, tone)
├── requirements.txt     # Python dependencies
├── .env.example         # Template for secrets
├── .env                 # Your secrets (gitignored)
├── src/
│   ├── research.py      # YouTube + Reddit + Twitter + SearXNG
│   ├── generate.py      # Tree-of-thought LLM generation + formatting
│   ├── post.py          # Playwright LinkedIn browser automation
│   └── db.py            # PostgreSQL tracking + auto-balance
└── docker/
    ├── Dockerfile       # Python 3.12 + Playwright + Chromium
    ├── docker-compose.yml
    └── README.md        # Docker deployment guide
```

## License

MIT
