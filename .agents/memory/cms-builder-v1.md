---
name: CMS Builder v1
description: Arsitektur, route, dan pola install CMS Builder modul kustom TPQ HMarisa
---

## Model
- `CmsModule` — satu baris per modul; kolom: name, slug, icon, color, description, purpose, role_access (CSV), features (JSON), parent_menu_id (FK SidebarMenu), sort_order, is_active
- `CmsField` — kolom per modul; field_type: text/textarea/number/date/datetime/select/boolean/email/phone/file; options_raw = comma-separated untuk select
- `CmsRecord` — data generik; kolom data = JSON dict keyed by CmsField.name; soft-delete via is_deleted+deleted_at

## Route Pattern
- Admin builder: `/control-center/cms-builder` (index, new, edit, delete, toggle)
- Data module: `/m/<slug>` (list, add, edit, delete, export csv/xlsx, template xlsx, import)
- Hub page: `/hub/<menu_id>` — ditampilkan saat parent menu diklik, menampilkan children sebagai kartu

## Submenu sebagai Page Tabs (Req E)
- `record_list.html` query `SidebarMenu` untuk sibling (parent_id = module.parent_menu_id)
- Jika ada sibling, ditampilkan sebagai `.cmp-page-tabs` horizontal DI ATAS konten, BUKAN dropdown sidebar

## Auto-sidebar
- Saat modul dibuat/diedit, `_register_sidebar(module)` otomatis membuat/update entri SidebarMenu
- Saat modul dihapus, `_unregister_sidebar(slug)` menghapus entri sidebar

## Install
- `install_cms_module_v1(app, db, globals())` dipanggil dari app.py setelah install_sidebar_menu_v1
- Ekspos CmsModule, CmsField, CmsRecord ke globals()

**Why:** EAV-style (JSON data column) dipilih agar tidak perlu ALTER TABLE saat modul baru dibuat; tradeoff: tidak bisa query per-field di SQL level.
**How to apply:** Saat menambah fitur baru ke modul, tambah ke ALL_FEATURES list di cms_module_v1.py dan ke CSS .cms-feature-grid.
