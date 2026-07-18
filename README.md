# Portal TPQ HMarisa — Revisi Final

Aplikasi Flask + SQLite/SQLAlchemy untuk Portal TPQ HMarisa. Paket ini mencakup revisi Halaman Utama sampai E-Raport, sekaligus mempertahankan Sistem Keuangan dan Perpustakaan Digital dari proyek sebelumnya.

## Fitur utama

- Portal Wali berbasis pilihan kelas dan nama santri.
- Hadis Harian dari bank internal yang sinkron antara halaman publik dan dashboard.
- Data Master dinamis: kelas, guru, bidang pelajaran, dan tahun ajaran.
- Database santri dengan status aktif/nonaktif, ekspor CSV, dan Nama Tampilan Publik.
- Silabus Bulanan Pekan 1–5 dengan Bank Silabus Ar Rahman dan Ar Rahim.
- Jurnal Mutabaah dan Tracker Hafalan Juz 30 terpisah dari E-Raport.
- Santri Terbaik Mingguan dan poster yang dapat dibagikan manual ke WhatsApp.
- E-Raport dengan KKM 70, predikat otomatis, pratinjau, penerbitan, revisi, dan PDF A4.

## Menjalankan secara lokal

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Aplikasi tersedia pada `http://127.0.0.1:5000`.

## Login admin bawaan

- Username: `tpqhmarisa`
- Password: `tpqhmarisa`

Ubah sandi bawaan setelah instalasi produksi. Atur `SECRET_KEY` melalui environment/WSGI.

## Database

- Database aktif: `instance/tpq_hmarisa.db`
- Backup sebelum revisi: `instance/tpq_hmarisa_before_final_revision.db`
- Pembaruan tabel/kolom dijalankan otomatis saat aplikasi pertama kali dimuat.

## Bank Silabus

- Data JSON: `data/curriculum_bank.json`
- Workbook sumber: `data/Bank_Silabus_Semester_TPQ_HMarisa_Sesuai_Kaldik.xlsx`

## Deployment

Baca `PETUNJUK_UPDATE_PYTHONANYWHERE.txt` sebelum mengganti versi produksi.

## Poster mingguan

Dashboard menyediakan proses manual **Jalankan Sekarang/Buat Ulang Poster**. Skrip `scheduled_weekly.py` dapat dipasang sebagai tugas harian pukul 06.00 WIB; skrip hanya memproses pada hari Ahad. Pengiriman ke WhatsApp tetap dilakukan manual melalui tombol berbagi.
