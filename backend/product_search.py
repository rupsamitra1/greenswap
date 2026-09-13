"""Retailer product search via a data API.

Scraping a retailer's search page from an extension is fragile: the markup
changes, and a programmatic request is exactly the profile bot detection
challenges. A product data API returns structured results with none of that.

Canopy is the provider here because it has a genuinely permanent free tier
(100 requests/month, no card). The interface below is deliberately narrow --
query in, listings out -- so swapping providers means rewriting one function.

The browser scrape stays as the first attempt: it costs nothing and, when it
works, reflects exactly what the shopper would see. This is the fallback, and
its quota is small enough that results are cached hard.
"""

import json
import os
import re
import urllib.error
import urllib.request

CANOPY_ENDPOINT = "https://graphql.canopyapi.co/"

SEARCH_QUERY = """
query GreenSwapSearch($term: String!, $limit: Int!) {
  amazonProductSearchResults(input: { searchTerm: $term }) {
    productResults(input: { page: 1, limit: $limit }) {
      results {
        asin
        title
        sponsored
        price { display }
      }
    }
  }
}
"""


def _parse_price(display):
    """Canopy returns a display string like "$12.99"; we need a number."""
    if not display:
        return None
    found = re.search(r"\d+(?:[.,]\d+)?", str(display).replace(",", ""))
    return float(found.group(0)) if found else None


def search(query: str, api_key: str, limit: int = 12, timeout: float = 15.0) -> list[dict]:
    """Return listings for a keyword search, or raise on failure.

    Sponsored results are dropped: they are ads, and recommending one as a
    greener choice would make this the thing it claims to replace.
    """
    body = json.dumps({
        "query": SEARCH_QUERY,
        "variables": {"term": query, "limit": limit},
    }).encode()

    request = urllib.request.Request(
        CANOPY_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json", "API-KEY": api_key},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())

    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "search failed"))

    results = (
        payload.get("data", {})
        .get("amazonProductSearchResults", {})
        .get("productResults", {})
        .get("results")
    ) or []

    listings = []
    for row in results:
        asin, title = row.get("asin"), row.get("title")
        if not asin or not title or row.get("sponsored"):
            continue
        price = _parse_price((row.get("price") or {}).get("display"))
        if price is None:
            continue  # unpriced results cannot be compared
        listings.append({
            "name": title,
            "price": price,
            "url": f"https://www.amazon.com/dp/{asin}",
            "source": "canopy",
        })
    return listings


STOPWORDS = {
    "pack", "count", "with", "size", "large", "small", "value", "ultra",
    "original", "scent", "liquid", "bottles", "bottle", "each", "free", "the",
    "for", "and",
}


def greener_queries(title: str) -> list[str]:
    """Search terms aimed at the greener end of the same shelf.

    Plain descriptive words on purpose: "eco" in a listing title means nothing,
    while "refillable" and "reusable" describe the actual object.
    """
    words = [
        w for w in re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower()).split()
        if len(w) > 3 and w not in STOPWORDS
    ][:4]
    if not words:
        return []
    base = " ".join(words)
    return [f"reusable {base}", f"refillable plastic free {base}"]
