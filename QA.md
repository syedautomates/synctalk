# QA.md

Manual QA checklist and running gate-review log, per the delivery plan's operating model. QA re-runs each milestone's acceptance criteria independently — not the same session that built the feature.

---

## Milestone gate log

| Milestone | Acceptance criteria (from `claude.md` §7) | Result | Notes |
|---|---|---|---|
| M0 Scaffold | `docker compose up` → `curl /healthz` = 200; CI green | **Pass** | Verified 2026-08-19: `docker compose up -d --build` → all 3 containers healthy → Alembic migration 0001 applied cleanly inside the api container → `curl localhost:8000/healthz` → `200 {"status":"ok"}`. CI green on `syedautomates/synctalk` main (ruff, mypy, migration-against-real-postgres, pytest all pass). One lint-fix cycle needed (E501 line-length) before CI went green — see `DECISIONS.md`. |
| M1 Profiles/uploads/validation | Upload golden fixtures → profile checklist all green; upload a deliberately blurry photo → clear rejection message | **Pass** (photos + video; voice pending) | Verified 2026-08-19 via real `docker compose` stack (not mocked). Bad-photo half: synthetic 200×200 blank/faceless photo → all 3 expected rejections fired with clear messages (low resolution, blur, no face). Golden-fixture half, real files: 3/5 real candidate photos passed (other 2 correctly rejected — visually softer, confirmed by face-region sharpness scoring); real 51.5s/4K/24fps reference video passed with `single_face_ratio=1.0`, `hands_ratio=0.885`, 12 frames extracted, primary reference frame visually confirmed sharp/upright/natural. Two real bugs found and fixed via this real-data testing (not caught by the earlier synthetic test) — see `DECISIONS.md`: (1) sharpness scored on the whole frame instead of the face region, falsely rejecting genuinely-sharp zoomed-in photos with plain backgrounds; (2) phone-video rotation metadata wasn't applied to decoded frames, so face detection ran sideways and `single_face_ratio` measured 7.7% instead of the true ~100%. `photos.ok` and `reference_video.ok` both `true` in the live checklist. **Voice sample not yet tested** — file not yet transferred to this machine, so `voice_sample.ok` and full `ready` remain unverified. |

---

## Golden fixtures (M8, pulled forward — tracked here as they're produced)

| Fixture | Status | Notes |
|---|---|---|
| 2–3 zoomed-in photos | ✅ Uploaded & validated | 5 candidates transferred to `Downloads/`; 3 (`IMG_9582/9583/9585`) passed real validation and are copied into `assets/test/photo_{1,2,3}.jpeg` (local only, gitignored — see `DECISIONS.md`). |
| 30–60s reference video (face/lips/hands) | ✅ Uploaded & validated | Landed directly in the repo folder as `IMG_9587.mov`, moved to `assets/test/reference_video.mov` (local only, gitignored). 51.5s, 4K, 24fps. Passed real validation after the rotation-metadata fix — see `DECISIONS.md`. |
| ≥30s voice sample | ⏳ Not yet on this machine | Director confirmed a separate clean audio-only recording exists, but the file hasn't been transferred here yet — validation not yet run. |
| ~300-word test script | ✅ Locked | `assets/test/script.txt` (tracked in git — small text file). Repurposed from an existing Upwork/HeyGen profile-video script — GoHighLevel/Zapier automation topic, ~270 words, natural emotional arc (serious → warm → confident → calm). |
| Emotion/movement brief example | ✅ Locked | `assets/test/emotion_brief.txt` (tracked in git). Derived from the same source script's segment-direction table — serious/documentary opening, warm reveal, confident/rhythmic build, calm-certain close, minimal natural gestures throughout. |
| Consent confirmation | ✅ Confirmed | Director confirmed both the consent copy wording and personal consent. Copy logged in `DECISIONS.md`. |

## Manual QA checklist (per M8 — to execute once M5/M6 are complete)

- [ ] Identity match at 0s / 30s / 60s of a generated video
- [ ] Lip-sync spot check at 3 timestamps
- [ ] Hands move naturally in generated output
- [ ] No teeth artifacts
- [ ] 4K file plays in QuickTime + Chrome
- [ ] Audio drift ≤0.2s at end of video
