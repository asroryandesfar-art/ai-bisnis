# Web Intelligence — Frontend

Enterprise workspace UI for the `backend/modules/web_intelligence` module, built
**inside the existing BotNesia SPA** (vanilla-JS ES modules, dark theme) — no
React/Next/build step. Consistent with the rest of the dashboard.

## Files
| File | Role |
|------|------|
| `web_intelligence.js` | The whole workspace: 8 route renderers + view/state helpers. Self-contained, dependency-injected via `createWebIntelligence({ el, setPage, toast, state, api })`. |
| `api-client.js` | `webIntel*` methods (status/read/crawl/ingest/screenshot/cache-clear). |
| `components.js` | Nav group `web-intelligence`, per-route icons, route meta. |
| `app.js` | Imports the module, spreads its renderers + routes into the router. |
| `i18n.js` | `wi.*`, `nav.*`, `route.*` strings (ID + EN). |
| `styles.css` | `.wi-*` classes (uses existing design tokens only). |

## Routes (sidebar group “Web Intelligence”)
`web-intelligence` (Dashboard) · `wi-scraper` · `wi-crawl` · `wi-extract` ·
`wi-knowledge` · `wi-verify` · `wi-screenshot` · `wi-settings`.

## Backend mapping (every button hits a real API — no mock data)
| Tab | Endpoint |
|-----|----------|
| Dashboard / Settings | `GET /api/web-intelligence/status`, `POST …/cache/clear` |
| Web Scraper / Extraction / Verification | `POST …/read` |
| Website Crawl | `POST …/crawl` |
| Knowledge Builder | `POST …/read` (preview) + `POST …/ingest?bot_id=` |
| Screenshot | `POST …/screenshot` (PNG blob) |

## State / UX
- Module-scoped `wiState` (status cache 30 s, cross-tab URL prefill, in-flight
  `AbortController` for Cancel, screenshot object-URL cleanup). No fake persistence.
- Every async view has: skeleton/spinner loading, try/catch error state, and an
  empty state. Cross-tab actions (Open / Extract / Verify / To Knowledge) carry
  the URL forward via `wiState.prefillUrl`.
- Fully localized (ID/EN) and responsive.

## Intentionally NOT shipped (no backend yet)
Search, Scheduler, Browser-Automation actions (click/type/scroll), Job
History/Queue, and WebSocket live-progress have **no backend endpoint**. Per the
“no mock data” rule they are omitted rather than faked. Crawl runs synchronously
(the API returns on completion), so its progress is a busy state + final stats,
not a streamed bar. When those backends land, add a route to `WI_ROUTES`, a
renderer, a nav item, and i18n/icon entries — the module is structured for it.
