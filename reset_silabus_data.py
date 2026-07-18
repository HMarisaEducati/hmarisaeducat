"""Kosongkan data Silabus Bulanan secara aman.

Jalankan hanya setelah patch terpasang:
    python reset_silabus_data.py HAPUS-SEMUA-SILABUS

Script membuat salinan database SQLite terlebih dahulu, lalu menghapus record
WeeklyCurriculum. Data Master, Bank Silabus, santri, raport, iuran, dan uploads
tidak diubah.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app import BASE_DIR, WeeklyCurriculum, app, db

CONFIRMATION = "HAPUS-SEMUA-SILABUS"


def backup_sqlite_database(database_path: Path) -> Path:
    backup_dir = Path(BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"sebelum_reset_silabus_{timestamp}.db"
    source = sqlite3.connect(str(database_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1].strip().upper() != CONFIRMATION:
        print("PERINTAH DIBATALKAN.")
        print(f"Gunakan: python reset_silabus_data.py {CONFIRMATION}")
        return 2

    with app.app_context():
        database_url = db.engine.url
        if database_url.get_backend_name() != "sqlite":
            print("Reset otomatis hanya diizinkan untuk database SQLite.")
            print("Database tidak diubah.")
            return 3
        db.session.remove()
        database_path = Path(database_url.database or "")
        if not database_path.is_absolute():
            database_path = (Path(app.instance_path) / database_path).resolve()
        if not database_path.exists():
            print(f"Database tidak ditemukan: {database_path}")
            return 4

        backup_path = backup_sqlite_database(database_path)
        count = WeeklyCurriculum.query.count()
        deleted = db.session.query(WeeklyCurriculum).delete(synchronize_session=False)
        db.session.commit()

        preview_dir = Path(app.instance_path) / "curriculum_import_previews"
        if preview_dir.exists():
            shutil.rmtree(preview_dir)
            preview_dir.mkdir(parents=True, exist_ok=True)

        print("RESET SILABUS SELESAI")
        print(f"Backup database : {backup_path}")
        print(f"Data sebelumnya : {count}")
        print(f"Data dihapus     : {deleted}")
        print("Data Master dan Bank Silabus tetap dipertahankan.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
