(() => {
  const $ = (selector) => document.querySelector(selector);
  const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  const brief = $("#builderBrief");
  const nameInput = $("#builderName");
  const planButton = $("#builderPlan");
  const approveButton = $("#builderApprove");
  const status = $("#builderStatus");
  const planBox = $("#builderPlanBox");
  const planName = $("#builderPlanName");
  const fileList = $("#builderFiles");
  const target = $("#builderTarget");
  const output = $("#builderOutput");
  if (!brief || !planButton) return;

  let plan = null;
  let ready = false;

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
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  function renderStatus() {
    if (!ready) {
      planButton.disabled = true;
      approveButton.disabled = true;
      return;
    }
    planButton.disabled = false;
    approveButton.disabled = !plan;
  }

  function renderPlan(result) {
    plan = result;
    planBox.hidden = false;
    output.hidden = true;
    planName.textContent = `${result.name} · ${result.files.length} file${result.files.length === 1 ? "" : "s"} · ${result.total_bytes} bytes`;
    fileList.innerHTML = result.files.map((file) =>
      `<li><code>${escapeHTML(file.path)}</code> <span>${file.bytes} B · ${file.lines} lines</span>
       <details><summary>preview</summary><pre>${escapeHTML(file.preview)}</pre></details></li>`).join("");
    target.textContent = `Writes to ${result.target}${result.will_run ? ` then runs ${result.entry} once` : " (static files, nothing runs)"}`;
    target.dataset.planId = result.plan_id;
    target.dataset.planHash = result.plan_hash;
    status.textContent = result.notice;
    renderStatus();
  }

  function renderRun(result) {
    const run = result.run || {};
    const lines = [`Created ${result.files.length} file(s) in ${result.target}`];
    if (run.ran) {
      lines.push("");
      lines.push(`$ ${run.command}`);
      lines.push(run.timed_out ? `(stopped after the time limit)` : `exit code ${run.exit_code} in ${run.seconds}s`);
      if (run.stdout) lines.push("", "stdout:", run.stdout.trim());
      if (run.stderr) lines.push("", "stderr:", run.stderr.trim());
    } else {
      lines.push("", run.reason || "Nothing was executed.");
    }
    output.textContent = lines.join("\n");
    output.hidden = false;
    output.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function loadStatus() {
    try {
      const result = await api("/api/builder/status");
      ready = Boolean(result.ready);
      if (result.ready) {
        status.textContent = `Ready · apps folder: ${result.apps_folder}. ${result.notice}`;
      } else if (result.enabled && result.problem) {
        status.textContent = result.problem;
      } else {
        status.textContent = `Disabled. ${result.setup}`;
      }
    } catch (error) {
      ready = false;
      status.textContent = error.message;
    }
    renderStatus();
  }

  planButton.addEventListener("click", async () => {
    const text = brief.value.trim();
    if (text.length < 3) { status.textContent = "Describe the app you want first."; return; }
    plan = null;
    planBox.hidden = true;
    planButton.disabled = true;
    status.textContent = "BabyMind is planning the app with the local model…";
    try {
      renderPlan(await api("/api/builder/plan", {
        method: "POST",
        body: JSON.stringify({ brief: text, name: nameInput.value.trim() }),
      }));
    } catch (error) {
      status.textContent = error.message;
    } finally {
      planButton.disabled = !ready;
      renderStatus();
    }
  });

  approveButton.addEventListener("click", async () => {
    if (!plan) return;
    const runNote = plan.will_run ? ` and run ${plan.entry} once` : "";
    if (!confirm(`Create ${plan.files.length} file(s) in ${plan.target}${runNote}? Nothing existing will be overwritten.`)) return;
    approveButton.disabled = true;
    status.textContent = "Writing files and running the entry point…";
    try {
      const result = await api("/api/builder/build", {
        method: "POST",
        body: JSON.stringify({ plan_id: plan.plan_id, plan_hash: plan.plan_hash }),
      });
      status.textContent = result.notice;
      plan = null;
      renderRun(result);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      renderStatus();
    }
  });

  loadStatus();
})();
