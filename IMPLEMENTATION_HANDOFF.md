# GreenSwap analysis overhaul handoff

Branch: `vallabha_branch`

Baseline commit: `171e84fa004d012efb33d0b19cd743a5b37f671b`

## Completed

1. Created an isolated feature branch from the existing prototype.
2. Recorded the complete offline demo responses for the soap and bottle pages in
   `backend/tests/fixtures/legacy_demo_responses.json`. These are compatibility
   fixtures, not claims that the old scores are scientifically valid.
3. Added `backend/scoring.py`, an intentionally unwired scoring foundation with:
   - a structured analysis response;
   - traceable evidence and provenance;
   - explicit unknown dimensions and coverage bounds;
   - category-specific cleaning and bottle rubrics;
   - a conservative generic fallback;
   - validation preventing unsupported certification and evidence claims;
   - method versioning for future cache invalidation;
   - calculated confidence from coverage and source provenance.
4. Added `backend/extraction.py`. It conservatively extracts normalized,
   source-linked facts from listing text while retaining marketing claims as
   unverified claims rather than evidence of performance.
5. Added `backend/identification.py` with GTIN check-digit validation, Amazon
   ASIN extraction, normalized model/SKU support, size/quantity variant
   protection, deterministic identity keys, and fail-closed identity matching.
6. Extended the scraper and backend request contract with `asin`, `gtin`,
   `model_number`, and `sku`. Exact identifiers now take priority in cache keys.
   The mock products carry stable model/SKU identifiers for repeatable demos.
   Certified lookup also tries exact identifiers before its legacy title fallback.
7. Added upgrade-safe identifier columns and GTIN indexes to the Supabase schema.
8. Added focused unit tests across scoring, extraction, identity, and the
   extension/backend product contract.

## Key decisions

- Unknown data produces `overall_score: null`; it is not converted to an average
  score. `coverage_bounds` describes the mathematical range left by missing
  dimensions and is not a statistical confidence interval.
- A certification is evidence for a relevant assessment. It does not add a
  separate bonus that could double count the same benefit.
- Price, affiliate status, commission, and brand do not enter environmental
  scoring.
- The current `/analyze` endpoint remains unchanged. This preserves the working
  extension while the new pipeline is built behind it.
- Confidence is a transparent rule based on evidence coverage and provenance.
  It is explicitly described as evidence confidence rather than statistical
  certainty or validation of the environmental rubric.
- Title similarity is capped below an exact match. Conflicting GTINs, Amazon
  ASINs, brands, model numbers, or package variants prevent confident matching.
- Extraction records explicit facts. It does not yet convert those facts into
  environmental assessments; that belongs with the ingredient/material work.

## Continue with step 7

Build ingredient and material evaluation on top of the normalized facts. Keep
the local reference data small, explicit, and auditable for the demo. Avoid
converting the presence of words such as "natural," "plastic," or "recyclable"
directly into a safety conclusion.

Suggested sequence:

1. Add an ingredient/material reference module with the scope and source for
   every rule.
2. Translate supported normalized facts into explicit rubric assessments.
3. Add fixture evidence for the two mock-store products and every fallback
   alternative, then score originals and alternatives through the same function.
4. Version the cache with the identity, evidence fingerprint, and method version.
5. Add the structured result alongside legacy fields in `/analyze` only after
   the fixtures score end to end.

Run the current scoring checks with:

```bash
/opt/homebrew/bin/python3.12 -m unittest discover -s backend/tests -v
```

The system `python3` on the original development machine is Python 3.9; the
existing backend already uses Python 3.10+ type syntax. Python 3.12 is available
at the path above.
