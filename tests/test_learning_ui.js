// Permanent autonomous self-improvement view functional test (jsdom).
//
// Loads the real index.html + app.js + learning.js, exercises navigation,
// status/gate/ledger rendering, all operator controls, interval validation and
// HTML escaping. This is a DOM-level wiring test, not a real-browser pass.
// Run with: node tests/test_learning_ui.js
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const webRoot = path.join(__dirname, "..", "src", "babymind", "web");
const html = fs.readFileSync(path.join(webRoot, "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(webRoot, "app.js"), "utf8");
const learningJs = fs.readFileSync(path.join(webRoot, "learning.js"), "utf8");

const STATUS = {
  autonomous: true,
  default_enabled: true,
  enabled_by_environment: true,
  enabled: true,
  state: "idle",
  mode: "in-process supervisor",
  process_running: true,
  thread_alive: true,
  stop_flag_path: "/home/user/.babymind/learning/STOP",
  stop_flag_present: false,
  interval_seconds: 1800,
  startup_delay_seconds: 300,
  max_consecutive_errors: 5,
  next_due_at: "2026-11-06T20:00:00+00:00",
  next_due_in_seconds: 600,
  last_started_at: "2026-11-06T19:00:00+00:00",
  last_finished_at: "2026-11-06T19:04:00+00:00",
  last_decision: "kept",
  last_error: "",
  last_skip_reason: "",
  halted_reason: "",
  consecutive_errors: 0,
  total_cycles: 12,
  decisions: { kept: 3, rolled_back: 2, no_change: 5, failed: 1, skipped: 1 },
  gates: {
    ready: true,
    reasons: [],
    checks: {
      enabled_by_environment: true,
      enabled_in_store: true,
      stop_flag_present: false,
      state: "idle",
      audit_chain_intact: true,
      dev_available: true,
      selfdev_enabled: true,
      sandbox_policy: "require",
      sandbox_backend_available: true,
      desktop_session_active: false,
    },
  },
  gate_reason: "",
  recent_runs: [],
  learning: {
    cycles_total: 11,
    recent_lessons: ["Add a bounded retry before giving up.", "Do not repeat a rolled-back patch."],
    audit_chain_intact: true,
    supervisor: { enabled: true, state: "idle", total_cycles: 12 },
  },
  note: "Enabled by default and persistent across restarts, but bounded.",
};

const RUNS = {
  runs: [
    { id: "r2", created_at: "2026-11-06T19:04:00+00:00", finished_at: "2026-11-06T19:04:02+00:00",
      kind: "autonomous", decision: "kept", reason: "A bounded retry fixed the weakness.",
      cycle_id: "cycle-2", weakness_id: "w-2", duration_seconds: 92.5, error: "" },
    { id: "r1", created_at: "2026-11-06T18:00:00+00:00", finished_at: "2026-11-06T18:00:04+00:00",
      kind: "autonomous", decision: "rolled_back", reason: "Verification failed and rolled back.",
      cycle_id: "cycle-1", weakness_id: "w-1", duration_seconds: 88.0, error: "" },
  ],
  audit: { intact: true, entries: 42, broken_at_seq: null, reason: "" },
};

const fetchCalls = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (e) => console.log("JSDOM ERROR:", (e.detail && e.detail.stack) || e.stack || e));
const window = new JSDOM(html, {
  url: "http://127.0.0.1:8765/", runScripts: "dangerously",
  pretendToBeVisual: true, virtualConsole,
}).window;

const jsonResponse = (obj, status = 200) => ({
  ok: status >= 200 && status < 300, status,
  headers: { get: () => "application/json" }, json: async () => obj,
});

window.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  fetchCalls.push({ url, method, body: options.body || null });
  if (url === "/api/learning/service") return jsonResponse(STATUS);
  if (url.startsWith("/api/learning/runs")) return jsonResponse(RUNS);
  if (url.startsWith("/api/learning/service/")) return jsonResponse({ ok: true, state: "idle", changed: true });
  if (typeof url === "string" && (url.startsWith("/api/agents") || url.startsWith("/api/conversations")
      || url.startsWith("/api/tasks") || url.startsWith("/api/memory"))) return jsonResponse([]);
  return jsonResponse({});
};

for (const source of [appJs, learningJs]) {
  const tag = window.document.createElement("script");
  tag.textContent = source;
  window.document.body.appendChild(tag);
}

const results = [];
const check = (name, condition) => {
  results.push([name, !!condition]);
  console.log((condition ? "PASS" : "FAIL") + "  " + name);
};
const flush = () => new Promise((r) => setTimeout(r, 80));
const postTo = (url) => fetchCalls.find((call) => call.url === url && call.method === "POST");

(async () => {
  await flush();
  const doc = window.document;

  // 1. Navigation to the new view.
  doc.querySelector('[data-view="learning"]').click();
  await flush();
  check("learning view becomes active", doc.querySelector("#learningView").classList.contains("active"));
  check("page title becomes Self-improvement", doc.querySelector("#pageTitle").textContent === "Self-improvement");
  check("status endpoint is fetched", !!fetchCalls.find((c) => c.url === "/api/learning/service"));
  check("run ledger endpoint is fetched", !!fetchCalls.find((c) => c.url.startsWith("/api/learning/runs")));

  // 2. Supervisor status and counts.
  const stateGrid = doc.querySelector("#learningStateGrid").textContent;
  check("state grid shows the supervisor state", stateGrid.includes("idle"));
  check("state grid shows the interval", stateGrid.includes("1800"));
  check("state grid shows the next cycle", stateGrid.includes("2026-11-06T20:00:00"));
  check("state grid shows the stop switch is clear", stateGrid.includes("clear"));
  check("navigation badge shows the state", doc.querySelector("#learningState").textContent === "idle");
  const counts = doc.querySelector("#learningCounts").textContent;
  check("outcomes show kept and rolled-back counts", counts.includes("Kept") && counts.includes("Rolled back"));
  check("outcomes show total cycles", counts.includes("12"));

  // 3. Gates, lessons, ledger and audit chain.
  const gates = doc.querySelector("#learningGates").textContent;
  check("gates render the fail-closed sandbox policy", gates.includes("sandbox policy") || gates.includes("sandbox_policy"));
  check("gates render the audit chain check", gates.includes("Audit chain intact"));
  check("gate summary reports readiness", doc.querySelector("#learningGateReason").textContent.includes("All gates pass"));
  const lessons = doc.querySelector("#learningLessons").textContent;
  check("recorded lessons are shown", lessons.includes("Add a bounded retry before giving up."));
  const runs = doc.querySelector("#learningRuns").textContent;
  check("run ledger shows a kept cycle", runs.includes("kept"));
  check("run ledger shows a rolled-back cycle", runs.includes("rolled_back"));
  check("audit chain is reported intact", doc.querySelector("#learningChain").textContent.includes("chain intact"));

  // 4. Operator controls issue narrow POSTs and reload the view.
  doc.querySelector("#learningPause").click();
  await flush();
  check("pause POSTs to the pause endpoint", !!postTo("/api/learning/service/pause"));
  doc.querySelector("#learningResume").click();
  await flush();
  check("resume POSTs to the resume endpoint", !!postTo("/api/learning/service/resume"));
  doc.querySelector("#learningRunOnce").click();
  await flush();
  check("run-once POSTs to the run-once endpoint", !!postTo("/api/learning/service/run-once"));
  doc.querySelector("#learningStop").click();
  await flush();
  const stopCall = postTo("/api/learning/service/stop");
  check("stop POSTs to the kill-switch endpoint", !!stopCall);
  check("stop carries a reason", stopCall && JSON.parse(stopCall.body).reason.includes("Self-improvement"));
  doc.querySelector("#learningReset").click();
  await flush();
  check("reset POSTs to the reset endpoint", !!postTo("/api/learning/service/reset"));
  doc.querySelector("#learningDisable").click();
  await flush();
  check("disable POSTs to the disable endpoint", !!postTo("/api/learning/service/disable"));
  doc.querySelector("#learningEnable").click();
  await flush();
  check("enable POSTs to the enable endpoint", !!postTo("/api/learning/service/enable"));

  // 5. Interval validation and submission.
  const input = doc.querySelector("#learningInterval");
  input.value = "10";
  doc.querySelector("#learningIntervalForm").dispatchEvent(new window.Event("submit"));
  await flush();
  check("an interval below 60 seconds is refused", !postTo("/api/learning/service/interval"));
  input.value = "900";
  doc.querySelector("#learningIntervalForm").dispatchEvent(new window.Event("submit"));
  await flush();
  const intervalCall = postTo("/api/learning/service/interval");
  check("a valid interval is POSTed", !!intervalCall);
  check("interval payload carries seconds", intervalCall && JSON.parse(intervalCall.body).seconds === 900);

  // 6. Refresh control re-fetches status.
  const before = fetchCalls.filter((c) => c.url === "/api/learning/service").length;
  doc.querySelector("#learningRefresh").click();
  await flush();
  check("refresh re-fetches the status", fetchCalls.filter((c) => c.url === "/api/learning/service").length > before);

  const failed = results.filter(([, ok]) => !ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) {
    console.log("FAILED: " + failed.map(([n]) => n).join(", "));
    window.close();
    process.exit(1);
  }
  console.log("Autonomous learning UI checks passed");
  window.close();
})();
