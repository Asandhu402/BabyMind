// Diagnostics window functional test (jsdom).
//
// Loads the real index.html + app.js into jsdom, mocks fetch / clipboard /
// confirm / window errors, and asserts the Diagnostics view renders the
// interaction log, copies per-entry/report/log-path to the clipboard, issues
// DELETE for Clear log, and posts uncaught client errors back to the server.
//
// This is a DOM-level test: it proves the view's logic and wiring, not visual
// rendering or a real browser (no browser is available in CI; see
// docs/KNOWN_LIMITATIONS.md). Run with: node tests/test_diagnostics_ui.js
// Functional test of the Diagnostics window: loads the real HTML + app.js into
// jsdom, mocks fetch/clipboard/confirm, and exercises the view end to end.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

// Repo-relative paths, so the test works from any checkout.
const webRoot = path.join(__dirname, "..", "src", "babymind", "web");
const html = fs.readFileSync(path.join(webRoot, "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(webRoot, "app.js"), "utf8");

const FIXTURE_ENTRIES = [
  { id:"e1", time:"2026-11-06T18:00:00.000+00:00", kind:"api", method:"GET", path:"/api/health", status:200, ok:true, duration_ms:3.2, error:null, detail:null },
  { id:"e2", time:"2026-11-06T18:01:00.000+00:00", kind:"api", method:"POST", path:"/api/memory/search", status:400, ok:false, duration_ms:1.5, error:"invalid literal for int() with base 10: 'abc'", detail:null },
  { id:"e3", time:"2026-11-06T18:02:00.000+00:00", kind:"client_error", method:"CLIENT", path:"/chat", status:0, ok:false, duration_ms:null, error:"TypeError: render exploded", detail:"at render (app.js:1) next line" },
  { id:"e4", time:"2026-11-06T18:03:00.000+00:00", kind:"asset", method:"GET", path:"/assets/app.js", status:404, ok:false, duration_ms:0.4, error:"Not found", detail:null },
];
const FIXTURE_REPORT = "## BabyMind diagnostics report\n\n- BabyMind: 0.6.0\n- Entries: 4 (3 with errors, newest last)\n";
const LOG_PATH = "/home/user/.babymind/interactions.jsonl";

const fetchCalls = [];
let clipboard = "";
let confirmAnswer = true;

const virtualConsole = new (require("jsdom").VirtualConsole)();
virtualConsole.on("jsdomError", (e) => console.log("JSDOM ERROR:", (e.detail && e.detail.stack) || e.stack || e));
const window = new JSDOM(html, { url: "http://127.0.0.1:8765/", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole }).window;

const jsonResponse = (obj) => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => obj });
window.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  fetchCalls.push({ url, method, body: options.body || null });
  if (url === "/api/diagnostics/interactions?limit=200") return jsonResponse({ interactions: FIXTURE_ENTRIES, count: 4, log_path: LOG_PATH, generated_at: "now" });
  if (url.startsWith("/api/diagnostics/interactions") && method === "DELETE") return jsonResponse({ deleted: 4 });
  if (url === "/api/diagnostics/report") return jsonResponse({ report: FIXTURE_REPORT, generated_at: "now" });
  if (url.startsWith("/api/diagnostics/client-error")) return jsonResponse({ recorded: true });
  if (typeof url === "string" && (url.startsWith("/api/agents") || url.startsWith("/api/conversations") || url.startsWith("/api/tasks") || url.startsWith("/api/memory") || url.startsWith("/api/agents/"))) return jsonResponse([]);
  return jsonResponse({});
};
Object.defineProperty(window.navigator, "clipboard", { value: { writeText: async (t) => { clipboard = t; return true; } }, configurable: true });
window.confirm = () => confirmAnswer;

// Execute the real client code exactly as a classic browser <script> would.
window.eval(appJs);

const results = [];
const check = (name, condition) => { results.push([name, !!condition]); console.log((condition ? "PASS" : "FAIL") + "  " + name); };
const flush = () => new Promise((r) => setTimeout(r, 80));

(async () => {
  await flush();
  const doc = window.document;

  // 1. Nav switches to the diagnostics view.
  doc.querySelector('[data-view="diagnostics"]').click();
  await flush();
  check("diagnostics view becomes active", doc.querySelector("#diagnosticsView").classList.contains("active"));
  check("page title becomes Diagnostics", doc.querySelector("#pageTitle").textContent === "Diagnostics");

  // 2. Entries render, with badges and error text.
  const rows = doc.querySelectorAll("#diagnosticList .diagnostic-row");
  check("4 rows render newest first", rows.length === 4 && rows[0].textContent.includes("/assets/app.js"));
  const badges = [...doc.querySelectorAll("#diagnosticList .diagnostic-kind")].map((el) => el.textContent);
  check("badges include OK/CLIENT/ASSET/ERROR", badges.includes("OK") && badges.includes("CLIENT") && badges.includes("ASSET") && badges.includes("ERROR"));
  check("error text rendered verbatim", doc.querySelector("#diagnosticList").innerHTML.includes("invalid literal for int() with base 10: &#39;abc&#39;") || doc.querySelector("#diagnosticList").textContent.includes("invalid literal for int()"));
  check("client-error detail rendered", doc.querySelector("#diagnosticList").textContent.includes("at render (app.js:1) next line"));

  // 3. Report preview is selectable and populated.
  check("report preview populated", doc.querySelector("#diagnosticsReport").value.includes("BabyMind diagnostics report"));
  check("report preview is readonly", doc.querySelector("#diagnosticsReport").readOnly === true);
  check("summary shows counts and full log path", doc.querySelector("#diagnosticsSummary").textContent.includes(LOG_PATH));

  // 4. Per-row Copy copies exactly one entry, report format.
  clipboard = "";
  const firstCopy = doc.querySelector(".diagnostic-row .diagnostic-copy");
  firstCopy.click();
  await flush();
  check("per-row copy yields one formatted entry", clipboard.includes("`GET /assets/app.js` → ERROR 404") && !clipboard.includes("diagnostics report"));

  // 5. Copy report copies the whole markdown report.
  clipboard = "";
  doc.querySelector("#copyReport").click();
  await flush();
  check("copy report yields full markdown", clipboard.startsWith("## BabyMind diagnostics report"));

  clipboard = "";
  doc.querySelector("#copyLogBottom").click();
  await flush();
  check("bottom Copy log button copies the full report", clipboard.startsWith("## BabyMind diagnostics report"));

  // 6. Copy log path copies the JSONL path.
  clipboard = "";
  doc.querySelector("#copyLogPath").click();
  await flush();
  check("copy log path yields path", clipboard === LOG_PATH);

  // 7. Clear log asks for confirmation and issues DELETE.
  confirmAnswer = true;
  doc.querySelector("#clearDiagnostics").click();
  await flush();
  const deleteCalls = fetchCalls.filter((c) => c.method === "DELETE" && c.url.startsWith("/api/diagnostics/interactions"));
  check("clear log issues DELETE /api/diagnostics/interactions", deleteCalls.length >= 1);

  // 8. Uncaught client errors are reported to the server.
  fetchCalls.length = 0;
  window.dispatchEvent(new window.ErrorEvent("error", { message: "TypeError: boom", error: new Error("boom") }));
  await flush();
  const clientErr = fetchCalls.find((c) => c.url === "/api/diagnostics/client-error");
  check("window error is posted to /api/diagnostics/client-error", !!clientErr && clientErr.body.includes("boom"));

  const failed = results.filter(([, ok]) => !ok);
  console.log("\n" + (results.length - failed.length) + "/" + results.length + " checks passed");
  process.exit(failed.length ? 1 : 0);
})().catch((err) => { console.error("TEST HARNESS ERROR:", err); process.exit(2); });
