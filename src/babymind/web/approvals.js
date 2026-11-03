(() => {
  const list = document.querySelector("#approvalList");
  const count = document.querySelector("#approvalCount");
  const notice = '<div class="approval-empty"><strong>Workspace file actions are temporarily disabled.</strong><p>BabyMind will not list, search, preview, create, or edit workspace files until native, race-resistant filesystem protections are implemented and tested. Existing proposals cannot be approved.</p></div>';
  function renderDisabledState() {
    if (count) count.textContent = "0";
    if (list) list.innerHTML = notice;
    const form = document.querySelector("#createProposalForm");
    if (form) form.remove();
  }
  document.querySelector("#refreshApprovals")?.addEventListener("click", renderDisabledState);
  document.addEventListener("click", event => {
    if (event.target.closest('[data-view="approvals"]')) {
      const title = document.querySelector("#pageTitle");
      if (title) title.textContent = "Approvals";
      renderDisabledState();
    }
  });
  renderDisabledState();
})();
