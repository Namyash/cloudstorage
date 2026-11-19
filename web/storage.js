const el = id => document.getElementById(id);
const identity = () => ({ drive: '', path: '', offset: 0, listing: null });
let state = null;
let view = identity();
let query = 0;
let refreshing = false;
let choosing = false;
let authNeeded = false;
let includeSystem = false;
let moveRequested = false;
const driveRows = new Map();
const emptyDrives = document.createElement('p');
emptyDrives.className = 'quiet-state';
emptyDrives.textContent = 'Windows currently reports no drive letters.';
let renderedDisks;

const eligible = volume => volume.eligible || (includeSystem && volume.system && volume.ready);

function escape(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function bytes(size) {
  if (size === null || size === undefined) return '—';
  const [base, unit] = [[1e9, 'GB'], [1e6, 'MB'], [1e3, 'KB'], [1, 'B']].find(([base]) => size >= base) || [1, 'B'];
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(size / base)} ${unit}`;
}

function setText(node, value) {
  if (node.textContent !== value) node.textContent = value;
}

function report(message = '') {
  el('error').textContent = message;
  el('error').hidden = !message;
}

async function request(action, payload) {
  const options = { cache: 'no-store' };
  if (payload) Object.assign(options, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Family-Drive': '1' }, body: JSON.stringify(payload) });
  const response = await fetch(`/api/storage/${action}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || 'Storage could not be accessed.'), { status: response.status });
  return data;
}

function setStatus(label, detail, mode) {
  const target = el('connection');
  const html = `<strong>${escape(label)}</strong>${escape(detail)}`;
  if (target.innerHTML !== html) target.innerHTML = html;
  target.dataset.state = mode;
}

function newDriveRow(drive) {
  const row = document.createElement('div');
  row.className = 'volume-entry';
  row.innerHTML = '<div><strong></strong><p></p></div><button class="button secondary" type="button">Browse</button><span class="badge"></span><progress max="100"></progress>';
  const browse = row.querySelector('button');
  const meter = row.querySelector('progress');
  browse.dataset.drive = drive;
  browse.setAttribute('aria-label', `Browse ${drive}`);
  meter.setAttribute('aria-label', `Disk used on ${drive}`);
  return { row, browse, meter, title: row.querySelector('strong'), detail: row.querySelector('p'), badge: row.querySelector('.badge') };
}

function displayVolumes() {
  const container = el('volumes');
  const detected = new Set(state.volumes.map(volume => volume.drive));
  for (const [drive, entry] of driveRows) {
    if (!detected.has(drive)) {
      entry.row.remove();
      driveRows.delete(drive);
    }
  }
  if (!detected.size && !emptyDrives.isConnected) container.append(emptyDrives);
  else if (detected.size && emptyDrives.isConnected) emptyDrives.remove();

  // Keep the existing controls attached while free space changes in the background.
  state.volumes.forEach((volume, index) => {
    let entry = driveRows.get(volume.drive);
    if (!entry) {
      entry = newDriveRow(volume.drive);
      driveRows.set(volume.drive, entry);
    }
    if (container.children[index] !== entry.row) container.insertBefore(entry.row, container.children[index] ?? null);
    const title = volume.label ? `${volume.drive} ${volume.label}` : volume.drive;
    const status = volume.system ? 'Windows system drive' : volume.eligible ? 'Ready' : volume.ready ? 'Unavailable' : 'No accessible volume';
    const detail = volume.ready ? `${bytes(volume.free)} free of ${bytes(volume.capacity)}` : volume.kind;
    const usage = volume.ready && volume.capacity > 0 ? Math.round(100 * (volume.capacity - volume.free) / volume.capacity) : 0;
    const canBrowse = eligible(volume) && state.unlocked && state.mode !== 'moving';
    const ready = volume.system && includeSystem ? ' · System drive' : volume.eligible && state.unlocked ? ' · Ready' : '';
    setText(entry.title, title);
    setText(entry.detail, detail + ready);
    setText(entry.badge, status);
    entry.badge.classList.toggle('role-admin', volume.eligible);
    entry.badge.classList.toggle('muted-badge', !volume.eligible);
    entry.browse.hidden = !canBrowse;
    entry.browse.disabled = choosing;
    entry.badge.hidden = canBrowse;
    entry.meter.hidden = !volume.ready;
    if (entry.meter.value !== usage) entry.meter.value = usage;
  });

  const disks = state.disks;
  const diskList = JSON.stringify(disks);
  if (renderedDisks !== diskList) {
    el('disks').innerHTML = disks?.length ? disks.map(name => `<div class="disk-entry"><strong>${escape(name)}</strong><span class="badge role-admin">Detected</span></div>`).join('') :
      `<p class="quiet-state">${disks === null ? 'Windows disk hardware information is unavailable.' : 'Windows reports no connected disk hardware.'}</p>`;
    renderedDisks = diskList;
  }
}

function displayState() {
  el('inventory').hidden = false;
  el('home').hidden = state.mode !== 'active';
  setText(el('home'), 'Open Family Drive');
  const ready = state.volumes.some(eligible);
  const moving = state.mode === 'moving';
  const active = state.mode === 'active';
  if (!active) moveRequested = false;
  el('unlock-panel').hidden = active || moving || state.unlocked || !ready;
  el('system-option').hidden = moving || !state.volumes.some(volume => volume.system && volume.ready);
  el('move-open').hidden = !active || !state.canMove;
  setText(el('move-open'), moveRequested ? 'Cancel drive change' : 'Change storage location');
  el('move-progress').hidden = !moving;
  el('move-result').hidden = !active || !['done', 'failed'].includes(state.move?.phase);
  if (active && state.move?.phase === 'done') {
    setText(el('move-result'), 'Storage move finished. Family Drive is using the new folder. The previous folder is a backup.');
    el('move-result').dataset.state = 'active';
  } else if (active && state.move?.phase === 'failed') {
    setText(el('move-result'), state.move.error);
    el('move-result').dataset.state = 'offline';
  }
  if (moving) {
    setStatus('Storage move in progress', 'Family Drive is pausing uploads and changes while it copies and verifies your household data.', 'setup');
    const job = state.move;
    setText(el('move-detail'), job.phase === 'waiting' ? 'Waiting for current requests to finish.' :
      job.phase === 'verifying' ? 'Verifying the database and activating the new folder.' : `${bytes(job.copied)} of ${bytes(job.total)} copied · ${job.files} of ${job.fileCount} files verified`);
    if (job.total > 0) el('move-meter').value = Math.min(100, Math.round(100 * job.copied / job.total));
    else el('move-meter').removeAttribute('value');
  } else if (active) setStatus('Storage is connected', moveRequested ? 'Browse the destination drive or folder below, then choose a new folder name.' : `Family Drive uses ${state.selected}`, 'active');
  else if (state.mode === 'offline') setStatus('Your storage drive is offline', `${state.selected}. ${state.detail}`, 'offline');
  else if (ready) setStatus('Data drive available', state.unlocked ? 'Browse a drive below and choose where Family Drive should store the database and files.' : 'Unlock storage setup using the code in your terminal to browse a drive and choose a folder.', 'setup');
  else setStatus('Choose a storage drive', 'Connect a spare drive with a Windows drive letter. Family Drive checks for changes automatically.', 'offline');
  displayVolumes();
  if (view.drive && (moving || !state.unlocked || !state.volumes.some(volume => volume.drive === view.drive && eligible(volume)))) {
    query += 1;
    view = identity();
  }
  el('browse').hidden = !view.listing;
  if (view.listing) updateChoice();
}

async function refresh(quiet = false) {
  if (refreshing || choosing) return;
  refreshing = true;
  if (!quiet) {
    el('refresh').disabled = true;
    report();
  }
  try {
    state = await request('state');
    authNeeded = false;
    displayState();
  } catch (error) {
    if (error.status === 401 || error.status === 403) {
      authNeeded = true;
      el('home').textContent = 'Open sign-in';
      el('home').hidden = false;
      el('inventory').hidden = true;
      el('unlock-panel').hidden = true;
      el('browse').hidden = true;
      setStatus('Admin sign-in required', 'Sign in to Family Drive as the administrator to browse the attached drives.', 'offline');
    } else if (!quiet || !state) report(error.message);
  } finally {
    refreshing = false;
    el('refresh').disabled = false;
  }
}

function updateChoice() {
  const reconnect = state.mode === 'offline';
  const moving = state.mode === 'active' && moveRequested;
  el('choose').hidden = state.mode === 'active' && !moving;
  el('select-new').hidden = reconnect || view.listing.managed;
  el('select-current').hidden = moving;
  el('select-current').disabled = choosing || !view.path || (reconnect && !view.listing.managed);
  el('move-password').hidden = !moving;
  el('move-password').querySelector('input').required = moving;
  setText(el('select-submit'), moving ? 'Copy and switch storage' : 'Create and use folder');
  setText(el('choice-title'), moving ? 'Choose new storage folder' : reconnect ? 'Reconnect your storage' : 'Choose storage folder');
  setText(el('select-current'), reconnect ? 'Reconnect this folder' : 'Use this folder');
  setText(el('choice-help'), moving ? 'Family Drive copies your accounts and files, checks the copy, and then switches. Your previous folder stays available as a backup.' : reconnect ? 'Browse to your original Family Drive folder if Windows changed the drive letter.' : 'Create a dedicated folder or use an existing Family Drive folder or an empty folder.');
}

function displayFolder() {
  const path = view.path.split('/').filter(Boolean).join('\\');
  const { entries, managed, more } = view.listing;
  el('browse').hidden = false;
  el('browse-path').textContent = `${view.drive}\\${path}`;
  el('parent').disabled = !view.path;
  el('entries-table').hidden = !entries.length;
  el('browse-message').hidden = Boolean(entries.length);
  el('browse-message').textContent = managed ? 'This is a Family Drive storage folder. Use the app’s file spaces to access managed files.' : 'This folder is empty.';
  el('entries').innerHTML = entries.map(item => `<tr><td>${item.directory ? `<button class="folder-button" data-folder="${escape(item.name)}" type="button">${escape(item.name)}</button>` : escape(item.name)}</td><td>${item.directory ? 'Folder' : 'File'}</td><td>${bytes(item.size)}</td><td>${escape(new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(item.modified * 1000)))}</td></tr>`).join('');
  el('pages').hidden = !more && view.offset === 0;
  el('prev').disabled = view.offset === 0;
  el('next').disabled = !more;
  el('page-number').textContent = `Page ${view.offset / 100 + 1}`;
  updateChoice();
}

async function openFolder(drive, path = '', offset = 0) {
  const id = ++query;
  const params = new URLSearchParams({ drive, path, offset, system: includeSystem ? '1' : '0' });
  const listing = await request(`folders?${params}`);
  if (id !== query) return;
  view = { drive, path, offset, listing };
  displayFolder();
}

async function selectFolder(newName = '', password = '') {
  if (choosing || !view.listing) return;
  const move = state.mode === 'active' && moveRequested;
  choosing = true;
  const submit = el('select-new').querySelector('button');
  submit.disabled = true;
  updateChoice();
  try {
    await request(move ? 'move' : 'select', { drive: view.drive, path: view.path, newName, password, allowSystem: includeSystem });
    if (!move) location.assign('/');
    else {
      moveRequested = false;
      el('move-password').querySelector('input').value = '';
    }
  } finally {
    choosing = false;
    submit.disabled = false;
    updateChoice();
  }
  if (move) await refresh(true);
}

async function run(action) {
  report();
  try {
    await action();
  } catch (error) {
    if (error.status === 401 || error.status === 503) await refresh(true);
    report(error.message);
  }
}

el('refresh').addEventListener('click', () => refresh());
el('system-drive').addEventListener('change', event => {
  includeSystem = event.target.checked;
  if (state) displayState();
});
el('move-open').addEventListener('click', () => {
  moveRequested = !moveRequested;
  el('move-password').querySelector('input').value = '';
  displayState();
});
el('volumes').addEventListener('click', event => {
  const drive = event.target.closest('[data-drive]')?.dataset.drive;
  if (drive && !choosing) run(() => openFolder(drive));
});
el('entries').addEventListener('click', event => {
  const folder = event.target.closest('[data-folder]')?.dataset.folder;
  if (folder && !choosing) run(() => openFolder(view.drive, [view.path, folder].filter(Boolean).join('/')));
});
el('parent').addEventListener('click', () => !choosing && run(() => openFolder(view.drive, view.path.split('/').slice(0, -1).join('/'))));
el('prev').addEventListener('click', () => !choosing && run(() => openFolder(view.drive, view.path, view.offset - 100)));
el('next').addEventListener('click', () => !choosing && run(() => openFolder(view.drive, view.path, view.offset + 100)));
el('unlock').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    const button = event.submitter;
    button.disabled = true;
    try {
      await request('unlock', { code: new FormData(event.target).get('code') });
      event.target.reset();
      await refresh(true);
    } finally {
      button.disabled = false;
    }
  });
});
el('select-new').addEventListener('submit', event => {
  event.preventDefault();
  run(() => {
    const values = new FormData(event.target);
    const name = values.get('folder').trim();
    if (!name) throw new Error('Enter the new folder name.');
    return selectFolder(name, values.get('password'));
  });
});
el('select-current').addEventListener('click', () => run(() => selectFolder()));

await refresh();
setInterval(() => { if (!document.hidden && !authNeeded) refresh(true); }, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(true); });
