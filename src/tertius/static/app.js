// Polls /api/status. Holds no job state of its own: the server is the truth,
// so a reload or a second tab picks up exactly where the job actually is.
const $ = (id) => document.getElementById(id);

const POLL_IDLE = 2000;
const POLL_RUNNING = 1000;
let pollTimer = null;

async function api(path, options) {
  const res = await fetch(path, options);
  let body = {};
  try { body = await res.json(); } catch (_) { /* non-JSON (e.g. 500 page) */ }
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
  return body;
}

const jsonPost = (path, payload) =>
  api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });

function collectOptions() {
  const formats = [...document.querySelectorAll('.opt-format:checked')].map((c) => c.value);
  return {
    model_size: $('opt-model').value,
    device: $('opt-device').value,
    compute_type: $('opt-compute').value,
    language: $('opt-language').value.trim() || null,
    formats,
  };
}

function note(id, message, isError) {
  const el = $(id);
  el.textContent = message || '';
  el.style.color = isError ? 'var(--bad)' : '';
}

function basename(p) {
  const parts = String(p).split(/[\\/]/);
  return parts[parts.length - 1];
}

function formatBytes(n) {
  if (!n) return '0 MB';
  const mb = n / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(0)} MB`;
}

// --- theme -----------------------------------------------------------------
// Dark is the default; the choice sticks across reloads.
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('theme-icon').textContent = theme === 'dark' ? '☀' : '☾';
  $('theme-label').textContent = theme === 'dark' ? 'Light' : 'Dark';
}

function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

applyTheme(localStorage.getItem('tertius-theme') === 'light' ? 'light' : 'dark');

$('btn-theme').onclick = () => {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  localStorage.setItem('tertius-theme', next);
  applyTheme(next);
};

function renderDownload(status) {
  const panel = $('download-panel');
  const downloading = status.phase === 'downloading_model';
  const loading = status.phase === 'loading_model';
  if (!downloading && !loading) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const d = status.download || {};
  const model = d.model ? ` (${d.model})` : '';

  if (loading) {
    $('download-title').textContent = `Loading model into memory…${model}`;
    $('download-bar').style.width = '100%';
    $('download-text').textContent = 'Already downloaded — just starting it up.';
    return;
  }

  $('download-title').textContent = `Downloading model${model}…`;
  if (d.total) {
    // Percentage comes from the hub's bars; the size shown is the measured
    // download size, because those bars overlap and overstate the bytes.
    const pct = Math.min(100, Math.round((d.downloaded / d.total) * 100));
    $('download-bar').style.width = `${pct}%`;
    $('download-text').textContent = d.expected_bytes
      ? `${pct}% of about ${formatBytes(d.expected_bytes)}`
      : `${pct}%`;
  } else {
    // Sizes arrive with the first byte-progress bar; until then, be honest.
    $('download-bar').style.width = '0%';
    $('download-text').textContent = 'Starting download…';
  }
}

function render(status) {
  const state = status.state || 'idle';
  const pill = $('job-state');
  pill.textContent = status.cancel_requested && status.running ? 'cancelling' : state;
  pill.className = `pill ${state}`;

  renderDownload(status);

  const run = status.run || {};
  const total = run.total || 0;
  const processed = run.processed || 0;
  $('progress-bar').style.width = total ? `${Math.round((processed / total) * 100)}%` : '0';
  const waitingOnModel =
    status.phase === 'downloading_model' || status.phase === 'loading_model';
  $('progress-text').textContent = total
    ? `${processed}/${total} processed — ${run.completed || 0} completed, ${run.failed || 0} failed, ${run.skipped || 0} already done` +
      (status.current_file
        ? `\nCurrent: ${basename(status.current_file)}`
        : waitingOnModel
          ? '\nWaiting for the model — see above.'
          : '')
    : 'No job yet.';
  note('job-error', status.error || '', true);

  // Cancel is cooperative and only checked between files. A file wedged inside
  // the model's native code cannot be interrupted at all, so say that plainly
  // instead of showing "cancelling" forever, and offer the thing that works.
  const stuck = status.force_stop_suggested;
  $('btn-force-stop').hidden = !stuck;
  let notice = status.notice || '';
  if (stuck) {
    const secs = Math.round(status.cancel_pending_seconds || 0);
    notice =
      `Still on "${basename(status.current_file || '')}" ${secs}s after you cancelled. ` +
      `Cancel only takes effect between files, and a file stuck inside the model ` +
      `can't be interrupted. Use Force stop — finished work is kept, and you can ` +
      `Resume afterwards.`;
  }
  const noticeEl = $('job-notice');
  noticeEl.textContent = notice;
  noticeEl.className = notice ? 'note warn-text' : 'note';

  const s = status.summary || {};
  $('counts').innerHTML = ['total', 'pending', 'in_progress', 'done', 'failed', 'skipped']
    .map((k) => `<span>${k.replace('_', ' ')}: <b>${s[k] || 0}</b></span>`)
    .join('');

  const banner = $('resume-banner');
  if (status.can_resume) {
    banner.hidden = false;
    $('resume-detail').textContent = `${s.pending || 0} of ${s.total || 0} file(s) still pending in ${status.output_dir}.`;
  } else {
    banner.hidden = true;
  }

  $('btn-start').disabled = status.running;
  $('btn-resume').disabled = status.running;
  $('btn-retry').disabled = status.running || !(s.failed > 0);
  $('btn-cancel').disabled = !status.running;

  const rows = (status.files || []).map((f) => {
    const links = (f.outputs || [])
      .map((o) => {
        const name = basename(o);
        return `<a href="/api/transcript?name=${encodeURIComponent(name)}" target="_blank">${name}</a>`;
      })
      .join(' ');
    const detail = f.error
      ? f.error
      : [f.language ? `lang ${f.language}` : '', f.duration ? `${f.duration.toFixed(1)}s` : '']
          .filter(Boolean)
          .join(' · ');
    const remove = status.running
      ? ''
      : `<button data-remove="${encodeURIComponent(f.path)}">remove</button>`;
    return `<tr>
      <td class="file" title="${f.path}">${f.name}</td>
      <td class="status-${f.status}">${f.status}</td>
      <td class="detail">${detail || ''}</td>
      <td>${links}</td>
      <td>${remove}</td>
    </tr>`;
  });
  $('queue').querySelector('tbody').innerHTML =
    rows.join('') || '<tr><td colspan="5" class="detail">Queue is empty.</td></tr>';

  document.querySelectorAll('[data-remove]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        const status = await jsonPost('/api/queue/remove', {
          path: decodeURIComponent(btn.dataset.remove),
        });
        render(status.status);
      } catch (err) {
        note('add-note', err.message, true);
      }
    };
  });
}

async function poll() {
  clearTimeout(pollTimer);
  let interval = POLL_IDLE;
  try {
    const status = await api('/api/status');
    render(status);
    interval = status.running ? POLL_RUNNING : POLL_IDLE;
  } catch (err) {
    note('job-error', `lost contact with the server: ${err.message}`, true);
  }
  pollTimer = setTimeout(poll, interval);
}

// --- model comparison + machine suitability ---------------------------------
const VERDICT_LABEL = {
  ok: ['Fine', 'ok'],
  tight: ['Tight', 'warn'],
  risky: ['Too big', 'bad'],
  unknown: ['Unknown', 'muted'],
};

let systemCache = null;

async function loadSystem() {
  const device = $('opt-device').value;
  const compute = $('opt-compute').value;
  systemCache = await api(
    `/api/system?device=${encodeURIComponent(device)}&compute_type=${encodeURIComponent(compute)}`,
  );
  return systemCache;
}

// A GPU existing and a GPU being usable are different things. Say so on load,
// rather than letting someone discover it part-way through their first batch.
function renderCudaBanner(sys) {
  const runtime = (sys && sys.cuda_runtime) || {};
  const banner = $('cuda-banner');
  if (runtime.state !== 'missing') {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  $('cuda-detail').textContent =
    ` ${sys.gpu_name || 'A CUDA GPU'} was detected, but the CUDA runtime libraries ` +
    `it needs aren't installed. Install them (about 1.2 GB) by running this in the ` +
    `Tertius folder:`;
  $('cuda-command').textContent =
    '.venv\\Scripts\\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12';
}

function describeMachine(sys) {
  const parts = [];
  if (sys.cpu_count) parts.push(`${sys.cpu_count} CPU cores`);
  if (sys.ram_bytes) parts.push(`${formatBytes(sys.ram_bytes)} RAM`);
  if (sys.cuda_devices) {
    parts.push(`GPU: ${sys.gpu_name || 'CUDA device'}${sys.vram_bytes ? ` (${formatBytes(sys.vram_bytes)} VRAM)` : ''}`);
  } else {
    parts.push('no CUDA GPU detected — models run on the CPU');
  }
  return `This machine: ${parts.join(' · ')}`;
}

function renderModelTable(data) {
  $('system-summary').textContent = describeMachine(data.system);
  const rows = data.models.map((m) => {
    const [label, cls] = VERDICT_LABEL[m.verdict] || VERDICT_LABEL.unknown;
    const reason = m.reason ? ` title="${m.reason.replace(/"/g, '&quot;')}"` : '';
    return `<tr>
      <td><code>${m.model}</code></td>
      <td>${formatBytes(m.download_bytes)}</td>
      <td>${m.cached === null ? '?' : m.cached ? 'yes' : 'not yet'}</td>
      <td>${m.speed || ''}</td>
      <td class="detail">${m.quality || ''}</td>
      <td class="verdict-${cls}"${reason}>${label}${m.reason ? ' ⓘ' : ''}</td>
    </tr>`;
  });
  $('model-table').querySelector('tbody').innerHTML = rows.join('');
}

async function refreshModelAdvice() {
  try {
    const data = await loadSystem();
    renderCudaBanner(data.system);
    renderModelTable(data);
    const chosen = data.models.find((m) => m.model === $('opt-model').value);
    const messages = [];
    if (chosen && chosen.verdict !== 'ok' && chosen.reason) {
      messages.push(`${chosen.model}: ${chosen.reason}`);
    }
    if (data.compute_warning) messages.push(data.compute_warning);
    if ($('opt-device').value === 'cuda' && !data.system.cuda_devices) {
      messages.push('Device is set to cuda but no CUDA GPU was detected — the job will fail to start.');
    }
    const warning = $('model-warning');
    warning.textContent = messages.join('  ');
    warning.className = messages.length ? 'note warn-text' : 'note';
  } catch (err) {
    $('model-warning').textContent = '';
  }
}

$('btn-model-info').onclick = async () => {
  const panel = $('model-info');
  panel.hidden = !panel.hidden;
  if (!panel.hidden) await refreshModelAdvice();
};
$('btn-model-info-close').onclick = () => {
  $('model-info').hidden = true;
};
['opt-model', 'opt-device', 'opt-compute'].forEach((id) => {
  $(id).onchange = refreshModelAdvice;
});

$('btn-browse').onclick = async () => {
  const button = $('btn-browse');
  button.disabled = true;
  note('add-note', 'Folder picker open — check for a dialog window.');
  try {
    const res = await jsonPost('/api/browse-folder', { initial: $('scan-dir').value.trim() });
    if (res.cancelled) {
      note('add-note', 'No folder chosen.');
    } else {
      $('scan-dir').value = res.path;
      note('add-note', `Selected ${res.path} — now press "Scan & queue".`);
    }
  } catch (err) {
    note('add-note', err.message, true);
  } finally {
    button.disabled = false;
  }
};

$('btn-scan').onclick = async () => {
  const directory = $('scan-dir').value.trim();
  if (!directory) return note('add-note', 'Enter a folder path first.', true);
  note('add-note', 'Scanning…');
  try {
    const found = await api('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory, recursive: $('scan-recursive').checked }),
    });
    if (!found.count) return note('add-note', `No media files found in ${found.directory}.`);
    const queued = await jsonPost('/api/queue', { files: found.files });
    note('add-note', `Found ${found.count} file(s); queued ${queued.added} new.`);
    render(queued.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
};

$('btn-upload').onclick = async () => {
  const input = $('upload-files');
  if (!input.files.length) return note('add-note', 'Choose files to upload first.', true);
  const form = new FormData();
  [...input.files].forEach((f) => form.append('files', f));
  note('add-note', `Uploading ${input.files.length} file(s)…`);
  try {
    const res = await api('/api/upload', { method: 'POST', body: form });
    const rejected = res.rejected.length ? ` (skipped: ${res.rejected.join(', ')})` : '';
    note('add-note', `Queued ${res.saved.length} uploaded file(s)${rejected}.`);
    input.value = '';
    render(res.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
};

$('btn-start').onclick = async () => {
  note('job-error', '');
  try {
    render(await jsonPost('/api/job/start', {
      options: collectOptions(),
      output_dir: $('opt-outdir').value.trim() || undefined,
    }));
  } catch (err) {
    note('job-error', err.message, true);
  }
  poll();
};

$('btn-resume').onclick = async () => {
  note('job-error', '');
  try {
    render(await jsonPost('/api/job/resume', {}));
  } catch (err) {
    note('job-error', err.message, true);
  }
  poll();
};

$('btn-cancel').onclick = async () => {
  try {
    render(await jsonPost('/api/job/cancel', {}));
  } catch (err) {
    note('job-error', err.message, true);
  }
};

$('btn-force-stop').onclick = async () => {
  const button = $('btn-force-stop');
  button.disabled = true;
  try {
    const res = await jsonPost('/api/job/force-stop', {});
    clearTimeout(pollTimer); // the server is going away; stop asking it things
    note('job-error', '');
    $('job-notice').textContent = res.message;
    $('job-state').textContent = 'stopped';
  } catch (err) {
    // A server that dies before answering is a successful force stop.
    clearTimeout(pollTimer);
    $('job-notice').textContent =
      'Tertius has stopped. Relaunch it and press Resume to carry on.';
  }
};

$('btn-retry').onclick = async () => {
  try {
    const res = await jsonPost('/api/job/retry-failed', {});
    note('job-error', '');
    render(res.status);
  } catch (err) {
    note('job-error', err.message, true);
  }
};

poll();
// Tell the user up front if their default model suits this machine.
refreshModelAdvice();
