(() => {
  const root = document.getElementById('exam-upload-progress');
  if (!root) return;
  const button = document.getElementById('refresh-upload-status');
  const message = document.getElementById('upload-refresh-message');
  let timer, busy = false, attempts = 0, active = root.dataset.active === 'true';

  let refreshStartedAt = Date.now();
  const withinBudget = () => attempts < 24 && Date.now() - refreshStartedAt < 120000;
  async function refresh() {
    if (busy || document.hidden) return;
    if (!withinBudget()) {
      message.textContent = 'Automatic refresh paused. Use Refresh status to check again.';
      return;
    }
    busy = true;
    button.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(root.dataset.statusUrl, {signal: controller.signal, headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error('Status request failed');
      const data = await response.json();
      for (const status of ['pending', 'processing', 'processed', 'failed']) {
        document.getElementById(`${status}-count`).textContent = data[status];
      }
      const body = document.getElementById('upload-history-rows');
      body.replaceChildren();
      for (const upload of data.uploads) {
        const row = document.createElement('tr');
        const name = document.createElement('td');
        const link = document.createElement('a');
        link.href = upload.url;
        link.textContent = upload.original_name;
        name.append(link);
        row.append(name);
        for (const value of [upload.pdf_type, upload.status, `${upload.records_created} new / ${upload.records_updated} updated`, upload.error_message || '—']) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.append(cell);
        }
        body.append(row);
      }
      if (!data.uploads.length) {
        const row = document.createElement('tr'), cell = document.createElement('td');
        cell.colSpan = 5;
        cell.textContent = 'No uploads yet. Select a PDF to start.';
        row.append(cell);
        body.append(row);
      }
      active = data.pending + data.processing > 0;
      attempts += 1;
      message.textContent = `Updated ${new Date().toLocaleTimeString()}. ` +
        (active ? (withinBudget() ? 'Waiting for the worker; refreshing automatically.' : 'Automatic refresh paused. Use Refresh status to check again.') : 'No queued or processing files in this scope.');
      if (active && withinBudget()) timer = setTimeout(refresh, 5000);
    } catch (_) {
      message.textContent = 'Could not refresh status. Displayed data may be out of date. Check your connection or session, then use Refresh status.';
    } finally {
      clearTimeout(timeout);
      busy = false;
      button.disabled = false;
    }
  }
  button.addEventListener('click', () => {clearTimeout(timer); attempts = 0; refreshStartedAt = Date.now(); refresh();});
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (!document.hidden && active && withinBudget()) refresh();
  });
  if (active) refresh();
})();
