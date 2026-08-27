# autogram

autogramworld

**Free, open-source, self-hosted Instagram auto-poster.** Given one standing
content theme and Instagram credentials, autogram generates a fresh, non-repeating
image (self-hosted diffusion) and caption (self-hosted LLM) and posts it — on your
machine or unattended on the GitHub Actions free tier. **No paid APIs, no hosted
inference.** Every model runs locally.

- 🎨 Image generation with `diffusers` (default `Lykon/dreamshaper-8`, photoreal on CPU; `sd-turbo` for speed)
- ✍️ Captions/hashtags/alt-text with a local **Ollama** LLM (default `qwen2.5:3b-instruct`)
- 🔁 Never repeats: seeded variation + history-aware divergence + near-duplicate rejection
- 🛡️ Safety gates: NSFW, degenerate-image, profanity — any failure aborts cleanly
- 🔌 Two fully-implemented posting backends: `instagrapi` (private API) and `graph` (official)
- 🤖 Runs identically locally and on `ubuntu-latest` (4 vCPU / 16 GB / no GPU)

> ⚠️ **Terms-of-Service notice.** The **`instagrapi`** backend uses Instagram's
> **private API**, which **violates Instagram's Terms of Service** and can get an
> account **rate-limited, challenged, or banned**. Use a **dedicated/burner
> account**, keep volume to **1–2 posts/day**, and **prefer the `graph` backend**
> (official API) for anything that matters. You use this at your own risk.

---

## Architecture

```
                      ┌──────────────────────────────────────────────────┐
   config.yaml  ─────▶│                  autogram.run                     │
   (theme, models,    │              orchestration + CLI                  │
    gates, ...)       └───┬───────┬────────┬─────────┬────────┬─────────┬─┘
                          │       │        │         │        │         │
   secrets (env) ─────────┤       ▼        ▼         ▼        ▼         ▼
   IG_*, POST_BACKEND     │   ┌────────┐┌────────┐┌────────┐┌───────┐┌────────┐
                          └──▶│ brief  ││imagegen││postproc││caption││ safety │
                              │  LLM   ││diffusers││ Pillow ││  LLM  ││ gates  │
                              └───┬────┘└───┬────┘└───┬────┘└──┬────┘└───┬────┘
                                  │ theme→  │ prompt→ │ PNG→   │ brief→  │ abort
                                  │ brief   │ PNG     │ JPEG   │ caption │ on fail
                                  ▼         ▼         ▼        ▼         │
                              ┌──────────────────────────────────────┐  │
                              │              state.py                 │◀─┘
                              │   history.json: dedupe, idempotency,  │
                              │   recent-briefs context, audit trail  │
                              └───────────────────┬──────────────────┘
                                                  ▼
                              ┌──────────────────────────────────────┐
                              │           poster/  (POST_BACKEND)     │
                              │   InstagrapiPoster  |  GraphApiPoster │
                              │   (private API)     |  (official +    │
                              │                     |   ImageHost)    │
                              └──────────────────────────────────────┘
```

Each stage is an independent module behind a small interface, so any stage can be
swapped without touching the others. Full pipeline:

```
theme → brief (LLM) → SD prompts → image (diffusers) → image gates → JPEG (Pillow)
      → idempotency check → caption+hashtags+alt (LLM) → caption gate → publish → history
```

---

## Quick start

See **[QUICKSTART.md](QUICKSTART.md)** for the 5-minute version. In short:

```bash
make setup          # venv + CPU torch + deps + Ollama-managed-at-runtime
cp .env.example .env # fill in credentials
# edit config/config.yaml → set your `theme`
make dry-run        # generate image + caption, save to out/, post NOTHING
```

`make dry-run` on a clean Linux CPU machine produces a valid `1080×1080` JPEG and a
caption `.txt` in `out/`, with no GPU and no paid API.

---

## CLI

```bash
python -m autogram.run                        # full pipeline from config
python -m autogram.run --description "..."    # one-off theme override
python -m autogram.run --dry-run              # generate + gate + save, do NOT post
python -m autogram.run --image-only           # skip caption and post
python -m autogram.run --seed 1234            # reproducible run
python -m autogram.run --log-level DEBUG
```

Exit codes (distinct per failure class): `0` ok, `1` config, `2` brief/LLM,
`3` image, `4` postproc, `5` caption, `6` safety gate, `7` publish, `8` duplicate.

---

## Configuration

All non-secret settings live in **`config/config.yaml`** (validated by pydantic).
Two logical inputs only: **Instagram credentials** (env) and the **content theme**
(config / `--description`). Everything else has a sane default.

Env vars override any YAML value:

```bash
AUTOGRAM_THEME="cats in tiny hats"       # override a top-level key
AUTOGRAM_IMAGE__STEPS=4                    # override nested keys with __
AUTOGRAM_GATES__NSFW=false
```

### Secrets (environment only — never in YAML)

| Variable          | Backend      | Purpose                                                        |
|-------------------|--------------|----------------------------------------------------------------|
| `POST_BACKEND`    | both         | `instagrapi` or `graph`                                         |
| `IG_USERNAME`     | instagrapi   | Login username                                                  |
| `IG_PASSWORD`     | instagrapi   | Login password (used only if the session is dead)              |
| `IG_SESSION_B64`  | instagrapi   | Base64 session settings — **strongly recommended** (see below) |
| `IG_PROXY`        | instagrapi   | Optional `http://user:pass@host:port`                          |
| `IG_ACCESS_TOKEN` | graph        | Long-lived access token                                         |
| `IG_USER_ID`      | graph        | Numeric IG Business/Creator user id                            |
| `GITHUB_TOKEN`    | graph        | For the default image host (auto-set in Actions)               |
| `GITHUB_REPOSITORY` | graph      | `owner/repo` for release-asset image URLs (auto-set in Actions)|
| `OLLAMA_HOST`     | both         | Existing daemon; else autogram starts its own (default `127.0.0.1:11434`) |

A logging filter redacts every secret value, so credentials never reach logs or the
committed `state/history.json`.

---

## Backend A — `instagrapi` (private API)

1. **Log in once locally** to create a session (this is where you'd clear any
   challenge/2FA interactively):

   ```bash
   POST_BACKEND=instagrapi IG_USERNAME=you IG_PASSWORD=secret \
     python -m autogram.run --dry-run
   ```

   On first successful login autogram writes `state/ig_session.json`.

2. **Seed `IG_SESSION_B64`** for CI from that session file:

   ```bash
   # base64 (no newlines) of the session settings JSON
   b64=$(base64 -w0 state/ig_session.json)      # macOS: base64 -i state/ig_session.json | tr -d '\n'
   gh secret set IG_SESSION_B64 --body "$b64"
   gh secret set IG_USERNAME --body "you"
   gh secret set IG_PASSWORD --body "secret"
   gh secret set POST_BACKEND --body "instagrapi"
   ```

   On every run autogram reloads the session and only falls back to a password
   login if the session is dead — this is the single biggest defense against
   challenges and bans. Device fingerprint and user agent are pinned so the
   fingerprint stays stable.

### Troubleshooting the instagrapi challenge flow

- **`ChallengeRequired`** — Instagram wants to "verify it's you". Open Instagram in
  the app/website **from the same IP** (or the proxy you use), approve the login,
  then re-run locally to refresh `state/ig_session.json` and re-seed
  `IG_SESSION_B64`. Do **not** keep retrying fresh password logins — that escalates.
- **`TwoFactorRequired`** — complete 2FA during the local login, then seed the
  session as above. CI cannot solve 2FA.
- **`PleaseWaitFewMinutes`** — you're rate-limited. autogram backs off with jitter
  and retries; if it persists, lower your posting frequency.
- **`LoginRequired`** — the stored session expired; autogram falls back to password
  login automatically and re-persists a new session.
- Keep to **1–2 posts/day**, one dedicated account, ideally a stable IP/proxy.

---

## Backend B — `graph` (official Instagram Graph API)

Requirements: an **Instagram Business/Creator** account linked to a **Facebook
Page**, a Meta app, a **long-lived access token**, and the numeric **IG user id**.

1. Create a Meta app (developers.facebook.com), add the **Instagram Graph API**
   product, and link your IG Business account to a Facebook Page.
2. Get a short-lived user token via the Graph API Explorer with scopes
   `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`.
3. **Exchange it for a long-lived token** (~60 days):

   ```bash
   curl -s "https://graph.facebook.com/v19.0/oauth/access_token\
   ?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET\
   &fb_exchange_token=SHORT_LIVED_TOKEN"
   ```

4. Find your IG user id:

   ```bash
   curl -s "https://graph.facebook.com/v19.0/me/accounts?access_token=LONG_TOKEN"
   # → page id, then:
   curl -s "https://graph.facebook.com/v19.0/PAGE_ID?fields=instagram_business_account&access_token=LONG_TOKEN"
   ```

5. Set secrets:

   ```bash
   gh secret set POST_BACKEND   --body "graph"
   gh secret set IG_ACCESS_TOKEN --body "LONG_TOKEN"
   gh secret set IG_USER_ID     --body "1789..."
   # GITHUB_TOKEN / GITHUB_REPOSITORY are provided automatically in Actions.
   ```

The Graph API needs a **publicly reachable image URL**. The default
`GitHubReleaseHost` uploads the JPEG as an asset on a dated GitHub Release using
`GITHUB_TOKEN` and derives its public URL. It implements the swappable `ImageHost`
interface, so you can drop in S3/R2/etc. Publishing is two steps (create media
container → poll until `FINISHED` → `media_publish`). Rate-limit headers
(`x-app-usage`) and the **25 posts / 24 h** quota are surfaced in the logs.

**Switching backends requires no code change** — only `POST_BACKEND`.

---

## Measured runtime & disk (reference)

Reference figures for a GitHub-hosted `ubuntu-latest` runner (4 vCPU, 16 GB RAM,
no GPU). Diffusion on CPU dominates wall-clock; the LLM and gates are minor.
Numbers are approximate and vary with runner load — see
[DECISIONS.md](DECISIONS.md) for how they were derived.

### Image models (CPU, 512²/1024² as noted)

| Model                              | Resolution | Steps | ~Wall-clock (CPU) | ~Disk (weights) | Notes                        |
|------------------------------------|-----------|-------|-------------------|-----------------|------------------------------|
| `segmind/tiny-sd`                  | 512²      | 1–4   | **~10–25 s**      | ~1.7 GB         | fastest; lower fidelity      |
| `stabilityai/sd-turbo`             | 512²      | 1–4   | **~20–60 s**      | ~2.6 GB         | fast fallback; plasticky/AI-looking |
| `Lykon/dreamshaper-8` *(default)*  | 512²      | 20–30 | **~3–8 min**      | ~4.0 GB         | photoreal on CPU; the realism ceiling without a GPU |
| `stabilityai/sdxl-turbo`           | 1024²     | 1–4   | **~3–6 min**      | ~6.9 GB         | higher quality; slow on CPU  |
| `black-forest-labs/FLUX.1-schnell` | 1024²     | 1–4   | GPU only (fp16)   | ~24 GB          | auto-selected when CUDA present |

### LLM models (Ollama)

| Model                    | ~Disk   | Host        | Notes                          |
|--------------------------|---------|-------------|--------------------------------|
| `qwen2.5:3b-instruct` *(default)* | ~2.0 GB | CPU runner  | comfortable on 4 cores         |
| `qwen2.5:7b-instruct`    | ~4.7 GB | GPU host    | auto-selected when CUDA present |
| `llama3.1:8b`            | ~4.9 GB | GPU host    | config-selectable              |

### Other costs

| Item                                    | ~Disk   |
|-----------------------------------------|---------|
| NSFW safety checker (`CompVis/...`)     | ~1.2 GB |
| CPU torch + diffusers + deps            | ~2.5 GB |

**Total warm-cache footprint** (default dreamshaper-8 + qwen2.5:3b + NSFW checker + deps)
≈ **9–10 GB**, under the runner's ~14 GB free disk and the **10 GB repo
cache ceiling**. Target scheduled run: **~10–15 minutes** with a warm cache — the
photoreal model spends a few minutes sampling (cold cache adds model-download
time). For sub-minute runs at lower fidelity, set `image.model` back to
`stabilityai/sd-turbo` (the code auto-switches to the distilled sampling path).

---

## GitHub Actions

- **`.github/workflows/post.yml`** — scheduled (`cron`, twice weekly by default) +
  manual `workflow_dispatch` (`description`, `dry_run`, `seed`). `concurrency`
  prevents overlap, `timeout-minutes: 60`, `permissions: contents: write`. Caches
  `~/.cache/huggingface`, Ollama models, and pip. Adds a **0–45 min jitter** so
  posts don't land at a robotic fixed minute. On success it commits
  `state/history.json` back with `[skip ci]` and uploads the image + caption as an
  artifact. On failure it opens/updates a GitHub issue with the log tail.

  > **cron is UTC** and GitHub **delays scheduled runs under load**, so exact
  > minutes are not guaranteed.

- **`.github/workflows/ci.yml`** — `ruff` + `mypy` + `pytest` on every PR, plus a
  **`--dry-run` smoke test with the poster/models mocked** (no downloads, no network).

> **Cache note:** the repo Actions cache ceiling is **10 GB** and entries **evict
> after 7 days** of no use. A cold cache re-downloads models (adds several minutes).

---

## Development

```bash
make setup     # venv + deps
make test      # pytest (no network)
make lint      # ruff + mypy
make dry-run   # full pipeline, nothing posted
```

Determinism: pass `--seed` (or rely on the date+salt seed) for a reproducible run;
the torch generator, Ollama `seed`, and axis-hint RNG are all seeded and the seed
is recorded in history.

## License

MIT — see [LICENSE](LICENSE). You are responsible for complying with Instagram's
and Meta's terms for whichever backend you choose.