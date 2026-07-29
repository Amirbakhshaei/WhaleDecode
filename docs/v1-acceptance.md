# WhaleDecode v1.0 — Acceptance Criteria

## A. User-Facing Product

- [ ] 1. `/start` explains product clearly + disclaimer
- [ ] 2. User can chat `/ask` `/decode` and get structured smart-money investigation answers
- [ ] 3. System monitors curated wallets on Base + Arbitrum
- [ ] 4. High-signal events are detected
- [ ] 5. Events decoded by AI into plain-English reports:
  - what happened
  - why it might matter
  - wallet context
  - risks
  - alternatives
  - confidence
  - evidence
  - follow-ups
  - disclaimer
- [ ] 6. Paid users receive alerts in Telegram
- [ ] 7. Alert callbacks work:
  - Explain more
  - Risks
  - Related
  - Ask follow-up
- [ ] 8. `/briefing` daily briefing works
- [ ] 9. `/track` `/untrack` works with plan limits
- [ ] 10. `/alerts on|off` works
- [ ] 11. `/status` and `/upgrade` work
- [ ] 12. Free vs Paid enforcement is real and server-side

## B. Curation / Admin Operability

- [ ] 13. Curated wallets seeded and manageable
- [ ] 14. Admin can:
  - grant paid
  - add/remove curated wallet
  - list curated
- [ ] 15. Admin can view basic stats

## C. Intelligence Quality

- [ ] 16. EventInvestigationGraph works
- [ ] 17. ChatInvestigationGraph works
- [ ] 18. BriefingGraph works
- [ ] 19. AEGIS guards outputs (disclaimer, PII scrub, content filter)
- [ ] 20. RELAY formats scannable Telegram messages
- [ ] 21. AI outputs are Pydantic-validated
- [ ] 22. AgentRun logging exists (prompt/tool/latency/cost best-effort)

## D. Production Readiness

- [ ] 23. bot + worker entrypoints exist
- [ ] 24. Postgres migrations work
- [ ] 25. Redis integrated or cleanly optional with clear path
- [ ] 26. Docker Compose local run works
- [ ] 27. Railway deploy docs/settings exist
- [ ] 28. env validation exists
- [ ] 29. retries/timeouts on LLM + RPC
- [ ] 30. alert idempotency via dedupe_key
- [ ] 31. basic tests pass:
  - plan gating
  - dedupe
  - schema validation
  - one graph smoke test
- [ ] 32. README contains:
  - architecture summary
  - local run
  - seed wallets
  - Railway deploy
  - admin playbook
  - known limitations

## E. Launch Readiness

- [ ] 33. At least 100 curated wallets supportable (seed may start smaller, pipeline supports growth)
- [ ] 34. Internal demo script or make target proves:
  - chat decode
  - sample event decode
  - alert format
  - briefing format
  - channel post format
- [ ] 35. No critical security issues around admin auth/secrets
- [ ] 36. Product is narrow, stable, and chargeable

## F. Channel Auto-Publishing (In Scope v1.0)

- [ ] 37. High-signal events auto-published to Telegram channel
- [ ] 38. Channel posts include branded header + disclaimer
- [ ] 39. Daily cap (20 posts) enforced
- [ ] 40. AEGIS filters low-signal events from public channel
- [ ] 41. No duplicate events published
- [ ] 42. Bot must be channel admin (documented prerequisite)

---

**All criteria must pass before v1.0 is declared complete.**
