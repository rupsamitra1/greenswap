"""
GreenSwap backend (FastAPI).

Pipeline for /analyze:
1. Identify the exact product and separate documented facts from marketing.
2. Check verified records, then a versioned evidence cache.
3. On a cache miss, use Gemini or Azure with server-verified citations.
4. Score structured dimensions and run alternatives through the same rubric.
5. Apply eligibility, price, and disclosed affiliate ranking after eco scoring.

Everything degrades gracefully: with no Supabase and no model credentials the
service still answers from a built-in catalog and a keyword heuristic, so the
demo never depends on the network.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload
"""

import json
import os
import re
import threading
import time
import urllib.parse
import types
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    # Supports both `uvicorn backend.main:app` from the repo root and the
    # documented `uvicorn main:app` command from inside backend/.
    from backend.identification import identify_product
    from backend.demo_catalog import alternatives as catalog_alternatives
    from backend.evaluation import evaluate_product
    from backend.pricing import price_basis
    from backend.ranking import rank_candidates
    from backend.scoring import METHOD_VERSION
    from backend import agent as agent_mod, evaluation as evidence_eval
    from backend import heuristics, identification, pricing, product_search
except ModuleNotFoundError:
    from identification import identify_product
    from demo_catalog import alternatives as catalog_alternatives
    from evaluation import evaluate_product
    from pricing import price_basis
    from ranking import rank_candidates
    from scoring import METHOD_VERSION
    import agent as agent_mod
    import evaluation as evidence_eval
    import heuristics
    import identification
    import pricing
    import product_search

def _ensure_env_file() -> None:
    """Create .env from .env.example on first run.

    .env is gitignored (it must be), so a fresh clone has no such file and
    the operator has to know to copy the template first. Doing it here means
    "drop your key in backend/.env" is literally the only step.
    """
    here = Path(__file__).resolve().parent
    env, template = here / ".env", here / ".env.example"
    if not env.exists() and template.exists():
        env.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[GreenSwap] Created {env} from .env.example - add your API key there.")


_ensure_env_file()
load_dotenv()

app = FastAPI(title="GreenSwap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,
)

@app.middleware("http")
async def allow_private_network(request, call_next):
    """Permit requests from a public page to this local server.

    Chrome's Private Network Access rules gate requests that originate from a
    public site (amazon.com) toward a private address (localhost). Without this
    header the extension works on the local mock store and fails on Amazon --
    which looks like a backend outage rather than a browser policy.
    """
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# The mock storefront is served by this same process so the extension only ever
# needs one origin permission (http://localhost:8000/*).
STORE_DIR = Path(__file__).resolve().parent.parent / "store"
if STORE_DIR.is_dir():
    app.mount("/store", StaticFiles(directory=STORE_DIR, html=True), name="store")


# ---------------------------------------------------------------------------
# Config -- set these in .env (see .env.example). Never hardcode keys.
# ---------------------------------------------------------------------------
def _clean(value: str | None) -> str | None:
    """Trim whitespace and stray quotes.

    Pasting a key out of the Azure portal very often brings along a trailing
    newline or a pair of quotes, which produces a 401 that looks like a bad
    key rather than a bad paste.
    """
    if value is None:
        return None
    return value.strip().strip('"').strip("'") or None


SUPABASE_URL = _clean(os.getenv("SUPABASE_URL"))
SUPABASE_KEY = _clean(os.getenv("SUPABASE_SERVICE_KEY"))

AZURE_ENDPOINT = _clean(os.getenv("AZURE_OPENAI_ENDPOINT"))
AZURE_API_KEY = _clean(os.getenv("AZURE_OPENAI_API_KEY"))
AZURE_DEPLOYMENT = _clean(os.getenv("AZURE_OPENAI_DEPLOYMENT")) or "gpt-4o-mini"
AZURE_API_VERSION = _clean(os.getenv("AZURE_OPENAI_API_VERSION")) or "2024-10-21"

if AZURE_ENDPOINT:
    # The portal offers a full "target URI" like
    #   https://res.openai.azure.com/openai/deployments/x/chat/completions?api-version=...
    # The SDK wants only the resource root; pasting the whole thing yields a
    # 404 that reads like a wrong deployment name.
    if "/openai/" in AZURE_ENDPOINT:
        AZURE_ENDPOINT = AZURE_ENDPOINT.split("/openai/")[0]
    if not AZURE_ENDPOINT.startswith("http"):
        AZURE_ENDPOINT = "https://" + AZURE_ENDPOINT
    if not AZURE_ENDPOINT.endswith("/"):
        AZURE_ENDPOINT += "/"

# A hung call must not hold a product page waiting.
REQUEST_TIMEOUT = float(
    _clean(os.getenv("LLM_TIMEOUT")) or _clean(os.getenv("AZURE_OPENAI_TIMEOUT")) or 20
)

# --- provider -------------------------------------------------------------
# Gemini exposes an OpenAI-compatible endpoint, so the same client, the same
# tool-calling loop and the same tests serve both providers. Only the base URL
# and the model id differ.
PROVIDER = (_clean(os.getenv("GREENSWAP_PROVIDER")) or "auto").lower()
GEMINI_API_KEY = _clean(os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = _clean(os.getenv("GEMINI_MODEL")) or "gemini-3.6-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Optional local pacing. Gemini's free tier benefits from a 5 RPM cap, but an
# Azure deployment already enforces its own purchased quota. Applying the
# Gemini cap to Azure made two product pages look like exhausted Azure credits.
# Set 0 to trust the provider's limits and allow every product analysis through.
_default_rpm = 5 if GEMINI_API_KEY and PROVIDER != "azure" else 0
LLM_RPM = int(_clean(os.getenv("LLM_RPM")) or _default_rpm)

# ...but a shopper is waiting on the other end of this. Queueing behind the
# quota is only worth doing briefly; past this we answer with the heuristic
# rather than leave a product page hanging.
LLM_MAX_WAIT = float(_clean(os.getenv("LLM_MAX_WAIT")) or 8)

# Hard ceiling on a single /analyze. Chrome terminates an MV3 service worker
# that sits idle for roughly 30 seconds, so a slow answer is not a slow answer
# -- it is no answer at all, and the card never renders. Past this we return
# the rules-based result, which is always ready.
ANALYZE_DEADLINE = float(_clean(os.getenv("ANALYZE_DEADLINE")) or 18)

# Surfaced by /health and /selftest so a misconfigured key is visible rather
# than silently degrading into the offline fallback.
AGENT_ENABLED = (_clean(os.getenv("GREENSWAP_AGENT")) or "on").lower() != "off"

llm_status: dict = {"calls": 0, "failures": 0, "last_error": None, "json_mode": True,
                       "agent_runs": 0, "agent_failures": 0}

# Affiliate tag, appended to outbound links when set. This is the hook for the
# primary revenue stream in the business model; without it the links still work,
# they just earn nothing.
AMAZON_AFFILIATE_TAG = _clean(os.getenv("AMAZON_AFFILIATE_TAG"))

# Fallback product search, used only when the browser's own scrape comes back
# empty. The free tier is 100 requests/month, so results are cached by query.
CANOPY_API_KEY = _clean(os.getenv("CANOPY_API_KEY"))
_search_cache: dict[str, list[dict]] = {}

# An alternative must beat the original by this much to be worth suggesting.
ECO_SCORE_MARGIN = 10

# ...and must be genuinely green in its own right. A relative margin alone is
# not enough: when the viewed product scores 15, "beat it by 10" admits a 25,
# and disposable plastic cups get recommended as the greener swap for
# disposable plastic cups. 60 is the floor of the durable/reusable band.
MIN_RECOMMEND_SCORE = int(_clean(os.getenv("MIN_RECOMMEND_SCORE")) or 60)

# Which scorer answers when no model is available.
#
#   auto   evidence pipeline when it can answer, rules when it cannot
#   rules  keyword signals only
#
# There is deliberately no evidence-only mode. That pipeline scores from
# documented facts and declines otherwise, and a retail listing documents
# almost nothing -- its catalog matches on SKU or model number, which scraped
# listings do not carry. Evidence-only would therefore answer "insufficient"
# for essentially every real product, and a mode that always says nothing is
# worse than no mode. "auto" uses evidence the moment real product data exists
# and stays useful until then.
SCORER = (_clean(os.getenv("GREENSWAP_SCORER")) or "auto").lower()
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    from supabase import create_client

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def _retry_delay_seconds(message: str) -> float:
    """Google states exactly how long to wait; obey it rather than guessing."""
    for pattern in (r"'retryDelay':\s*'([\d.]+)s'", r"retry in ([\d.]+)s"):
        found = re.search(pattern, message)
        if found:
            return min(float(found.group(1)) + 0.5, 30.0)
    return 5.0


_rate_lock = threading.Lock()
_recent_calls: deque = deque()


class RateBudgetExceeded(RuntimeError):
    """No quota slot within the time a shopper should be asked to wait."""


def _throttle(budget: float | None = None) -> None:
    """Wait for a slot in the per-minute allowance, but not indefinitely."""
    if LLM_RPM <= 0:
        return
    deadline = time.monotonic() + (LLM_MAX_WAIT if budget is None else budget)
    while True:
        with _rate_lock:
            now = time.monotonic()
            while _recent_calls and now - _recent_calls[0] > 60:
                _recent_calls.popleft()
            if len(_recent_calls) < LLM_RPM:
                _recent_calls.append(now)
                return
            wait = 60 - (now - _recent_calls[0]) + 0.25

        if time.monotonic() + wait > deadline:
            raise RateBudgetExceeded(
                f"rate limit: no slot within {LLM_MAX_WAIT:.0f}s "
                f"({LLM_RPM}/min allowance)"
            )
        print(f"[GreenSwap] rate limit reached, waiting {wait:.1f}s")
        time.sleep(max(wait, 0.1))


class ThrottledClient:
    """Wraps the provider client so every call is paced and 429-aware.

    The agent loop and the single-call path both go through here, so the
    allowance is shared rather than each path having its own idea of it.
    """

    def __init__(self, inner):
        self._inner = inner
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        last = None
        for attempt in range(3):
            _throttle()
            try:
                return self._inner.chat.completions.create(**kwargs)
            except Exception as exc:
                message = str(exc)
                if "429" not in message and "RESOURCE_EXHAUSTED" not in message:
                    raise
                last = exc
                delay = _retry_delay_seconds(message)
                if delay > LLM_MAX_WAIT:
                    raise RateBudgetExceeded(
                        f"rate limit: provider asked for {delay:.0f}s"
                    ) from exc
                print(f"[GreenSwap] 429; retrying in {delay:.1f}s "
                      f"(attempt {attempt + 1}/3)")
                time.sleep(delay)
        raise last


llm_client = None
MODEL_NAME = None
ACTIVE_PROVIDER = None

_want_gemini = PROVIDER in ("auto", "gemini") and GEMINI_API_KEY
_want_azure = PROVIDER in ("auto", "azure") and AZURE_ENDPOINT and AZURE_API_KEY

if PROVIDER == "gemini" or (_want_gemini and PROVIDER != "azure"):
    if GEMINI_API_KEY:
        from openai import OpenAI

        llm_client = OpenAI(
            api_key=GEMINI_API_KEY,
            base_url=GEMINI_BASE_URL,
            timeout=REQUEST_TIMEOUT,
            max_retries=2,
        )
        llm_client = ThrottledClient(llm_client)
        MODEL_NAME = GEMINI_MODEL
        ACTIVE_PROVIDER = "gemini"
elif _want_azure:
    from openai import AzureOpenAI

    llm_client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
        api_version=AZURE_API_VERSION,
        timeout=REQUEST_TIMEOUT,
        max_retries=2,
    )
    llm_client = ThrottledClient(llm_client)
    MODEL_NAME = AZURE_DEPLOYMENT
    ACTIVE_PROVIDER = "azure"

# Used only when Supabase is not configured, so the cache still works locally.
_memory_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class Listing(BaseModel):
    """One real search result the extension pulled from the retailer.

    The browser does this fetch, not the server: the content script is already
    inside the retailer's origin with the shopper's own session, so results
    load the way they would for any visitor. A server doing it would be
    scraping from a datacenter IP and would be blocked in short order.
    """

    name: str
    price: float | None = None
    url: str | None = None
    source: str | None = "live"


class Product(BaseModel):
    """Structured product data scraped from the page by the content script."""

    title: str
    price: float | None = None
    brand: str | None = None
    bullets: list[str] = []
    image_url: str | None = None
    url: str | None = None
    retailer: str | None = None
    asin: str | None = None
    gtin: str | None = None
    model_number: str | None = None
    sku: str | None = None
    # Candidate alternatives the extension already fetched from the store.
    listings: list[Listing] = []


# ---------------------------------------------------------------------------
# Built-in catalog -- mirrors supabase/schema.sql so the demo runs with no DB.
# ---------------------------------------------------------------------------
# Keyword heuristic used when no LLM is reachable. Deliberately crude -- it
# exists so the demo degrades to something honest rather than to an error.
CATEGORY_KEYWORDS = {
    "cleaning": ["soap", "detergent", "cleaner", "dish", "laundry", "wipes"],
    "bottles": ["bottle", "cup", "tumbler", "mug", "straw", "water"],
    "personal_care": ["shampoo", "toothpaste", "lotion", "deodorant", "razor"],
    "kitchen": ["wrap", "foil", "bag", "container", "utensil", "plate"],
}


def guess_category(text: str) -> str:
    lowered = text.lower()
    for category, words in CATEGORY_KEYWORDS.items():
        if any(word in lowered for word in words):
            return category
    return "other"


# ---------------------------------------------------------------------------
# Step 1: certified lookup (ground truth)
# ---------------------------------------------------------------------------
def lookup_certified(product_or_title):
    """Check exact identifiers before falling back to the legacy title match."""
    if not supabase:
        return None
    if isinstance(product_or_title, str):
        title = product_or_title.strip()
        data = {"title": title}
    else:
        data = (product_or_title.model_dump() if hasattr(product_or_title, "model_dump")
                else product_or_title.dict() if hasattr(product_or_title, "dict")
                else dict(product_or_title))
        title = str(data.get("title") or "").strip()
    if not title:
        return None
    identity = identify_product(data)
    exact_filters = []
    if identity.gtin:
        exact_filters.append({"gtin": identity.gtin})
    if identity.asin and identity.retailer:
        exact_filters.append({"retailer": identity.retailer, "asin": identity.asin})
    if identity.brand and identity.model_number:
        exact_filters.append({"brand": identity.brand, "model_number": identity.model_number})
    if identity.retailer and identity.brand and identity.sku:
        exact_filters.append({"retailer": identity.retailer, "brand": identity.brand, "sku": identity.sku})

    for filters in exact_filters:
        try:
            query = supabase.table("certified_products").select("*")
            for field, value in filters.items():
                query = query.ilike(field, value) if field == "brand" else query.eq(field, value)
            res = query.limit(1).execute()
            if res.data:
                return res.data[0]
        except Exception as exc:
            # An existing optional database may not have the new identifier
            # columns until schema.sql is applied. Preserve the old demo path.
            print(f"[GreenSwap] Exact certified lookup unavailable: {exc}")
            break

    res = (supabase.table("certified_products").select("*")
           .ilike("name", f"%{title}%").limit(1).execute())
    return res.data[0] if res.data else None


# ---------------------------------------------------------------------------
# Step 2: the cache -- this is what keeps per-page LLM cost off the floor
# ---------------------------------------------------------------------------
def cache_key(product: Product, evidence_fingerprint: str = "unversioned") -> str:
    """Version identity-keyed estimates so methodology changes invalidate them."""
    data = product.model_dump() if hasattr(product, "model_dump") else product.dict()
    return f"{METHOD_VERSION}:{identify_product(data).identity_key}:{evidence_fingerprint[:16]}"


def cache_get(key: str):
    if supabase:
        res = (
            supabase.table("ai_estimates")
            .select("*")
            .eq("query_hash", key)
            .limit(1)
            .execute()
        )
        row = res.data[0] if res.data else None
    else:
        row = _memory_cache.get(key)
    if row and row.get("expires_at"):
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if expires <= datetime.now(timezone.utc):
            return None
    return row


def cache_put(key: str, product: Product, estimate: dict, evidence_fingerprint: str | None = None):
    row = {
        "query_hash": key,
        "query": product.title[:500],
        "category": estimate["category"],
        "materials": estimate["materials"],
        "eco_score": estimate["eco_score"],
        "reason": estimate["reason"],
        "method_version": METHOD_VERSION,
        "model_version": MODEL_NAME or "offline-heuristic",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "evidence_fingerprint": evidence_fingerprint,
        # Without these a cache hit would quietly drop the evidence and
        # downgrade a verified product to an estimate.
        "citations": estimate.get("citations") or [],
        "verified": bool(estimate.get("verified")),
        "certification": estimate.get("certification"),
        # Without this a cached rule-based score comes back labelled as an AI
        # estimate, which is precisely the confusion the labels exist to stop.
        "source": estimate.get("source"),
    }
    if supabase:
        try:
            supabase.table("ai_estimates").upsert(row, on_conflict="query_hash").execute()
        except Exception as exc:
            # Existing demo databases remain usable until the migration is run.
            print(f"[GreenSwap] Versioned cache columns unavailable: {exc}")
            legacy = {k: row[k] for k in ("query_hash", "query", "category", "materials", "eco_score", "reason")}
            supabase.table("ai_estimates").upsert(legacy, on_conflict="query_hash").execute()
    else:
        _memory_cache[key] = row


# ---------------------------------------------------------------------------
# Step 3: AI estimation for products with no published materials
# ---------------------------------------------------------------------------
ESTIMATE_PROMPT = """You are a sustainability analyst. Given a product listing,
estimate its likely materials and environmental impact.

Respond ONLY with JSON, no markdown fences, in this exact shape:
{
  "category": "one of: cleaning, bottles, personal_care, kitchen, other",
  "materials": ["list", "of", "likely", "materials"],
  "eco_score": 0-100 integer,
  "reason": "one plain-English sentence explaining the score"
}

Score against this rubric, so that scores mean the same thing across products:

  0-30   Single-use or disposable. Virgin plastic, non-recyclable packaging,
         harsh or petroleum-derived chemistry, sold in bulk to be thrown away.
  31-60  Mixed. Partly recyclable, or durable but made from high-impact
         materials, or a refill option exists but is not the default.
  61-85  Durable and reusable, or plant-derived and readily biodegradable,
         with modest packaging.
  86-100 Reusable or refillable AND made from recycled/renewable material,
         with minimal or plastic-free packaging.

Be conservative: when the listing does not say, assume the commonplace version
of that product rather than the best case, score toward the lower end of the
band, and say in `reason` what you could not determine.

Never invent a certification. You are estimating, not verifying — certification
is established elsewhere, from a database, and claiming one here would be a
false verification."""


def evidence_estimate(product: Product) -> dict | None:
    """Score from documented facts, or return None when there are too few.

    Returning None is the point: this pipeline declines to guess, which is
    right for a verdict and useless as the only answer.
    """
    try:
        result = evidence_eval.evaluate_product({
            "title": product.title,
            "name": product.title,
            "brand": product.brand,
            "url": product.url,
            "price": product.price,
            "bullets": product.bullets,
            "category": guess_category(
                f"{product.title} {' '.join(product.bullets)}"
            ),
        })
    except Exception as exc:
        print(f"[GreenSwap] evidence scorer failed: {exc}")
        return None

    analysis = result.get("analysis") or {}
    score = analysis.get("overall_score")
    if score is None:
        return None

    dimensions = [d for d in analysis.get("dimensions", []) if d.get("assessment")]
    detail = ", ".join(
        f"{d['dimension'].replace('_', ' ')}: {d['assessment'].replace('_', ' ')}"
        for d in dimensions[:3]
    )
    return {
        "category": analysis.get("category") or guess_category(product.title),
        "materials": [d["dimension"].replace("_", " ") for d in dimensions][:6] or ["documented"],
        "citations": [],
        "verified": False,
        "source": "evidence",
        "eco_score": int(score),
        "reason": (
            f"Scored from documented facts ({analysis.get('confidence', 'low')} "
            f"confidence, {analysis.get('coverage_percent', 0)}% evidence coverage)"
            + (f" — {detail}." if detail else ".")
        ),
        "analysis": analysis,
    }


def offline_estimate(product: Product, note: str | None = None) -> dict:
    """Honest fallback when the model cannot answer.

    The reason matters: "not configured" and "rate limited" look identical to a
    shopper but mean completely different things to whoever is running this.
    """
    text = f"{product.title} {' '.join(product.bullets)}"
    category = guess_category(text)
    rules = heuristics.analyze_text(text)
    return {
        "category": category,
        "materials": rules["materials"],
        "citations": [],
        "verified": False,
        "source": "heuristic",
        "eco_score": rules["eco_score"],
        "reason": note or (heuristics.explain(rules) if rules["confident"] else (
            "Scored cautiously from the product name alone — AI analysis "
            "is not configured, so materials could not be inferred."
        )),
    }


def build_listing(product: Product) -> str:
    listing = f"Title: {product.title}"
    if product.brand:
        listing += f"\nBrand: {product.brand}"
    if product.price:
        listing += f"\nPrice: ${product.price}"
    if product.bullets:
        listing += "\nDetails:\n" + "\n".join(f"- {b}" for b in product.bullets[:8])
    return listing


def find_alternatives(category: str, min_score: int = 0, max_price: float | None = None):
    """Expose the structured demo catalog to the model's bounded search tool."""
    rows = []
    for item in catalog_alternatives(category):
        result = evaluate_product(
            {"title": item["name"], "brand": item["brand"], "sku": item["sku"],
             "model_number": item["model_number"]}, item)
        score = result["analysis"]["overall_score"]
        if score is None or score < min_score:
            continue
        if max_price is not None and item["price"] > max_price:
            continue
        rows.append({
            "id": item["id"], "name": item["name"], "brand": item["brand"],
            "category": item["category"], "price": item["price"],
            "eco_score": score, "trust": "documented",
            "certification": item.get("certification"), "reason": item["reason"],
        })
    return sorted(rows, key=lambda row: (-row["eco_score"], row["price"]))[:3]


ALLOWED_CATEGORIES = {"cleaning", "bottles", "personal_care", "kitchen", "other"}


def parse_model_json(text: str) -> dict:
    """Parse the reply, tolerating markdown fences and surrounding prose.

    JSON mode makes this unnecessary, but not every Azure deployment supports
    JSON mode, and the fallback path below lands here.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def normalize_estimate(raw: dict, product_title: str) -> dict:
    """Never trust the shape of model output.

    eco_score especially: it is compared numerically against catalog scores to
    decide what gets recommended, so a string or an out-of-range number would
    quietly distort recommendations rather than fail loudly.
    """
    category = str(raw.get("category", "")).strip().lower()
    if category not in ALLOWED_CATEGORIES:
        category = guess_category(product_title)

    try:
        score = int(float(raw.get("eco_score", 40)))
    except (TypeError, ValueError):
        score = 40
    score = max(0, min(100, score))

    materials = raw.get("materials") or []
    if isinstance(materials, str):
        materials = [materials]
    materials = [str(m) for m in materials][:10]

    reason = str(raw.get("reason") or "").strip() or (
        "Estimated from the listing; it gave little detail about materials."
    )

    return {
        "category": category,
        "materials": materials,
        "eco_score": score,
        "reason": reason,
    }


def _llm_create(listing: str, json_mode: bool) -> dict:
    kwargs = {
        "model": MODEL_NAME,  # Azure: deployment name. Gemini: model id.
        "messages": [
            {"role": "system", "content": ESTIMATE_PROMPT},
            {"role": "user", "content": listing},
        ],
        "temperature": 0,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = llm_client.chat.completions.create(**kwargs)
    return parse_model_json(resp.choices[0].message.content)


def call_llm(listing: str) -> dict:
    """One estimate, surviving the two failures actually worth surviving.

    Older deployments reject response_format outright. Rather than making
    whoever set up the key discover that from a stack trace, retry once
    without JSON mode and lean on parse_model_json. A rate limit gets one
    backed-off retry.
    """
    try:
        return _llm_create(listing, json_mode=llm_status["json_mode"])
    except Exception as exc:
        message = str(exc).lower()
        if llm_status["json_mode"] and any(
            k in message for k in ("response_format", "json_object", "json mode")
        ):
            # Remember, so every later call skips the doomed attempt.
            llm_status["json_mode"] = False
            return _llm_create(listing, json_mode=False)
        if "429" in message or "rate limit" in message:
            time.sleep(2)
            return _llm_create(listing, json_mode=llm_status["json_mode"])
        raise


def choose_offline_scorer(product: Product, note: str | None = None) -> dict:
    """Evidence first when configured, rules when evidence cannot answer."""
    if SCORER == "auto":
        scored = evidence_estimate(product)
        if scored is not None:
            return scored
    return offline_estimate(product, note=note)


def estimate_with_ai(product: Product, deadline: float | None = None) -> dict:
    if not llm_client:
        return choose_offline_scorer(product)

    def remaining() -> float:
        return 1e9 if deadline is None else deadline - time.monotonic()

    # An agent run is several sequential calls; do not start one we cannot
    # finish inside the budget.
    if remaining() < 12:
        return choose_offline_scorer(product, note=(
            "Scored from the listing text — the AI was too slow to answer "
            "within the time a page should wait."
        ))

    llm_status["calls"] += 1
    try:
        listing = build_listing(product)
        if AGENT_ENABLED and remaining() > 12:
            try:
                raw = agent_mod.run_agent(
                    llm_client, MODEL_NAME, listing,
                    {"lookup_certified": lookup_certified,
                     "find_alternatives": find_alternatives,
                     "live_listings": [l.model_dump() for l in product.listings]},
                    parse_model_json,
                )
                result = normalize_estimate(raw, product.title)
                # Carry the evidence through: these are already verified against
                # recorded tool output by agent.verify_claims.
                result["citations"] = raw.get("citations", [])
                result["verified"] = bool(raw.get("verified"))
                result["certification"] = raw.get("certification")
                result["agent_steps"] = len(raw.get("tool_calls", []))
                result["picks"] = raw.get("picks", [])
                result["source"] = "agent"
                llm_status["agent_runs"] += 1
                llm_status["last_error"] = None
                return result
            except Exception as exc:
                # A failed research loop should cost the shopper nothing beyond
                # the citations -- fall back to the single-call estimate.
                llm_status["agent_failures"] += 1
                llm_status["last_error"] = f"agent: {type(exc).__name__}: {exc}"
                print(f"[GreenSwap] agent failed, using single call: {exc}")

        if remaining() < 3:
            return choose_offline_scorer(product, note=(
                "Scored from the listing text — the AI was too slow to answer "
                "within the time a page should wait."
            ))
        raw = call_llm(listing)
        result = normalize_estimate(raw, product.title)
        result["source"] = "model"
        llm_status["last_error"] = None
        return result
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        llm_status["failures"] += 1
        llm_status["last_error"] = f"bad response: {exc}"
        return {
            "category": guess_category(product.title),
            "materials": ["unknown"],
            "eco_score": 40,
            "reason": "Could not parse the AI response; defaulted to a cautious score.",
        }
    except Exception as exc:
        # Network/auth/quota trouble must never take the page down -- but it
        # must not vanish either, or a bad key looks exactly like a working one.
        llm_status["failures"] += 1
        llm_status["last_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[GreenSwap] model call failed: {llm_status['last_error']}")
        message = str(exc)
        if any(k in message for k in ("429", "RESOURCE_EXHAUSTED", "rate limit")):
            return choose_offline_scorer(product, note=(
                "Scored from the product name alone — the AI quota is "
                "temporarily exhausted, so materials could not be inferred."
            ))
        return offline_estimate(product)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def with_price_basis(row: dict) -> dict:
    """Attach sticker/unit pricing.

    Comparing $12.99 against $9.99 says nothing when one is 100 cups and the
    other is 25. This is what makes "cheaper" mean cheaper.
    """
    basis = pricing.price_basis(row)
    if basis.get("price_per_unit") and basis.get("unit"):
        row["unit_price"] = basis["price_per_unit"]
        row["unit_label"] = basis["unit"]
        row["unit_quantity"] = basis["quantity"]
    return row


def buy_url(row: dict, retailer: str | None = None) -> str:
    """A link the shopper can actually act on.

    We link to a retailer search for the product rather than a product page,
    because the catalog holds names rather than listings. It is honest -- the
    shopper lands on real results for that exact item -- and it is where the
    affiliate tag attaches when there is one.
    """
    if row.get("url"):
        return row["url"]  # a real listing link beats a search link

    terms = " ".join(filter(None, [row.get("brand"), row.get("name")]))
    query = urllib.parse.quote_plus(terms)
    if (retailer or "").lower() == "walmart":
        return f"https://www.walmart.com/search?q={query}"
    if (retailer or "").lower() == "target":
        return f"https://www.target.com/s?searchTerm={query}"

    url = f"https://www.amazon.com/s?k={query}"
    if AMAZON_AFFILIATE_TAG:
        url += f"&tag={urllib.parse.quote_plus(AMAZON_AFFILIATE_TAG)}"
    return url


def _program_citation(certification: str | None) -> list[dict]:
    """Turn a certification name into a link the shopper can check."""
    program = agent_mod.CERTIFICATION_PROGRAMS.get(str(certification or "").lower())
    if not program:
        return []
    return [{
        "claim": f"Certified under {program['name']}",
        "source": program["name"],
        "url": program["url"],
    }]


@app.post("/analyze")
def analyze(product: Product):
    deadline = time.monotonic() + ANALYZE_DEADLINE
    product_data = product.model_dump() if hasattr(product, "model_dump") else product.dict()
    structured = evaluate_product(product_data)
    profile = structured["profile"]
    certified = None if profile else lookup_certified(product)
    cached = False

    if profile:
        analysis = structured["analysis"]
        original = {
            "id": profile["id"], "name": profile["name"], "brand": profile["brand"],
            "price": product.price if product.price is not None else profile["price"],
            "eco_score": analysis["overall_score"], "trust": "documented",
            "certification": profile.get("certification"), "materials": [],
            "reason": profile["reason"], "analysis": analysis,
            "price_basis": price_basis(profile), "category": profile["category"],
        }
        category = profile["category"]
    elif certified:
        original = {
            "name": certified["name"],
            "brand": certified.get("brand", ""),
            "price": certified.get("price") or product.price or 0,
            "eco_score": certified["eco_score"],
            "trust": "certified",
            "certification": certified.get("certification"),
            "materials": [],
            "reason": certified.get("reason", ""),
            "analysis": structured["analysis"],
            "price_basis": price_basis(product_data),
            "category": certified["category"],
            "citations": _program_citation(certified.get("certification")),
        }
        category = certified["category"]
    else:
        key = cache_key(product, structured["evidence_fingerprint"])
        estimate = cache_get(key)
        if estimate:
            cached = True
        else:
            estimate = estimate_with_ai(product, deadline=deadline)
            cache_put(key, product, estimate, structured["evidence_fingerprint"])

        # The agent may have verified this against the certification database.
        # agent.verify_claims has already discarded any certification a tool did
        # not actually return, so trusting it here is safe.
        verified = bool(estimate.get("verified"))
        # Say which process actually produced this. Calling a rules-based score
        # an "AI estimate" would be a small lie in the one place the product
        # cannot afford one.
        estimated_by = {
            "heuristic": "heuristic",
            "evidence": "evidence",
        }.get(estimate.get("source"), "ai_estimated")
        original = {
            "name": product.title,
            "brand": product.brand or "",
            "price": product.price or 0,
            "eco_score": estimate["eco_score"],
            "trust": "certified" if verified else estimated_by,
            "certification": estimate.get("certification"),
            "materials": estimate.get("materials", []),
            "reason": estimate["reason"],
            "analysis": structured["analysis"],
            "price_basis": price_basis(product_data),
            "category": estimate["category"],
            "citations": estimate.get("citations") or [],
        }
        category = estimate["category"]

    # If the scraper could not read a price, there is nothing to compare
    # against and the same-price-or-cheaper guarantee cannot be enforced.
    # Say so explicitly rather than letting the promise lapse in silence.
    price_known = bool(original["price"])

    evaluated_candidates = []
    for item in catalog_alternatives(category):
        if profile and item["id"] == profile["id"]:
            continue
        result = evaluate_product({"title": item["name"], "brand": item["brand"],
                                   "sku": item["sku"], "model_number": item["model_number"]}, item)
        evaluated_candidates.append({
            "id": item["id"], "name": item["name"], "brand": item["brand"],
            "category": item["category"], "price": item["price"],
            "reason": item["reason"], "emoji": item["emoji"],
            "affiliate": item["affiliate"], "purchase_url": item["purchase_url"],
            "available": True,
            "certification": item.get("certification"), "analysis": result["analysis"],
            "price_basis": price_basis(item),
        })

    rank_input = {"category": category, "price": original["price"], "analysis": original["analysis"]}
    ranking = rank_candidates(rank_input, evaluated_candidates, price_ceiling=price_known)
    alternatives = ranking["candidates"][:3]
    # Ranking annotates candidate dictionaries in place. Use shallow copies for
    # the optional pricier pass so it cannot erase the disclosed boost applied
    # to the primary same-price-or-cheaper result.
    unrestricted = rank_candidates(
        rank_input, [dict(item) for item in evaluated_candidates], price_ceiling=False
    )
    pricier = ([item for item in unrestricted["candidates"]
                if price_known and item["price"] > original["price"]][:3])

    # A real retailer uses only listings found on that retailer. The fictional
    # demo catalog remains available exclusively on the local mock storefront.
    min_score = max(original["eco_score"] + ECO_SCORE_MARGIN, MIN_RECOMMEND_SCORE)
    on_real_store = bool(product.retailer) and product.retailer != "mockstore"

    if on_real_store and not product.listings and CANOPY_API_KEY:
        for query in product_search.greener_queries(product.title):
            if query in _search_cache:
                product.listings += [Listing(**row) for row in _search_cache[query]]
                continue
            try:
                found = product_search.search(query, CANOPY_API_KEY)
                _search_cache[query] = found
                product.listings += [Listing(**row) for row in found]
            except Exception as exc:
                print(f"[GreenSwap] product API failed for {query!r}: {exc}")

    scored_listings = []
    if on_real_store:
        scored_listings = [
            heuristics.score_listing(listing.model_dump())
            for listing in product.listings
            if heuristics.same_product_type(product.title, listing.name)
        ]

        proposed = [] if profile or certified else (estimate.get("picks") or [])
        live_picks = [
            pick for pick in proposed
            if pick.get("price") is not None
            and (not price_known or pick["price"] <= original["price"])
            and pick.get("eco_score", 0) >= min_score
            and heuristics.same_product_type(product.title, pick.get("name", ""))
        ]
        if not live_picks:
            live_picks = heuristics.rank_listings(
                [listing.model_dump() for listing in product.listings
                 if heuristics.same_product_type(product.title, listing.name)],
                min_score=min_score,
                max_price=original["price"] if price_known else None,
            )
        live_picks.sort(key=lambda item: (-item["eco_score"], item.get("price") or 0))
        alternatives = live_picks[:3]

        dearer = heuristics.rank_listings(
            [listing.model_dump() for listing in product.listings
             if heuristics.same_product_type(product.title, listing.name)],
            min_score=min_score,
            max_price=None,
            limit=8,
        )
        chosen = {item.get("url") for item in alternatives}
        pricier = [item for item in dearer
                   if item.get("url") not in chosen and price_known
                   and item.get("price") is not None and item["price"] > original["price"]][:3]
        ranking = {
            "policy": {"minimum_improvement": ECO_SCORE_MARGIN,
                       "minimum_recommend_score": MIN_RECOMMEND_SCORE,
                       "affiliate_points_added_to_eco_score": 0},
            "rejected": [], "affiliate_influenced": False,
            "keep_current": False,
        }

    diagnostics = {
        "listings_considered": len(scored_listings),
        "min_score": min_score,
        "viewed_score": original["eco_score"],
        "too_low_scoring": sum(item["eco_score"] < min_score for item in scored_listings),
        "too_expensive": sum(price_known and (item.get("price") or 0) > original["price"]
                             for item in scored_listings),
    }
    near_misses = sorted(
        ((item["eco_score"], item["name"], item.get("price")) for item in scored_listings),
        reverse=True,
    )
    diagnostics["closest"] = [
        {"name": n, "eco_score": sc, "price": pr} for sc, n, pr in near_misses[:2]
    ]

    def public_candidate(item, dearer=False):
        analysis = item.get("analysis")
        score = analysis.get("overall_score") if analysis else item.get("eco_score")
        result = {
            "id": item["id"], "name": item["name"], "brand": item.get("brand", ""),
            "price": item.get("price", 0), "eco_score": score,
            "trust": "documented" if analysis else item.get("trust", "ai_estimated"),
            "certification": item.get("certification"), "reason": item.get("reason", ""),
            "emoji": item.get("emoji", "🌿"), "analysis": analysis,
            "price_basis": item.get("price_basis") or price_basis(item),
            "purchase_url": item.get("purchase_url") or buy_url(item, product.retailer),
            "url": item.get("url") or buy_url(item, product.retailer),
            "affiliate": bool(item.get("affiliate")),
            "affiliate_boost": item.get("affiliate_boost", 0),
            "affiliate_influenced_order": bool(item.get("affiliate_influenced_order")),
            "ranking_explanation": item.get("ranking_explanation", ""),
        }
        enriched = with_price_basis(dict(item))
        for key in ("unit_price", "unit_label", "unit_quantity"):
            if key in enriched:
                result[key] = enriched[key]
        if dearer:
            result["extra_cost"] = round(item["price"] - original["price"], 2)
        else:
            result["savings"] = round(original["price"] - item["price"], 2) if price_known else None
        return result

    return {
        "original": original,
        "category": category,
        "cached": cached,
        "price_known": price_known,
        "identity": structured["identity"],
        "analysis": original["analysis"],
        "evidence_fingerprint": structured["evidence_fingerprint"],
        "method_version": structured["method_version"],
        "extraction": structured["extraction"],
        "analysis_steps": [
            {"label": "Identify", "detail": structured["identity"]["identity_strength"] + " product match"},
            {"label": "Extract", "detail": "documented facts separated from marketing claims"},
            {"label": "Score", "detail": f"{original['analysis']['coverage_percent']}% rubric coverage"},
            {"label": "Compare", "detail": f"{len(scored_listings) if on_real_store else len(evaluated_candidates)} products run through the same rubric"},
        ],
        "diagnostics": diagnostics,
        "ranking": {k: v for k, v in ranking.items() if k != "candidates"},
        "keep_current": ranking["keep_current"] if not on_real_store else False,
        "pricier": [public_candidate(a, True) for a in pricier],
        "alternatives": [public_candidate(a) for a in alternatives],
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "supabase": bool(supabase),
        "provider": ACTIVE_PROVIDER,
        "model": MODEL_NAME,
        "llm_ready": bool(llm_client),
        "agent_enabled": AGENT_ENABLED,
        "llm_calls": llm_status["calls"],
        "llm_failures": llm_status["failures"],
        "agent_runs": llm_status["agent_runs"],
        "last_error": llm_status["last_error"],
        "cached_estimates": len(_memory_cache) if not supabase else None,
    }


@app.get("/selftest")
def selftest():
    """One real model call, bypassing the cache, reporting the actual error.

    This exists because every failure path in /analyze degrades gracefully --
    which is right for shoppers and useless for setup. Hit this after dropping
    in a key to find out whether it actually works.
    """
    if not llm_client:
        return {
            "ok": False,
            "reason": "No model provider configured",
            "set_one_of": {
                "gemini": ["GEMINI_API_KEY"],
                "azure": ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY"],
            },
            "hint": "Put a key in backend/.env, then RESTART the server "
                    "(.env is read once at startup).",
        }

    sample = Product(
        title="Disposable Plastic Water Bottles, 24 Pack",
        brand="HydroBasic",
        price=12.99,
        bullets=["Lightweight PET plastic construction", "Single-use"],
    )
    started = time.perf_counter()
    try:
        raw = call_llm(build_listing(sample))
        return {
            "ok": True,
            "provider": ACTIVE_PROVIDER,
            "model": MODEL_NAME,
            "json_mode": llm_status["json_mode"],
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "raw": raw,
            "normalized": normalize_estimate(raw, sample.title),
        }
    except Exception as exc:
        message = str(exc)
        low = message.lower()
        gemini = ACTIVE_PROVIDER == "gemini"
        hint = "Unexpected error - check the key and model name."
        if "401" in message or "access denied" in low or "unauthorized" in low:
            hint = ("Key rejected. Check GEMINI_API_KEY was copied whole from "
                    "Google AI Studio." if gemini else
                    "Key rejected. Check AZURE_OPENAI_API_KEY matches this resource.")
        elif "400" in message and "api key" in low:
            hint = "Key malformed. Re-copy it; Google AI Studio keys start with 'AIza'."
        elif "404" in message or "not found" in low:
            # Google names the replacement model in its own error when one is
            # retired; quoting it beats guessing a name that may also be stale.
            suggested = re.search(r"use models/([\w.-]+)", message)
            hint = ((f"Model '{MODEL_NAME}' is unavailable. Set "
                     f"GEMINI_MODEL={suggested.group(1)} in backend/.env and restart."
                     if suggested else
                     f"Model '{MODEL_NAME}' not found. Check GEMINI_MODEL against "
                     f"https://aistudio.google.com/.")
                    if gemini else
                    "Deployment not found. AZURE_OPENAI_DEPLOYMENT must be the "
                    "deployment NAME you chose in Azure AI Foundry, not the model name.")
        elif "429" in message:
            hint = ("Rate limited. Gemini's free tier has per-minute limits; "
                    "wait a moment and retry." if gemini else
                    "Rate limited or out of quota for this deployment.")
        elif "getaddrinfo" in low or "connect" in low:
            hint = "Endpoint unreachable - check your network."
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {message}",
            "hint": hint,
            "provider": ACTIVE_PROVIDER,
            "model": MODEL_NAME,
        }
