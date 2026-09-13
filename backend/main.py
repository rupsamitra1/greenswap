"""
GreenSwap backend (FastAPI).

Pipeline for /analyze:
1. Look the product up in certified_products (Supabase).
   -> If found, trust = "certified" (ground truth from EPA Safer Choice / ENERGY STAR).
2. If not found, check the ai_estimates cache before spending a single token.
3. On a cache miss, ask the model (Gemini or Azure OpenAI) to estimate,
   then write the result back to the cache. trust = "ai_estimated".
4. Return greener alternatives in the same category that cost NO MORE than
   the original -- the "same price or cheaper" promise is a hard filter.

Everything degrades gracefully: with no Supabase and no model credentials the
service still answers from a built-in catalog and a keyword heuristic, so the
demo never depends on the network.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload
"""

import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import types
from collections import deque
from pathlib import Path

import agent as agent_mod
import heuristics
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

# Gemini's free tier allows 5 requests per minute per model, and one agent run
# spends 3-4 of them. Left alone, browsing two products in a minute exhausts
# the quota and every later request 429s. Waiting is far better than failing.
LLM_RPM = int(_clean(os.getenv("LLM_RPM")) or 5)

# ...but a shopper is waiting on the other end of this. Queueing behind the
# quota is only worth doing briefly; past this we answer with the heuristic
# rather than leave a product page hanging.
LLM_MAX_WAIT = float(_clean(os.getenv("LLM_MAX_WAIT")) or 8)

# Surfaced by /health and /selftest so a misconfigured key is visible rather
# than silently degrading into the offline fallback.
AGENT_ENABLED = (_clean(os.getenv("GREENSWAP_AGENT")) or "on").lower() != "off"

llm_status: dict = {"calls": 0, "failures": 0, "last_error": None, "json_mode": True,
                       "agent_runs": 0, "agent_failures": 0}

# Affiliate tag, appended to outbound links when set. This is the hook for the
# primary revenue stream in the business model; without it the links still work,
# they just earn nothing.
AMAZON_AFFILIATE_TAG = _clean(os.getenv("AMAZON_AFFILIATE_TAG"))

# An alternative must beat the original by this much to be worth suggesting.
ECO_SCORE_MARGIN = 10

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
    # Candidate alternatives the extension already fetched from the store.
    listings: list[Listing] = []


# ---------------------------------------------------------------------------
# Built-in catalog -- mirrors supabase/schema.sql so the demo runs with no DB.
# ---------------------------------------------------------------------------
FALLBACK_ALTERNATIVES = [
    {
        "id": "alt-leafclean",
        "name": "Plant-Based Dish Soap, 40oz",
        "brand": "LeafClean",
        "category": "cleaning",
        "price": 3.99,
        "eco_score": 93,
        "trust": "certified",
        "certification": "EPA Safer Choice",
        "reason": "Every ingredient appears on the EPA Safer Chemical Ingredients List.",
        "emoji": "🌿",
    },
    {
        "id": "alt-barblock",
        "name": "Solid Dish Soap Block, Plastic-Free",
        "brand": "Sudsy Bar",
        "category": "cleaning",
        "price": 3.25,
        "eco_score": 90,
        "trust": "ai_estimated",
        "certification": None,
        "reason": "Solid format ships without a plastic bottle or added water.",
        "emoji": "🧼",
    },
    {
        "id": "alt-refill",
        "name": "Refillable Dish Soap Starter Kit",
        "brand": "ReFill Co.",
        "category": "cleaning",
        "price": 5.25,
        "eco_score": 88,
        "trust": "ai_estimated",
        "certification": None,
        "reason": "Refill pouches cut plastic packaging by roughly 80%.",
        "emoji": "♻️",
    },
    {
        "id": "alt-eversip",
        "name": "Stainless Steel Bottle, 24oz",
        "brand": "EverSip",
        "category": "bottles",
        "price": 9.99,
        "eco_score": 91,
        "trust": "certified",
        "certification": "Climate Pledge Friendly",
        "reason": "Reusable; replaces roughly 150 single-use bottles per year.",
        "emoji": "🥤",
    },
    {
        "id": "alt-pureflow",
        "name": "Glass Bottle with Protective Sleeve",
        "brand": "PureFlow",
        "category": "bottles",
        "price": 7.49,
        "eco_score": 84,
        "trust": "ai_estimated",
        "certification": None,
        "reason": "Reusable borosilicate glass, fully recyclable at end of life.",
        "emoji": "🫙",
    },
]

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
def lookup_certified(title: str):
    """Check whether the product matches a known certified product.

    Falls back to the built-in catalog when Supabase is not configured --
    otherwise the viewed product could never be verified without a database,
    and the verified badge would be unreachable in the offline demo.
    """
    title = (title or "").strip()
    if not title:
        return None

    if supabase:
        res = (
            supabase.table("certified_products")
            .select("*")
            .ilike("name", f"%{title}%")
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return None

    needle = title.lower()
    for row in FALLBACK_ALTERNATIVES:
        if row.get("trust") != "certified":
            continue
        name = row["name"].lower()
        if needle in name or name in needle:
            return row
    return None


# ---------------------------------------------------------------------------
# Step 2: the cache -- this is what keeps per-page LLM cost off the floor
# ---------------------------------------------------------------------------
def cache_key(product: Product) -> str:
    """Normalize so trivial title differences still hit the same cache row."""
    raw = f"{(product.brand or '').strip()} {product.title.strip()}".lower()
    raw = re.sub(r"[^a-z0-9 ]+", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cache_get(key: str):
    if supabase:
        res = (
            supabase.table("ai_estimates")
            .select("*")
            .eq("query_hash", key)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    return _memory_cache.get(key)


def cache_put(key: str, product: Product, estimate: dict):
    row = {
        "query_hash": key,
        "query": product.title[:500],
        "category": estimate["category"],
        "materials": estimate["materials"],
        "eco_score": estimate["eco_score"],
        "reason": estimate["reason"],
        # Without these a cache hit would quietly drop the evidence and
        # downgrade a verified product to an estimate.
        "citations": estimate.get("citations") or [],
        "verified": bool(estimate.get("verified")),
        "certification": estimate.get("certification"),
    }
    if supabase:
        # upsert so concurrent shoppers viewing the same product cannot collide
        supabase.table("ai_estimates").upsert(row, on_conflict="query_hash").execute()
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
        "reason": note or heuristics.explain(rules) if rules["confident"] else note or (
            "Scored cautiously from the product name alone — AI analysis "
            "is not configured, so materials could not be inferred."
        ),
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


def estimate_with_ai(product: Product) -> dict:
    if not llm_client:
        return offline_estimate(product)

    llm_status["calls"] += 1
    try:
        listing = build_listing(product)
        if AGENT_ENABLED:
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
            return offline_estimate(product, note=(
                "Scored from the product name alone — the AI quota is "
                "temporarily exhausted, so materials could not be inferred."
            ))
        return offline_estimate(product)


# ---------------------------------------------------------------------------
# Step 4: greener alternatives, at or below the original price
# ---------------------------------------------------------------------------
def find_alternatives(category: str, min_score: int, max_price: float | None):
    """Hard price ceiling: GreenSwap only ever suggests same-price-or-cheaper."""
    if supabase:
        q = (
            supabase.table("alternatives")
            .select("*")
            .eq("category", category)
            .gte("eco_score", min_score)
        )
        if max_price:
            q = q.lte("price", max_price)
        res = q.execute()
        rows = res.data or []
    else:
        rows = [
            a
            for a in FALLBACK_ALTERNATIVES
            if a["category"] == category
            and a["eco_score"] >= min_score
            and (max_price is None or a["price"] <= max_price)
        ]

    # Greenest first; when two are equally green, the cheaper one wins.
    rows.sort(key=lambda a: (-a["eco_score"], a.get("price") or 0))
    return rows[:3]


def find_pricier(category: str, min_score: int, above_price: float):
    """Greener options that cost MORE than the original.

    Only ever used as an opt-in fallback when nothing qualifies at or below
    the original price. Sorted by price ascending rather than eco score: once
    we are asking the shopper to spend more, the amount extra is the thing
    they are actually deciding on.
    """
    if supabase:
        res = (
            supabase.table("alternatives")
            .select("*")
            .eq("category", category)
            .gte("eco_score", min_score)
            .gt("price", above_price)
            .execute()
        )
        rows = res.data or []
    else:
        rows = [
            a
            for a in FALLBACK_ALTERNATIVES
            if a["category"] == category
            and a["eco_score"] >= min_score
            and (a["price"] or 0) > above_price
        ]

    rows.sort(key=lambda a: (a.get("price") or 0, -a["eco_score"]))
    return rows[:3]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
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
    certified = lookup_certified(product.title)
    cached = False

    if certified:
        original = {
            "name": certified["name"],
            "brand": certified.get("brand", ""),
            "price": certified.get("price") or product.price or 0,
            "eco_score": certified["eco_score"],
            "trust": "certified",
            "certification": certified.get("certification"),
            "materials": [],
            "reason": certified.get("reason", ""),
            "citations": _program_citation(certified.get("certification")),
        }
        category = certified["category"]
    else:
        key = cache_key(product)
        estimate = cache_get(key)
        if estimate:
            cached = True
        else:
            estimate = estimate_with_ai(product)
            cache_put(key, product, estimate)

        # The agent may have verified this against the certification database.
        # agent.verify_claims has already discarded any certification a tool did
        # not actually return, so trusting it here is safe.
        verified = bool(estimate.get("verified"))
        # Say which process actually produced this. Calling a rules-based score
        # an "AI estimate" would be a small lie in the one place the product
        # cannot afford one.
        estimated_by = (
            "heuristic" if estimate.get("source") == "heuristic" else "ai_estimated"
        )
        original = {
            "name": product.title,
            "brand": product.brand or "",
            "price": product.price or 0,
            "eco_score": estimate["eco_score"],
            "trust": "certified" if verified else estimated_by,
            "certification": estimate.get("certification"),
            "materials": estimate.get("materials", []),
            "reason": estimate["reason"],
            "citations": estimate.get("citations") or [],
        }
        category = estimate["category"]

    # If the scraper could not read a price, there is nothing to compare
    # against and the same-price-or-cheaper guarantee cannot be enforced.
    # Say so explicitly rather than letting the promise lapse in silence.
    price_known = bool(original["price"])

    alternatives = find_alternatives(
        category=category,
        min_score=original["eco_score"] + ECO_SCORE_MARGIN,
        max_price=original["price"] if price_known else None,
    )

    # Live picks from the store, chosen by the agent from listings the browser
    # actually saw. The price ceiling and the score margin are applied HERE,
    # in code: the model proposes, but it cannot talk its way past the promise
    # the product is built on.
    pricier: list[dict] = []
    live_picks = []
    for pick in (estimate.get("picks") if not certified else None) or []:
        price = pick.get("price")
        if price is None:
            continue
        if price_known and price > original["price"]:
            continue
        if pick["eco_score"] < original["eco_score"] + ECO_SCORE_MARGIN:
            continue
        live_picks.append(pick)

    # Whenever the agent did not choose for us -- it is switched off, the model
    # answered in one call, or the quota ran out -- rank the scraped listings
    # with the rules engine instead. Otherwise a real store would show nothing
    # at all, since the catalog is rightly excluded there.
    if not live_picks and product.listings:
        live_picks = heuristics.rank_listings(
            [l.model_dump() for l in product.listings],
            min_score=original["eco_score"] + ECO_SCORE_MARGIN,
            max_price=original["price"] if price_known else None,
        )

    on_real_store = bool(product.retailer) and product.retailer != "mockstore"

    if on_real_store and not product.listings:
        # The retailer search came back empty -- its markup may have changed.
        # Falling back to the seeded catalog here is what put invented dish
        # soap on an Amazon page: those products cannot be bought, and a wrong
        # answer is worse than none.
        alternatives = []
        print(f"[GreenSwap] no live listings for {product.retailer}; "
              "returning no alternatives rather than catalog demo data")

    if product.listings:
        # We searched the real store, so answer from it alone. The seeded
        # catalog is demo data: those products do not exist on Amazon, and
        # padding a real result set with invented ones is worse than returning
        # fewer answers. Only the mock store, which has no live search, still
        # falls back to the catalog.
        live_picks.sort(key=lambda a: (-a["eco_score"], a.get("price") or 0))
        alternatives = live_picks[:3]

        # Dearer options come from the same real listings.
        dearer = heuristics.rank_listings(
            [l.model_dump() for l in product.listings],
            min_score=original["eco_score"] + ECO_SCORE_MARGIN,
            max_price=None,
            limit=8,
        )
        chosen = {a.get("url") for a in alternatives}
        pricier = [
            dict(d, extra_cost=round(d["price"] - original["price"], 2))
            for d in dearer
            if d.get("url") not in chosen
            and price_known
            and d["price"] > original["price"]
        ][:3]
    elif live_picks:
        live_picks.sort(key=lambda a: (-a["eco_score"], a.get("price") or 0))
        seen = {p["name"].lower() for p in live_picks}
        alternatives = (
            live_picks + [a for a in alternatives if a["name"].lower() not in seen]
        )[:3]

    # Greener options above the price are always computed, but the card keeps
    # them behind an explicit opt-in whether or not cheaper ones exist. The
    # unprompted answer stays "same price or cheaper"; the shopper decides
    # whether to look further.
    #
    # On a real store this was already filled from real listings above; the
    # catalog is only consulted when there was no live search to draw on.
    if not product.listings:
        pricier = (
            find_pricier(
                category=category,
                min_score=original["eco_score"] + ECO_SCORE_MARGIN,
                above_price=original["price"],
            )
            if price_known
            else []
        )

    return {
        "original": original,
        "category": category,
        "cached": cached,
        "price_known": price_known,
        "pricier": [
            {
                "id": a["id"],
                "name": a["name"],
                "brand": a.get("brand", ""),
                "price": a.get("price", 0),
                "eco_score": a["eco_score"],
                "trust": a.get("trust", "ai_estimated"),
                "certification": a.get("certification"),
                "reason": a.get("reason", ""),
                "url": buy_url(a, product.retailer),
                "extra_cost": round((a.get("price") or 0) - original["price"], 2),
            }
            for a in pricier
        ],
        "alternatives": [
            {
                "id": a["id"],
                "name": a["name"],
                "brand": a.get("brand", ""),
                "price": a.get("price", 0),
                "eco_score": a["eco_score"],
                "trust": a.get("trust", "ai_estimated"),
                "certification": a.get("certification"),
                "reason": a.get("reason", ""),
                "emoji": a.get("emoji", "🌿"),
                "url": buy_url(a, product.retailer),
                "savings": (
                    round(original["price"] - (a.get("price") or 0), 2)
                    if price_known
                    else None
                ),
            }
            for a in alternatives
        ],
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
