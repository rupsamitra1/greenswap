# GreenSwap

GreenSwap is a Chrome extension prototype that explains a product's environmental score and suggests a meaningfully better option at the same sticker price or less.

Built for the C2S Tech NextGen Internship 2026 (Group 4).

## What the demo proves

The `/analyze` pipeline is deterministic and inspectable:

1. **Identify** — prefer GTIN/ASIN/model/SKU over title similarity and protect size variants.
2. **Extract** — retain source-linked facts, while words such as “natural” and “eco-friendly” remain unverified marketing claims.
3. **Assess** — translate only supported facts into category-specific dimensions. Unknown data stays unknown; it never becomes an average score.
4. **Score** — total ingredient/material impact, environmental fate or reuse, packaging, and concentration/end-of-life. A point score requires full rubric coverage.
5. **Compare** — analyze the viewed item and every alternative with the same rubric and version.
6. **Qualify** — require adequate evidence confidence, the same category, and at least a 10-point environmental improvement.
7. **Rank** — enforce the current sticker price as the default ceiling, then consider value and availability.

The UI exposes the completed stages, dimension points, evidence confidence, missing-data warnings, sticker and per-use pricing, and the scoring method version. This is a screening prototype—not a product-safety certification or a measured life-cycle assessment.

## Verified citations and model providers

**The verified badge is a guarantee, not a label.** On a cache miss the model runs a short research loop (`backend/agent.py`): it may search the certification database, look up a certification programme's official reference, and search the catalog for cheaper greener options. It must then cite a source for anything it claims. Crucially, citations are checked against *recorded tool output* before they reach the shopper -- a model that invents "EPA Safer Choice", or cites a plausible-looking URL it never received, is silently downgraded to an estimate. Telling a model not to fabricate certifications is a request; discarding unsupported claims server-side is a guarantee. Set `GREENSWAP_AGENT=off` to fall back to a single classification call.

The agent runs on either provider unchanged, because both speak the same tool-calling API.

## Affiliate policy in the demo

Environmental scores never include affiliate status, price, brand, or commission rate.

After a product qualifies environmentally, an affiliate product may receive at most a **3-point recommendation boost**, and only when it is within **4 environmental points** of the best qualified option. The raw environmental score remains visible and unchanged. If this rule changes the order, the UI says so. Partner links are labeled, and commission percentage is never a ranking input.

The soap page deliberately demonstrates this: the non-partner option scores 85 and the partner option scores 84; the disclosed 3-point ranking preference places the partner first. A five-point environmental gap cannot be crossed by the affiliate rule.

## Run locally

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.main:app --reload --port 8000
```

Then:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose **Load unpacked** and select `extension/`.
4. Open <http://localhost:8000/store/>.

### Adding an API key

Either provider works. Gemini exposes an OpenAI-compatible endpoint, so both share one client, one tool-calling loop, and one test suite — only the base URL and model id differ.

**Gemini (recommended — free tier).** Get a key at <https://aistudio.google.com/apikey>, then in `backend/.env`:

    GEMINI_API_KEY=AIza...

The current default model is listed in `backend/.env.example`.

**Azure OpenAI.** Configure the endpoint, key, and deployment fields in `backend/.env`. With both providers present, Gemini wins; force either with `GREENSWAP_PROVIDER=gemini|azure`.

The three reliable demo stories are:

- **Ultra Clean Dish Soap** — a 50-point product with two cheaper, documented swaps and a visible affiliate-equivalence example.
- **Disposable Plastic Water Bottles** — a 10-point single-use product compared with durable reusable options.
- **BetterDrop Refill** — a 100-point product that produces an honest “keep this one” result.

All demo brands, profiles, certifications, use counts, and purchase destinations are fictional fixtures. `example.com` purchase links demonstrate affiliate behavior without representing a commercial relationship.

Run verification:

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
node --check extension/content.js
node --check extension/scrapers.js
```

## Optional services

The demo is fully functional without Azure OpenAI or Supabase. Copy `backend/.env.example` to `backend/.env` to configure them. `/health` reports configuration state, and `/selftest` performs one uncached model call for setup diagnostics.

Cached estimates are keyed by product identity, evidence fingerprint, and scoring method version; rows also record model version and expire after 30 days. Apply `supabase/schema.sql` to add the current fields to an existing database.

## Project map

```text
extension/              Chrome MV3 extension and explanation UI
backend/main.py         FastAPI endpoint and graceful external-service fallback
backend/scoring.py      deterministic category rubrics
backend/extraction.py   conservative listing fact extraction
backend/identification.py exact identity and variant matching
backend/reference_data.py auditable material/ingredient question flags
backend/evaluation.py   shared original/alternative evaluation path
backend/pricing.py      sticker, unit, and estimated per-use comparison
backend/ranking.py      environmental eligibility and separate affiliate policy
backend/demo_catalog.py fictional, internally consistent demo evidence
store/                  three-page local demo retailer
supabase/schema.sql     optional database schema and migration
```

Start the backend with:

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

`--host 0.0.0.0` matters. Uvicorn defaults to IPv4 `127.0.0.1` only, but on
Windows `localhost` resolves to the IPv6 loopback `::1` first — so a browser
extension calling `http://localhost:8000` gets a connection refused that
surfaces as a bare "Failed to fetch" with nothing else to go on. The
extension asks for `127.0.0.1` first for the same reason.

Use `python -m uvicorn`, not the bare `uvicorn` command: pip installs it into a `Scripts` directory that is not on `PATH` by default on Windows. Note also that Windows PowerShell 5.1 has no `&&` operator — chain with `;` or run the two lines separately.

## Important limits

- The rubric is a transparent product decision for a demo, not a peer-reviewed LCA methodology.
- Real ingredient conclusions require authoritative hazard/fate datasets and exact chemical identity; “synthetic,” “natural,” or a material name is not itself a verdict.
- Durable-product break-even depends on actual reuse count, washing, manufacturing, transport, and local disposal. The demo shows estimated uses but does not claim a universal break-even point.
- The curated catalog is intentionally small. Live Supabase alternative rows still need structured evidence records before they should enter this score-based ranking pipeline.
- Amazon selectors can change, and no Walmart or Target scraper is implemented.
- Affiliate destinations are placeholders; real programs need network approval, tracking parameters, conversion reporting, and periodic link validation.
