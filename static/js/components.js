/* ═══════════════════════════════════════════════════════════════════════════
   Komponen Global JS — Portal TPQ HMarisa
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── Modal Helpers ──────────────────────────────────────────────────────────── */
function cmpOpenModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  // Focus first focusable element
  const focusable = el.querySelector('button, [href], input, select, textarea');
  if (focusable) setTimeout(() => focusable.focus(), 50);
}

function cmpCloseModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = 'none';
  document.body.style.overflow = '';
}

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.cmp-modal-overlay').forEach(function(m) {
      if (m.style.display !== 'none') cmpCloseModal(m.id);
    });
  }
});

/* ── File Upload Preview ────────────────────────────────────────────────────── */
function cmpShowFile(input, modalId) {
  const el = document.getElementById('chosen-' + modalId);
  if (!el) return;
  if (input.files && input.files[0]) {
    const f = input.files[0];
    const size = f.size < 1024 * 1024
      ? (f.size / 1024).toFixed(1) + ' KB'
      : (f.size / 1024 / 1024).toFixed(2) + ' MB';
    el.querySelector('span').textContent = f.name + ' (' + size + ')';
    el.style.display = 'flex';
  } else {
    el.style.display = 'none';
  }
}

/* ── Delete confirmation with dynamic URL ───────────────────────────────────── */
function cmpConfirmDelete(modalId, actionUrl, itemName) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  // Update form action
  const forms = modal.querySelectorAll('form');
  forms.forEach(function(f) { f.action = actionUrl; });
  // Update message if there's an element for item name
  const nameEl = modal.querySelector('[data-item-name]');
  if (nameEl && itemName) nameEl.textContent = itemName;
  cmpOpenModal(modalId);
}

/* ── Drag & drop for dropzones ──────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.cmp-dropzone').forEach(function(dz) {
    dz.addEventListener('dragover', function(e) {
      e.preventDefault();
      dz.style.borderColor = 'var(--cmp-primary)';
      dz.style.background = '#f0fdf9';
    });
    dz.addEventListener('dragleave', function() {
      dz.style.borderColor = '';
      dz.style.background = '';
    });
    dz.addEventListener('drop', function(e) {
      e.preventDefault();
      dz.style.borderColor = '';
      dz.style.background = '';
      const fileInput = dz.querySelector('input[type=file]');
      if (fileInput && e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });
  });
});

/* ── CMS Builder: Field Row Management ─────────────────────────────────────── */
let cmsFieldCounter = 0;

function cmsAddField() {
  cmsFieldCounter++;
  const container = document.getElementById('cms-fields-container');
  if (!container) return;
  const row = document.createElement('div');
  row.className = 'cms-field-row';
  row.id = 'field-row-' + cmsFieldCounter;
  const n = cmsFieldCounter;
  row.innerHTML = `
    <input type="text" name="fields[${n}][name]" placeholder="nama_kolom"
           class="form-control cms-form-control" style="font-family:monospace"
           pattern="[a-z_][a-z0-9_]*" title="Huruf kecil dan underscore saja">
    <input type="text" name="fields[${n}][label]" placeholder="Label Tampil"
           class="form-control cms-form-control">
    <select name="fields[${n}][type]" class="form-control cms-form-control">
      <option value="text">Teks Pendek</option>
      <option value="textarea">Teks Panjang</option>
      <option value="number">Angka</option>
      <option value="date">Tanggal</option>
      <option value="select">Pilihan</option>
      <option value="boolean">Ya/Tidak</option>
      <option value="email">Email</option>
      <option value="phone">Telepon</option>
      <option value="file">File</option>
    </select>
    <div style="display:flex;align-items:center;gap:.4rem">
      <label style="display:flex;align-items:center;gap:.25rem;font-size:.75rem;cursor:pointer;color:var(--cmp-text-muted)">
        <input type="checkbox" name="fields[${n}][required]" value="1"> Wajib
      </label>
      <button type="button" class="btn" style="color:#dc2626;border-color:#fecaca;padding:.3rem .5rem;font-size:.75rem"
              onclick="cmsRemoveField(${n})">
        <i class="fa-solid fa-trash"></i>
      </button>
    </div>`;
  container.appendChild(row);
}

function cmsRemoveField(n) {
  const row = document.getElementById('field-row-' + n);
  if (row) row.remove();
}

/* ── Auto-slug from name ────────────────────────────────────────────────────── */
function cmsAutoSlug(nameInput, slugInput) {
  const nameEl = document.getElementById(nameInput);
  const slugEl = document.getElementById(slugInput);
  if (!nameEl || !slugEl) return;
  nameEl.addEventListener('input', function() {
    if (!slugEl.dataset.manual) {
      slugEl.value = nameEl.value
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, '')
        .trim()
        .replace(/\s+/g, '_');
    }
  });
  slugEl.addEventListener('input', function() {
    slugEl.dataset.manual = '1';
  });
}

/* ── Search: auto-submit on filter change ──────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.cmp-filter-select').forEach(function(sel) {
    sel.addEventListener('change', function() {
      const form = sel.closest('form');
      if (form) form.submit();
    });
  });
});

/* ── Flash message auto-dismiss ─────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.flash-msg-auto').forEach(function(el) {
    setTimeout(function() {
      el.style.opacity = '0';
      setTimeout(function() { el.remove(); }, 300);
    }, 4000);
  });
});
