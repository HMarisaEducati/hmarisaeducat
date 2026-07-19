# HMARISA Architecture Reference

Dokumen ini disusun sebagai referensi internal pengembangan untuk proyek HMARISA Education. Tujuannya adalah membantu tim memahami struktur aplikasi saat ini, modul yang ada, risiko sistem, dan aturan pengembangan agar perubahan tidak merusak fungsi yang sudah berjalan.

Catatan:
- Dokumen ini bersifat dokumentasi saja.
- Tidak ada refactor atau perubahan kode yang dilakukan.
- Referensi ini berdasarkan hasil audit terhadap aplikasi aktif, route yang terdaftar, dan skema database yang terpakai.

---

## 1. Struktur aplikasi saat ini

Aplikasi HMARISA adalah sistem web berbasis Flask yang berjalan sebagai monolit modular. Artinya, satu aplikasi inti menghubungkan banyak modul fungsional, tetapi modul-modul tersebut tetap dipisahkan secara fungsi dan file.

### Karakteristik utama
- Framework backend: Flask
- ORM: Flask-SQLAlchemy
- Auth: Flask-Login
- Database aktif: SQLite
- Template: Jinja2
- Pola arsitektur: monolit modular, bukan microservice

### Ciri penting
- Aplikasi inti berada di file utama app.py
- Modul fitur dipasang melalui fungsi install_* dari file terpisah
- Banyak modul berbagi tabel dan model yang sama
- Route terdaftar sangat banyak, sehingga perubahan di satu area dapat memengaruhi area lain

### Status yang terverifikasi
- Jumlah route aktif: 235
- Jumlah tabel database aktif: 50

---

## 2. Daftar modul

### A. Modul inti / core
- app.py
- Menangani autentikasi, model dasar, dashboard, manajemen santri, data pengguna, dan helper umum aplikasi.

### B. Modul akademik
- Fokus pada aktivitas belajar santri: hafalan, mutabaah, riwayat akademik, dan dashboard akademik.

### C. Modul kurikulum
- Menangani silabus, materi, import/export, preview, dan data kurikulum.

### D. Modul keuangan
- finance_v15a.py
- finance_v15b.py
- finance_administration_v15b2.py
- finance_history_reports_v15cd.py
- finance_integration_v15e.py
- Fokus: tagihan, pembayaran, setting keuangan, laporan, integrasi pembayaran.

### E. Modul eraport
- eraport_final_v10.py
- Fokus: pengisian, revisi, publikasi, preview, dan dashboard rapor.

### F. Modul portal dan konten publik
- portal_control_v17.py
- portal_settings_v16a.py
- portal_settings_v16_integrated.py
- Fokus: halaman portal, form dinamis, konten, submission, dan pengaturan visual portal.

### G. Modul control center
- control_center_v1.py
- Fokus: manajemen pengguna, backup/restore, database explorer, CMS builder, log aktivitas, dan pengaturan sistem.

### H. Modul CMS dan navigasi
- cms_module_v1.py
- sidebar_menu_v1.py
- Fokus: modul CMS, sidebar menu, dan navigasi aplikasi.

### I. Modul library / buku
- Fokus: upload buku, akses buku, preview dokumen, dan pengaturan akses.

---

## 3. Struktur database

Database utama adalah SQLite dengan 50 tabel. Struktur data terbagi ke beberapa domain utama.

### A. Domain inti
- user
- santri
- academic_year
- master_class
- subject
- teacher

### B. Domain akademik
- raport
- eraport_period_v10
- hafalan_record
- curriculum_bank
- weekly_curriculum
- weekly_winner

### C. Domain buku dan akses
- kitab
- akses_kitab

### D. Domain keuangan
- finance_bill
- finance_payment
- finance_charge_type
- finance_payment_channel
- finance_waiver
- finance_access_permission
- finance_audit_log
- finance_general_setting
- finance_billing_setting
- finance_receipt_setting
- finance_whatsapp_setting
- finance_whatsapp_contact
- finance_document_sequence

### E. Domain portal dan konten
- portal_control_page_v17
- portal_control_form_v17
- portal_control_content_v17
- portal_control_submission_v17
- portal_control_media_v17
- portal_control_revision_v17
- portal_control_audit_v17
- portal_settings_version
- portal_settings_state
- portal_settings_audit
- portal_experience_version
- portal_experience_state
- portal_experience_audit

### F. Domain CMS dan navigasi
- cms_module
- cms_field
- cms_record
- sidebar_menu

### G. Domain kontrol sistem
- cc_activity_log
- cc_backup_record
- cc_site_setting

### Pola desain database
- Banyak tabel memiliki relasi foreign key
- Banyak data disimpan dalam kolom JSON seperti draft_json, published_json, data_json, settings_json, snapshot_json, scores_json
- Ada pola versi (version), draft, published, dan audit trail

### Relasi penting
- santri.guardian_id -> user.id
- finance_bill.santri_id -> santri.id
- finance_bill.charge_type_id -> finance_charge_type.id
- finance_payment.bill_id -> finance_bill.id
- portal_control_submission_v17.form_id -> portal_control_form_v17.id
- cms_field.module_id -> cms_module.id
- cms_module.parent_menu_id -> sidebar_menu.id

---

## 4. Modul kritis

Modul berikut sangat penting karena menyangkut data inti, transaksi, atau operasi sistem yang sensitif.

### A. Modul user dan santri
- Menjadi fondasi akses, identitas, dan relasi santri-wali.
- Perubahan di area ini dapat memengaruhi seluruh sistem.

### B. Modul keuangan
- finance_bill dan finance_payment adalah bagian paling kritis karena menyangkut transaksi.
- Perubahan pada status, relasi, atau field utama berisiko besar terhadap integritas bisnis.

### C. Modul rapor dan eraport
- Menyimpan data akademik yang penting untuk proses pembelajaran dan evaluasi.
- Data sering disimpan dalam format JSON, sehingga perubahan struktur harus hati-hati.

### D. Modul portal dan submission
- Form dinamis, konten publik, dan submission mengandung logika versi dan data payload.
- Sangat rentan terhadap perubahan skema atau perubahan workflow.

### E. Modul control center
- Memiliki akses administratif dan fungsi backup/restore.
- Karena menyentuh sistem secara luas, perubahan harus sangat hati-hati.

---

## 5. Aturan pengembangan agar tidak merusak sistem

Berikut aturan yang disarankan untuk tim pengembang agar perubahan tetap aman dan tidak merusak fungsi yang sudah berjalan.

### A. Jangan mengubah struktur inti tanpa audit
- Hindari mengubah model user, santri, finance_bill, finance_payment, raport, dan portal_control_* tanpa review mendalam.
- Perubahan di tabel utama dapat memengaruhi banyak modul.

### B. Jangan menghapus atau mengubah field lama secara langsung
- Jika perlu menambah field, lakukan penambahan, bukan penghapusan.
- Hindari perubahan foreign key dan relasi yang sudah terpakai.

### C. Pertahankan kompatibilitas dengan data lama
- Karena aplikasi memakai database aktif dan data nyata, perubahan skema harus aman dan backward compatible.

### D. Gunakan pattern yang sudah ada
- Untuk fitur baru, gunakan pola yang serupa dengan modul yang sudah ada.
- Ikuti gaya route, decorator, dan model yang sudah dipakai di aplikasi.

### E. Selalu pertimbangkan dampak lintas modul
- Sebelum menambah fitur baru, pastikan fitur tersebut tidak memerlukan perubahan mendasar di modul lain.

### F. Pastikan autentikasi dan hak akses diperiksa
- Semua route penting harus tetap terlindungi.
- Jangan menambahkan pintu akses baru tanpa mempertimbangkan role dan batasan data.

### G. Lakukan backup sebelum perubahan skema atau data penting
- Segala perubahan database harus didahului backup.
- Khusus untuk fitur finance dan portal, backup wajib dilakukan.

---

## 6. Panduan penambahan fitur baru

### Prinsip umum
- Fitur baru harus ditambahkan dengan pendekatan yang memperhatikan arsitektur yang sudah ada.
- Hindari membuat sistem terpisah yang justru memperumit integrasi.

### Langkah yang disarankan
1. Identifikasi modul induk yang paling sesuai.
2. Tentukan apakah fitur tersebut butuh tabel baru, field baru, atau cukup memanfaatkan tabel yang ada.
3. Periksa apakah fitur tersebut memerlukan route baru, template baru, atau controller baru.
4. Pastikan role akses dan batasan data sudah dipikirkan.
5. Cek dampaknya terhadap database, UI, dan modul terkait.
6. Uji dengan data nyata sebelum di-deploy.

### Kriteria fitur yang aman ditambahkan
- Tidak mengubah relasi utama yang sudah berjalan
- Tidak menghapus field penting
- Tidak menambah dependensi yang terlalu besar ke modul lain
- Tidak memerlukan migrasi skema yang agresif

### Rekomendasi struktur penambahan fitur
- Untuk fitur kecil: tambahkan ke modul yang paling relevan
- Untuk fitur besar: buat modul baru yang tetap terhubung ke aplikasi inti, bukan memecah sistem secara radikal
- Untuk fitur keuangan dan portal: lakukan review ekstra karena sensitif

---

## 7. Risiko yang harus dihindari

### A. Risiko keamanan
- Akses yang terlalu luas ke route admin
- Role yang tidak konsisten
- Secret key atau konfigurasi sensitif yang tidak aman

### B. Risiko data
- Menghapus field atau mengubah relasi penting
- Menambahkan fitur tanpa mempertimbangkan migrasi data
- Mengubah payload JSON tanpa kompatibilitas yang memadai

### C. Risiko integritas bisnis
- Mengubah status transaksi atau alur pembayaran tanpa pengujian
- Mengubah struktur rapor atau data akademik tanpa konsistensi
- Mengubah workflow portal submission menjadi tidak aman atau tidak bisa diterima

### D. Risiko operasional
- Tidak ada backup yang valid
- Tidak ada pengujian restore
- Tidak ada review dampak antar modul

### E. Risiko maintainability
- Menambahkan fitur tanpa dokumentasi
- Membuat modul baru yang saling bergantung terlalu kuat
- Menyebarkan logika bisnis ke banyak file yang tidak terkontrol

---

## Kesimpulan

Proyek HMARISA sudah memiliki cakupan fitur yang luas dan struktur aplikasi yang cukup matang untuk kebutuhan operasional lembaga. Namun, karena sistem ini besar, modular, dan memakai database yang saling terkait, perubahan harus dilakukan dengan hati-hati.

Prioritas utama pengembangan adalah:
- menjaga integritas data,
- menjaga keamanan akses,
- meminimalkan dampak perubahan antar modul,
- dan memastikan setiap penambahan fitur tetap konsisten dengan arsitektur yang ada.

Dokumen ini disusun sebagai acuan internal untuk pengembangan yang aman dan terkontrol.
