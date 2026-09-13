# GreenSwap

A browser extension that shows a **verified greener alternative — at the same price or cheaper** — directly on the product page, at the moment the shopper is deciding what to buy.

Built for the C2S Tech NextGen Internship 2026 (Group 4).

---

## How it works

```
product page ──▶ content script scrapes title, price, brand, bullets
                          │
                          ▼
                 service worker ──▶ POST /analyze
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                         ▼
     1. certified lookup        2. estimate cache          3. Azure OpenAI
        (EPA Safer Choice,         (skip the model            (infer materials
         ENERGY STAR)               entirely on a hit)         when unlisted)
              │                         │                         │
              └─────────────────────────┴─────────────────────────┘
                          │
                          ▼
              4. alternatives in the same category,
                 eco_score higher, price ≤ original
                          │
                          ▼
                 card injected on the page
```

Three design decisions carry the product:

**The verified badge is a guarantee, not a label.** On a cache miss the model runs a short research loop (`backend/agent.py`): it may search the certification database, look up a certification programme's official reference, and search the catalog for cheaper greener options. It must then cite a source for anything it claims. Crucially, citations are checked against *recorded tool output* before they reach the shopper -- a model that invents "EPA Safer Choice", or cites a plausible-looking URL it never received, is silently downgraded to an estimate. Telling a model not to fabricate certifications is a request; discarding unsupported claims server-side is a guarantee. Set `GREENSWAP_AGENT=off` to fall back to a single classification call.

The agent runs on either provider unchanged, because both speak the same tool-calling API.


**Certified before estimated.** The database is consulted first, and the model runs only when a product has no published materials. Every result the user sees is labeled `✓ Verified` or `~ AI estimated`, so nobody has to take an opaque eco-score on faith. This is the answer to the 55% of consumers who distrust sustainability claims.

**Price is a ceiling by default, and only the shopper can lift it.** `find_alternatives` never returns anything costing more than the original. When nothing qualifies, `find_pricier` offers greener-but-dearer options — but the card keeps them behind an explicit "show N that cost more" button, so a pricier suggestion is always something the shopper asked for. The unprompted answer stays "same price or cheaper, or nothing at all."

When the price cannot be scraped at all, the ceiling cannot be enforced, so the card says so plainly rather than letting the promise lapse in silence.

**Estimates are cached across users.** Running a model on every product page every shopper opens is the cost problem flagged in the Week 4 reflection. Estimates are keyed by a normalized hash of brand + title in `ai_estimates`, so the hundredth shopper to view a product pays nothing.

---

## Tests

```bash
cd backend
python tests/test_llm.py     # single-call paths: parsing, retries, error handling
python tests/test_agent.py   # the research loop and its citation enforcement
```

Both stub the model client, so they need no key, no network, and no provider.

## Setup

### 1. Backend

```bash
cd backend && pip install -r requirements.txt
```

### Adding an API key

Either provider works. Gemini exposes an OpenAI-compatible endpoint, so both share one client, one tool-calling loop, and one test suite — only the base URL and model id differ.

**Gemini (recommended — free tier).** Get a key at <https://aistudio.google.com/apikey>, then in `backend/.env`:

    GEMINI_API_KEY=AIza...

That is the whole setup. `GEMINI_MODEL` defaults to `gemini-2.0-flash`.

**Azure OpenAI.** Three values instead:

    AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
    AZURE_OPENAI_API_KEY=<the long key string>
    AZURE_OPENAI_DEPLOYMENT=<your deployment name>

`AZURE_OPENAI_DEPLOYMENT` is the **deployment name you chose in Azure AI Foundry**, not the model name. That mismatch is the most common failure, and it surfaces as a 404.

With both present, Gemini wins; force either with `GREENSWAP_PROVIDER=gemini|azure`.

The server reads `.env` once at startup, so **restart it after editing**.

Then confirm it actually works:

```bash
curl http://localhost:8000/selftest
```

That makes one real model call and reports the outcome. `"ok": true` comes back with the model's scoring of a sample product. `"ok": false` comes back with the actual error and a hint naming the likely cause, written for whichever provider is active. This endpoint exists because every failure path in `/analyze` degrades gracefully into the offline estimator — which is right for shoppers, and useless when you are trying to find out whether your key works. `/health` reports the active provider, the model, and the running call/failure counts.

`.env` is gitignored. Never commit it.

Supabase is optional. With `SUPABASE_URL` blank, the backend serves a built-in demo catalog and caches estimates in memory, which is enough to run the whole demo offline.

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

Check it came up: <http://localhost:8000/health> reports whether Supabase and Azure OpenAI are actually wired in.

### 2. Database (optional)

Paste `supabase/schema.sql` into the Supabase SQL editor. It creates the three tables, the RLS policies, and the demo seed rows.

Note the RLS behavior: with row-level security on and no `select` policy, queries return **empty results silently** instead of erroring. If alternatives stop appearing, check the policies before you check the code.

### 3. Extension

1. Open `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select the `extension/` folder

### 4. Demo

With the backend running, open <http://localhost:8000/store/> and click a product. The card appears under the Add to Cart button.

The same extension also runs on `https://www.amazon.com/*` product pages. Amazon's markup changes often, so the scraper tries several selectors per field and the card falls back to a floating position when the buy box cannot be found — but the mock storefront is the reliable surface to demo on.

---

## Layout

```
extension/     Chrome MV3 extension
  manifest.json
  scrapers.js    per-retailer page scrapers
  content.js     shadow-DOM card, injection, fallback placement
  background.js  service worker; all backend traffic routes through here
backend/       FastAPI service (also serves the mock storefront)
  main.py
store/         mock retailer used for demos
supabase/      schema, RLS policies, seed data
```

## Current limits

- The alternatives catalog is a small seeded set, not a live retailer feed. Real coverage needs a product data API.
- Material inference from images is not implemented; the model currently reads the title and bullet text only.
- Only Amazon has a real scraper. Walmart and Target are named in the deliverables and are not built.
- No affiliate link wrapping yet, so the primary revenue path is not exercised.
