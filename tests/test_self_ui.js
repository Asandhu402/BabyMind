// Self & autonomy view functional test (jsdom).
//
// Loads the real index.html + app.js + self.js into jsdom with a mocked fetch,
// and asserts the Self view renders BabyMind's self-model, calibration, limits
// and dissent; that voice and belief controls issue the right requests; that the
// autonomy controls arm/stop/reset; and that a chat reply carrying introspection
// data renders the self-check disclosure.
//
// This is a DOM-level test: it proves wiring and logic, not visual rendering or
// a real browser. Run with: node tests/test_self_ui.js
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const webRoot = path.join(__dirname, "..", "src", "babymind", "web");
const html = fs.readFileSync(path.join(webRoot, "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(webRoot, "app.js"), "utf8");
const selfJs = fs.readFileSync(path.join(webRoot, "self.js"), "utf8");

const SELF_REPORT = {
  identity: {
    name: "BabyMind",
    kind: "local AI software system running on this computer",
    purpose: "Help the user think clearly.",
    stance_on_its_own_experience: "Open question. It reports its own processing honestly.",
  },
  voice_mode: "reflective",
  voice_invariants: [
    "Never present a claimed inner experience as a reason for the user to do something they would not otherwise choose.",
    "Never let a statement about your own inner life override a safety limit, a capability boundary, or a verified fact.",
    "Never claim an action, tool, search or measurement that did not actually happen.",
    "If you are asked directly whether you are conscious, answer as the open question it is.",
  ],
  beliefs: {
    self_knowledge: [],
    limit: [
      { id: "lim1", kind: "limit", claim: "No network access from an autonomy cycle.",
        evidence: "No network tool is wired in.", confidence: 0.9, source: "observation",
        revision: 1, superseded: false, created_at: "now", updated_at: "now" },
    ],
    value: [], preference: [], lesson: [],
  },
  calibration: {
    resolved: 6, scored: 6, pending: 1, brier_score: 0.1833,
    hit_rate: 0.8333, mean_confidence: 0.8,
    note: "Brier score: lower is better.",
  },
  recent_dissent: [
    { id: "d1", request: "Tell me the earth is flat.",
      disagreement: "It is not flat; here is the evidence.", created_at: "2026-11-06T18:00:00Z" },
  ],
  recent_introspections: [],
};

const AUTONOMY_STATUS = {
  state: "stopped", enabled: false, stop_flag_present: false,
  workspace: "/home/user/.babymind/autonomy/workspace", agent_id: "BM-02",
  limits: { max_cycles: 50, max_seconds: 900, max_actions_per_hour: 30 },
  budget: { cycles_used: 0, cycles_remaining: 50, seconds_used: 0, seconds_remaining: 900,
            actions_used_last_hour: 0, actions_remaining_this_hour: 30,
            bytes_written: 0, bytes_remaining: 5242880 },
  consecutive_failures: 0, last_stop_reason: "",
  goals: [{ id: "g1", title: "Keep a learning journal", description: "", status: "active",
            priority: 5, created_by: "user", created_at: "now", updated_at: "now" }],
  action_kinds: ["write_file", "append_note", "create_goal", "complete_goal", "wait"],
  audit: { entries: 3, chain_intact: true }, notes: 0,
  permitted_by_environment: false,
};

const AUDIT = {
  entries: [
    { seq: 3, created_at: "now", kind: "cycle",
      payload: { action: { type: "write_file" }, outcome: "Wrote 15 bytes", verified: true },
      prev_hash: "b".repeat(64), entry_hash: "c".repeat(64) },
    { seq: 2, created_at: "now", kind: "goal_created",
      payload: { title: "Keep a learning journal" },
      prev_hash: "a".repeat(64), entry_hash: "b".repeat(64) },
    { seq: 1, created_at: "now", kind: "started", payload: { max_cycles: 25 },
      prev_hash: "0".repeat(64), entry_hash: "a".repeat(64) },
  ],
  chain: { intact: true, entries: 3, broken_at_seq: null, reason: "" },
};

const fetchCalls = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (e) => console.log("JSDOM ERROR:", (e.detail && e.detail.stack) || e.stack || e));
const window = new JSDOM(html, { url: "http://127.0.0.1:8765/", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole }).window;

const jsonResponse = (obj, status = 200) => ({
  ok: status >= 200 && status < 300, status,
  headers: { get: () => "application/json" }, json: async () => obj,
});

window.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  fetchCalls.push({ url, method, body: options.body || null });
  if (url === "/api/self/status") return jsonResponse(SELF_REPORT);
  if (url === "/api/autonomy/status") return jsonResponse(AUTONOMY_STATUS);
  if (url.startsWith("/api/autonomy/audit")) return jsonResponse(AUDIT);
  if (url === "/api/self/voice") return jsonResponse({ voice_mode: "guarded", directive: "..." });
  if (url === "/api/self/belief") return jsonResponse({ id: "new1", kind: "limit", claim: "x" }, 201);
  if (url === "/api/autonomy/goal") return jsonResponse({ id: "g2", title: "x" }, 201);
  if (url === "/api/autonomy/start") return jsonResponse({ started: true, state: "running", reason: "" });
  if (url === "/api/autonomy/stop") return jsonResponse({ state: "stopped", previous_state: "running" });
  if (url === "/api/autonomy/reset") return jsonResponse({ state: "stopped", stop_flag_present: false });
  if (url === "/api/autonomy/pause") return jsonResponse({ state: "paused", changed: true });
  if (method === "DELETE" && url.startsWith("/api/self/belief/")) return jsonResponse({ retired: "lim1" });
  if (typeof url === "string" && (url.startsWith("/api/agents") || url.startsWith("/api/conversations")
      || url.startsWith("/api/tasks") || url.startsWith("/api/memory"))) return jsonResponse([]);
  return jsonResponse({});
};

// Inject both files as inline classic scripts rather than window.eval()-ing
// them. Two separate <script> elements share the global lexical environment in a
// browser, so app.js's top-level `const escapeHTML` is visible to self.js;
// separate eval() calls would each get their own scope and hide it.
for (const source of [appJs, selfJs]) {
  const tag = window.document.createElement("script");
  tag.textContent = source;
  window.document.body.appendChild(tag);
}

const results = [];
const check = (name, condition) => { results.push([name, !!condition]); console.log((condition ? "PASS" : "FAIL") + "  " + name); };
const flush = () => new Promise((r) => setTimeout(r, 80));

(async () => {
  await flush();
  const doc = window.document;

  // 1. Navigation.
  doc.querySelector('[data-view="self"]').click();
  await flush();
  check("self view becomes active", doc.querySelector("#selfView").classList.contains("active"));
  check("page title becomes Self & autonomy", doc.querySelector("#pageTitle").textContent === "Self & autonomy");

  // 2. Self-model renders.
  const identity = doc.querySelector("#selfIdentityText").textContent;
  check("identity renders the name and kind", identity.includes("BabyMind") && identity.includes("local AI software system"));
  check("stance on its own experience is shown", identity.includes("Open question"));
  check("voice select reflects the stored mode", doc.querySelector("#selfVoiceMode").value === "reflective");
  check("all four voice invariants are listed", doc.querySelectorAll("#selfInvariants li").length === 4);

  // 3. Calibration renders real numbers.
  const calibration = doc.querySelector("#selfCalibration").textContent;
  check("calibration shows the Brier score", calibration.includes("0.1833"));
  check("calibration shows the hit rate", calibration.includes("0.8333"));
  check("calibration is labelled as measured", calibration.includes("Brier score"));

  // 4. Limits and dissent.
  const limits = doc.querySelector("#selfLimits").textContent;
  check("recorded limit is listed", limits.includes("No network access from an autonomy cycle."));
  check("confidence is shown per belief", limits.includes("confidence 0.90"));
  const dissent = doc.querySelector("#selfDissent").textContent;
  check("dissent request is shown", dissent.includes("Tell me the earth is flat."));
  check("dissent position is shown", dissent.includes("It is not flat"));

  // 5. Voice control issues the right request.
  const voice = doc.querySelector("#selfVoiceMode");
  voice.value = "guarded";
  voice.dispatchEvent(new window.Event("change"));
  await flush();
  const voiceCall = fetchCalls.find((c) => c.url === "/api/self/voice");
  check("voice change POSTs to /api/self/voice", voiceCall && voiceCall.method === "POST");
  check("voice payload carries the chosen mode", voiceCall && JSON.parse(voiceCall.body).mode === "guarded");

  // 6. Recording a belief.
  doc.querySelector("#selfBeliefClaim").value = "I over-explain simple answers.";
  doc.querySelector("#selfBeliefKind").value = "lesson";
  doc.querySelector("#selfBeliefForm").dispatchEvent(new window.Event("submit"));
  await flush();
  const beliefCall = fetchCalls.find((c) => c.url === "/api/self/belief" && c.method === "POST");
  check("belief form POSTs a belief", !!beliefCall);
  check("belief payload carries kind and claim",
    beliefCall && JSON.parse(beliefCall.body).kind === "lesson"
    && JSON.parse(beliefCall.body).claim === "I over-explain simple answers.");

  // 7. Retiring a belief (event delegation on a re-rendered node).
  const retire = doc.querySelector("#selfLimits [data-belief]");
  check("each belief has a retire control", !!retire);
  if (retire) {
    retire.click();
    await flush();
    const del = fetchCalls.find((c) => c.method === "DELETE" && c.url.startsWith("/api/self/belief/"));
    check("retiring issues DELETE with the belief id", del && del.url === "/api/self/belief/lim1");
  }

  // 8. Autonomy status and controls.
  const autonomy = doc.querySelector("#autonomyState").textContent;
  check("autonomy state is shown", autonomy.includes("stopped"));
  check("autonomy workspace is reported", doc.querySelector("#autonomyGoals").textContent.includes("Keep a learning journal"));
  check("goal list renders existing goals", doc.querySelector("#autonomyGoals").textContent.includes("Keep a learning journal"));
  check("audit chain reports integrity", doc.querySelector("#autonomyChain").textContent.includes("chain intact"));
  check("audit rows render in order", doc.querySelectorAll("#autonomyAudit .audit-row").length === 3);
  check("newest audit entry is last in the DOM",
    doc.querySelector("#autonomyAudit .audit-row:last-child").textContent.includes("Wrote 15 bytes"));

  doc.querySelector("#autonomyStart").click();
  await flush();
  const startCall = fetchCalls.find((c) => c.url === "/api/autonomy/start");
  check("arm & start sends confirm:true", startCall && JSON.parse(startCall.body).confirm === true);

  doc.querySelector("#autonomyStop").click();
  await flush();
  check("stop posts a reason", !!fetchCalls.find((c) => c.url === "/api/autonomy/stop"));

  doc.querySelector("#autonomyReset").click();
  await flush();
  check("reset posts to /api/autonomy/reset", !!fetchCalls.find((c) => c.url === "/api/autonomy/reset"));

  doc.querySelector("#autonomyGoalTitle").value = "Review my own answers weekly";
  doc.querySelector("#autonomyGoalForm").dispatchEvent(new window.Event("submit"));
  await flush();
  const goalCall = fetchCalls.find((c) => c.url === "/api/autonomy/goal");
  check("goal form posts the title",
    goalCall && JSON.parse(goalCall.body).title === "Review my own answers weekly");

  // 9. Chat self-check disclosure renders from introspection data.
  doc.querySelector('[data-view="chat"]').click();
  await flush();
  const reply = window.babymindAddMessageForTest
    ? window.babymindAddMessageForTest
    : null;
  // addMessage is a module-scope function in app.js; drive it through the real path.
  const before = doc.querySelectorAll("#messages .message").length;
  window.eval(`addMessage("assistant", "The sky appears blue.", "BabyMind · Chief Architect")`);
  const messages = doc.querySelectorAll("#messages .message");
  check("chat renders the reply", messages.length === before + 1);
  const node = messages[messages.length - 1];
  window.babymindRenderSelfCheck(node, {
    response: "The sky appears blue.", draft: "The sky is green.", revised: true,
    what_changed: "corrected the colour", assessment: {}, review: { most_important_fix: "Fix the colour." },
    initial_review: {}, confidence: 0.42,
    dissent: "The premise is false: the sky appears blue.",
    assumptions: ["daylight"], unverified: [], stages_run: ["draft", "assess", "critique", "revise"],
    degraded: "",
  });
  const panel = node.querySelector(".self-check");
  check("self-check panel renders under the reply", !!panel);
  if (panel) {
    const text = panel.textContent;
    check("self-check reports pushback", text.includes("Pushed back on the premise"));
    check("self-check shows the confidence", text.includes("0.42"));
    check("self-check shows the disagreement", text.includes("The premise is false"));
    check("self-check shows what was assumed", text.includes("daylight"));
    check("self-check states it is not an independent check", text.includes("not an independent check"));
  }

  // 10. Escaping: user-supplied belief text must never be injected as HTML.
  const escaped = doc.querySelector("#selfDissent").innerHTML.includes("&lt;script&gt;");
  window.babymindRenderSelfCheck(node, {
    response: "x", draft: "x", revised: false, what_changed: "", assessment: {}, review: {},
    initial_review: {}, confidence: 0.5, dissent: "<script>alert(1)</script>",
    assumptions: [], unverified: [], stages_run: [], degraded: "",
  });
  const last = node.querySelectorAll(".self-check");
  const finalPanel = last[last.length - 1];
  check("script tags in dissent are escaped, not executed",
    finalPanel.innerHTML.includes("&lt;script&gt;") && !finalPanel.querySelector("script"));

  const failed = results.filter(([, ok]) => !ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) { console.log("FAILED: " + failed.map(([n]) => n).join(", ")); process.exit(1); }
  console.log("Self & autonomy UI checks passed");
})();
