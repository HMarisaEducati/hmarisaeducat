const menuButton = document.querySelector('[data-menu-toggle]');
const drawer = document.querySelector('[data-mobile-drawer]');
const overlay = document.querySelector('[data-drawer-overlay]');
const closeDrawerButton = document.querySelector('[data-drawer-close]');

function setDrawer(open) {
  if (!drawer || !overlay) return;
  drawer.classList.toggle('open', open);
  overlay.classList.toggle('open', open);
  document.body.style.overflow = open ? 'hidden' : '';
}
if (menuButton) menuButton.addEventListener('click', () => setDrawer(true));
if (closeDrawerButton) closeDrawerButton.addEventListener('click', () => setDrawer(false));
if (overlay) overlay.addEventListener('click', () => setDrawer(false));
document.addEventListener('keydown', event => { if (event.key === 'Escape') setDrawer(false); });

document.querySelectorAll('[data-toggle-password]').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.querySelector(button.dataset.togglePassword);
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
    const icon = button.querySelector('i');
    if (icon) {
      icon.classList.toggle('fa-eye', input.type === 'password');
      icon.classList.toggle('fa-eye-slash', input.type !== 'password');
    }
  });
});

document.querySelectorAll('.flash button').forEach(button => button.addEventListener('click', () => button.parentElement.remove()));
setTimeout(() => document.querySelectorAll('.flash').forEach(el => el.classList.add('fade')), 4500);

function bindTableSearch(inputId, tableId) {
  const input = document.getElementById(inputId);
  const table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener('input', () => {
    const query = input.value.trim().toLowerCase();
    table.querySelectorAll('tbody tr[data-search]').forEach(row => {
      row.hidden = !row.dataset.search.toLowerCase().includes(query);
    });
  });
}
bindTableSearch('studentSearch', 'studentTable');
bindTableSearch('billSearch', 'billTable');

function updatePortalDate() {
  const now = new Date();
  const gregorian = document.getElementById('current-gregorian-date');
  const hijri = document.getElementById('current-hijri-date');
  if (gregorian) {
    gregorian.textContent = new Intl.DateTimeFormat('id-ID', {
      weekday: 'long', day: '2-digit', month: 'long', year: 'numeric'
    }).format(now);
  }
  if (hijri) {
    try {
      const text = new Intl.DateTimeFormat('id-ID-u-ca-islamic', {
        day: 'numeric', month: 'long', year: 'numeric'
      }).format(now);
      hijri.textContent = text.replace('AH', 'H');
    } catch (error) {
      hijri.textContent = 'Kalender Hijriah';
    }
  }
}
updatePortalDate();
