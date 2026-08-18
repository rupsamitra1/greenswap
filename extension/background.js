/**
 * Service worker.
 *
 * Content scripts fetch under the page's origin and would be blocked by CORS.
 * The service worker fetches under the extension's own origin using
 * host_permissions, so all backend traffic is routed through here.
 */

const API_BASE = "http://localhost:8000";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
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
