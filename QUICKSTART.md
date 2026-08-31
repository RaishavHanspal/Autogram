# autogram — Quickstart

Get from zero to a generated post (dry-run) in ~5 minutes on a Linux/macOS/WSL
machine. No GPU, no paid API.

## 1. Install

```bash
git clone <your-fork-url> autogram && cd autogram
make setup
```

`make setup` creates a venv, installs the **CPU** torch wheel + deps, and installs
autogram. Ollama is installed and managed automatically at runtime (Linux); on
macOS/Windows install Ollama once from https://ollama.com/download.

## 2. Configure

```bash
cp .env.example .env
```

Edit **`config/config.yaml`** and choose a `content.active_profile`; edit or add profiles under `content.profiles`:

```yaml
content:
  active_profile: "romance"
```

That's the only required config. Everything else has sane defaults. For the full
walkthrough — content types, reel music, and linking **multiple accounts** to one
repo — see **[CONFIGURE.md](CONFIGURE.md)**.

## 3. Dry run (nothing is posted)

```bash
make dry-run
```

First run downloads the diffusion model (~2.6 GB for `sd-turbo`) and the LLM
(~2 GB for `qwen2.5:3b-instruct`) — subsequent runs use the cache. When it
finishes you'll have:

```
out/<timestamp>.jpg    # 1080x1080 Instagram-ready JPEG
out/<timestamp>.txt    # caption + hashtags
out/<timestamp>.json   # brief, prompts, seed, hashes
state/history.json     # run recorded (drives dedupe + idempotency)
```

Faster iteration? Use the tiny model:

```bash
AUTOGRAM_IMAGE__MODEL=segmind/tiny-sd AUTOGRAM_IMAGE__STEPS=1 make dry-run
```

## 4. Post for real

Pick a backend (see the README for full setup):

### instagrapi (private API — burner account, low volume)

```bash
# .env
POST_BACKEND=instagrapi
IG_USERNAME=your_user
IG_PASSWORD=your_pass
```

```bash
python -m autogram.run          # first run creates state/ig_session.json
```

### graph (official API — recommended for anything that matters)

```bash
# .env
POST_BACKEND=graph
IG_ACCESS_TOKEN=EAAB...         # long-lived token
IG_USER_ID=1789...              # numeric IG business user id
GITHUB_TOKEN=ghp_...            # for the default image host (auto in Actions)
GITHUB_REPOSITORY=you/autogram
```

```bash
python -m autogram.run
```

## 5. Automate on GitHub Actions (free tier)

1. Push your fork.
2. Add secrets (see README "Secrets" table). For instagrapi, seed a session:
   ```bash
   b64=$(base64 -w0 state/ig_session.json)
   gh secret set IG_SESSION_B64 --body "$b64"
   ```
3. The `autogram-post` workflow runs twice weekly (and on-demand via
   **Run workflow** → `dry_run: true` to test safely first).

## Common flags

```bash
python -m autogram.run --dry-run                 # generate, gate, save, no post
python -m autogram.run --image-only              # image only, no caption/post
python -m autogram.run --seed 1234               # reproducible
python -m autogram.run --content-type reel       # force photo | reel | carousel
python -m autogram.run --account romance         # run only one configured account
python -m autogram.run --content-profile romance # select a configured profile
python -m autogram.run --description "new theme" # one-off active-profile theme
```

## Troubleshooting

- **instagrapi `ChallengeRequired`** → approve the login in the IG app from the
  same IP, re-run locally, re-seed `IG_SESSION_B64`. See README.
- **Slow first run** → models are downloading; they're cached afterward.
- **Out of disk in CI** → you're not on the default models; check the disk table
  in the README (sd-turbo + qwen2.5:3b fits comfortably).
