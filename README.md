# Portal TPQ H. Marisa — Revisi Administrasi, Silabus, dan Koleksi Kitab

Aplikasi web Flask + SQLite/SQLAlchemy untuk Portal TPQ H. Marisa.

## Login dan akses

### Wali santri
Halaman utama tidak memakai username atau password. Wali cukup mengetik nama lengkap santri dan memilih kelas.

Data contoh:
- Nama: `Ahmad Zaki Al-Fatih`
- Kelas: `Ar-Rahim`

Wali hanya dapat melihat perkembangan, hafalan, tagihan, dan koleksi kitab. Nilai serta E-Raport tetap disembunyikan dan dilindungi dari akses URL langsung.

### Admin
Buka `/admin/login`.

- Username: `tpqhmarisa`
- Password: `tpqhmarisa`

## Fitur revisi terbaru

1. Silabus dan kurikulum pekanan per kelas, lengkap dengan tambah, edit, dan hapus.
2. Database santri ditampilkan ringkas dalam dua kolom: nama dan kelas, dengan pencarian.
3. Buku prestasi harian memiliki pencarian nama/kelas serta tombol edit dan hapus catatan.
4. E-Raport dibuka melalui pilihan kelas terlebih dahulu.
5. Sistem keuangan memiliki tombol Input, Edit, dan Ekspor.
6. Pencarian administrasi memakai nama, kelas, dan bulan.
7. Data tagihan dapat diedit manual.
8. Koleksi kitab dapat diunggah, diedit, dan dihapus oleh admin.
9. Kategori kitab:
   - Kitab Fiqih
   - Kitab Akhlaq
   - Kitab Nizhomi
   - Kitab Tilawati
   - Buku Edukasi Anak
10. Wali dapat membaca tiga halaman awal kitab premium. Tombol unduh mengarah ke pembelian, lalu file penuh otomatis dapat diunduh setelah admin mengonfirmasi pembayaran.
11. Beranda admin memiliki satu pilihan kelas untuk menampilkan silabus pekanan.

## Menjalankan aplikasi

```bash
pip install -r requirements.txt
python app.py
```

Untuk deployment:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

## Memasang ke project lama tanpa kehilangan data

Ganti file/folder berikut:

- `app.py`
- `templates/`
- `static/css/style.css`
- `static/js/app.js` bila disertakan dalam paket update

Jangan menimpa atau menghapus:

- `instance/`
- `uploads/`

Aplikasi akan otomatis menambahkan tabel silabus dan kolom kategori kitab ke database SQLite lama saat pertama kali dijalankan.

## Catatan pembelian kitab

Versi ini memakai alur transfer manual:

1. Wali membuka tiga halaman awal.
2. Wali menekan tombol unduh dan diarahkan ke halaman pembelian.
3. Wali mengunggah bukti transfer.
4. Admin mengonfirmasi pembayaran.
5. Akses baca dan unduh penuh langsung terbuka untuk santri tersebut.

Integrasi pembayaran bank otomatis belum digunakan karena membutuhkan payment gateway atau API bank terpisah.
