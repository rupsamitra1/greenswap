"""
GreenSwap backend (FastAPI).

Pipeline for /analyze:
1. Look the product up in the certified-products table (Supabase).
   -> If found, trust = "certified" (ground truth from EPA Safer Choice / ENERGY STAR data).
2. If not found, call the OpenAI API to ESTIMATE materials + eco score
   from the product name/description. trust = "ai_estimated".
3. Query Supabase for greener alternatives in the same category,
   sorted by eco score, filtered near the original price.

Run:
    pip install fastapi uvicorn openai supabase python-dotenv
    uvicorn main:app --reload
"""

import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="GreenSwap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Config — set these as environment variables (never hardcode keys!)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    from supabase import create_client

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

openai_client = None
if OPENAI_API_KEY:
    from openai import OpenAI

    openai_client = OpenAI(api_key=OPENAI_API_KEY)


class AnalyzeRequest(BaseModel):
    query: str  # product name, description, or URL


# ---------------------------------------------------------------------------
# Step 1: certified lookup (ground truth)
# ---------------------------------------------------------------------------
def lookup_certified(query: str):
    """Check if the product matches a row in our certified_products table."""
    if not supabase:
        return None
    res = (
        supabase.table("certified_products")
        .select("*")
        .ilike("name", f"%{query}%")
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------------------------------------------------------------------------
# Step 2: AI estimation for unlisted products
# ---------------------------------------------------------------------------
ESTIMATE_PROMPT = """You are a sustainability analyst. Given a product name or
description, estimate its likely materials and environmental impact.

Respond ONLY with JSON, no markdown fences, in this exact shape:
{
  "category": "one of: cleaning, bottles, personal_care, kitchen, other",
  "materials": ["list", "of", "likely", "materials"],
  "eco_score": 0-100 integer (100 = most sustainable),
  "reason": "one plain-English sentence explaining the score"
}

Be conservative: if uncertain, score lower and say why."""


def estimate_with_ai(query: str):
    if not openai_client:
        # Offline fallback so the demo works with no API key
        return {
            "category": "other",
            "materials": ["unknown"],
            "eco_score": 40,
            "reason": "AI estimation unavailable (no API key configured).",
        }
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": ESTIMATE_PROMPT},
            {"role": "user", "content": query},
        ],
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "category": "other",
            "materials": ["unknown"],
            "eco_score": 40,
            "reason": "Could not parse AI response; defaulted to cautious score.",
        }


# ---------------------------------------------------------------------------
# Step 3: find greener alternatives
# ---------------------------------------------------------------------------
def find_alternatives(category: str, min_score: int, max_price: float | None):
    if not supabase:
        return []
    q = (
        supabase.table("alternatives")
        .select("*")
        .eq("category", category)
        .gte("eco_score", min_score)
        .order("eco_score", desc=True)
        .limit(3)
    )
    if max_price:
        q = q.lte("price", max_price * 1.6)  # allow slightly pricier options
    res = q.execute()
    return res.data or []


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    certified = lookup_certified(req.query)

    if certified:
        original = {
            "id": certified["id"],
            "name": certified["name"],
            "brand": certified.get("brand", ""),
            "price": certified.get("price", 0),
            "eco_score": certified["eco_score"],
            "trust": "certified",
            "certification": certified.get("certification"),
            "reason": certified.get("reason", ""),
            "emoji": certified.get("emoji", "📦"),
        }
        category = certified["category"]
    else:
        est = estimate_with_ai(req.query)
        original = {
            "id": "estimated",
            "name": req.query,
            "brand": "",
            "price": 0,
            "eco_score": est["eco_score"],
            "trust": "ai_estimated",
            "certification": None,
            "reason": est["reason"],
            "emoji": "📦",
        }
        category = est["category"]

    alts = find_alternatives(
        category=category,
        min_score=max(original["eco_score"] + 15, 70),
        max_price=original["price"] or None,
    )

    return {
        "original": original,
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
            }
            for a in alts
        ],
    }


@app.get("/health")
def health():
    return {"ok": True, "supabase": bool(supabase), "openai": bool(openai_client)}
