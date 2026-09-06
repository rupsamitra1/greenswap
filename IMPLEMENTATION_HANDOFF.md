# GreenSwap analysis overhaul handoff

Branch: `vallabha_branch`

Baseline commit: `171e84fa004d012efb33d0b19cd743a5b37f671b`

## Completed

All 18 planned implementation steps are complete on this branch:

- isolated branch and legacy-response fixtures;
- deterministic category scoring with explicit unknowns and evidence confidence;
- conservative extraction, strong product identity, and variant protection;
- auditable ingredient/material flags and complete fictional demo evidence;
- versioned/expiring cache keys using identity, evidence fingerprint, method, and model version;
- identical evaluation for originals and alternatives;
- sticker, unit, and estimated per-use price bases;
- recommendation eligibility, keep-current behavior, and hard default price ceiling;
- a disclosed affiliate preference of at most 3 points inside a 4-point eco-equivalence band, with raw eco scores untouched;
- expanded API contract plus legacy UI fields;
- extension explanation UI and clickable, labeled partner links;
- three end-to-end demo stories, including an already-sustainable product;
- unit/API tests and local backend verification.

## Verification

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
node --check extension/content.js
node --check extension/scrapers.js
```

The local virtual environment is gitignored. No Azure or Supabase credentials are required for the demo. Demo claims and outbound URLs are explicitly fictional placeholders.

## Future production work

Replace demo evidence with licensed/authoritative product and chemical data, model durable-product break-even by use scenario, store structured evidence for live catalog rows, add retailer price/availability feeds, connect real affiliate programs and conversion callbacks, and validate the methodology with domain experts.

Do not merge automatically; review this branch first.
