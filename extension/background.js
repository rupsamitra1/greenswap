/**
 * Service worker.
 *
 * Content scripts fetch under the page's origin and would be blocked by CORS.
 * The service worker fetches under the extension's own origin using
 * host_permissions, so all backend traffic is routed through here.
 */

// 127.0.0.1, not "localhost". On Windows localhost resolves to the IPv6
// loopback ::1 first, and a server bound only to IPv4 refuses that -- which
// surfaces as a bare "Failed to fetch" with nothing else to go on.
console.log("[GreenSwap] service worker started", chrome.runtime.getManifest().version);

const API_BASES = ["http://127.0.0.1:8000", "http://localhost:8000"];

async function callBackend(path, init) {
  // "Failed to fetch" on its own is useless for diagnosis -- it covers a
  // refused connection, a blocked private-network request and a dead server
  // alike. Report what was tried and what each attempt said.
  const attempts = [];
  for (const base of API_BASES) {
    try {
      const res = await fetch(base + path, init);
      console.log(`[GreenSwap] ${base}${path} -> ${res.status}`);
      return res;
    } catch (err) {
      attempts.push(`${base}: ${err?.message || err}`);
      console.warn(`[GreenSwap] ${base}${path} failed:`, err);
    }
  }
  throw new Error(
    `backend unreachable — ${attempts.join(" | ")}. ` +
    `Is the server running? Start it with: ` +
    `python -m uvicorn main:app --host 0.0.0.0 --port 8000`
  );
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  // Retailer search runs here rather than in the content script: a page like
  // Amazon has a strict CSP that can block fetches made from its own context,
  // while the service worker fetches under host_permissions and still sends
  // the shopper's cookies, so results match what they would see.
  if (message?.type === "GREENSWAP_SEARCH") {
    fetch(message.url, { credentials: "include" })
      .then(async (res) => {
        const html = await res.text();
        if (!res.ok) {
          return sendResponse({
            ok: false,
            error: `HTTP ${res.status}`,
            bytes: html.length,
          });
        }
        // Amazon serves a bot check instead of results when it does not like
        // the request. That arrives as a perfectly good 200, so the only way
        // to tell is to look at what came back.
        const blocked =
          /api-services-support@amazon\.com|Robot Check|Enter the characters you see|captcha/i
            .test(html.slice(0, 20000));
        sendResponse({ ok: true, html, bytes: html.length, blocked });
      })
      .catch((err) =>
        sendResponse({ ok: false, error: err?.message || String(err) })
      );
    return true;
  }

  if (message?.type !== "GREENSWAP_ANALYZE") return false;

  callBackend("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.product),
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);
      sendResponse({ ok: true, data: await res.json() });
    })
    .catch((err) => {
      sendResponse({ ok: false, error: err.message });
    });

  return true; // keep the message channel open for the async response
});
