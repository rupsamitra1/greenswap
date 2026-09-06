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
   - method versioning for future cache invalidation.
4. Added focused unit tests in `backend/tests/test_scoring.py`.

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
- `confidence: uncalibrated` is deliberate. Calibration belongs in step 5; the
  prototype must not imply measured certainty before that work exists.

## Continue with step 4

Build fact extraction and normalization as a separate module. It should turn
scraped listing fields into candidate evidence and assessments, while keeping
inferred facts distinguishable from documented facts. Do not wire it into
`/analyze` until fixture products can be scored end to end.

Suggested sequence:

1. Add normalized product facts for ingredients/materials, packaging, product
   format, concentration, and reuse.
2. Add fixture evidence for the two mock-store products and every fallback
   alternative.
3. Score originals and alternatives through the same function.
4. Add the structured result alongside legacy fields in `/analyze`.
5. Compare responses with the legacy fixture, then update the extension UI in a
   later step.

Run the current scoring checks with:

```bash
/opt/homebrew/bin/python3.12 -m unittest backend.tests.test_scoring -v
```

The system `python3` on the original development machine is Python 3.9; the
existing backend already uses Python 3.10+ type syntax. Python 3.12 is available
at the path above.
