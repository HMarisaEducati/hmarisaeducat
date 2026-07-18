"""Keuangan V15-B: kerangka terpadu, ringkasan, tagihan, dan administrasi iuran.

Modul dipasang setelah V15-A. Ia tidak menghapus tabel Iuran lama. Data lama
hanya dibaca dan dimigrasikan ke tabel baru secara idempoten.
"""
from __future__ import annotations

import calendar
import json
import re
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint, func


VALID_STATUSES = {"Belum Lunas", "Sebagian", "Lunas", "Dibebaskan"}
PAGE_SIZES = {25, 50, 100}
MONTH_NUMBERS = {
    "Januari": 1, "Februari": 2, "Maret": 3, "April": 4,
    "Mei": 5, "Juni": 6, "Juli": 7, "Agustus": 8,
    "September": 9, "Oktober": 10, "November": 11, "Desember": 12,
}


def install_finance_v15b(app, db, namespace: dict[str, Any]):
    """Daftarkan model dan route V15-B tanpa menyentuh modul portal lain."""
    if app.extensions.get("finance_v15b"):
        return app.extensions["finance_v15b"]

    v15a = app.extensions.get("finance_v15a")
    if not v15a:
        raise RuntimeError("Keuangan V15-A harus terpasang sebelum V15-B.")

    Santri = namespace["Santri"]
    Iuran = namespace["Iuran"]
    admin_required = namespace["admin_required"]
    CLASSES = namespace.get("CLASSES", [])
    MONTHS = namespace.get("MONTHS", list(MONTH_NUMBERS))

    settings_models = v15a["models"]
    GeneralSetting = settings_models["general"]
    BillingSetting = settings_models["billing"]
    ChargeType = settings_models["charge_type"]
    AuditLog = settings_models["audit"]

    class FinanceBill(db.Model):
        __tablename__ = "finance_bill"
        id = db.Column(db.Integer, primary_key=True)
        bill_number = db.Column(db.String(30), nullable=False, unique=True, index=True)
        legacy_iuran_id = db.Column(db.Integer, unique=True, index=True)
        santri_id = db.Column(db.Integer, db.ForeignKey("santri.id"), nullable=False, index=True)
        academic_year = db.Column(db.String(20), nullable=False, index=True)
        semester = db.Column(db.String(20), nullable=False, index=True)
        charge_type_id = db.Column(db.Integer, db.ForeignKey("finance_charge_type.id"), nullable=False, index=True)
        period_label = db.Column(db.String(80), nullable=False, index=True)
        period_month = db.Column(db.Integer)
        period_year = db.Column(db.Integer, nullable=False, index=True)
        amount = db.Column(db.Integer, nullable=False, default=0)
        paid_amount = db.Column(db.Integer, nullable=False, default=0)
        status = db.Column(db.String(30), nullable=False, default="Belum Lunas", index=True)
        due_date = db.Column(db.Date)
        notes = db.Column(db.Text, nullable=False, default="")
        waiver_reason = db.Column(db.Text, nullable=False, default="")
        canonical_key = db.Column(db.String(255), nullable=False, index=True)
        active_dedupe_key = db.Column(db.String(255), unique=True, index=True)
        is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
        archived_at = db.Column(db.DateTime)
        archived_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        archive_reason = db.Column(db.Text, nullable=False, default="")
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        version = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        @property
        def remaining_amount(self):
            return max(0, int(self.amount or 0) - int(self.paid_amount or 0))

    class FinanceDocumentSequence(db.Model):
        __tablename__ = "finance_document_sequence"
        id = db.Column(db.Integer, primary_key=True)
        document_type = db.Column(db.String(30), nullable=False)
        year = db.Column(db.Integer, nullable=False)
        last_number = db.Column(db.Integer, nullable=False, default=0)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        __table_args__ = (
            UniqueConstraint("document_type", "year", name="uq_finance_document_sequence"),
        )

    def _finance_admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_admin or current_user.is_teacher or not getattr(current_user, "is_active", True):
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def _int(value: Any, field: str, minimum: int = 0, maximum: int | None = None) -> int:
        try:
            result = int(str(value).replace(".", "").replace(",", "").strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} harus berupa angka.") from exc
        if result < minimum or (maximum is not None and result > maximum):
            raise ValueError(f"{field} tidak valid.")
        return result

    def _clean(value: Any, limit: int = 255) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())[:limit]

    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "periode"

    def _format_wib(value: datetime | None) -> str:
        if value is None:
            return "Belum diisi"
        return (value + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M WIB")

    def _request_ip() -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",", 1)[0].strip() if forwarded else request.remote_addr or "")[:80]

    def _record_audit(action: str, entity_type: str, entity_id: Any, before: dict, after: dict) -> None:
        db.session.add(AuditLog(
            user_id=getattr(current_user, "id", None),
            user_name=getattr(current_user, "full_name", "Sistem") or "Sistem",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id or ""),
            before_json=json.dumps(before or {}, ensure_ascii=False, default=str),
            after_json=json.dumps(after or {}, ensure_ascii=False, default=str),
            ip_address=_request_ip(),
            user_agent=(request.headers.get("User-Agent", "") or "")[:500],
            request_id=uuid.uuid4().hex,
        ))

    def _bill_dict(row: FinanceBill) -> dict[str, Any]:
        return {
            "bill_number": row.bill_number,
            "santri_id": row.santri_id,
            "academic_year": row.academic_year,
            "semester": row.semester,
            "charge_type_id": row.charge_type_id,
            "period_label": row.period_label,
            "period_year": row.period_year,
            "amount": row.amount,
            "paid_amount": row.paid_amount,
            "status": row.status,
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "notes": row.notes,
            "is_archived": row.is_archived,
        }

    def _active_settings():
        general, billing, _, _ = v15a["ensure_defaults"]()
        return general, billing

    def _canonical_key(student_id: int, charge_type_id: int, academic_year: str,
                       semester: str, period_label: str, period_year: int) -> str:
        return "|".join([
            str(student_id), str(charge_type_id), academic_year.strip().lower(),
            semester.strip().lower(), str(period_year), _slug(period_label),
        ])

    def _due_date(period_label: str, period_year: int, due_day: int) -> date | None:
        month = MONTH_NUMBERS.get(period_label)
        if not month:
            return None
        last_day = calendar.monthrange(period_year, month)[1]
        return date(period_year, month, min(max(1, due_day), last_day))

    def _next_number(year: int) -> str:
        sequence = FinanceDocumentSequence.query.filter_by(document_type="TAG", year=year).first()
        if sequence is None:
            sequence = FinanceDocumentSequence(document_type="TAG", year=year, last_number=0)
            db.session.add(sequence)
            db.session.flush()
        sequence.last_number += 1
        db.session.flush()
        return f"TAG-{year}-{sequence.last_number:06d}"

    def _derive_status(amount: int, paid: int, waived: bool = False) -> str:
        if waived:
            return "Dibebaskan"
        if paid <= 0:
            return "Belum Lunas"
        if paid < amount:
            return "Sebagian"
        return "Lunas"

    def migrate_legacy() -> dict[str, int]:
        """Salin Iuran lama ke FinanceBill sekali saja; tabel lama tidak diubah."""
        v15a["ensure_defaults"]()
        general, billing = _active_settings()
        spp = ChargeType.query.filter_by(slug="spp").first()
        if spp is None:
            spp = ChargeType(name="SPP", slug="spp", default_amount=50000, sort_order=1, is_active=True)
            db.session.add(spp)
            db.session.flush()

        created = 0
        skipped = 0
        legacy_rows = Iuran.query.order_by(Iuran.id).all()
        for legacy in legacy_rows:
            if FinanceBill.query.filter_by(legacy_iuran_id=legacy.id).first():
                skipped += 1
                continue
            period_label = legacy.month
            period_year = int(legacy.year)
            key = _canonical_key(
                legacy.santri_id, spp.id, general.academic_year_active,
                general.semester_active, period_label, period_year,
            )
            duplicate = FinanceBill.query.filter_by(active_dedupe_key=key).first()
            if duplicate:
                # Hubungkan data lama ke tagihan aktif yang sudah tersedia tanpa membuat duplikat.
                if duplicate.legacy_iuran_id is None:
                    duplicate.legacy_iuran_id = legacy.id
                skipped += 1
                continue
            old_status = (legacy.status or "Belum Lunas").strip()
            paid = int(legacy.nominal or 0) if old_status == "Lunas" else 0
            status = _derive_status(int(legacy.nominal or 0), paid)
            notes = ""
            if old_status not in {"Belum Lunas", "Lunas"}:
                notes = f"Migrasi dari status lama: {old_status}."
            row = FinanceBill(
                bill_number=_next_number(period_year),
                legacy_iuran_id=legacy.id,
                santri_id=legacy.santri_id,
                academic_year=general.academic_year_active,
                semester=general.semester_active,
                charge_type_id=spp.id,
                period_label=period_label,
                period_month=MONTH_NUMBERS.get(period_label),
                period_year=period_year,
                amount=int(legacy.nominal or 0),
                paid_amount=paid,
                status=status,
                due_date=_due_date(period_label, period_year, spp.due_day or billing.default_due_day),
                notes=notes,
                canonical_key=key,
                active_dedupe_key=key,
                created_at=legacy.created_at or datetime.utcnow(),
                updated_at=legacy.verified_at or legacy.created_at or datetime.utcnow(),
            )
            db.session.add(row)
            created += 1
        db.session.commit()
        return {"created": created, "skipped": skipped, "legacy": len(legacy_rows)}

    def _student_map(ids: list[int] | set[int]) -> dict[int, Any]:
        if not ids:
            return {}
        return {row.id: row for row in Santri.query.filter(Santri.id.in_(list(ids))).all()}

    def _charge_map(ids: list[int] | set[int]) -> dict[int, Any]:
        if not ids:
            return {}
        return {row.id: row for row in ChargeType.query.filter(ChargeType.id.in_(list(ids))).all()}

    def _attach(rows: list[FinanceBill]) -> tuple[dict[int, Any], dict[int, Any]]:
        return _student_map({r.santri_id for r in rows}), _charge_map({r.charge_type_id for r in rows})

    def _select_students() -> list[Any]:
        class_name = _clean(request.form.get("class_name"), 60)
        whole_class = request.form.get("whole_class") in {"1", "on", "true"}
        selected_ids = []
        for raw in request.form.getlist("student_ids"):
            try:
                selected_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        query = Santri.query.filter_by(is_active=True)
        if class_name:
            if class_name not in CLASSES:
                raise ValueError("Kelas tidak valid.")
            query = query.filter_by(class_name=class_name)
        if whole_class:
            rows = query.order_by(Santri.name).all()
        else:
            if not selected_ids:
                raise ValueError("Pilih minimal satu santri atau centang seluruh santri dalam kelas.")
            rows = query.filter(Santri.id.in_(selected_ids)).order_by(Santri.name).all()
            if len(rows) != len(set(selected_ids)):
                raise ValueError("Sebagian data santri tidak ditemukan atau tidak sesuai kelas.")
        if not rows:
            raise ValueError("Tidak ada santri aktif yang dipilih.")
        return rows

    def _form_payload() -> dict[str, Any]:
        general, billing = _active_settings()
        charge_type_id = _int(request.form.get("charge_type_id"), "Jenis tagihan", 1)
        charge_type = db.session.get(ChargeType, charge_type_id)
        if not charge_type or not charge_type.is_active:
            raise ValueError("Jenis tagihan tidak tersedia atau tidak aktif.")
        academic_year = _clean(request.form.get("academic_year") or general.academic_year_active, 20)
        semester = _clean(request.form.get("semester") or general.semester_active, 20)
        if not re.fullmatch(r"\d{4}/\d{4}", academic_year):
            raise ValueError("Tahun ajaran tidak valid.")
        if semester not in {"Semester 1", "Semester 2"}:
            raise ValueError("Semester tidak valid.")
        period_label = _clean(request.form.get("period_label"), 80)
        if not period_label:
            raise ValueError("Periode/Bulan wajib diisi.")
        period_year = _int(request.form.get("period_year"), "Tahun", 2020, 2100)
        amount = _int(request.form.get("amount"), "Nominal", 0, 2_000_000_000)
        due_raw = _clean(request.form.get("due_date"), 20)
        if due_raw:
            try:
                due = date.fromisoformat(due_raw)
            except ValueError as exc:
                raise ValueError("Jatuh tempo tidak valid.") from exc
        else:
            due = _due_date(period_label, period_year, charge_type.due_day or billing.default_due_day)
        return {
            "charge_type": charge_type,
            "academic_year": academic_year,
            "semester": semester,
            "period_label": period_label,
            "period_year": period_year,
            "amount": amount,
            "due_date": due,
            "notes": _clean(request.form.get("notes"), 2000),
        }

    def _bill_form_context(preview: dict | None = None):
        general, billing = _active_settings()
        students = Santri.query.filter_by(is_active=True).order_by(Santri.class_name, Santri.name).all()
        charge_types = ChargeType.query.filter_by(is_active=True).order_by(ChargeType.sort_order, ChargeType.name).all()
        return {
            "active_tab": "create",
            "general": general,
            "billing": billing,
            "students": students,
            "classes": CLASSES,
            "months": MONTHS,
            "charge_types": charge_types,
            "preview": preview,
            "form_data": request.form,
        }

    @app.route("/finance")
    @_finance_admin_required
    def finance():
        return redirect(url_for("finance_summary"))

    @app.route("/finance/summary")
    @_finance_admin_required
    def finance_summary():
        general, _ = _active_settings()
        active = FinanceBill.query.filter_by(is_archived=False)
        total_students = Santri.query.filter_by(is_active=True).count()
        now_wib = datetime.utcnow() + timedelta(hours=7)
        current_month = next((name for name, number in MONTH_NUMBERS.items() if number == now_wib.month), str(now_wib.month))
        active_period = active.filter_by(
            academic_year=general.academic_year_active,
            semester=general.semester_active,
            period_label=current_month,
            period_year=now_wib.year,
        )
        statuses = dict(
            db.session.query(FinanceBill.status, func.count(FinanceBill.id))
            .filter(
                FinanceBill.is_archived.is_(False),
                FinanceBill.academic_year == general.academic_year_active,
                FinanceBill.semester == general.semester_active,
                FinanceBill.period_label == current_month,
                FinanceBill.period_year == now_wib.year,
            )
            .group_by(FinanceBill.status).all()
        )
        active_total = active_period.count()
        active_paid = active_period.filter(FinanceBill.status.in_(["Lunas", "Dibebaskan"])).count()
        percent = round((active_paid / active_total) * 100) if active_total else 0

        class_rows = []
        for class_name in CLASSES:
            students_count = Santri.query.filter_by(class_name=class_name, is_active=True).count()
            student_ids = [r[0] for r in db.session.query(Santri.id).filter_by(class_name=class_name, is_active=True).all()]
            counts = {status: 0 for status in VALID_STATUSES}
            if student_ids:
                counts.update(dict(
                    db.session.query(FinanceBill.status, func.count(FinanceBill.id))
                    .filter(
                        FinanceBill.is_archived.is_(False), FinanceBill.santri_id.in_(student_ids),
                        FinanceBill.academic_year == general.academic_year_active,
                        FinanceBill.semester == general.semester_active,
                        FinanceBill.period_label == current_month,
                        FinanceBill.period_year == now_wib.year,
                    )
                    .group_by(FinanceBill.status).all()
                ))
            class_rows.append({"class_name": class_name, "students": students_count, **counts})

        latest = active.filter(FinanceBill.status == "Lunas")\
            .order_by(FinanceBill.updated_at.desc(), FinanceBill.id.desc()).limit(5).all()
        unpaid = active_period.filter(FinanceBill.status.in_(["Belum Lunas", "Sebagian"]))\
            .order_by(FinanceBill.due_date.asc(), FinanceBill.id.desc()).limit(8).all()
        student_map, charge_map = _attach(list({row.id: row for row in latest + unpaid}.values()))
        return render_template(
            "finance_v15b/summary.html", active_tab="summary", total_students=total_students,
            statuses=statuses, percent=percent, active_total=active_total,
            class_rows=class_rows, latest=latest, unpaid=unpaid,
            student_map=student_map, charge_map=charge_map, general=general, current_month=current_month, current_year=now_wib.year,
        )

    @app.route("/finance/bills/new", methods=["GET", "POST"])
    @_finance_admin_required
    def finance_bill_new():
        if request.method == "POST":
            action = request.form.get("action", "preview")
            try:
                students = _select_students()
                payload = _form_payload()
                candidates = []
                duplicates = []
                for student in students:
                    key = _canonical_key(
                        student.id, payload["charge_type"].id, payload["academic_year"],
                        payload["semester"], payload["period_label"], payload["period_year"],
                    )
                    existing = FinanceBill.query.filter_by(active_dedupe_key=key).first()
                    target = {
                        "student": student,
                        "key": key,
                        "existing": existing,
                    }
                    (duplicates if existing else candidates).append(target)

                if action == "preview":
                    preview = {
                        "payload": payload,
                        "candidates": candidates,
                        "duplicates": duplicates,
                        "all_students": students,
                    }
                    return render_template("finance_v15b/bill_form.html", **_bill_form_context(preview))

                if action != "create":
                    abort(400)
                if not candidates:
                    raise ValueError("Semua tagihan terdeteksi duplikat. Tidak ada data baru yang dibuat.")

                created = []
                for item in candidates:
                    student = item["student"]
                    row = FinanceBill(
                        bill_number=_next_number(payload["period_year"]),
                        santri_id=student.id,
                        academic_year=payload["academic_year"],
                        semester=payload["semester"],
                        charge_type_id=payload["charge_type"].id,
                        period_label=payload["period_label"],
                        period_month=MONTH_NUMBERS.get(payload["period_label"]),
                        period_year=payload["period_year"],
                        amount=payload["amount"], paid_amount=0, status="Belum Lunas",
                        due_date=payload["due_date"], notes=payload["notes"],
                        canonical_key=item["key"], active_dedupe_key=item["key"],
                        created_by=current_user.id, updated_by=current_user.id,
                    )
                    db.session.add(row)
                    db.session.flush()
                    _record_audit("Membuat tagihan", "finance_bill", row.id, {}, _bill_dict(row))
                    created.append(row)
                db.session.commit()
                skipped = len(duplicates)
                message = f"{len(created)} tagihan berhasil dibuat."
                if skipped:
                    message += f" {skipped} duplikat dilewati."
                flash(message, "success")
                return redirect(url_for("finance_administration"))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("finance_v15b/bill_form.html", **_bill_form_context())

    @app.route("/finance/administration")
    @_finance_admin_required
    def finance_administration():
        q = _clean(request.args.get("q"), 140)
        class_name = _clean(request.args.get("class_name"), 60)
        charge_type_id = request.args.get("charge_type_id", "").strip()
        period = _clean(request.args.get("period"), 80)
        status = _clean(request.args.get("status"), 30)
        academic_year = _clean(request.args.get("academic_year"), 20)
        semester = _clean(request.args.get("semester"), 20)
        sort = request.args.get("sort", "newest")
        page = max(1, _int(request.args.get("page", 1), "Halaman", 1))
        per_page = _int(request.args.get("per_page", 25), "Jumlah per halaman", 1, 100)
        if per_page not in PAGE_SIZES:
            per_page = 25

        query = FinanceBill.query.join(Santri, FinanceBill.santri_id == Santri.id).filter(FinanceBill.is_archived.is_(False))
        if q:
            query = query.filter(Santri.name.ilike(f"%{q}%"))
        if class_name in CLASSES:
            query = query.filter(Santri.class_name == class_name)
        if charge_type_id.isdigit():
            query = query.filter(FinanceBill.charge_type_id == int(charge_type_id))
        if period:
            query = query.filter(FinanceBill.period_label == period)
        if status in VALID_STATUSES:
            query = query.filter(FinanceBill.status == status)
        if academic_year:
            query = query.filter(FinanceBill.academic_year == academic_year)
        if semester in {"Semester 1", "Semester 2"}:
            query = query.filter(FinanceBill.semester == semester)

        ordering = {
            "name": (Santri.name.asc(), FinanceBill.id.desc()),
            "class": (Santri.class_name.asc(), Santri.name.asc()),
            "status": (FinanceBill.status.asc(), Santri.name.asc()),
            "amount": (FinanceBill.amount.desc(), Santri.name.asc()),
            "period": (FinanceBill.period_year.desc(), FinanceBill.period_month.desc(), Santri.name.asc()),
            "oldest": (FinanceBill.created_at.asc(), FinanceBill.id.asc()),
            "newest": (FinanceBill.created_at.desc(), FinanceBill.id.desc()),
        }
        query = query.order_by(*ordering.get(sort, ordering["newest"]))
        total = query.count()
        max_page = max(1, (total + per_page - 1) // per_page)
        page = min(page, max_page)
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
        student_map, charge_map = _attach(rows)
        general, _ = _active_settings()
        charge_types = ChargeType.query.order_by(ChargeType.sort_order, ChargeType.name).all()
        academic_years = [r[0] for r in db.session.query(FinanceBill.academic_year).distinct().order_by(FinanceBill.academic_year.desc()).all()]
        if general.academic_year_active not in academic_years:
            academic_years.insert(0, general.academic_year_active)
        return render_template(
            "finance_v15b/administration.html", active_tab="administration", rows=rows,
            student_map=student_map, charge_map=charge_map, classes=CLASSES,
            months=MONTHS, statuses=sorted(VALID_STATUSES), charge_types=charge_types,
            total=total, page=page, max_page=max_page, per_page=per_page,
            academic_years=academic_years, filters={
                "q": q, "class_name": class_name, "charge_type_id": charge_type_id,
                "period": period, "status": status, "academic_year": academic_year,
                "semester": semester, "sort": sort,
            },
        )

    @app.route("/finance/bills/<int:bill_id>")
    @_finance_admin_required
    def finance_bill_detail(bill_id):
        row = db.get_or_404(FinanceBill, bill_id)
        student = db.session.get(Santri, row.santri_id)
        charge_type = db.session.get(ChargeType, row.charge_type_id)
        audit_logs = AuditLog.query.filter_by(entity_type="finance_bill", entity_id=str(row.id))\
            .order_by(AuditLog.created_at.desc()).limit(30).all()
        return render_template(
            "finance_v15b/bill_detail.html", active_tab="administration", bill=row,
            student=student, charge_type=charge_type, audit_logs=audit_logs, format_wib=_format_wib,
        )

    @app.route("/finance/bills/<int:bill_id>/edit", methods=["GET", "POST"])
    @_finance_admin_required
    def finance_bill_edit(bill_id):
        row = db.get_or_404(FinanceBill, bill_id)
        if row.is_archived:
            flash("Tagihan berada di arsip. Restore terlebih dahulu sebelum mengedit.", "warning")
            return redirect(url_for("finance_bill_detail", bill_id=row.id))
        if request.method == "POST":
            before = _bill_dict(row)
            try:
                amount = _int(request.form.get("amount"), "Nominal", 0, 2_000_000_000)
                if amount < row.paid_amount:
                    raise ValueError("Nominal tagihan tidak boleh lebih kecil dari jumlah yang sudah dibayar.")
                status_choice = _clean(request.form.get("status"), 30)
                waiver_reason = _clean(request.form.get("waiver_reason"), 2000)
                if status_choice == "Dibebaskan":
                    if not waiver_reason:
                        raise ValueError("Alasan pembebasan wajib diisi.")
                    row.status = "Dibebaskan"
                    row.waiver_reason = waiver_reason
                else:
                    row.status = _derive_status(amount, row.paid_amount)
                    row.waiver_reason = ""
                due_raw = _clean(request.form.get("due_date"), 20)
                row.due_date = date.fromisoformat(due_raw) if due_raw else None
                row.amount = amount
                row.notes = _clean(request.form.get("notes"), 2000)
                row.updated_by = current_user.id
                row.version += 1
                _record_audit("Mengubah tagihan", "finance_bill", row.id, before, _bill_dict(row))
                db.session.commit()
                flash("Tagihan berhasil diperbarui.", "success")
                return redirect(url_for("finance_bill_detail", bill_id=row.id))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        student = db.session.get(Santri, row.santri_id)
        charge_type = db.session.get(ChargeType, row.charge_type_id)
        return render_template(
            "finance_v15b/bill_edit.html", active_tab="administration", bill=row,
            student=student, charge_type=charge_type,
        )

    @app.route("/finance/bills/<int:bill_id>/archive", methods=["POST"])
    @_finance_admin_required
    def finance_bill_archive(bill_id):
        row = db.get_or_404(FinanceBill, bill_id)
        if row.is_archived:
            flash("Tagihan sudah berada di arsip.", "info")
            return redirect(url_for("finance_archive"))
        reason = _clean(request.form.get("reason"), 1000)
        if not reason:
            flash("Alasan arsip wajib diisi.", "danger")
            return redirect(url_for("finance_bill_detail", bill_id=row.id))
        before = _bill_dict(row)
        row.is_archived = True
        row.archived_at = datetime.utcnow()
        row.archived_by = current_user.id
        row.archive_reason = reason
        row.active_dedupe_key = None
        row.updated_by = current_user.id
        row.version += 1
        _record_audit("Mengarsipkan tagihan", "finance_bill", row.id, before, _bill_dict(row))
        db.session.commit()
        flash("Tagihan dipindahkan ke Arsip.", "success")
        return redirect(url_for("finance_administration"))

    @app.route("/finance/archive")
    @_finance_admin_required
    def finance_archive():
        rows = FinanceBill.query.filter_by(is_archived=True).order_by(FinanceBill.archived_at.desc()).limit(200).all()
        student_map, charge_map = _attach(rows)
        return render_template(
            "finance_v15b/archive.html", active_tab="administration", rows=rows,
            student_map=student_map, charge_map=charge_map,
        )

    @app.route("/finance/bills/<int:bill_id>/restore", methods=["POST"])
    @_finance_admin_required
    def finance_bill_restore(bill_id):
        row = db.get_or_404(FinanceBill, bill_id)
        if not row.is_archived:
            flash("Tagihan sudah aktif.", "info")
            return redirect(url_for("finance_bill_detail", bill_id=row.id))
        duplicate = FinanceBill.query.filter_by(active_dedupe_key=row.canonical_key).first()
        if duplicate:
            flash(f"Restore gagal karena tagihan aktif yang sama sudah tersedia: {duplicate.bill_number}.", "danger")
            return redirect(url_for("finance_archive"))
        before = _bill_dict(row)
        row.is_archived = False
        row.archived_at = None
        row.archived_by = None
        row.archive_reason = ""
        row.active_dedupe_key = row.canonical_key
        row.updated_by = current_user.id
        row.version += 1
        _record_audit("Merestore tagihan", "finance_bill", row.id, before, _bill_dict(row))
        db.session.commit()
        flash("Tagihan berhasil direstore.", "success")
        return redirect(url_for("finance_bill_detail", bill_id=row.id))

    @app.route("/finance/payments")
    @_finance_admin_required
    def finance_payments():
        return render_template(
            "finance_v15b/coming_soon.html", active_tab="payments",
            page_title="Riwayat Pembayaran",
            message="Belum ada pembayaran baru pada struktur terpadu. Data pembayaran akan diaktifkan pada tahap pembayaran berikutnya.",
        )

    @app.route("/finance/reports")
    @_finance_admin_required
    def finance_reports():
        return render_template(
            "finance_v15b/coming_soon.html", active_tab="reports",
            page_title="Laporan",
            message="Laporan PDF dan Excel akan menggunakan data tagihan terpadu setelah pencatatan pembayaran selesai diaktifkan.",
        )

    @app.context_processor
    def _finance_sidebar_context():
        try:
            general, _ = _active_settings()
            now_wib = datetime.utcnow() + timedelta(hours=7)
            current_month = next((name for name, number in MONTH_NUMBERS.items() if number == now_wib.month), str(now_wib.month))
            count = FinanceBill.query.filter(
                FinanceBill.is_archived.is_(False),
                FinanceBill.status.in_(["Belum Lunas", "Sebagian"]),
                FinanceBill.academic_year == general.academic_year_active,
                FinanceBill.semester == general.semester_active,
                FinanceBill.period_label == current_month,
                FinanceBill.period_year == now_wib.year,
            ).count()
        except Exception:
            count = 0
        return {"finance_unpaid_count": count}

    app.extensions["finance_v15b"] = {
        "models": {"bill": FinanceBill, "sequence": FinanceDocumentSequence},
        "migrate_legacy": migrate_legacy,
        "version": "V15-B",
    }
    return app.extensions["finance_v15b"]
