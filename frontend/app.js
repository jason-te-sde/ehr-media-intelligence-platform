// frontend/app.js — EHR Media Intelligence client
// Vanilla JS; no build step. Talks to FastAPI on the same origin.

(function () {
  'use strict';

  // ----------------------------- State ------------------------------------

  const state = {
    query: '',
    resourceTypes: new Set(),
    dateFrom: null,
    dateTo: null,
    results: [],
    loading: false,
    requestId: 0,      // race-condition guard
    selected: null,
  };

  // ----------------------------- DOM refs ---------------------------------

  const $ = (id) => document.getElementById(id);
  const ui = {
    search: $('search'),
    dateFrom: $('date-from'),
    dateTo: $('date-to'),
    clearFilters: $('clear-filters'),
    rtypeButtons: document.querySelectorAll('.rtype'),
    status: $('status'),
    loading: $('loading'),
    results: $('results'),
    hint: $('hint'),
    empty: $('empty'),
    error: $('error'),
    errorMsg: $('error-msg'),
    modal: $('modal'),
    modalTitle: $('modal-title'),
    modalSubtitle: $('modal-subtitle'),
    modalBody: $('modal-body'),
    modalClose: $('modal-close'),
  };

  // ----------------------------- Utilities --------------------------------

  function debounce(fn, ms) {
    let t = null;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const RTYPE_BADGE = {
    Summary: { label: 'Summary', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
    DocumentReference: { label: 'Note', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
    DiagnosticReport: { label: 'Report', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  };

  function setStatus(text) { ui.status.textContent = text; }

  function showOnly(panelId) {
    for (const id of ['hint', 'empty', 'error', 'loading']) {
      const el = $(id);
      el.hidden = id !== panelId;
    }
  }

  function clearResultsDom() { ui.results.innerHTML = ''; }

  // ----------------------------- Rendering --------------------------------

  function renderResults() {
    clearResultsDom();
    if (state.results.length === 0) {
      showOnly('empty');
      setStatus('No matches.');
      return;
    }
    showOnly(null);   // hide all panels
    for (const h of state.results) {
      ui.results.appendChild(renderCard(h));
    }
    setStatus(`${state.results.length} match${state.results.length === 1 ? '' : 'es'}.`);
  }

  function renderCard(h) {
    const badge = RTYPE_BADGE[h.resource_type] || { label: h.resource_type, cls: '' };
    const li = document.createElement('li');
    const date = h.resource_date || '—';
    const scoreFill = Math.round((h.relevance_score || 0) * 100);
    li.innerHTML = `
      <article tabindex="0" role="button"
               aria-label="Open detail for ${escapeHtml(h.display_name)} (${escapeHtml(h.mrn)})"
               class="bg-white border rounded-lg p-4 hover:shadow-md focus:shadow-md transition cursor-pointer">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <p class="font-semibold">${escapeHtml(h.display_name)}</p>
            <p class="text-xs text-slate-500">${escapeHtml(h.mrn)} · ${escapeHtml(date)}</p>
          </div>
          <span class="text-xs px-2 py-1 rounded-full border ${badge.cls}">${badge.label}</span>
        </div>
        <p class="mt-2 text-sm text-slate-700">${escapeHtml((h.snippet || '').slice(0, 220))}${(h.snippet || '').length > 220 ? '…' : ''}</p>
        <div class="mt-3 flex items-center gap-2" aria-label="Relevance score">
          <div class="flex-1 h-1.5 bg-slate-200 rounded overflow-hidden"
               role="meter" aria-valuemin="0" aria-valuemax="1"
               aria-valuenow="${(h.relevance_score || 0).toFixed(2)}">
            <div class="h-full bg-blue-500" style="width:${scoreFill}%"></div>
          </div>
          <span class="text-xs tabular-nums text-slate-500">${(h.relevance_score || 0).toFixed(2)}</span>
        </div>
      </article>`;
    const card = li.firstElementChild;
    card.addEventListener('click', () => openDetail(h.patient_id));
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openDetail(h.patient_id);
      }
    });
    return li;
  }

  // ------------------------- Search request -------------------------------

  async function runSearch() {
    if (!state.query) {
      state.results = [];
      clearResultsDom();
      showOnly('hint');
      return;
    }
    const reqId = ++state.requestId;
    showOnly('loading');
    setStatus('Searching…');

    const payload = {
      query: state.query,
      top_k: 5,
      resource_types: state.resourceTypes.size ? [...state.resourceTypes] : null,
      date_from: state.dateFrom || null,
      date_to: state.dateTo || null,
    };

    try {
      const res = await fetch('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (reqId !== state.requestId) return;      // a newer request superseded us
      if (!res.ok) {
        const t = await res.text();
        throw new Error(`HTTP ${res.status} ${t.slice(0, 200)}`);
      }
      const body = await res.json();
      state.results = body.hits || [];
      renderResults();
    } catch (err) {
      if (reqId !== state.requestId) return;
      console.error(err);
      ui.errorMsg.textContent = String(err.message || err);
      showOnly('error');
      setStatus('Search failed.');
    }
  }

  const searchDebounced = debounce(runSearch, 300);

  // ------------------------- Filters --------------------------------------

  function toggleResourceType(btn) {
    const t = btn.dataset.rtype;
    if (state.resourceTypes.has(t)) {
      state.resourceTypes.delete(t);
      btn.setAttribute('aria-pressed', 'false');
      btn.classList.remove('bg-blue-100', 'border-blue-400', 'text-blue-700');
    } else {
      state.resourceTypes.add(t);
      btn.setAttribute('aria-pressed', 'true');
      btn.classList.add('bg-blue-100', 'border-blue-400', 'text-blue-700');
    }
    runSearch();
  }

  function clearAllFilters() {
    state.resourceTypes.clear();
    state.dateFrom = null;
    state.dateTo = null;
    ui.dateFrom.value = '';
    ui.dateTo.value = '';
    ui.rtypeButtons.forEach((b) => {
      b.setAttribute('aria-pressed', 'false');
      b.classList.remove('bg-blue-100', 'border-blue-400', 'text-blue-700');
    });
    runSearch();
  }

  // ------------------------- Detail modal ---------------------------------

  let lastFocused = null;

  async function openDetail(patientId) {
    lastFocused = document.activeElement;
    ui.modalBody.innerHTML = '<p class="text-sm text-slate-500">Loading…</p>';
    ui.modalSubtitle.textContent = '';
    ui.modal.hidden = false;
    document.body.style.overflow = 'hidden';
    ui.modalClose.focus();
    setStatus('Loading patient detail…');
    try {
      const res = await fetch(`/patient/${encodeURIComponent(patientId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      renderDetail(d);
      setStatus(`Showing detail for ${d.display_name}.`);
    } catch (err) {
      ui.modalBody.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderDetail(d) {
    ui.modalSubtitle.textContent = `${d.mrn} · DOB ${d.dob || '—'} · ${d.gender || 'unknown'}`;
    ui.modalTitle.textContent = d.display_name || 'Patient';

    const parts = [];
    // Summary section
    if (d.summary) {
      const s = d.summary;
      const list = (arr) => arr && arr.length
        ? `<ul class="list-disc list-inside text-sm space-y-0.5 mt-1">${arr.map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul>`
        : '<p class="text-sm text-slate-500 italic mt-1">None recorded.</p>';
      parts.push(`
        <section>
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">Chief concern</h3>
          <p class="mt-1">${escapeHtml(s.chief_concern)}</p>
        </section>
        <section>
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">Key diagnoses</h3>
          ${list(s.key_diagnoses)}
        </section>
        <section>
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">Recent media</h3>
          ${list(s.recent_media)}
        </section>
        <section>
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">Flagged anomalies</h3>
          ${list(s.anomalies)}
        </section>
        <section class="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-800">
          ${escapeHtml(s.disclaimer)}
        </section>`);
    } else {
      parts.push(`
        <section class="text-sm text-slate-500 italic">
          No AI summary has been generated for this patient yet.
        </section>`);
    }

    // Linked resources
    if (d.linked_resources && d.linked_resources.length) {
      const rows = d.linked_resources.slice(0, 25).map((lr) => {
        const badge = RTYPE_BADGE[lr.resource_type] || { label: lr.resource_type, cls: '' };
        return `<li class="flex items-center justify-between gap-3 text-sm py-1.5 border-b last:border-b-0">
          <span class="text-slate-700">${escapeHtml(lr.title || '—')}</span>
          <span class="flex items-center gap-2 text-xs">
            <span class="px-2 py-0.5 rounded-full border ${badge.cls}">${badge.label}</span>
            <span class="text-slate-500 tabular-nums">${escapeHtml(lr.date || '—')}</span>
          </span>
        </li>`;
      }).join('');
      const overflow = d.linked_resources.length > 25
        ? `<p class="text-xs text-slate-500 mt-2">…and ${d.linked_resources.length - 25} more</p>`
        : '';
      parts.push(`
        <section>
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">Linked FHIR resources (${d.linked_resources.length})</h3>
          <ul class="mt-1">${rows}</ul>
          ${overflow}
        </section>`);
    }

    ui.modalBody.innerHTML = parts.join('');
  }

  function closeModal() {
    ui.modal.hidden = true;
    document.body.style.overflow = '';
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus();
    }
  }

  // Trap focus while modal is open
  function focusTrap(e) {
    if (ui.modal.hidden) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeModal();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = ui.modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }

  // ----------------------------- Wiring -----------------------------------

  ui.search.addEventListener('input', (e) => {
    state.query = e.target.value.trim();
    searchDebounced();
  });

  ui.dateFrom.addEventListener('change', (e) => { state.dateFrom = e.target.value || null; runSearch(); });
  ui.dateTo.addEventListener('change', (e) => { state.dateTo = e.target.value || null; runSearch(); });
  ui.rtypeButtons.forEach((b) => b.addEventListener('click', () => toggleResourceType(b)));
  ui.clearFilters.addEventListener('click', clearAllFilters);

  ui.modalClose.addEventListener('click', closeModal);
  ui.modal.addEventListener('click', (e) => {
    // backdrop click closes (but not clicks inside the content)
    if (e.target === ui.modal) closeModal();
  });
  document.addEventListener('keydown', focusTrap);

  // Focus the search box on load
  ui.search.focus();
})();
