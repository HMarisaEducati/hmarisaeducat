---
name: Control Center architecture
description: Cara Control Center diintegrasikan ke app.py TPQ HMarisa tanpa merusak fitur lama
---

## Pola Integrasi
Control Center menggunakan pola `install_X(app, db, globals())` yang sama dengan modul lain (finance_v15e, eraport_v10, dll). File: `control_center_v1.py`.

**Why:** Pola ini konsisten dengan arsitektur yang sudah ada dan menghindari konflik Blueprint registration.

## File yang dibuat
- `control_center_v1.py` — semua routes, models, helpers
- `templates/control_center/` — base.html, dashboard.html, users.html, user_form.html, activity_log.html, settings.html, database.html, table_view.html, backup.html
- `static/css/control_center.css` — modern dark sidebar CSS
- `static/js/control_center.js` — theme toggle, sidebar collapse, global search, charts

## Model DB baru (tidak mengubah tabel lama)
- `cc_activity_log` — log semua aktivitas sistem
- `cc_site_setting` — key-value pengaturan website
- `cc_backup_record` — riwayat backup

## Routes terdaftar
Prefix: `/control-center`
- `/` — dashboard
- `/users` — daftar pengguna
- `/users/add`, `/users/<id>/edit`, `/users/<id>/delete`, `/users/<id>/toggle`, `/users/<id>/reset-password`
- `/activity-log`, `/activity-log/clear`
- `/settings`
- `/database`, `/database/table/<name>`, `/database/export/<name>`, `/database/export-all`
- `/backup`, `/backup/create`, `/backup/download`, `/backup/download/<filename>`, `/backup/restore`
- `/search` — JSON API untuk global search

## Penting: sa_or bukan db.or_
Flask-SQLAlchemy 3.x tidak punya `db.or_`. Gunakan `from sqlalchemy import or_ as sa_or`.

**How to apply:** Setiap kali query dengan OR condition, gunakan `sa_or()` bukan `db.or_()`.

## Link di sidebar
Ditambahkan di `templates/base.html` (desktop sidebar dan mobile drawer) — hanya tampil untuk `is_superadmin`.
