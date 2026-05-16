// frontend/app.js — EHR Media Intelligence client
// Vanilla JS; no build step. Talks to FastAPI on the same origin.

(function () {
  'use strict';

  // ----------------------------- State ------------------------------------

  const state = {
    query: '',
    resourceType: '', // '' = All; otherwise 'DocumentReference' or 'DiagnosticReport'
    dateFrom: null,
    dateTo: null,
    results: [],
    loading: false,
    requestId: 0,      // race-condition guard
    selected: null,
    provider: null,    // chosen LLM provider id; null = use server default
    providers: [],     // [{id,name,model,healthy,active,...}]
  };

  // ----------------------------- DOM refs ---------------------------------

  const $ = (id) => document.getElementById(id);
  const ui = {
    search: $('search'),
    dateFrom: $('date-from'),
    dateTo: $('date-to'),
    clearFilters: $('clear-filters'),
    rtypeSelect: $('rtype-select'),
    providerSelect: $('provider-select'),
    providerMsg: $('provider-msg'),
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

  // Render the limited markdown Synthea emits: H1/H2, bullets, paragraphs.
  // All input is escaped first; we then promote a handful of safe constructs.
  function renderNoteMarkdown(text) {
    if (!text) return '<p class="text-sm text-slate-500 italic">(empty)</p>';
    const lines = String(text).replace(/\r\n/g, '\n').split('\n');
    const out = [];
    let inList = false;
    let paragraph = [];

    const flushPara = () => {
      if (paragraph.length) {
        out.push(`<p class="text-sm leading-relaxed">${paragraph.join(' ')}</p>`);
        paragraph = [];
      }
    };
    const closeList = () => {
      if (inList) { out.push('</ul>'); inList = false; }
    };

    for (const raw of lines) {
      const line = raw.replace(/\t/g, '  ');
      const trimmed = line.trim();
      if (!trimmed) { flushPara(); closeList(); continue; }

      let m;
      if ((m = trimmed.match(/^##\s+(.+)$/))) {
        flushPara(); closeList();
        out.push(`<h5 class="font-semibold text-sm text-slate-700 mt-3">${escapeHtml(m[1])}</h5>`);
        continue;
      }
      if ((m = trimmed.match(/^#\s+(.+)$/))) {
        flushPara(); closeList();
        out.push(`<h4 class="font-semibold text-sm uppercase tracking-wide text-slate-500 mt-3">${escapeHtml(m[1])}</h4>`);
        continue;
      }
      if ((m = trimmed.match(/^[-*]\s+(.+)$/))) {
        flushPara();
        if (!inList) { out.push('<ul class="list-disc list-inside text-sm space-y-0.5 mt-1">'); inList = true; }
        out.push(`<li>${escapeHtml(m[1])}</li>`);
        continue;
      }
      // ISO date line at the top of every Synthea note — promote to a date label.
      if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed) && out.length === 0) {
        out.push(`<p class="text-xs text-slate-500 tabular-nums">${escapeHtml(trimmed)}</p>`);
        continue;
      }
      closeList();
      paragraph.push(escapeHtml(trimmed));
    }
    flushPara(); closeList();
    return out.join('\n');
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
    // PDF spec calls for an "AI summary snippet" on every card. Prefer
    // h.summary_snippet (patient-level AI summary); fall back to the matched
    // resource excerpt only when no AI summary exists for the patient.
    const aiAvailable = !!(h.summary_snippet && h.summary_snippet.length);
    const bodyText = aiAvailable
      ? h.summary_snippet
      : (h.snippet || '').slice(0, 220) + ((h.snippet || '').length > 220 ? '…' : '');
    const matchHint = aiAvailable
      ? `<p class="mt-1 text-xs text-slate-400">Matched ${badge.label}${date ? ' · ' + escapeHtml(date) : ''}</p>`
      : '';
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
        <p class="mt-2 text-sm text-slate-700">${escapeHtml(bodyText)}</p>
        ${matchHint}
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

  function _hasAnyFilter() {
    return !!state.resourceType || !!state.dateFrom || !!state.dateTo;
  }

  async function runSearch() {
    // No query AND no filters → idle hint state.
    if (!state.query && !_hasAnyFilter()) {
      state.results = [];
      clearResultsDom();
      showOnly('hint');
      return;
    }
    const reqId = ++state.requestId;
    showOnly('loading');
    setStatus(state.query ? 'Searching…' : 'Listing matches…');

    const payload = {
      query: state.query,
      top_k: 5,
      resource_types: state.resourceType ? [state.resourceType] : null,
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

  function onResourceTypeChange(e) {
    state.resourceType = e.target.value || '';
    runSearch();
  }

  function clearAllFilters() {
    state.resourceType = '';
    state.dateFrom = null;
    state.dateTo = null;
    ui.dateFrom.value = '';
    ui.dateTo.value = '';
    if (ui.rtypeSelect) ui.rtypeSelect.value = '';
    runSearch();
  }

  // ------------------------- Detail modal ---------------------------------

  let lastFocused = null;
  let currentPatientId = null;

  async function openDetail(patientId) {
    lastFocused = document.activeElement;
    currentPatientId = patientId;
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

  async function generateAISummary(force = false) {
    if (!currentPatientId) return;
    const btn = document.getElementById('gen-ai-btn');
    const banner = document.getElementById('ai-banner');
    const provLabel = state.provider
      ? (state.providers.find(p => p.id === state.provider)?.name || state.provider)
      : 'LLM';
    if (btn) { btn.disabled = true; btn.textContent = force ? 'Regenerating…' : `Calling ${provLabel}…`; }
    if (banner) banner.hidden = true;
    setStatus(`Calling ${provLabel}…`);
    try {
      const params = new URLSearchParams();
      if (force) params.set('force', 'true');
      if (state.provider) params.set('provider', state.provider);
      const qs = params.toString();
      const url = `/patient/${encodeURIComponent(currentPatientId)}/summarize${qs ? '?' + qs : ''}`;
      const res = await fetch(url, { method: 'POST' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = body.detail || `HTTP ${res.status}`;
        throw new Error(msg);
      }
      // Re-fetch the full patient detail so linked_resources stay rendered.
      const detail = await fetch(`/patient/${encodeURIComponent(currentPatientId)}`).then(r => r.json());
      renderDetail(detail);
      setStatus(body.cached
        ? `Loaded cached AI summary (${body.provider}).`
        : `AI summary generated by ${body.provider}.`);
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = force ? 'Regenerate AI summary' : 'Generate AI summary'; }
      if (banner) {
        banner.hidden = false;
        banner.textContent = String(err.message || err);
      }
      setStatus('AI summary failed.');
    }
  }

  async function loadProviders() {
    try {
      const res = await fetch('/providers');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const list = await res.json();
      state.providers = list;
      const active = list.find(p => p.active);
      state.provider = active ? active.id : (list[0] && list[0].id) || null;
      renderProviderSelect();
    } catch (err) {
      ui.providerSelect.innerHTML = '<option value="">unavailable</option>';
      ui.providerMsg.textContent = String(err.message || err);
    }
  }

  function renderProviderSelect() {
    if (!ui.providerSelect) return;
    ui.providerSelect.innerHTML = state.providers.map(p => {
      const label = `${p.name} · ${p.model}${p.healthy ? '' : ' (unhealthy)'}`;
      const sel = p.id === state.provider ? ' selected' : '';
      return `<option value="${escapeHtml(p.id)}"${sel}>${escapeHtml(label)}</option>`;
    }).join('');
    updateProviderMsg();
  }

  function updateProviderMsg() {
    const p = state.providers.find(x => x.id === state.provider);
    if (!p) return;
    ui.providerMsg.textContent = p.healthy ? '' : p.message;
    ui.providerMsg.className = p.healthy
      ? 'text-slate-400 hidden sm:inline'
      : 'text-amber-700 hidden sm:inline';
  }

  const SUMMARY_SOURCE_BADGE = {
    ai: { label: 'AI-generated', cls: 'bg-blue-100 text-blue-700 border-blue-200' },
    extractive: { label: 'Extracted from notes', cls: 'bg-slate-100 text-slate-700 border-slate-300' },
    none: { label: 'No summary', cls: 'bg-slate-100 text-slate-500 border-slate-300' },
  };

  function renderDetail(d) {
    ui.modalSubtitle.textContent = `${d.mrn} · DOB ${d.dob || '—'} · ${d.gender || 'unknown'}`;
    ui.modalTitle.textContent = d.display_name || 'Patient';

    const parts = [];
    // Summary section
    if (d.summary) {
      const s = d.summary;
      const srcBadge = SUMMARY_SOURCE_BADGE[d.summary_source || 'extractive'];
      const list = (arr) => arr && arr.length
        ? `<ul class="list-disc list-inside text-sm space-y-0.5 mt-1">${arr.map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul>`
        : '<p class="text-sm text-slate-500 italic mt-1">None recorded.</p>';
      const isAI = d.summary_source === 'ai';
      const btnLabel = isAI ? 'Regenerate AI summary' : 'Generate AI summary';
      parts.push(`
        <section class="flex items-center gap-2 flex-wrap">
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">Summary</h3>
          <span class="text-xs px-2 py-0.5 rounded-full border ${srcBadge.cls}">${srcBadge.label}</span>
          <button id="gen-ai-btn" type="button"
                  class="ml-auto text-xs px-3 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">
            ${btnLabel}
          </button>
        </section>
        <p id="ai-banner" hidden class="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"></p>
        <section>
          <h4 class="text-xs uppercase tracking-wide text-slate-400">Chief concern</h4>
          <p class="mt-1 text-sm">${escapeHtml(s.chief_concern)}</p>
        </section>
        <section>
          <h4 class="text-xs uppercase tracking-wide text-slate-400">Key diagnoses</h4>
          ${list(s.key_diagnoses)}
        </section>
        <section>
          <h4 class="text-xs uppercase tracking-wide text-slate-400">Recent reports</h4>
          ${list(s.recent_media)}
        </section>
        <section>
          <h4 class="text-xs uppercase tracking-wide text-slate-400">Flagged anomalies</h4>
          ${list(s.anomalies)}
        </section>
        <section class="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-800">
          ${escapeHtml(s.disclaimer)}
        </section>`);
    } else {
      parts.push(`
        <section class="flex items-center gap-2">
          <p class="text-sm text-slate-500 italic">No clinical text available for this patient.</p>
          <button id="gen-ai-btn" type="button"
                  class="ml-auto text-xs px-3 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700">
            Generate AI summary
          </button>
        </section>
        <p id="ai-banner" hidden class="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"></p>`);
    }

    // Linked resources (collapsible, sorted newest first by backend)
    if (d.linked_resources && d.linked_resources.length) {
      const VISIBLE = 25;
      const visible = d.linked_resources.slice(0, VISIBLE);
      const rows = visible.map((lr, idx) => {
        const badge = RTYPE_BADGE[lr.resource_type] || { label: lr.resource_type, cls: '' };
        const preview = (lr.content || '').slice(0, 180).replace(/\s+/g, ' ').trim();
        const rendered = renderNoteMarkdown(lr.content || '');
        return `
        <li class="border-b last:border-b-0 py-2">
          <details data-idx="${idx}">
            <summary class="cursor-pointer flex items-center justify-between gap-3 text-sm">
              <span class="text-slate-700 truncate">${escapeHtml(lr.title || '—')}</span>
              <span class="flex items-center gap-2 text-xs shrink-0">
                <span class="px-2 py-0.5 rounded-full border ${badge.cls}">${badge.label}</span>
                <span class="text-slate-500 tabular-nums">${escapeHtml(lr.date || '—')}</span>
              </span>
            </summary>
            ${preview ? `<p class="mt-1.5 text-xs text-slate-500">${escapeHtml(preview)}${(lr.content || '').length > 180 ? '…' : ''}</p>` : ''}
            <div class="mt-2 bg-slate-50 border border-slate-200 rounded p-3 space-y-1 text-slate-800">${rendered}</div>
          </details>
        </li>`;
      }).join('');
      const overflow = d.linked_resources.length > VISIBLE
        ? `<p class="text-xs text-slate-500 mt-2">Showing latest ${VISIBLE} of ${d.linked_resources.length}.</p>`
        : '';
      parts.push(`
        <section>
          <h3 class="font-semibold text-sm uppercase tracking-wide text-slate-500">
            Linked FHIR resources (${d.linked_resources.length})
          </h3>
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
  if (ui.rtypeSelect) ui.rtypeSelect.addEventListener('change', onResourceTypeChange);
  ui.clearFilters.addEventListener('click', clearAllFilters);

  ui.modalClose.addEventListener('click', closeModal);
  ui.modal.addEventListener('click', (e) => {
    // backdrop click closes (but not clicks inside the content)
    if (e.target === ui.modal) closeModal();
  });
  // Delegate the AI-summary button click since it's re-rendered with the modal body.
  ui.modalBody.addEventListener('click', (e) => {
    const btn = e.target.closest('#gen-ai-btn');
    if (btn) {
      const isRegen = btn.textContent.trim().startsWith('Regenerate');
      generateAISummary(isRegen);
    }
  });
  document.addEventListener('keydown', focusTrap);

  if (ui.providerSelect) {
    ui.providerSelect.addEventListener('change', (e) => {
      state.provider = e.target.value || null;
      updateProviderMsg();
    });
  }

  // Focus the search box on load
  ui.search.focus();
  loadProviders();
})();
