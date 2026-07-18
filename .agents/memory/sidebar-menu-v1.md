---
name: Sidebar Menu Dinamis v1
description: Sistem pengelolaan menu sidebar berbasis database — arsitektur, seed, dan pola rendering
---

## Arsitektur
- **Model**: `SidebarMenu` di `sidebar_menu_v1.py` (tabel `sidebar_menu`); parent/child via self-referential FK
- **Install pattern**: `install_sidebar_menu_v1(app, db, globals())` dipasang di bawah install modul lain, sebelum `with app.app_context():` di app.py
- **Seed**: `seed_sidebar_menus()` dipanggil TERPISAH di startup block (bukan dalam `seed_database()`)
- **Context processor**: `inject_sidebar_menus()` menyediakan `sidebar_menus`, `nav_badges`, `resolve_nav_url` ke semua template
- **Admin UI**: `/admin/sidebar-menu` — hanya superadmin (`admin_utama`)

## Rendering di base.html
- Macro `{% macro render_nav(active=true) %}` didefinisikan di base.html, dipanggil di desktop sidebar dan mobile drawer nav
- `menu._nav_children` — atribut dinamis yang diset oleh context processor (filtered by role)
- Active state: cek `request.endpoint in _eps` — _eps dari `active_endpoints + ',' + endpoint` di-split

## Roles & Special Cases
- Field `roles`: comma-separated string (mis. `admin_utama,admin,guru`)
- Guardian menus punya `url_param='guardian_student_id'` — `resolved_url()` pakai session untuk inject student_id ke URL
- `is_system=True`: tidak bisa dihapus via admin UI, hanya bisa dinonaktifkan
- Badge count: field `badge_key` → dicocokkan dengan `nav_badges` dict dari context processor (finance_unpaid_count, guardian_finance_unpaid_count)

**Why:** Sidebar hardcoded di base.html harus diubah manual setiap ada fitur baru. DB-driven system memungkinkan admin mengatur navigasi tanpa menyentuh kode.

**How to apply:** Tambah menu baru via /admin/sidebar-menu (hanya login superadmin). Untuk sub-menu, pilih menu induk saat tambah. Gunakan `active_endpoints` untuk list endpoint terkait.
