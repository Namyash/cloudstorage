import { downloadPrivate, fileContext, importVaultKey, open, openText, overhead, randomBytes, recoverySettings, seal, sealText, unlockSecret } from './vault.js';

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
let folders = [];
let trash = [];
let folderId = null;
let fileView = 'browse';
let gridView = localStorage.getItem('family-drive-layout') === 'grid';
let previewUrl;
let draggedItem;
let loadToken = 0;
let displayedPage;
let search = '';
let fileSort = 'newest';
const selectedFiles = new Set();
const fileSorts = {
  newest: ['Newest first', (a, b) => b.created - a.created],
  oldest: ['Oldest first', (a, b) => a.created - b.created],
  name: ['Name A–Z', (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })],
  reverseName: ['Name Z–A', (a, b) => b.name.localeCompare(a.name, undefined, { numeric: true })],
  size: ['Largest first', (a, b) => b.size - a.size],
  smallest: ['Smallest first', (a, b) => a.size - b.size],
};
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
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h1m-1 6h1m-1 6h1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
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
  selectedFiles.clear();
  if (isVaultPage()) {
    files = [];
    folders = [];
    trash = [];
  }
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
  displayedPage = undefined;
  if (data.setupOnHost) {
    app.innerHTML = '<main class="loading"><h1>Family Drive needs setup</h1><p>Create the first admin account on the computer hosting Family Drive.</p></main>';
    return;
  }
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
  if (data.user.familyAccess) items.push(['family', 'Family space', 'folder']);
  if ((isAdmin() && data.people.some(person => person.role === 'guest')) || data.user.exchange) items.push(['exchange', 'Guest exchange', 'exchange']);
  return items;
}

function layout(content, title) {
  const entering = displayedPage !== page;
  displayedPage = page;
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
    <main class="content${entering ? ' entering' : ''}">${content}</main></div></div>`;
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
      <td><span class="status ${color}"><i></i>${label}</span>${person.role === 'family' ? `<div class="field-note">Family space ${person.familyAccess ? 'allowed' : 'blocked'}</div>` : ''}</td>
      <td><button class="icon-button row-action" data-action="edit-person" data-id="${person.id}" title="Manage ${esc(person.name)}" aria-label="Manage ${esc(person.name)}">${icon('edit', 17)}</button></td></tr>`;
  }).join('');
}

function peopleTable() {
  return `<section class="panel people-panel" aria-labelledby="people-title"><div class="panel-heading"><div><h2 id="people-title">People & access</h2><p>Manage accounts, storage quotas, and shared-space access.</p></div>
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

const itemKey = item => `${item.kind}:${item.id}`;
const activeItems = () => [...folders, ...files];
const itemByKey = key => [...activeItems(), ...trash].find(item => itemKey(item) === key);

function visibleFiles() {
  const term = search.toLowerCase().trim();
  let source = activeItems();
  if (fileView === 'trash') source = trash;
  else if (fileView === 'starred') source = source.filter(item => item.starred);
  else if (fileView === 'recent') source = files;
  else if (!term) source = source.filter(item => item.folderId === folderId);
  const compare = fileView === 'recent' ? fileSorts.newest[1] : fileSorts[fileSort][1];
  return source.filter(item => item.name.toLowerCase().includes(term))
    .sort((a, b) => (a.kind !== b.kind ? (a.kind === 'folder' ? -1 : 1) : compare(a, b)));
}

function itemCheckbox(item) {
  return item.canDelete ? `<input type="checkbox" data-select-file="${itemKey(item)}" aria-label="Select ${esc(item.name)}" ${selectedFiles.has(itemKey(item)) ? 'checked' : ''} ${transfer ? 'disabled' : ''}>` : '';
}

function itemName(item) {
  const glyph = `<span class="file-glyph ${item.kind}">${icon(item.kind, 19)}</span>`;
  if (fileView === 'trash') return `<div class="item-name">${glyph}<strong>${esc(item.name)}</strong></div>`;
  const action = item.kind === 'folder' ? 'open-folder' : 'preview-file';
  return `<button class="item-name" data-action="${action}" data-id="${itemKey(item)}" ${transfer ? 'disabled' : ''}>${glyph}<strong>${esc(item.name)}</strong></button>`;
}

function itemLocation(item) {
  if (fileView === 'trash' || (!search.trim() && fileView === 'browse')) return '';
  const names = folderPath(item.folderId).map(folder => folder.name);
  if (!names.length) return '';
  return `<small class="item-owner">${esc(names.join(' / '))}</small>`;
}

function itemButtons(item) {
  return `${!isArchive() && fileView !== 'trash' ? `<button class="icon-button star-button ${item.starred ? 'starred' : ''}" aria-pressed="${item.starred}" data-action="star-item" data-id="${itemKey(item)}" aria-label="Star ${esc(item.name)}" ${transfer ? 'disabled' : ''}>${icon('star', 18)}</button>` : ''}
    <button class="icon-button" data-action="item-menu" data-id="${itemKey(item)}" title="More actions" aria-label="More actions for ${esc(item.name)}" ${transfer ? 'disabled' : ''}>${icon('more', 19)}</button>`;
}

function dragAttributes(item) {
  if (transfer || isArchive() || fileView === 'trash') return '';
  return `${item.canDelete ? `draggable="true" data-drag-item="${itemKey(item)}"` : ''} ${item.kind === 'folder' ? `data-drop-folder="${item.id}"` : ''}`;
}

function fileRows() {
  const visible = visibleFiles();
  const added = item => formatDate(item.trashed || item.created);
  if (gridView) return visible.map(item => `<article class="file-card" ${dragAttributes(item)}>
    <div class="file-card-tools">${itemCheckbox(item)}<div>${itemButtons(item)}</div></div>
    ${itemName(item)}<small>${item.kind === 'folder' ? 'Folder' : formatSize(item.size)} · ${added(item)}</small>${itemLocation(item)}</article>`).join('');
  return visible.map(item => `<tr ${dragAttributes(item)}>${isArchive() ? '' : `<td class="file-selection">${itemCheckbox(item)}</td>`}
    <td>${itemName(item)}${itemLocation(item) || (!isVaultPage() ? `<small class="item-owner">${esc(item.by)}</small>` : '')}</td>
    <td>${item.kind === 'folder' ? '—' : formatSize(item.size)}</td><td>${added(item)}</td><td class="file-actions">${itemButtons(item)}</td></tr>`).join('');
}

function folderPath(id) {
  const byId = new Map(folders.map(folder => [folder.id, folder]));
  const path = [];
  while (byId.has(id)) {
    const folder = byId.get(id);
    byId.delete(id);
    path.unshift(folder);
    id = folder.folderId;
  }
  return path;
}

function folderBreadcrumbs() {
  if (fileView !== 'browse') return '';
  const path = folderPath(folderId);
  return `<nav class="folder-path" aria-label="Folder path">
    <button class="button text-button" data-action="folder-root">${esc(workspaceName())}</button>
    ${path.map(folder => `${icon('chevron', 14)}<button class="button text-button" data-action="open-folder" data-id="${itemKey(folder)}">${esc(folder.name)}</button>`).join('')}
  </nav>`;
}

function fileTable() {
  const views = [['browse', 'Browse', 'folder'], ['recent', 'Recent', 'clock'], ['starred', 'Starred', 'star'], ['trash', 'Trash', 'trash']];
  return `<section class="panel files-panel" id="file-workspace">
    ${isArchive() ? '' : `<nav class="file-views" aria-label="File views">${views.map(([value, label, symbol]) => `<button class="button file-view ${value === fileView ? 'current' : ''}" data-action="file-view" data-id="${value}" aria-pressed="${value === fileView}" ${transfer ? 'disabled' : ''}>${icon(symbol, 17)}${label}</button>`).join('')}</nav>`}
    <div class="panel-heading file-heading">${folderBreadcrumbs()}<div class="file-tools">
    <label class="search">${icon('search', 17)}<span class="visually-hidden">Search this space</span><input id="search" type="search" placeholder="Search this space" value="${esc(search)}"></label>
    <select id="file-sort" aria-label="Sort items" ${fileView === 'recent' ? 'disabled' : ''}>${Object.entries(fileSorts).map(([key, [label]]) => `<option value="${key}" ${key === fileSort ? 'selected' : ''}>${label}</option>`).join('')}</select>
    <button class="icon-button layout-toggle" data-action="toggle-grid" title="${gridView ? 'List view' : 'Grid view'}" aria-label="${gridView ? 'Switch to list view' : 'Switch to grid view'}">${icon(gridView ? 'list' : 'overview', 18)}</button></div></div>
    ${isArchive() ? '' : `<div id="selection-tools" class="selection-tools" hidden><strong id="selection-count"></strong>
      ${fileView === 'trash' ? '<button class="button secondary" data-action="restore-selected">Restore</button><button class="button danger" data-action="purge-selected">Delete forever</button>' :
       '<button class="button secondary" data-action="move-selected">Move</button><button class="button secondary" data-action="remove-selected">Move to Trash</button>'}</div>`}
    <div id="files-empty" class="files-empty" hidden>${icon(fileView === 'trash' ? 'trash' : fileView === 'starred' ? 'star' : 'folder', 26)}<strong></strong><small></small></div>
    ${gridView ? `${isArchive() ? '' : '<label class="grid-select"><input type="checkbox" id="select-visible"> Select visible items</label>'}<div class="file-grid" id="rows">${fileRows()}</div>` :
      `<div class="table-scroll"><table><thead><tr>${isArchive() ? '' : '<th class="file-selection"><input type="checkbox" id="select-visible" aria-label="Select all eligible items shown"></th>'}<th>Name</th><th>Size</th><th>${fileView === 'trash' ? 'Removed' : 'Added'}</th><th><span class="visually-hidden">Actions</span></th></tr></thead><tbody id="rows">${fileRows()}</tbody></table></div>`}
    </section>`;
}

function updateFileSelection() {
  const selectAll = document.querySelector('#select-visible');
  if (!selectAll) return;
  const checkboxes = [...document.querySelectorAll('[data-select-file]')];
  const count = checkboxes.filter(checkbox => checkbox.checked).length;
  selectAll.disabled = Boolean(transfer) || !checkboxes.length;
  selectAll.checked = count > 0 && count === checkboxes.length;
  selectAll.indeterminate = count > 0 && count < checkboxes.length;
  const tools = document.querySelector('#selection-tools');
  tools.hidden = !count;
  tools.querySelectorAll('button').forEach(button => { button.disabled = Boolean(transfer); });
  document.querySelector('#selection-count').textContent = `${count} selected`;
}

function updateEmptyState() {
  const element = document.querySelector('#files-empty');
  if (!element) return;
  element.hidden = Boolean(document.querySelector('#rows').children.length);
  const messages = {
    browse: ['This folder is empty', isArchive() ? '' : 'Upload files or create a folder to get started.'],
    recent: ['No recent files', 'Uploaded files appear here.'],
    starred: ['Nothing starred yet', 'Use the star beside a file or folder to keep it handy.'],
    trash: ['Trash is empty', 'Items you remove appear here until restored or permanently deleted.'],
  };
  const [title, description] = search.trim() ? ['No matching items', 'Try a different search.'] : messages[fileView];
  element.querySelector('strong').textContent = title;
  element.querySelector('small').textContent = description;
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
    ${data.archives.map(item => `<div><div class="person-cell"><span class="file-glyph">${icon('lock', 18)}</span><div><strong>${formatDate(item.created)}</strong><small>${item.fileCount} ${item.fileCount === 1 ? 'file' : 'files'} · ${item.folderCount} ${item.folderCount === 1 ? 'folder' : 'folders'}</small></div></div><button class="button secondary" data-page="archive:${item.id}">Open archive</button></div>`).join('')}</section>`;
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
  const description = archive ? 'Open these files with the passphrase or recovery key for this archived vault.' : privateSpace ? 'Your browser encrypts your personal files before upload.' : familySpace ? 'Shared files for family members with access.' : target ? `Files shared between the admin and ${esc(target.name)}.` : 'Files shared between you and the admin.';
  const actions = archive || fileView !== 'browse' || (privateSpace && !vaultKey) ? '' : `<button class="button secondary" data-action="new-folder" ${transfer ? 'disabled' : ''}>${icon('folder', 19)} New folder</button>
    <button class="button primary" data-action="upload" ${transfer ? 'disabled' : ''}>${icon('upload', 19)} Upload files</button><input type="file" id="file-picker" multiple hidden>
    <button class="button secondary" data-action="upload-folder" ${transfer ? 'disabled' : ''}>${icon('upload', 18)} Upload folder</button><input type="file" id="folder-picker" webkitdirectory multiple hidden>`;
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
    selectedFiles.clear();
    document.querySelector('#rows').innerHTML = page === 'overview' || page === 'people' ? personRows() : fileRows();
    updateFileSelection();
    updateEmptyState();
  });
  document.querySelector('#file-sort')?.addEventListener('change', event => {
    fileSort = event.target.value;
    document.querySelector('#rows').innerHTML = fileRows();
    updateFileSelection();
  });
  document.querySelector('#rows')?.addEventListener('change', event => {
    const id = event.target.dataset.selectFile;
    if (!id) return;
    if (event.target.checked) selectedFiles.add(id);
    else selectedFiles.delete(id);
    updateFileSelection();
  });
  document.querySelector('#select-visible')?.addEventListener('change', event => {
    selectedFiles.clear();
    for (const checkbox of document.querySelectorAll('[data-select-file]')) {
      checkbox.checked = event.target.checked;
      if (checkbox.checked) selectedFiles.add(checkbox.dataset.selectFile);
    }
    updateFileSelection();
  });
  updateFileSelection();
  updateEmptyState();
  document.querySelector('#file-picker')?.addEventListener('change', event => {
    if (event.target.files.length) guarded(() => upload([...event.target.files]));
  });
  document.querySelector('#folder-picker')?.addEventListener('change', event => {
    if (event.target.files.length) guarded(() => upload([...event.target.files], true));
  });
}

function space() {
  return page === 'exchange' && !isAdmin() ? `exchange:${data.user.id}` : page;
}

async function loadFiles() {
  files = [];
  folders = [];
  trash = [];
  const token = ++loadToken;
  const currentPage = page;
  const encrypted = isVaultPage();
  const key = vaultKey;
  if (!data.user || ['overview', 'people'].includes(page) || (page === 'exchange' && isAdmin()) || (encrypted && !key)) return;
  const user = data.user.id;
  const response = await api(`files?space=${encodeURIComponent(space())}`);
  const decode = async item => {
    if (!encrypted) return { ...item, name: item.label };
    try {
      return { ...item, name: await openText(key, item.label, itemNameContext(user, item)) };
    } catch {
      return { ...item, name: `Unreadable encrypted ${item.kind}`, damaged: true };
    }
  };
  const [nextFiles, nextFolders, nextTrash] = await Promise.all([
    Promise.all(response.files.map(decode)),
    Promise.all(response.folders.map(decode)),
    Promise.all([...response.trashFiles, ...response.trashFolders].map(decode)),
  ]);
  if (token !== loadToken || page !== currentPage || data.user?.id !== user || (encrypted && vaultKey !== key)) return;
  files = nextFiles;
  folders = nextFolders;
  trash = nextTrash;
  if (!folders.some(folder => folder.id === folderId)) folderId = null;
}

async function refresh() {
  const previous = data?.user?.id;
  const revision = data?.vault?.revision;
  data = await api('state');
  if (previous !== data.user?.id || (page === 'private' && revision !== data.vault?.revision)) clearVaultKey();
}

async function navigate(next) {
  if (transfer) { notice('Wait for the current transfer to finish.'); return; }
  if (next === 'family') {
    await refresh();
    if (!data.user?.familyAccess) {
      await navigate('private');
      if (data.user) notice('Family space access is blocked.', true);
      return;
    }
  }
  if (page !== next && isVaultPage()) clearVaultKey();
  page = next;
  folderId = null;
  fileView = 'browse';
  search = '';
  selectedFiles.clear();
  await loadFiles();
  render();
}

function openFolder(item) {
  if (transfer) return;
  folderId = item?.id ?? null;
  fileView = 'browse';
  search = '';
  selectedFiles.clear();
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

function familyPermission(allowed) {
  return `<label class="checkbox"><input type="checkbox" name="familyAccess" ${allowed ? 'checked' : ''}><span>Allow Family space access<small>Lets this member open and upload shared files.</small></span></label>`;
}

function addPerson() {
  const form = formDialog('Add person', 'Give a family member or guest their own login and storage quota.',
    `<label>Display name<input name="name" required maxlength="60"></label>${usernameField}
    <div class="form-grid"><label>Role<select name="role"><option value="family">Family member</option><option value="guest">Guest</option></select></label>${quotaField(null)}</div><div class="family-fields">${familyPermission(true)}</div>${guestFields({ role: 'family' })}`, 'Create account', async values => {
    const { familyAccess, ...fields } = values;
    const account = await api('people', { method: 'POST', data: { ...fields, quota: Math.round(Number(values.quota) * GB),
      ...(values.role === 'family' ? { familyAccess: familyAccess === 'on' } : guestValues(values)) } });
    await refresh();
    render();
    showCredential(account);
  });
  form.elements.role.addEventListener('change', () => {
    form.querySelector('.guest-fields').hidden = form.elements.role.value !== 'guest';
    form.querySelector('.family-fields').hidden = form.elements.role.value !== 'family';
  });
}

function editPerson(id) {
  const person = data.people.find(item => item.id === id);
  if (!person) return;
  formDialog('Manage account', `${esc(person.name)} · @${esc(person.username)} · ${roleName(person.role)}`,
    `${quotaField(person.quota)}<span class="field-note">${formatSize(person.used)} in use</span>
    ${person.role !== 'admin' ? `<label class="checkbox"><input type="checkbox" name="active" ${person.active ? 'checked' : ''}><span>Allow sign-in<small>Controls access to the entire account.</small></span></label>` : ''}
    ${person.role === 'family' ? familyPermission(person.familyAccess) : ''}
    ${person.role === 'guest' ? guestFields(person) : ''}`, 'Save changes', async values => {
      const payload = { quota: Math.round(Number(values.quota) * GB), active: person.role === 'admin' || values.active === 'on' };
      if (person.role === 'family') payload.familyAccess = values.familyAccess === 'on';
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
    ${help ? `<p class="dialog-help">${help}</p>` : ''}${body}`;
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
  const hasItems = vault.fileCount || vault.folderCount;
  const details = hasItems ? 'Starting fresh moves the existing encrypted folders and files into an archive. You can unlock that archive later with its original credentials.' : 'You can reset this empty vault using your Family Drive sign-in password.';
  showVaultDialog('Forgot vault passphrase?', details,
    `<div class="dialog-actions"><button class="button ${recover ? 'secondary' : 'primary'}" data-action="vault-reset">${hasItems ? 'Start fresh and keep archive' : 'Reset empty vault'}</button>${recover}</div>`);
}

function resetVaultDialog() {
  const current = data.vault;
  const hasItems = current.fileCount || current.folderCount;
  const help = hasItems ? 'Your existing folders and files will move to a locked archive. Enter your sign-in password to continue and create a fresh vault.' : 'Enter your sign-in password to clear the vault settings and choose a new passphrase.';
  formDialog('Reset private vault', help,
    '<label>Family Drive sign-in password<input name="password" type="password" autocomplete="current-password" required></label>',
    hasItems ? 'Archive and reset' : 'Reset vault', async values => {
      const result = await api('vault/reset', { method: 'POST', data: { password: values.password, revision: current.revision } });
      clearVaultKey();
      dialog.close();
      await refresh();
      await navigate('private');
      notice(result.archiveCreated ? 'Saved your items in an encrypted archive.' : 'Vault reset. Choose a new vault passphrase.');
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

const newId = () => crypto.randomUUID().replaceAll('-', '');
const itemNameContext = (user, item) => fileContext(user, item, item.kind === 'folder' ? 'folder-name' : 'name');

async function createFolder(name, parent = folderId) {
  const item = { id: newId(), kind: 'folder', size: 0, space: space(), folderId: parent, label: name };
  if (item.space === 'private') {
    if (!vaultKey) throw new Error('Unlock your vault before creating a folder.');
    item.revision = data.vault.revision;
    item.label = await sealText(vaultKey, name, itemNameContext(data.user.id, item));
  }
  await api('folders', { method: 'POST', data: item });
  return item.id;
}

async function upload(selected, withFolders = false, success = '') {
  if (transfer) return;
  const currentSpace = space();
  const uploadFolder = folderId;
  const pathIds = new Map([['', uploadFolder]]);
  const key = currentSpace === 'private' ? vaultKey : null;
  if (currentSpace === 'private' && !key) throw new Error('Unlock your vault first.');
  transfer = { label: 'Preparing upload…', percent: 0 };
  render();
  let done = 0;
  const errors = [];
  try {
    for (const local of selected) {
      const file = { id: newId(), size: local.size, space: currentSpace, folderId: uploadFolder };
      if (key) file.revision = data.vault.revision;
      let registered = false;
      const label = `Uploading ${local.name}`;
      updateProgress(label, 0);
      try {
        if (withFolders) {
          const parts = local.webkitRelativePath.split('/').slice(0, -1);
          let path = '';
          for (const name of parts) {
            const next = `${path}/${name}`;
            if (!pathIds.has(next)) pathIds.set(next, await createFolder(name, pathIds.get(path)));
            path = next;
          }
          file.folderId = pathIds.get(path);
        }
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
    if (page === 'family' && !data.user?.familyAccess) await navigate('private');
    else {
      await loadFiles();
      render();
    }
  }
  if (errors.length) notice(`${done ? `${done} uploaded. ` : ''}${errors[0]}${errors.length > 1 ? ` (${errors.length} failed)` : ''}`, true);
  else notice(success || `${done} ${done === 1 ? 'file' : 'files'} uploaded.`);
}

async function readFileSlice(file, start, end, key, user, chunkSize) {
  const encrypted = Boolean(key);
  const index = Math.floor(start / chunkSize);
  const offset = encrypted ? start + index * overhead : start;
  const length = end - start + (encrypted ? overhead : 0);
  if (!length) return new Uint8Array();
  const response = await fetch(`/api/files/${file.id}/blob`, {
    headers: { Range: `bytes=${offset}-${offset + length - 1}` },
    cache: 'no-store',
  });
  if (response.status !== 206 || Number(response.headers.get('Content-Length')) !== length) {
    await response.body?.cancel();
    throw Object.assign(new Error('Could not read this file. Check access and try again.'), { status: response.status });
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length !== length) throw new Error('The file is incomplete.');
  return encrypted ? open(key, bytes, fileContext(user, file, index)) : bytes;
}

function copyFile(file) {
  const { chunkSize } = data;
  const user = data.user.id;
  const key = isVaultPage() ? vaultKey : null;
  const extensionIndex = file.name.lastIndexOf('.');
  const suffix = extensionIndex > 0 ? file.name.slice(extensionIndex) : '';
  const stem = extensionIndex > 0 ? file.name.slice(0, extensionIndex) : file.name;
  const name = `${stem.slice(0, Math.max(0, 250 - suffix.length))} copy${suffix.slice(0, 250)}`;
  const local = { name, size: file.size, slice: (start, end) => ({
    arrayBuffer: () => readFileSlice(file, start, end, key, user, chunkSize),
  }) };
  return upload([local], false, 'File copied to the open folder.');
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

function itemLabel(name) {
  const label = name.trim();
  if (!label || /[\x00-\x1f\x7f/\\]/.test(label) || label === '.' || label === '..') throw new Error('Enter a valid name.');
  return label;
}

function newFolder() {
  formDialog('New folder', '', '<label>Folder name<input name="name" maxlength="255" required></label>', 'Create folder',
    async values => {
      await createFolder(itemLabel(values.name));
      dialog.close();
      search = '';
      await loadFiles();
      render();
      notice('Folder created.');
    });
}

function renameItem(item) {
  if (!item?.canDelete || item.damaged) return;
  const form = formDialog(`Rename ${item.kind}`, '', `<label>Name<input name="name" value="${esc(item.name)}" maxlength="255" required></label>`,
    'Save name', async values => {
      const name = itemLabel(values.name);
      const fields = { label: name };
      if (page === 'private') {
        if (!vaultKey) throw new Error('Unlock your vault before renaming.');
        fields.revision = data.vault.revision;
        fields.label = await sealText(vaultKey, name, itemNameContext(data.user.id, item));
      }
      await api(`${item.kind}s/${item.id}`, { method: 'PATCH', data: fields });
      dialog.close();
      await loadFiles();
      render();
      notice('Name saved.');
    });
  form.elements.name.focus();
  form.elements.name.select();
}

const selectedItems = () => visibleFiles().filter(item => item.canDelete && selectedFiles.has(itemKey(item)));

async function organize(action, items, fields = {}) {
  if (!items.length) return;
  await api(`items/${action}`, {
    method: 'POST', data: { ...fields, items: items.map(({ kind, id }) => ({ kind, id })) },
  });
  selectedFiles.clear();
  if (dialog.open) dialog.close();
  if (action === 'purge') await refresh();
  await loadFiles();
  render();
}

function moveItems(items) {
  if (!items.length) return;
  const forbidden = new Set(items.filter(item => item.kind === 'folder').map(item => item.id));
  const targets = folders.map(folder => folderPath(folder.id))
    .filter(path => path.every(folder => !forbidden.has(folder.id)))
    .map(path => ({ id: path.at(-1).id, name: path.map(folder => folder.name).join(' / ') }))
    .sort((a, b) => a.name.localeCompare(b.name));
  formDialog('Move items', '', `<label>Destination<select name="folder"><option value="">${esc(workspaceName())} (top level)</option>
    ${targets.map(target => `<option value="${target.id}">${esc(target.name)}</option>`).join('')}</select></label>`, 'Move here', async values => {
    await organize('move', items, { folderId: values.folder || null });
    notice('Items moved.');
  });
}

function confirmRemoval(items, permanent) {
  if (!items.length) return;
  const name = items.length === 1 ? esc(items[0].name) : `${items.length} items`;
  const title = permanent ? 'Delete forever' : 'Move to Trash';
  formDialog(`${title}?`, `<strong>${name}</strong>`, permanent
    ? '<p>This permanently deletes the selection, including the contents of selected folders.</p>'
    : '<p>You can restore these items from Trash. They still count toward storage usage until deleted forever.</p>',
  title, async () => {
    await organize(permanent ? 'purge' : 'trash', items);
    notice(permanent ? 'Items permanently deleted.' : 'Moved to Trash.');
  });
  if (permanent) dialog.querySelector('button[type="submit"]').classList.replace('primary', 'danger');
}

function itemMenu(item) {
  if (!item) return;
  const button = (action, label, symbol) => `<button class="button secondary" data-action="${action}" data-id="${itemKey(item)}">${icon(symbol, 18)}${label}</button>`;
  const file = item.kind === 'file' && !item.damaged;
  const activeActions = (file ? button('download', 'Download', 'download') : '') +
    (file && !isArchive() ? button('copy-file', 'Copy to open folder', 'copy') : '') +
    (item.canDelete ? (item.damaged ? '' : button('rename', 'Rename', 'edit')) +
      button('move-item', 'Move to folder', 'folder') + button('trash-item', 'Move to Trash', 'trash') : '');
  const actions = item.trashed ? button('restore-item', 'Restore', 'folder') + button('purge-item', 'Delete forever', 'trash') : activeActions;
  showVaultDialog(esc(item.name), '', `<p class="item-details">${item.kind === 'folder' ? 'Folder' : formatSize(item.size)} · ${formatDate(item.created)}
    ${!isVaultPage() ? `· Added by ${esc(item.by)}` : ''}</p><div class="item-menu">${actions}</div>`);
}

function previewKind(name) {
  const extension = name.split('.').at(-1).toLowerCase();
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'bmp'].includes(extension)) return ['image', `image/${extension === 'jpg' ? 'jpeg' : extension}`];
  if (['mp3', 'ogg', 'wav'].includes(extension)) return ['audio', `audio/${extension === 'mp3' ? 'mpeg' : extension}`];
  if (['mp4', 'webm'].includes(extension)) return ['video', `video/${extension}`];
  if (['txt', 'md', 'csv', 'json', 'log'].includes(extension)) return ['text', 'text/plain'];
  return [];
}

async function previewFile(file) {
  if (!file || file.damaged) return;
  const [kind, mime] = previewKind(file.name);
  const limit = (kind === 'text' ? 1 : 24) * 1024 * 1024;
  const available = Boolean(kind) && file.size <= limit;
  showVaultDialog(esc(file.name), '', `<div class="preview-file"><div class="preview-content" aria-live="polite">${available ? 'Loading preview…' : 'Download this file to open it.'}</div>
    <div class="dialog-actions"><button class="button primary" data-action="download" data-id="${itemKey(file)}">${icon('download', 18)} Download</button></div></div>`);
  if (!available) return;
  const container = dialog.querySelector('.preview-content');
  const { chunkSize } = data;
  const user = data.user.id;
  const key = isVaultPage() ? vaultKey : null;
  const parts = [];
  try {
    for (let start = 0; start < file.size || (start === 0 && key); start += chunkSize) {
      if (!container.isConnected || !dialog.open) return;
      parts.push(await readFileSlice(file, start, Math.min(file.size, start + chunkSize), key, user, chunkSize));
    }
    if (!container.isConnected || !dialog.open) return;
    const blob = new Blob(parts, { type: mime });
    if (kind === 'text') {
      const pre = document.createElement('pre');
      pre.textContent = await blob.text();
      if (container.isConnected && dialog.open) container.replaceChildren(pre);
    } else {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob);
      const media = document.createElement(kind === 'image' ? 'img' : kind);
      if (kind === 'image') media.alt = file.name;
      else media.controls = true;
      media.src = previewUrl;
      media.addEventListener('error', () => { container.textContent = 'This format could not be previewed. Download the file to open it.'; }, { once: true });
      container.replaceChildren(media);
    }
  } catch {
    if (container.isConnected && dialog.open) container.textContent = 'Could not preview this file. Check access and try again.';
  }
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
    } else if (error.status === 404 && page === 'family') {
      await refresh();
      if (!data.user?.familyAccess) await navigate('private');
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
  else if (action === 'upload-folder') document.querySelector('#folder-picker').click();
  else if (action === 'new-folder') newFolder();
  else if (action === 'folder-root') openFolder(null);
  else if (action === 'open-folder') openFolder(itemByKey(id));
  else if (action === 'toggle-grid') {
    gridView = !gridView;
    localStorage.setItem('family-drive-layout', gridView ? 'grid' : 'list');
    render();
    document.querySelector('.layout-toggle')?.focus();
  } else if (action === 'file-view') {
    fileView = id;
    search = '';
    selectedFiles.clear();
    render();
    document.querySelector(`[data-action="file-view"][data-id="${id}"]`)?.focus();
  } else if (action === 'item-menu') itemMenu(itemByKey(id));
  else if (action === 'preview-file') guarded(() => previewFile(itemByKey(id)));
  else if (action === 'download' || action === 'copy-file') {
    const item = itemByKey(id);
    if (!item) return;
    if (dialog.open) dialog.close();
    guarded(() => action === 'download' ? startDownload(item) : copyFile(item));
  } else if (action === 'rename') renameItem(itemByKey(id));
  else if (action === 'move-item' || action === 'move-selected') moveItems(id ? [itemByKey(id)].filter(Boolean) : selectedItems());
  else if (['trash-item', 'remove-selected', 'purge-item', 'purge-selected'].includes(action)) {
    confirmRemoval(id ? [itemByKey(id)].filter(Boolean) : selectedItems(), action.startsWith('purge'));
  } else if (action === 'restore-item' || action === 'restore-selected') {
    guarded(async () => {
      await organize('restore', id ? [itemByKey(id)].filter(Boolean) : selectedItems());
      notice('Items restored.');
    });
  } else if (action === 'star-item') {
    const item = itemByKey(id);
    if (item) guarded(() => organize('star', [item], { starred: !item.starred }));
  }
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

dialog.addEventListener('close', () => {
  if (!dialog.open) {
    dialog.replaceChildren();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
});
document.addEventListener('contextmenu', event => {
  const actions = event.target.closest('tr, .file-card')?.querySelector('[data-action="item-menu"]:not(:disabled)');
  if (!actions) return;
  event.preventDefault();
  itemMenu(itemByKey(actions.dataset.id));
});
document.addEventListener('dragstart', event => {
  const key = event.target.closest('[data-drag-item]')?.dataset.dragItem;
  if (!key) return;
  draggedItem = itemByKey(key);
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('application/x-family-drive-item', key);
});
function dropTarget(event) {
  if (transfer || dialog.open || isArchive()) return null;
  if (draggedItem) {
    const folder = event.target.closest('[data-drop-folder]');
    return folder?.dataset.dropFolder !== draggedItem.id ? folder : null;
  }
  if (fileView === 'browse' && event.dataTransfer.types.includes('Files')) return event.target.closest('#file-workspace');
  return null;
}
document.addEventListener('dragover', event => {
  const target = dropTarget(event);
  if (!target) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = draggedItem ? 'move' : 'copy';
  if (!target.classList.contains('drop-ready')) {
    document.querySelector('.drop-ready')?.classList.remove('drop-ready');
    target.classList.add('drop-ready');
  }
});
document.addEventListener('dragleave', event => {
  const target = event.target.closest('.drop-ready');
  if (target && !target.contains(event.relatedTarget)) target.classList.remove('drop-ready');
});
document.addEventListener('dragend', () => {
  draggedItem = null;
  document.querySelector('.drop-ready')?.classList.remove('drop-ready');
});
document.addEventListener('drop', event => {
  const target = dropTarget(event);
  if (!target) return;
  event.preventDefault();
  target.classList.remove('drop-ready');
  if (draggedItem) {
    const item = draggedItem;
    draggedItem = null;
    guarded(async () => {
      await organize('move', [item], { folderId: target.dataset.dropFolder });
      notice('Item moved.');
    });
  } else if (event.dataTransfer.files.length) guarded(() => upload([...event.dataTransfer.files]));
});
document.addEventListener('keydown', event => {
  if (dialog.open || transfer || event.target.closest('input, textarea, select, [contenteditable]')) return;
  const items = selectedItems();
  if (event.key === 'F2' && items.length === 1 && fileView !== 'trash') {
    event.preventDefault();
    renameItem(items[0]);
  } else if (event.key === 'Delete' && items.length) {
    event.preventDefault();
    confirmRemoval(items, fileView === 'trash');
  }
});
document.addEventListener('pointerdown', vaultActivity, { passive: true });
document.addEventListener('keydown', vaultActivity);
document.addEventListener('visibilitychange', checkVaultIdle);

try {
  await refresh();
  await navigate(isAdmin() ? 'overview' : 'private');
} catch (error) {
  app.innerHTML = `<main class="loading" role="alert"><h1>Family Drive is unavailable</h1><p>${esc(error.message)}</p><p>Check the host computer and reload this page.</p></main>`;
}
