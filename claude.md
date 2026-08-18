# AVATAR STUDIO — Phase 1 Implementation Plan (Instructions for Claude Code)

> **How to use this document:** Save it as `CLAUDE.md` in the root of a new empty repo, open Claude Code in that repo, and work milestone by milestone: "Implement M0 from CLAUDE.md", then "Implement M1", etc. Do not skip milestones — each one's acceptance criteria must pass before the next begins.

---

## 0. What we are building (context for Claude Code)

A self-hosted "HeyGen-style" talking-head video product. Phase 1 delivers a single working pipeline for one user (the founder), architected so multi-tenant support can be added later without rewrites.

**Phase 1 user journey:**

1. **Train my avatar** — user uploads 2–3 zoomed-in photos + one 30–60 second video (clearly showing face, lips, and hand movement), and records/uploads a voice sample. Default voice accent target: American English.
2. **Generate a look** — user types a scene request, e.g. *"tech home-office setup, Rode mic entering frame from the left, put me in a black polo."* System returns 2–4 candidate images of the user in that scene; user approves one.
3. **Create a video** — user provides (a) an emotion/movement brief (*"casual and funny, relaxed energy"*) and (b) a script. An LLM orchestrator combines them into a tagged voice script + a video style prompt. The system renders a finished straight-to-camera talking-head video: lip-synced, natural face/eye/hand movement, upscaled to 4K. No manual editing anywhere.

**Critical concept — what "training" means here.** No model fine-tuning happens in Phase 1. "Training" = capturing and validating the user's reference assets (photos, video, voice) into an **Avatar Profile**, then conditioning zero-shot models on those assets at generation time. This is the same pattern HeyGen's own Avatar V uses (their published architecture requires no identity-specific fine-tuning at inference). Never present this to the user as "we trained a model on you" in code comments or docs — call it "profile creation."

**Phase 1 non-goals (do NOT build these):**
- Per-user model fine-tuning / LoRA training
- Timeline choreography ("raise hand at 0:07") — impossible with current models; motion is audio-driven + prompt-guided only
- Real-time / streaming avatars
- Multi-scene videos, B-roll, captions, editing timeline
- Billing, teams, orgs
- Mobile apps

---

## 1. Architecture

```
┌─────────────┐     ┌──────────────────────────┐     ┌───────────────────────────────┐
│  Next.js UI │────▶│  FastAPI  (control plane) │────▶│  PostgreSQL  +  S3/R2 storage │
└─────────────┘     │  - auth (single user)     │     └───────────────────────────────┘
                    │  - profiles & uploads      │
                    │  - job queue (DB-backed)   │◀──── long-poll ────┐
                    │  - ElevenLabs client       │                    │
                    │  - Claude orchestrator     │          ┌─────────┴──────────┐
                    └──────────────────────────┘            │  GPU WORKER (RunPod │
                                                            │  or similar pod)    │
                                                            │  1. Qwen-Image-Edit │  ← look generation
                                                            │  2. LongCat-Video-  │  ← talking-head video
                                                            │     Avatar-1.5      │
                                                            │  3. SeedVR2         │  ← 4K upscale
                                                            │  4. ffmpeg mux      │
                                                            └────────────────────┘
```

**Design decisions (locked — do not substitute):**

- **Job queue is PostgreSQL-backed, not Redis/Celery.** The GPU worker runs on a rented pod with no shared network; it authenticates with a worker token and long-polls `GET /internal/jobs/next` over HTTPS, then PATCHes progress/results back. This survives pod restarts and avoids exposing a message broker publicly.
- **All generation is asynchronous.** Every user-facing generation endpoint returns a `job_id` immediately; the UI polls `GET /jobs/{id}`.
- **One continuous render per video (LiveAvatar primary).** LiveAvatar generates any duration — including 30 minutes — as a single continuous pass over the full audio track, so no video stitching is needed at any length. Script is chunked only at the TTS level (ElevenLabs limit) and audio chunks are ffmpeg-concatenated *before* video generation. The parallel-segment design in §13 applies only if the M5 bake-off sends us to the LongCat fallback, or later as an optional latency booster. Never stitch video mid-sentence in any mode.

---

## 2. Locked tool stack (verified as of Aug 2026 — re-verify each repo README before install)

| Component | Tool | Key verified facts | License |
|---|---|---|---|
| Voice clone + TTS | **ElevenLabs API** — Instant Voice Clone (IVC) + model `eleven_v3` | v3 supports inline audio tags (`[sad]`, `[laughs]`, `[whispers]`, etc.) via the standard Create Speech endpoint. v3 is still labeled alpha; **Professional Voice Clones are not fully optimized for v3 — use IVC**. Single-pass generation is length-limited (~10k chars reported); chunk long scripts. | Commercial SaaS |
| Orchestrator LLM | **Claude API**, model `claude-sonnet-4-6` | Turns (emotion brief + script) into strict JSON: tagged voice script + video style prompt. Verify current model names at https://docs.claude.com before hardcoding. | Commercial SaaS |
| Look generation | **Qwen-Image-Edit-2511** (fallback: 2509) | Open-sourced by Alibaba's Qwen team; 2511 specifically improves character/identity consistency for portrait edits; 2509 supports 1–3 input images (person + garment reference = the "wear this shirt" case) and ControlNet inputs. A distilled "Lightning" variant runs in 4–8 steps. | Apache 2.0 |
| Talking-head video (PRIMARY) | **LiveAvatar** (repo: `Alibaba-Quark/LiveAvatar`; weights: `Wan-AI/Wan2.2-S2V-14B` base + `Quark-Vision/Live-Avatar` LoRA on HF) | Real-time streaming avatar generation: 14B model, 45 FPS with 4-step sampling on a 5-GPU Hopper node (TPP pipeline parallelism — GPUs must share one machine); v1.1 (Jan 2026) adds FP8 (48GB-capable) + compilation for 2.5–3× speedup; single-80GB-GPU offline mode exists (throughput unpublished — benchmark); 10,000+ second continuous generation, so 30-min videos need no cuts. Inputs: audio + reference image + optional text prompt. First run with compilation enabled is slow; subsequent runs get the speedup. | Apache 2.0 (LiveAvatar and Wan base both) |
| Talking-head video (FALLBACK) | **LongCat-Video-Avatar-1.5** (repo: `meituan-longcat/LongCat-Video`, weights: `meituan-longcat/LongCat-Video-Avatar-1.5` on HF) | Quality fallback + M5 bake-off contender. 13.6B DiT; v1.5 uses Whisper-Large lip sync, 8-step distill (`--use_distill` REQUIRED; `--use_int8` supported). ~44 GPU-sec per finished second measured on A800-40GB. Repo states Apache 2.0; one review cites MIT — **read the LICENSE file at setup and record which** (both commercial-friendly). | Apache 2.0 (verify) |
| 4K upscale | **SeedVR2** via `numz/ComfyUI-SeedVR2_VideoUpscaler` (has a standalone CLI — use the CLI, not ComfyUI) | 3B and 7B variants, FP16/FP8/GGUF; 24GB VRAM recommended, ~12GB workable with FP8; batch processing eliminates temporal flicker. | Open (check repo) |
| Backend | FastAPI (Python 3.11+), PostgreSQL 16, S3-compatible storage (Cloudflare R2 or MinIO for local dev) | — | OSS |
| Frontend | Next.js (App Router) + TypeScript + Tailwind | Three-screen wizard, nothing fancy. | OSS |
| Media utils | ffmpeg/ffprobe, OpenCV, MediaPipe (face detection), librosa | Upload validation + frame extraction + muxing. | OSS |

**Rule for Claude Code:** never invent API parameters. Before wiring each external tool, fetch and read the authoritative source: ElevenLabs docs (elevenlabs.io/docs), the LongCat-Video GitHub README, the Qwen-Image-Edit-2511 HF model card, the SeedVR2 upscaler repo README, and https://docs.claude.com for the Anthropic SDK. If a flag or endpoint in this document conflicts with the current README, the README wins — note the discrepancy in `DECISIONS.md`.

---

## 3. Repository layout

```
avatar-studio/
├── CLAUDE.md                    # this file
├── DECISIONS.md                 # running log of deviations/verified facts (Claude Code maintains)
├── docker-compose.yml           # postgres + minio + api (dev)
├── .env.example
├── apps/
│   ├── api/                     # FastAPI control plane
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py        # pydantic-settings, reads env
│   │   │   ├── db/              # SQLAlchemy models + Alembic migrations
│   │   │   ├── routes/          # auth.py, profiles.py, uploads.py, looks.py, videos.py, jobs.py, internal.py
│   │   │   ├── services/
│   │   │   │   ├── media_validation.py
│   │   │   │   ├── frame_extraction.py
│   │   │   │   ├── elevenlabs_client.py
│   │   │   │   ├── orchestrator.py      # Claude API call
│   │   │   │   ├── storage.py           # S3 presigned upload/download
│   │   │   │   └── jobs.py              # DB-backed queue
│   │   │   └── schemas/         # pydantic request/response models
│   │   └── tests/
│   └── web/                     # Next.js
│       └── src/app/(wizard)/train | looks | create
├── worker/                      # GPU worker — deployed to the pod, NOT in docker-compose
│   ├── setup.sh                 # provisions the pod: drivers check, repos, weights
│   ├── worker.py                # long-poll loop, dispatches job handlers
│   ├── handlers/
│   │   ├── look_generation.py   # Qwen-Image-Edit-2511
│   │   ├── video_generation.py  # LongCat-Video-Avatar-1.5
│   │   └── upscale.py           # SeedVR2 CLI wrapper
│   └── requirements.txt
└── assets/test/                 # golden test fixtures (see M8)
```

---

## 4. Environment variables (`.env.example`)

```bash
# --- control plane ---
DATABASE_URL=postgresql+psycopg://avatar:avatar@localhost:5432/avatar_studio
S3_ENDPOINT=http://localhost:9000          # MinIO in dev, R2/S3 in prod
S3_BUCKET=avatar-studio
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
JWT_SECRET=...                              # single-user auth
FOUNDER_EMAIL=...                           # seeded user
WORKER_TOKEN=...                            # shared secret for /internal/* routes

# --- external APIs ---
ELEVENLABS_API_KEY=...
ELEVENLABS_TTS_MODEL=eleven_v3
ELEVENLABS_FALLBACK_MODEL=eleven_multilingual_v2   # for >10k-char chunks if v3 rejects
ELEVENLABS_DEFAULT_VOICE_ID=...             # pick an American-accent stock voice; used before user clones
ANTHROPIC_API_KEY=...
ORCHESTRATOR_MODEL=claude-sonnet-4-6

# --- worker (set on the GPU pod) ---
API_BASE_URL=https://api.yourdomain.com
WORKER_TOKEN=...                            # must match control plane
HF_TOKEN=...                                # HuggingFace weight downloads
VIDEO_MODEL=liveavatar                      # liveavatar (primary) | longcat (fallback, per M5 bake-off)
LIVEAVATAR_ENABLE_COMPILE=true              # long first-run compile, big speedup after; set false for quick tests
LIVEAVATAR_ENABLE_FP8=false                 # VRAM saver (48GB-capable) with slight quality cost — benchmark before enabling
LONGCAT_FLAGS=--use_distill --use_int8      # fallback model only; required flags per its repo
AUDIO_CFG=4                                 # LongCat fallback only; repo-recommended lip-sync range is 3–5
SEEDVR2_VARIANT=3b_fp16                     # start with 3B; 7B only if VRAM allows
TARGET_RESOLUTION=4k                        # pipeline: native 720p -> SeedVR2 -> 2160p
```

---

## 5. Database schema (Alembic migration 001)

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE avatar_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',      -- draft | validating | ready | failed
  consent_confirmed_at TIMESTAMPTZ,          -- REQUIRED before status can become 'ready'
  elevenlabs_voice_id TEXT,                  -- null until voice cloned
  primary_ref_image_key TEXT,                -- best extracted/uploaded frame (S3 key)
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE media_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES avatar_profiles(id) NOT NULL,
  kind TEXT NOT NULL,                        -- photo | reference_video | voice_sample | extracted_frame
  s3_key TEXT NOT NULL,
  meta JSONB NOT NULL DEFAULT '{}',          -- width/height/duration/sharpness_score/face_bbox etc.
  validation TEXT NOT NULL DEFAULT 'pending',-- pending | passed | failed
  validation_errors JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE looks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES avatar_profiles(id) NOT NULL,
  prompt TEXT NOT NULL,                      -- user's scene request, verbatim
  garment_asset_id UUID REFERENCES media_assets(id),  -- optional "wear this shirt" image
  candidate_keys JSONB NOT NULL DEFAULT '[]',-- S3 keys of generated candidates
  approved_key TEXT,                         -- null until user picks one
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE video_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES avatar_profiles(id) NOT NULL,
  look_id UUID REFERENCES looks(id) NOT NULL,
  emotion_brief TEXT NOT NULL,
  script TEXT NOT NULL,
  orchestrator_output JSONB,                 -- tagged_script, style_prompt, tts_chunks
  audio_key TEXT,                            -- final concatenated ElevenLabs audio
  video_720_key TEXT,
  video_4k_key TEXT,
  status TEXT NOT NULL DEFAULT 'queued',     -- queued|orchestrating|tts|rendering|upscaling|done|failed
  error TEXT,
  cost_ledger JSONB NOT NULL DEFAULT '{}',   -- elevenlabs_chars, claude_tokens, gpu_seconds
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type TEXT NOT NULL,                        -- look_generation | video_generation | upscale
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',     -- queued | leased | running | done | failed
  lease_expires_at TIMESTAMPTZ,              -- worker leases for 15 min, renews via heartbeat
  attempts INT NOT NULL DEFAULT 0,           -- max 2; then failed
  result JSONB,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX jobs_poll_idx ON jobs (status, created_at);
```

---

## 6. API contract (all under `/api/v1`, JWT auth except `/internal/*` which uses `WORKER_TOKEN`)

```
POST /auth/login                     {email} -> magic token (dev: returns JWT directly)

POST /profiles                       {name} -> profile
POST /profiles/{id}/uploads/presign  {kind, filename, content_type} -> {upload_url, s3_key}
POST /profiles/{id}/assets           {kind, s3_key} -> asset (triggers validation)
POST /profiles/{id}/consent          {confirmed: true} -> records consent_confirmed_at
POST /profiles/{id}/voice            {source_asset_id | use_reference_video: true} -> job (IVC creation)
POST /profiles/{id}/finalize         -> validates completeness, sets status=ready
GET  /profiles/{id}                  -> profile + assets + readiness checklist

POST /profiles/{id}/looks            {prompt, garment_asset_id?} -> {look_id, job_id}
POST /looks/{id}/approve             {candidate_key} -> look
GET  /looks/{id}

POST /videos                         {profile_id, look_id, emotion_brief, script} -> {video_request_id}
GET  /videos/{id}                    -> status + signed URLs when done
GET  /jobs/{id}                      -> status/progress (0–100) for UI polling

# worker protocol
GET   /internal/jobs/next?types=...  -> 200 job (leased) | 204 none
PATCH /internal/jobs/{id}            {status?, progress?, heartbeat: true}
POST  /internal/jobs/{id}/complete   {result} | /fail {error}
POST  /internal/uploads/presign      worker uploads outputs directly to S3
```

---

## 7. Milestones

### M0 — Scaffold (½ day)
- Monorepo per §3, docker-compose (postgres + minio + api), Alembic migration 001, `/healthz`, pytest wiring, ruff + mypy, GitHub Actions CI running tests.
- **Accept:** `docker compose up` → `curl /healthz` = 200; CI green.

### M1 — Profiles, uploads, validation (1–2 days)
- Presigned S3 uploads (client → S3 direct; never proxy file bytes through FastAPI).
- `media_validation.py`:
  - **Photos (2–3 required):** decode with OpenCV; require min 768px on the short side; exactly one face detected (MediaPipe); face bounding box ≥ 25% of frame height (enforces "zoomed-in"); sharpness = variance of Laplacian, reject bottom-decile blurry images (tune threshold on your own test photos, start ~100).
  - **Reference video (1 required):** ffprobe: duration 30–60s (accept 25–75 with a warning), ≥720p, ≥24fps; sample 1 frame/sec, require a single consistent face in ≥90% of sampled frames; require detectable hands (MediaPipe Hands) in ≥30% of sampled frames — this enforces "shows hand movement."
  - **Voice sample:** ≥30s of speech (or extract audio track from the reference video via ffmpeg as fallback); loudness check with ffmpeg `volumedetect` — reject near-silence.
- `frame_extraction.py`: from the reference video, extract the 12 sharpest frontal frames; store as `extracted_frame` assets; auto-select the best (sharpest, most frontal, neutral) as `primary_ref_image_key`, user can override in UI.
- Every validation failure returns a **human-readable fix instruction** ("Your video is 18s — record at least 30s", "Move closer to the camera").
- **Accept:** upload the golden fixtures (M8) → profile checklist shows all green; upload a deliberately blurry photo → clear rejection message.

### M2 — Voice pipeline (1 day)
- `elevenlabs_client.py`: create **Instant Voice Clone** from the user's voice sample(s) (verify the current voices/add endpoint shape in ElevenLabs docs before coding); store `elevenlabs_voice_id`.
- Consent gate: `POST /voice` returns 403 unless `consent_confirmed_at` is set. The consent text must state the user certifies the voice/likeness is their own. (This matters later for payment processors and app-store review — HeyGen enforces the same.)
- TTS function `synthesize(voice_id, tagged_text) -> mp3`: model `eleven_v3`; chunk input on paragraph boundaries so no chunk exceeds the v3 length limit; concat chunks with ffmpeg (`concat` demuxer, re-encode once to 44.1kHz mp3/wav); return single file + duration.
- **American default:** before a clone exists, `ELEVENLABS_DEFAULT_VOICE_ID` (choose an American stock voice) is used so the pipeline is testable end-to-end. A cloned voice keeps the user's own accent — do not attempt accent conversion in Phase 1.
- **Accept:** integration test (behind an env flag, real API): tagged text `"[excited] Hello! [laughs] This is a test."` → audible emotional delivery in the output file; a 12k-char script chunks into ≥2 calls and concats into one seamless file.

### M3 — Look generation (2 days, first GPU milestone)
- Worker handler `look_generation.py` using **Qwen-Image-Edit-2511** (follow the HF model card for the exact diffusers pipeline class; use the Lightning/distilled variant if VRAM-tight).
- Inputs: `primary_ref_image` (+ up to 2 more profile photos if the pipeline accepts multi-image), optional garment image, scene prompt.
- Prompt template (worker-side, not user-visible):
  `"Photorealistic portrait of the same person as in the reference image, identity and face unchanged, {user_prompt}, upper-body framing suitable for a talking-head video, subject facing camera, sharp focus, natural lighting"`
- Generate 4 candidates (different seeds) at ≥1024px. Upload to S3, write `candidate_keys`.
- UI: candidate grid → approve one → stored as the Look. **Reroll button** re-queues with new seeds — Qwen edits are occasionally inconsistent; reroll is the Phase 1 mitigation, not a bug.
- **Accept:** prompt *"tech home office, condenser mic on a boom arm entering from the left, black polo shirt"* on the golden profile → ≥1 of 4 candidates keeps identity recognizably intact (manual check) with mic on the correct side.

### M4 — Claude orchestrator (1 day)
- `orchestrator.py`: one Claude API call (`ORCHESTRATOR_MODEL`), temperature ≤0.4, with the system prompt in §8. Input: emotion_brief + script + target voice notes. Output MUST be strict JSON (use the API's structured-output/JSON mode per current Anthropic docs); validate with pydantic; one retry on invalid JSON, then fail the request with the validation error stored.
- Output schema:
```json
{
  "tagged_script": "string — the user's script with ElevenLabs v3 audio tags inserted; wording of the script itself is NEVER changed",
  "tts_chunks": ["array of tagged_script split on paragraph boundaries, each under the v3 length limit"],
  "style_prompt": "string — LongCat video prompt: appearance-neutral, describes demeanor/energy/gesture style, always includes the words 'talking, speaking to camera'",
  "negative_notes": "string — things to avoid (e.g. 'no exaggerated laughing')",
  "emotion_summary": "string — one line shown back to the user for confirmation"
}
```
- **Accept:** unit tests with mocked Claude responses for schema validation; one live test: brief *"sad, subdued, this is a farewell message"* + a 3-paragraph script → tags like `[sad]`/`[sighs]` appear at plausible points, script wording unchanged (diff check ignoring bracketed tags), style_prompt contains "talking" and no appearance descriptors.

### M5 — GPU worker: video generation + upscale (3–4 days, the hard milestone)
- **`worker/setup.sh`** (idempotent, run on a fresh pod):
  1. Assert CUDA GPU with **≥80GB VRAM** for LiveAvatar (dev rig: 1× A100 80GB; speed rig: 5× H100 SXM on ONE node — TPP pipeline parallelism requires same-machine GPUs). FP8 may enable 48GB cards — treat as an experiment, not the plan.
  2. Clone `Alibaba-Quark/LiveAvatar`; **read its README and LICENSE now**; install per README: Python 3.10 env, PyTorch 2.8 cu128, FlashAttention 3 on Hopper (H100/H200) or FlashAttention 2 otherwise, ffmpeg. Record exact steps in `DECISIONS.md`.
  3. Download weights via `huggingface-cli` into `./ckpt/`: `Wan-AI/Wan2.2-S2V-14B` (base) + `Quark-Vision/Live-Avatar` (LoRA). Also clone `meituan-longcat/LongCat-Video` + its Avatar-1.5 weights for the bake-off (step 7).
  4. Install SeedVR2 upscaler repo + its 3B FP16 weights.
  5. Install Qwen-Image-Edit-2511 (shared pod is fine — models are loaded/unloaded per job in Phase 1; keep-warm optimization is Phase 2).
  6. Smoke test: run LiveAvatar's own single-GPU sample (`infinite_inference_single_gpu.sh`) with compile disabled; save `/tmp/smoke.mp4`. Setup is not done until it passes.
  7. **Bake-off (half a day, do it once):** run the SAME reference image + 60s ElevenLabs audio + style prompt through LiveAvatar and LongCat-Avatar-1.5. Compare identity hold, lip sync, gesture naturalness, and measure wall time + GPU-seconds for each. Record winner and numbers in `DECISIONS.md`; set `VIDEO_MODEL` accordingly (expected: liveavatar on speed, verify quality holds).
- **`handlers/video_generation.py`** contract:
  - Inputs (from job payload): approved look image (S3), final audio file (S3), style_prompt, negative_notes.
  - Branch on `VIDEO_MODEL`:
    - **liveavatar (primary):** invoke exactly as the repo's scripts do — `infinite_inference_single_gpu.sh` pattern on the dev rig, `infinite_inference_multi_gpu.sh` (torchrun TPP) on the 5-GPU node. Inputs: audio + reference image + text prompt. Respect `ENABLE_COMPILE`/`ENABLE_FP8` env passthrough; use `--num_clip` for cheap preview renders; `size` follows the look image's aspect ratio per repo docs.
    - **longcat (fallback):** Audio-Text-Image-to-Video mode with `--use_distill --use_int8`, audio CFG from env (repo lip-sync range 3–5), consistency knobs `ref_img_index` (0–24) and `mask_frame_range` per its README.
  - Stream progress: parse the process's clip/segment logs → PATCH progress every 30s (also serves as the lease heartbeat).
  - Output: 720p-class mp4 (model-native max) → S3 → hand off to upscale job.
  - Stream progress: parse the process's segment logs → PATCH progress every 30s (also serves as the lease heartbeat).
  - Output: 720p (or the model's native max) mp4 → S3 → hand off to upscale job.
- **`handlers/upscale.py`**: SeedVR2 CLI, 720p → 2160p (batch mode per its README to avoid temporal flicker), then ffmpeg: mux the ORIGINAL ElevenLabs audio back in (`-c:v copy -c:a aac`), `+faststart`. Verify output duration matches audio duration ±0.2s.
- **Failure policy:** any handler exception → job `failed` with the last 50 log lines in `error`; control plane retries once; video_requests surface the human-readable stage that failed.
- **Accept:** golden profile + approved look + 30s audio → finished 4K mp4 with correct lip sync (manual check), no frame jumps, audio in sync at start AND end.

### M6 — End-to-end wiring + frontend wizard (2 days)
- `POST /videos` pipeline: orchestrate (Claude) → TTS (ElevenLabs, chunk+concat) → enqueue `video_generation` → auto-enqueue `upscale` on completion → mark done; `cost_ledger` updated at each stage (chars, tokens, GPU seconds from job timings).
- Next.js wizard (3 routes): **Train** (upload checklist with live validation states) → **Looks** (prompt box, candidate grid, approve) → **Create** (emotion brief textarea + script textarea + look picker → progress screen with stage labels → video player + download 4K/720p).
- Progress honesty: show estimated render time from §9 math (`duration_s × 44 / speedup_factor`) so the user isn't surprised that a 60s video takes tens of minutes.
- **Accept:** a person who has never seen the code completes photo→video entirely through the UI.

### M7 — Hardening (1–2 days)
- Idempotency keys on all POSTs; job lease expiry reclaims abandoned jobs; S3 lifecycle rule deletes raw uploads' temp copies after 7 days; structured JSON logging with request/job IDs; `/metrics` basic counters.
- Content gate: refuse look prompts and scripts that request a *different real person* than the profile owner (simple check now: the consent model already binds the profile to the user's own likeness; add a Claude-based moderation check on look prompts for impersonation/NSFW).
- **Accept:** kill the worker mid-render → job is reclaimed and retried once → completes; duplicate `POST /videos` with same idempotency key → one job.

### M8 — Golden fixtures + QA checklist (½ day, do this DURING M1 not last)
- `assets/test/`: 3 founder photos, one 45s reference video, one 60s voice sample, one 300-word script, one emotion brief. (Founder records these on day 1.)
- Manual QA checklist file `QA.md`: identity match at 0s/30s/60s, lip-sync spot check at 3 timestamps, hands move naturally, no teeth artifacts, 4K file plays in QuickTime + Chrome, audio drift ≤0.2s at end.

---

## 8. Orchestrator system prompt (use verbatim as the Claude API system prompt)

```
You convert a video request into production inputs for a talking-head AI video pipeline.

You receive:
- EMOTION_BRIEF: how the speaker should come across (mood, energy, movement style)
- SCRIPT: the exact words the speaker will say

You output ONLY a JSON object with keys: tagged_script, tts_chunks, style_prompt, negative_notes, emotion_summary.

Rules for tagged_script:
1. NEVER change, add, remove, or reorder the script's words. Your only additions are ElevenLabs v3 audio tags in square brackets and punctuation adjustments for pacing (ellipses, dashes).
2. Insert tags sparingly — one tag per 1–3 sentences maximum. Over-tagging degrades v3 output.
3. Choose tags that realize the EMOTION_BRIEF: e.g. sad → [sad], [sighs], slower punctuation; funny/casual → [laughs], [chuckles], [excited] at genuinely fitting moments only; professional → minimal tags, clean delivery.
4. If the brief implies an emotional arc (e.g. "starts serious, ends hopeful"), distribute tags to follow that arc through the script.

Rules for tts_chunks:
5. Split tagged_script on paragraph boundaries into chunks of at most 2500 characters each. Never split mid-sentence. The concatenation of all chunks must equal tagged_script exactly.

Rules for style_prompt (this drives body/face motion in the video model):
6. Describe ONLY demeanor, energy, gesture style, gaze, and pace — NEVER appearance, clothing, background, or setting (those come from the approved look image and must not be contradicted).
7. Always include the phrase "talking, speaking directly to camera" (the video model needs explicit verbal-action cues for natural lip movement).
8. Map the brief to motion vocabulary: sad → "subdued expression, slow minimal hand gestures, soft gaze"; casual/funny → "relaxed posture, animated natural hand gestures, warm smiling expression"; professional → "composed, measured deliberate gestures, steady eye contact".
9. Keep it under 60 words, comma-separated descriptors.

Rules for negative_notes:
10. List motion behaviors to avoid given the brief (e.g. "no laughing" for somber content).

emotion_summary: one plain sentence describing the delivery you designed, for user confirmation.

Output raw JSON only. No markdown, no commentary.
```

---

## 9. GPU sizing, throughput, and cost reality (plan the product around these numbers)

**Primary path — LiveAvatar throughput (repo-published, benchmark on your own pods day 1):** 45 FPS with 4-step sampling on a 5-GPU Hopper node (v1.1: FP8 + compilation give 2.5–3× over v1.0). At 25fps output that is ~1.8× faster than realtime: a 1-min video generates in ~33s; a 30-min video in ~17 min, in ONE continuous pass. Single-80GB-GPU offline mode exists but its throughput is unpublished — measure it before promising any single-GPU SLA. First run with compilation is slow (budget a 10–30 min warm-up per cold pod).

**Verified rental rates (Aug 2026 — re-check before committing):** A100 80GB ≈ $0.67/hr (Vast) / $0.79/hr (RunPod) — the dev/correctness rig. H100 SXM ≈ $2.69/hr (RunPod Community) / $2.99/hr (RunPod Secure, predictable availability — use Secure for production) / as low as ~$1.49–1.87/hr on Vast's marketplace. The 5× H100 SXM production node ≈ $13.50–15/hr on RunPod Secure, billed per second — spin up per batch, don't idle it. Note: A100 (Ampere) lacks FP8 and FlashAttention 3, so it validates correctness, not speed; all speed benchmarks happen on Hopper.

**Per-video GPU cost (primary path):** 1-min video ≈ 165 GPU-seconds across the node ≈ **$0.10–0.15**; 30-min video ≈ **$3–6**. Plus SeedVR2 upscale time (benchmark; if it threatens the 3–5-min latency budget, evaluate FlashVSR as the real-time-oriented swap).

**Fallback path — LongCat measured numbers (independent hands-on, July 2026):** ~44 GPU-seconds per finished second on a 40GB A800 with INT8 + 8-step distill (82s clip ≈ 1 hour). If the bake-off sends us here, latency is sequential per video and §13's parallel segments become mandatory for anything long.

Implications Claude Code must build for:
- **Latency budget (primary):** end-to-end target is 1-min video in 3–5 min wall: TTS (~15–30s) + LiveAvatar gen (~33s–3 min depending on rig) + upscale + muxing. The upscale stage is the schedule risk — benchmark it in M5 and pick SeedVR2 settings (or FlashVSR) that fit.
- **Cost math:** hosted alternatives are $3.60/min (InfiniteTalk on WaveSpeed, 720p) to $9.60/min (OmniHuman 1.5 on fal) — the rented-GPU path is ~25–60× cheaper per minute at scale, at the cost of ops.
- **30-minute videos:** single continuous LiveAvatar pass (~17 min on the 5-GPU node, ~$3–6 GPU). §13's parallel-segment fallback: 22 GPU-hours total on LongCat (~$44), wall time by worker count (1 ≈ 22h, 4 ≈ 5.5h, 8 ≈ 2.75h).
- **Pod spec:** dev = 1× A100 80GB; prod = 5× H100 SXM, one node, NVLink. SeedVR2 3B fits alongside (24GB when the video model is unloaded). Disk ≥250GB for all weight sets. Long-form fallback mode uses N identical single-GPU pods — the DB-backed queue load-balances them with zero extra code.

---

## 10. Known risks & honest limitations (surface these, never paper over)

1. **ElevenLabs v3 is alpha**: PVCs underperform on v3 → IVC only; keep `eleven_multilingual_v2` as a fallback path behind an env flag if v3 quality/limits regress.
2. **Expressiveness ceiling**: "sad vs. casual" reads clearly; broad comedic acting is where open models trail HeyGen's Avatar V. Do not promise theatrical performance in marketing until tested.
3. **No choreography**: motion is emergent from audio + style prompt. The UI copy must say "natural movement," never "control movements."
4. **Qwen look edits can miss** (wrong mic side, drifted face) — the 4-candidate + reroll UX is the mitigation; measure the reroll rate.
5. **License verification is a setup task**: LongCat (Apache 2.0 per repo, MIT per one review — confirm from LICENSE), SeedVR2 repo license, Qwen (Apache 2.0). Log all three in `DECISIONS.md` before any commercial launch.
6. **Consent/impersonation**: profiles are self-likeness only in Phase 1; the consent record + moderation check (M7) is the minimum bar payment processors and platforms will expect.

---

## 11. Definition of done (Phase 1)

- [ ] Founder completes Train → Look → Create entirely in the UI with real assets
- [ ] Voice clone speaks with the founder's voice; default American stock voice works pre-clone
- [ ] Look prompt "tech home office, mic from the left, black polo" yields an approvable identity-true candidate within ≤2 rerolls
- [ ] Emotion brief demonstrably changes both audio delivery and on-screen demeanor between a "sad" and a "funny" render of the same script
- [ ] Output is 4K, lip-synced start-to-end, single continuous shot, no manual editing performed
- [ ] Job survives a worker restart; costs per video are recorded in `cost_ledger`
- [ ] M5 bake-off completed (LiveAvatar vs LongCat, same inputs): quality verdict, wall time, and GPU-seconds recorded in `DECISIONS.md`; `VIDEO_MODEL` set from the result
- [ ] A ≥10-minute render completes as one continuous pass with stable identity; one full 30-minute validation run before launch
- [ ] Measured 1-min-video wall time on the production rig meets the 3–5 minute target (TTS + generation + upscale + mux)
- [ ] `DECISIONS.md` records: confirmed licenses, measured sec-GPU-per-sec-video on your pod, measured reroll rate

## 12. Primary sources to (re)read during implementation

- LiveAvatar (primary video model): github.com/Alibaba-Quark/LiveAvatar · huggingface.co/Quark-Vision/Live-Avatar · base: huggingface.co/Wan-AI/Wan2.2-S2V-14B
- LongCat-Video repo + Avatar-1.5 weights (fallback): github.com/meituan-longcat/LongCat-Video · huggingface.co/meituan-longcat/LongCat-Video-Avatar-1.5
- Qwen-Image-Edit: github.com/QwenLM/Qwen-Image · huggingface.co/Qwen (2511 / 2509 model cards)
- SeedVR2 upscaler: github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
- ElevenLabs v3 + audio tags: elevenlabs.io/docs (Create Speech, voices/add, v3 prompting guide)
- Anthropic API: docs.claude.com (models, structured outputs, SDK)

---

## 13. Long-form mode — parallel segments (FALLBACK path + optional latency booster)

**Status with LiveAvatar as primary:** not needed for launch. LiveAvatar generates 10,000+ second continuous videos, so a 30-minute video is one uninterrupted pass (~17 min on the 5-GPU node) with zero cuts. Build this section ONLY if (a) the M5 bake-off sends us to the LongCat fallback, or (b) later, as an optional speed mode (parallel segments can cut wall time further even on LiveAvatar, trading in visible jump cuts).

**Why this design exists.** On the LongCat fallback, ~44 GPU-seconds per finished second means ~22 GPU-hours for one 30-min video, generated sequentially — parallel segmentation is the only way to acceptable wall times, and it also bounds identity drift.

**Architecture (extends M4–M6; build after the short-mode path passes M6 acceptance):**

1. **Segmentation is deterministic code, not LLM output.** New `services/segmentation.py`: after the orchestrator returns `tagged_script`, split it into segments of 60–90 estimated seconds each (~150 wpm ⇒ ~150–225 words), cutting ONLY on paragraph boundaries; never mid-sentence, never mid-tag. Each segment keeps its own slice of the tagged script.
2. **Per-segment TTS.** Each segment gets its own ElevenLabs render (same voice, same settings) → its own audio file. Do not generate one giant audio file and slice it — paragraph-aligned TTS gives natural breath pauses exactly at the cut points.
3. **Fan-out rendering.** The video_request spawns one `video_generation` job per segment (same approved look image, same style_prompt for all). The existing DB queue distributes them across however many GPU pods are online. Add `segment_index` and `parent_video_request_id` to the job payload; the request completes when all segments are done.
4. **Editorial cuts, not hidden seams.** Each segment naturally opens from the look image's pose — a visible reset if concatenated raw. Make it intentional: in the ffmpeg assembly step, apply a ~110% center punch-in (crop+scale) to every even-numbered segment. Alternating wide/close framing is the standard YouTube jump-cut grammar; viewers read it as editing, not a glitch. No transitions, no crossfades — hard cuts on paragraph pauses.
5. **Per-segment upscale, then assemble.** Run SeedVR2 on each segment in parallel (same worker pool, `upscale` jobs), then concat the 4K segments with identical encode settings (`concat` demuxer, single re-encode pass, `+faststart`). Verify total duration = sum of segment audio durations ±0.5s.
6. **Progress UI.** For long-form requests, show a segment grid (e.g. "14/22 segments rendered") plus the wall-clock estimate from §9's table based on currently-online worker count.
7. **Delivery sizes.** 30 min of 4K H.264 is roughly 5–9 GB at sane bitrates. Default long-form delivery to 1080p with 4K as an explicit optional download; generate the 1080p by downscaling the 4K master (never skip the SeedVR2 pass — 720p→1080p direct looks worse).

**Quality property worth understanding:** every segment restarts from the pristine approved look image, so identity drift is bounded to one segment's length. A 30-minute video holds identity exactly as well as a 90-second one. This is an advantage over single-pass generation, not a compromise.

**Failure handling:** a failed segment retries alone (max 2 attempts) without re-rendering the other segments; the parent request fails only if a segment exhausts retries. Segments are content-addressed by `(video_request_id, segment_index, script_hash)` so a retried parent run reuses finished segments.

**Long-form acceptance:** a 10-minute script across ≥2 workers → segments render in parallel (check timestamps overlap), cuts land on paragraph pauses, alternating framing is visible, identity consistent across all segments, audio never drifts. Then one full 30-minute validation run before launch.
