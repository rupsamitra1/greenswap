/**
 * Service worker.
 *
 * Content scripts fetch under the page's origin and would be blocked by CORS.
 * The service worker fetches under the extension's own origin using
 * host_permissions, so all backend traffic is routed through here.
 */

const API_BASE = "http://localhost:8000";

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

  fetch(`${API_BASE}/analyze`, {
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
