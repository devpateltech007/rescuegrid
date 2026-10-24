# Reuse notes — kenilhv/signal-zero

Checked 2026-10-23: https://github.com/kenilhv/signal-zero has **no LICENSE file**
(`/LICENSE` and the GitHub license API both return 404). Without a license, default copyright
applies, so **no code was copied**.

Ideas re-implemented from scratch in Python/TypeScript:

| signal-zero idea | RESCUEGRID 3D implementation |
|---|---|
| Human decision log that survives pipeline re-runs | `decisions` + `invocations` tables are excluded from mission reset (`storage/db.py::AUDIT_TABLES`) |
| "A human with a name decides" | every decision endpoint requires a validated `operator` (`models/schemas.py::OperatorAction`) |
| Visible degraded-source feed instead of silent failure | `system.degraded` events → red banner + timeline + toasts; failed Bedrock calls are kept as `FAILED` invocations |
| Offline deterministic mode when credentials are missing | `RESCUEGRID_BEDROCK=0` keeps simulation, 3D and routing working; optional `OFFLINE_FIXTURE` is explicitly labelled and never marked live |
| Evidence trail per ranked item | incident cards show every observation image, source provenance, Bedrock evidence/uncertainty and decision record |

Not reused: GLOF ranking model, Bright Data ingestion, OpenAI tier-3 classifier (unrelated to this problem).
