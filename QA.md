# QA.md

Manual QA checklist and running gate-review log, per the delivery plan's operating model. QA re-runs each milestone's acceptance criteria independently — not the same session that built the feature.

---

## Milestone gate log

| Milestone | Acceptance criteria (from `claude.md` §7) | Result | Notes |
|---|---|---|---|
| M0 Scaffold | `docker compose up` → `curl /healthz` = 200; CI green | **Pending** | Blocked on Docker Desktop + Python install on Director's machine. Code is written; not yet run. |

---

## Golden fixtures (M8, pulled forward — tracked here as they're produced)

| Fixture | Status | Notes |
|---|---|---|
| 2–3 zoomed-in photos | ✅ Captured | Stored on Director's phone; not yet uploaded to the app (no upload flow exists until M1). |
| 30–60s reference video (face/lips/hands) | ✅ Captured | Natural delivery, not word-for-word scripted — includes genuine laugh, tone shift, hand gestures. Face stayed detectable despite occasional glances at laptop for script. |
| ≥30s voice sample | ✅ Captured | Separate clean audio-only recording (not extracted from reference video). |
| ~300-word test script | ✅ Locked | See `assets/test/script.txt` (to be added when `assets/test/` is created in M1/M8). Repurposed from an existing Upwork/HeyGen profile-video script — GoHighLevel/Zapier automation topic, ~270 words, natural emotional arc (serious → warm → confident → calm). |
| Emotion/movement brief example | ✅ Locked | Derived from the same source script's segment-direction table — serious/documentary opening, warm reveal, confident/rhythmic build, calm-certain close, minimal natural gestures throughout. |
| Consent confirmation | ✅ Confirmed | Director confirmed both the consent copy wording and personal consent. Copy logged in `DECISIONS.md`. |

## Manual QA checklist (per M8 — to execute once M5/M6 are complete)

- [ ] Identity match at 0s / 30s / 60s of a generated video
- [ ] Lip-sync spot check at 3 timestamps
- [ ] Hands move naturally in generated output
- [ ] No teeth artifacts
- [ ] 4K file plays in QuickTime + Chrome
- [ ] Audio drift ≤0.2s at end of video
