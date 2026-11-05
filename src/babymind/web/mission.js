(() => {
  const $ = (selector) => document.querySelector(selector);
  const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  const brief = $("#missionBrief");
  const startButton = $("#startMission");
  const cancelButton = $("#cancelMission");
  const status = $("#missionStatus");
  const bar = $("#missionBar");
  const counts = $("#missionCounts");
  const agentList = $("#missionAgents");
  const agentSummary = $("#missionAgentSummary");
  const selfdevStatus = $("#selfdevStatus");
  const checkpointList = $("#checkpointList");
  const upgradeStatus = $("#upgradeStatus");
  if (!brief || !startButton) return;

  let poller = null;
  let currentMission = null;

  async function api(path, options = {}, retried = false) {
    const token = localStorage.getItem("babymind_access_token") || "";
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-BabyMind-Token": token } : {}),
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({ error: "Unexpected server response" }));
    if (response.status === 401 && !retried) {
      const entered = prompt("Enter the one-time BabyMind access token shown in the console on your PC:");
      if (!entered) throw new Error("Access token is required for this BabyMind server.");
      localStorage.setItem("babymind_access_token", entered.trim());
      return api(path, options, true);
    }
    if (!response.ok && response.status !== 200) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  const STATUS_CLASS = {
    contributed: "ok", error: "bad", deferred: "warn", pending: "idle",
  };

  function renderCounts(mission) {
    const map = mission.counts || {};
    const recorded = mission.agents_recorded || 0;
    const pct = Math.round((recorded / 50) * 100);
    if (bar) bar.style.width = pct + "%";
    if (counts) {
      counts.innerHTML = [
        ["recorded", recorded],
        ["returned text", map.contributed || 0],
        ["errors", map.error || 0],
        ["deferred", map.deferred || 0],
      ].map(([label, value]) => `<span><strong>${value}</strong> ${label}</span>`).join("");
    }
    if (agentSummary) agentSummary.textContent = mission.status === "running" ? `${recorded}/50 roles recorded` : `Mission ${mission.status}`;
  }

  function renderAgents(mission) {
    if (!agentList) return;
    if (!mission || !mission.runs || !mission.runs.length) {
      agentList.innerHTML = '<div class="empty-state">No roles have reported yet.</div>';
      return;
    }
    agentList.innerHTML = mission.runs.map((run) => `
      <details class="agent-run ${STATUS_CLASS[run.status] || "idle"}">
        <summary><span class="run-id">${escapeHTML(run.agent_id)}</span>
        <span class="run-name">${escapeHTML(run.agent_name)}</span>
        <span class="run-phase">${escapeHTML(run.phase)}</span>
        <span class="run-status">${escapeHTML(run.status)}</span>
        <span class="run-time">${run.seconds}s</span></summary>
        <p>${escapeHTML(run.output || run.error || "No output recorded.")}</p>
      </details>`).join("");
  }

  async function poll(missionId) {
    try {
      const mission = await api(`/api/missions/${encodeURIComponent(missionId)}`);
      currentMission = mission;
      renderCounts(mission);
      renderAgents(mission);
      let line = mission.status === "running"
        ? `Running · ${mission.agents_recorded}/50 roles recorded`
        : `${mission.status.toUpperCase()} · ${mission.summary || ""}`;
      if (mission.self_edit) {
        const edit = mission.self_edit;
        const tries = edit.attempts ? ` after ${edit.attempts} attempt(s)` : "";
        line += `\nSelf-edit: ${edit.status}${tries} — ${edit.detail || ""}`;
      }
      status.textContent = line;
      if (mission.status !== "running") {
        clearInterval(poller);
        poller = null;
        startButton.disabled = false;
        cancelButton.disabled = true;
      }
    } catch (error) {
      status.textContent = error.message;
      clearInterval(poller);
      poller = null;
      startButton.disabled = false;
      cancelButton.disabled = true;
    }
  }

  startButton.addEventListener("click", async () => {
    const text = brief.value.trim();
    if (text.length < 8) { status.textContent = "Describe the mission in a few words first."; return; }
    startButton.disabled = true;
    status.textContent = "Queuing all 50 roles…";
    try {
      const selfEdit = Boolean($("#missionSelfEdit") && $("#missionSelfEdit").checked);
      const created = await api("/api/missions", {
        method: "POST",
        body: JSON.stringify({ brief: text, self_edit: selfEdit }),
      });
      cancelButton.disabled = false;
      status.textContent = `Running · mission ${created.id}`;
      clearInterval(poller);
      poller = setInterval(() => poll(created.id), 1500);
      poll(created.id);
    } catch (error) {
      status.textContent = error.message;
      startButton.disabled = false;
    }
  });

  cancelButton.addEventListener("click", async () => {
    if (!currentMission) return;
    try {
      await api(`/api/missions/${encodeURIComponent(currentMission.id)}/cancel`, { method: "POST", body: "{}" });
      status.textContent = "Cancellation requested; recorded roles are kept.";
    } catch (error) { status.textContent = error.message; }
  });

  async function loadSelfDev() {
    try {
      const report = await api("/api/dev/status");
      const box = report.sandbox || {};
      const isolation = box.available
        ? `Verification runs in the ${box.backend} sandbox (no network, system files read-only).`
        : `No OS sandbox on this platform (${box.detail || "backend unavailable"}); results say so.`;
      const scope = report.source_scope === "staged-copy"
        ? "Staged source only: changes do not update the running packaged app. " : "";
      selfdevStatus.textContent = report.enabled
        ? `Enabled · ${report.root} · ${scope}changes are checkpointed, compiled, tested and auto-rolled back on failure. ${isolation} Audit log ${report.audit.valid ? "intact" : "BROKEN"}.`
        : `Disabled${report.problem ? " · " + report.problem : ""}. Set BABYMIND_SELF_DEVELOPMENT_ENABLED=true in a source checkout.`;
      checkpointList.innerHTML = (report.checkpoints || []).map((item) =>
        `<div class="checkpoint-row"><span><strong>${escapeHTML(item.label || item.id)}</strong><small>${escapeHTML(item.created_at || "")} · ${item.file_count} files</small></span>
         <button class="task-refresh" data-rollback="${escapeHTML(item.id)}" type="button">Roll back</button></div>`).join("");
      checkpointList.querySelectorAll("[data-rollback]").forEach((button) => {
        button.addEventListener("click", async () => {
          if (!confirm("Restore this checkpoint? Files created after it are removed.")) return;
          try {
            const result = await api("/api/dev/rollback", { method: "POST", body: JSON.stringify({ checkpoint_id: button.dataset.rollback }) });
            selfdevStatus.textContent = `Rolled back ${result.restored_files.length} file(s).`;
            loadSelfDev();
          } catch (error) { selfdevStatus.textContent = error.message; }
        });
      });
    } catch (error) {
      selfdevStatus.textContent = error.message;
    }
  }

  $("#runTests")?.addEventListener("click", async () => {
    const output = $("#testOutput");
    output.hidden = false;
    output.textContent = "Running the project's test suite…";
    try {
      const result = await api("/api/dev/tests", { method: "POST", body: "{}" });
      const summary = result.summary || {};
      output.textContent = `Ran ${summary.ran || 0} tests · failures ${summary.failures || 0} · errors ${summary.errors || 0} · ${result.seconds}s\n\n`
        + (result.stdout || "") + (result.stderr || "");
    } catch (error) { output.textContent = error.message; }
  });

  $("#previewEdit")?.addEventListener("click", async () => {
    const diff = $("#devDiff");
    const path = $("#devPath").value.trim();
    const content = $("#devContent").value;
    if (!path) { diff.hidden = false; diff.textContent = "Enter a project-relative path."; return; }
    try {
      const result = await api("/api/dev/preview", { method: "POST", body: JSON.stringify({ edits: [{ path, content }] }) });
      diff.hidden = false;
      diff.textContent = result.files.map((file) => file.diff || "(new file)").join("\n\n") || "No changes.";
    } catch (error) { diff.hidden = false; diff.textContent = error.message; }
  });

  $("#applyEdit")?.addEventListener("click", async () => {
    const path = $("#devPath").value.trim();
    const content = $("#devContent").value;
    const reason = $("#devReason").value.trim();
    const resultBox = $("#devResult");
    if (!path) { resultBox.hidden = false; resultBox.textContent = "Enter a project-relative path."; return; }
    if (!confirm(`Apply this change to ${path}? BabyMind will checkpoint, compile, and run the full test suite, then roll back automatically if anything fails.`)) return;
    resultBox.hidden = false;
    resultBox.textContent = "Applying, compiling, and testing…";
    try {
      const result = await api("/api/dev/apply", {
        method: "POST",
        body: JSON.stringify({ edits: [{ path, content }], reason }),
      });
      const tests = result.tests && result.tests.summary;
      resultBox.textContent = [
        `Status: ${result.status}`,
        result.reason ? `Reason: ${result.reason}` : "",
        `Checkpoint: ${result.checkpoint_id}`,
        tests ? `Tests: ran ${tests.ran}, failures ${tests.failures}, errors ${tests.errors}` : "Tests: not run",
        result.notice || "",
      ].filter(Boolean).join("\n");
      loadSelfDev();
    } catch (error) { resultBox.textContent = error.message; }
  });

  $("#previewWindow")?.addEventListener("click", async () => {
    const button = $("#previewWindow");
    button.disabled = true;
    upgradeStatus.textContent = "Starting a preview window with the current (possibly patched) source…";
    try {
      const result = await api("/api/dev/preview-window", { method: "POST", body: "{}" });
      upgradeStatus.textContent = `Preview window running at ${result.url} (separate data folder; the running app is unchanged).`;
      window.open(result.url, "_blank", "noopener");
    } catch (error) { upgradeStatus.textContent = error.message; }
    finally { button.disabled = false; }
  });

  $("#previewStop")?.addEventListener("click", async () => {
    try {
      const result = await api("/api/dev/preview-window/stop", { method: "POST", body: "{}" });
      upgradeStatus.textContent = result.notice;
    } catch (error) { upgradeStatus.textContent = error.message; }
  });

  $("#upgradeApp")?.addEventListener("click", async () => {
    const confirmation = $("#upgradeConfirmation").value.trim();
    if (confirmation !== "UPGRADE BABYMIND") { upgradeStatus.textContent = "Type UPGRADE BABYMIND to confirm."; return; }
    if (!confirm("Copy the checkpointed, tested staged source into the downloaded package's source code? A backup of the original is kept. The running app is not modified; restart BabyMind afterwards.")) return;
    const button = $("#upgradeApp");
    button.disabled = true;
    upgradeStatus.textContent = "Upgrading the downloaded source seed…";
    try {
      const result = await api("/api/dev/upgrade", { method: "POST", body: JSON.stringify({ confirmation }) });
      upgradeStatus.textContent = result.notice + (result.backup ? ` Backup: ${result.backup}` : "");
      if (result.upgraded) $("#upgradeConfirmation").value = "";
      loadSelfDev();
    } catch (error) { upgradeStatus.textContent = error.message; }
    finally { button.disabled = false; }
  });

  window.babymindLoadMission = function loadMissionView() {
    loadSelfDev();
    if (currentMission) poll(currentMission.id);
  };

  api("/api/agents/activity").then((stats) => {
    if (agentSummary && !currentMission) {
      const runs = stats.reduce((total, item) => total + item.runs, 0);
      agentSummary.textContent = `${stats.length} roles registered · ${runs} recorded contributions`;
    }
  }).catch(() => {});

  loadSelfDev();
})();
