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
      .slice(0, 8);

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

  function detect() {
    if (location.hostname === "localhost") return scrapeMockStore();
    if (location.hostname.endsWith("amazon.com")) return scrapeAmazon();
    return null;
  }

  self.GreenSwapScrapers = { detect };
})();
