// Polls /api/status. Holds no job state of its own: the server is the truth,
// so a reload or a second tab picks up exactly where the job actually is. The
// only client-owned state is what has not been submitted yet — the settings in
// the rail, and whether a cancel is waiting on its confirmation.
const $ = (id) => document.getElementById(id);

const POLL_IDLE = 2000;
const POLL_RUNNING = 1000;
let pollTimer = null;

let confirmingCancel = false;
let settingsRestored = false;
let lastRunState = null;
let lastRunSignature = null;
let missedPolls = 0;

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

// --- formatting ------------------------------------------------------------

const esc = (value) =>
  String(value == null ? '' : value).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const basename = (p) => String(p).split(/[\\/]/).pop();

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** 41:20, or 1:12:38 once it passes an hour. */
function clock(seconds) {
  if (!seconds && seconds !== 0) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** "6 h 42 m" for spans of hours, "18 min" below that. */
function span(seconds) {
  if (!seconds && seconds !== 0) return null;
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const h = Math.floor(total / 3600);
  const m = Math.round((total % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, '0')} m` : `${m} min`;
}

function formatBytes(n) {
  if (!n) return '0 MB';
  const mb = n / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(0)} MB`;
}

function note(id, message, isError) {
  const el = $(id);
  el.textContent = message || '';
  el.className = `caption${isError ? ' error-text' : ''}`;
}

// --- theme -----------------------------------------------------------------
// Dark is the default; the choice sticks across reloads. The switch is instant
// on purpose — a cross-fade looks cheap.

function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelectorAll('[data-theme-choice]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.themeChoice === theme));
  });
}

document.querySelectorAll('[data-theme-choice]').forEach((button) => {
  button.onclick = () => {
    localStorage.setItem('tertius-theme', button.dataset.themeChoice);
    applyTheme(button.dataset.themeChoice);
  };
});
applyTheme(currentTheme());

// --- settings in the rail --------------------------------------------------

let device = 'auto';
const formats = new Set([...document.querySelectorAll('.chip')].map((c) => c.dataset.format));

function paintDevice() {
  document.querySelectorAll('.seg').forEach((seg) => {
    seg.setAttribute('aria-checked', String(seg.dataset.device === device));
  });
}

function paintFormats() {
  document.querySelectorAll('.chip').forEach((chip) => {
    chip.setAttribute('aria-pressed', String(formats.has(chip.dataset.format)));
  });
}

document.querySelectorAll('.seg').forEach((seg) => {
  seg.onclick = () => {
    if (seg.disabled) return;
    device = seg.dataset.device;
    paintDevice();
    refreshModelAdvice();
  };
});

document.querySelectorAll('.chip').forEach((chip) => {
  chip.onclick = () => {
    const format = chip.dataset.format;
    if (formats.has(format)) {
      // At least one format has to survive, or a run would write nothing.
      if (formats.size === 1) return note('add-note', 'At least one output format is needed.', true);
      formats.delete(format);
    } else {
      formats.add(format);
    }
    paintFormats();
  };
});

paintDevice();
paintFormats();

// Language codes come from Whisper's own list; the browser knows their names,
// so no hand-written table can go stale or wrong.
(function nameLanguages() {
  const select = $('opt-language');
  let display = null;
  try { display = new Intl.DisplayNames(['en'], { type: 'language' }); } catch (_) { /* older browser */ }
  const options = [...select.options].slice(1);
  options.forEach((option) => {
    let name = option.value;
    try { name = display ? display.of(option.value) : option.value; } catch (_) { /* not a known tag */ }
    option.textContent = name === option.value ? option.value : `${name} · ${option.value}`;
  });
  options
    .sort((a, b) => a.textContent.localeCompare(b.textContent))
    .forEach((option) => select.appendChild(option));
})();

function collectOptions() {
  return {
    model_size: $('opt-model').value,
    device,
    compute_type: $('opt-compute').value,
    language: $('opt-language').value || null,
    formats: [...formats],
    use_reference_text: $('opt-use-text').checked,
    alignment_granularity: $('opt-granularity').value,
  };
}

/** Take the settings the server last ran with, once, at startup. */
function restoreSettings(status) {
  const options = status.options;
  if (settingsRestored || !options) return;
  settingsRestored = true;
  if (options.model_size) $('opt-model').value = options.model_size;
  if (options.compute_type) $('opt-compute').value = options.compute_type;
  if (options.device) { device = options.device; paintDevice(); }
  $('opt-language').value = options.language || '';
  if (Array.isArray(options.formats) && options.formats.length) {
    formats.clear();
    options.formats.forEach((f) => formats.add(f));
    paintFormats();
  }
  if (options.alignment_granularity) $('opt-granularity').value = options.alignment_granularity;
  // Off unless the queue in front of you actually uses it. The saved option
  // alone is not enough: `use_reference_text` sticks in the state file from
  // whenever it was last run, so honouring it meant opening a folder full of
  // ordinary transcription work with the box already ticked, weeks later.
  //
  // The queue is the honest answer. A file set to be timestamped, or waiting
  // on a decision about its text, means the mode is genuinely in use — and
  // those are exactly the files that would break if the box came up clear.
  const queueWantsText = (status.files || [])
    .some((f) => f.mode === 'align' || f.mode === 'undecided');
  if (queueWantsText) {
    $('opt-use-text').checked = true;
    $('granularity-row').hidden = false;
    $('textdir-row').hidden = false;
  }
  if (status.reference_dir) $('opt-textdir').value = status.reference_dir;
  const savedDir = localStorage.getItem('tertius-source');
  if (savedDir && !$('scan-dir').value) $('scan-dir').value = savedDir;
  const recursive = localStorage.getItem('tertius-recursive');
  if (recursive !== null) $('scan-recursive').checked = recursive === '1';
}

$('scan-recursive').onchange = () =>
  localStorage.setItem('tertius-recursive', $('scan-recursive').checked ? '1' : '0');

// --- source ----------------------------------------------------------------

async function scanAndQueue(directory) {
  if (!directory) return note('add-note', 'Choose a folder first.', true);
  localStorage.setItem('tertius-source', directory);
  note('add-note', 'Scanning…');
  try {
    const found = await jsonPost('/api/scan', {
      directory,
      recursive: $('scan-recursive').checked,
    });
    if (!found.count) return note('add-note', `No audio or video files in ${found.directory}.`);
    // Pass the scanned folder so the output directory can mirror its structure.
    const queued = await jsonPost('/api/queue', {
      files: found.files,
      base_dir: found.directory,
      match_reference_text: $('opt-use-text').checked,
    });
    let message = `Found ${plural(found.count, 'file', 'files')}; queued ${queued.added} new.`;
    if ($('opt-use-text').checked) {
      message += ` Matched text for ${queued.matched_text}; ${queued.needs_choice} need a choice.`;
    }
    note('add-note', message);
    render(queued.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
}

$('btn-browse').onclick = async () => {
  const button = $('btn-browse');
  button.disabled = true;
  note('add-note', 'Folder picker open — check for a dialog window.');
  try {
    const picked = await jsonPost('/api/browse-folder', { initial: $('scan-dir').value.trim() });
    if (picked.cancelled) {
      note('add-note', 'No folder chosen.');
    } else {
      $('scan-dir').value = picked.path;
      await scanAndQueue(picked.path);
    }
  } catch (err) {
    note('add-note', err.message, true);
  } finally {
    button.disabled = false;
  }
};

$('scan-dir').onkeydown = (event) => {
  if (event.key === 'Enter') scanAndQueue($('scan-dir').value.trim());
};

$('btn-pick-files').onclick = () => $('upload-files').click();
$('upload-files').onchange = () => {
  if ($('upload-files').files.length) uploadFiles([...$('upload-files').files]);
};

async function uploadFiles(files) {
  if (!files.length) return;
  const form = new FormData();
  files.forEach((f) => form.append('files', f));
  // .txt files upload alongside the audio and are paired by name.
  form.append('match_reference_text', $('opt-use-text').checked ? '1' : '0');
  note('add-note', `Copying ${plural(files.length, 'file', 'files')} in…`);
  try {
    const res = await api('/api/upload', { method: 'POST', body: form });
    const rejected = res.rejected.length ? ` Skipped: ${res.rejected.join(', ')}.` : '';
    const texts = res.texts.length ? ` and ${plural(res.texts.length, 'text file', 'text files')}` : '';
    let message = `Queued ${plural(res.saved.length, 'file', 'files')}${texts}.${rejected}`;
    if ($('opt-use-text').checked) {
      message += ` Matched text for ${res.matched_text}; ${res.needs_choice} need a choice.`;
    }
    note('add-note', message);
    $('upload-files').value = '';
    render(res.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
}

// --- drag & drop -----------------------------------------------------------
// The whole window takes audio. Folders cannot be read from a drop, so those
// still go through Browse.

let dragDepth = 0;

function showVeil(bad) {
  const veil = $('drop-veil');
  veil.hidden = false;
  veil.classList.toggle('is-bad', Boolean(bad));
}

function hideVeil() {
  dragDepth = 0;
  $('drop-veil').hidden = true;
}

window.addEventListener('dragenter', (event) => {
  if (![...event.dataTransfer.types].includes('Files')) return;
  dragDepth += 1;
  showVeil(false);
});

window.addEventListener('dragover', (event) => {
  if ([...event.dataTransfer.types].includes('Files')) event.preventDefault();
});

window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) hideVeil();
});

window.addEventListener('drop', (event) => {
  if (![...event.dataTransfer.types].includes('Files')) return;
  event.preventDefault();
  hideVeil();
  const files = [...event.dataTransfer.files];
  if (files.length) uploadFiles(files);
});

// --- text timestamping -----------------------------------------------------

const applyReferenceMode = (enabled) =>
  jsonPost('/api/queue/reference-mode', {
    enabled,
    reference_dir: $('opt-textdir').value.trim(),
  });

$('opt-use-text').onchange = async () => {
  const enabled = $('opt-use-text').checked;
  $('granularity-row').hidden = !enabled;
  $('textdir-row').hidden = !enabled;
  // Re-evaluate what is already queued, so ticking the box after adding files
  // does something visible instead of silently nothing.
  try {
    const res = await applyReferenceMode(enabled);
    if (enabled) {
      note('add-note', `Text matching on: ${res.matched} matched, ${res.needs_choice} need a choice.`);
    } else if (res.reverted) {
      note('add-note', `Text matching off: ${res.reverted} back to normal transcription.`);
    } else {
      note('add-note', '');
    }
    render(res.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
};

$('btn-browse-outdir').onclick = async () => {
  const button = $('btn-browse-outdir');
  button.disabled = true;
  note('add-note', 'Folder picker open — check for a dialog window.');
  try {
    const picked = await jsonPost('/api/browse-folder', {
      initial: $('opt-outdir').value.trim(),
    });
    if (picked.cancelled) {
      note('add-note', 'No folder chosen.');
    } else {
      $('opt-outdir').value = picked.path;
      // Say what changing this means, rather than letting it be discovered on
      // the next run: each folder carries its own history of what is done.
      note('add-note',
        `Transcripts will go to ${picked.path}. Anything still queued comes too.`);
    }
  } catch (err) {
    note('add-note', err.message, true);
  } finally {
    button.disabled = false;
  }
};

$('btn-browse-textdir').onclick = async () => {
  const button = $('btn-browse-textdir');
  button.disabled = true;
  note('add-note', 'Folder picker open — check for a dialog window.');
  try {
    const picked = await jsonPost('/api/browse-folder', { initial: $('opt-textdir').value.trim() });
    if (picked.cancelled) {
      note('add-note', 'No folder chosen.');
    } else {
      $('opt-textdir').value = picked.path;
      const res = await applyReferenceMode($('opt-use-text').checked);
      note('add-note',
        `Looked in ${res.reference_dir || 'each audio file’s own folder'}: ` +
        `${res.matched} matched, ${res.needs_choice} still without text.`);
      render(res.status);
    }
  } catch (err) {
    note('add-note', err.message, true);
  } finally {
    button.disabled = false;
  }
};

$('btn-rematch-text').onclick = async () => {
  try {
    const res = await jsonPost('/api/queue/rematch-text', {});
    note('add-note', res.matched
      ? `Found text files for ${plural(res.matched, 'more file', 'more files')}.`
      : 'Still no matching text files found.');
    render(res.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
};

const decideAll = async (mode) => {
  try {
    const res = await jsonPost('/api/queue/decide-all', { mode });
    note('add-note', `Set ${plural(res.changed, 'file', 'files')} to ${mode}.`);
    render(res.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
};
$('btn-all-transcribe').onclick = () => decideAll('transcribe');
$('btn-all-skip').onclick = () => decideAll('skip');

// --- job control -----------------------------------------------------------

async function begin() {
  hidePanel('panel-error');
  try {
    render(await jsonPost('/api/job/start', {
      options: collectOptions(),
      output_dir: $('opt-outdir').value.trim() || undefined,
    }));
  } catch (err) {
    showError(err.message);
  }
  poll();
}

async function cancelRun() {
  confirmingCancel = false;
  try {
    render(await jsonPost('/api/job/cancel', {}));
  } catch (err) {
    showError(err.message);
  }
}

async function forceStop() {
  try {
    const res = await jsonPost('/api/job/force-stop', {});
    clearTimeout(pollTimer); // the server is going away; stop asking it things
    showPanel('panel-notice', res.message);
  } catch (err) {
    // A server that dies before answering is a successful force stop.
    clearTimeout(pollTimer);
    showPanel('panel-notice',
      'Tertius has stopped. Relaunch it and press Begin to carry on.');
  }
}

async function retryFailed() {
  try {
    const res = await jsonPost('/api/job/retry-failed', {});
    hidePanel('panel-error');
    render(res.status);
  } catch (err) {
    showError(err.message);
  }
}

async function openOutput() {
  try {
    await jsonPost('/api/open-output', {});
  } catch (err) {
    showError(err.message);
  }
}

// --- panels ----------------------------------------------------------------

function showPanel(id, text) {
  const panel = $(id);
  panel.hidden = false;
  if (text != null) {
    const body = panel.querySelector('.panel-body');
    if (body) body.textContent = text;
  }
}

const hidePanel = (id) => { $(id).hidden = true; };

function showError(message, title) {
  $('panel-error-title').textContent = title || 'The run stopped.';
  showPanel('panel-error', message);
}

// --- the status band -------------------------------------------------------

function elapsedOf(file) {
  return file.started_at && file.finished_at ? file.finished_at - file.started_at : null;
}

/** How much faster than realtime this run has been, from finished files. */
function realtimeFactor(files) {
  let audio = 0;
  let wall = 0;
  files.forEach((f) => {
    const spent = elapsedOf(f);
    if (f.status === 'done' && f.duration && spent > 0) {
      audio += f.duration;
      wall += spent;
    }
  });
  return wall > 0 ? audio / wall : null;
}

/** Progress weighted by audio length, not file count: a 72-minute chapter is
 *  not one twelfth of the work. Files with no known length take the average. */
function progressOf(status) {
  const files = status.files || [];
  const known = files.map((f) => f.duration).filter(Boolean);
  const average = known.length ? known.reduce((a, b) => a + b, 0) / known.length : 1;
  const active = status.active || {};
  let total = 0;
  let done = 0;
  let failed = 0;
  files.forEach((f) => {
    const weight = f.duration || average;
    total += weight;
    if (f.status === 'done' || f.status === 'skipped') done += weight;
    else if (f.status === 'failed') failed += weight;
    else if (f.status === 'in_progress') done += weight * (active.progress || 0);
  });
  return total ? { done: done / total, failed: failed / total } : { done: 0, failed: 0 };
}

function audioTotal(files) {
  const seconds = files.reduce((sum, f) => sum + (f.duration || 0), 0);
  return seconds || null;
}

function bandModel(status) {
  const s = status.summary || {};
  const files = status.files || [];
  const done = s.done || 0;
  const failed = s.failed || 0;
  const total = s.total || 0;
  const processed = done + failed + (s.skipped || 0);
  const audio = audioTotal(files);

  if (status.phase === 'downloading_model' || status.phase === 'loading_model') {
    const d = status.download || {};
    const pct = d.total ? Math.min(100, Math.round((d.downloaded / d.total) * 100)) : null;
    return {
      tone: 'running',
      headline: status.phase === 'loading_model' ? 'Loading the model' : 'Fetching the model',
      counter: status.phase === 'loading_model'
        ? `${d.model || ''} — already downloaded`
        : pct === null
          ? 'starting the download'
          : `${d.model || ''} · ${pct}% of about ${formatBytes(d.expected_bytes)}`,
      right: 'one-time, for this model size',
      progress: pct === null ? 0 : pct / 100,
      stats: [],
    };
  }

  if (status.running) {
    const rate = realtimeFactor(files);
    const remainingAudio = files
      .filter((f) => f.status === 'pending')
      .reduce((sum, f) => sum + (f.duration || 0), 0);
    const bits = [];
    if (rate && remainingAudio) bits.push(`≈ ${span(remainingAudio / rate)} remaining`);
    if (rate) bits.push(`${rate.toFixed(1)}× realtime`);
    return {
      tone: 'running',
      headline: status.cancel_requested ? 'Finishing this file' : 'Transcribing',
      counter: `${processed + 1} of ${total}`,
      right: bits.join(' · '),
      stats: [
        ['Done', done],
        ['Pending', s.pending || 0],
        failed ? ['Failed', failed, 'danger'] : null,
        audio ? ['Audio', span(audio)] : null,
      ],
    };
  }

  if (status.state === 'error') {
    return {
      tone: 'danger',
      headline: 'The run stopped',
      counter: `${plural(done, 'file written', 'files written')} · ${s.pending || 0} still pending`,
      buttons: [['Retry failed', retryFailed, failed ? '' : 'hidden'],
                ['Open output folder', openOutput, 'filled']],
      stats: [['Done', done], ['Failed', failed, 'danger'], ['Pending', s.pending || 0]],
    };
  }

  if (status.state === 'cancelled' && (s.pending || 0) > 0) {
    return {
      tone: 'paused',
      headline: 'Stopped',
      counter: `${done} of ${total} · ${plural(s.pending, 'file', 'files')} still to go`,
      buttons: [['Resume', begin, 'accent']],
      progressTone: 'paused',
      stats: [['Done', done], ['Pending', s.pending || 0],
              audio ? ['Audio', span(audio)] : null],
    };
  }

  if (status.state === 'completed' || (total > 0 && processed === total && processed > 0)) {
    const rate = realtimeFactor(files);
    const words = files.reduce((sum, f) => sum + (f.words || 0), 0);
    if (failed) {
      return {
        tone: 'danger',
        headline: failed === 1 ? 'Finished with one failure' : `Finished with ${failed} failures`,
        counter: `${done} written · ${plural(failed, 'unreadable', 'unreadable')}`,
        buttons: [['Retry failed', retryFailed, ''], ['Open output folder', openOutput, 'filled']],
        progressTone: 'success',
        stats: completionStats(status, files, rate, words),
      };
    }
    return {
      tone: 'success',
      headline: 'The batch is finished',
      counter: `${done} of ${total}${status.elapsed_seconds ? ` · ${span(status.elapsed_seconds)} elapsed` : ''}`,
      buttons: [['Open output folder', openOutput, 'filled']],
      progressTone: 'success',
      stats: completionStats(status, files, rate, words),
    };
  }

  if (!total) {
    return {
      tone: 'idle',
      headline: 'Nothing gathered yet',
      counter: 'choose a folder, or drop files anywhere',
      stats: [],
    };
  }

  return {
    tone: 'idle',
    headline: done ? 'Ready to carry on' : 'Ready to write',
    counter: `${plural(total, 'file', 'files')} gathered`,
    right: audio ? `${span(audio)} of audio` : '',
    stats: [
      ['Pending', s.pending || 0],
      done ? ['Already done', done, 'success'] : null,
      failed ? ['Failed', failed, 'danger'] : null,
      audio ? ['Audio', span(audio)] : null,
    ],
  };
}

function completionStats(status, files, rate, words) {
  const audio = audioTotal(files);
  return [
    status.elapsed_seconds ? ['Elapsed', span(status.elapsed_seconds)] : null,
    audio ? ['Audio', span(audio)] : null,
    rate ? ['Average', `${rate.toFixed(1)}× realtime`] : null,
    words ? ['Words', words.toLocaleString()] : null,
  ];
}

function renderBand(status) {
  const model = bandModel(status);
  const progress = model.progress != null
    ? { done: model.progress, failed: 0 }
    : progressOf(status);

  $('band-dot').dataset.tone = model.tone;
  const headline = $('band-headline');
  if (headline.textContent !== model.headline) headline.textContent = model.headline;
  headline.dataset.tone = model.tone;
  $('band-counter').textContent = model.counter || '';

  const fill = $('band-fill');
  fill.style.width = `${Math.round(progress.done * 100)}%`;
  fill.dataset.tone = model.progressTone || '';
  $('band-fill-failed').style.width = `${Math.round(progress.failed * 100)}%`;
  $('band-track').setAttribute('aria-valuenow', Math.round(progress.done * 100));

  const right = $('band-right');
  right.innerHTML = '';
  (model.buttons || []).forEach(([label, handler, variant]) => {
    if (variant === 'hidden') return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn ${variant === 'filled' ? 'btn-filled' : variant === 'accent' ? 'btn-accent' : 'btn-plain'}`;
    button.textContent = label;
    button.onclick = handler;
    right.appendChild(button);
  });
  if (model.right && !(model.buttons || []).length) {
    right.textContent = model.right;
  }

  $('band-stats').innerHTML = (model.stats || [])
    .filter(Boolean)
    .map(([label, value, tone]) =>
      `<span>${esc(label)}<b${tone ? ` data-tone="${tone}"` : ''}>${esc(value)}</b></span>`)
    .join('');
}

// --- the run section -------------------------------------------------------

// What renderRun would draw. Compared before touching the DOM, because
// rebuilding the controls on a 2s poll silently ate clicks: a press that spans
// a tick puts mousedown on one button and mouseup on its replacement, and the
// browser fires no click at all. That is the "I pressed Begin and nothing
// happened, so I pressed it again" bug.
function runSignature(status) {
  const s = status.summary || {};
  return [
    status.running ? 'running' : 'idle',
    confirmingCancel ? 'confirming' : '',
    status.cancel_requested ? 'stopping' : '',
    status.force_stop_suggested ? 'force' : '',
    s.pending || 0,
    (s.done || 0) + (s.failed || 0),
    s.total || 0,
  ].join('|');
}

function renderRun(status, force = false) {
  const signature = runSignature(status);
  if (!force && signature === lastRunSignature) return;
  lastRunSignature = signature;

  const s = status.summary || {};
  const pending = s.pending || 0;
  const box = $('run-controls');
  box.innerHTML = '';
  const caption = $('run-caption');

  if (status.running) {
    caption.textContent =
      'Nothing leaves this machine. You may close the tab; the scribe keeps working.';
    if (confirmingCancel) {
      box.innerHTML =
        `<div class="run-confirm"><p>Stop after the file being transcribed now? ` +
        `The ${plural(pending, 'file', 'files')} still pending stay in the queue.</p>` +
        `<div class="run-pair">` +
        `<button type="button" class="btn" id="btn-confirm-cancel">Stop the run</button>` +
        `<button type="button" class="btn" id="btn-keep-going">Keep going</button>` +
        `</div></div>`;
      $('btn-confirm-cancel').onclick = cancelRun;
      $('btn-keep-going').onclick = () => { confirmingCancel = false; renderRun(status, true); };
      return;
    }
    const stopping = status.cancel_requested;
    const pair = document.createElement('div');
    pair.className = 'run-pair';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn';
    cancel.textContent = stopping ? 'Stopping…' : 'Cancel';
    cancel.disabled = stopping;
    cancel.title = 'Stop after the file being transcribed now. Finished files are kept.';
    cancel.onclick = () => { confirmingCancel = true; renderRun(status, true); };
    pair.appendChild(cancel);
    if (status.force_stop_suggested) {
      const force = document.createElement('button');
      force.type = 'button';
      force.className = 'btn btn-danger';
      force.textContent = 'Force stop';
      force.title = 'Shut Tertius down now. Finished work is kept; relaunch and press Begin.';
      force.onclick = forceStop;
      pair.appendChild(force);
    }
    box.appendChild(pair);
    return;
  }

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'run-primary';
  const again = (s.done || 0) > 0 || (s.failed || 0) > 0;
  button.textContent = pending
    ? `${again ? 'Begin again' : 'Begin'} — ${plural(pending, 'file', 'files')}`
    : again ? 'Begin again' : 'Begin';
  button.disabled = pending === 0;
  button.title = pending
    ? 'Transcribe everything still pending. The job runs on this machine; you can close the tab.'
    : 'Nothing is pending — add files first.';
  button.onclick = begin;
  box.appendChild(button);

  caption.textContent = !s.total
    ? 'Nothing leaves this machine. Choose a folder to begin.'
    : pending === 0
      ? 'Nothing leaves this machine. Every file in the queue is finished.'
      : 'Nothing leaves this machine. The model runs here, on your own hardware.';
}

// --- the queue -------------------------------------------------------------

const RANK = { in_progress: 0, done: 1, failed: 1, skipped: 1, pending: 2 };
const MAX_ROWS = 200;

/** 60 bars, deterministic per file: the same recording always draws the same
 *  waveform. A stand-in for the real envelope, which would mean decoding the
 *  audio a second time just to draw it. */
function waveform(path, progress) {
  let hash = 2166136261;
  for (let i = 0; i < path.length; i += 1) {
    hash = Math.imul(hash ^ path.charCodeAt(i), 16777619);
  }
  const bars = [];
  for (let i = 0; i < 60; i += 1) {
    hash = Math.imul(hash ^ (hash >>> 15), 2246822507);
    hash ^= hash >>> 13;
    const noise = ((hash >>> 0) % 1000) / 1000;
    // A slow swell across the bar so it reads as speech rather than static.
    const swell = 0.55 + 0.45 * Math.sin((i / 60) * Math.PI * 3.2);
    const height = Math.round(4 + noise * swell * 24);
    const lit = i / 60 < progress;
    bars.push(`<i class="${lit ? 'lit' : ''}" style="height:${height}px"></i>`);
  }
  return `<div class="waveform" aria-hidden="true">${bars.join('')}</div>`;
}

function outputLinks(file) {
  const links = (file.outputs || []).map((output) => {
    const name = basename(output);
    const relative = file.subdir ? `${file.subdir}/${name}` : name;
    const label = name.split('.').pop();
    return `<a href="/api/transcript?name=${encodeURIComponent(relative)}" target="_blank"
              title="Open ${esc(name)}">${esc(label)}</a>`;
  });
  return links.join('') || '<span class="em-dash">—</span>';
}

function stateCell(file, status) {
  const active = status.active || {};
  if (file.status === 'in_progress') {
    const pct = file.path === active.path && active.progress != null
      ? ` ${Math.round(active.progress * 100)}%`
      : '';
    return `<span class="state-running">Transcribing${pct}</span>`;
  }
  if (file.status === 'done') {
    const spent = clock(elapsedOf(file));
    return `<span class="state-done">Done${spent ? ` · ${spent}` : ''}</span>`;
  }
  if (file.status === 'failed') return '<span class="state-failed">Failed</span>';
  if (file.status === 'skipped') return 'Skipped';
  return 'Waiting';
}

/** The cause, without the copy of the file's own path most decoders tack on —
 *  the row already says which file this is, and the full text stays on hover. */
function shortError(message) {
  return String(message || 'Failed.').replace(/:?\s*'[^']*'\s*$/, '');
}

/** The second line under a file name: why it will be treated the way it is. */
function subLine(file, running) {
  const path = encodeURIComponent(file.path);
  if (file.status === 'failed') {
    return `<div class="q-sub is-error">
      <span class="clamp" title="${esc(file.error || '')}">${esc(shortError(file.error))}</span>
      <button type="button" class="linkish" data-retry="${path}"
              title="Put this file back in the queue">Retry</button></div>`;
  }
  if (file.mode === 'align') {
    const name = basename(file.reference_text || '');
    return `<div class="q-sub is-text">Timestamping ${esc(name)}
      ${running ? '' : `<button type="button" class="linkish" data-attach="${path}"
        title="Choose a different text file for this recording">change</button>`}</div>`;
  }
  if (file.mode === 'undecided') {
    const where = (file.searched || []).join('\n');
    return `<div class="q-sub is-ask"><span title="Looked in:\n${esc(where)}">No matching text file.</span>
      ${running ? '' : `<button type="button" class="linkish" data-mode="transcribe" data-path="${path}"
          title="Transcribe this one normally">transcribe it</button>
        <button type="button" class="linkish" data-mode="skip" data-path="${path}"
          title="Leave this one out of the run">skip it</button>
        <button type="button" class="linkish" data-attach="${path}"
          title="Choose the text file for this recording">choose a text file…</button>`}</div>`;
  }
  if (file.mode === 'skip' && file.status === 'pending') {
    return `<div class="q-sub">Set to skip.
      ${running ? '' : `<button type="button" class="linkish" data-mode="transcribe" data-path="${path}"
        title="Transcribe this one after all">transcribe it instead</button>`}</div>`;
  }
  return '';
}

function renderQueue(status) {
  const files = [...(status.files || [])];
  const running = Boolean(status.running);
  const active = status.active || {};

  files.sort((a, b) => {
    const rank = (RANK[a.status] ?? 3) - (RANK[b.status] ?? 3);
    if (rank) return rank;
    return (a.finished_at || 0) - (b.finished_at || 0);
  });

  const shown = files.slice(0, MAX_ROWS);
  const rows = shown.map((file) => {
    const name = file.subdir ? `${file.subdir}/${file.name}` : file.name;
    const length = clock(file.duration) || '<span class="em-dash">—</span>';
    const kill = running
      ? ''
      : `<button type="button" data-remove="${encodeURIComponent(file.path)}"
                 title="Take this file out of the queue" aria-label="Remove ${esc(name)}">✕</button>`;
    const cells =
      `<div class="q-file" title="${esc(file.path)}">${esc(name)}${subLine(file, running)}</div>
       <div class="q-len">${length}</div>
       <div class="q-state">${stateCell(file, status)}</div>
       <div class="q-out">${outputLinks(file)}</div>
       <div class="q-kill">${kill}</div>`;

    if (file.status === 'in_progress') {
      const progress = file.path === active.path ? (active.progress || 0) : 0;
      const excerpt = file.path === active.path ? (active.excerpt || '') : '';
      return `<div class="qrow is-active" data-status="in_progress">
        <div class="qrow-main">${cells}</div>
        ${waveform(file.path, progress)}
        <p class="excerpt">${excerpt ? `“…${esc(excerpt)}…”` : ''}</p>
      </div>`;
    }
    const failed = file.status === 'failed' ? ' is-failed' : '';
    return `<div class="qrow${failed}" data-status="${file.status}">${cells}</div>`;
  });

  if (files.length > shown.length) {
    rows.push(`<div class="queue-more">…and ${files.length - shown.length} more.</div>`);
  }

  $('queue').innerHTML = rows.join('') ||
    `<p class="queue-empty">The queue is empty. Choose a folder in <b>Source</b>,
      or drop audio files anywhere on this window.</p>`;

  wireQueueButtons();
}

function wireQueueButtons() {
  document.querySelectorAll('[data-remove]').forEach((button) => {
    button.onclick = async () => {
      try {
        const res = await jsonPost('/api/queue/remove', {
          path: decodeURIComponent(button.dataset.remove),
        });
        render(res.status);
      } catch (err) {
        note('add-note', err.message, true);
      }
    };
  });

  document.querySelectorAll('[data-mode]').forEach((button) => {
    button.onclick = async () => {
      try {
        const res = await jsonPost('/api/queue/mode', {
          path: decodeURIComponent(button.dataset.path),
          mode: button.dataset.mode,
        });
        render(res.status);
      } catch (err) {
        showError(err.message);
      }
    };
  });

  document.querySelectorAll('[data-retry]').forEach((button) => {
    button.onclick = async () => {
      try {
        const res = await jsonPost('/api/queue/retry', {
          path: decodeURIComponent(button.dataset.retry),
        });
        hidePanel('panel-error');
        render(res.status);
      } catch (err) {
        showError(err.message);
      }
    };
  });

  document.querySelectorAll('[data-attach]').forEach((button) => {
    button.onclick = async () => {
      button.disabled = true;
      note('add-note', 'File picker open — check for a dialog window.');
      try {
        const picked = await jsonPost('/api/browse-text-file', {});
        if (picked.cancelled) {
          note('add-note', 'No text file chosen.');
        } else {
          const res = await jsonPost('/api/queue/mode', {
            path: decodeURIComponent(button.dataset.attach),
            mode: 'align',
            reference_text: picked.path,
          });
          note('add-note', `Using ${basename(picked.path)} for this recording.`);
          render(res.status);
        }
      } catch (err) {
        note('add-note', err.message, true);
      } finally {
        button.disabled = false;
      }
    };
  });
}

// --- render ----------------------------------------------------------------

// --- clearing the queue ----------------------------------------------------

// The last summary seen, so the confirmation can say what is about to go
// without asking the server again mid-click.
let lastSummary = {};

function renderQueueBar(status) {
  lastSummary = status.summary || {};
  const total = lastSummary.total || 0;
  const running = !!status.running;

  $('qbar-count').textContent = total
    ? `${total} file${total === 1 ? '' : 's'}`
    : '';

  // Hidden with an empty queue because there is nothing to clear, and while a
  // job runs because the server refuses it anyway - offering a button that can
  // only fail is worse than not offering one.
  $('btn-clear-queue').hidden = !total || running;
  if (!total || running) hidePanel('panel-clear-queue');
}

$('btn-clear-queue').onclick = () => {
  const total = lastSummary.total || 0;
  const done = lastSummary.done || 0;
  // Spell out what is being thrown away. "Clear queue?" on its own does not
  // tell you whether it is about to lose an afternoon of finished work.
  const parts = [`${total} file${total === 1 ? '' : 's'} will be removed from the queue`];
  if (done) {
    parts.push(
      `${done} of them ${done === 1 ? 'is' : 'are'} already transcribed - ` +
      `${done === 1 ? 'its transcript' : 'their transcripts'} will be kept, but ` +
      `Tertius will no longer know ${done === 1 ? 'it was' : 'they were'} done`
    );
  }
  $('panel-clear-detail').textContent = `${parts.join('. ')}.`;
  showPanel('panel-clear-queue');
};

$('btn-clear-cancel').onclick = () => hidePanel('panel-clear-queue');

$('btn-clear-confirm').onclick = async () => {
  hidePanel('panel-clear-queue');
  try {
    const res = await jsonPost('/api/queue/clear', {});
    const freed = res.bytes_reclaimed
      ? `, freeing ${(res.bytes_reclaimed / (1024 * 1024)).toFixed(1)} MB`
      : '';
    note('add-note', `Queue cleared — ${res.cleared} file${res.cleared === 1 ? '' : 's'} removed${freed}.`);
    render(res.status);
  } catch (err) {
    note('add-note', err.message, true);
  }
};

function render(status) {
  restoreSettings(status);

  renderBand(status);
  renderRun(status);
  renderQueue(status);
  renderQueueBar(status);

  if (status.error) showError(status.error); else hidePanel('panel-error');

  // Cancel is cooperative and only checked between files. A file wedged inside
  // the model's native code cannot be interrupted at all, so say that plainly
  // instead of showing "stopping" forever, and offer the thing that works.
  let notice = status.notice || '';
  if (status.force_stop_suggested) {
    const secs = Math.round(status.cancel_pending_seconds || 0);
    notice =
      `Still on "${basename(status.current_file || '')}" ${secs}s after you cancelled. ` +
      `Cancel only takes effect between files, and a file stuck inside the model ` +
      `can't be interrupted. Use Force stop — finished work is kept, and you can ` +
      `carry on afterwards.`;
  }
  if (notice) showPanel('panel-notice', notice); else hidePanel('panel-notice');

  const undecided = (status.files || []).filter((f) => f.mode === 'undecided');
  if (undecided.length) {
    // Say exactly where it looked — "no text found" is useless on its own.
    const searched = (undecided[0].searched || []).join('  ·  ');
    $('panel-missing-detail').innerHTML =
      `No <code>.txt</code> with a matching name was found for ` +
      `${plural(undecided.length, 'file', 'files')}: ` +
      `${undecided.slice(0, 3).map((f) => esc(f.name)).join(', ')}` +
      `${undecided.length > 3 ? `, and ${undecided.length - 3} more` : ''}.` +
      (searched ? `<br>Looked in: ${esc(searched)}` : '') +
      `<br>Set a <b>Text folder</b> in Settings if your text files live somewhere else — ` +
      `uploaded audio is copied into <code>_uploads</code>, so its original folder is not known.`;
    showPanel('panel-missing-text');
  } else {
    hidePanel('panel-missing-text');
  }

  // The band changing is the notification; a backgrounded tab gets the title.
  if (lastRunState === 'running' && !status.running && document.hidden) {
    document.title = status.summary && status.summary.failed
      ? '! Tertius — finished with failures'
      : '✓ Tertius — finished';
  }
  if (status.running) document.title = 'Tertius';
  lastRunState = status.running ? 'running' : status.state;
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) document.title = 'Tertius';
});

async function poll() {
  clearTimeout(pollTimer);
  let interval = POLL_IDLE;
  try {
    const status = await api('/api/status');
    missedPolls = 0;
    render(status);
    interval = status.running ? POLL_RUNNING : POLL_IDLE;
  } catch (err) {
    // One dropped poll is a reload or a hiccup, not a dead server; only say so
    // once it has actually stopped answering.
    missedPolls += 1;
    if (missedPolls > 2) {
      showError(
        `${err.message}. The job itself is unaffected — it runs in the Tertius ` +
        `process, not in this tab.`,
        'Lost contact with Tertius.');
    }
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

function renderCudaBanner(sys) {
  const runtime = (sys && sys.cuda_runtime) || {};
  // A GPU existing and a GPU being usable are different things. Say so on load,
  // rather than letting someone discover it part-way through their first batch.
  if (runtime.state !== 'missing') {
    hidePanel('panel-cuda');
    return;
  }
  $('panel-cuda-detail').textContent =
    `${sys.gpu_name || 'A CUDA GPU'} was detected, but the CUDA runtime libraries ` +
    `it needs aren't installed. Install them (about 1.2 GB) by running this in the ` +
    `Tertius folder:`;
  // The server sends the command because the path to pip is not the same on
  // Windows and Linux, and this page has no way to know which it is running on.
  $('panel-cuda-command').textContent =
    runtime.fix_command || 'pip install nvidia-cublas-cu12 nvidia-cudnn-cu12';
  showPanel('panel-cuda');
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
  $('model-table').querySelector('tbody').innerHTML = data.models.map((m) => {
    const [label, cls] = VERDICT_LABEL[m.verdict] || VERDICT_LABEL.unknown;
    const reason = m.reason ? ` title="${esc(m.reason)}"` : '';
    return `<tr>
      <td class="name">${esc(m.model)}</td>
      <td>${formatBytes(m.download_bytes)}</td>
      <td>${m.cached === null ? '?' : m.cached ? 'yes' : 'not yet'}</td>
      <td>${esc(m.speed || '')}</td>
      <td>${esc(m.quality || '')}</td>
      <td class="verdict-${cls}"${reason}>${label}${m.reason ? ' ⓘ' : ''}</td>
    </tr>`;
  }).join('');
}

async function refreshModelAdvice() {
  try {
    const data = await api(
      `/api/system?device=${encodeURIComponent(device)}` +
      `&compute_type=${encodeURIComponent($('opt-compute').value)}`);
    renderCudaBanner(data.system);
    renderModelTable(data);

    // Offering a device the machine does not have is a trap; disable it instead.
    const cuda = document.querySelector('.seg[data-device="cuda"]');
    if (cuda) {
      cuda.disabled = !data.system.cuda_devices;
      cuda.title = data.system.cuda_devices
        ? 'Force the GPU. Much faster on the bigger models.'
        : 'No CUDA GPU was detected on this machine.';
    }

    const messages = [];
    const chosen = data.models.find((m) => m.model === $('opt-model').value);
    if (chosen && chosen.verdict !== 'ok' && chosen.reason) {
      messages.push(`${chosen.model}: ${chosen.reason}`);
    }
    if (data.compute_warning) messages.push(data.compute_warning);
    if (device === 'cuda' && !data.system.cuda_devices) {
      messages.push('Device is set to cuda but no CUDA GPU was detected — the job will fail to start.');
    }
    const warning = $('model-warning');
    warning.textContent = messages.join('  ');
    warning.className = messages.length ? 'caption warn-text' : 'caption';
  } catch (err) {
    $('model-warning').textContent = '';
  }
}

$('btn-model-info').onclick = async () => {
  const panel = $('panel-model-info');
  panel.hidden = !panel.hidden;
  $('btn-model-info').setAttribute('aria-expanded', String(!panel.hidden));
  if (!panel.hidden) await refreshModelAdvice();
};
$('btn-model-info-close').onclick = () => {
  $('panel-model-info').hidden = true;
  $('btn-model-info').setAttribute('aria-expanded', 'false');
};
['opt-model', 'opt-compute'].forEach((id) => { $(id).onchange = refreshModelAdvice; });

poll();
// Tell the user up front if their default model suits this machine.
refreshModelAdvice();
