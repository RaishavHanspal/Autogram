# DECISIONS.md

Every notable assumption and trade-off made while building autogram. Where a
constraint (CPU-only diffusion above all) forced a quality trade-off, the
CPU-safe default is implemented and the high-quality path is wired behind
auto-detection.

## Runtime constraint: CPU-first, GPU auto-upgrade

- **GitHub `ubuntu-latest` has no GPU.** CPU is the only guaranteed path, so it is
  the default and the acceptance target. `imagegen.py` and `run.py` auto-detect
  `torch.cuda.is_available()`:
  - **CPU:** fp32, `enable_attention_slicing()`, `torch.set_num_threads(cpu_count)`,
    default model `stabilityai/sd-turbo`, LLM `qwen2.5:3b-instruct`.
  - **CUDA:** fp16, `hq_model` (default `black-forest-labs/FLUX.1-schnell`), LLM
    `hq_model` (default `qwen2.5:7b-instruct`). Same code path.
- The FLUX path is **not exercised on CI** (no GPU) — it is best-effort and gated
  behind CUDA detection. `imagegen.py` drops `negative_prompt` for FLUX (it doesn't
  accept one).

## torch install: CPU wheel pinned separately

- `torch` is deliberately **not** in `requirements.txt`. Installing it there risks
  pip pulling the ~2.5 GB CUDA build onto a GPU-less runner. `requirements-cpu.txt`
  pins `torch==2.3.1+cpu` from `https://download.pytorch.org/whl/cpu`. GPU users
  install `torch==2.3.1` from PyPI themselves.

## Pinned versions

- All deps are pinned (`requirements.txt`, `pyproject.toml`). Chosen for mutual
  compatibility under Python 3.11: `diffusers==0.27.2` / `transformers==4.40.2` /
  `torch==2.3.1`, `pydantic==2.7.1` / `pydantic-settings==2.2.1`, `instagrapi==2.1.2`.
  If a pin ever conflicts or is yanked, bump it and note it here — do **not**
  silently unpin.

## LLM runtime: Ollama, lifecycle-managed in-process

- `caption.py`'s `OllamaClient` owns the daemon: it detects an existing daemon at
  `OLLAMA_HOST`, and if absent installs Ollama (Linux script) and spawns
  `ollama serve`, health-polls `/api/tags` with backoff, pulls the model if
  missing, and tears the daemon down on exit (including on failure, via `atexit`).
- `brief.py` reuses the same `OllamaClient` (imported from `caption.py`) to avoid a
  second runtime. `caption.py` references `Brief` only under `TYPE_CHECKING` to
  avoid an import cycle.
- **Assumption:** auto-install is Linux-only (matches the runner). On macOS/Windows
  the user installs Ollama once; the client still manages `serve`/health/pull.

## NSFW gate model choice

- Uses the **official CompVis `stable-diffusion-safety-checker`** shipped as a class
  inside `diffusers`, rather than a hand-rolled CLIP classifier. Rationale (also in
  `safety.py`): it is the canonical, well-understood NSFW gate, needs no bespoke
  thresholds, its weights (~1.2 GB) cache in `HF_HOME` next to the diffusion model,
  and it scores a single 512px image in ~1–2 s on CPU — negligible vs. generation.
  The spec's "lighter CLIP classifier" escape hatch is unnecessary at this scale.

## Variety guarantees (3 independent mechanisms)

1. **Seeded axis hints:** `random.Random(compute_seed(run_date, salt) ^ seed)`
   pre-selects camera angle / season / focal length / subject scale, injected into
   the brief prompt — variety even if the LLM is repetitive.
2. **History-aware divergence:** the last N briefs (default 30) are shown to the LLM
   with an explicit "must differ" instruction.
3. **Near-duplicate rejection:** `rapidfuzz.token_set_ratio` > threshold (default
   85) triggers reject-and-retry (max 3), then a deterministic fallback so a run
   never dies.

## Determinism & fallbacks

- Seed source: `--seed` if given, else `sha256(run_date + salt)`. The torch
  generator, Ollama `seed`, and axis RNG all derive from it; the seed is recorded
  in `history.json`.
- Both LLM stages validate JSON into pydantic models, retry up to 3× feeding the
  error back, then fall back to a deterministic template. A malformed LLM reply
  never aborts a run.

## Hashtag handling

- Normalize → validate `^#[A-Za-z0-9_]{2,29}$` → **drop** (not merge) anything that
  fails, per spec. `normalize_tag` strips only leading/trailing whitespace; a tag
  with internal spaces is a phrase, not a hashtag, and is dropped.
- Dedupe case-insensitively, filter against `config/banned_hashtags.txt`, always
  append brand tags, hard-cap at 30. Tier distribution (30/50/20) is requested from
  the LLM (labelled per tag) and validated in code with tolerance.
- Placement (`caption` vs `comment`) is config-driven; the `Poster` interface
  therefore supports a follow-up `comment()`.

## Post-processing

- Center-crop to the configured aspect → LANCZOS resize to exact IG dims
  (`1:1`→1080², `4:5`→1080×1350, `1.91:1`→1080×566) → sRGB (ICC-converted if a
  profile is present, else `convert("RGB")`) → unsharp → JPEG q92 → **strip all
  metadata** by copying pixels into a fresh image → hard-fail if >8 MB or aspect
  outside 0.8–1.91.

## Posting backends

- `POST_BACKEND` selects the backend with **zero code change**.
- **instagrapi:** session persistence is mandatory (base64 secret or session file);
  password login is the fallback only when the session is dead. Device + UA pinned.
  `ChallengeRequired` / `TwoFactorRequired` / `LoginRequired` / `PleaseWaitFewMinutes`
  get distinct, actionable messages. Backoff has jitter. Proxy optional.
- **graph:** needs a public image URL → `ImageHost` abstraction, default
  `GitHubReleaseHost` (release asset via `GITHUB_TOKEN`). Two-step publish with
  container polling; surfaces `x-app-usage` and the 25/24h quota.
- Both honour `--dry-run`: full pipeline, artifacts written, exact call logged,
  nothing posted.

## State

- `state/history.json`: one record/run (timestamp, brief, prompts, seed, model ids,
  image sha256, caption, hashtags, backend, post id/url, status). Written
  **atomically** (temp file + `os.replace` + fsync). Idempotency: refuse to post an
  image hash already present. Corrupt history is treated as empty (warn, don't die).

## Secrets & logging

- Secrets come from env only (`Secrets` via pydantic-settings); never YAML. A
  `RedactingFilter` masks registered secret values and credential-shaped substrings
  in every log record, so no credential reaches logs or the committed state file.

## Runtime/disk table: how the numbers were derived

- The runtime and disk figures in the README are **reference estimates**, not
  measured on this build host (a Windows dev box with only Python 3.14 and no GPU,
  used solely to run the pure-logic tests). They combine:
  - published model card / weight sizes (HF) for disk,
  - the spec's own stated CPU ranges (sd-turbo ~20–60 s, sdxl-turbo several minutes,
    tiny-sd fastest) and known `diffusers` CPU benchmarks for wall-clock on 4 vCPU.
- They are labelled approximate in the README. Re-measure on a real
  `ubuntu-latest` run and update the table if you want exact figures for your config.

## Testing approach

- Unit tests are **network-free** and avoid the heavy deps where possible (torch/
  diffusers are only touched by the opt-in integration test and the imagegen path).
  Posters are tested against mocked clients including the challenge and rate-limit
  paths. `tests/smoke_dry_run.py` runs the **entire orchestration** end-to-end with
  the LLM, image generator, and poster mocked (no downloads) and is wired into
  `ci.yml`.
- The opt-in `tests/test_integration.py` (`AUTOGRAM_INTEGRATION=1`) performs a real
  dry run with actual models.

## Build-host validation note

- On the build machine (Python 3.14, no GPU) the full pure-logic suite (52 tests,
  incl. both posters) and the mocked end-to-end smoke test pass; `ruff` is clean.
  The project **targets Python 3.11** (`pyproject.toml`), which CI uses; 3.14 here
  was only a convenience for logic validation and is not a supported runtime.
