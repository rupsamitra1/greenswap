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

  /**
   * Longest matching text across several selectors.
   *
   * Picking the first match is wrong on search results: a brand label and a
   * product title both live under an h2, and the brand usually comes first.
   */
  function longestText(root, selectors) {
    let best = "";
    for (const selector of selectors) {
      for (const el of root.querySelectorAll(selector)) {
        const value = el.textContent.trim().replace(/\s+/g, " ");
        if (value.length > best.length) best = value;
      }
    }
    return best || null;
  }

  function parsePrice(raw) {
    if (!raw) return null;
    const match = raw.replace(/,/g, "").match(/\d+(\.\d+)?/);
    return match ? parseFloat(match[0]) : null;
  }

  function productJsonLd() {
    const candidates = [];
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(script.textContent);
        const visit = (value) => {
          if (!value || typeof value !== "object") return;
          if (Array.isArray(value)) return value.forEach(visit);
          const types = Array.isArray(value["@type"]) ? value["@type"] : [value["@type"]];
          if (types.some((type) => String(type).toLowerCase() === "product")) candidates.push(value);
          if (value["@graph"]) visit(value["@graph"]);
        };
        visit(parsed);
      } catch (_) {
        // Retailers sometimes ship malformed analytics JSON beside valid JSON-LD.
      }
    }
    return candidates[0] || {};
  }

  function amazonAsin() {
    const input = document.querySelector("#ASIN")?.value;
    const match = location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i);
    return (input || match?.[1] || "").trim().toUpperCase() || null;
  }

  function amazonModelNumber() {
    for (const row of document.querySelectorAll("#productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr")) {
      const label = row.querySelector("th")?.textContent.trim();
      if (/^(item )?model number$/i.test(label || "")) return row.querySelector("td")?.textContent.trim() || null;
    }
    return null;
  }

  /** Read Amazon's specification tables, including the "Top highlights"
   * block. Important material facts often live here instead of in bullets. */
  function amazonDetailFacts() {
    const facts = [];
    const selectors = [
      "#productOverview_feature_div tr",
      "#productDetails_techSpec_section_1 tr",
      "#productDetails_detailBullets_sections1 tr",
      "#detailBullets_feature_div li",
    ];
    for (const row of document.querySelectorAll(selectors.join(","))) {
      const cells = Array.from(row.querySelectorAll("th, td, span.a-text-bold"))
        .map((cell) => cell.textContent.trim().replace(/\s+/g, " "))
        .filter(Boolean);
      const value = row.querySelector("td")?.textContent.trim().replace(/\s+/g, " ");
      let fact = value && cells[0] ? `${cells[0]}: ${value}` : row.textContent.trim().replace(/\s+/g, " ");
      if (fact && fact.length >= 4 && fact.length <= 500 && !facts.includes(fact)) facts.push(fact);
    }
    const description = text(document, ["#productDescription", "#aplus_feature_div"]);
    if (description && description.length <= 1200) facts.push(description.replace(/\s+/g, " "));
    return facts.slice(0, 14);
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
      asin: null,
      gtin: root.dataset.gtin || null,
      model_number: root.dataset.modelNumber || null,
      sku: root.dataset.sku || null,
    };
  }

  // --- Amazon ---------------------------------------------------------------
  function scrapeAmazon() {
    const structured = productJsonLd();
    const structuredGtin = structured.gtin14 || structured.gtin13 || structured.gtin12 || structured.gtin8 || structured.gtin;
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
      .slice(0, 8)
      .concat(amazonDetailFacts())
      .slice(0, 20);

    return {
      title,
      price: parsePrice(priceRaw),
      brand,
      bullets,
      image_url: document.querySelector("#landingImage")?.src || null,
      url: location.href,
      retailer: "amazon",
      asin: amazonAsin(),
      gtin: structuredGtin ? String(structuredGtin) : null,
      model_number: structured.mpn || structured.model || amazonModelNumber(),
      sku: structured.sku || null,
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
  const SEARCH_TTL_MS = 10 * 60 * 1000;

  /** Session-scoped cache, so reloading a page does not refetch the search. */
  function cachedSearch(query) {
    try {
      const raw = sessionStorage.getItem("greenswap:" + query);
      if (!raw) return null;
      const { at, listings } = JSON.parse(raw);
      return Date.now() - at < SEARCH_TTL_MS ? listings : null;
    } catch (err) {
      return null; // storage can be unavailable; never fatal
    }
  }

  function rememberSearch(query, listings) {
    try {
      sessionStorage.setItem(
        "greenswap:" + query,
        JSON.stringify({ at: Date.now(), listings })
      );
    } catch (err) {
      /* quota or disabled storage -- not worth failing over */
    }
  }

  async function searchAmazon(query, limit = 8) {
    const cached = cachedSearch(query);
    if (cached) {
      console.log(`[GreenSwap] search (cached): ${cached.length} results`);
      return cached;
    }

    const url = `https://www.amazon.com/s?k=${encodeURIComponent(query)}`;
    let doc;
    let bytes = 0; // kept out of the try so the diagnostics below can see it
    let res = null;

    /**
     * Fetch from the page first, the service worker second.
     *
     * A content script runs same-origin on amazon.com, so its request carries
     * the shopper's cookies, a real referer and the browser's own headers --
     * it looks like the page asking, because it is. The service worker fetches
     * from the extension's context with none of that, which is the profile
     * Amazon answers with a bot check. Page CSP does not block this: content
     * scripts run in an isolated world and their fetches are exempt.
     *
     * The worker stays as a fallback for the case the page context refuses.
     */
    async function fetchSearchHtml() {
      if (location.hostname.endsWith("amazon.com")) {
        try {
          // A hang here would stop the card appearing at all, because the
          // backend call waits on this. Bound it.
          const abort = new AbortController();
          const timer = setTimeout(() => abort.abort(), 8000);
          const res = await fetch(url, {
            credentials: "include",
            headers: { Accept: "text/html,application/xhtml+xml" },
            signal: abort.signal,
          }).finally(() => clearTimeout(timer));
          if (res.ok) {
            const html = await res.text();
            return { ok: true, html, bytes: html.length, via: "page" };
          }
        } catch (err) {
          // fall through to the worker
        }
      }
      return await new Promise((resolve) => {
        let runtime;
        try {
          runtime = globalThis.chrome?.runtime?.id ? globalThis.chrome.runtime : null;
        } catch (err) {
          runtime = null;
        }
        if (!runtime) return resolve({ ok: false, error: "no extension context" });
        try {
          runtime.sendMessage({ type: "GREENSWAP_SEARCH", url }, (r) =>
            resolve(runtime.lastError ? { ok: false } : { ...r, via: "worker" })
          );
        } catch (err) {
          resolve({ ok: false, error: err.message });
        }
      });
    }

    try {
      res = await fetchSearchHtml();
      if (!res?.ok) {
        console.warn(
          `[GreenSwap] search fetch failed: ${res?.error || "unknown"} (${url})`
        );
        return [];
      }
      const blocked =
        res.blocked ??
        /api-services-support@amazon\.com|Robot Check|Enter the characters you see|captcha/i
          .test(res.html.slice(0, 20000));
      if (blocked) {
        console.warn(
          `[GreenSwap] Amazon returned a bot check via ${res.via} ` +
            `(${res.bytes} bytes). Live search unavailable on this request.`
        );
        return [];
      }
      bytes = res.bytes || res.html.length;
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

      // Amazon puts the brand in its own h2-adjacent span, so "first selector
      // that matches" reliably returns "YETI" instead of the product name.
      // Titles are long and brands are short, so take the longest candidate.
      const name = longestText(card, [
        '[data-cy="title-recipe"] h2 span',
        "h2 a span",
        "h2 span",
        ".a-size-medium",
        ".a-size-base-plus",
        "h2",
      ]);
      if (!name || name.length < 12) continue;

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

    if (results.length) {
      console.log(`[GreenSwap] search via ${res.via}: ${results.length} results`);
      rememberSearch(query, results);
    }
    if (!results.length) {
      // Distinguish "the page came back but we could not read it" from "the
      // request never succeeded" -- they need completely different fixes.
      console.warn(
        `[GreenSwap] parsed 0 results from ${bytes} bytes; ` +
          `${cards.length} result blocks seen. Amazon's markup may have changed.`
      );
    }
    return results;
  }

  /**
   * Queries aimed at the greener end of the same shelf. Deliberately plain
   * terms -- "eco" in a listing title means nothing, but "refill" and
   * "stainless steel" describe the actual thing.
   */
  function greenerQueries(product) {
    // Two things must come out of the query or it searches for the very
    // product we are replacing: the brand, which is irrelevant to finding an
    // alternative, and the words describing what is wrong with it. "reusable
    // clawsoff plastic disposable cups" returns disposable Clawsoff cups.
    const fullText = `${product.title || ""} ${(product.bullets || []).join(" ")}`.toLowerCase();
    if (/\b(water|beverage)\b/.test(fullText) && /\b(bottle|bottled|carton|pack)\b/.test(fullText)) {
      return ["reusable stainless steel water bottle"];
    }
    if (/\b(cups?|tumblers?)\b/.test(fullText)) return ["reusable insulated cup"];
    if (/\b(straws?)\b/.test(fullText)) return ["reusable stainless steel straws"];
    if (/\b(plates?|bowls?)\b/.test(fullText)) return ["reusable plates"];

    const brandWords = new Set(
      (product.brand || "").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)
    );
    const base = (product.title || "")
      .toLowerCase()
      .replace(/[^a-z0-9 ]+/g, " ")
      .split(/\s+/)
      .filter(
        (w) =>
          w.length > 3 &&
          !STOPWORDS.has(w) &&
          !AVOID_WORDS.has(w) &&
          !brandWords.has(w)
      )
      .slice(0, 3)
      .join(" ");
    if (!base) return [];
    // One query, not two. Each search is a multi-megabyte download, and firing
    // two on every product page both doubled the wait and made Amazon throttle
    // us. "reusable" is the single most productive term.
    return [`reusable ${base}`];
  }

  // Words naming the problem. Searching for them finds more of the problem.
  const AVOID_WORDS = new Set([
    "disposable", "plastic", "single", "styrofoam", "polystyrene", "foam",
    "throwaway", "onetime",
  ]);

  const STOPWORDS = new Set([
    "pack", "count", "with", "size", "large", "small", "value", "ultra",
    "original", "scent", "liquid", "bottles", "bottle", "each", "free",
  ]);

  async function findCandidates(product) {
    if (product.retailer !== "amazon") return [];
    const queries = greenerQueries(product);

    // Whatever happens, the card must still appear. Searching is an
    // enhancement; it is never allowed to become a precondition.
    const batches = await Promise.race([
      Promise.all(queries.map((q) => searchAmazon(q, 8))),
      new Promise((resolve) =>
        setTimeout(() => {
          console.warn("[GreenSwap] live search timed out; showing card anyway");
          resolve([]);
        }, 15000)
      ),
    ]);

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
