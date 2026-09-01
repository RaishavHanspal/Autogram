# autogram — Configuration guide

Everything you can control, and exactly where. There are only **two** places:

- **`config/config.yaml`** — all non-secret content + behaviour (one file).
- **environment / GitHub secrets** — credentials only, never in YAML.

Jump to: [1. What to post](#1-what-to-post-the-content-profile) ·
[2. Content types](#2-content-types-photo--reel--carousel) ·
[3. Reel music](#3-reel-music) ·
[4. One account](#4-credentials-single-account) ·
[5. Multiple accounts](#5-multiple-accounts-in-one-repo) ·
[6. GitHub Actions](#6-github-actions-secrets) ·
[7. Verify](#7-verify)

---

## 1. What to post (the content profile)

A **profile** is the creative direction: theme, the recurring couple/anchor, the
scene vocabulary (locations, moods, lighting), and the LLM instructions. It lives
under `content.profiles` in `config/config.yaml`. The shipped profile is
`romance` (cinematic marriage-proposal scenes).

```yaml
content:
  active_profile: "romance"      # which profile runs by default
  profiles:
    romance:
      theme: >
        photorealistic cinematic Indian romance ...
      prompt_anchor: >
        the same recurring adult romantic couple, consistent facial identity ...
      visual:
        interaction_styles: [ ... ]
        moods_and_emotions: [ ... ]
        locations: { romantic: [ ... ], indoor: [ ... ] }
        photography_trends: { compositions: [ ... ], lighting_styles: [ ... ] }
```

To add a channel, **add a new profile** (don't edit pipeline code):

```yaml
content:
  active_profile: "travel"
  profiles:
    romance: { ... }
    travel:
      theme: "sweeping cinematic travel photography of ..."
      prompt_anchor: "..."
      visual: { locations: { ... }, moods_and_emotions: [ ... ] }
```

The `romance:` top-level block (proposal direction, ring/flowers/kneeling, the
optional third-person love triangle) tunes the romance scene brain specifically.

Override the theme for a single run without editing YAML:

```bash
python -m autogram.run --dry-run --description "a rainy-night proposal on a bridge"
```

---

## 2. Content types (photo / reel / carousel)

Every run produces **one** content type:

| Type       | Media        | Controlled by            |
|------------|--------------|--------------------------|
| `photo`    | one image    | —                        |
| `reel`     | one MP4      | `reel.num_scenes`        |
| `carousel` | 2–10 images  | `carousel.num_slides`    |

The type is chosen per run from a **weighted mix** (weight `0` disables a type):

```yaml
content_mix:
  reel: 3         # 3x as likely as photo/carousel
  carousel: 1
  photo: 1

reel:
  enabled: true
  num_scenes: 4
carousel:
  enabled: true
  num_slides: 4
```

Force a type for one run (useful for testing):

```bash
python -m autogram.run --dry-run --content-type carousel
```

---

## 3. Reel music

Drop royalty-free `.mp3` (or `.wav/.m4a/.aac/.ogg/.flac`) files in the folder
named by `reel.audio_dir` (default `assets/audio/`) **and commit them** (the CI
runner needs them in the repo):

```yaml
reel:
  audio_dir: "assets/audio"
```

Each reel picks a random track **and a random start offset inside it** (so it
never always starts at the beginning), with fade in/out. If the folder is empty,
a synthesized ambient bed is used instead. No configuration needed beyond adding
the files.

---

### Performance — staying within the CI timeout

Image generation on a free CPU runner is the dominant cost (~4 min per 512²
image at 20 steps). The run time is roughly:

    accounts × scenes_per_item × (~4 min/image) + one LLM brief per item

Only **one** LLM brief is generated per reel/carousel (extra scenes reuse it with
a new shot), so images dominate. Levers, cheapest first:

| Lever | Where | Effect |
|---|---|---|
| `reel.num_scenes` / `carousel.num_slides` | config.yaml | fewer images per item |
| `content_mix` weight on `photo` | config.yaml | photos are 1 image (fast) |
| `image.steps` (e.g. 20 → 16) | config.yaml | fewer diffusion steps |
| fewer accounts per run | `--account`, `enabled`, or stagger schedules | time is linear in accounts |
| `reel.ai_video.mode: off` | config.yaml | skip AI-video attempts entirely |

Two accounts each posting a 3-scene reel is ≈ 6 images ≈ **~30 min** — well under
a 60-min job.

### Image quality (free)

- `image.compact_prompt: true` (default) builds an identity-first prompt that
  fits CLIP's 77-token window, so the couple anchor is never truncated.
- `image.use_compel: true` (default) uses [compel](https://github.com/damian0815/compel)
  when installed to encode prompts **past** 77 tokens with no truncation — free,
  negligible time, and safely optional (falls back automatically if absent). The
  posting workflow installs it best-effort.
- `image.hires_fix: true` adds real detail via a second pass but ~doubles image
  time — enable only with a low `reel.num_scenes`.

---

## 4. Credentials (single account)

Credentials are environment-only. Copy `.env.example` to `.env` and fill in the
backend you use. Leave `accounts:` in `config.yaml` **empty** for this mode.

**instagrapi** (private API — use a burner account, low volume):

```bash
POST_BACKEND=instagrapi
IG_USERNAME=your_user
IG_PASSWORD=your_pass
IG_SESSION_B64=            # strongly recommended; see below
```

**graph** (official Instagram API):

```bash
POST_BACKEND=graph
IG_ACCESS_TOKEN=EAAB...
IG_USER_ID=1789...
GITHUB_TOKEN=ghp_...       # for the default image host (auto in Actions)
GITHUB_REPOSITORY=you/autogram
```

**youtube** (Shorts — needs a video, so keep `reel` in the mix):

```bash
POST_BACKEND=youtube
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...   # OAuth token with the youtube.upload scope
```

Seed an instagrapi session once (avoids password logins / challenges every run):

```bash
python -m autogram.run --dry-run          # logs in, writes state/ig_session.json
b64=$(base64 -w0 state/ig_session.json)   # this is your IG_SESSION_B64
```

---

## 5. Multiple accounts in one repo

This is what replaces running several repos. Two parts:

### 5a. Declare the accounts (non-secret) in `config/config.yaml`

```yaml
accounts:
  - id: romance                # matches a credential entry by this id
    platform: instagram        # instagram | youtube
    backend: instagrapi        # instagrapi | graph | youtube  ("" -> derived)
    profile: romance           # a key under content.profiles
    enabled: true
    content_mix: { reel: 3, carousel: 1, photo: 1 }
    audio_dir: "assets/audio"
  - id: shorts
    platform: youtube
    profile: romance
    content_mix: { reel: 1 }   # YouTube needs a video
```

Each account gets its own history (`state/history.<id>.json`) and output folder
(`out/<id>/`). They run sequentially in one job (reusing the warmed models); one
account failing never aborts the others.

### 5b. Supply all credentials via ONE secret

Because flat names like `IG_USERNAME` would collide, every account's credentials
go into a single `AUTOGRAM_ACCOUNTS` secret — a JSON array matched to the
accounts above by `id` (keep it one line):

```bash
AUTOGRAM_ACCOUNTS=[{"id":"romance","ig_username":"u","ig_password":"p","ig_session_b64":"b64"},{"id":"shorts","youtube_client_id":"..","youtube_client_secret":"..","youtube_refresh_token":".."}]
```

Recognized keys per entry: `ig_username`, `ig_password`, `ig_session_b64`,
`ig_proxy`, `ig_access_token`, `ig_user_id`, `youtube_client_id`,
`youtube_client_secret`, `youtube_refresh_token`. (`GITHUB_TOKEN` /
`GITHUB_REPOSITORY` are shared, from the normal env.)

Run one specific account:

```bash
python -m autogram.run --dry-run --account shorts
```

---

## 6. GitHub Actions secrets

Add these under **Settings → Secrets and variables → Actions**. Only set what you
use.

| Secret | When |
|---|---|
| `AUTOGRAM_ACCOUNTS` | multiple accounts (JSON array from step 5b) |
| `POST_BACKEND`, `IG_USERNAME`, `IG_PASSWORD`, `IG_SESSION_B64` | single instagrapi account |
| `IG_ACCESS_TOKEN`, `IG_USER_ID` | single graph account |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | single youtube account |
| `HF_TOKEN`, `HF_VIDEO_MODEL` | optional free-tier AI video (Hugging Face) |
| `PIXVERSE_API_KEY`, `PIXVERSE_MODEL` | optional AI video (PixVerse) |

`GITHUB_TOKEN` and `GITHUB_REPOSITORY` are provided automatically.

The workflow (`.github/workflows/autogram.yml`) runs on a schedule and via
**Run workflow** (set `dry_run: true` to test without posting). It commits each
account's `state/history.*.json` back so dedupe/idempotency persists.

> Note: renaming the workflow file resets GitHub's schedule for it (the first
> cycle is skipped). Keep the filename stable.

---

## 7. Verify

Nothing is posted in a dry run.

```bash
# one of everything, no posting
python -m autogram.run --dry-run --content-type photo
python -m autogram.run --dry-run --content-type carousel   # -> N images in out/
python -m autogram.run --dry-run --content-type reel       # -> out/<stamp>.mp4

# all enabled accounts
python -m autogram.run --dry-run
```

Check the run log for the content type, chosen music + offset, and (for reels)
`reel assembled from N ...`. Outputs land in `out/` (or `out/<id>/` per account)
and the run is recorded in `state/history*.json`.
