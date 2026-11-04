/* Public GitHub research: no cloned code or automatic imports. */
let githubRepository = null;
let githubFile = null;
let githubFileRequest = 0;

async function inspectGitHubRepository() {
  const form = $('#githubInspectForm');
  const button = form.querySelector('button');
  button.disabled = true;
  $('#githubRepository').textContent = 'Inspecting public repository…';
  $('#githubFile').textContent = '';
  githubRepository = null;
  githubFile = null;
  try {
    const result = await api('/api/research/github/inspect', {method:'POST', body:JSON.stringify({owner:$('#githubOwner').value.trim(),repo:$('#githubRepo').value.trim()})});
    githubRepository = result;
    $('#githubRepository').innerHTML = `<article class="task-card"><h3>${escapeHTML(result.owner)}/${escapeHTML(result.repo)}</h3><p>${escapeHTML(result.description)}</p><p>Commit: <code>${escapeHTML(result.commit)}</code><br>License metadata: ${escapeHTML(result.license)}</p><p>${escapeHTML(result.notice)}</p><p>${result.truncated ? 'File list is incomplete or truncated.' : 'File list:'}</p><div class="task-actions">${result.files.map(file => `<button type="button" class="task-action" data-github-file="${escapeHTML(file.path)}">${escapeHTML(file.path)}${file.size == null ? '' : ' (' + file.size + ' bytes)'}</button>`).join('')}</div></article>`;
    $('#githubRepository').querySelectorAll('[data-github-file]').forEach(item => item.addEventListener('click', () => readGitHubFile(item.dataset.githubFile)));
  } catch(error) { $('#githubRepository').textContent = error.message; }
  finally { button.disabled = false; }
}

async function readGitHubFile(path) {
  const repository = githubRepository;
  if (!repository) return;
  const requestId = ++githubFileRequest;
  $('#githubFile').textContent = 'Reading pinned source file…';
  githubFile = null;
  try {
    const file = await api('/api/research/github/file', {method:'POST', body:JSON.stringify({owner:repository.owner,repo:repository.repo,commit:repository.commit,path})});
    if (githubRepository !== repository || requestId !== githubFileRequest) return;
    githubFile = file;
    $('#githubFile').innerHTML = `<article class="task-card"><h3>${escapeHTML(file.path)}</h3><p>Commit: ${escapeHTML(file.commit)}<br>Git blob: ${escapeHTML(file.blob)}</p><p>${escapeHTML(file.notice)}</p><button type="button" class="task-action" id="githubUseInReview">Use excerpt in development review</button><pre style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></article>`;
    $('#githubFile pre').textContent = file.text;
    $('#githubUseInReview').addEventListener('click', () => {
      if (!githubFile) return;
      const input = $('#developmentContext');
      const header = `GitHub source (untrusted): ${file.owner}/${file.repo} at ${file.commit}, ${file.path}\n`;
      const available = 4000 - input.value.length - (input.value ? 2 : 0) - header.length;
      if (available <= 0) { toast('Development review context is full.'); return; }
      const excerpt = file.text.slice(0, available);
      input.value += (input.value ? '\n\n' : '') + header + excerpt;
      setView('development');
      toast(excerpt.length < file.text.length ? 'Source excerpt added; file was truncated to fit.' : 'Source added to review context.');
    });
  } catch(error) { if (githubRepository === repository && requestId === githubFileRequest) $('#githubFile').textContent = error.message; }
}

document.addEventListener('DOMContentLoaded', () => {
  $('#githubSearchForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.target.querySelector('button');
    button.disabled = true;
    $('#githubSearchResults').textContent = 'Searching public GitHub repositories…';
    try {
      const data = await api('/api/research/github/search', {method:'POST',body:JSON.stringify({query:$('#githubQuery').value,limit:5})});
      $('#githubSearchResults').innerHTML = data.results.map(item => `<article class="task-card"><h3>${escapeHTML(item.owner)}/${escapeHTML(item.repo)}</h3><p>${escapeHTML(item.description)}</p><small>License metadata: ${escapeHTML(item.license)} · Stars: ${item.stars == null ? 'unknown' : item.stars}</small><div class="task-actions"><button type="button" class="task-action" data-github-owner="${escapeHTML(item.owner)}" data-github-repo="${escapeHTML(item.repo)}">Inspect</button></div></article>`).join('') || '<div class="empty-state">No public repositories found.</div>';
      $('#githubSearchResults').querySelectorAll('[data-github-owner]').forEach(item => item.addEventListener('click', () => {
        $('#githubOwner').value = item.dataset.githubOwner;
        $('#githubRepo').value = item.dataset.githubRepo;
        inspectGitHubRepository();
      }));
    } catch(error) { $('#githubSearchResults').textContent = error.message; }
    finally { button.disabled = false; }
  });
  $('#githubInspectForm').addEventListener('submit', event => { event.preventDefault(); inspectGitHubRepository(); });
});
