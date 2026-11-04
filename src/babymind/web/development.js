/* Model-backed specialist review UI. These reports are not proof of execution. */
let selectedDevelopmentReview = null;
let loadingDevelopmentReviews = false;

async function loadDevelopmentReviews() {
  if (loadingDevelopmentReviews) return;
  loadingDevelopmentReviews = true;
  try {
    const reviews = await api('/api/development-reviews');
    const history = $('#developmentHistory');
    history.innerHTML = reviews.map(review => `<button type="button" class="task-refresh" data-review-id="${escapeHTML(review.id)}">${escapeHTML(review.task.slice(0, 90))} · ${escapeHTML(review.status)}</button>`).join('') || '<div class="empty-state">No development reviews yet.</div>';
    history.querySelectorAll('[data-review-id]').forEach(button => button.addEventListener('click', () => {
      selectedDevelopmentReview = button.dataset.reviewId;
      loadDevelopmentReviews();
    }));
    if (selectedDevelopmentReview && !reviews.some(review => review.id === selectedDevelopmentReview)) selectedDevelopmentReview = null;
    if (!selectedDevelopmentReview && reviews.length) selectedDevelopmentReview = reviews[0].id;
    const target = $('#developmentReport');
    if (!selectedDevelopmentReview) { target.innerHTML = ''; return; }
    const review = await api('/api/development-reviews/' + encodeURIComponent(selectedDevelopmentReview));
    const open = new Set([...target.querySelectorAll('details[open]')].map(item => item.dataset.roleId));
    const completed = review.roles.filter(role => role.status === 'completed').length;
    const failed = review.roles.filter(role => role.status === 'failed').length;
    const actions = review.status === 'running' ? '<button type="button" data-review-action="cancel">Cancel after current model call</button>' :
      ['failed', 'interrupted', 'cancelled'].includes(review.status) ? '<button type="button" data-review-action="resume">Resume pending and failed roles</button><button type="button" data-review-action="delete">Delete review</button>' :
      review.status === 'reviewed' ? '<button type="button" data-review-action="delete">Delete review</button>' : '';
    target.innerHTML = `<article class="task-card"><h3>${escapeHTML(review.task)}</h3><p>Status: ${escapeHTML(review.status)} · ${completed}/50 reports · ${failed} failed</p><p>Reports are unverified model output. No files were inspected and no tests were run.</p><div class="task-actions">${actions}</div></article>` + review.roles.map(role => {
      const attempts = review.attempts.filter(attempt => attempt.role_id === role.role_id);
      const last = attempts[attempts.length - 1];
      const attemptText = last ? `${attempts.length} attempt(s) · last ${last.duration_ms == null ? 'interrupted' : (last.duration_ms / 1000).toFixed(1) + 's'}${last.error ? ' · ' + last.error : ''}` : 'Not attempted';
      const history = attempts.length > 1 ? `<details><summary>Attempt history</summary>${attempts.map(attempt => `<p><small>${escapeHTML(attempt.started_at)} · ${escapeHTML(attempt.status)}${attempt.error ? ' · ' + escapeHTML(attempt.error) : ''}</small><br><span style="white-space:pre-wrap">${escapeHTML(attempt.response || '')}</span></p>`).join('')}</details>` : '';
      return `<details class="task-card" data-role-id="${role.role_id}" ${open.has(String(role.role_id)) ? 'open' : ''}><summary>${String(role.role_id).padStart(2, '0')} · ${escapeHTML(role.name)} — ${escapeHTML(role.status)}</summary><p>${escapeHTML(role.objective)}</p><small>${escapeHTML(attemptText)}</small><p style="white-space:pre-wrap">${escapeHTML(role.response || 'No report recorded.')}</p>${history}</details>`;
    }).join('');
    target.querySelectorAll('[data-review-action]').forEach(button => button.addEventListener('click', async () => {
      const action = button.dataset.reviewAction;
      button.disabled = true;
      try {
        const url = '/api/development-reviews/' + encodeURIComponent(review.id);
        if (action === 'delete') {
          if (!confirm('Delete this review and all its recorded reports?')) return;
          await api(url, {method: 'DELETE'});
          selectedDevelopmentReview = null;
        } else await api(url + '/' + action, {method: 'POST', body: '{}'});
        await loadDevelopmentReviews();
      } catch (error) { toast(error.message); }
      finally { button.disabled = false; }
    }));
  } catch (error) { $('#developmentReport').textContent = error.message; }
  finally { loadingDevelopmentReviews = false; }
}

document.addEventListener('DOMContentLoaded', () => {
  $('#developmentForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    try {
      const result = await api('/api/development-reviews', {method: 'POST', body: JSON.stringify({task: $('#developmentTask').value, context: $('#developmentContext').value})});
      selectedDevelopmentReview = result.id;
      await loadDevelopmentReviews();
    } catch (error) { toast(error.message); }
    finally { button.disabled = false; }
  });
  $('#refreshDevelopment').addEventListener('click', loadDevelopmentReviews);
  setInterval(() => { if ($('#developmentView').classList.contains('active')) loadDevelopmentReviews(); }, 4000);
});
