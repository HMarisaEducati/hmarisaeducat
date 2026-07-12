import csv
import io
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import date, datetime
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask, Response, abort, flash, redirect, render_template, request, session,
    send_file, send_from_directory, url_for
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required, login_user, logout_user
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func, inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
PROOF_DIR = os.path.join(UPLOAD_DIR, "proofs")
BOOK_DIR = os.path.join(UPLOAD_DIR, "books")
PREVIEW_DIR = os.path.join(UPLOAD_DIR, "previews")
os.makedirs(PROOF_DIR, exist_ok=True)
os.makedirs(BOOK_DIR, exist_ok=True)
os.makedirs(PREVIEW_DIR, exist_ok=True)

app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-secret-key-in-production"),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///tpq_hmarisa.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    BSI_BANK_NAME="Bank Syariah Indonesia (BSI)",
    BSI_ACCOUNT_NUMBER=os.environ.get("BSI_ACCOUNT_NUMBER", "[ISI NOMOR REKENING BSI]"),
    BSI_ACCOUNT_NAME=os.environ.get("BSI_ACCOUNT_NAME", "TPQ HMarisa"),
)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "home"
login_manager.login_message = "Silakan masuk terlebih dahulu."

CLASSES = ["Ar-Rahim", "Ar-Rahman", "Al-Bayyan"]
MONTHS = ["Juli", "Agustus", "September", "Oktober", "November", "Desember",
          "Januari", "Februari", "Maret", "April", "Mei", "Juni"]
SURAH_JUZ30 = [
    "An-Naba'", "An-Nazi'at", "'Abasa", "At-Takwir", "Al-Infitar", "Al-Mutaffifin",
    "Al-Insyiqaq", "Al-Buruj", "At-Tariq", "Al-A'la", "Al-Ghasyiyah", "Al-Fajr",
    "Al-Balad", "Asy-Syams", "Al-Lail", "Ad-Duha", "Asy-Syarh", "At-Tin", "Al-'Alaq",
    "Al-Qadr", "Al-Bayyinah", "Az-Zalzalah", "Al-'Adiyat", "Al-Qari'ah", "At-Takasur",
    "Al-'Asr", "Al-Humazah", "Al-Fil", "Quraisy", "Al-Ma'un", "Al-Kausar", "Al-Kafirun",
    "An-Nasr", "Al-Lahab", "Al-Ikhlas", "Al-Falaq", "An-Nas"
]
SCORE_FIELDS = {
    "Ar-Rahim": ["BTQ", "Hafalan Doa", "Praktek Ibadah", "Adab/Akhlak"],
    "Ar-Rahman": ["BTQ", "Hafalan Doa", "Praktek Ibadah", "Adab/Akhlak"],
    "Al-Bayyan": ["Tahfidz", "Nizomi", "Doa Harian", "Praktek Sholat"],
}
TEACHERS = {
    "Al-Bayyan": "Bunda Hj. Maryamah",
    "Ar-Rahman": "Yeni Susilawati",
    "Ar-Rahim": "Faisal Kazim Muyassar, S.H.",
}
PRINCIPAL = "Bunda Hj. Maryamah"
BOOK_CATEGORIES = [
    "Kitab Fiqih", "Kitab Akhlaq", "Kitab Nizhomi", "Kitab Tilawati",
    "Buku Edukasi Anak"
]
PREVIEW_PAGE_LIMIT = 3
SEARCH_LIMIT = 30


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="guardian")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    students = db.relationship("Santri", backref="guardian", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"


class Santri(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nis = db.Column(db.String(12), unique=True, nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False, index=True)
    class_name = db.Column(db.String(30), nullable=False, index=True)
    guardian_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    raport = db.relationship("Raport", backref="santri", uselist=False, cascade="all, delete-orphan")
    bills = db.relationship("Iuran", backref="santri", cascade="all, delete-orphan", lazy=True)
    book_accesses = db.relationship("AksesKitab", backref="santri", cascade="all, delete-orphan", lazy=True)


class Raport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    santri_id = db.Column(db.Integer, db.ForeignKey("santri.id"), unique=True, nullable=False)
    semester = db.Column(db.String(20), default="Semester 1")
    academic_year = db.Column(db.String(20), default="2026/2027")
    scores_json = db.Column(db.Text, default="{}", nullable=False)
    mutabaah_json = db.Column(db.Text, default="[]", nullable=False)
    hafalan_json = db.Column(db.Text, default="{}", nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def scores(self):
        try:
            return json.loads(self.scores_json or "{}")
        except json.JSONDecodeError:
            return {}

    def mutabaah(self):
        try:
            return json.loads(self.mutabaah_json or "[]")
        except json.JSONDecodeError:
            return []

    def hafalan(self):
        try:
            return json.loads(self.hafalan_json or "{}")
        except json.JSONDecodeError:
            return {}


class Iuran(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    santri_id = db.Column(db.Integer, db.ForeignKey("santri.id"), nullable=False, index=True)
    month = db.Column(db.String(20), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="Belum Lunas", nullable=False)
    nominal = db.Column(db.Integer, default=50000, nullable=False)
    proof_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    verified_at = db.Column(db.DateTime)
    __table_args__ = (UniqueConstraint("santri_id", "month", "year", name="uq_bill_period"),)


class Kitab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    category = db.Column(db.String(80), default="Kitab Fiqih", nullable=False, index=True)
    price = db.Column(db.Integer, default=0, nullable=False)
    filename = db.Column(db.String(255))
    original_filename = db.Column(db.String(255))
    original_size = db.Column(db.Integer, default=0)
    optimized_size = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    accesses = db.relationship("AksesKitab", backref="kitab", cascade="all, delete-orphan", lazy=True)


class AksesKitab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kitab_id = db.Column(db.Integer, db.ForeignKey("kitab.id"), nullable=False)
    santri_id = db.Column(db.Integer, db.ForeignKey("santri.id"), nullable=False)
    status = db.Column(db.String(30), default="Terkunci", nullable=False)
    proof_path = db.Column(db.String(255))
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    confirmed_at = db.Column(db.DateTime)
    __table_args__ = (UniqueConstraint("kitab_id", "santri_id", name="uq_book_student"),)


class WeeklyCurriculum(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(30), nullable=False, index=True)
    week_number = db.Column(db.Integer, nullable=False, default=1)
    subject = db.Column(db.String(120), nullable=False)
    topic = db.Column(db.String(220), nullable=False)
    learning_target = db.Column(db.Text, default="")
    activities = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def selected_guardian_student():
    """Return the one student selected from the public guardian entry form."""
    if not current_user.is_authenticated or current_user.is_admin:
        return None
    student_id = session.get("guardian_student_id")
    if not student_id:
        return None
    student = db.session.get(Santri, int(student_id))
    if not student or student.guardian_id != current_user.id:
        return None
    return student


def can_access_student(student):
    if not current_user.is_authenticated:
        return False
    if current_user.is_admin:
        return True
    selected = selected_guardian_student()
    return bool(selected and selected.id == student.id)


def get_or_create_raport(student):
    if student.raport:
        return student.raport
    raport = Raport(santri_id=student.id)
    db.session.add(raport)
    db.session.flush()
    return raport


def generate_nis(year=None):
    year = year or datetime.now().year
    prefix = str(year)[-2:]
    existing = Santri.query.filter(Santri.nis.like(f"{prefix}%")).all()
    numbers = []
    for student in existing:
        suffix = student.nis[2:]
        if suffix.isdigit():
            numbers.append(int(suffix))
    seq = max(numbers, default=0) + 1
    return f"{prefix}{seq:03d}"


def save_upload(file_storage, folder, allowed_exts):
    if not file_storage or not file_storage.filename:
        return None
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in allowed_exts:
        raise ValueError(f"Format file tidak didukung. Gunakan: {', '.join(sorted(allowed_exts))}")
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(folder, filename)
    file_storage.save(path)
    return filename


def rupiah(value):
    try:
        return "Rp {:,.0f}".format(int(value)).replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


app.jinja_env.filters["rupiah"] = rupiah


@app.context_processor
def inject_globals():
    return {
        "CLASSES": CLASSES,
        "MONTHS": MONTHS,
        "SURAH_JUZ30": SURAH_JUZ30,
        "SCORE_FIELDS": SCORE_FIELDS,
        "TEACHERS": TEACHERS,
        "PRINCIPAL": PRINCIPAL,
        "BOOK_CATEGORIES": BOOK_CATEGORIES,
        "PREVIEW_PAGE_LIMIT": PREVIEW_PAGE_LIMIT,
        "current_date": date.today().isoformat(),
        "current_year": datetime.now().year,
    }


@app.route("/", methods=["GET", "POST"])
def home():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("dashboard"))
        if selected_guardian_student():
            return redirect(url_for("dashboard"))
        logout_user()
        session.pop("guardian_student_id", None)

    students_by_class = {class_name: [] for class_name in CLASSES}
    students = (Santri.query
                .order_by(Santri.class_name, func.lower(Santri.name), Santri.id)
                .all())
    for student in students:
        students_by_class.setdefault(student.class_name, []).append({
            "id": student.id,
            "name": student.name,
            "nis": student.nis,
        })

    selected_class = request.form.get("class_name", "").strip() if request.method == "POST" else ""
    selected_student_id = request.form.get("student_id", type=int) if request.method == "POST" else None

    if request.method == "POST":
        if selected_class not in CLASSES or not selected_student_id:
            flash("Pilih kelas dan nama santri terlebih dahulu.", "danger")
            return render_template(
                "guardian_entry.html",
                students_by_class=students_by_class,
                class_name=selected_class,
                student_id=selected_student_id,
            ), 400

        student = db.session.get(Santri, selected_student_id)
        if not student or student.class_name != selected_class:
            flash("Data santri tidak ditemukan atau tidak sesuai dengan kelas yang dipilih.", "danger")
            return render_template(
                "guardian_entry.html",
                students_by_class=students_by_class,
                class_name=selected_class,
                student_id=selected_student_id,
            ), 404

        login_user(student.guardian, remember=False)
        session["guardian_student_id"] = student.id
        session["guardian_entry"] = True
        flash(f"Data ananda {student.name} berhasil dibuka.", "success")
        return redirect(url_for("dashboard"))

    return render_template("guardian_entry.html", students_by_class=students_by_class)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("dashboard"))
        logout_user()
        session.pop("guardian_student_id", None)
        session.pop("guardian_entry", None)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username, role="admin").first()
        if not user or not user.check_password(password):
            flash("Coba lagi", "danger")
            return render_template("login.html", username=username), 401
        login_user(user, remember=bool(request.form.get("remember")))
        session.pop("guardian_student_id", None)
        session.pop("guardian_entry", None)
        flash(f"Selamat datang, {user.full_name}.", "success")
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("login.html")


@app.route("/login")
def login():
    return redirect(url_for("admin_login"))


@app.route("/logout")
def logout():
    was_admin = current_user.is_authenticated and current_user.is_admin
    if current_user.is_authenticated:
        logout_user()
    session.pop("guardian_student_id", None)
    session.pop("guardian_entry", None)
    flash("Anda telah keluar." if was_admin else "Akses data ananda telah ditutup.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin:
        stats = {
            "students": Santri.query.count(),
            "unpaid": Iuran.query.filter(Iuran.status != "Lunas").count(),
            "pending_bills": Iuran.query.filter_by(status="Menunggu Verifikasi").count(),
            "pending_books": AksesKitab.query.filter_by(status="Menunggu Verifikasi").count(),
        }
        recent_students = Santri.query.order_by(Santri.created_at.desc()).limit(5).all()
        recent_bills = Iuran.query.order_by(Iuran.created_at.desc()).limit(6).all()
        curriculum_class = request.args.get("syllabus_class", "").strip()
        curriculum_rows = []
        if curriculum_class in CLASSES:
            curriculum_rows = (WeeklyCurriculum.query
                               .filter_by(class_name=curriculum_class)
                               .order_by(WeeklyCurriculum.week_number, WeeklyCurriculum.id)
                               .all())
        return render_template(
            "dashboard_admin.html", stats=stats, recent_students=recent_students,
            recent_bills=recent_bills, curriculum_class=curriculum_class,
            curriculum_rows=curriculum_rows
        )

    student = selected_guardian_student()
    if not student:
        logout_user()
        session.pop("guardian_student_id", None)
        flash("Silakan masukkan kembali nama santri dan kelas.", "info")
        return redirect(url_for("home"))

    raport = get_or_create_raport(student)
    db.session.commit()
    bills = (Iuran.query
             .filter_by(santri_id=student.id)
             .order_by(Iuran.year.desc(), Iuran.id.desc())
             .all())
    hafalan = raport.hafalan()
    mutabaah = raport.mutabaah()
    hafalan_done = sum(1 for surah in SURAH_JUZ30 if hafalan.get(surah))
    unpaid_count = sum(1 for bill in bills if bill.status != "Lunas")
    open_access_ids = {access.kitab_id for access in student.book_accesses if access.status == "Terbuka"}
    available_books = Kitab.query.filter((Kitab.price == 0) | (Kitab.id.in_(open_access_ids or {-1}))).count()

    return render_template(
        "dashboard_guardian.html",
        student=student,
        selected_student=student,
        raport=raport,
        bills=bills,
        mutabaah=mutabaah,
        hafalan=hafalan,
        hafalan_done=hafalan_done,
        unpaid_count=unpaid_count,
        available_books=available_books,
    )


@app.route("/students", methods=["GET", "POST"])
@admin_required
def students():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "")
        guardian_name = request.form.get("guardian_name", "").strip() or f"Wali {name}"
        if not name or class_name not in CLASSES:
            flash("Nama santri dan kelas wajib diisi.", "danger")
            return redirect(url_for("students"))

        nis = generate_nis()
        guardian_username = request.form.get("guardian_username", "").strip() or f"wali{nis}"
        base_username = guardian_username
        counter = 1
        while User.query.filter_by(username=guardian_username).first():
            guardian_username = f"{base_username}{counter}"
            counter += 1
        guardian = User(username=guardian_username, full_name=guardian_name, role="guardian")
        guardian.set_password(uuid.uuid4().hex)
        db.session.add(guardian)
        db.session.flush()

        student = Santri(nis=nis, name=name, class_name=class_name, guardian_id=guardian.id)
        db.session.add(student)
        db.session.flush()
        db.session.add(Raport(santri_id=student.id))
        db.session.commit()
        flash(f"Santri {name} berhasil ditambahkan dengan NIS {student.nis}.", "success")
        return redirect(url_for("students", q=name))

    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()
    query = Santri.query
    if q:
        query = query.filter(Santri.name.ilike(f"%{q}%"))
    if class_filter in CLASSES:
        query = query.filter_by(class_name=class_filter)
    total_matches = query.count()
    student_rows = query.order_by(Santri.name).limit(SEARCH_LIMIT).all()
    return render_template(
        "students.html", students=student_rows, class_filter=class_filter, q=q,
        total_matches=total_matches, search_limit=SEARCH_LIMIT
    )


@app.route("/students/bulk", methods=["GET", "POST"])
@admin_required
def bulk_students():
    results = []
    if request.method == "POST":
        raw = request.form.get("csv_data", "")
        reader = csv.reader(io.StringIO(raw))
        created = 0
        for index, row in enumerate(reader, start=1):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip().lower() in {"nama", "name"}:
                continue
            try:
                name = row[0].strip()
                class_name = row[1].strip()
                guardian_username = row[2].strip()
                guardian_name = row[3].strip() if len(row) > 3 and row[3].strip() else guardian_username
                guardian_password = row[4].strip() if len(row) > 4 and row[4].strip() else f"{guardian_username}123"
                if not name or class_name not in CLASSES or not guardian_username:
                    raise ValueError("Kolom wajib tidak lengkap atau kelas tidak valid")
                guardian = User.query.filter_by(username=guardian_username).first()
                if not guardian:
                    guardian = User(username=guardian_username, full_name=guardian_name, role="guardian")
                    guardian.set_password(guardian_password)
                    db.session.add(guardian)
                    db.session.flush()
                if guardian.role != "guardian":
                    raise ValueError("Username wali sudah dipakai akun non-wali")
                student = Santri(nis=generate_nis(), name=name, class_name=class_name, guardian_id=guardian.id)
                db.session.add(student)
                db.session.flush()
                db.session.add(Raport(santri_id=student.id))
                db.session.commit()
                created += 1
                results.append((index, name, "Berhasil"))
            except Exception as exc:
                db.session.rollback()
                results.append((index, row[0].strip() if row else "-", f"Gagal: {exc}"))
        flash(f"Impor selesai. {created} santri berhasil ditambahkan.", "success" if created else "warning")
    return render_template("bulk_students.html", results=results)


@app.route("/curriculum", methods=["GET", "POST"])
@admin_required
def curriculum():
    if request.method == "POST":
        try:
            class_name = request.form.get("class_name", "").strip()
            week_number = int(request.form.get("week_number", "1"))
            subject = request.form.get("subject", "").strip()
            topic = request.form.get("topic", "").strip()
            learning_target = request.form.get("learning_target", "").strip()
            activities = request.form.get("activities", "").strip()
            notes = request.form.get("notes", "").strip()
            if class_name not in CLASSES or week_number < 1 or week_number > 60:
                raise ValueError("Kelas atau pekan tidak valid")
            if not subject or not topic:
                raise ValueError("Bidang pelajaran dan materi pokok wajib diisi")
            row = WeeklyCurriculum(
                class_name=class_name, week_number=week_number, subject=subject, topic=topic,
                learning_target=learning_target, activities=activities, notes=notes
            )
            db.session.add(row)
            db.session.commit()
            flash("Silabus dan kurikulum pekanan berhasil disimpan.", "success")
            return redirect(url_for("curriculum", class_name=class_name))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    class_filter = request.args.get("class_name", "").strip()
    query = WeeklyCurriculum.query
    if class_filter in CLASSES:
        query = query.filter_by(class_name=class_filter)
    rows = query.order_by(WeeklyCurriculum.class_name, WeeklyCurriculum.week_number, WeeklyCurriculum.id).all()
    return render_template("curriculum.html", rows=rows, class_filter=class_filter)


@app.route("/curriculum/<int:row_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_curriculum(row_id):
    row = db.get_or_404(WeeklyCurriculum, row_id)
    if request.method == "POST":
        try:
            class_name = request.form.get("class_name", "").strip()
            week_number = int(request.form.get("week_number", "1"))
            subject = request.form.get("subject", "").strip()
            topic = request.form.get("topic", "").strip()
            if class_name not in CLASSES or not subject or not topic or not 1 <= week_number <= 60:
                raise ValueError("Lengkapi kelas, pekan, bidang pelajaran, dan materi pokok")
            row.class_name = class_name
            row.week_number = week_number
            row.subject = subject
            row.topic = topic
            row.learning_target = request.form.get("learning_target", "").strip()
            row.activities = request.form.get("activities", "").strip()
            row.notes = request.form.get("notes", "").strip()
            db.session.commit()
            flash("Silabus pekanan berhasil diperbarui.", "success")
            return redirect(url_for("curriculum", class_name=class_name))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("curriculum_edit.html", row=row)


@app.route("/curriculum/<int:row_id>/delete", methods=["POST"])
@admin_required
def delete_curriculum(row_id):
    row = db.get_or_404(WeeklyCurriculum, row_id)
    class_name = row.class_name
    db.session.delete(row)
    db.session.commit()
    flash("Baris silabus pekanan berhasil dihapus.", "info")
    return redirect(url_for("curriculum", class_name=class_name))


@app.route("/daily-progress")
@admin_required
def daily_progress():
    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()
    query = Santri.query
    if q:
        query = query.filter(Santri.name.ilike(f"%{q}%"))
    if class_filter in CLASSES:
        query = query.filter_by(class_name=class_filter)
    total_matches = query.count()
    students_rows = query.order_by(Santri.name).limit(SEARCH_LIMIT).all()
    return render_template(
        "daily_progress.html", students=students_rows, q=q, class_filter=class_filter,
        total_matches=total_matches, search_limit=SEARCH_LIMIT
    )


@app.route("/eraport")
@admin_required
def eraport():
    class_filter = request.args.get("class_name", "").strip()
    students_rows = []
    if class_filter in CLASSES:
        students_rows = Santri.query.filter_by(class_name=class_filter).order_by(Santri.name).all()
    return render_template("eraport.html", students=students_rows, class_filter=class_filter)


@app.route("/ananda/<int:student_id>")
@login_required
def guardian_student_detail(student_id):
    """Halaman perkembangan ananda tanpa nilai dan tanpa E-Raport."""
    if current_user.is_admin:
        return redirect(url_for("student_detail", student_id=student_id))
    student = db.get_or_404(Santri, student_id)
    selected = selected_guardian_student()
    if not selected or selected.id != student.id:
        abort(403)
    raport = get_or_create_raport(student)
    db.session.commit()
    bills = (Iuran.query
             .filter_by(santri_id=student.id)
             .order_by(Iuran.year.desc(), Iuran.id.desc())
             .all())
    return render_template(
        "guardian_student.html",
        student=student,
        raport=raport,
        mutabaah=raport.mutabaah(),
        hafalan=raport.hafalan(),
        bills=bills,
    )


@app.route("/student/<int:student_id>")
@admin_required
def student_detail(student_id):
    student = db.get_or_404(Santri, student_id)
    raport = get_or_create_raport(student)
    db.session.commit()
    bills = Iuran.query.filter_by(santri_id=student.id).order_by(Iuran.year.desc()).all()
    return render_template("student_detail.html", student=student, raport=raport, bills=bills)


@app.route("/student/<int:student_id>/delete", methods=["POST"])
@admin_required
def delete_student(student_id):
    student = db.get_or_404(Santri, student_id)
    name = student.name
    db.session.delete(student)
    db.session.commit()
    flash(f"Data {name} dihapus.", "info")
    return redirect(url_for("students"))


@app.route("/academics/<int:student_id>", methods=["GET", "POST"])
@admin_required
def academics(student_id):
    student = db.get_or_404(Santri, student_id)
    raport = get_or_create_raport(student)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_scores":
            scores = {}
            for field in SCORE_FIELDS[student.class_name]:
                raw = request.form.get(f"score_{field}", "0")
                try:
                    value = int(raw)
                except ValueError:
                    value = 0
                scores[field] = max(0, min(100, value))
            raport.scores_json = json.dumps(scores, ensure_ascii=False)
            raport.semester = request.form.get("semester", "Semester 1")
            raport.academic_year = request.form.get("academic_year", "2026/2027")
            flash("Nilai E-Raport berhasil disimpan.", "success")

        elif action == "add_mutabaah":
            entries = raport.mutabaah()
            entries.insert(0, {
                "date": request.form.get("date") or date.today().isoformat(),
                "tilawati": request.form.get("tilawati", "").strip(),
                "fiqih": request.form.get("fiqih", "").strip(),
                "notes": request.form.get("notes", "").strip(),
            })
            raport.mutabaah_json = json.dumps(entries[:100], ensure_ascii=False)
            flash("Jurnal mutabaah ditambahkan.", "success")

        elif action == "save_hafalan":
            completed = {surah: bool(request.form.get(f"surah_{i}")) for i, surah in enumerate(SURAH_JUZ30)}
            raport.hafalan_json = json.dumps(completed, ensure_ascii=False)
            flash("Progres hafalan Juz 30 disimpan.", "success")

        db.session.commit()
        return redirect(url_for("academics", student_id=student.id))

    return render_template("academics.html", student=student, raport=raport,
                           scores=raport.scores(), mutabaah=raport.mutabaah(), hafalan=raport.hafalan())


@app.route("/academics/<int:student_id>/mutabaah/<int:entry_index>/edit", methods=["GET", "POST"])
@admin_required
def edit_mutabaah(student_id, entry_index):
    student = db.get_or_404(Santri, student_id)
    raport = get_or_create_raport(student)
    entries = raport.mutabaah()
    if entry_index < 0 or entry_index >= len(entries):
        abort(404)
    entry = entries[entry_index]
    if request.method == "POST":
        entries[entry_index] = {
            "date": request.form.get("date") or date.today().isoformat(),
            "tilawati": request.form.get("tilawati", "").strip(),
            "fiqih": request.form.get("fiqih", "").strip(),
            "notes": request.form.get("notes", "").strip(),
        }
        raport.mutabaah_json = json.dumps(entries, ensure_ascii=False)
        db.session.commit()
        flash("Prestasi harian santri berhasil diperbarui.", "success")
        return redirect(url_for("academics", student_id=student.id, _anchor="mutabaah"))
    return render_template("mutabaah_edit.html", student=student, entry=entry, entry_index=entry_index)


@app.route("/academics/<int:student_id>/mutabaah/<int:entry_index>/delete", methods=["POST"])
@admin_required
def delete_mutabaah(student_id, entry_index):
    student = db.get_or_404(Santri, student_id)
    raport = get_or_create_raport(student)
    entries = raport.mutabaah()
    if entry_index < 0 or entry_index >= len(entries):
        abort(404)
    entries.pop(entry_index)
    raport.mutabaah_json = json.dumps(entries, ensure_ascii=False)
    db.session.commit()
    flash("Catatan prestasi harian berhasil dihapus.", "info")
    return redirect(url_for("academics", student_id=student.id, _anchor="mutabaah"))


def build_report_pdf(student, raport):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitle", parent=styles["Title"], alignment=TA_CENTER,
                              textColor=colors.HexColor("#024936"), fontSize=18, leading=22))
    story = [
        Paragraph("E-RAPORT SANTRI", styles["CenterTitle"]),
        Paragraph("TPQ HMarisa", ParagraphStyle(name="sub", parent=styles["Heading2"], alignment=TA_CENTER)),
        Spacer(1, 12),
    ]
    identity = [
        ["Nama Santri", student.name], ["NIS", student.nis], ["Kelas", student.class_name],
        ["Semester", raport.semester], ["Tahun Ajaran", raport.academic_year],
    ]
    ident_table = Table(identity, colWidths=[4 * cm, 12 * cm])
    ident_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e3df")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf5f2")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([ident_table, Spacer(1, 16), Paragraph("Nilai Akademik", styles["Heading2"])])

    score_rows = [["Mata Pelajaran", "Nilai", "Predikat"]]
    scores = raport.scores()
    for field in SCORE_FIELDS[student.class_name]:
        value = int(scores.get(field, 0) or 0)
        predicate = "A" if value >= 90 else "B" if value >= 80 else "C" if value >= 70 else "D"
        score_rows.append([field, str(value), predicate])
    score_table = Table(score_rows, colWidths=[10 * cm, 3 * cm, 3 * cm])
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#024936")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8c9c2")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([score_table, Spacer(1, 14)])

    hafalan = raport.hafalan()
    done = sum(1 for s in SURAH_JUZ30 if hafalan.get(s))
    story.append(Paragraph(f"Progres Hafalan Juz 30: <b>{done} dari {len(SURAH_JUZ30)} surah</b>", styles["BodyText"]))
    story.append(Spacer(1, 24))

    signatures = [
        ["Mengetahui,", "Wali Kelas"],
        ["Kepala TPQ HMarisa", student.class_name],
        ["\n\n\n", "\n\n\n"],
        [PRINCIPAL, TEACHERS[student.class_name]],
    ]
    sig_table = Table(signatures, colWidths=[8 * cm, 8 * cm])
    sig_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("LINEBELOW", (0, 3), (-1, 3), 0.6, colors.black),
    ]))
    story.append(sig_table)
    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route("/report/<int:student_id>/pdf")
@admin_required
def report_pdf(student_id):
    student = db.get_or_404(Santri, student_id)
    raport = get_or_create_raport(student)
    db.session.commit()
    pdf = build_report_pdf(student, raport)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", student.name)
    return send_file(pdf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"E-Raport_{safe_name}.pdf")


@app.route("/finance", methods=["GET", "POST"])
@admin_required
def finance():
    if request.method == "POST":
        try:
            student_id = int(request.form.get("student_id", "0"))
            month = request.form.get("month", "")
            year = int(request.form.get("year", "2026"))
            nominal = int(request.form.get("nominal", "50000"))
            status = request.form.get("status", "Belum Lunas")
            if month not in MONTHS or year < 2026 or year > 2040 or nominal < 0:
                raise ValueError("Data tagihan tidak valid")
            db.get_or_404(Santri, student_id)
            bill = Iuran(santri_id=student_id, month=month, year=year,
                         nominal=nominal, status=status)
            db.session.add(bill)
            db.session.commit()
            flash("Tagihan berhasil dibuat.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Tagihan gagal dibuat: {exc}", "danger")
        return redirect(url_for("finance", q=request.form.get("student_name", ""), month=request.form.get("month", "")))

    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()
    month_filter = request.args.get("month", "").strip()
    query = Iuran.query.join(Santri)
    if q:
        query = query.filter(Santri.name.ilike(f"%{q}%"))
    if class_filter in CLASSES:
        query = query.filter(Santri.class_name == class_filter)
    if month_filter in MONTHS:
        query = query.filter(Iuran.month == month_filter)
    total_matches = query.count()
    bills = query.order_by(Iuran.year.desc(), Iuran.id.desc()).limit(60).all()
    student_rows = Santri.query.order_by(Santri.name).all()
    return render_template(
        "finance.html", bills=bills, students=student_rows, years=range(2026, 2041),
        q=q, class_filter=class_filter, month_filter=month_filter,
        total_matches=total_matches
    )


@app.route("/finance/<int:bill_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_bill(bill_id):
    bill = db.get_or_404(Iuran, bill_id)
    if request.method == "POST":
        try:
            student_id = int(request.form.get("student_id", "0"))
            month = request.form.get("month", "").strip()
            year = int(request.form.get("year", "2026"))
            status = request.form.get("status", "Belum Lunas").strip()
            nominal = int(request.form.get("nominal", "50000"))
            if month not in MONTHS or not 2026 <= year <= 2040 or nominal < 0:
                raise ValueError("Data administrasi tidak valid")
            db.get_or_404(Santri, student_id)
            bill.santri_id = student_id
            bill.month = month
            bill.year = year
            bill.status = status
            bill.nominal = nominal
            if status == "Lunas" and not bill.verified_at:
                bill.verified_at = datetime.utcnow()
            elif status != "Lunas":
                bill.verified_at = None
            db.session.commit()
            flash("Data administrasi santri berhasil diperbarui.", "success")
            return redirect(url_for("finance", q=bill.santri.name, class_name=bill.santri.class_name, month=bill.month))
        except Exception as exc:
            db.session.rollback()
            flash(f"Perubahan gagal disimpan: {exc}", "danger")
    students_rows = Santri.query.order_by(Santri.name).all()
    return render_template("finance_edit.html", bill=bill, students=students_rows, years=range(2026, 2041))


@app.route("/bill/<int:bill_id>/upload", methods=["POST"])
@login_required
def upload_bill_proof(bill_id):
    bill = db.get_or_404(Iuran, bill_id)
    selected = selected_guardian_student()
    if current_user.is_admin or not selected or bill.santri_id != selected.id:
        abort(403)
    if bill.status == "Lunas":
        flash("Tagihan ini sudah lunas.", "info")
        return redirect(url_for("guardian_student_detail", student_id=bill.santri_id))
    try:
        filename = save_upload(request.files.get("proof"), PROOF_DIR, {"jpg", "jpeg", "png", "pdf"})
        if not filename:
            raise ValueError("Pilih file bukti transfer")
        if bill.proof_path:
            old = os.path.join(PROOF_DIR, bill.proof_path)
            if os.path.exists(old):
                os.remove(old)
        bill.proof_path = filename
        bill.status = "Menunggu Verifikasi"
        db.session.commit()
        flash("Bukti transfer terkirim dan menunggu verifikasi admin.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("guardian_student_detail", student_id=bill.santri_id))


@app.route("/bill/<int:bill_id>/verify", methods=["POST"])
@admin_required
def verify_bill(bill_id):
    bill = db.get_or_404(Iuran, bill_id)
    bill.status = "Lunas"
    bill.verified_at = datetime.utcnow()
    db.session.commit()
    flash("Pembayaran telah diverifikasi dan ditandai Lunas.", "success")
    return redirect(url_for("finance"))


@app.route("/bill/<int:bill_id>/receipt")
@login_required
def bill_receipt(bill_id):
    bill = db.get_or_404(Iuran, bill_id)
    if not current_user.is_admin:
        selected = selected_guardian_student()
        if not selected or bill.santri_id != selected.id:
            abort(403)
    return render_template("receipt.html", bill=bill)


@app.route("/bill/<int:bill_id>/whatsapp")
@login_required
def bill_whatsapp(bill_id):
    bill = db.get_or_404(Iuran, bill_id)
    if not current_user.is_admin:
        selected = selected_guardian_student()
        if not selected or bill.santri_id != selected.id:
            abort(403)
    text = (f"Assalamu'alaikum, berikut tagihan iuran TPQ ananda {bill.santri.name} "
            f"bulan {bill.month}. Nominal: {rupiah(bill.nominal)}. Terima kasih.")
    return redirect(f"https://wa.me/?text={quote(text)}")


@app.route("/proof/bill/<int:bill_id>")
@admin_required
def view_bill_proof(bill_id):
    bill = db.get_or_404(Iuran, bill_id)
    if not bill.proof_path:
        abort(404)
    return send_from_directory(PROOF_DIR, bill.proof_path)


@app.route("/library")
@login_required
def library():
    selected_category = request.args.get("category", "").strip()
    query = Kitab.query
    if selected_category in BOOK_CATEGORIES:
        query = query.filter_by(category=selected_category)
    books = query.order_by(Kitab.uploaded_at.desc()).all()
    selected_student = None
    access_map = {}
    if not current_user.is_admin:
        selected_student = selected_guardian_student()
        if not selected_student:
            flash("Silakan pilih data santri terlebih dahulu.", "info")
            return redirect(url_for("home"))
        access_map = {a.kitab_id: a for a in selected_student.book_accesses}
    pending = AksesKitab.query.filter_by(status="Menunggu Verifikasi").all() if current_user.is_admin else []
    return render_template(
        "library.html", books=books, student=selected_student, access_map=access_map,
        pending=pending, selected_category=selected_category
    )


@app.route("/library/upload", methods=["GET", "POST"])
@admin_required
def upload_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        try:
            price = max(0, int(request.form.get("price", "0")))
            if category not in BOOK_CATEGORIES:
                raise ValueError("Pilih kategori kitab yang tersedia")
            pdf = request.files.get("pdf")
            if not title or not pdf or not pdf.filename:
                raise ValueError("Judul dan file PDF wajib diisi")
            original_filename = secure_filename(pdf.filename)
            if not original_filename.lower().endswith(".pdf"):
                raise ValueError("Buku harus berupa PDF")
            temp_name = f"tmp_{uuid.uuid4().hex}.pdf"
            temp_path = os.path.join(BOOK_DIR, temp_name)
            pdf.save(temp_path)
            original_size = os.path.getsize(temp_path)
            final_name = f"{uuid.uuid4().hex}.pdf"
            final_path = os.path.join(BOOK_DIR, final_name)
            try:
                import fitz
                doc = fitz.open(temp_path)
                doc.save(final_path, garbage=4, deflate=True, clean=True)
                doc.close()
                os.remove(temp_path)
            except Exception:
                shutil.move(temp_path, final_path)
            optimized_size = os.path.getsize(final_path)
            book = Kitab(title=title, description=description, category=category, price=price,
                         filename=final_name, original_filename=original_filename,
                         original_size=original_size, optimized_size=optimized_size)
            db.session.add(book)
            db.session.commit()
            flash("Buku berhasil diunggah dan dioptimalkan.", "success")
            return redirect(url_for("library"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("library_upload.html")


@app.route("/library/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_book(book_id):
    book = db.get_or_404(Kitab, book_id)
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            category = request.form.get("category", "").strip()
            price = max(0, int(request.form.get("price", "0")))
            if not title:
                raise ValueError("Judul buku wajib diisi")
            if category not in BOOK_CATEGORIES:
                raise ValueError("Pilih kategori kitab yang tersedia")

            replacement_pdf = request.files.get("pdf")
            if replacement_pdf and replacement_pdf.filename:
                original_filename = secure_filename(replacement_pdf.filename)
                if not original_filename.lower().endswith(".pdf"):
                    raise ValueError("Buku harus berupa PDF")
                temp_name = f"tmp_{uuid.uuid4().hex}.pdf"
                temp_path = os.path.join(BOOK_DIR, temp_name)
                replacement_pdf.save(temp_path)
                original_size = os.path.getsize(temp_path)
                final_name = f"{uuid.uuid4().hex}.pdf"
                final_path = os.path.join(BOOK_DIR, final_name)
                try:
                    import fitz
                    doc = fitz.open(temp_path)
                    doc.save(final_path, garbage=4, deflate=True, clean=True)
                    doc.close()
                    os.remove(temp_path)
                except Exception:
                    shutil.move(temp_path, final_path)

                old_filename = book.filename
                old_path = os.path.join(BOOK_DIR, old_filename or "")
                if old_filename:
                    clear_book_preview_cache(old_filename)
                if old_filename and os.path.exists(old_path):
                    os.remove(old_path)
                book.filename = final_name
                book.original_filename = original_filename
                book.original_size = original_size
                book.optimized_size = os.path.getsize(final_path)

            book.title = title
            book.description = description
            book.category = category
            book.price = price
            db.session.commit()
            flash("Data buku berhasil diperbarui.", "success")
            return redirect(url_for("library"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("library_edit.html", book=book)


@app.route("/library/<int:book_id>/delete", methods=["POST"])
@admin_required
def delete_book(book_id):
    book = db.get_or_404(Kitab, book_id)
    title = book.title
    filename = book.filename
    path = os.path.join(BOOK_DIR, filename or "")
    proof_paths = [access.proof_path for access in book.accesses if access.proof_path]
    db.session.delete(book)
    db.session.commit()
    if filename:
        clear_book_preview_cache(filename)
    if filename and os.path.exists(path):
        os.remove(path)
    for proof_name in proof_paths:
        proof_path = os.path.join(PROOF_DIR, proof_name)
        if os.path.exists(proof_path):
            os.remove(proof_path)
    flash(f"Buku {title} berhasil dihapus.", "info")
    return redirect(url_for("library"))


@app.route("/library/access/<int:access_id>/revoke", methods=["POST"])
@admin_required
def revoke_book_access(access_id):
    access = db.get_or_404(AksesKitab, access_id)
    student_name = access.santri.name
    book_title = access.kitab.title
    access.status = "Terkunci"
    access.confirmed_at = None
    db.session.commit()
    flash(f"Akses {book_title} untuk {student_name} telah ditutup.", "info")
    return redirect(url_for("library"))


@app.route("/library/<int:book_id>/purchase")
@login_required
def purchase_book(book_id):
    if current_user.is_admin:
        return redirect(url_for("download_book", book_id=book_id))
    book = db.get_or_404(Kitab, book_id)
    student = selected_guardian_student()
    if not student:
        abort(403)
    access = AksesKitab.query.filter_by(kitab_id=book.id, santri_id=student.id).first()
    if has_book_access(book, student):
        return redirect(url_for("download_book", book_id=book.id))
    return render_template("library_purchase.html", book=book, student=student, access=access)


@app.route("/library/<int:book_id>/unlock", methods=["POST"])
@login_required
def request_book_unlock(book_id):
    if current_user.is_admin:
        abort(403)
    book = db.get_or_404(Kitab, book_id)
    if book.price == 0:
        flash("Buku ini gratis dan dapat langsung dibuka tanpa pembayaran.", "info")
        return redirect(url_for("library"))
    student_id = request.form.get("student_id", type=int)
    student = db.get_or_404(Santri, student_id)
    selected = selected_guardian_student()
    if not selected or student.id != selected.id:
        abort(403)
    try:
        filename = save_upload(request.files.get("proof"), PROOF_DIR, {"jpg", "jpeg", "png", "pdf"})
        if not filename:
            raise ValueError("Unggah bukti transfer terlebih dahulu")
        access = AksesKitab.query.filter_by(kitab_id=book.id, santri_id=student.id).first()
        if not access:
            access = AksesKitab(kitab_id=book.id, santri_id=student.id)
            db.session.add(access)
        if access.proof_path:
            old = os.path.join(PROOF_DIR, access.proof_path)
            if os.path.exists(old):
                os.remove(old)
        access.proof_path = filename
        access.status = "Menunggu Verifikasi"
        access.requested_at = datetime.utcnow()
        db.session.commit()
        flash("Permintaan unlock terkirim. Admin akan memverifikasi pembayaran.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("purchase_book", book_id=book.id))


@app.route("/library/access/<int:access_id>/confirm", methods=["POST"])
@admin_required
def confirm_book_access(access_id):
    access = db.get_or_404(AksesKitab, access_id)
    access.status = "Terbuka"
    access.confirmed_at = datetime.utcnow()
    db.session.commit()
    flash(f"Buku {access.kitab.title} dibuka untuk {access.santri.name}.", "success")
    return redirect(url_for("library"))


@app.route("/proof/book/<int:access_id>")
@admin_required
def view_book_proof(access_id):
    access = db.get_or_404(AksesKitab, access_id)
    if not access.proof_path:
        abort(404)
    return send_from_directory(PROOF_DIR, access.proof_path)


def has_book_access(book, student):
    # Admin selalu memiliki akses penuh. Buku harga Rp 0 otomatis gratis bagi wali.
    if current_user.is_admin or book.price == 0:
        return True
    access = AksesKitab.query.filter_by(kitab_id=book.id, santri_id=student.id).first()
    return bool(access and access.status == "Terbuka")


def preview_cache_directory(filename):
    safe_stem = os.path.splitext(os.path.basename(filename or "book"))[0]
    return os.path.join(PREVIEW_DIR, safe_stem)


def clear_book_preview_cache(filename):
    cache_dir = preview_cache_directory(filename)
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)


def build_book_preview(pdf_path, filename, page_number):
    """Render one real PDF page to a cached JPEG preview."""
    import fitz

    cache_dir = preview_cache_directory(filename)
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"page_{page_number}.jpg")
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return output_path

    doc = fitz.open(pdf_path)
    try:
        if doc.needs_pass:
            raise ValueError("PDF terkunci dengan kata sandi")
        if page_number < 1 or page_number > doc.page_count:
            return None
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image_bytes = pix.tobytes("jpeg", jpg_quality=84)
        temporary_path = f"{output_path}.tmp"
        with open(temporary_path, "wb") as preview_file:
            preview_file.write(image_bytes)
        os.replace(temporary_path, output_path)
        return output_path
    finally:
        doc.close()


@app.route("/library/<int:book_id>/preview/<int:page_number>")
@login_required
def book_preview(book_id, page_number):
    book = db.get_or_404(Kitab, book_id)
    if page_number < 1:
        abort(404)
    if not current_user.is_admin:
        student = selected_guardian_student()
        if not student:
            abort(403)
        unlocked = has_book_access(book, student)
        if not unlocked and page_number > PREVIEW_PAGE_LIMIT:
            abort(403)
    if not book.filename:
        abort(404)

    pdf_path = os.path.join(BOOK_DIR, book.filename)
    if not os.path.exists(pdf_path):
        abort(404)

    try:
        preview_path = build_book_preview(pdf_path, book.filename, page_number)
        if not preview_path:
            abort(404)
        return send_file(preview_path, mimetype="image/jpeg", conditional=True, max_age=86400)
    except (ValueError, RuntimeError):
        abort(422)
    except Exception:
        app.logger.exception("Gagal membuat pratinjau PDF untuk buku %s halaman %s", book.id, page_number)
        abort(500)


@app.route("/library/<int:book_id>/download")
@login_required
def download_book(book_id):
    book = db.get_or_404(Kitab, book_id)
    if not current_user.is_admin:
        student = selected_guardian_student()
        if not student:
            abort(403)
        if not has_book_access(book, student):
            flash("Buku penuh dapat diunduh setelah pembelian dan verifikasi admin.", "info")
            return redirect(url_for("purchase_book", book_id=book.id))
    path = os.path.join(BOOK_DIR, book.filename or "")
    if not book.filename or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=book.original_filename or f"{book.title}.pdf")


@app.route("/backup/academic.csv")
@admin_required
def backup_academic():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["NIS", "Nama", "Kelas", "Wali", "Semester", "Tahun Ajaran", "Nilai JSON", "Hafalan JSON", "Mutabaah JSON"])
    for student in Santri.query.order_by(Santri.nis).all():
        raport = get_or_create_raport(student)
        writer.writerow([student.nis, student.name, student.class_name, student.guardian.username,
                         raport.semester, raport.academic_year, raport.scores_json,
                         raport.hafalan_json, raport.mutabaah_json])
    db.session.commit()
    data = output.getvalue().encode("utf-8-sig")
    return Response(data, mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=backup_akademik_{date.today().isoformat()}.csv"
    })


@app.route("/backup/financial.csv")
@admin_required
def backup_financial():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["NIS", "Nama", "Bulan", "Tahun", "Status", "Nominal", "Tanggal Verifikasi"])
    for bill in Iuran.query.order_by(Iuran.year, Iuran.id).all():
        writer.writerow([bill.santri.nis, bill.santri.name, bill.month, bill.year,
                         bill.status, bill.nominal, bill.verified_at or ""])
    data = output.getvalue().encode("utf-8-sig")
    return Response(data, mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=backup_keuangan_{date.today().isoformat()}.csv"
    })


@app.route("/backup/database.sql")
@admin_required
def backup_database():
    db_path = os.path.join(app.instance_path, "tpq_hmarisa.db")
    if not os.path.exists(db_path):
        abort(404)
    connection = sqlite3.connect(db_path)
    dump = "\n".join(connection.iterdump())
    connection.close()
    return Response(dump, mimetype="application/sql", headers={
        "Content-Disposition": f"attachment; filename=tpq_hmarisa_{date.today().isoformat()}.sql"
    })


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="Anda tidak memiliki akses ke halaman ini."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="Halaman atau data tidak ditemukan."), 404


@app.errorhandler(413)
def too_large(_error):
    flash("Ukuran file terlalu besar. Maksimal 25 MB.", "danger")
    return redirect(request.referrer or url_for("dashboard"))


def ensure_schema_updates():
    """Add new columns safely when an older SQLite database is reused."""
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if "kitab" in table_names:
        columns = {column["name"] for column in inspector.get_columns("kitab")}
        if "category" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE kitab ADD COLUMN category VARCHAR(80) DEFAULT 'Kitab Fiqih'"
                ))
        with db.engine.begin() as connection:
            connection.execute(text(
                "UPDATE kitab SET category = 'Kitab Fiqih' WHERE category IS NULL OR category = ''"
            ))


def create_sample_book():
    path = os.path.join(BOOK_DIR, "sample_panduan_wudhu.pdf")
    if os.path.exists(path):
        return path
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(path, pagesize=A4)
        width, height = A4
        pages = [
            ("Panduan Wudhu Anak", "Belajar wudhu dengan tertib, bersih, dan menyenangkan."),
            ("Langkah 1", "Niat, membaca basmalah, lalu membasuh kedua telapak tangan."),
            ("Langkah 2", "Berkumur, membersihkan hidung, kemudian membasuh wajah."),
            ("Langkah 3", "Membasuh tangan, mengusap kepala dan telinga, lalu membasuh kaki."),
        ]
        for title, body in pages:
            c.setFillColorRGB(0.01, 0.29, 0.21)
            c.rect(0, height - 120, width, 120, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 24)
            c.drawCentredString(width / 2, height - 72, title)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setFont("Helvetica", 15)
            text = c.beginText(70, height - 190)
            text.setLeading(24)
            for line in body.split(". "):
                text.textLine(line.strip())
            c.drawText(text)
            c.setFillColorRGB(0.9, 0.66, 0.23)
            c.circle(width / 2, height / 2 - 40, 70, fill=1, stroke=0)
            c.showPage()
        c.save()
    except Exception:
        return None
    return path


def seed_database():
    admin = User.query.filter_by(username="tpqhmarisa").first()
    if not admin:
        admin = User(username="tpqhmarisa", full_name="Administrator TPQ HMarisa", role="admin")
        admin.set_password("tpqhmarisa")
        db.session.add(admin)

    guardian = User.query.filter_by(username="walizaki").first()
    if not guardian:
        guardian = User(username="walizaki", full_name="Wali Ahmad Zaki", role="guardian")
        guardian.set_password("walizaki123")
        db.session.add(guardian)
        db.session.flush()

    student = Santri.query.filter_by(name="Ahmad Zaki Al-Fatih").first()
    if not student:
        student = Santri(nis="26001", name="Ahmad Zaki Al-Fatih", class_name="Ar-Rahim",
                         guardian_id=guardian.id)
        db.session.add(student)
        db.session.flush()
        scores = {"BTQ": 88, "Hafalan Doa": 90, "Praktek Ibadah": 86, "Adab/Akhlak": 92}
        mutabaah = [
            {"date": "2026-07-10", "tilawati": "Tilawati Jilid 2 halaman 14", "fiqih": "Rukun wudhu", "notes": "Makhraj semakin baik."},
            {"date": "2026-07-08", "tilawati": "Tilawati Jilid 2 halaman 12", "fiqih": "Adab ke masjid", "notes": "Perlu murojaah harakat kasrah."},
        ]
        hafalan = {surah: i >= len(SURAH_JUZ30) - 5 for i, surah in enumerate(SURAH_JUZ30)}
        db.session.add(Raport(santri_id=student.id, scores_json=json.dumps(scores, ensure_ascii=False),
                              mutabaah_json=json.dumps(mutabaah, ensure_ascii=False),
                              hafalan_json=json.dumps(hafalan, ensure_ascii=False)))
        db.session.add_all([
            Iuran(santri_id=student.id, month="Juli", year=2026, status="Lunas", nominal=50000, verified_at=datetime.utcnow()),
            Iuran(santri_id=student.id, month="Agustus", year=2026, status="Belum Lunas", nominal=50000),
        ])

    if Kitab.query.count() == 0:
        sample_path = create_sample_book()
        if sample_path:
            size = os.path.getsize(sample_path)
            book = Kitab(title="Panduan Wudhu Anak", description="Buku digital ringkas untuk mengenalkan urutan wudhu kepada santri.",
                         category="Kitab Fiqih", price=25000, filename=os.path.basename(sample_path),
                         original_filename="Panduan Wudhu Anak.pdf", original_size=size, optimized_size=size)
            db.session.add(book)

    db.session.commit()


with app.app_context():
    db.create_all()
    ensure_schema_updates()
    seed_database()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
