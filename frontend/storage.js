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
let newHouseholdRequested = false;
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
  row.innerHTML = '<div><strong></strong><span class="volume-location"></span><p></p></div><button class="button secondary" type="button">Browse</button><span class="badge"></span><progress max="100"></progress>';
  const browse = row.querySelector('button');
  const meter = row.querySelector('progress');
  browse.dataset.drive = drive;
  browse.setAttribute('aria-label', `Browse ${drive}`);
  meter.setAttribute('aria-label', `Disk used on ${drive}`);
  return { row, browse, meter, title: row.querySelector('strong'), location: row.querySelector('.volume-location'),
    detail: row.querySelector('p'), badge: row.querySelector('.badge') };
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
  const activeDrive = ['active', 'moving'].includes(state.mode) ? state.selected?.slice(0, 2).toUpperCase() : '';
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
    const current = volume.drive.toUpperCase() === activeDrive;
    const destination = state.mode === 'active' && moveRequested && volume.drive === view.drive;
    setText(entry.title, title);
    setText(entry.location, current ? (destination ? 'Current drive · selected destination' : 'Current drive') : 'Selected destination');
    entry.location.hidden = !current && !destination;
    entry.row.classList.toggle('selected-destination', destination);
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
  setText(el('home'), 'Open SpareDrive');
  const ready = state.volumes.some(eligible);
  const moving = state.mode === 'moving';
  const active = state.mode === 'active';
  if (!active || !state.canMove) moveRequested = false;
  if (state.mode !== 'offline' || !state.unlocked) newHouseholdRequested = false;
  el('new-household').hidden = state.mode !== 'offline' || !state.unlocked || !ready;
  setText(el('new-household'), newHouseholdRequested ? 'Reconnect existing household instead' : 'Set up a new household');
  el('unlock-panel').hidden = active || moving || state.unlocked || !ready;
  el('system-option').hidden = moving || !state.volumes.some(volume => volume.system && volume.ready);
  el('move-open').hidden = !active || !state.canMove;
  setText(el('move-open'), moveRequested ? 'Cancel move' : 'Move storage');
  const localUrl = active && !state.canMove && state.localStorageUrl;
  el('move-local').hidden = !localUrl;
  if (localUrl) {
    const link = el('move-local-link');
    link.href = localUrl;
    setText(link, localUrl);
  }
  el('move-progress').hidden = !moving;
  const finished = active && state.move?.phase === 'done';
  const failed = state.move?.phase === 'failed';
  el('move-result').hidden = !finished && !failed;
  if (finished) {
    setText(el('move-result'), `Storage moved to ${state.selected}. SpareDrive now saves changes there. The previous folder holds a backup from the time of the move.`);
    el('move-result').dataset.state = 'active';
  } else if (failed) {
    setText(el('move-result'), active ? `${state.move.error} SpareDrive still uses ${state.selected}.` : state.move.error);
    el('move-result').dataset.state = 'offline';
  }
  if (moving) {
    setStatus('Storage move in progress', 'SpareDrive is pausing uploads and changes while it copies and verifies your household data.', 'setup');
    const job = state.move;
    setText(el('move-progress-source'), job.source || state.selected || '');
    setText(el('move-progress-target'), job.target || '');
    setText(el('move-detail'), job.phase === 'waiting' ? 'Waiting for current requests to finish.' :
      job.phase === 'verifying' ? 'Verifying the database and activating the new folder.' : `${bytes(job.copied)} of ${bytes(job.total)} copied · ${job.files} of ${job.fileCount} files verified`);
    if (job.total > 0) el('move-meter').value = Math.min(100, Math.round(100 * job.copied / job.total));
    else el('move-meter').removeAttribute('value');
  } else if (active) setStatus(moveRequested ? 'Choose a destination' : 'Storage is connected',
    moveRequested ? `Currently using ${state.selected}. Browse the drive where you want your household to move.`
      : `SpareDrive uses ${state.selected}`, 'active');
  else if (state.mode === 'offline') setStatus('Household storage is unavailable',
    newHouseholdRequested ? 'Browse an available drive and choose an empty folder for the new household.'
      : `${state.selected}. ${state.detail}`, 'offline');
  else if (ready) setStatus('Data drive available', state.unlocked ? 'Browse a drive below and choose where SpareDrive should store the database and files.' : 'Unlock storage setup using the code in your terminal to browse a drive and choose a folder.', 'setup');
  else setStatus('Choose a storage drive', 'Connect a spare drive with a Windows drive letter. SpareDrive checks for changes automatically.', 'offline');
  if (view.drive && (moving || !state.unlocked || !state.volumes.some(volume => volume.drive === view.drive && eligible(volume)))) {
    query += 1;
    view = identity();
  }
  displayVolumes();
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
      moveRequested = false;
      state = null;
      query += 1;
      view = identity();
      el('move-open').hidden = true;
      el('move-local').hidden = true;
      el('move-progress').hidden = true;
      el('move-result').hidden = true;
      el('move-password').querySelector('input').value = '';
      el('home').textContent = 'Open sign-in';
      el('home').hidden = false;
      el('inventory').hidden = true;
      el('unlock-panel').hidden = true;
      el('new-household').hidden = true;
      el('browse').hidden = true;
      setStatus('Admin sign-in required', 'Sign in to SpareDrive as the administrator to browse the attached drives.', 'offline');
    } else if (!quiet || !state) report(error.message);
  } finally {
    refreshing = false;
    el('refresh').disabled = false;
  }
}

function updateChoice() {
  const reconnect = state.mode === 'offline' && !newHouseholdRequested;
  const active = state.mode === 'active';
  const moving = active && moveRequested;
  const { managed, empty } = view.listing;
  const canUseFolder = moving && !managed && empty === true && Boolean(view.path);
  if (!canUseFolder) el('move-create').checked = true;
  const useExisting = canUseFolder && el('move-existing').checked;
  el('browse-move').hidden = !active || !state.canMove || moving;
  el('choose').hidden = active && !moving;
  el('select-new').hidden = reconnect || managed;
  el('select-current').hidden = moving;
  el('select-current').disabled = choosing || !view.path || (reconnect ? !managed : managed || empty === false);
  el('move-options').hidden = !canUseFolder;
  el('move-existing').disabled = !canUseFolder;
  el('folder-label').hidden = useExisting;
  el('folder-name').required = !useExisting;
  el('move-password').hidden = !moving;
  el('move-password').querySelector('input').required = moving;
  el('move-paths').hidden = !moving || managed;
  if (moving && !managed) {
    setText(el('move-source'), state.selected);
    const parent = folderPath();
    const name = el('folder-name').value.trim();
    const separator = parent.endsWith('\\') ? '' : '\\';
    setText(el('move-target'), useExisting ? parent : name ? parent + separator + name : 'Enter a new folder name');
  }
  setText(el('select-submit'), moving ? 'Copy and switch storage' : 'Create and use folder');
  setText(el('choice-title'), moving ? 'Move household storage' : reconnect ? 'Reconnect your storage' : 'Set up storage for a new household');
  setText(el('select-current'), reconnect ? 'Reconnect this folder' : 'Use this empty folder');
  let help = 'Create a folder or select an empty one. You’ll create the first admin account next.';
  if (moving) help = managed
    ? 'This folder already contains SpareDrive data. Go up or choose another drive to select a destination.'
    : 'SpareDrive pauses household changes, verifies the copy, then switches to the destination. Keep both drives connected until it finishes.';
  else if (reconnect) help = 'Browse to the folder containing your existing SpareDrive database.';
  else if (newHouseholdRequested && !managed) help = 'Choose an empty folder for a separate household. SpareDrive saves a backup of the previous host settings.';
  else if (managed) help = 'This folder contains another SpareDrive household. Go up and create a new folder for this setup.';
  setText(el('choice-help'), help);
}

function folderPath() {
  return view.drive + '\\' + view.path.split('/').filter(Boolean).join('\\');
}

function displayFolder() {
  const { entries, managed, empty, more } = view.listing;
  el('browse').hidden = false;
  el('browse-path').textContent = folderPath();
  el('parent').disabled = !view.path;
  el('entries-table').hidden = !entries.length;
  el('browse-message').hidden = Boolean(entries.length);
  el('browse-message').textContent = managed ? 'This is a SpareDrive storage folder. Use the app’s file spaces to access managed files.'
    : empty ? 'This folder is empty.' : 'No items to display in this folder.';
  el('entries').innerHTML = entries.map(item => `<tr><td>${item.directory ? `<button class="folder-button" data-folder="${escape(item.name)}" type="button"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg><span>${escape(item.name)}</span></button>` : escape(item.name)}</td><td>${item.directory ? 'Folder' : 'File'}</td><td>${bytes(item.size)}</td><td>${escape(new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(item.modified * 1000)))}</td></tr>`).join('');
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
  if (view.drive !== drive || view.path !== path) el('move-create').checked = true;
  view = { drive, path, offset, listing };
  displayVolumes();
  displayFolder();
}

async function selectFolder(newName = '', password = '') {
  if (choosing || !view.listing) return;
  const move = state.mode === 'active' && moveRequested;
  const newHousehold = state.mode === 'offline' && newHouseholdRequested;
  if (newHousehold && !window.confirm('Create a separate household on this drive? You will create a new admin account. Your previous files stay on the original drive.')) return;
  choosing = true;
  const submit = el('select-new').querySelector('button');
  submit.disabled = true;
  updateChoice();
  try {
    const destination = { drive: view.drive, path: view.path, newName, allowSystem: includeSystem };
    const result = await request(move ? 'move' : 'select', move ? { ...destination, password } : { ...destination, newHousehold });
    if (!move) location.assign('/');
    else {
      el('move-password').querySelector('input').value = '';
      state = { ...state, mode: 'moving', move: result };
      displayState();
      el('move-progress').scrollIntoView({ block: 'start' });
    }
  } finally {
    choosing = false;
    submit.disabled = false;
    if (state && view.listing) updateChoice();
  }
  if (move) {
    await refresh(true);
    const result = el('move-result');
    if (!result.hidden) result.scrollIntoView({ block: 'start' });
  }
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
function toggleMove() {
  if (choosing || state?.mode !== 'active' || !state.canMove) return;
  report();
  moveRequested = !moveRequested;
  el('move-create').checked = true;
  el('move-password').querySelector('input').value = '';
  displayState();
  if (!moveRequested) return;
  el(view.listing ? 'choose' : 'inventory').scrollIntoView({ block: 'start' });
  if (view.listing && !view.listing.managed) el('folder-name').focus({ preventScroll: true });
  else if (view.listing) el('parent').focus({ preventScroll: true });
}

el('move-open').addEventListener('click', toggleMove);
el('browse-move').addEventListener('click', toggleMove);
el('move-options').addEventListener('change', updateChoice);
el('folder-name').addEventListener('input', updateChoice);
el('new-household').addEventListener('click', () => {
  if (choosing || state?.mode !== 'offline' || !state.unlocked) return;
  newHouseholdRequested = !newHouseholdRequested;
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
    const useExisting = moveRequested && values.get('destination') === 'existing';
    const name = useExisting ? '' : values.get('folder').trim();
    if (!useExisting && !name) throw new Error('Enter the new folder name.');
    return selectFolder(name, values.get('password'));
  });
});
el('select-current').addEventListener('click', () => run(() => selectFolder()));

await refresh();
setInterval(() => { if (!document.hidden && !authNeeded) refresh(true); }, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(true); });
