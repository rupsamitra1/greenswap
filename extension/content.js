/**
 * Content script: scrape the page, ask the backend, then sit quietly in the
 * corner until the shopper wants us.
 *
 * Interaction: a circular launcher pinned bottom-right. When we have something
 * worth saying it gains a soft halo -- an invitation, not an interruption.
 * Clicking opens the panel.
 *
 * Layout owes a debt to three extensions that solve this well: Fakespot
 * (verdict first -- one big score in a high-contrast block, one plain
 * sentence), Capital One Shopping (scannable rows with a dedicated price
 * column and the winner tagged), and Honey (the savings number is never
 * buried in prose).
 *
 * Typography is deliberately split. The brand faces -- Edu cursive for the
 * wordmark, EB Garamond for the score -- carry personality at display sizes.
 * Everything else is a system sans, because old-style serifs at 12px are hard
 * to read on screen and this panel is dense UI, not an essay.
 */

(function () {
  "use strict";

  if (window.__greenswapInjected) return;
  window.__greenswapInjected = true;

  /**
   * Bundled fonts, served from inside the extension -- never a font CDN, which
   * would leak every product page a user opens to a third party.
   *
   * These rules must live in the PAGE document: Chrome ignores @font-face
   * declared inside a shadow root, though the shadow root can use the families.
   */
  function installFonts() {
    if (document.getElementById("greenswap-fonts")) return;
    const url = (f) => chrome.runtime.getURL(`fonts/${f}`);
    const style = document.createElement("style");
    style.id = "greenswap-fonts";
    style.textContent = `
      @font-face {
        font-family: "GreenSwap Script";
        src: url("${url("EduNSWACTCursive-Bold.woff2")}") format("woff2"),
             url("${url("EduNSWACTCursive-Bold.ttf")}") format("truetype");
        font-weight: 700; font-style: normal; font-display: swap;
      }
      @font-face {
        font-family: "GreenSwap Serif";
        src: url("${url("EBGaramond-Regular.woff2")}") format("woff2"),
             url("${url("EBGaramond-Regular.ttf")}") format("truetype");
        font-weight: 400; font-display: swap;
      }
      @font-face {
        font-family: "GreenSwap Serif";
        src: url("${url("EBGaramond-SemiBold.woff2")}") format("woff2"),
             url("${url("EBGaramond-SemiBold.ttf")}") format("truetype");
        font-weight: 600; font-display: swap;
      }`;
    (document.head || document.documentElement).appendChild(style);
  }

  const LOGO = () =>
    `<img src="${chrome.runtime.getURL("icons/logo.png")}" alt="" aria-hidden="true">`;

  const STYLES = `
    :host {
      /* --- brand ------------------------------------------------------- */
      --gs-green: #225c3d;
      --gs-green-deep: #16412b;
      --gs-halo: #6fe3a0;

      /* --- surfaces ---------------------------------------------------- */
      --gs-cream: #f4f1e8;
      --gs-card: #fffdf7;
      --gs-line: #ded9ca;

      /* --- text: all of these clear WCAG AA on cream ------------------- */
      --gs-ink: #12291d;      /* primary copy  ~13.5:1 */
      --gs-muted: #4d6b59;    /* secondary     ~5.6:1  */

      --gs-script: "GreenSwap Script", "Segoe Script", "Bradley Hand", cursive;
      --gs-serif: "GreenSwap Serif", "EB Garamond", Georgia, serif;
      --gs-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    }

    .wrap { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; }

    /* --- launcher ------------------------------------------------------ */
    .launcher {
      position: relative; display: block;
      width: 56px; height: 56px; padding: 0;
      border: 0; border-radius: 50%;
      background: var(--gs-green); cursor: pointer;
      box-shadow: 0 3px 12px rgba(22, 65, 43, 0.32);
      transition: transform 160ms ease, box-shadow 160ms ease;
    }
    .launcher img { width: 100%; height: 100%; border-radius: 50%; display: block; }
    .launcher:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(22,65,43,.4); }
    .launcher:focus-visible { outline: 3px solid var(--gs-halo); outline-offset: 3px; }

    .launcher.has-news::after {
      content: ""; position: absolute; inset: -3px;
      border-radius: 50%; pointer-events: none;
      box-shadow: 0 0 0 1.5px rgba(111,227,160,.75),
                  0 0 10px 2px rgba(111,227,160,.55),
                  0 0 22px 6px rgba(111,227,160,.28);
      animation: gs-halo 2.8s ease-in-out infinite;
    }
    @keyframes gs-halo { 0%,100% { opacity:.45 } 50% { opacity:1 } }

    /* --- panel --------------------------------------------------------- */
    .panel {
      position: absolute; right: 0; bottom: 68px;
      width: 384px; max-width: calc(100vw - 40px);
      max-height: 74vh; overflow-y: auto;
      background: var(--gs-cream);
      color: var(--gs-ink);
      border-radius: 14px;
      box-shadow: 0 14px 38px rgba(22,65,43,.26);
      font-family: var(--gs-sans);
      font-size: 14px; line-height: 1.5;
      text-align: left;
    }
    .panel[hidden] { display: none; }
    .panel * { box-sizing: border-box; }

    /* --- header -------------------------------------------------------- */
    .head {
      display: flex; align-items: center; gap: 9px;
      padding: 13px 16px 11px;
      border-bottom: 1px solid var(--gs-line);
    }
    .head img { width: 24px; height: 24px; border-radius: 50%; display: block; }
    .wordmark {
      font-family: var(--gs-script);
      font-size: 26px; line-height: 1.3;
      color: var(--gs-green); font-weight: 700;
    }
    .close {
      margin-left: auto; width: 30px; height: 30px;
      display: flex; align-items: center; justify-content: center;
      border: 0; border-radius: 50%; background: transparent;
      color: var(--gs-muted); font-size: 20px; line-height: 1; cursor: pointer;
      font-family: var(--gs-sans);
      transition: background-color 140ms ease, color 140ms ease;
    }
    .close:hover { background: #e7e2d3; color: var(--gs-ink); }
    .close:focus-visible { outline: 2px solid var(--gs-green); outline-offset: 2px; }

    /* --- verdict: inverted block, the loudest thing in the panel ------- */
    .verdict {
      display: flex; align-items: center; gap: 14px;
      padding: 15px 16px;
      background: var(--gs-green);
      color: #fff;
    }
    .verdict-score {
      font-family: var(--gs-serif); font-weight: 600;
      font-size: 46px; line-height: .95;
      letter-spacing: -0.02em;
      flex: none;
    }
    .verdict-score span { font-family: var(--gs-sans); font-size: 13px; font-weight: 400; opacity: .8; }
    .verdict-label {
      font-size: 10.5px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .1em;
      opacity: .85;
    }
    .verdict-reason { font-size: 13px; line-height: 1.45; margin-top: 3px; }

    .badge {
      display: inline-block; margin-top: 7px;
      padding: 3px 9px; border-radius: 999px;
      font-size: 11px; font-weight: 600; letter-spacing: .02em;
      white-space: nowrap;
    }
    /* On the green verdict block */
    .verdict .badge.certified { background: #fff; color: var(--gs-green-deep); }
    .verdict .badge.ai_estimated,
    .verdict .badge.heuristic { background: rgba(255,255,255,.16); color: #fff; }
    /* On cream rows */
    .badge.certified { background: var(--gs-green); color: #fff; }
    .badge.ai_estimated, .badge.heuristic {
      background: transparent; color: var(--gs-muted);
      border: 1px solid var(--gs-line);
    }
    .badge.documented { background: #e4ede7; color: var(--gs-green-deep); border: 1px solid #bfd0c4; }
    .partner { display:inline-block; padding:3px 8px; border-radius:999px; background:#fff2cc; color:#694f00; font-size:11px; font-weight:700; }

    /* --- citations: the evidence behind the badge ----------------------- */
    .sources { margin-top: 10px; }
    .sources-label {
      font-size: 10.5px; font-weight: 700; letter-spacing: .1em;
      text-transform: uppercase; opacity: .85;
    }
    .source {
      display: block; margin-top: 5px;
      font-size: 12px; line-height: 1.4;
      color: #fff; text-decoration: none;
      border-bottom: 1px solid rgba(255,255,255,.45);
      width: fit-content; max-width: 100%;
    }
    .source:hover { border-bottom-color: #fff; }
    .source:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
    .source .cite-claim { opacity: .92; }
    .source .cite-src { opacity: .7; }

    /* --- section heading ------------------------------------------------ */
    .section {
      display: flex; align-items: baseline; gap: 6px;
      padding: 14px 16px 8px;
      font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .1em;
      color: var(--gs-muted);
    }

    /* --- baseline: what they're looking at now, for direct comparison -- */
    .baseline {
      display: flex; align-items: center; gap: 10px;
      margin: 0 16px 4px; padding: 8px 11px;
      border: 1px dashed var(--gs-line); border-radius: 9px;
      font-size: 12.5px; color: var(--gs-muted);
    }
    .baseline .amount { margin-left: auto; font-weight: 600; color: var(--gs-ink); }

    /* --- comparison rows ------------------------------------------------ */
    .rows { padding: 0 16px 6px; }
    .row {
      position: relative;
      display: flex; gap: 12px;
      padding: 12px 12px;
      margin-bottom: 8px;
      background: var(--gs-card);
      border: 1px solid var(--gs-line);
      border-radius: 10px;
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }
    .row:hover { border-color: var(--gs-green); box-shadow: 0 2px 10px rgba(34,92,61,.12); }
    .row.best { border-color: var(--gs-green); border-width: 1.5px; }

    .tag {
      position: absolute; top: -8px; left: 11px;
      padding: 2px 8px; border-radius: 999px;
      background: var(--gs-green); color: #fff;
      font-size: 10px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .08em;
    }
    .row-main { flex: 1; min-width: 0; }
    .row-name {
      font-size: 14px; font-weight: 600; line-height: 1.3;
      color: var(--gs-ink);
    }
    a.row-name { text-decoration: none; }
    a.row-name:hover { text-decoration: underline; }
    a.row-name:focus-visible { outline: 2px solid var(--gs-green); outline-offset: 2px; }
    .row-go,
    .row-go:link,
    .row-go:visited {
      display: inline-block; margin-top: 8px;
      padding: 6px 12px; border-radius: 999px;
      background: var(--gs-green); color: #fff;
      font-size: 12px; font-weight: 600; text-decoration: none;
      transition: background-color 140ms ease;
    }
    .row-go:hover { background: var(--gs-green-deep); }
    .row-go:focus-visible { outline: 2px solid var(--gs-green); outline-offset: 2px; }
    .row-go::after { content: " →"; }
    .row-why { font-size: 12.5px; line-height: 1.45; color: var(--gs-muted); margin-top: 4px; }
    .row-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 8px; }

    .eco {
      display: inline-block; padding: 3px 9px; border-radius: 999px;
      background: #e4ede7; color: var(--gs-green-deep);
      font-size: 11px; font-weight: 700; letter-spacing: .01em;
      white-space: nowrap;
    }

    /* Dedicated price column -- the number is never buried in prose. */
    .row-price { flex: none; text-align: right; min-width: 78px; }
    .amount {
      font-size: 18px; font-weight: 700; color: var(--gs-ink);
      font-variant-numeric: tabular-nums; line-height: 1.2;
    }
    .save {
      display: inline-block; margin-top: 4px;
      padding: 2px 7px; border-radius: 999px;
      background: var(--gs-green); color: #fff;
      font-size: 11px; font-weight: 700; white-space: nowrap;
    }
    .unit {
      margin-top: 3px; font-size: 11px; color: var(--gs-muted);
      font-variant-numeric: tabular-nums;
    }
    .save.neutral { background: #e4ede7; color: var(--gs-green-deep); }
    .save.more { background: #f0e6d8; color: #7a5320; }

    /* --- states --------------------------------------------------------- */
    .empty, .notice { font-size: 13px; line-height: 1.5; }
    .empty { padding: 2px 16px 14px; color: var(--gs-muted); }
    .why { margin-top: 6px; font-size: 12px; opacity: .85; }
    .tier-note {
      margin: 0 16px 8px; font-size: 12px; line-height: 1.45;
      color: var(--gs-muted);
    }
    .near-label { margin-top: 7px; font-weight: 600; opacity: .9; }
    .near { margin-top: 3px; font-size: 11.5px; opacity: .8; }
    .notice {
      margin: 0 16px 10px; padding: 10px 12px;
      background: #f0e6d8; color: #6b4a1c;
      border-radius: 9px; font-size: 12.5px;
    }
    .reveal {
      display: block; width: calc(100% - 32px); margin: 2px 16px 14px;
      padding: 11px 12px;
      background: transparent; color: var(--gs-green);
      border: 1.5px solid var(--gs-green); border-radius: 999px;
      font-family: var(--gs-sans); font-size: 13px; font-weight: 600;
      cursor: pointer;
      transition: background-color 140ms ease, color 140ms ease;
    }
    .reveal:hover { background: var(--gs-green); color: #fff; }
    .reveal:focus-visible { outline: 2px solid var(--gs-green); outline-offset: 2px; }
    .pricier[hidden] { display: none; }

    .pipeline { display:grid; grid-template-columns:repeat(4,1fr); gap:5px; padding:12px 16px 4px; }
    .step { border:1px solid var(--gs-line); border-radius:8px; padding:7px 4px; text-align:center; font-size:10px; color:var(--gs-muted); background:var(--gs-card); }
    .step::before { content:"✓"; display:block; color:var(--gs-green); font-weight:800; font-size:14px; }
    .step strong { display:block; color:var(--gs-ink); font-size:10.5px; }
    .explain { margin:8px 16px 4px; border:1px solid var(--gs-line); border-radius:9px; background:var(--gs-card); }
    .explain summary { cursor:pointer; padding:10px 12px; color:var(--gs-green-deep); font-weight:700; }
    .explain-body { padding:0 12px 11px; font-size:12px; color:var(--gs-muted); }
    .dimension { display:grid; grid-template-columns:1fr auto; gap:8px; padding:5px 0; border-top:1px solid #ece8dc; }
    .dimension strong { color:var(--gs-ink); }
    .confidence { margin:8px 0; padding:7px 8px; border-radius:7px; background:#edf3ee; color:var(--gs-green-deep); }
    .warning { color:#79531c; margin-top:5px; }
    .evidence { margin-top:8px; padding-top:7px; border-top:1px solid #ece8dc; }
    .evidence div { margin-top:4px; }
    .unit { color:var(--gs-muted); font-size:10.5px; margin-top:3px; white-space:nowrap; }
    .row-go.shop { color:#fff; text-decoration:none; }
    .disclosure { margin:7px 16px 12px; font-size:11px; line-height:1.4; color:var(--gs-muted); }
    .keep { margin:0 16px 12px; padding:12px; background:#e4ede7; color:var(--gs-green-deep); border-radius:9px; font-weight:650; }

    @media (max-width: 480px) {
      .panel { width: calc(100vw - 40px); }
      .verdict-score { font-size: 38px; }
    }
    @media (prefers-reduced-motion: reduce) {
      .launcher, .launcher.has-news::after, .close, .reveal, .row { transition: none; animation: none; }
      .launcher.has-news::after { opacity: .85; }
    }
  `;

  function escapeHtml(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function badge(trust, certification) {
    const labels = {
      certified: `✓ ${certification || "Certified"}`,
      documented: `✓ ${certification || "Documented"}`,
      evidence: "~ Evidence estimate",
      ai_estimated: "~ AI estimate",
      heuristic: "~ Rule-based estimate",
    };
    const label = labels[trust] || labels.ai_estimated;
    return `<span class="badge ${trust}">${escapeHtml(label)}</span>`;
  }

  /** Price column: the saving is a filled pill, never a sentence. */
  function priceCell(alt) {
    let pill;
    if (typeof alt.extra_cost === "number") {
      pill = `<span class="save more">+$${alt.extra_cost.toFixed(2)}</span>`;
    } else if (alt.savings === null || alt.savings === undefined) {
      pill = `<span class="save neutral">Not compared</span>`;
    } else if (alt.savings > 0) {
      pill = `<span class="save">Save $${alt.savings.toFixed(2)}</span>`;
    } else {
      pill = `<span class="save neutral">Same price</span>`;
    }
    const basis = alt.price_basis || {};
    const unitText = basis.price_per_use != null
      ? `$${Number(basis.price_per_use).toFixed(3)}/use*`
      : basis.price_per_unit != null && basis.unit
        ? `$${Number(basis.price_per_unit).toFixed(2)}/${escapeHtml(basis.unit)}`
        : alt.unit_price && alt.unit_label
          ? `$${Number(alt.unit_price).toFixed(2)}/${escapeHtml(alt.unit_label)}`
          : "";
    return `
      <div class="row-price">
        <div class="amount">$${Number(alt.price).toFixed(2)}</div>
        ${pill}
        ${unitText ? `<div class="unit">${unitText}</div>` : ""}
      </div>`;
  }

  /**
   * Citations are what separate a verified badge from a claim. The backend has
   * already discarded any the model could not support with a real tool result,
   * so anything reaching here is checkable -- and we make it clickable so the
   * shopper can check it.
   */
  function renderCitations(citations) {
    if (!citations || !citations.length) return "";
    const links = citations
      .map(
        (c) => `<a class="source" href="${escapeHtml(c.url)}"
                   target="_blank" rel="noopener noreferrer">
                  <span class="cite-claim">${escapeHtml(c.claim)}</span>
                  <span class="cite-src"> — ${escapeHtml(c.source)}</span>
                </a>`
      )
      .join("");
    return `<div class="sources">
              <div class="sources-label">Evidence</div>${links}
            </div>`;
  }

  function renderRow(alt, index, all, opts = {}) {
    // Only the cheaper list has a "best swap". Tagging the first dearer option
    // that way says the best thing to do is spend more, which is the opposite
    // of what this product promises.
    const best = index === 0 && opts.tagBest !== false;
    return `
      <div class="row ${best ? "best" : ""}">
        ${best ? `<span class="tag">Best swap</span>` : ""}
        <div class="row-main">
          ${
            alt.url
              ? `<a class="row-name" href="${escapeHtml(alt.url)}"
                     target="_blank" rel="noopener noreferrer"
                  >${escapeHtml(alt.name)}</a>`
              : `<div class="row-name">${escapeHtml(alt.name)}</div>`
          }
          <div class="row-why">${escapeHtml(alt.reason)}</div>
          <div class="row-meta">
            <span class="eco">Eco score: ${alt.eco_score}</span>
            ${badge(alt.trust, alt.certification)}
            ${alt.affiliate ? `<span class="partner">Partner link</span>` : ""}
          </div>
          ${
            alt.purchase_url || alt.url
              ? `<a class="row-go shop" href="${escapeHtml(alt.purchase_url || alt.url)}"
                     target="_blank" rel="noopener noreferrer">View product ↗</a>`
              : ""
          }
        </div>
        ${priceCell(alt)}
      </div>`;
  }

  function renderPanel(data) {
    const { original, alternatives } = data;
    const pricier = data.pricier || [];

    // Cheaper-or-equal options are the answer. Dearer ones are always available
    // but never volunteered -- the shopper opts in, so a pricier suggestion is
    // something they asked for rather than something we slipped in.
    let body = "";
    if (alternatives.length) {
      body = `<div class="rows">${alternatives.map(renderRow).join("")}</div>`;
    } else if (pricier.length) {
      body = `<div class="empty">Nothing greener at or below this price.</div>`;
    } else if (data.keep_current) {
      body = `<div class="keep">Keep this one. We found no sufficiently better option at this price.</div>`;
    } else {
      // Say which kind of nothing this is. "We could not read this page" and
      // "we checked twelve and none qualified" call for different reactions.
      const d = data.diagnostics || {};
      let why;
      if (!d.listings_considered) {
        why = `We couldn't read other listings from this page, so there is
               nothing to compare against yet.`;
      } else {
        const bits = [];
        if (d.too_low_scoring) bits.push(`${d.too_low_scoring} weren't meaningfully greener`);
        if (d.too_expensive) bits.push(`${d.too_expensive} cost more`);
        const closest = (d.closest || [])
          .map(
            (c) =>
              `<div class="near">${escapeHtml(c.name.slice(0, 60))} — scored ${
                c.eco_score
              }${c.price ? `, $${Number(c.price).toFixed(2)}` : ""}</div>`
          )
          .join("");
        why =
          `We checked ${d.listings_considered} other listing${
            d.listings_considered === 1 ? "" : "s"
          } on this page${bits.length ? ` — ${bits.join(", ")}` : ""}.` +
          (closest
            ? `<div class="near-label">Closest we found (needs ${d.min_score}+):</div>${closest}`
            : "");
      }
      body = `<div class="empty">No greener option at or below this price yet.
                We never suggest an alternative that costs more.
                <div class="why">${why}</div></div>`;
    }

    // Two further kinds of answer, each framed for what it actually is.
    const betterFormat = data.better_format || [];
    const longerTerm = data.longer_term || [];

    if (betterFormat.length) {
      body += `
        <div class="section">Same format, better material</div>
        <div class="tier-note">Still single-use, but a lower-impact material.</div>
        <div class="rows">${betterFormat
          .map((alt, i, all) => renderRow(alt, i, all, { tagBest: false }))
          .join("")}</div>`;
    }

    if (longerTerm.length) {
      body += `
        <div class="section">Longer-term swap</div>
        <div class="tier-note">Replaces repeat purchases rather than matching
          this pack — better for the planet, different for your basket.</div>
        <div class="rows">${longerTerm
          .map((alt, i, all) => renderRow(alt, i, all, { tagBest: false }))
          .join("")}</div>`;
    }

    if (pricier.length) {
      const label = alternatives.length
        ? `See ${pricier.length} greener option${pricier.length > 1 ? "s" : ""} that cost more`
        : `Show ${pricier.length} that cost more`;
      body += `
        <button class="reveal" aria-expanded="false">${label}</button>
        <div class="pricier rows" hidden>${pricier
          .map((alt, i, all) => renderRow(alt, i, all, { tagBest: false }))
          .join("")}</div>`;
    }

    // Showing the current price alongside makes the comparison concrete
    // rather than asking the shopper to hold it in their head.
    const baseline =
      data.price_known !== false && original.price
        ? `<div class="baseline">
             <span>Currently viewing</span>
             <span class="amount">$${Number(original.price).toFixed(2)}</span>
           </div>`
        : "";

    const analysis = data.analysis || original.analysis || {};
    const dimensions = (analysis.dimensions || []).map((dimension) => `
      <div class="dimension">
        <span><strong>${escapeHtml(dimension.dimension.replaceAll("_", " "))}</strong><br>${escapeHtml(dimension.assessment || "Unknown — no points assumed")}</span>
        <span>${dimension.points == null ? "?" : dimension.points}/${dimension.maximum}</span>
      </div>`).join("");
    const warnings = (analysis.warnings || []).slice(0, 3).map((w) => `<div class="warning">• ${escapeHtml(w)}</div>`).join("");
    const evidence = (analysis.evidence || []).slice(0, 4).map((item) => `<div>• ${escapeHtml(item.claim)} <em>(${escapeHtml(item.source)})</em></div>`).join("");
    // The strict rubric can decline to issue a verified score, but the shopper
    // still needs a useful screening estimate. Show the bounded fallback and
    // mark it visibly approximate instead of replacing it with a blank dash.
    const isEstimate = analysis.overall_score == null && original.eco_score != null;
    const scoreDisplay = analysis.overall_score ?? original.eco_score ?? "—";
    const pipeline = (data.analysis_steps || []).map((step) => `<div class="step"><strong>${escapeHtml(step.label)}</strong>${escapeHtml(step.detail)}</div>`).join("");
    const affiliateDisclosure = [...alternatives, ...pricier].some((a) => a.affiliate)
      ? `<div class="disclosure"><strong>Affiliate disclosure:</strong> GreenSwap may earn from partner links. Eco scores never receive partner points.${data.ranking?.affiliate_influenced ? " A maximum 3-point partner preference changed the order only inside the disclosed 4-point environmental equivalence band." : " Partner status did not change this ordering."} *Per-use values are estimates.</div>` : "";

    return `
      <div class="head">
        ${LOGO()}
        <span class="wordmark">GreenSwap</span>
        <button class="close" aria-label="Close GreenSwap">&times;</button>
      </div>

      <div class="verdict">
        <div class="verdict-score">${isEstimate ? "~" : ""}${scoreDisplay}<span>/100</span></div>
        <div>
          <div class="verdict-label">This item</div>
          <div class="verdict-reason">${escapeHtml(original.reason)}</div>
          ${badge(original.trust, original.certification)}
          ${renderCitations(original.citations)}
        </div>
      </div>

      <div class="pipeline">${pipeline}</div>
      <details class="explain">
        <summary>Why this score?</summary>
        <div class="explain-body">
          <div class="confidence">${isEstimate ? "Estimated range: ±10 points · " : ""}${escapeHtml(analysis.confidence || "low")} evidence confidence · ${analysis.confidence_score ?? 0}/100 · ${analysis.coverage_percent ?? 0}% coverage</div>
          ${dimensions}
          ${evidence ? `<div class="evidence"><strong>Evidence used</strong>${evidence}</div>` : ""}
          ${warnings}
          <div class="warning">Method ${escapeHtml(data.method_version || "prototype")}; this is a screening tool, not a safety certification or full life-cycle assessment.</div>
        </div>
      </details>

      <div class="section">${
        data.price_known === false
          ? "Greener options · price not compared"
          : "Swap for · same price or less"
      }</div>
      ${
        data.price_known === false
          ? `<div class="notice">We couldn't read this item's price, so these
               haven't been checked against it and may cost more.</div>`
          : baseline
      }
      ${body}
      ${affiliateDisclosure}`;
  }

  function mount(data) {
    installFonts();

    const host = document.createElement("div");
    host.id = "greenswap-host";
    document.body.appendChild(host);

    const shadow = host.attachShadow({ mode: "open" });
    const hasNews = (data.alternatives.length || (data.pricier || []).length) > 0;

    shadow.innerHTML = `
      <style>${STYLES}</style>
      <div class="wrap">
        <div class="panel" role="dialog" aria-label="GreenSwap suggestions" hidden></div>
        <button class="launcher ${hasNews ? "has-news" : ""}"
                aria-label="Open GreenSwap" aria-expanded="false">${LOGO()}</button>
      </div>`;

    const launcher = shadow.querySelector(".launcher");
    const panel = shadow.querySelector(".panel");

    function open() {
      panel.innerHTML = renderPanel(data);
      panel.hidden = false;
      launcher.setAttribute("aria-expanded", "true");
      launcher.classList.remove("has-news"); // seen it; stop glowing
      panel.querySelector(".close").addEventListener("click", close);

      const reveal = panel.querySelector(".reveal");
      reveal?.addEventListener("click", () => {
        panel.querySelector(".pricier").hidden = false;
        reveal.remove();
      });
      panel.querySelector(".close").focus();
    }

    function close() {
      panel.hidden = true;
      panel.innerHTML = "";
      launcher.setAttribute("aria-expanded", "false");
      launcher.focus();
    }

    launcher.addEventListener("click", () => (panel.hidden ? open() : close()));
    shadow.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden) close();
    });
  }

  /** True only while this script still has a live extension context. */
  function alive() {
    try {
      return Boolean(globalThis.chrome?.runtime?.id);
    } catch (err) {
      return false; // touching a dead context can throw outright
    }
  }

  const product = self.GreenSwapScrapers.detect();
  if (!product || !product.title) return;

  /**
   * Look for real alternatives on the store before asking the backend, so the
   * agent reasons about listings that actually exist -- with real prices and
   * real product links -- rather than a small hand-kept catalog.
   *
   * The search happens here rather than server-side because this code is
   * already inside the retailer's origin with the shopper's session.
   */
  async function start() {
    if (!alive()) return; // orphaned before we even began

    // Announce the build up front. Without this there is no way to tell a
    // stale extension from a broken one, and they look identical from here.
    console.log(
      "[GreenSwap] v" + chrome.runtime.getManifest().version + " active"
    );

    try {
      product.listings = await self.GreenSwapScrapers.findCandidates(product);
      if (product.retailer === "amazon") {
        // Visible diagnostic: if this is 0 the retailer's search markup has
        // moved, and recommendations will silently fall back to the catalog.
        console.log(
          `[GreenSwap] ${product.listings.length} live listings found`,
          product.listings.map((l) => `${l.name.slice(0, 40)} $${l.price}`)
        );
      }
    } catch (err) {
      console.warn("[GreenSwap] live search failed:", err.message);
      product.listings = []; // a failed search must not cost us the card
    }

    // Reloading the extension orphans content scripts already running in open
    // tabs: chrome.runtime disappears underneath them. Awaiting the retailer
    // search widens that window, so check before using it rather than throwing
    // an uncaught error into the page.
    if (!alive()) {
      console.warn("[GreenSwap] extension was reloaded — refresh this page");
      return;
    }

    console.log("[GreenSwap] asking backend...");
    chrome.runtime.sendMessage(
      { type: "GREENSWAP_ANALYZE", product },
      (response) => {
        if (chrome.runtime.lastError || !response) {
          console.warn(
            "[GreenSwap] no reply from the service worker:",
            chrome.runtime.lastError?.message ||
              "it was probably terminated mid-request"
          );
          return;
        }
        if (!response.ok) {
          console.warn("[GreenSwap]", response.error);
          return;
        }
        mount(response.data);
      }
    );
  }

  // Nothing from an async entry point should surface as an uncaught rejection
  // in someone else's page.
  start().catch((err) => console.warn("[GreenSwap]", err?.message || err));
})();
