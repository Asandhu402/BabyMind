(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = { tasks: [], proposals: [], busy: false };
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function toast(message) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => el.classList.remove("show"), 2800);
  }
  async function api(path, options = {}, retried = false) {
    const token = localStorage.getItem("babymind_access_token") || "";
    const response = await fetch(path, { ...options, headers: {
      "Content-Type": "application/json",
      ...(token ? {"X-BabyMind-Token": token} : {}),
      ...(options.headers || {})
    }});
    const data = await response.json().catch(() => ({error:"Unexpected server response"}));
    if (response.status === 401 && !retried) {
      const entered = prompt("Enter the one-time BabyMind access token shown in the PowerShell window on your PC:");
      if (!entered) throw new Error("Access token is required.");
      localStorage.setItem("babymind_access_token", entered.trim());
      return api(path, options, true);
    }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }
  async function load() {
    try {
      const [tasks, proposals] = await Promise.all([api("/api/tasks"), api("/api/proposals")]);
      state.tasks = tasks;
      state.proposals = proposals;
      const pending = proposals.filter(item => item.status === "awaiting_approval").length;
      $("#approvalCount").textContent = pending;
      render();
    } catch (error) {
      $("#approvalList").innerHTML = `<div class="approval-empty">${escapeHTML(error.message)}</div>`;
      toast(error.message);
    }
  }
  function render() {
    const activeTasks = state.tasks.filter(task => task.status === "active");
    const pending = state.proposals.filter(item => item.status === "awaiting_approval");
    const finished = state.proposals.filter(item => item.status !== "awaiting_approval");
    const cards = [...pending, ...finished].sort((a,b) => String(b.created_at).localeCompare(String(a.created_at)));
    if (!cards.length) {
      $("#approvalList").innerHTML = '<div class="approval-empty">No proposals yet. Start a task, then create a folder-listing proposal from this screen.</div>';
      renderCreateForm(activeTasks);
      return;
    }
    $("#approvalList").innerHTML = cards.map(item => {
      const target = item.payload?.relative_path || ".";
      let resultHTML = "";
      if (item.status === "completed" && item.result) {
        try {
          const result = typeof item.result === "string" ? JSON.parse(item.result) : item.result;
          const entries = Array.isArray(result.entries) ? result.entries : [];
          const foundFiles = Array.isArray(result.files) ? result.files : [];
          resultHTML = item.action === "run_tests"
            ? `<div class="approval-result"><strong>Test run · ${result.success ? "passed" : result.timed_out ? "timed out" : "failed"} · exit code ${escapeHTML(result.exit_code)}</strong><pre class="approval-file-preview">${escapeHTML(result.output || "No test output.")}</pre>${result.output_truncated ? "<p>Output was truncated to the last 20,000 characters.</p>" : ""}</div>`
            : item.action === "edit_text_file"
            ? `<div class="approval-result"><strong>File updated · ${escapeHTML(result.bytes)} bytes</strong><p>${escapeHTML(result.relative_path)}</p></div>`
            : item.action === "create_text_file"
            ? `<div class="approval-result"><strong>New file created · ${escapeHTML(result.bytes)} bytes</strong><p>${escapeHTML(result.relative_path)}</p></div>`
            : item.action === "read_text_file"
              ? `<div class="approval-result"><strong>Text preview · ${escapeHTML(result.bytes)} bytes</strong><pre class="approval-file-preview">${escapeHTML(result.content)}</pre></div>`
              : item.action === "find_files"
              ? `<div class="approval-result"><strong>Filename matches · ${escapeHTML(result.count)}</strong><p>File contents were not opened. Create a separate preview proposal for each file; each preview requires its own approval.</p><ul>${foundFiles.map(file => `<li><code>${escapeHTML(file.relative_path)}</code> <button type="button" class="approval-file-propose" data-preview-path="${escapeHTML(file.relative_path)}" data-task-id="${escapeHTML(item.task_id)}">Request preview</button></li>`).join("") || "<li>No matching text files found.</li>"}</ul>${result.truncated ? "<p>Search reached a safety limit; narrow the filename or folder to see more.</p>" : ""}</div>`
              : `<div class="approval-result"><strong>Directory listing result</strong><ul>${entries.map(entry => `<li>${escapeHTML(entry.name)} <span>· ${escapeHTML(entry.type)}</span></li>`).join("") || "<li>Folder is empty.</li>"}</ul>${result.truncated ? "<p>Only the first 200 entries are shown.</p>" : ""}</div>`;
        } catch { resultHTML = '<div class="approval-result">Completed. Result could not be displayed.</div>'; }
      }
      const approve = item.status === "awaiting_approval"
        ? `<div class="approval-actions"><button class="approval-approve" data-approve="${escapeHTML(item.id)}" ${state.busy ? "disabled" : ""}>Approve this exact action</button></div>`
        : "";
      const isTestRun = item.action === "run_tests";
      const isFileRead = item.action === "read_text_file";
      const isFileSearch = item.action === "find_files";
      const isFileCreate = item.action === "create_text_file";
      const isFileEdit = item.action === "edit_text_file";
      const editPreview = isFileEdit ? `<div class="approval-result"><strong>Before</strong><pre class="approval-file-preview">${escapeHTML(item.payload?.original_content || "")}</pre><strong>After</strong><pre class="approval-file-preview">${escapeHTML(item.payload?.content || "")}</pre></div>` : "";
      return `<article class="approval-card"><div class="approval-card-head"><div><span class="approval-status ${item.status === "completed" ? "completed" : ""}">${escapeHTML(item.status.replaceAll("_"," "))}</span><h3>${isTestRun ? "Run project tests" : isFileEdit ? "Edit existing text file" : isFileCreate ? "Create new text file" : isFileRead ? "Preview text file" : isFileSearch ? "Search filenames" : "List folder contents"}</h3><p>Workspace path: <strong>${escapeHTML(target)}</strong></p></div><small>${escapeHTML(new Date(item.created_at).toLocaleString())}</small></div><p>Effect: ${isTestRun ? "Run fixed Python unittest discovery for up to 90 seconds. Test code can execute arbitrary code and access files/network available to this Windows user; it is not sandboxed. Run only trusted projects." : isFileEdit ? "Replace this file's contents only if its current SHA-256 still matches the reviewed version. The change is atomic." : isFileCreate ? "Create a new UTF-8 text file up to 32 KB. Existing files are never overwritten." : isFileRead ? "Read up to 32 KB of UTF-8 text after approval. The preview may contain sensitive information." : isFileSearch ? "Search eligible filenames only. File contents are not opened; each file preview needs separate approval." : "Read names and basic item types only. No file contents are opened or modified."}</p><div class="approval-meta"><span>Task: ${escapeHTML(item.task_id)}</span><span>Action: ${escapeHTML(item.action)}</span></div><div class="approval-hash">Proposal fingerprint: ${escapeHTML(item.proposal_hash)}</div>${editPreview}${approve}${resultHTML}</article>`;
    }).join("");
    $("#approvalList").querySelectorAll("[data-approve]").forEach(button => button.addEventListener("click", () => approve(button.dataset.approve)));
    $("#approvalList").querySelectorAll("[data-preview-path]").forEach(button => button.addEventListener("click", () => requestFilePreview(button.dataset.taskId, button.dataset.previewPath)));
    renderCreateForm(activeTasks);
  }
  function renderCreateForm(activeTasks) {
    let form = $("#createProposalForm");
    if (!form) {
      form = document.createElement("form");
      form.id = "createProposalForm";
      form.className = "task-create-form";
      $("#approvalList").before(form);
    }
    if (!activeTasks.length) {
      form.innerHTML = '<strong>New proposal</strong><p>There are no active tasks. Open Task queue and press Start on a task before creating a proposal.</p><button class="task-primary" type="button" id="goTasks">Open task queue</button>';
      $("#goTasks").addEventListener("click", () => document.querySelector('[data-view="tasks"]')?.click());
      return;
    }
    form.innerHTML = `<strong>Create a workspace proposal</strong><label for="proposalTask">Active task</label><select id="proposalTask">${activeTasks.map(task => `<option value="${escapeHTML(task.id)}">${escapeHTML(task.title)}</option>`).join("")}</select><label for="proposalAction">Action</label><select id="proposalAction"><option value="list_directory">List folder names and types</option><option value="find_files">Search filenames (no contents read)</option><option value="read_text_file">Preview a text file (max 32 KB)</option><option value="create_text_file">Create a new text file (max 32 KB)</option><option value="edit_text_file">Edit existing text file (max 32 KB)</option><option value="run_tests">Run Python unit tests (max 90 seconds)</option></select><label for="proposalPath">Folder or file path inside your workspace</label><input id="proposalPath" maxlength="500" value="." placeholder="e.g. projects"><label for="proposalQuery" id="proposalQueryLabel" hidden>Filename contains</label><input id="proposalQuery" maxlength="80" placeholder="e.g. invoice" hidden><label for="proposalContent" id="proposalContentLabel" hidden>New file content (max 32 KB)</label><textarea id="proposalContent" maxlength="32768" rows="8" placeholder="Write the new file contents…" hidden></textarea><small>Search does not open file contents. Text previews and new file creation each require separate approval. New files never overwrite existing files. Editing shows before/after text and requires approval of the exact file version. Running tests executes project code with your user permissions and is not sandboxed; approve only trusted projects.</small><button class="task-primary" type="submit" ${state.busy ? "disabled" : ""}>＋ Create proposal for review</button>`;
    const actionSelect = $("#proposalAction");
    const queryInput = $("#proposalQuery");
    const queryLabel = $("#proposalQueryLabel");
    const contentInput = $("#proposalContent");
    const contentLabel = $("#proposalContentLabel");
    const updateQueryVisibility = () => {
      const visible = actionSelect.value === "find_files";
      $("#proposalPath").placeholder = actionSelect.value === "run_tests" ? "e.g. my-project (must contain tests/)" : "e.g. projects";
      const creating = actionSelect.value === "create_text_file";
      const editing = actionSelect.value === "edit_text_file";
      queryInput.hidden = !visible;
      queryLabel.hidden = !visible;
      queryInput.required = visible;
      contentInput.hidden = !(creating || editing);
      contentLabel.hidden = !(creating || editing);
      contentLabel.textContent = editing ? "Replacement content (max 32 KB)" : "New file content (max 32 KB)";
      contentInput.required = creating || editing;
    };
    actionSelect.addEventListener("change", updateQueryVisibility);
    updateQueryVisibility();
    form.onsubmit = async event => {
      event.preventDefault();
      if (state.busy) return;
      const taskId = $("#proposalTask").value;
      const relativePath = $("#proposalPath").value.trim();
      const action = $("#proposalAction").value;
      const name_contains = $("#proposalQuery").value.trim();
      const content = $("#proposalContent").value;
      state.busy = true;
      try {
        await api(`/api/tasks/${encodeURIComponent(taskId)}/propose`, {method:"POST", body:JSON.stringify({relative_path:relativePath, action, name_contains, content})});
        toast("Proposal created. Review it below before approving.");
        await load();
      } catch (error) { toast(error.message); }
      finally { state.busy = false; }
    };
  }
  async function requestFilePreview(taskId, relativePath) {
    if (state.busy) return;
    state.busy = true;
    try {
      await api(`/api/tasks/${encodeURIComponent(taskId)}/propose`, {
        method:"POST",
        body:JSON.stringify({relative_path:relativePath, action:"read_text_file"})
      });
      toast("Individual preview proposal created. Review and approve it separately.");
      await load();
    } catch (error) { toast(error.message); }
    finally { state.busy = false; }
  }
  async function approve(id) {
    const item = state.proposals.find(proposal => proposal.id === id);
    if (!item || item.status !== "awaiting_approval" || state.busy) return;
    const target = item.payload?.relative_path || ".";
    const isFileRead = item.action === "read_text_file";
    const isFileSearch = item.action === "find_files";
    const isFileCreate = item.action === "create_text_file";
    const isFileEdit = item.action === "edit_text_file";
    const isTestRun = item.action === "run_tests";
    const confirmation = isTestRun
      ? `Approve running Python unittest discovery in this project?\n\nProject: ${target}\n\nThe fixed test command runs for at most 90 seconds. Project tests are arbitrary code: they can read/write files and access network resources available to your Windows user. BabyMind does not sandbox them. Continue only if you trust this project.`
      : isFileEdit
      ? `Approve replacing the contents of this existing text file?\n\n${target}\n\nBabyMind will first verify the current file still matches SHA-256 ${item.payload?.expected_sha256 || ""}. The before/after contents are shown on this card. If the file has changed, the edit will be refused.`
      : isFileCreate
      ? `Approve creating this new UTF-8 text file?\n\n${target}\n\nSize: ${new TextEncoder().encode(item.payload?.content || "").length} bytes\n\nThe target must not already exist. BabyMind will never overwrite a file.`
      : isFileRead
      ? `Approve reading up to 32 KB of UTF-8 text from this exact workspace file?\n\n${target}\n\nThe contents may be sensitive and will be shown in BabyMind. No file will be modified.`
      : isFileSearch
        ? `Approve searching filenames inside this workspace folder?\n\nFolder: ${target}\nFilename contains: ${item.payload?.name_contains || ""}\n\nOnly eligible filenames will be inspected. No file contents will be opened.`
        : `Approve this exact read-only action?\n\nList names and types in workspace folder: ${target}\n\nNo files will be opened or changed.`;
    if (!confirm(confirmation)) return;
    state.busy = true;
    try {
      await api(`/api/proposals/${encodeURIComponent(id)}/approve`, {method:"POST", body:JSON.stringify({proposal_hash:item.proposal_hash})});
      toast(isTestRun ? "Approved. Test run finished; review its result." : isFileEdit ? "Approved. Text file updated." : isFileCreate ? "Approved. New file created." : isFileRead ? "Approved. Text preview complete." : isFileSearch ? "Approved. Filename search complete." : "Approved. The read-only listing is complete.");
      await load();
    } catch (error) { toast(error.message); }
    finally { state.busy = false; }
  }
  document.addEventListener("click", event => {
    const nav = event.target.closest('[data-view="approvals"]');
    if (nav) {
      $("#pageTitle").textContent = "Approvals";
      load();
    }
  });
  $("#refreshApprovals")?.addEventListener("click", load);
  load();
})();