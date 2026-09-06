"""
GreenSwap backend (FastAPI).

Pipeline for /analyze:
1. Identify the exact product and separate documented facts from marketing.
2. Score category dimensions from referenced evidence; unknowns stay unknown.
3. Run every alternative through the exact same scoring method.
4. Apply eligibility, price, and disclosed affiliate ranking after eco scoring.

Everything degrades gracefully: with no Supabase and no Azure credentials the
service still answers from a built-in catalog and a keyword heuristic, so the
demo never depends on the network.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload
"""

import json
import os
import re
import time
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
except ModuleNotFoundError:
    from identification import identify_product
    from demo_catalog import alternatives as catalog_alternatives
    from evaluation import evaluate_product
    from pricing import price_basis
    from ranking import rank_candidates
    from scoring import METHOD_VERSION

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
        print(f"[GreenSwap] Created {env} from .env.example - add your Azure key there.")


_ensure_env_file()
load_dotenv()

app = FastAPI(title="GreenSwap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

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
REQUEST_TIMEOUT = float(_clean(os.getenv("AZURE_OPENAI_TIMEOUT")) or 20)

# Surfaced by /health and /selftest so a misconfigured key is visible rather
# than silently degrading into the offline fallback.
azure_status: dict = {"calls": 0, "failures": 0, "last_error": None, "json_mode": True}

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    from supabase import create_client

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

azure_client = None
if AZURE_ENDPOINT and AZURE_API_KEY:
    from openai import AzureOpenAI

    azure_client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
        api_version=AZURE_API_VERSION,
        timeout=REQUEST_TIMEOUT,
        max_retries=2,
    )

# Used only when Supabase is not configured, so the cache still works locally.
_memory_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
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
def lookup_certified(product: Product):
    """Check exact identifiers before falling back to the legacy title match."""
    if not supabase:
        return None
    data = product.model_dump() if hasattr(product, "model_dump") else product.dict()
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
           .ilike("name", f"%{product.title}%").limit(1).execute())
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
        "model_version": AZURE_DEPLOYMENT if azure_client else "offline-heuristic",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "evidence_fingerprint": evidence_fingerprint,
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


def offline_estimate(product: Product) -> dict:
    """Honest fallback when no LLM is configured."""
    category = guess_category(f"{product.title} {' '.join(product.bullets)}")
    return {
        "category": category,
        "materials": ["unknown"],
        "eco_score": 40,
        "reason": (
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


def _azure_create(listing: str, json_mode: bool) -> dict:
    kwargs = {
        "model": AZURE_DEPLOYMENT,  # on Azure this is the DEPLOYMENT name
        "messages": [
            {"role": "system", "content": ESTIMATE_PROMPT},
            {"role": "user", "content": listing},
        ],
        "temperature": 0,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = azure_client.chat.completions.create(**kwargs)
    return parse_model_json(resp.choices[0].message.content)


def call_azure(listing: str) -> dict:
    """One estimate, surviving the two failures actually worth surviving.

    Older deployments reject response_format outright. Rather than making
    whoever set up the key discover that from a stack trace, retry once
    without JSON mode and lean on parse_model_json. A rate limit gets one
    backed-off retry.
    """
    try:
        return _azure_create(listing, json_mode=azure_status["json_mode"])
    except Exception as exc:
        message = str(exc).lower()
        if azure_status["json_mode"] and any(
            k in message for k in ("response_format", "json_object", "json mode")
        ):
            # Remember, so every later call skips the doomed attempt.
            azure_status["json_mode"] = False
            return _azure_create(listing, json_mode=False)
        if "429" in message or "rate limit" in message:
            time.sleep(2)
            return _azure_create(listing, json_mode=azure_status["json_mode"])
        raise


def estimate_with_ai(product: Product) -> dict:
    if not azure_client:
        return offline_estimate(product)

    azure_status["calls"] += 1
    try:
        raw = call_azure(build_listing(product))
        result = normalize_estimate(raw, product.title)
        azure_status["last_error"] = None
        return result
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        azure_status["failures"] += 1
        azure_status["last_error"] = f"bad response: {exc}"
        return {
            "category": guess_category(product.title),
            "materials": ["unknown"],
            "eco_score": 40,
            "reason": "Could not parse the AI response; defaulted to a cautious score.",
        }
    except Exception as exc:
        # Network/auth/quota trouble must never take the page down -- but it
        # must not vanish either, or a bad key looks exactly like a working one.
        azure_status["failures"] += 1
        azure_status["last_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[GreenSwap] Azure call failed: {azure_status['last_error']}")
        return offline_estimate(product)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.post("/analyze")
def analyze(product: Product):
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
        }
        category = certified["category"]
    else:
        key = cache_key(product, structured["evidence_fingerprint"])
        estimate = cache_get(key)
        if estimate:
            cached = True
        else:
            estimate = estimate_with_ai(product)
            cache_put(key, product, estimate, structured["evidence_fingerprint"])

        original = {
            "name": product.title,
            "brand": product.brand or "",
            "price": product.price or 0,
            "eco_score": estimate["eco_score"],
            "trust": "ai_estimated",
            "certification": None,
            "materials": estimate.get("materials", []),
            "reason": estimate["reason"],
            "analysis": structured["analysis"],
            "price_basis": price_basis(product_data),
            "category": estimate["category"],
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
    pricier = []
    if price_known and not alternatives:
        unrestricted = rank_candidates(rank_input, evaluated_candidates, price_ceiling=False)
        pricier = [item for item in unrestricted["candidates"] if item["price"] > original["price"]][:3]

    def public_candidate(a, dearer=False):
        score = a["analysis"]["overall_score"]
        result = {
            "id": a["id"], "name": a["name"], "brand": a.get("brand", ""),
            "price": a.get("price", 0), "eco_score": score, "trust": "documented",
            "certification": a.get("certification"), "reason": a.get("reason", ""),
            "emoji": a.get("emoji", "🌿"), "analysis": a["analysis"],
            "price_basis": a["price_basis"], "purchase_url": a.get("purchase_url"),
            "affiliate": bool(a.get("affiliate")), "affiliate_boost": a.get("affiliate_boost", 0),
            "affiliate_influenced_order": bool(a.get("affiliate_influenced_order")),
            "ranking_explanation": a.get("ranking_explanation", ""),
        }
        if dearer:
            result["extra_cost"] = round(a["price"] - original["price"], 2)
        else:
            result["savings"] = round(original["price"] - a["price"], 2) if price_known else None
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
            {"label": "Compare", "detail": f"{len(evaluated_candidates)} products run through the same rubric"},
        ],
        "ranking": {k: v for k, v in ranking.items() if k != "candidates"},
        "keep_current": ranking["keep_current"],
        "pricier": [public_candidate(a, True) for a in pricier],
        "alternatives": [public_candidate(a) for a in alternatives],
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "supabase": bool(supabase),
        "azure_openai": bool(azure_client),
        "azure_deployment": AZURE_DEPLOYMENT if azure_client else None,
        "azure_calls": azure_status["calls"],
        "azure_failures": azure_status["failures"],
        "azure_last_error": azure_status["last_error"],
        "cached_estimates": len(_memory_cache) if not supabase else None,
    }


@app.get("/selftest")
def selftest():
    """One real model call, bypassing the cache, reporting the actual error.

    This exists because every failure path in /analyze degrades gracefully --
    which is right for shoppers and useless for setup. Hit this after dropping
    in a key to find out whether it actually works.
    """
    if not azure_client:
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT),
                ("AZURE_OPENAI_API_KEY", AZURE_API_KEY),
            )
            if not value
        ]
        return {
            "ok": False,
            "reason": "Azure client not configured",
            "missing_env": missing,
            "hint": "Create backend/.env from .env.example, then restart the server.",
        }

    sample = Product(
        title="Disposable Plastic Water Bottles, 24 Pack",
        brand="HydroBasic",
        price=12.99,
        bullets=["Lightweight PET plastic construction", "Single-use"],
    )
    started = time.perf_counter()
    try:
        raw = call_azure(build_listing(sample))
        return {
            "ok": True,
            "deployment": AZURE_DEPLOYMENT,
            "api_version": AZURE_API_VERSION,
            "json_mode": azure_status["json_mode"],
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "raw": raw,
            "normalized": normalize_estimate(raw, sample.title),
        }
    except Exception as exc:
        message = str(exc)
        hint = "Unexpected error — check the endpoint and deployment name."
        low = message.lower()
        if "401" in message or "access denied" in low or "unauthorized" in low:
            hint = "Key rejected. Check AZURE_OPENAI_API_KEY matches this resource."
        elif "404" in message or "not found" in low:
            hint = (
                "Deployment not found. AZURE_OPENAI_DEPLOYMENT must be the "
                "deployment name you chose in Azure AI Foundry, not the model name."
            )
        elif "429" in message:
            hint = "Rate limited or out of quota for this deployment."
        elif "getaddrinfo" in low or "connect" in low:
            hint = "Endpoint unreachable. Check AZURE_OPENAI_ENDPOINT."
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {message}",
            "hint": hint,
            "deployment": AZURE_DEPLOYMENT,
            "endpoint_set": bool(AZURE_ENDPOINT),
        }
