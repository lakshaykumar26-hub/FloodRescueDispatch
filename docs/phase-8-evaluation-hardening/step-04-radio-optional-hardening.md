# Phase 8 / Step 04 — Optional Radio + Security Hardening + Labeling

## Goal

Radio only after protocol + tests pass; ship hardened and honestly labeled as prototype.

## Files

- `backend/app/communications/radio_adapter.py` (stub implementing gateway interface; real driver only with compatible mesh hardware + config)
- Security checklist: device auth + role scopes, Pydantic validation everywhere, TLS where supported, SecureStore secrets, minimal mobile cache, decommission wipe, location/reports treated untrusted.
- `README.md` + UI banners: "Simulation/prototype — NOT for real emergency operations. Requires operational/comms/security/safety review."

Only after: delayed/dup/disconnect/recovery pass over radio link in controlled setting; limits documented (range, throughput, no internet-path services like push).

## What to test

- [ ] Radio adapter conformance: same gateway interface tests pass with adapter swapped in (simulated transport).
- [ ] Decommission: wipe device → no mission/cache/token recoverable.
- [ ] Over-permissioned token cannot access other devices' missions or admin inject.
- [ ] Banners visible in README + dashboard + mobile about-screen.
- [ ] Manual: controlled radio drill log (if hardware present) or explicit `NOT_TESTED_ON_HARDWARE` note.
