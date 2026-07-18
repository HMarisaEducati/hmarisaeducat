"""Tugas terjadwal Santri Terbaik Bulanan TPQ HMarisa.

Pasang sebagai tugas harian pukul 17.00 WIB. Skrip hanya memproses pada hari
terakhir bulan tersebut, sehingga aman dijalankan setiap hari. Nama file ini
dipertahankan agar tugas PythonAnywhere lama tidak langsung rusak.
"""
from app import app, calculate_monthly_winners, generate_monthly_poster, jakarta_now, monthly_period


def main() -> None:
    now = jakarta_now()
    _, last_day = monthly_period(now.date())
    if now.date() != last_day or now.hour < 17:
        print(f"Lewati: {now:%Y-%m-%d %H:%M} WIB bukan akhir bulan pukul 17.00 atau sesudahnya.")
        return
    with app.app_context():
        winners = calculate_monthly_winners(reference=now.date(), force=True)
        poster = generate_monthly_poster(reference=now.date(), force=True)
        print(f"Berhasil: {len(winners)} hasil kelas; poster={poster or 'belum dibuat'}")


if __name__ == "__main__":
    main()
