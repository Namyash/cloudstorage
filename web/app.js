import { downloadPrivate, fileContext, importVaultKey, openText, randomBytes, recoverySettings, seal, sealText, unlockSecret } from './vault.js';

const app = document.querySelector('#app');
const dialog = document.querySelector('#dialog');
const toast = document.querySelector('#toast');
const GB = 1_000_000_000;
const vaultIdleLimit = 10 * 60 * 1000;
let data;
let page = 'overview';
let vaultKey = null;
let vaultTimer;
let lastVaultActivity = 0;
let files = [];
let search = '';
let transfer = null;
let toastTimer;

const paths = {
  drive: '<rect x="3" y="4" width="18" height="16" rx="4"/><path d="M3 14h18M7 17h.01m4 0h.01"/>',
  overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  people: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/><circle cx="9" cy="7" r="4"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
  exchange: '<path d="M3 7h16m-4-4 4 4-4 4M21 17H5m4-4-4 4 4 4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 1.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.1h-2.5v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1-1.8-1.8.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1h-.1v-2.5h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1L9.5 7l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5v-.1H15v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3L18 7l1.8 1.8-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.1v2.5h-.1a1.7 1.7 0 0 0-1.5 1Z" transform="translate(-1.5 -.8)"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m8 4 5 5-5 5m5-5H9"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.3"/><path d="m16 16 4 4"/>',
  upload: '<path d="M12 16V4m-5 5 5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  download: '<path d="M12 4v12m-5-5 5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  file: '<path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10Zm0 0v7h7"/>',
  trash: '<path d="M3 6h18m-2 0-1 14H6L5 6m4 0V3h6v3m-5 4v6m4-6v6"/>',
  shield: '<path d="M12 22s7-3.6 7-10V5l-7-3-7 3v7c0 6.4 7 10 7 10Z"/><path d="m9 12 2 2 4-4"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  edit: '<path d="m15 5 4 4m-14 6 11-11a2.8 2.8 0 0 1 4 4L9 19l-5 1Z"/>',
};

function icon(name, size = 20) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function formatSize(bytes) {
  if (!bytes) return '0 GB';
  if (bytes < 1000) return `${bytes} B`;
  const units = [[GB, 'GB'], [1_000_000, 'MB'], [1000, 'KB']];
  const [base, unit] = units.find(([base]) => bytes >= base);
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(bytes / base)} ${unit}`;
}

function formatDate(seconds) {
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(seconds * 1000));
}

function forDateInput(seconds) {
  if (!seconds) return '';
  const day = new Date(seconds * 1000);
  return new Date(day.getTime() - day.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function ratio(value, max) {
  return max ? Math.max(0, Math.min(100, 100 * value / max)) : 0;
}

async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = { 'X-Family-Drive': '1' };
  let body;
  if (options.binary) {
    headers['Content-Type'] = 'application/octet-stream';
    body = options.binary;
  } else if (options.data !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.data);
  }
  const response = await fetch(`/api/${path}`, { method, headers, body, cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(payload.error || 'Family Drive could not complete the request.'), { status: response.status });
  return payload;
}

function notice(message, bad = false) {
  toast.textContent = message;
  toast.className = bad ? 'visible error' : 'visible';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = ''; }, 5200);
}

function brand() {
  return `<div class="brand"><span class="brand-icon">${icon('drive', 21)}</span><span>Family<span class="brand-accent">Drive</span><small>PRIVATE STORAGE</small></span></div>`;
}

const roleName = role => ({ admin: 'Admin', family: 'Family', guest: 'Guest' })[role];
const isAdmin = () => data.user?.role === 'admin';
const isArchive = () => page.startsWith('archive:');
const isVaultPage = () => page === 'private' || isArchive();
const selectedVault = () => isArchive() ? data.archives.find(item => page === `archive:${item.id}`) : data.vault;

function clearVaultKey() {
  clearTimeout(vaultTimer);
  vaultKey = null;
}

function checkVaultIdle() {
  if (!vaultKey) return;
  clearTimeout(vaultTimer);
  const remaining = vaultIdleLimit - (Date.now() - lastVaultActivity);
  if (remaining > 0 || transfer) {
    vaultTimer = setTimeout(checkVaultIdle, Math.max(1000, remaining));
    return;
  }
  clearVaultKey();
  files = [];
  if (dialog.open) dialog.close();
  render();
  notice('Vault locked after 10 minutes of inactivity.');
}

function vaultActivity() {
  if (!vaultKey) return;
  if (!transfer && Date.now() - lastVaultActivity >= vaultIdleLimit) {
    checkVaultIdle();
    return;
  }
  lastVaultActivity = Date.now();
  checkVaultIdle();
}

function avatar(user, extra = '') {
  const initials = user.name.split(/\s+/).slice(0, 2).map(word => Array.from(word)[0]).join('').toUpperCase();
  return `<span class="avatar avatar-${user.role} ${extra}" aria-hidden="true">${esc(initials)}</span>`;
}

const usernameField = '<label>Username<input name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>';

function authView() {
  const setup = data.setup;
  const change = data.changePassword;
  const title = setup ? 'Set up your family drive' : change ? 'Choose your own password' : 'Welcome back';
  const description = setup ? 'Create the first admin account using the setup code on your host computer. You’ll assign storage quotas from the dashboard.' : change ? 'Replace your temporary password before opening your storage.' : 'Sign in to access your family storage.';
  app.innerHTML = `<main class="auth-shell"><aside class="auth-side">${brand()}<div class="auth-message"><div class="auth-symbol">${icon('drive', 52)}</div><h2>Your family’s files.<br>On your own drive.</h2><p>A home for the photos and documents you choose to keep.</p></div><div class="auth-foot">${icon('shield', 18)} Private family storage</div></aside>
    <section class="auth-main"><div class="auth-mobile">${brand()}</div><div class="auth-card"><h1>${title}</h1><p>${description}</p><form id="auth-form">
      ${setup ? '<label>Setup code<input name="code" autocomplete="off" required></label><label>Display name<input name="name" autocomplete="name" maxlength="60" required></label>' : ''}
      ${change ? '<label>Temporary or current password<input name="current" type="password" autocomplete="current-password" required></label>' : usernameField}
      <label>${change ? 'New password' : 'Password'}<input name="password" type="password" autocomplete="${setup || change ? 'new-password' : 'current-password'}" required></label>
      <p class="form-error" role="alert" hidden></p><button class="button primary" type="submit">${setup ? 'Create admin account' : change ? 'Save password' : 'Sign in'}</button>
      ${change ? '<button class="button text-button" type="button" data-action="logout">Sign out</button>' : ''}
    </form></div></section></main>`;
  const form = document.querySelector('#auth-form');
  form.addEventListener('submit', event => {
    event.preventDefault();
    submit(form, async values => {
      await api(setup ? 'setup' : change ? 'password' : 'login', { method: 'POST', data: values });
      await refresh();
      await navigate(isAdmin() ? 'overview' : 'private');
    });
  });
}

function navigation() {
  const items = [];
  if (isAdmin()) items.push(['overview', 'Overview', 'overview'], ['people', 'People & access', 'people']);
  items.push(['private', 'My files', 'lock']);
  if (data.user.role !== 'guest') items.push(['family', 'Family space', 'folder']);
  if ((isAdmin() && data.people.some(person => person.role === 'guest')) || data.user.exchange) items.push(['exchange', 'Guest exchange', 'exchange']);
  return items;
}

function layout(content, title) {
  const items = navigation();
  const section = isArchive() ? 'private' : page.split(':')[0];
  const group = (key, label, symbol) => `<button class="nav-link ${section === key ? 'current' : ''}" data-page="${key}" ${section === key ? 'aria-current="page"' : ''}>${icon(symbol, 19)}<span>${label}</span></button>`;
  const manage = isAdmin() ? `<div class="nav-group"><span class="nav-label">MANAGE</span>${items.slice(0, 2).map(item => group(...item)).join('')}<a class="nav-link storage-link" href="/storage">${icon('drive', 19)}<span>Storage explorer</span></a></div>` : '';
  const storage = items.slice(isAdmin() ? 2 : 0).map(item => group(...item)).join('');
  app.innerHTML = `<div class="shell"><aside class="sidebar">${brand()}
    <nav aria-label="Workspace">${manage}<div class="nav-group"><span class="nav-label">STORAGE</span>${storage}</div></nav>
    <div class="sidebar-bottom"><div class="drive-status"><span class="drive-glyph">${icon('drive', 18)}</span><span>Local storage<small><i></i> Drive connected</small></span></div>
      <div class="profile">${avatar(data.user)}<span class="profile-name">${esc(data.user.name)}<small>${roleName(data.user.role)}</small></span><button class="icon-button sidebar-button" data-action="logout" title="Sign out" aria-label="Sign out">${icon('logout', 18)}</button></div></div></aside>
    <div class="workspace"><header class="topbar"><div class="breadcrumbs"><span>Workspace</span>${icon('chevron', 14)}<strong>${esc(title)}</strong></div><button class="button settings-link" data-action="settings">${icon('settings', 19)}<span>Account</span></button></header>
    <main class="content">${content}</main></div></div>`;
  const ring = document.querySelector('.ring');
  if (ring) ring.style.setProperty('--fill', `${ring.dataset.percent}%`);
}

function pageTitle(name, tagline, actions = '') {
  return `<div class="page-title"><div><h1>${name}</h1><p>${tagline}</p></div>${actions ? `<div class="page-actions">${actions}</div>` : ''}</div>`;
}

function status(person) {
  if (!person.active) return ['Paused', 'muted'];
  if (person.expires && person.expires * 1000 <= Date.now()) return ['Expired', 'muted'];
  return ['Active', 'good'];
}

function personRows() {
  const term = search.toLowerCase().trim();
  const people = data.people.filter(person => `${person.name} ${person.username} ${person.role}`.toLowerCase().includes(term));
  if (!people.length) return '<tr><td class="empty-row" colspan="5">No matching accounts</td></tr>';
  return people.map(person => {
    const [label, color] = status(person);
    return `<tr><td><div class="person-cell">${avatar(person)}<div><strong>${esc(person.name)}</strong><small>@${esc(person.username)}${person.id === data.user.id ? ' · You' : ''}</small></div></div></td>
      <td><span class="badge role-${person.role}">${roleName(person.role)}</span></td>
      <td><div class="row-usage"><span><strong>${formatSize(person.used)}</strong><span> / ${formatSize(person.quota)}</span></span><progress max="100" value="${ratio(person.used, person.quota)}" aria-label="Quota usage"></progress></div></td>
      <td><span class="status ${color}"><i></i>${label}</span></td>
      <td><button class="icon-button row-action" data-action="edit-person" data-id="${person.id}" title="Manage ${esc(person.name)}" aria-label="Manage ${esc(person.name)}">${icon('edit', 17)}</button></td></tr>`;
  }).join('');
}

function peopleTable() {
  return `<section class="panel people-panel" aria-labelledby="people-title"><div class="panel-heading"><div><h2 id="people-title">People & access</h2><p>Manage accounts, storage quotas, and guest permissions.</p></div>
    <label class="search">${icon('search', 17)}<span class="visually-hidden">Search people</span><input id="search" type="search" placeholder="Search people" value="${esc(search)}"></label></div>
    <div class="table-scroll"><table><thead><tr><th scope="col">Name</th><th scope="col">Role</th><th scope="col">Storage</th><th scope="col">Status</th><th scope="col"><span class="visually-hidden">Manage</span></th></tr></thead><tbody id="rows">${personRows()}</tbody></table></div></section>`;
}

function overview() {
  const drive = data.drive;
  const pct = Math.round(ratio(drive.allocated, drive.allocatableCapacity));
  const family = data.people.filter(person => person.role !== 'guest').length;
  const guests = data.people.length - family;
  return `${pageTitle('Overview', 'Manage your family’s storage and access in one place.', addButton())}
    <div class="summary-grid">
      <section class="panel storage-card"><div class="summary-title"><span class="tile-icon">${icon('drive', 20)}</span><h2>Drive usage</h2></div>
        <div class="drive-main"><div><div class="big-stat">${formatSize(drive.used)}</div><p class="sub-stat">stored on your drive</p>
          <div class="legend"><span><i class="swatch assigned"></i><strong>${formatSize(drive.allocated)}</strong> allocated</span><span><i class="swatch unassigned"></i><strong>${formatSize(drive.availableToAllocate)}</strong> available to allocate</span></div></div>
          <div class="ring" data-percent="${pct}" role="img" aria-label="${pct} percent of allocatable storage assigned"><div class="ring-center"><strong>${pct}%</strong><small>allocated</small></div></div></div>
        <div class="card-footer"><span>Drive capacity <strong>${formatSize(drive.total)}</strong></span><span>Free on disk <strong>${formatSize(drive.free)}</strong></span></div>
        <p class="storage-location"><span>Storage folder</span><strong>${esc(drive.root)}</strong></p></section>
      <section class="panel access-card"><div class="summary-title"><span class="tile-icon lavender">${icon('people', 20)}</span><h2>Household access</h2></div>
        <div class="count-grid"><div><strong>${family}</strong><span>Family & admin</span></div><div><strong>${guests}</strong><span>${guests === 1 ? 'Guest' : 'Guests'}</span></div></div>
        <div class="access-note">${icon('shield', 18)}<span>Only accounts you create can sign in.</span></div></section>
    </div>${peopleTable()}`;
}

function addButton() {
  return `<button class="button primary" data-action="add-person">${icon('plus', 19)} Add person</button>`;
}

function quotaBar(used, quota) {
  return `<div class="quota-bar"><div><span>Storage used</span><strong>${formatSize(used)} / ${formatSize(quota)}</strong></div>
    <progress max="100" value="${ratio(used, quota)}" aria-label="Storage used"></progress></div>`;
}

function fileRows() {
  const term = search.toLowerCase().trim();
  const filtered = files.filter(file => file.name.toLowerCase().includes(term));
  if (!filtered.length) return `<tr><td colspan="4" class="empty-row">${term ? 'No matching files' : 'No files yet'}</td></tr>`;
  return filtered.map(file => `<tr><td><div class="person-cell"><span class="file-glyph">${icon('file', 19)}</span><div><strong class="file-name">${esc(file.name)}</strong>${!isVaultPage() ? `<small>${esc(file.by)}</small>` : ''}</div></div></td>
    <td>${formatSize(file.size)}</td><td>${formatDate(file.created)}</td><td class="file-actions"><button class="icon-button" data-action="download" data-id="${file.id}" title="Download" aria-label="Download ${esc(file.name)}" ${file.damaged || transfer ? 'disabled' : ''}>${icon('download', 19)}</button>
    ${file.canDelete ? `<button class="icon-button danger-icon" data-action="remove" data-id="${file.id}" title="Delete" aria-label="Delete ${esc(file.name)}" ${transfer ? 'disabled' : ''}>${icon('trash', 18)}</button>` : ''}</td></tr>`).join('');
}

function fileTable() {
  return `<section class="panel files-panel"><div class="panel-heading"><div><h2>Files</h2><p>${files.length} ${files.length === 1 ? 'file' : 'files'}</p></div><label class="search">${icon('search', 17)}<span class="visually-hidden">Search files</span><input id="search" type="search" placeholder="Search files" value="${esc(search)}"></label></div>
    <div class="table-scroll"><table><thead><tr><th>Name</th><th>Size</th><th>Added</th><th><span class="visually-hidden">Actions</span></th></tr></thead><tbody id="rows">${fileRows()}</tbody></table></div></section>`;
}

function transferBar() {
  if (!transfer) return '';
  return `<div class="panel transfer" role="status"><span id="transfer-message">${esc(transfer.label)}</span><progress id="transfer-progress" max="100" value="${transfer.percent}" aria-label="Transfer progress"></progress></div>`;
}

function workspaceName() {
  if (page === 'private') return 'My files';
  if (isArchive()) return 'Archived vault';
  return page === 'family' ? 'Family space' : 'Guest exchange';
}

function archiveList() {
  if (!data.archives.length) return '';
  return `<section class="panel exchange-list archived-list"><div class="archive-heading"><div><h2>Archived vaults</h2><p>These encrypted files count toward your storage quota.</p></div></div>
    ${data.archives.map(item => `<div><div class="person-cell"><span class="file-glyph">${icon('lock', 18)}</span><div><strong>${formatDate(item.created)}</strong><small>${item.fileCount} ${item.fileCount === 1 ? 'file' : 'files'}</small></div></div><button class="button secondary" data-page="archive:${item.id}">Open archive</button></div>`).join('')}</section>`;
}

function workspace() {
  const privateSpace = isVaultPage();
  const archive = isArchive();
  const familySpace = page === 'family';
  const exchange = page.startsWith('exchange:');
  const target = data.people?.find(person => page === `exchange:${person.id}`);
  const name = workspaceName();
  if (page === 'exchange' && isAdmin()) {
    return `${pageTitle(name, 'Choose a guest to open the folder you share with them.')}
      <section class="panel exchange-list">${data.people.filter(person => person.role === 'guest').map(person => `<div><div class="person-cell">${avatar(person)}<div><strong>${esc(person.name)}</strong><small>${person.exchange ? 'Guest access enabled' : 'Guest access disabled'}</small></div></div><button class="button secondary" data-page="exchange:${person.id}">Open folder ${icon('chevron', 15)}</button></div>`).join('')}</section>`;
  }
  const description = archive ? 'Open these files with the passphrase or recovery key for this archived vault.' : privateSpace ? 'Your browser encrypts your personal files before upload.' : familySpace ? 'Files here are shared with everyone in the family.' : target ? `Files shared between the admin and ${esc(target.name)}.` : 'Files shared between you and the admin.';
  const actions = archive || (privateSpace && !vaultKey) ? '' : `<button class="button primary" data-action="upload" ${transfer ? 'disabled' : ''}>${icon('upload', 19)} Upload files</button><input type="file" id="file-picker" multiple hidden>`;
  const lockButton = privateSpace && vaultKey ? `<button class="button secondary" data-action="lock" ${transfer ? 'disabled' : ''}>${icon('lock', 17)} Lock vault</button>` : '';
  const security = page === 'private' && vaultKey ? `<button class="button secondary" data-action="vault-security" ${transfer ? 'disabled' : ''}>${icon('settings', 18)} Vault security</button>` : '';
  const back = archive ? '<button class="button secondary" data-page="private">Back to My files</button>' : '';
  const familySettings = familySpace && isAdmin() ? `<button class="button secondary" data-action="family-quota">${icon('settings', 18)} Set quota</button>` : '';
  const usage = familySpace ? quotaBar(data.familyUsed, data.familyQuota) : quotaBar(data.used, data.user.quota);
  const vault = privateSpace ? selectedVault() : null;
  const locked = privateSpace ? `<section class="panel vault-panel"><span class="vault-icon">${icon('lock', 31)}</span><h2>${vault.salt ? 'Your vault is locked' : 'Set up your private vault'}</h2>
    <p>${vault.salt ? 'Unlock with your vault passphrase.' : 'Choose a separate passphrase for your files. You’ll also get a recovery key to save.'}</p><button class="button primary" data-action="vault">${vault.salt ? 'Unlock vault' : 'Set up vault'}</button>
    ${archive && vault.recoveryWrap ? '<button class="button text-button" data-action="vault-recover">Use recovery key</button>' : !archive && vault.salt ? '<button class="button text-button" data-action="vault-forgot">Forgot vault passphrase?</button>' : ''}</section>` : '';
  return `${pageTitle(name, description, back + security + lockButton + familySettings + actions)}${exchange && target && !target.exchange ? '<div class="access-banner">Guest access is disabled. You can re-enable it in People & access.</div>' : ''}${usage}${transferBar()}${privateSpace && !vaultKey ? locked : fileTable()}${page === 'private' ? archiveList() : ''}`;
}

function render() {
  if (!data.user || data.changePassword) {
    authView();
    return;
  }
  if (page === 'overview') layout(overview(), 'Overview');
  else if (page === 'people') layout(pageTitle('People & access', 'Set storage quotas and control who can use your drive.', addButton()) + peopleTable(), 'People & access');
  else layout(workspace(), workspaceName());
  document.querySelector('#search')?.addEventListener('input', event => {
    search = event.target.value;
    document.querySelector('#rows').innerHTML = page === 'overview' || page === 'people' ? personRows() : fileRows();
  });
  document.querySelector('#file-picker')?.addEventListener('change', event => {
    if (event.target.files.length) guarded(() => upload([...event.target.files]));
  });
}

function space() {
  return page === 'exchange' && !isAdmin() ? `exchange:${data.user.id}` : page;
}

async function loadFiles() {
  files = [];
  const currentPage = page;
  const encrypted = isVaultPage();
  const key = vaultKey;
  if (!data.user || ['overview', 'people'].includes(page) || (page === 'exchange' && isAdmin()) || (encrypted && !key)) return;
  const response = await api(`files?space=${encodeURIComponent(space())}`);
  const loaded = await Promise.all(response.files.map(async file => {
    if (!encrypted) return { ...file, name: file.label };
    try {
      return { ...file, name: await openText(key, file.label, fileContext(data.user.id, file, 'name')) };
    } catch {
      return { ...file, name: 'Unreadable encrypted file', damaged: true };
    }
  }));
  if (page === currentPage && (!encrypted || vaultKey === key)) files = loaded;
}

async function refresh() {
  const previous = data?.user?.id;
  const revision = data?.vault?.revision;
  data = await api('state');
  if (previous !== data.user?.id || (page === 'private' && revision !== data.vault?.revision)) clearVaultKey();
}

async function navigate(next) {
  if (transfer) { notice('Wait for the current transfer to finish.'); return; }
  if (page !== next && isVaultPage()) clearVaultKey();
  page = next;
  search = '';
  await loadFiles();
  render();
}

function formDialog(title, help, content, submitLabel, callback, extra = '') {
  dialog.innerHTML = `<div class="dialog-head"><h2 id="dialog-title">${title}</h2><button class="icon-button" type="button" data-action="close" aria-label="Close">${icon('close')}</button></div>
    ${help ? `<p class="dialog-help">${help}</p>` : ''}<form id="dialog-form">${content}<p class="form-error" role="alert" hidden></p>
    <div class="dialog-actions">${extra}<button type="button" class="button secondary" data-action="close">Cancel</button><button type="submit" class="button primary">${submitLabel}</button></div></form>`;
  if (!dialog.open) dialog.showModal();
  const form = dialog.querySelector('form');
  form.addEventListener('submit', event => {
    event.preventDefault();
    submit(form, callback);
  });
  return form;
}

async function submit(form, callback) {
  const button = form.querySelector('[type="submit"]');
  const error = form.querySelector('.form-error');
  button.disabled = true;
  error.hidden = true;
  const input = new FormData(form);
  try {
    await callback(Object.fromEntries(input.entries()));
  } catch (problem) {
    error.textContent = problem.message;
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
}

function quotaField(quota = 0) {
  return `<label>Storage quota <span class="field-note">GB</span><input name="quota" type="number" min="0" step="any" value="${quota === null ? '' : quota / GB}" required></label>`;
}

function guestFields(person = {}) {
  return `<div class="guest-fields" ${person.role === 'family' ? 'hidden' : ''}><label>Access expires <span class="field-note">Optional</span><input type="datetime-local" name="expires" value="${forDateInput(person.expires)}"></label>
    <label class="checkbox"><input type="checkbox" name="exchange" ${person.exchange ? 'checked' : ''}><span>Enable a shared folder for this guest<small>Only the guest and admin can open it.</small></span></label></div>`;
}

function guestValues(values) {
  return { expires: values.expires ? new Date(values.expires).toISOString() : null, exchange: values.exchange === 'on' };
}

function showCredential(account) {
  dialog.innerHTML = `<div class="dialog-head"><h2 id="dialog-title">Account credentials</h2><button class="icon-button" data-action="close" aria-label="Close">${icon('close')}</button></div>
    <p class="dialog-help">Send these credentials privately. ${esc(account.username)} will choose a new password on first sign-in.</p>
    <div class="credentials"><div><span>Username</span><code id="new-username">${esc(account.username)}</code></div><div><span>Temporary password</span><code id="new-password">${esc(account.temporaryPassword)}</code></div></div>
    <div class="dialog-actions"><button class="button secondary" data-action="copy">${icon('copy', 17)} Copy</button><button class="button primary" data-action="close">Done</button></div>`;
  if (!dialog.open) dialog.showModal();
  dialog.querySelector('[data-action="copy"]').focus();
}

function addPerson() {
  const form = formDialog('Add person', 'Give a family member or guest their own login and storage quota.',
    `<label>Display name<input name="name" required maxlength="60"></label>${usernameField}
    <div class="form-grid"><label>Role<select name="role"><option value="family">Family member</option><option value="guest">Guest</option></select></label>${quotaField(null)}</div>${guestFields({ role: 'family' })}`, 'Create account', async values => {
    const account = await api('people', { method: 'POST', data: { ...values, quota: Math.round(Number(values.quota) * GB), ...guestValues(values) } });
    await refresh();
    render();
    showCredential(account);
  });
  form.elements.role.addEventListener('change', () => { form.querySelector('.guest-fields').hidden = form.elements.role.value !== 'guest'; });
}

function editPerson(id) {
  const person = data.people.find(item => item.id === id);
  if (!person) return;
  formDialog('Manage account', `${esc(person.name)} · @${esc(person.username)} · ${roleName(person.role)}`,
    `${quotaField(person.quota)}<span class="field-note">${formatSize(person.used)} in use</span>
    ${person.role !== 'admin' ? `<label class="checkbox"><input type="checkbox" name="active" ${person.active ? 'checked' : ''}><span>Allow sign-in</span></label>` : ''}
    ${person.role === 'guest' ? guestFields(person) : ''}`, 'Save changes', async values => {
      const payload = { quota: Math.round(Number(values.quota) * GB), active: person.role === 'admin' || values.active === 'on' };
      if (person.role === 'guest') Object.assign(payload, guestValues(values));
      await api(`people/${id}`, { method: 'PATCH', data: payload });
      dialog.close();
      await refresh();
      render();
      notice('Account updated.');
    }, person.role === 'admin' ? '' : `<button type="button" class="button text-button left" data-action="reset" data-id="${id}">Reset password</button>`);
}

function setFamilyQuota() {
  formDialog('Family space quota', 'This quota is shared by the whole family.', quotaField(data.familyQuota), 'Save quota', async values => {
    await api('family', { method: 'PATCH', data: { quota: Math.round(Number(values.quota) * GB) } });
    dialog.close();
    await refresh();
    render();
    notice('Family quota updated.');
  });
}

const passphraseInput = '<label>Vault passphrase<input name="current" type="password" maxlength="256" autocomplete="off" required></label>';
const recoveryInput = '<label>Recovery key<input name="recovery" type="password" maxlength="80" autocomplete="off" autocapitalize="none" spellcheck="false" required></label>';
const newPassphraseInputs = '<label>New vault passphrase<input name="passphrase" type="password" maxlength="256" minlength="16" autocomplete="new-password" required></label><label>Confirm passphrase<input name="confirm" type="password" maxlength="256" minlength="16" autocomplete="new-password" required></label><span class="field-note">Use at least 16 characters.</span>';

function showVaultDialog(title, help, body) {
  dialog.innerHTML = `<div class="dialog-head"><h2 id="dialog-title">${title}</h2><button class="icon-button" data-action="close" aria-label="Close">${icon('close')}</button></div>
    <p class="dialog-help">${help}</p>${body}`;
  if (!dialog.open) dialog.showModal();
}

function showRecoveryKey(code) {
  showVaultDialog('Save your recovery key', 'Keep this key somewhere you can find it while locked out. It can unlock your private files, so keep it private.',
    `<div class="credentials"><code id="recovery-key">${esc(code)}</code></div><div class="dialog-actions"><button class="button secondary" data-action="copy-recovery">${icon('copy', 17)} Copy key</button><button class="button primary" data-action="close">Done</button></div>`);
}

function confirmedPassphrase(values) {
  if (values.passphrase !== values.confirm) throw new Error('The passphrases do not match.');
  return values.passphrase;
}

async function openVaultPage(key, expectedPage) {
  if (page !== expectedPage) return;
  vaultKey = key;
  lastVaultActivity = Date.now();
  checkVaultIdle();
  await navigate(expectedPage);
}

async function saveVaultSecurity(secret, passphrase, current, method) {
  const { code, settings } = await recoverySettings(data.user.id, secret, passphrase, current.verifier);
  await api('vault', { method, data: { ...settings, revision: current.revision } });
  showRecoveryKey(code);
  await refresh();
}

function vaultDialog() {
  const scope = page;
  const current = selectedVault();
  if (current.salt) {
    formDialog('Unlock private vault', 'Enter the passphrase for this vault.', passphraseInput, 'Unlock', async values => {
      const { secret, key } = await unlockSecret(data.user.id, current, values.current);
      secret.fill(0);
      dialog.close();
      await openVaultPage(key, scope);
    });
    return;
  }
  formDialog('Set up your private vault', 'Choose a passphrase for your private files. You’ll get a recovery key to save after setup.', newPassphraseInputs, 'Create vault', async values => {
    const passphrase = confirmedPassphrase(values);
    const secret = randomBytes(32);
    try {
      const key = await importVaultKey(secret);
      await saveVaultSecurity(secret, passphrase, current, 'POST');
      await openVaultPage(key, scope);
    } finally {
      secret.fill(0);
    }
  });
}

function forgotVault() {
  const vault = data.vault;
  const recover = vault.recoveryWrap ? '<button class="button primary" data-action="vault-recover">Use recovery key</button>' : '';
  const details = vault.fileCount ? 'Starting fresh moves the existing encrypted files into an archive. You can unlock that archive later with its original credentials.' : 'You can reset this empty vault using your Family Drive sign-in password.';
  showVaultDialog('Forgot vault passphrase?', details,
    `<div class="dialog-actions"><button class="button ${recover ? 'secondary' : 'primary'}" data-action="vault-reset">${vault.fileCount ? 'Start fresh and keep archive' : 'Reset empty vault'}</button>${recover}</div>`);
}

function resetVaultDialog() {
  const current = data.vault;
  const help = current.fileCount ? 'Your existing files will move to a locked archive. Enter your sign-in password to continue and create a fresh vault.' : 'Enter your sign-in password to clear the vault settings and choose a new passphrase.';
  formDialog('Reset private vault', help,
    '<label>Family Drive sign-in password<input name="password" type="password" autocomplete="current-password" required></label>',
    current.fileCount ? 'Archive files and reset' : 'Reset vault', async values => {
      const result = await api('vault/reset', { method: 'POST', data: { password: values.password, revision: current.revision } });
      clearVaultKey();
      dialog.close();
      await refresh();
      await navigate('private');
      notice(result.archived ? `${result.archived} ${result.archived === 1 ? 'file preserved' : 'files preserved'} in an encrypted archive.` : 'Vault reset. Choose a new vault passphrase.');
    });
}

function recoverVault() {
  const current = selectedVault();
  const scope = page;
  const archived = isArchive();
  formDialog(archived ? 'Unlock with recovery key' : 'Reset with recovery key', archived ? 'Enter the recovery key saved for this archived vault.' : 'Enter your saved recovery key and choose a new passphrase. Your existing files stay in My files.',
    recoveryInput + (archived ? '' : newPassphraseInputs), archived ? 'Unlock archive' : 'Reset passphrase', async values => {
      const { secret, key } = await unlockSecret(data.user.id, current, values.recovery, true);
      try {
        if (archived) dialog.close();
        else await saveVaultSecurity(secret, confirmedPassphrase(values), current, 'PATCH');
        await openVaultPage(key, scope);
      } finally {
        secret.fill(0);
      }
    });
}

function vaultSecurity() {
  showVaultDialog('Vault security', 'The vault locks after 10 minutes of inactivity. You can change its passphrase or generate a new recovery key.',
    `<div class="dialog-actions"><button class="button secondary" data-action="vault-new-key">${data.vault.recoveryWrap ? 'Replace recovery key' : 'Create recovery key'}</button><button class="button primary" data-action="vault-change">Change passphrase</button></div>`);
}

function updateVaultSecurity(changePassphrase) {
  const current = data.vault;
  const help = changePassphrase ? 'Confirm your current vault passphrase and choose a new one. Save the new recovery key afterward.' : 'Confirm your vault passphrase. The key you generate replaces any previous recovery key for this vault.';
  formDialog(changePassphrase ? 'Change vault passphrase' : 'Generate recovery key', help,
    passphraseInput + (changePassphrase ? newPassphraseInputs : ''), changePassphrase ? 'Change passphrase' : 'Generate key', async values => {
      const next = changePassphrase ? confirmedPassphrase(values) : values.current;
      const { secret, key } = await unlockSecret(data.user.id, current, values.current);
      try {
        await saveVaultSecurity(secret, next, current, 'PATCH');
        await openVaultPage(key, 'private');
      } finally {
        secret.fill(0);
      }
    });
}

function updateProgress(label, fraction) {
  transfer = { label, percent: Math.round(fraction * 100) };
  document.querySelector('#transfer-message').textContent = label;
  document.querySelector('#transfer-progress').value = transfer.percent;
}

async function upload(selected) {
  if (transfer) return;
  const currentSpace = space();
  const key = currentSpace === 'private' ? vaultKey : null;
  if (currentSpace === 'private' && !key) throw new Error('Unlock your vault first.');
  transfer = { label: 'Preparing upload…', percent: 0 };
  render();
  let done = 0;
  const errors = [];
  try {
    for (const local of selected) {
      const file = { id: crypto.randomUUID().replaceAll('-', ''), size: local.size, space: currentSpace };
      if (key) file.revision = data.vault.revision;
      let registered = false;
      const label = `Uploading ${local.name}`;
      updateProgress(label, 0);
      try {
        file.label = key ? await sealText(key, local.name, fileContext(data.user.id, file, 'name')) : local.name;
        await api('uploads', { method: 'POST', data: file });
        registered = true;
        let offset = 0;
        let index = 0;
        for (let pos = 0; pos < file.size || (key && index === 0);) {
          const end = Math.min(pos + data.chunkSize, file.size);
          const bytes = await local.slice(pos, end).arrayBuffer();
          const packet = key ? await seal(key, bytes, fileContext(data.user.id, file, index)) : bytes;
          const result = await api(`uploads/${file.id}/${offset}`, { method: 'PUT', binary: packet });
          offset = result.received;
          index += 1;
          pos = end;
          updateProgress(label, file.size ? pos / file.size : 1);
        }
        done += 1;
      } catch (error) {
        if (registered) await api(`uploads/${file.id}`, { method: 'DELETE' }).catch(() => {});
        errors.push(`${local.name}: ${error.message}`);
        if (error.status === 401) break;
      }
    }
  } finally {
    transfer = null;
    await refresh();
    await loadFiles();
    render();
  }
  if (errors.length) notice(`${done ? `${done} uploaded. ` : ''}${errors[0]}${errors.length > 1 ? ` (${errors.length} failed)` : ''}`, true);
  else notice(`${done} ${done === 1 ? 'file' : 'files'} uploaded.`);
}

async function startDownload(file) {
  if (!file || transfer) return;
  if (!isVaultPage()) {
    const link = document.createElement('a');
    link.href = `/api/files/${file.id}/blob`;
    link.download = file.name;
    link.click();
    return;
  }
  const label = `Downloading ${file.name}`;
  transfer = { label, percent: 0 };
  render();
  try {
    await downloadPrivate({ key: vaultKey, user: data.user.id, file, chunkSize: data.chunkSize, progress: progress => updateProgress(label, progress) });
    notice('Download complete.');
  } catch (error) {
    if (error.name !== 'AbortError') throw error;
  } finally {
    transfer = null;
    render();
  }
}

function confirmDelete(file) {
  if (!file) return;
  formDialog('Delete file?', `Delete <strong>${esc(file.name)}</strong> from this drive.`, '<div class="access-banner">This permanently removes the file from Family Drive.</div>', 'Delete file', async () => {
    await api(`files/${file.id}`, { method: 'DELETE' });
    dialog.close();
    await refresh();
    await loadFiles();
    render();
    notice('File deleted.');
  });
  dialog.querySelector('button[type="submit"]').classList.replace('primary', 'danger');
}

function accountSettings() {
  formDialog('Account', `${esc(data.user.name)} · @${esc(data.user.username)}`,
    '<label>Current password<input type="password" name="current" required autocomplete="current-password"></label><label>New password<input type="password" name="password" required autocomplete="new-password"></label>',
    'Change password', async values => {
      await api('password', { method: 'POST', data: values });
      dialog.close();
      notice('Password changed.');
    });
}

async function guarded(action) {
  try { await action(); } catch (error) {
    notice(error.message, true);
    if (error.status === 401) {
      clearVaultKey();
      if (dialog.open) dialog.close();
      await refresh();
      render();
    }
  }
}

document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button) return;
  const { page: destination, action, id } = button.dataset;
  if (destination) guarded(() => navigate(destination));
  if (!action) return;
  if (action === 'close') dialog.close();
  else if (action === 'add-person') addPerson();
  else if (action === 'edit-person') editPerson(id);
  else if (action === 'family-quota') setFamilyQuota();
  else if (action === 'settings') accountSettings();
  else if (action === 'vault') vaultDialog();
  else if (action === 'vault-forgot') forgotVault();
  else if (action === 'vault-reset') resetVaultDialog();
  else if (action === 'vault-recover') recoverVault();
  else if (action === 'vault-security') vaultSecurity();
  else if (action === 'vault-change') updateVaultSecurity(true);
  else if (action === 'vault-new-key') updateVaultSecurity(false);
  else if (action === 'copy-recovery') guarded(async () => {
    await navigator.clipboard.writeText(document.querySelector('#recovery-key').textContent);
    button.textContent = 'Copied';
  });
  else if (action === 'upload') document.querySelector('#file-picker').click();
  else if (action === 'download') guarded(() => startDownload(files.find(file => file.id === id)));
  else if (action === 'remove') confirmDelete(files.find(file => file.id === id));
  else if (action === 'lock') {
    clearVaultKey();
    guarded(() => navigate(page));
  } else if (action === 'reset') {
    formDialog('Reset sign-in password?', 'This ends the account’s current sessions and creates a new temporary password. The private vault still uses its own passphrase.', '', 'Generate password', async () => {
      showCredential(await api(`people/${id}/reset`, { method: 'POST' }));
    });
  } else if (action === 'copy') {
    guarded(async () => {
      await navigator.clipboard.writeText(`Username: ${document.querySelector('#new-username').textContent}\nTemporary password: ${document.querySelector('#new-password').textContent}`);
      notice('Credentials copied.');
    });
  } else if (action === 'logout') {
    if (transfer) { notice('Wait for the current transfer to finish.'); return; }
    guarded(async () => {
      await api('logout', { method: 'POST' });
      clearVaultKey();
      if (dialog.open) dialog.close();
      await refresh();
      render();
    });
  }
});

dialog.addEventListener('close', () => { if (!dialog.open) dialog.replaceChildren(); });
document.addEventListener('pointerdown', vaultActivity, { passive: true });
document.addEventListener('keydown', vaultActivity);
document.addEventListener('visibilitychange', checkVaultIdle);

try {
  await refresh();
  await navigate(isAdmin() ? 'overview' : 'private');
} catch (error) {
  app.innerHTML = `<main class="loading" role="alert"><h1>Family Drive is unavailable</h1><p>${esc(error.message)}</p><p>Check the host computer and reload this page.</p></main>`;
}
