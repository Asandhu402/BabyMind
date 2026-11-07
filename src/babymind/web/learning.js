/* Permanent autonomous self-improvement view.

   Loaded after app.js; reuses its $, api, toast and escapeHTML. This is a
   control surface for the supervised learning service, not an editor. Every
   action is a narrow POST to the local API; the server enforces the gates. */
(function () {
  "use strict";
  if (typeof window === "undefined") return;

  const el = (id) => document.getElementById(id);
  const text = (value) => String(value === null || value === undefined ? "" : value);
  let bound = false;

  function setHTML(id, html) {
    const node = el(id);
    if (node) node.innerHTML = html;
  }

  function statGrid(pairs) {
    return pairs
      .map(([label, value]) =>
        `<div class="self-stat"><span>${escapeHTML(label)}</span><strong>${escapeHTML(text(value))}</strong></div>`
      )
      .join("");
  }

  function emptyRow(message) {
    return `<div class="self-empty">${escapeHTML(message)}</div>`;
  }

  function gateValue(value) {
    if (value === true) return "pass";
    if (value === false) return "blocked";
    return text(value);
  }

  function renderStatus(status) {
    const state = text(status.state || "idle");
    const stop = !!status.stop_flag_present;
    const enabled = !!status.enabled && !!status.enabled_by_environment;
    setHTML("learningStateGrid", statGrid([
      ["State", state],
      ["Enabled", enabled && !stop ? "yes" : "no"],
      ["Process", status.process_running ? "running" : "not in this process"],
      ["Next cycle", status.next_due_at || "not scheduled"],
      ["Interval", `${text(status.interval_seconds || 0)} s`],
      ["Stop switch", stop ? "present" : "clear"],
      ["Last decision", status.last_decision || "none yet"],
      ["Errors in a row", status.consecutive_errors || 0],
    ]));
    const grid = el("learningStateGrid");
    if (grid) {
      grid.classList.toggle("is-running", state === "running" && enabled && !stop);
      grid.classList.toggle("is-halted", state === "halted" || stop || !enabled);
    }
    const badge = el("learningState");
    if (badge) badge.textContent = stop ? "stopped" : (enabled ? state : "off");
    const interval = el("learningInterval");
    if (interval && !interval.value) interval.value = text(status.interval_seconds || 1800);
    const detail = status.last_error || status.halted_reason || status.last_skip_reason
      || status.gate_reason || status.note || "The supervisor is idle and waiting for its next verified cycle.";
    setHTML("learningStatusText", escapeHTML(detail));
  }

  function renderGates(status) {
    const gates = status.gates || {};
    const checks = gates.checks || {};
    const labels = {
      enabled_by_environment: "Default-on environment flag",
      enabled_in_store: "Operator setting",
      stop_flag_present: "Kill switch clear",
      state: "Supervisor state",
      audit_chain_intact: "Audit chain intact",
      dev_available: "Developable checkout",
      selfdev_enabled: "Self-development enabled",
      sandbox_policy: "Fail-closed sandbox policy",
      sandbox_backend_available: "OS sandbox backend",
      desktop_session_active: "Standalone service idle while app is open",
    };
    const entries = Object.keys(checks).map((key) => {
      const value = checks[key];
      return `<div class="self-item"><div class="self-item-top"><span class="self-kind">${escapeHTML(labels[key] || key)}</span>` +
        `<span class="self-kind">${escapeHTML(gateValue(value))}</span></div></div>`;
    });
    setHTML("learningGates", entries.length ? entries.join("") : emptyRow("No gate report was returned."));
    setHTML("learningGateReason", gates.ready
      ? "All gates pass. A cycle can run when due."
      : escapeHTML((gates.reasons || []).join(" · ") || "A gate is closed."));
  }

  function renderCounts(status) {
    const decisions = status.decisions || {};
    setHTML("learningCounts", statGrid([
      ["Kept", decisions.kept || 0],
      ["Rolled back", decisions.rolled_back || 0],
      ["No change", decisions.no_change || 0],
      ["Failed", decisions.failed || 0],
      ["Skipped", decisions.skipped || 0],
      ["Total cycles", status.total_cycles || 0],
    ]));
  }

  function renderLessons(status) {
    const learning = status.learning || {};
    const lessons = learning.recent_lessons || [];
    setHTML("learningLessons", lessons.length
      ? lessons.map((lesson) => `<div class="self-item"><p>${escapeHTML(lesson)}</p></div>`).join("")
      : emptyRow("No lessons recorded yet. Completed cycles write concise lessons here."));
  }

  function renderRuns(data) {
    const chain = data.audit || {};
    const chainNode = el("learningChain");
    if (chainNode) {
      chainNode.textContent = chain.intact
        ? `chain intact · ${chain.entries || 0} entries`
        : `CHAIN BROKEN at entry ${chain.broken_at_seq || "?"}`;
      chainNode.classList.toggle("is-bad", !chain.intact);
    }
    const runs = data.runs || [];
    setHTML("learningRuns", runs.length
      ? runs.map((run) =>
          `<div class="audit-row"><span class="audit-seq">${escapeHTML(text(run.created_at)).slice(0, 10)}</span>` +
          `<span class="audit-kind">${escapeHTML(run.kind)}</span>` +
          `<span class="audit-detail">${escapeHTML(run.decision)} · ${escapeHTML(run.reason || run.error || "")}</span>` +
          `<code class="audit-hash">${escapeHTML(text(run.cycle_id)).slice(0, 10) || "—"}</code></div>`
        ).join("")
      : emptyRow("No autonomous cycles have been supervised yet."));
  }

  async function post(path, body) {
    return api(path, { method: "POST", body: JSON.stringify(body || {}) });
  }

  function bindControls() {
    if (bound) return;
    bound = true;
    const actions = [
      ["learningPause", "/api/learning/service/pause"],
      ["learningResume", "/api/learning/service/resume"],
      ["learningRunOnce", "/api/learning/service/run-once"],
      ["learningStop", "/api/learning/service/stop"],
      ["learningReset", "/api/learning/service/reset"],
      ["learningDisable", "/api/learning/service/disable"],
      ["learningEnable", "/api/learning/service/enable"],
    ];
    actions.forEach(([id, path]) => {
      const button = el(id);
      if (!button) return;
      button.addEventListener("click", async () => {
        try {
          button.disabled = true;
          await post(path, id === "learningStop" ? { reason: "Stopped from the Self-improvement view." } : {});
          toast("Learning service updated");
          await loadLearning();
        } catch (error) {
          toast(error.message);
        } finally {
          button.disabled = false;
        }
      });
    });
    const refresh = el("learningRefresh");
    if (refresh) refresh.addEventListener("click", () => loadLearning());
    const form = el("learningIntervalForm");
    if (form) form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const seconds = Number((el("learningInterval") || {}).value);
      if (!Number.isFinite(seconds) || seconds < 60 || seconds > 86400) {
        toast("Enter an interval between 60 and 86400 seconds.");
        return;
      }
      try {
        await post("/api/learning/service/interval", { seconds });
        toast("Learning interval updated");
        await loadLearning();
      } catch (error) {
        toast(error.message);
      }
    });
  }

  async function loadLearning() {
    bindControls();
    try {
      const status = await api("/api/learning/service");
      const runs = await api("/api/learning/runs?limit=20");
      renderStatus(status);
      renderGates(status);
      renderCounts(status);
      renderLessons(status);
      renderRuns(runs);
    } catch (error) {
      setHTML("learningStateGrid", emptyRow(`Could not load the learning service: ${error.message}`));
      setHTML("learningGates", emptyRow(error.message));
      setHTML("learningCounts", emptyRow(error.message));
      setHTML("learningLessons", emptyRow(error.message));
      setHTML("learningRuns", emptyRow(error.message));
    }
  }

  window.babymindLoadLearning = loadLearning;
})();
