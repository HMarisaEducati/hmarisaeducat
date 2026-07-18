"""E-Raport Final V10 untuk Portal TPQ HMarisa.

Modul ini dipasang secara terarah: route lama E-Raport dipertahankan URL-nya,
namun view function-nya diganti. Data raport per periode disimpan di tabel baru
`eraport_period_v10` agar satu santri dapat memiliki raport untuk setiap
Tahun Ajaran + Semester tanpa mengubah tabel produksi lama.
"""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import text


TABLE_NAME = "eraport_period_v10"
ALLOWED_STATUSES = {"Draf", "Diterbitkan"}
ATTITUDE_KEYS = ["Kehadiran", "Kedisiplinan", "Keterlibatan", "Pergaulan/Perilaku"]
ATTENDANCE_KEYS = ["Sakit", "Izin", "Tanpa Keterangan"]
ATTITUDE_OPTIONS = [
    ("A", "Sangat Baik"),
    ("B", "Baik"),
    ("C", "Cukup"),
    ("D", "Perlu Bimbingan"),
]


@dataclass
class PeriodReport:
    id: int | None
    santri_id: int
    academic_year: str
    semester: str
    scores_json: str = "{}"
    attitude_json: str = "{}"
    absence_json: str = "{}"
    development_notes: str = ""
    status: str = "Draf"
    completeness: int = 0
    publish_date: date | None = None
    published_at: datetime | None = None
    version: int = 1
    snapshot_json: str = "{}"
    updated_at: datetime | None = None

    @classmethod
    def from_mapping(cls, row: Any) -> "PeriodReport":
        data = dict(row)
        for key in ("publish_date",):
            value = data.get(key)
            if isinstance(value, str) and value:
                try:
                    data[key] = date.fromisoformat(value[:10])
                except ValueError:
                    data[key] = None
        for key in ("published_at", "updated_at"):
            value = data.get(key)
            if isinstance(value, str) and value:
                try:
                    data[key] = datetime.fromisoformat(value)
                except ValueError:
                    data[key] = None
        return cls(**data)

    def _json(self, value: str, fallback: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def scores(self) -> dict[str, Any]:
        return self._json(self.scores_json, {})

    def attitude(self) -> dict[str, Any]:
        return self._json(self.attitude_json, {})

    def absence(self) -> dict[str, Any]:
        return self._json(self.absence_json, {})

    def snapshot(self) -> dict[str, Any]:
        return self._json(self.snapshot_json, {})


class EraportV10:
    def __init__(self, app, db, ns: dict[str, Any]):
        self.app = app
        self.db = db
        self.ns = ns
        self.Santri = ns["Santri"]
        self.LegacyRaport = ns["Raport"]
        self.HafalanRecord = ns["HafalanRecord"]
        self.AcademicYear = ns.get("AcademicYear")
        self.SURAH_JUZ30 = ns["SURAH_JUZ30"]
        self.active_class_names = ns["active_class_names"]
        self.normalize_class_name = ns["normalize_class_name"]
        self.class_subjects = ns["class_subjects"]
        self.class_teacher = ns["class_teacher"]
        self.score_predicate = ns["score_predicate"]
        self.jakarta_now = ns["jakarta_now"]
        self.current_hafalan_status = ns["current_hafalan_status"]
        self.PRINCIPAL = ns.get("PRINCIPAL", "Kepala TPQ HMarisa")
        self._storage_ready = False

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def ensure_storage(self) -> None:
        if self._storage_ready:
            return
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            santri_id INTEGER NOT NULL,
            academic_year VARCHAR(20) NOT NULL,
            semester VARCHAR(20) NOT NULL,
            scores_json TEXT NOT NULL DEFAULT '{{}}',
            attitude_json TEXT NOT NULL DEFAULT '{{}}',
            absence_json TEXT NOT NULL DEFAULT '{{}}',
            development_notes TEXT NOT NULL DEFAULT '',
            status VARCHAR(30) NOT NULL DEFAULT 'Draf',
            completeness INTEGER NOT NULL DEFAULT 0,
            publish_date VARCHAR(10),
            published_at VARCHAR(40),
            version INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT NOT NULL DEFAULT '{{}}',
            updated_at VARCHAR(40) NOT NULL,
            UNIQUE(santri_id, academic_year, semester)
        )
        """
        with self.db.engine.begin() as conn:
            conn.execute(text(ddl))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{TABLE_NAME}_student_period "
                f"ON {TABLE_NAME}(santri_id, academic_year, semester)"
            ))
        self._migrate_legacy_rows()
        self._storage_ready = True

    def _migrate_legacy_rows(self) -> None:
        try:
            legacy_rows = self.LegacyRaport.query.all()
        except Exception:
            return
        for old in legacy_rows:
            year = (old.academic_year or "2026/2027").strip()
            semester = (old.semester or "Semester 1").strip()
            if semester not in {"Semester 1", "Semester 2"}:
                semester = "Semester 1"
            status = "Diterbitkan" if old.status == "Diterbitkan" else "Draf"
            payload = {
                "santri_id": old.santri_id,
                "academic_year": year,
                "semester": semester,
                "scores_json": old.scores_json or "{}",
                "attitude_json": old.attitude_json or "{}",
                "absence_json": self._normalize_absence_json(old.absence_json),
                "development_notes": old.development_notes or "",
                "status": status,
                "completeness": int(old.completeness or 0),
                "publish_date": old.publish_date.isoformat() if old.publish_date else None,
                "published_at": old.published_at.isoformat() if old.published_at else None,
                "version": int(old.version or 1),
                "snapshot_json": old.snapshot_json or "{}",
                "updated_at": (old.updated_at or datetime.utcnow()).isoformat(),
            }
            self._insert_if_missing(payload)

    @staticmethod
    def _normalize_absence_json(raw: str | None) -> str:
        try:
            current = json.loads(raw or "{}")
        except (ValueError, TypeError):
            current = {}
        clean: dict[str, dict[str, int]] = {}
        for key in ATTENDANCE_KEYS:
            item = current.get(key, {})
            if isinstance(item, dict):
                count = item.get("count", 0)
            else:
                count = item
            try:
                count = max(0, int(count or 0))
            except (TypeError, ValueError):
                count = 0
            clean[key] = {"count": count}
        return json.dumps(clean, ensure_ascii=False)

    def _insert_if_missing(self, payload: dict[str, Any]) -> None:
        sql = text(f"""
            INSERT OR IGNORE INTO {TABLE_NAME}
            (santri_id, academic_year, semester, scores_json, attitude_json,
             absence_json, development_notes, status, completeness, publish_date,
             published_at, version, snapshot_json, updated_at)
            VALUES
            (:santri_id, :academic_year, :semester, :scores_json, :attitude_json,
             :absence_json, :development_notes, :status, :completeness, :publish_date,
             :published_at, :version, :snapshot_json, :updated_at)
        """)
        with self.db.engine.begin() as conn:
            conn.execute(sql, payload)

    def get_report(self, student_id: int, academic_year: str, semester: str, create: bool = True) -> PeriodReport | None:
        self.ensure_storage()
        sql = text(f"""
            SELECT * FROM {TABLE_NAME}
            WHERE santri_id=:sid AND academic_year=:year AND semester=:semester
            LIMIT 1
        """)
        with self.db.engine.begin() as conn:
            row = conn.execute(sql, {"sid": student_id, "year": academic_year, "semester": semester}).mappings().first()
        if row:
            return PeriodReport.from_mapping(row)
        if not create:
            return None
        now = datetime.utcnow().isoformat()
        self._insert_if_missing({
            "santri_id": student_id,
            "academic_year": academic_year,
            "semester": semester,
            "scores_json": "{}",
            "attitude_json": "{}",
            "absence_json": self._normalize_absence_json("{}"),
            "development_notes": "",
            "status": "Draf",
            "completeness": 0,
            "publish_date": None,
            "published_at": None,
            "version": 1,
            "snapshot_json": "{}",
            "updated_at": now,
        })
        return self.get_report(student_id, academic_year, semester, create=False)

    def latest_report(self, student_id: int, published_only: bool = False) -> PeriodReport | None:
        self.ensure_storage()
        where = "AND status='Diterbitkan'" if published_only else ""
        sql = text(f"""
            SELECT * FROM {TABLE_NAME}
            WHERE santri_id=:sid {where}
            ORDER BY COALESCE(published_at, updated_at) DESC, id DESC
            LIMIT 1
        """)
        with self.db.engine.begin() as conn:
            row = conn.execute(sql, {"sid": student_id}).mappings().first()
        return PeriodReport.from_mapping(row) if row else None

    def save_report(self, report: PeriodReport) -> PeriodReport:
        report.status = report.status if report.status in ALLOWED_STATUSES else "Draf"
        report.updated_at = datetime.utcnow()
        sql = text(f"""
            UPDATE {TABLE_NAME}
            SET scores_json=:scores_json,
                attitude_json=:attitude_json,
                absence_json=:absence_json,
                development_notes=:development_notes,
                status=:status,
                completeness=:completeness,
                publish_date=:publish_date,
                published_at=:published_at,
                version=:version,
                snapshot_json=:snapshot_json,
                updated_at=:updated_at
            WHERE santri_id=:santri_id AND academic_year=:academic_year AND semester=:semester
        """)
        values = {
            "scores_json": report.scores_json or "{}",
            "attitude_json": report.attitude_json or "{}",
            "absence_json": self._normalize_absence_json(report.absence_json),
            "development_notes": report.development_notes or "",
            "status": report.status,
            "completeness": int(report.completeness or 0),
            "publish_date": report.publish_date.isoformat() if report.publish_date else None,
            "published_at": report.published_at.isoformat() if report.published_at else None,
            "version": int(report.version or 1),
            "snapshot_json": report.snapshot_json or "{}",
            "updated_at": report.updated_at.isoformat(),
            "santri_id": report.santri_id,
            "academic_year": report.academic_year,
            "semester": report.semester,
        }
        with self.db.engine.begin() as conn:
            result = conn.execute(sql, values)
        if not result.rowcount:
            values["id"] = None
            self._insert_if_missing(values)
        return self.get_report(report.santri_id, report.academic_year, report.semester, create=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def require_staff(self) -> None:
        if not current_user.is_authenticated:
            abort(401)
        if not getattr(current_user, "is_admin", False):
            abort(403)

    def can_view_student(self, student) -> bool:
        if not current_user.is_authenticated:
            return False
        if getattr(current_user, "is_admin", False):
            return True
        return bool(getattr(student, "guardian_id", None) == getattr(current_user, "id", None))

    def period_options(self) -> list[tuple[str, str, str]]:
        names: list[str] = []
        if self.AcademicYear is not None:
            try:
                names = [row.name for row in self.AcademicYear.query.order_by(self.AcademicYear.name.desc()).all()]
            except Exception:
                names = []
        if not names:
            names = ["2026/2027"]
        result = []
        for year in names:
            for semester in ("Semester 1", "Semester 2"):
                result.append((self.period_value(year, semester), year, semester))
        return result

    @staticmethod
    def period_value(year: str, semester: str) -> str:
        return f"{year}|{semester}"

    def default_period(self) -> tuple[str, str]:
        options = self.period_options()
        if not options:
            return "2026/2027", "Semester 1"
        current_semester = "Semester 1" if self.jakarta_now().month >= 7 else "Semester 2"
        for _, year, semester in options:
            if semester == current_semester:
                return year, semester
        return options[0][1], options[0][2]

    def parse_period(self, value: str | None = None) -> tuple[str, str]:
        value = value or request.values.get("period", "")
        if value and "|" in value:
            year, semester = value.split("|", 1)
        else:
            year = request.values.get("academic_year", "")
            semester = request.values.get("semester", "")
        year = year.strip()
        semester = semester.strip()
        valid = {(y, s) for _, y, s in self.period_options()}
        if (year, semester) not in valid:
            return self.default_period()
        return year, semester

    def period_query(self, year: str, semester: str) -> dict[str, str]:
        return {"academic_year": year, "semester": semester}

    def report_hafalan_summary(self, student_id: int) -> dict[str, Any]:
        latest = self.current_hafalan_status(student_id)
        done = process = not_started = 0
        rows = []
        for surah in self.SURAH_JUZ30:
            row = latest.get(surah)
            if row and row.status == "Sudah Hafal":
                status = "Selesai"
                done += 1
            elif row and row.status == "Sedang Proses":
                status = "Proses"
                process += 1
            else:
                status = "Belum Mulai"
                not_started += 1
            rows.append({"surah": surah, "status": status, "record": row})
        return {
            "done": done,
            "process": process,
            "not_started": not_started,
            "total": len(self.SURAH_JUZ30),
            "percent": round(done / max(1, len(self.SURAH_JUZ30)) * 100, 1),
            "rows": rows,
            "has_data": bool(latest),
        }

    def completeness_sections(self, student, report: PeriodReport) -> dict[str, bool]:
        scores = report.scores()
        subjects = self.class_subjects(student.class_name)
        academic = bool(subjects) and all(scores.get(subject) not in (None, "", 0, "0") for subject in subjects)
        hafalan = self.report_hafalan_summary(student.id)["has_data"]
        attitude = report.attitude()
        attitude_complete = all(attitude.get(key) in {"A", "B", "C", "D"} for key in ATTITUDE_KEYS)
        try:
            absence_data = json.loads(report.absence_json or "{}")
        except (TypeError, ValueError):
            absence_data = {}
        attendance = all(key in absence_data for key in ATTENDANCE_KEYS)
        development = bool((report.development_notes or "").strip())
        return {
            "Nilai Akademik": academic,
            "Hafalan": hafalan,
            "Sikap": attitude_complete,
            "Kehadiran": attendance,
            "Catatan Perkembangan": development,
        }

    def calculate_completeness(self, student, report: PeriodReport) -> int:
        sections = self.completeness_sections(student, report)
        return int(round(sum(1 for value in sections.values() if value) / len(sections) * 100))

    def mark_draft(self, report: PeriodReport) -> None:
        report.status = "Draf"
        report.published_at = None

    def navigation_context(self, student, report: PeriodReport, active: str) -> dict[str, Any]:
        query = self.period_query(report.academic_year, report.semester)
        return {
            "student": student,
            "raport": report,
            "active_tab": active,
            "period_query": query,
            "period_value": self.period_value(report.academic_year, report.semester),
            "completeness_sections": self.completeness_sections(student, report),
            "attitude_options": ATTITUDE_OPTIONS,
        }

    # ------------------------------------------------------------------
    # Main pages
    # ------------------------------------------------------------------
    def eraport(self):
        self.require_staff()
        classes = self.active_class_names()
        year, semester = self.parse_period()
        return render_template(
            "eraport_filter_v10.html",
            classes=classes,
            period_options=self.period_options(),
            selected_period=self.period_value(year, semester),
            selected_status=request.args.get("status", "Semua"),
        )

    def class_dashboard(self):
        self.require_staff()
        class_name = self.normalize_class_name(request.args.get("class_name", ""))
        if class_name not in self.active_class_names():
            flash("Pilih kelas terlebih dahulu.", "warning")
            return redirect(url_for("eraport"))
        year, semester = self.parse_period()
        status_filter = request.args.get("status", "Semua")
        students = (self.Santri.query
                    .filter_by(class_name=class_name, is_active=True)
                    .order_by(self.Santri.name.asc()).all())
        rows = []
        stats = {"total": len(students), "draft": 0, "published": 0}
        for student in students:
            report = self.get_report(student.id, year, semester, create=True)
            report.completeness = self.calculate_completeness(student, report)
            report = self.save_report(report)
            if report.status == "Diterbitkan":
                stats["published"] += 1
            else:
                stats["draft"] += 1
            display_status = "Diterbitkan" if report.status == "Diterbitkan" else "Draft"
            if status_filter == "Draft" and report.status == "Diterbitkan":
                continue
            if status_filter == "Diterbitkan" and report.status != "Diterbitkan":
                continue
            rows.append((student, report, display_status))
        return render_template(
            "eraport_dashboard_v10.html",
            class_name=class_name,
            academic_year=year,
            semester=semester,
            status_filter=status_filter,
            rows=rows,
            stats=stats,
        )

    def report_edit_redirect(self, student_id: int):
        self.require_staff()
        year, semester = self.parse_period()
        return redirect(url_for("eraport_academic", student_id=student_id, academic_year=year, semester=semester))

    def academic(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        subjects = self.class_subjects(student.class_name)
        if request.method == "POST":
            scores: dict[str, int] = {}
            for index, subject in enumerate(subjects):
                raw = request.form.get(f"score_{index}", "").strip()
                if not raw:
                    continue
                try:
                    value = int(raw)
                except ValueError:
                    flash(f"Nilai {subject} tidak valid.", "danger")
                    return redirect(url_for("eraport_academic", student_id=student.id, academic_year=year, semester=semester))
                if not 60 <= value <= 100:
                    flash("Nilai harus berada pada rentang 60–100.", "danger")
                    return redirect(url_for("eraport_academic", student_id=student.id, academic_year=year, semester=semester))
                scores[subject] = value
            report.scores_json = json.dumps(scores, ensure_ascii=False)
            self.mark_draft(report)
            report.completeness = self.calculate_completeness(student, report)
            self.save_report(report)
            flash("Nilai akademik berhasil disimpan.", "success")
            endpoint = "eraport_hafalan" if request.form.get("action") == "save_next" else "eraport_academic"
            return redirect(url_for(endpoint, student_id=student.id, academic_year=year, semester=semester))
        context = self.navigation_context(student, report, "academic")
        context.update({"subjects": subjects, "scores": report.scores()})
        return render_template("eraport_academic_v10.html", **context)

    def hafalan(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        context = self.navigation_context(student, report, "hafalan")
        context.update({"hafalan": self.report_hafalan_summary(student.id)})
        return render_template("eraport_hafalan_v10.html", **context)

    def hafalan_detail(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        summary = self.report_hafalan_summary(student.id)
        selected_surah = request.args.get("surah") or self.SURAH_JUZ30[0]
        selected = next((item for item in summary["rows"] if item["surah"] == selected_surah), summary["rows"][0])
        context = self.navigation_context(student, report, "hafalan")
        context.update({"hafalan": summary, "selected": selected})
        return render_template("eraport_hafalan_detail_v10.html", **context)

    def hafalan_save(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        surah = request.form.get("surah", "")
        status = request.form.get("status", "Belum Mulai")
        if surah not in self.SURAH_JUZ30 or status not in {"Belum Mulai", "Proses", "Selesai"}:
            flash("Data Tracker Hafalan tidak valid.", "danger")
            return redirect(url_for("eraport_hafalan_detail", student_id=student.id, academic_year=year, semester=semester))
        score_raw = request.form.get("score", "").strip()
        score = None
        if score_raw:
            try:
                score = int(score_raw)
            except ValueError:
                score = None
            if score is None or not 60 <= score <= 100:
                flash("Nilai/kelancaran harus berada pada rentang 60–100.", "danger")
                return redirect(url_for("eraport_hafalan_detail", student_id=student.id, academic_year=year, semester=semester, surah=surah))
        today = date.today()
        raw_status = {"Belum Mulai": "Belum Hafal", "Proses": "Sedang Proses", "Selesai": "Sudah Hafal"}[status]
        entry_value = request.form.get("completion_date" if status == "Selesai" else "start_date", "")
        try:
            entry_date = date.fromisoformat(entry_value) if entry_value else today
        except ValueError:
            entry_date = today
        row = self.HafalanRecord(
            santri_id=student.id,
            surah=surah,
            activity_type={"Belum Mulai": "Reset Status", "Proses": "Update Progres", "Selesai": "Tandai Selesai"}[status],
            entry_date=entry_date,
            status=raw_status,
            fluency=score,
            notes=request.form.get("notes", "").strip(),
            created_by=current_user.full_name,
        )
        self.db.session.add(row)
        self.db.session.commit()
        report = self.get_report(student.id, year, semester, create=True)
        self.mark_draft(report)
        report.completeness = self.calculate_completeness(student, report)
        self.save_report(report)
        flash(f"Tracker {surah} berhasil diperbarui.", "success")
        return redirect(url_for("eraport_hafalan_detail", student_id=student.id, academic_year=year, semester=semester, surah=surah))

    def attitude(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        if request.method == "POST":
            attitude = {key: request.form.get(f"attitude_{index}", "") for index, key in enumerate(ATTITUDE_KEYS)}
            for value in attitude.values():
                if value and value not in {"A", "B", "C", "D"}:
                    abort(400)
            absence = {}
            for index, key in enumerate(ATTENDANCE_KEYS):
                count = request.form.get(f"attendance_{index}", type=int)
                absence[key] = {"count": max(0, count or 0)}
            report.attitude_json = json.dumps(attitude, ensure_ascii=False)
            report.absence_json = json.dumps(absence, ensure_ascii=False)
            self.mark_draft(report)
            report.completeness = self.calculate_completeness(student, report)
            self.save_report(report)
            flash("Sikap dan kehadiran berhasil disimpan.", "success")
            endpoint = "eraport_development" if request.form.get("action") == "save_next" else "eraport_attitude"
            return redirect(url_for(endpoint, student_id=student.id, academic_year=year, semester=semester))
        context = self.navigation_context(student, report, "attitude")
        context.update({"attitude": report.attitude(), "absence": report.absence(), "attitude_keys": ATTITUDE_KEYS, "attendance_keys": ATTENDANCE_KEYS})
        return render_template("eraport_attitude_v10.html", **context)

    def development(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        if request.method == "POST":
            report.development_notes = request.form.get("development_notes", "").strip()
            self.mark_draft(report)
            report.completeness = self.calculate_completeness(student, report)
            self.save_report(report)
            flash("Catatan perkembangan berhasil disimpan.", "success")
            endpoint = "eraport_publication" if request.form.get("action") == "save_next" else "eraport_development"
            return redirect(url_for(endpoint, student_id=student.id, academic_year=year, semester=semester))
        context = self.navigation_context(student, report, "development")
        return render_template("eraport_development_v10.html", **context)

    def publication(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        report.completeness = self.calculate_completeness(student, report)
        report = self.save_report(report)
        if request.method == "POST":
            action = request.form.get("action", "draft")
            if action == "publish":
                sections = self.completeness_sections(student, report)
                if not all(sections.values()):
                    flash("Raport belum lengkap. Lengkapi bagian yang masih ditandai.", "danger")
                    return redirect(url_for("eraport_publication", student_id=student.id, academic_year=year, semester=semester))
                report.status = "Diterbitkan"
                report.publish_date = self.jakarta_now().date()
                report.published_at = datetime.utcnow()
                report.completeness = 100
                report.snapshot_json = json.dumps(self.report_data(student, report, include_draft=False), ensure_ascii=False, default=str)
                self.save_report(report)
                flash("Raport berhasil diterbitkan.", "success")
                return redirect(url_for("report_preview", student_id=student.id, academic_year=year, semester=semester))
            self.mark_draft(report)
            self.save_report(report)
            flash("Raport disimpan sebagai Draft.", "success")
            return redirect(url_for("eraport_publication", student_id=student.id, academic_year=year, semester=semester))
        context = self.navigation_context(student, report, "publication")
        return render_template("eraport_publication_v10.html", **context)

    def report_publish(self, student_id: int):
        self.require_staff()
        year, semester = self.parse_period()
        return redirect(url_for("eraport_publication", student_id=student_id, academic_year=year, semester=semester))

    def report_revise(self, student_id: int):
        self.require_staff()
        student = self.db.get_or_404(self.Santri, student_id)
        year, semester = self.parse_period()
        report = self.get_report(student.id, year, semester, create=True)
        report.version += 1
        self.mark_draft(report)
        self.save_report(report)
        flash("Mode revisi dibuka. Raport kembali menjadi Draft.", "info")
        return redirect(url_for("eraport_academic", student_id=student.id, academic_year=year, semester=semester))

    def bulk(self):
        self.require_staff()
        class_name = self.normalize_class_name(request.values.get("class_name", ""))
        if class_name not in self.active_class_names():
            flash("Pilih kelas terlebih dahulu.", "warning")
            return redirect(url_for("eraport"))
        year, semester = self.parse_period()
        students = (self.Santri.query.filter_by(class_name=class_name, is_active=True)
                    .order_by(self.Santri.name.asc()).all())
        subjects = self.class_subjects(class_name)
        if request.method == "POST":
            for student in students:
                report = self.get_report(student.id, year, semester, create=True)
                scores = report.scores()
                for index, subject in enumerate(subjects):
                    raw = request.form.get(f"score_{student.id}_{index}", "").strip()
                    if not raw:
                        continue
                    try:
                        value = int(raw)
                    except ValueError:
                        continue
                    if 60 <= value <= 100:
                        scores[subject] = value
                report.scores_json = json.dumps(scores, ensure_ascii=False)
                self.mark_draft(report)
                report.completeness = self.calculate_completeness(student, report)
                self.save_report(report)
            flash("Nilai satu kelas berhasil disimpan sebagai Draft.", "success")
            return redirect(url_for("eraport_class_dashboard", class_name=class_name, academic_year=year, semester=semester))
        rows = [(student, self.get_report(student.id, year, semester, create=True)) for student in students]
        return render_template("eraport_bulk_v10.html", class_name=class_name, academic_year=year, semester=semester, subjects=subjects, rows=rows)

    # ------------------------------------------------------------------
    # Preview / PDF
    # ------------------------------------------------------------------
    def report_data(self, student, report: PeriodReport, include_draft: bool = True) -> dict[str, Any]:
        hafalan = self.report_hafalan_summary(student.id)
        return {
            "student_name": student.name,
            "nis": student.nis,
            "class_name": student.class_name,
            "semester": report.semester,
            "academic_year": report.academic_year,
            "teacher": self.class_teacher(student.class_name),
            "subjects": self.class_subjects(student.class_name),
            "scores": report.scores(),
            "attitude": report.attitude(),
            "absence": report.absence(),
            "development_notes": report.development_notes or "Belum diisi",
            "hafalan_done": hafalan["done"],
            "hafalan_total": hafalan["total"],
            "hafalan_process": hafalan["process"],
            "kkm": 70,
            "publish_date": report.publish_date or self.jakarta_now().date(),
            "is_draft": include_draft and report.status != "Diterbitkan",
        }

    def preview(self, student_id: int):
        student = self.db.get_or_404(self.Santri, student_id)
        if not self.can_view_student(student):
            abort(403)
        year, semester = self.parse_period()
        if getattr(current_user, "is_admin", False):
            report = self.get_report(student.id, year, semester, create=True)
        else:
            report = self.latest_report(student.id, published_only=True)
            if not report:
                flash("Raport belum diterbitkan.", "info")
                return redirect(url_for("guardian_student_detail", student_id=student.id))
            year, semester = report.academic_year, report.semester
        return render_template(
            "eraport_preview_v10.html",
            student=student,
            raport=report,
            academic_year=year,
            semester=semester,
            is_staff=getattr(current_user, "is_admin", False),
        )

    def image(self, student_id: int):
        student = self.db.get_or_404(self.Santri, student_id)
        if not self.can_view_student(student):
            abort(403)
        year, semester = self.parse_period()
        if getattr(current_user, "is_admin", False):
            report = self.get_report(student.id, year, semester, create=True)
        else:
            report = self.latest_report(student.id, published_only=True)
            if not report:
                abort(404)
        image = self.build_report_png(student, report, include_draft=True)
        response = send_file(image, mimetype="image/png", download_name=f"preview_raport_{student.id}.png")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    def pdf(self, student_id: int):
        student = self.db.get_or_404(self.Santri, student_id)
        if not self.can_view_student(student):
            abort(403)
        year, semester = self.parse_period()
        if getattr(current_user, "is_admin", False):
            report = self.get_report(student.id, year, semester, create=True)
        else:
            report = self.latest_report(student.id, published_only=True)
        if not report or report.status != "Diterbitkan":
            flash("Raport harus diterbitkan terlebih dahulu sebelum diunduh.", "warning")
            return redirect(url_for("report_preview", student_id=student.id, academic_year=year, semester=semester))
        pdf = self.build_report_pdf(student, report)
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", student.name).strip("_") or f"santri_{student.id}"
        return send_file(pdf, mimetype="application/pdf", as_attachment=True,
                         download_name=f"Raport_Santri_{safe_name}_{report.academic_year.replace('/', '-')}_{report.semester.replace(' ', '_')}.pdf")

    def guardian_report(self, student_id: int):
        student = self.db.get_or_404(self.Santri, student_id)
        if not self.can_view_student(student):
            abort(403)
        if getattr(current_user, "is_admin", False):
            return redirect(url_for("report_preview", student_id=student.id))
        report = self.latest_report(student.id, published_only=True)
        if not report:
            flash("Raport belum diterbitkan.", "info")
            return redirect(url_for("guardian_student_detail", student_id=student.id))
        return redirect(url_for("report_preview", student_id=student.id,
                                academic_year=report.academic_year, semester=report.semester))

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _font(self, size: int, bold: bool = False):
        from PIL import ImageFont
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
        for path in candidates:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    @staticmethod
    def _wrap(draw, text_value: Any, font, max_width: int) -> list[str]:
        text_value = str(text_value or "Belum diisi").strip() or "Belum diisi"
        words = text_value.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or ["Belum diisi"]

    def build_report_png(self, student, report: PeriodReport, include_draft: bool = True):
        from PIL import Image, ImageDraw

        W, H = 1240, 1754
        image = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(image)
        green = "#0B6B4D"
        dark = "#1F2937"
        muted = "#64748B"
        border = "#D8E1DC"
        pale = "#F5F9F7"
        gold = "#E8B13D"
        margin = 72

        data = self.report_data(student, report, include_draft=include_draft)
        if data["is_draft"]:
            overlay = Image.new("RGBA", (W, H), (255, 255, 255, 0))
            od = ImageDraw.Draw(overlay)
            od.text((W // 2, H // 2), "DRAFT", font=self._font(120, True), fill=(180, 40, 30, 40), anchor="mm", stroke_width=1)
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(image)

        # Kop kecil, proporsional, rata tengah.
        kop_path = os.path.join(self.app.root_path, "static", "img", "kop_surat_tpq_hmarisa.png")
        y = 38
        if os.path.exists(kop_path):
            kop = Image.open(kop_path).convert("RGBA")
            target_h = 118  # ±20 mm pada 150 dpi
            target_w = int(kop.width * target_h / kop.height)
            max_w = int((W - 2 * margin) * 0.80)
            if target_w > max_w:
                target_w = max_w
                target_h = int(kop.height * target_w / kop.width)
            kop = kop.resize((target_w, target_h), Image.LANCZOS)
            image.paste(kop, ((W - target_w) // 2, y), kop)
            y += target_h + 38

        title_font = self._font(35, True)
        draw.text((W // 2, y), "RAPORT SANTRI", font=title_font, fill=dark, anchor="ma")
        y += 50
        sub_font = self._font(20, False)
        draw.text((W // 2, y), f"Tahun Ajaran {report.academic_year} — {report.semester}", font=sub_font, fill=muted, anchor="ma")
        y += 38

        # Identitas
        box_x1, box_x2 = margin, W - margin
        identity_h = 145
        draw.rounded_rectangle((box_x1, y, box_x2, y + identity_h), radius=18, fill=pale, outline=border, width=2)
        label_font = self._font(17, True)
        value_font = self._font(18, False)
        identity = [
            ("Nama Santri", student.name, margin + 24, y + 25),
            ("NIS", student.nis, margin + 24, y + 78),
            ("Kelas", student.class_name, W // 2 + 10, y + 25),
            ("Wali Kelas", self.class_teacher(student.class_name), W // 2 + 10, y + 78),
        ]
        for label, value, x, yy in identity:
            draw.text((x, yy), label, font=label_font, fill=green)
            draw.text((x + 155, yy), str(value or "Belum diisi"), font=value_font, fill=dark)
        y += identity_h + 24

        # Nilai akademik
        section_font = self._font(23, True)
        draw.text((margin, y), "NILAI AKADEMIK", font=section_font, fill=green)
        y += 40
        subjects = data["subjects"]
        scores = data["scores"]
        cols = [50, 510, 120, 120, 300]
        headers = ["No.", "Mata Pelajaran", "Nilai", "Predikat", "Keterangan"]
        table_x = margin
        row_h = 52
        x = table_x
        for width, header in zip(cols, headers):
            draw.rectangle((x, y, x + width, y + row_h), fill=green, outline="white", width=1)
            draw.text((x + width // 2, y + row_h // 2), header, font=self._font(16, True), fill="white", anchor="mm")
            x += width
        y += row_h
        for idx, subject in enumerate(subjects, 1):
            raw = scores.get(subject)
            pred, note, _ = self.score_predicate(raw)
            values = [idx, subject, raw if raw not in (None, "", 0, "0") else "Belum diisi", pred or "Belum diisi", note]
            x = table_x
            fill = "#FFFFFF" if idx % 2 else "#F8FAF9"
            for col_i, (width, value) in enumerate(zip(cols, values)):
                draw.rectangle((x, y, x + width, y + row_h), fill=fill, outline=border, width=1)
                font = self._font(16, col_i == 1)
                if col_i == 1:
                    lines = self._wrap(draw, value, font, width - 20)[:2]
                    line_y = y + 10 if len(lines) > 1 else y + row_h // 2
                    for li, line in enumerate(lines):
                        draw.text((x + 10, line_y + li * 20), line, font=font, fill=dark, anchor="lm" if len(lines) == 1 else None)
                else:
                    draw.text((x + width // 2, y + row_h // 2), str(value), font=font, fill=dark, anchor="mm")
                x += width
            y += row_h
        y += 22

        # Hafalan
        draw.rounded_rectangle((margin, y, W - margin, y + 116), radius=16, fill=pale, outline=border, width=2)
        draw.text((margin + 22, y + 22), "PROGRES HAFALAN JUZ 30", font=self._font(20, True), fill=green)
        draw.text((W - margin - 22, y + 22), f"{data['hafalan_done']}/{data['hafalan_total']} surat", font=self._font(20, True), fill=dark, anchor="ra")
        bar_x1, bar_x2, bar_y = margin + 22, W - margin - 22, y + 70
        draw.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + 18), radius=9, fill="#E2E8F0")
        filled = int((bar_x2 - bar_x1) * data["hafalan_done"] / max(1, data["hafalan_total"]))
        if filled:
            draw.rounded_rectangle((bar_x1, bar_y, bar_x1 + filled, bar_y + 18), radius=9, fill=green)
        y += 138

        # Sikap dan Kehadiran dua kolom
        gap = 22
        left_x1, left_x2 = margin, W // 2 - gap // 2
        right_x1, right_x2 = W // 2 + gap // 2, W - margin
        block_h = 270
        for x1, x2, title in ((left_x1, left_x2, "PENILAIAN SIKAP"), (right_x1, right_x2, "KEHADIRAN")):
            draw.rounded_rectangle((x1, y, x2, y + block_h), radius=16, fill="white", outline=border, width=2)
            draw.text((x1 + 18, y + 18), title, font=self._font(20, True), fill=green)
        labels = dict(ATTITUDE_OPTIONS)
        attitude = data["attitude"]
        yy = y + 62
        for key in ATTITUDE_KEYS:
            val = attitude.get(key, "")
            display = f"{val} — {labels.get(val, 'Belum diisi')}" if val else "Belum diisi"
            draw.text((left_x1 + 18, yy), key, font=self._font(15, True), fill=dark)
            draw.text((left_x1 + 235, yy), display, font=self._font(15), fill=dark)
            yy += 48
        absence = data["absence"]
        yy = y + 68
        draw.text((right_x1 + 18, yy), "Keterangan", font=self._font(15, True), fill=muted)
        draw.text((right_x2 - 28, yy), "Jumlah", font=self._font(15, True), fill=muted, anchor="ra")
        yy += 42
        for key in ATTENDANCE_KEYS:
            item = absence.get(key, {})
            count = item.get("count", 0) if isinstance(item, dict) else item
            draw.text((right_x1 + 18, yy), key, font=self._font(17), fill=dark)
            draw.text((right_x2 - 28, yy), str(count if count is not None else "Belum diisi"), font=self._font(17, True), fill=dark, anchor="ra")
            yy += 55
        y += block_h + 22

        # Catatan perkembangan
        note_h = 205
        draw.rounded_rectangle((margin, y, W - margin, y + note_h), radius=16, fill="white", outline=border, width=2)
        draw.text((margin + 18, y + 18), "CATATAN PERKEMBANGAN", font=self._font(20, True), fill=green)
        note_font = self._font(17)
        lines = self._wrap(draw, data["development_notes"], note_font, W - 2 * margin - 40)
        max_lines = 6
        for index, line in enumerate(lines[:max_lines]):
            draw.text((margin + 20, y + 60 + index * 25), line, font=note_font, fill=dark)
        if len(lines) > max_lines:
            draw.text((W - margin - 22, y + note_h - 28), "…", font=self._font(22, True), fill=muted, anchor="ra")
        y += note_h + 26

        # KKM dan lokasi/tanggal, tanpa tanda tangan.
        draw.text((margin, y), "KKM: 70", font=self._font(18, True), fill=green)
        location = f"Tangerang Selatan, {data['publish_date'].strftime('%d-%m-%Y')}"
        draw.text((W - margin, y), location, font=self._font(17), fill=muted, anchor="ra")
        y += 38
        draw.line((margin, y, W - margin, y), fill=gold, width=3)

        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        out.seek(0)
        return out

    def build_report_pdf(self, student, report: PeriodReport):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        png = self.build_report_png(student, report, include_draft=False)
        out = io.BytesIO()
        width, height = A4
        pdf = canvas.Canvas(out, pagesize=A4, pageCompression=1)
        pdf.setTitle(f"Raport Santri {student.name}")
        pdf.drawImage(ImageReader(png), 0, 0, width=width, height=height,
                      preserveAspectRatio=False, mask="auto")
        pdf.showPage()
        pdf.save()
        out.seek(0)
        return out

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def install(self) -> None:
        # Ganti endpoint lama tanpa menambah route duplikat.
        replacements = {
            "eraport": self.eraport,
            "eraport_bulk": self.bulk,
            "report_edit": self.report_edit_redirect,
            "report_publish": self.report_publish,
            "report_revise": self.report_revise,
            "report_preview": self.preview,
            "report_image": self.image,
            "report_pdf": self.pdf,
            "guardian_report": self.guardian_report,
        }
        for endpoint, function in replacements.items():
            if endpoint in self.app.view_functions:
                self.app.view_functions[endpoint] = function

        routes = [
            ("/eraport/class-dashboard", "eraport_class_dashboard", self.class_dashboard, ["GET"]),
            ("/eraport/<int:student_id>/academic", "eraport_academic", self.academic, ["GET", "POST"]),
            ("/eraport/<int:student_id>/hafalan", "eraport_hafalan", self.hafalan, ["GET"]),
            ("/eraport/<int:student_id>/hafalan/detail", "eraport_hafalan_detail", self.hafalan_detail, ["GET"]),
            ("/eraport/<int:student_id>/hafalan/save", "eraport_hafalan_save", self.hafalan_save, ["POST"]),
            ("/eraport/<int:student_id>/attitude", "eraport_attitude", self.attitude, ["GET", "POST"]),
            ("/eraport/<int:student_id>/development", "eraport_development", self.development, ["GET", "POST"]),
            ("/eraport/<int:student_id>/publication", "eraport_publication", self.publication, ["GET", "POST"]),
        ]
        for rule, endpoint, view_func, methods in routes:
            if endpoint not in self.app.view_functions:
                self.app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=methods)

        with self.app.app_context():
            self.ensure_storage()


def install_eraport_v10(app, db, namespace: dict[str, Any]):
    service = EraportV10(app, db, namespace)
    service.install()
    app.extensions["eraport_v10"] = service
    return service
