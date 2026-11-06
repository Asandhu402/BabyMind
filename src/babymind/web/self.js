/* Self & autonomy view: BabyMind's self-model, calibration, dissent and the
   controls for bounded autonomous operation.

   Loaded after app.js and reuses its $, api, toast, escapeHTML and markdown. */
(function () {
  "use strict";
  if (typeof window === "undefined") return;

  const el = (id) => document.getElementById(id);
  const text = (value) => String(value === null || value === undefined ? "" : value);

  function setHTML(id, html) {
    const node = el(id);
    if (node) node.innerHTML = html;
  }

  function statGrid(pairs) {
    return pairs
      .map(
        ([label, value]) =>
          `<div class="self-stat"><span>${escapeHTML(label)}</span><strong>${escapeHTML(text(value))}</strong></div>`
      )
      .join("");
  }

  function emptyRow(message) {
    return `<div class="self-empty">${escapeHTML(message)}</div>`;
  }

  // ------------------------------------------------------------- self-model

  async function loadSelf() {
    try {
      const report = await api("/api/self/status");
      const identity = report.identity || {};
      setHTML(
        "selfIdentityText",
        `<strong>${escapeHTML(identity.name || "BabyMind")}</strong> — ${escapeHTML(identity.kind || "")}<br>` +
          `<span class="self-muted">${escapeHTML(identity.purpose || "")}</span>` +
          (identity.stance_on_its_own_experience
            ? `<div class="self-stance"><em>On its own experience:</em> ${escapeHTML(identity.stance_on_its_own_experience)}</div>`
            : "")
      );

      const select = el("selfVoiceMode");
      if (select && report.voice_mode) select.value = report.voice_mode;
      setHTML("selfVoiceStatus", `Voice mode: <strong>${escapeHTML(report.voice_mode || "reflective")}</strong>`);
      setHTML(
        "selfInvariants",
        (report.voice_invariants || [])
          .map((item) => `<li>${escapeHTML(item)}</li>`)
          .join("")
      );

      const calibration = report.calibration || {};
      if (!calibration.scored) {
        setHTML(
          "selfCalibration",
          emptyRow(
            calibration.note ||
              "No scored predictions yet. Calibration is unknown, not zero — BabyMind is told to say so."
          )
        );
      } else {
        setHTML(
          "selfCalibration",
          statGrid([
            ["Scored predictions", calibration.scored],
            ["Brier score", calibration.brier_score],
            ["Hit rate", calibration.hit_rate],
            ["Mean stated confidence", calibration.mean_confidence],
            ["Awaiting outcome", calibration.pending],
          ]) + `<div class="self-note">${escapeHTML(calibration.note || "")}</div>`
        );
      }

      const beliefs = report.beliefs || {};
      const limits = beliefs.limit || [];
      setHTML(
        "selfLimits",
        limits.length
          ? limits
              .map(
                (item) =>
                  `<div class="self-item"><div class="self-item-top"><span class="self-kind">${escapeHTML(item.kind)}</span>` +
                  `<button class="self-retire" data-belief="${escapeHTML(item.id)}" title="Retire this belief">×</button></div>` +
                  `<p>${escapeHTML(item.claim)}</p>` +
                  `<div class="confidence-bar"><i style="width:${Math.round((item.confidence || 0) * 100)}%"></i></div>` +
                  `<small>confidence ${Number(item.confidence || 0).toFixed(2)} · from ${escapeHTML(item.source)} · rev ${item.revision}</small></div>`
              )
              .join("")
          : emptyRow("No limits recorded yet. BabyMind starts with none and earns them from evidence.")
      );

      const dissent = report.recent_dissent || [];
      setHTML(
        "selfDissent",
        dissent.length
          ? dissent
              .map(
                (item) =>
                  `<div class="self-item"><small>${escapeHTML(item.created_at)}</small>` +
                  `<p class="self-ask">${escapeHTML(item.request)}</p>` +
                  `<p class="self-said">${escapeHTML(item.disagreement)}</p></div>`
              )
              .join("")
          : emptyRow("No pushback recorded yet.")
      );
    } catch (error) {
      setHTML("selfIdentityText", `Could not load BabyMind's self-model: ${escapeHTML(error.message)}`);
    }
  }

  // --------------------------------------------------------------- autonomy

  async function loadAutonomy() {
    try {
      const status = await api("/api/autonomy/status");
      const budget = status.budget || {};
      setHTML(
        "autonomyState",
        statGrid([
          ["State", status.state],
          ["Cycles", `${budget.cycles_used || 0} used / ${budget.cycles_remaining || 0} left`],
          ["Actions this hour", `${budget.actions_used_last_hour || 0} / ${(status.limits || {}).max_actions_per_hour || "?"}`],
          ["Written", `${Math.round((budget.bytes_written || 0) / 1024)} KB`],
          ["Failed in a row", status.consecutive_failures],
          ["Stop flag", status.stop_flag_present ? "present" : "clear"],
        ])
      );
      const stateNode = el("autonomyState");
      if (stateNode) {
        stateNode.classList.toggle("is-running", status.state === "running");
        stateNode.classList.toggle("is-halted", status.state === "halted");
      }
      setHTML(
        "autonomyStatus",
        status.last_stop_reason
          ? escapeHTML(status.last_stop_reason)
          : status.permitted_by_environment === false
          ? "Autonomy is not armed in this environment. Press “Arm &amp; start” to arm it for this session, or set BABYMIND_AUTONOMY=1."
          : "Autonomy is armed and idle."
      );

      const goals = status.goals || [];
      setHTML(
        "autonomyGoals",
        goals.length
          ? goals
              .map(
                (goal) =>
                  `<div class="self-item"><div class="self-item-top"><span class="self-kind">p${goal.priority}</span>` +
                  `<span class="self-kind">${escapeHTML(goal.created_by)}</span></div>` +
                  `<p>${escapeHTML(goal.title)}</p></div>`
              )
              .join("")
          : emptyRow("No active goals. Add one before starting autonomy.")
      );
    } catch (error) {
      setHTML("autonomyState", emptyRow(error.message));
    }
  }

  async function loadAudit() {
    try {
      const data = await api("/api/autonomy/audit?limit=40");
      const chain = data.chain || {};
      const chainNode = el("autonomyChain");
      if (chainNode) {
        chainNode.textContent = chain.intact
          ? `chain intact · ${chain.entries} entries`
          : `CHAIN BROKEN at entry ${chain.broken_at_seq}`;
        chainNode.classList.toggle("is-bad", !chain.intact);
      }
      const entries = (data.entries || []).slice().reverse();
      setHTML(
        "autonomyAudit",
        entries.length
          ? entries
              .map((entry) => {
                const detail =
                  entry.kind === "cycle"
                    ? `${text((entry.payload || {}).action && entry.payload.action.type)} → ${text(
                        (entry.payload || {}).outcome
                      )}${(entry.payload || {}).verified ? " ✓" : " ✗"}`
                    : text((entry.payload || {}).reason || (entry.payload || {}).title || entry.kind);
                return (
                  `<div class="audit-row"><span class="audit-seq">#${entry.seq}</span>` +
                  `<span class="audit-kind">${escapeHTML(entry.kind)}</span>` +
                  `<span class="audit-detail">${escapeHTML(detail)}</span>` +
                  `<code class="audit-hash" title="${escapeHTML(entry.entry_hash)}">${escapeHTML(
                    entry.entry_hash.slice(0, 10)
                  )}</code></div>`
                );
              })
              .join("")
          : emptyRow("Nothing has happened under autonomy yet.")
      );
    } catch (error) {
      setHTML("autonomyAudit", emptyRow(error.message));
    }
  }

  function refreshAll() {
    loadSelf();
    loadAutonomy();
    loadAudit();
  }

  // ------------------------------------------------------------ interactions

  function bind() {
    const voice = el("selfVoiceMode");
    if (voice) {
      voice.addEventListener("change", async () => {
        try {
          const result = await api("/api/self/voice", {
            method: "POST",
            body: JSON.stringify({ mode: voice.value }),
          });
          setHTML("selfVoiceStatus", `Voice mode: <strong>${escapeHTML(result.voice_mode)}</strong>`);
          toast("Voice updated");
        } catch (error) {
          toast(error.message);
        }
      });
    }

    const beliefForm = el("selfBeliefForm");
    if (beliefForm) {
      beliefForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const claim = text(el("selfBeliefClaim").value).trim();
        if (!claim) return;
        try {
          await api("/api/self/belief", {
            method: "POST",
            body: JSON.stringify({ kind: el("selfBeliefKind").value, claim, source: "user", confidence: 0.9 }),
          });
          el("selfBeliefClaim").value = "";
          setHTML("selfBeliefStatus", "Recorded.");
          loadSelf();
        } catch (error) {
          setHTML("selfBeliefStatus", escapeHTML(error.message));
        }
      });
    }

    document.addEventListener("click", async (event) => {
      const retire = event.target.closest("[data-belief]");
      if (!retire) return;
      try {
        await api(`/api/self/belief/${encodeURIComponent(retire.dataset.belief)}`, { method: "DELETE" });
        toast("Belief retired");
        loadSelf();
      } catch (error) {
        toast(error.message);
      }
    });

    const goalForm = el("autonomyGoalForm");
    if (goalForm) {
      goalForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const title = text(el("autonomyGoalTitle").value).trim();
        if (!title) return;
        try {
          await api("/api/autonomy/goal", { method: "POST", body: JSON.stringify({ title }) });
          el("autonomyGoalTitle").value = "";
          toast("Goal added");
          loadAutonomy();
        } catch (error) {
          toast(error.message);
        }
      });
    }

    const start = el("autonomyStart");
    if (start) {
      start.addEventListener("click", async () => {
        try {
          const result = await api("/api/autonomy/start", {
            method: "POST",
            body: JSON.stringify({ confirm: true, cycles: 25, interval: 5 }),
          });
          toast(result.started ? "Autonomy running" : `Not started: ${result.reason}`);
          refreshAll();
        } catch (error) {
          toast(error.message);
        }
      });
    }
    const stop = el("autonomyStop");
    if (stop) {
      stop.addEventListener("click", async () => {
        try {
          await api("/api/autonomy/stop", {
            method: "POST",
            body: JSON.stringify({ reason: "Stopped from the BabyMind interface." }),
          });
          toast("Autonomy stopped");
          refreshAll();
        } catch (error) {
          toast(error.message);
        }
      });
    }
    const pause = el("autonomyPause");
    if (pause) {
      pause.addEventListener("click", async () => {
        try {
          const result = await api("/api/autonomy/pause", { method: "POST", body: "{}" });
          if (result && result.changed) {
            pause.textContent = "Resume";
            pause.dataset.mode = "resume";
          } else {
            const resumed = await api("/api/autonomy/resume", { method: "POST", body: "{}" });
            pause.textContent = "Pause";
            pause.dataset.mode = "pause";
            if (resumed && !resumed.changed) toast(resumed.reason || "Autonomy is not running.");
          }
          refreshAll();
        } catch (error) {
          toast(error.message);
        }
      });
    }
    const reset = el("autonomyReset");
    if (reset) {
      reset.addEventListener("click", async () => {
        try {
          await api("/api/autonomy/reset", { method: "POST", body: "{}" });
          toast("Autonomy reset; the stop flag was cleared");
          refreshAll();
        } catch (error) {
          toast(error.message);
        }
      });
    }
  }

  // ------------------------------------------------------- chat self-check UI

  function renderSelfCheck(message, introspection) {
    if (!message || !introspection) return;
    const body = message.querySelector(".message-content");
    if (!body) return;
    const wrap = document.createElement("details");
    wrap.className = "self-check";
    const confidence = Number(introspection.confidence || 0);
    const label = introspection.dissent
      ? "Pushed back on the premise"
      : introspection.revised
      ? "Revised after self-critique"
      : "Self-checked";
    wrap.innerHTML =
      `<summary><span class="self-check-dot"></span>${escapeHTML(label)} · confidence ${confidence.toFixed(2)}` +
      `${introspection.degraded ? " · degraded" : ""}</summary>` +
      `<div class="self-check-body">` +
      (introspection.dissent
        ? `<div class="self-check-row"><strong>Disagreement</strong><span>${escapeHTML(introspection.dissent)}</span></div>`
        : "") +
      (introspection.what_changed
        ? `<div class="self-check-row"><strong>Changed</strong><span>${escapeHTML(introspection.what_changed)}</span></div>`
        : "") +
      ((introspection.assumptions || []).length
        ? `<div class="self-check-row"><strong>Assumed</strong><span>${escapeHTML(
            introspection.assumptions.join(" · ")
          )}</span></div>`
        : "") +
      ((introspection.unverified || []).length
        ? `<div class="self-check-row"><strong>Unverified</strong><span>${escapeHTML(
            introspection.unverified.join(" · ")
          )}</span></div>`
        : "") +
      ((introspection.review || {}).most_important_fix
        ? `<div class="self-check-row"><strong>Critique</strong><span>${escapeHTML(
            introspection.review.most_important_fix
          )}</span></div>`
        : "") +
      (introspection.degraded
        ? `<div class="self-check-row"><strong>Degraded</strong><span>${escapeHTML(introspection.degraded)}</span></div>`
        : "") +
      `<div class="self-check-foot">Second opinion from the same local model, not an independent check.</div>` +
      `</div>`;
    body.append(wrap);
  }

  // Expose for app.js; defer binding until the document is parsed.
  window.babymindLoadSelf = refreshAll;
  window.babymindRenderSelfCheck = renderSelfCheck;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
