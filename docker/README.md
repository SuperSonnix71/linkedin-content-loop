# Docker — LinkedIn Content Loop

## Architecture

```
NUC (Docker host)
├── linkedin-content-loop container (host networking)
│   ├── main.py scheduler (Mon-Fri 09:00, 13:00)
│   ├── research.py → YouTube + Reddit + Twitter + SearXNG
│   ├── generate.py → LLM via Ollama (OpenAI SDK compatible)
│   ├── post.py → Playwright headless Chromium
│   └── db.py → PostgreSQL (external)
│
├── Volumes:
│   └── browser-profile/ (LinkedIn session persistence)
│
└── Config:
    ├── config.yaml (mounted read-only)
    └── .env (env_file — secrets)
```

## Services required on host network

The container uses `network_mode: host` so it can reach local services by hostname:

| Service | Address | Purpose |
|---------|---------|---------|
| PostgreSQL | `192.168.1.234:5432` | Post tracking, dedup, quotas |
| Ollama | `mega:11434` | LLM inference (qwen3.6:35b) |
| SearXNG | `search.nuc:8081` | Web search for evidence |

## Environment

All secrets in `.env` (mounted via `env_file`):
- `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`
- `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD`
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `SUBJECT_SELECTION` (optional: volume/insight)

## 2FA Note

The container runs Playwright headless — no visible browser. If LinkedIn requires 2FA on first login from the container, the session can't be established automatically.

**Fix**: Log in once on your host machine (not Docker) to populate `browser-profile/`:
```bash
# On your laptop:
cd ~/Code/linkedin-content-loop
source .venv/bin/activate
# Temporarily set headless=False in src/post.py, then:
python main.py --run-now
# Complete 2FA in the browser window, then set headless=True back
```

The session cookies are saved to `browser-profile/` and persist across container restarts via the Docker volume.

## Commands

```bash
# View logs
ssh nuc "docker logs -f linkedin-content-loop"

# Stop
ssh nuc "cd ~/Code/linkedin-content-loop/docker && docker compose down"

# Start
ssh nuc "cd ~/Code/linkedin-content-loop/docker && docker compose up -d"

# Run once now (full pipeline + post)
ssh nuc "cd ~/Code/linkedin-content-loop/docker && docker compose run --rm linkedin-loop python main.py --run-now"

# Test only (no posting)
ssh nuc "cd ~/Code/linkedin-content-loop/docker && docker compose run --rm linkedin-loop python test_pipeline.py"
```

## Local commands (not SSH)

If you're on the nuc directly:

```bash
# Start the scheduler
cd ~/Code/linkedin-content-loop/docker && docker compose up -d

# Test without posting
docker compose run --rm linkedin-loop python test_pipeline.py

# Run full pipeline once
docker compose run --rm linkedin-loop python main.py --run-now

# View logs
docker logs -f linkedin-content-loop

# Stop
docker compose down
```

## Rebuilding after code changes

```bash
# On your laptop — push updates to nuc
rsync -avz --exclude '.venv' --exclude 'browser-profile' --exclude '__pycache__' \
  ~/Code/linkedin-content-loop/ nuc:~/Code/linkedin-content-loop/

# On nuc — rebuild and restart
ssh nuc "cd ~/Code/linkedin-content-loop/docker && docker compose build && docker compose up -d"
```
