# Portal TPQ HMarisa

Aplikasi web manajemen TPQ (Taman Pendidikan Al-Qur'an) HMarisa berbasis **Flask + SQLite**.

## Stack / Framework

- **Backend**: Python 3.11, Flask 3.1, Flask-SQLAlchemy 2.0, Flask-Login 0.6
- **Database**: SQLite (`instance/tpq_hmarisa.db`)
- **Frontend**: Jinja2 templates + HTML/CSS/JS (tanpa framework frontend terpisah)
- **Library tambahan**: ReportLab & PyMuPDF (PDF), Pillow (gambar), openpyxl (Excel), gunicorn (WSGI)

## Cara Menjalankan

```bash
DATABASE_URL='sqlite:///tpq_hmarisa.db' python app.py
```

Aplikasi tersedia di `http://127.0.0.1:5000`.

Workflow Replit sudah dikonfigurasi dengan perintah di atas — cukup klik **Run**.

## Login

| Role  | Username     | Password     |
|-------|-------------|-------------|
| Admin | `tpqhmarisa` | `tpqhmarisa` |

> Ganti password setelah deployment produksi.

## Fitur yang Tersedia

1. **Portal Wali Santri** — akses data ananda via pilihan kelas + nama
2. **Dashboard Admin** — manajemen santri, kelas, guru, dan data master
3. **E-Raport (v10)** — input nilai, predikat otomatis (KKM 70), pratinjau, penerbitan, ekspor PDF
4. **Jurnal Mutabaah** — tracker ibadah harian santri
5. **Tracker Hafalan Juz 30** — pencatatan progress hafalan
6. **Silabus Bulanan (v8)** — Bank Silabus Ar Rahman & Ar Rahim, ekspor PDF/Excel
7. **Keuangan (v15e)** — tagihan, pembayaran, laporan, riwayat, struk
8. **Perpustakaan Digital** — upload dan manajemen buku
9. **Santri Terbaik** — mingguan & bulanan dengan poster
10. **Hadis Harian** — tampil di halaman publik dan dashboard
11. **Data Master** — kelas, guru, bidang pelajaran, tahun ajaran
12. **Ekspor CSV** — data santri

## Database

- Database aktif: `instance/tpq_hmarisa.db`
- Backup: `instance/tpq_hmarisa_before_final_revision.db`
- Skema diperbarui otomatis saat aplikasi pertama kali dimuat

## Catatan Penting

- `DATABASE_URL` env var wajib di-override ke SQLite saat run (Replit default ke PostgreSQL)
- Control Center didaftarkan sebagai `install_*` function di `app.py`, setelah semua modul lain
- File modul utama: `app.py`, `eraport_final_v10.py`, `finance_*.py`, `curriculum_documents.py`, `visual_outputs.py`

## User Preferences

- Jangan mengubah konsep dan desain utama yang sudah ada
- Jangan membuat ulang proyek dari awal — perbaiki error tanpa ubah struktur
