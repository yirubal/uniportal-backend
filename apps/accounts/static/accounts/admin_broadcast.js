(() => {
  const form = document.getElementById('broadcastForm');
  const dialog = document.getElementById('confirmDialog');
  let confirmed = false, submitting = false;
  window.updateCounter = (input) => {
    document.getElementById('charCount').textContent = input.value.length;
    document.getElementById('previewBox').textContent = input.value;
  };
  window.togglePreview = () => {
    updateCounter(document.getElementById('message'));
    document.getElementById('previewSection').classList.toggle('hidden');
  };
  window.confirmSend = () => { if (form.reportValidity() && !submitting) dialog.showModal(); };
  window.submitBroadcast = () => {
    if (submitting || !form.reportValidity()) return;
    confirmed = true;
    form.requestSubmit();
  };
  form.addEventListener('submit', (event) => {
    if (submitting || !confirmed) {
      event.preventDefault();
      if (!submitting) confirmSend();
      return;
    }
    submitting = true;
    document.getElementById('confirm-broadcast-send').disabled = true;
    dialog.close();
  });
  updateCounter(document.getElementById('message'));

  const root = document.getElementById('broadcast-status');
  const button = document.getElementById('refresh-broadcast-status');
  const message = document.getElementById('broadcast-refresh-message');
  let timer, busy = false, attempts = 0;
  let active = [...document.querySelectorAll('[data-pending]')].some(element => Number(element.dataset.pending) > 0);
  let refreshStartedAt = Date.now();
  const withinBudget = () => attempts < 24 && Date.now() - refreshStartedAt < 120000;
  async function refresh() {
    if (busy || document.hidden) return;
    if (!withinBudget()) {
      message.textContent = 'Automatic refresh paused. Use Refresh delivery progress to check again.';
      return;
    }
    busy = true;
    button.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(root.dataset.statusUrl, {signal: controller.signal, headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error('Progress request failed');
      const data = await response.json();
      active = false;
      for (const broadcast of data.broadcasts) {
        const element = document.getElementById(`broadcast-progress-${broadcast.id}`);
        if (!element) continue;
        element.textContent = `${broadcast.delivered} / ${broadcast.total} delivered; ${broadcast.pending} remaining; ${broadcast.failed} failed`;
        active = active || broadcast.pending > 0;
      }
      attempts += 1;
      message.textContent = `Updated ${new Date().toLocaleTimeString()}. ` +
        (active ? (withinBudget() ? 'Delivery is queued; refreshing automatically.' : 'Automatic refresh paused. Use Refresh delivery progress to check again.') : 'Delivery has finished for the displayed broadcasts. Review any failed deliveries before retrying.');
      if (active && withinBudget()) timer = setTimeout(refresh, 5000);
    } catch (_) {
      message.textContent = 'Could not refresh delivery progress. Displayed counts may be out of date. Check your connection or session and refresh again.';
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
