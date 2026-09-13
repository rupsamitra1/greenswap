/**
 * Per-retailer page scrapers.
 *
 * Each scraper returns a plain product object or null if the current page is
 * not a product page. Selectors on real retailers change without warning, so
 * every field except the title is treated as optional and each scraper tries
 * several selectors before giving up.
 */

(function () {
  "use strict";

  function text(root, selectors) {
    for (const selector of selectors) {
      const el = root.querySelector(selector);
      if (el && el.textContent.trim()) return el.textContent.trim();
    }
    return null;
  }

  function parsePrice(raw) {
    if (!raw) return null;
    const match = raw.replace(/,/g, "").match(/\d+(\.\d+)?/);
    return match ? parseFloat(match[0]) : null;
  }

  // --- Mock storefront (served at http://localhost:8000/store) --------------
  // Markup here is ours, so the selectors are stable by construction.
  function scrapeMockStore() {
    const root = document.querySelector("[data-product]");
    if (!root) return null;
    const price = parseFloat(root.dataset.price);
    return {
      title: root.dataset.title,
      // null, not NaN -- NaN only survives the trip as null by accident of
      // JSON serialization, and the backend keys real behaviour off this.
      price: Number.isFinite(price) ? price : null,
      brand: root.dataset.brand || null,
      bullets: Array.from(root.querySelectorAll("[data-bullet]")).map((el) =>
        el.textContent.trim()
      ),
      image_url: root.querySelector("img")?.src || null,
      url: location.href,
      retailer: "mockstore",
    };
  }

  // --- Amazon ---------------------------------------------------------------
  function scrapeAmazon() {
    const title = text(document, ["#productTitle", "#title span"]);
    if (!title) return null; // not a product detail page

    const priceRaw =
      text(document, [
        "#corePrice_feature_div .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
      ]) || "";

    let brand = text(document, ["#bylineInfo", "#brand"]);
    if (brand) brand = brand.replace(/^(Visit the|Brand:)\s*/i, "").replace(/\s*Store$/i, "");

    const bullets = Array.from(
      document.querySelectorAll("#feature-bullets li span.a-list-item")
    )
      .map((el) => el.textContent.trim())
      .filter(Boolean)
      .slice(0, 8);

    return {
      title,
      price: parsePrice(priceRaw),
      brand,
      bullets,
      image_url: document.querySelector("#landingImage")?.src || null,
      url: location.href,
      retailer: "amazon",
    };
  }

  /**
   * Search the retailer for candidate alternatives.
   *
   * This runs in the content script, which means the request goes out from
   * the retailer's own origin using the shopper's session -- it loads the way
   * any normal search would. A server doing this from a datacenter IP gets
   * blocked quickly, and would see logged-out prices even when it worked.
   *
   * Returns real listings with real product URLs, so a recommendation can
   * link straight to the item instead of to a search page.
   */
  async function searchAmazon(query, limit = 8) {
    const url = `https://www.amazon.com/s?k=${encodeURIComponent(query)}`;
    let doc;
    try {
      const res = await new Promise((resolve) => {
        if (!chrome.runtime?.id) return resolve({ ok: false, error: "no context" });
        chrome.runtime.sendMessage({ type: "GREENSWAP_SEARCH", url }, (r) =>
          resolve(chrome.runtime.lastError ? { ok: false } : r)
        );
      });
      if (!res?.ok) return [];
      doc = new DOMParser().parseFromString(res.html, "text/html");
    } catch (err) {
      return []; // never let a failed search break the card
    }

    const results = [];
    // Amazon lists the same item twice when it is also a sponsored slot;
    // without this the duplicates eat the candidate budget.
    const seenAsins = new Set();
    const cards = doc.querySelectorAll('[data-component-type="s-search-result"]');
    for (const card of cards) {
      const asin = card.getAttribute("data-asin");
      if (!asin || seenAsins.has(asin)) continue;
      seenAsins.add(asin);

      const name = text(card, ["h2 span", "h2 a span", ".a-size-medium"]);
      if (!name) continue;

      const price = parsePrice(
        text(card, [".a-price .a-offscreen", ".a-price-whole"])
      );
      if (price === null) continue; // unpriced results are not comparable

      results.push({
        name,
        price,
        // Canonical product URL, not the search page. This is the point.
        url: `https://www.amazon.com/dp/${asin}`,
        source: "amazon",
      });
      if (results.length >= limit) break;
    }
    return results;
  }

  /**
   * Queries aimed at the greener end of the same shelf. Deliberately plain
   * terms -- "eco" in a listing title means nothing, but "refill" and
   * "stainless steel" describe the actual thing.
   */
  function greenerQueries(product) {
    const base = (product.title || "")
      .toLowerCase()
      .replace(/[^a-z0-9 ]+/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 3 && !STOPWORDS.has(w))
      .slice(0, 4)
      .join(" ");
    if (!base) return [];
    return [`refillable ${base}`, `plastic free reusable ${base}`];
  }

  const STOPWORDS = new Set([
    "pack", "count", "with", "size", "large", "small", "value", "ultra",
    "original", "scent", "liquid", "bottles", "bottle", "each", "free",
  ]);

  async function findCandidates(product) {
    if (product.retailer !== "amazon") return [];
    const queries = greenerQueries(product);
    const batches = await Promise.all(queries.map((q) => searchAmazon(q, 8)));

    const seen = new Set();
    const merged = [];
    for (const listing of batches.flat()) {
      if (seen.has(listing.url)) continue;
      seen.add(listing.url);
      merged.push(listing);
    }
    return merged.slice(0, 16);
  }

  function detect() {
    if (location.hostname === "localhost") return scrapeMockStore();
    if (location.hostname.endsWith("amazon.com")) return scrapeAmazon();
    return null;
  }

  self.GreenSwapScrapers = { detect, findCandidates, searchAmazon };
})();
