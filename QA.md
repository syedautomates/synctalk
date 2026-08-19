# QA.md

Manual QA checklist and running gate-review log, per the delivery plan's operating model. QA re-runs each milestone's acceptance criteria independently — not the same session that built the feature.

---

## Milestone gate log

| Milestone | Acceptance criteria (from `claude.md` §7) | Result | Notes |
|---|---|---|---|
| M0 Scaffold | `docker compose up` → `curl /healthz` = 200; CI green | **Pass** | Verified 2026-08-19: `docker compose up -d --build` → all 3 containers healthy → Alembic migration 0001 applied cleanly inside the api container → `curl localhost:8000/healthz` → `200 {"status":"ok"}`. CI green on `syedautomates/synctalk` main (ruff, mypy, migration-against-real-postgres, pytest all pass). One lint-fix cycle needed (E501 line-length) before CI went green — see `DECISIONS.md`. |
| M1 Profiles/uploads/validation | Upload golden fixtures → profile checklist all green; upload a deliberately blurry photo → clear rejection message | **Pass** | Verified 2026-08-19 via real `docker compose` stack (not mocked). Bad-photo half: synthetic 200×200 blank/faceless photo → all 3 expected rejections fired with clear messages (low resolution, blur, no face). Golden-fixture half, all real files: 3/5 real candidate photos passed (other 2 correctly rejected — visually softer, confirmed by face-region sharpness scoring); real 51.5s/4K/24fps reference video passed (`single_face_ratio=1.0`, `hands_ratio=0.885`, 12 frames extracted, primary reference frame visually confirmed sharp/upright/natural); real 54.6s voice sample passed (mean volume -16.3dB, well clear of the near-silence cutoff); consent confirmed via the live API. **Final checklist: `photos.ok=true`, `reference_video.ok=true`, `voice_sample.ok=true`, `consent=true`, `ready=true`.** Two real bugs found and fixed via this real-data testing (neither caught by the earlier synthetic test) — see `DECISIONS.md`: (1) sharpness scored on the whole frame instead of the face region, falsely rejecting genuinely-sharp zoomed-in photos with plain backgrounds; (2) phone-video rotation metadata wasn't applied to decoded frames, so face detection ran sideways and `single_face_ratio` measured 7.7% instead of the true ~100%. |
| M2 Voice pipeline | Tagged text → audible emotional delivery; 12k-char script chunks into ≥2 calls and concats into one seamless file | **Pass** (delivery quality needs your ear) | Verified 2026-08-19 against the real ElevenLabs API via the actual `/profiles/{id}/voice` endpoint (not a raw script): real IVC created from the real passed voice sample (`elevenlabs_voice_id=UBxdikrk51iTH7SzcoVC`); consent gate confirmed (`403` on a no-consent profile, before any ElevenLabs call fired); 12k-char chunking verified offline (3 chunks, all under the 4,500-char safety margin, exact text reconstruction); real TTS with `"[excited] Hello! [laughs] This is a test."` synthesized against the cloned voice, saved to `assets/test/emotion_test_output.mp3`; real multi-chunk concat path exercised (two real TTS calls → ffmpeg concat), combined duration 3.40s matched the sum of parts (1.65s + 1.80s). **Outstanding:** whether the emotional delivery actually *sounds* right is a human judgment call — Director should listen to `emotion_test_output.mp3` and confirm. |

---

## Golden fixtures (M8, pulled forward — tracked here as they're produced)

| Fixture | Status | Notes |
|---|---|---|
| 2–3 zoomed-in photos | ✅ Uploaded & validated | 5 candidates transferred to `Downloads/`; 3 (`IMG_9582/9583/9585`) passed real validation and are copied into `assets/test/photo_{1,2,3}.jpeg` (local only, gitignored — see `DECISIONS.md`). |
| 30–60s reference video (face/lips/hands) | ✅ Uploaded & validated | Landed directly in the repo folder as `IMG_9587.mov`, moved to `assets/test/reference_video.mov` (local only, gitignored). 51.5s, 4K, 24fps. Passed real validation after the rotation-metadata fix — see `DECISIONS.md`. |
| ≥30s voice sample | ✅ Uploaded & validated | `assets/test/voice_sample.mp4` (local only, gitignored). 54.6s, mean volume -16.3dB. Passed real validation. |
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
