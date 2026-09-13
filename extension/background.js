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
const API_BASES = ["http://127.0.0.1:8000", "http://localhost:8000"];

async function callBackend(path, init) {
  let lastError;
  for (const base of API_BASES) {
    try {
      return await fetch(base + path, init);
    } catch (err) {
      lastError = err; // try the next address before giving up
    }
  }
  throw lastError;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  // Retailer search runs here rather than in the content script: a page like
  // Amazon has a strict CSP that can block fetches made from its own context,
  // while the service worker fetches under host_permissions and still sends
  // the shopper's cookies, so results match what they would see.
  if (message?.type === "GREENSWAP_SEARCH") {
    fetch(message.url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`search returned ${res.status}`);
        sendResponse({ ok: true, html: await res.text() });
      })
      .catch((err) => sendResponse({ ok: false, error: err.message }));
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
