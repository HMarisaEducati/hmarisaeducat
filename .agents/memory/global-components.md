---
name: Global Komponen
description: Sistem komponen reusable (macro, CSS, JS) untuk semua halaman data TPQ HMarisa
---

## File
- `templates/components/_macros.html` — semua Jinja2 macro
- `static/css/components.css` — style untuk semua macro (prefix `.cmp-`)
- `static/js/components.js` — modal helpers, file upload preview, drag-drop, CMS field builder

## Auto-included
- `components.css` di-link di `templates/base.html` (setelah sidebar_menu.css)
- `components.js` di-include di `templates/base.html` (setelah portal_experience_v16.js)
- Halaman individual cukup `{% from "components/_macros.html" import ... %}`

## Macro Reference
- `page_toolbar(title, subtitle, actions, back_url, back_label)` — judul + tombol aksi + tombol kembali
- `page_tabs(tabs, active_url)` — tab horizontal antar sub-halaman (Req E)
- `search_bar(placeholder, name, value, filters)` — form GET dengan filter select
- `pagination(page, total_pages, base_url, q, extra)` — numbered pagination
- `confirm_modal(id, title, message, confirm_label, form_action, has_soft_delete)` — modal konfirmasi hapus
- `upload_modal(id, title, accept, max_mb, form_action, field_name)` — modal upload file
- `import_modal(id, title, template_url, form_action, accept, columns)` — modal import Excel/CSV
- `empty_state(icon, title, message, action_url, action_label)` — tampilan kosong
- `row_actions(edit_url, delete_url, view_url, extra, delete_confirm)` — tombol aksi per baris

**Why:** Macro dipilih atas include agar bisa di-call dengan parameter berbeda per halaman.
**How to apply:** Gunakan `{{ page_toolbar(...) }}` — BUKAN `{% call page_toolbar() %}{% endcall %}` (macro ini bukan caller macro).
