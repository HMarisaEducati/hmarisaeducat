---
name: Database URL override
description: DATABASE_URL env var di Replit harus di-override ke SQLite untuk mempertahankan data lama
---

## Situasi
Replit menyuntikkan `DATABASE_URL=postgresql://postgres:password@helium/heliumdb?sslmode=disable` ke environment. App.py menggunakan `os.environ.get("DATABASE_URL", "sqlite:///tpq_hmarisa.db")`, sehingga tanpa override akan mencoba koneksi PostgreSQL dan gagal (psycopg2 tidak ada).

## Solusi
Workflow dikonfigurasi dengan: `DATABASE_URL='sqlite:///tpq_hmarisa.db' python app.py`

**Why:** Data aktif ada di `instance/tpq_hmarisa.db` (SQLite). Seluruh fitur sudah dibangun untuk SQLite.

**How to apply:** Jika workflow direset atau dibuat ulang, pastikan command-nya selalu menggunakan override ini. Jangan gunakan `DATABASE_URL=''` (string kosong) karena SQLAlchemy akan error parsing URL kosong.
