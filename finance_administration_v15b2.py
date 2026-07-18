"""Keuangan V15-B2 — finalisasi halaman Administrasi Iuran.

Dipasang setelah Keuangan V15-A dan V15-B. Modul ini hanya menyempurnakan
halaman Administrasi Iuran dan alur yang langsung terkait dengannya:
filter berbasis kelas, pembayaran bertahap, status otomatis, pembebasan,
riwayat, WhatsApp, dan bukti pembayaran.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename


VALID_STATUSES = {"Belum Lunas", "Sebagian", "Lunas", "Dibebaskan"}
DISPLAY_STATUSES = ["Lunas", "Sebagian", "Belum Lunas", "Dibebaskan", "Belum Ada Tagihan"]
PAGE_SIZES = {25, 50, 100}
PAYMENT_METHODS = {"Tunai", "Transfer", "Lainnya"}
ALLOWED_PROOF_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}
MAX_PROOF_BYTES = 5 * 1024 * 1024
MONTH_NUMBERS = {
    "Januari": 1, "Februari": 2, "Maret": 3, "April": 4,
    "Mei": 5, "Juni": 6, "Juli": 7, "Agustus": 8,
    "September": 9, "Oktober": 10, "November": 11, "Desember": 12,
}


def install_finance_administration_v15b2(app, db, namespace: dict[str, Any]):
    """Daftarkan model dan route Administrasi Iuran V15-B2."""
    if app.extensions.get("finance_administration_v15b2"):
        return app.extensions["finance_administration_v15b2"]

    v15a = app.extensions.get("finance_v15a")
    v15b = app.extensions.get("finance_v15b")
    if not v15a or not v15b:
        raise RuntimeError("Keuangan V15-A dan V15-B harus terpasang sebelum V15-B2.")

    Santri = namespace["Santri"]
    CLASSES = namespace.get("CLASSES", [])
    MONTHS = namespace.get("MONTHS", list(MONTH_NUMBERS))
    upload_root = Path(namespace.get("UPLOAD_DIR") or (Path(app.root_path) / "uploads"))
    proof_dir = upload_root / "finance_payments"
    proof_dir.mkdir(parents=True, exist_ok=True)

    v15a_models = v15a["models"]
    ChargeType = v15a_models["charge_type"]
    PaymentChannel = v15a_models["payment_channel"]
    WhatsAppSetting = v15a_models["whatsapp_setting"]
    AuditLog = v15a_models["audit"]

    v15b_models = v15b["models"]
    FinanceBill = v15b_models["bill"]
    FinanceDocumentSequence = v15b_models["sequence"]

    class FinancePayment(db.Model):
        __tablename__ = "finance_payment"
        id = db.Column(db.Integer, primary_key=True)
        transaction_number = db.Column(db.String(40), nullable=False, unique=True, index=True)
        bill_id = db.Column(db.Integer, db.ForeignKey("finance_bill.id"), nullable=False, index=True)
        payment_date = db.Column(db.Date, nullable=False, index=True)
        amount = db.Column(db.Integer, nullable=False)
        method = db.Column(db.String(30), nullable=False)
        payment_channel_id = db.Column(db.Integer, db.ForeignKey("finance_payment_channel.id"))
        receiver_name = db.Column(db.String(160), nullable=False, default="")
        notes = db.Column(db.Text, nullable=False, default="")
        proof_path = db.Column(db.String(255), nullable=False, default="")
        snapshot_json = db.Column(db.Text, nullable=False, default="{}")
        source_key = db.Column(db.String(120), unique=True, index=True)
        idempotency_key = db.Column(db.String(80), unique=True, index=True)
        is_cancelled = db.Column(db.Boolean, nullable=False, default=False, index=True)
        cancelled_at = db.Column(db.DateTime)
        cancelled_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        cancellation_reason = db.Column(db.Text, nullable=False, default="")
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        def snapshot(self) -> dict[str, Any]:
            try:
                return json.loads(self.snapshot_json or "{}")
            except (TypeError, json.JSONDecodeError):
                return {}

    class FinanceWaiver(db.Model):
        __tablename__ = "finance_waiver"
        id = db.Column(db.Integer, primary_key=True)
        bill_id = db.Column(db.Integer, db.ForeignKey("finance_bill.id"), nullable=False, index=True)
        waiver_date = db.Column(db.Date, nullable=False)
        reason = db.Column(db.Text, nullable=False)
        approved_by_name = db.Column(db.String(160), nullable=False)
        notes = db.Column(db.Text, nullable=False, default="")
        is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        cancelled_at = db.Column(db.DateTime)
        cancelled_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        cancellation_reason = db.Column(db.Text, nullable=False, default="")

    def _finance_admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_admin or current_user.is_teacher or not getattr(current_user, "is_active", True):
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def _clean(value: Any, limit: int = 255) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())[:limit]

    def _integer(value: Any, field: str, minimum: int = 0, maximum: int | None = None) -> int:
        try:
            cleaned = re.sub(r"[^0-9-]", "", str(value or ""))
            result = int(cleaned)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} harus berupa angka.") from exc
        if result < minimum or (maximum is not None and result > maximum):
            raise ValueError(f"{field} tidak valid.")
        return result

    def _format_wib(value: datetime | None) -> str:
        if value is None:
            return "Belum diisi"
        return (value + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M WIB")

    def _request_ip() -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",", 1)[0].strip() if forwarded else request.remote_addr or "")[:80]

    def _audit(action: str, entity_type: str, entity_id: Any, before: dict, after: dict) -> None:
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

    def _bill_dict(row: Any) -> dict[str, Any]:
        return {
            "bill_number": row.bill_number,
            "santri_id": row.santri_id,
            "academic_year": row.academic_year,
            "semester": row.semester,
            "charge_type_id": row.charge_type_id,
            "period_label": row.period_label,
            "period_year": row.period_year,
            "amount": int(row.amount or 0),
            "paid_amount": int(row.paid_amount or 0),
            "status": row.status,
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "notes": row.notes or "",
            "is_archived": bool(row.is_archived),
            "version": int(row.version or 1),
        }

    def _payment_dict(row: Any) -> dict[str, Any]:
        return {
            "transaction_number": row.transaction_number,
            "bill_id": row.bill_id,
            "payment_date": row.payment_date.isoformat() if row.payment_date else None,
            "amount": int(row.amount or 0),
            "method": row.method,
            "payment_channel_id": row.payment_channel_id,
            "receiver_name": row.receiver_name,
            "notes": row.notes,
            "proof_path": row.proof_path,
            "is_cancelled": bool(row.is_cancelled),
        }

    def _active_waiver(bill_id: int):
        return FinanceWaiver.query.filter_by(bill_id=bill_id, is_active=True).order_by(FinanceWaiver.id.desc()).first()

    def _active_payments(bill_id: int):
        return FinancePayment.query.filter_by(bill_id=bill_id, is_cancelled=False).order_by(
            FinancePayment.payment_date.desc(), FinancePayment.id.desc()
        )

    def _derive_status(amount: int, paid: int, waived: bool = False) -> str:
        if waived:
            return "Dibebaskan"
        if paid <= 0:
            return "Belum Lunas"
        if paid < amount:
            return "Sebagian"
        return "Lunas"

    def _recalculate_bill(bill: Any) -> None:
        paid = int(db.session.query(func.coalesce(func.sum(FinancePayment.amount), 0)).filter(
            FinancePayment.bill_id == bill.id,
            FinancePayment.is_cancelled.is_(False),
        ).scalar() or 0)
        waiver = _active_waiver(bill.id)
        bill.paid_amount = paid
        bill.status = _derive_status(int(bill.amount or 0), paid, bool(waiver))
        bill.waiver_reason = waiver.reason if waiver else ""
        bill.updated_by = getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None
        bill.version = int(bill.version or 1) + 1

    def _next_payment_number(year: int) -> str:
        row = FinanceDocumentSequence.query.filter_by(document_type="BYR", year=year).first()
        if row is None:
            row = FinanceDocumentSequence(document_type="BYR", year=year, last_number=0)
            db.session.add(row)
            db.session.flush()
        row.last_number += 1
        db.session.flush()
        return f"TPQ-{year}-{row.last_number:04d}"

    def _canonical_key(student_id: int, charge_type_id: int, academic_year: str,
                       semester: str, period_label: str, period_year: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", period_label.lower()).strip("-") or "periode"
        return "|".join([
            str(student_id), str(charge_type_id), academic_year.strip().lower(),
            semester.strip().lower(), str(period_year), slug,
        ])

    def _save_proof(file_storage) -> str:
        if not file_storage or not file_storage.filename:
            return ""
        original = secure_filename(file_storage.filename)
        extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if extension not in ALLOWED_PROOF_EXTENSIONS:
            raise ValueError("Bukti transfer harus PNG, JPG, JPEG, WEBP, atau PDF.")
        stream = file_storage.stream
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size <= 0 or size > MAX_PROOF_BYTES:
            raise ValueError("Ukuran bukti transfer maksimal 5 MB.")
        filename = f"payment_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}.{extension}"
        file_storage.save(proof_dir / filename)
        return filename

    def _normalize_phone(value: str) -> str:
        try:
            return v15a["normalize_phone"](value)
        except Exception as exc:
            raise ValueError("Nomor WhatsApp wali belum valid. Perbarui nomor pada Database Santri.") from exc

    def _rupiah(value: Any) -> str:
        try:
            return "Rp{:,.0f}".format(int(value or 0)).replace(",", ".")
        except Exception:
            return "Rp0"

    def _payment_snapshot(bill: Any, student: Any, charge: Any, channel: Any, receiver: str) -> dict[str, Any]:
        general, _, _, receipt = v15a["ensure_defaults"]()
        return {
            "tpq_name": general.tpq_name,
            "tpq_address": general.tpq_address,
            "logo_path": general.logo_path,
            "student_name": student.name if student else "Belum diisi",
            "student_class": student.class_name if student else "Belum diisi",
            "guardian_name": student.guardian_name if student and student.guardian_name else "Belum diisi",
            "bill_number": bill.bill_number,
            "charge_type": charge.name if charge else "Belum diisi",
            "period": f"{bill.period_label} {bill.period_year}",
            "bill_amount": int(bill.amount or 0),
            "receiver_name": receiver,
            "treasurer_name": receipt.treasurer_name,
            "treasurer_position": receipt.treasurer_position,
            "footer_note": receipt.footer_note,
            "payment_channel": {
                "label": channel.label if channel else "",
                "bank_name": channel.bank_name if channel else "",
                "account_number": channel.account_number if channel else "",
                "account_holder": channel.account_holder if channel else "",
            },
        }

    def backfill_legacy_payments() -> dict[str, int]:
        """Buat transaksi pembayaran untuk tagihan migrasi lama secara idempoten."""
        created_payments = 0
        created_waivers = 0
        bills = FinanceBill.query.order_by(FinanceBill.id).all()
        for bill in bills:
            active_count = FinancePayment.query.filter_by(bill_id=bill.id, is_cancelled=False).count()
            if int(bill.paid_amount or 0) > 0 and active_count == 0:
                source_key = f"legacy-bill-{bill.id}"
                if not FinancePayment.query.filter_by(source_key=source_key).first():
                    moment = bill.updated_at or bill.created_at or datetime.utcnow()
                    student = db.session.get(Santri, bill.santri_id)
                    charge = db.session.get(ChargeType, bill.charge_type_id)
                    payment = FinancePayment(
                        transaction_number=_next_payment_number(moment.year),
                        bill_id=bill.id,
                        payment_date=moment.date(),
                        amount=int(bill.paid_amount or 0),
                        method="Migrasi Data Lama",
                        receiver_name="Sistem Migrasi",
                        notes="Pembayaran hasil migrasi data administrasi lama.",
                        snapshot_json=json.dumps(
                            _payment_snapshot(bill, student, charge, None, "Sistem Migrasi"),
                            ensure_ascii=False,
                        ),
                        source_key=source_key,
                    )
                    db.session.add(payment)
                    created_payments += 1
            if bill.status == "Dibebaskan" and not _active_waiver(bill.id):
                db.session.add(FinanceWaiver(
                    bill_id=bill.id,
                    waiver_date=(bill.updated_at or datetime.utcnow()).date(),
                    reason=bill.waiver_reason or "Pembebasan dari data sebelum V15-B2.",
                    approved_by_name="Sistem Migrasi",
                    notes="Migrasi status pembebasan lama.",
                    created_by=None,
                ))
                created_waivers += 1
        db.session.flush()
        for bill in bills:
            paid = int(db.session.query(func.coalesce(func.sum(FinancePayment.amount), 0)).filter(
                FinancePayment.bill_id == bill.id,
                FinancePayment.is_cancelled.is_(False),
            ).scalar() or 0)
            waiver = _active_waiver(bill.id)
            bill.paid_amount = paid
            bill.status = _derive_status(int(bill.amount or 0), paid, bool(waiver))
            bill.waiver_reason = waiver.reason if waiver else ""
        db.session.commit()
        return {"payments": created_payments, "waivers": created_waivers, "bills": len(bills)}

    @_finance_admin_required
    def finance_administration():
        class_name = _clean(request.args.get("class_name"), 60)
        charge_type_id = _clean(request.args.get("charge_type_id"), 20)
        period = _clean(request.args.get("period"), 80)
        status = _clean(request.args.get("status"), 40)
        general, _, _, _ = v15a["ensure_defaults"]()
        academic_year = _clean(request.args.get("academic_year") or general.academic_year_active, 20)
        semester = _clean(request.args.get("semester") or general.semester_active, 20)
        sort = _clean(request.args.get("sort") or "name", 30)
        page = max(1, _integer(request.args.get("page", 1), "Halaman", 1))
        per_page = _integer(request.args.get("per_page", 25), "Jumlah per halaman", 1, 100)
        if per_page not in PAGE_SIZES:
            per_page = 25

        class_selected = class_name in CLASSES
        items: list[dict[str, Any]] = []
        students_count = 0
        if class_selected:
            students = Santri.query.filter_by(class_name=class_name, is_active=True).order_by(Santri.name).all()
            students_count = len(students)
            student_ids = [row.id for row in students]
            bills_by_student: dict[int, list[Any]] = {row.id: [] for row in students}
            if student_ids:
                bill_query = FinanceBill.query.filter(
                    FinanceBill.is_archived.is_(False),
                    FinanceBill.santri_id.in_(student_ids),
                )
                if charge_type_id.isdigit():
                    bill_query = bill_query.filter(FinanceBill.charge_type_id == int(charge_type_id))
                if period:
                    bill_query = bill_query.filter(FinanceBill.period_label == period)
                if academic_year:
                    bill_query = bill_query.filter(FinanceBill.academic_year == academic_year)
                if semester in {"Semester 1", "Semester 2"}:
                    bill_query = bill_query.filter(FinanceBill.semester == semester)
                if status in VALID_STATUSES:
                    bill_query = bill_query.filter(FinanceBill.status == status)
                for bill in bill_query.order_by(
                    FinanceBill.period_year.desc(), FinanceBill.period_month.desc(), FinanceBill.id.desc()
                ).all():
                    bills_by_student.setdefault(bill.santri_id, []).append(bill)

            for student in students:
                matched = bills_by_student.get(student.id, [])
                if status == "Belum Ada Tagihan":
                    if not matched:
                        items.append({"student": student, "bill": None})
                    continue
                if matched:
                    for bill in matched:
                        items.append({"student": student, "bill": bill})
                elif status not in VALID_STATUSES:
                    items.append({"student": student, "bill": None})

            def sort_key(item: dict[str, Any]):
                student = item["student"]
                bill = item["bill"]
                if sort == "newest":
                    return bill.created_at if bill else datetime.min
                if sort == "period":
                    return (bill.period_year if bill else 0, bill.period_month if bill and bill.period_month else 0, student.name.lower())
                if sort == "amount_desc":
                    return (int(bill.amount or 0) if bill else -1, student.name.lower())
                if sort == "amount_asc":
                    return (int(bill.amount or 0) if bill else 2_000_000_001, student.name.lower())
                if sort == "status":
                    return ((bill.status if bill else "Belum Ada Tagihan"), student.name.lower())
                return student.name.lower()

            reverse = sort in {"name_desc", "newest", "period", "amount_desc"}
            items.sort(key=sort_key, reverse=reverse)

        total = len(items)
        max_page = max(1, (total + per_page - 1) // per_page)
        page = min(page, max_page)
        page_items = items[(page - 1) * per_page:page * per_page]
        charge_ids = {item["bill"].charge_type_id for item in page_items if item["bill"]}
        charge_map = {
            row.id: row for row in ChargeType.query.filter(ChargeType.id.in_(charge_ids)).all()
        } if charge_ids else {}
        charge_types = ChargeType.query.order_by(ChargeType.sort_order, ChargeType.name).all()
        academic_years = [
            row[0] for row in db.session.query(FinanceBill.academic_year).distinct().order_by(FinanceBill.academic_year.desc()).all()
        ]
        if general.academic_year_active not in academic_years:
            academic_years.insert(0, general.academic_year_active)

        return render_template(
            "finance_v15b2/administration.html",
            active_tab="administration",
            items=page_items,
            charge_map=charge_map,
            classes=CLASSES,
            months=MONTHS,
            statuses=DISPLAY_STATUSES,
            charge_types=charge_types,
            academic_years=academic_years,
            total=total,
            students_count=students_count,
            page=page,
            max_page=max_page,
            per_page=per_page,
            class_selected=class_selected,
            filters={
                "class_name": class_name,
                "charge_type_id": charge_type_id,
                "period": period,
                "status": status,
                "academic_year": academic_year,
                "semester": semester,
                "sort": sort,
            },
        )

    @_finance_admin_required
    def finance_bill_detail(bill_id: int):
        bill = db.get_or_404(FinanceBill, bill_id)
        student = db.session.get(Santri, bill.santri_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        payments = FinancePayment.query.filter_by(bill_id=bill.id).order_by(
            FinancePayment.payment_date.desc(), FinancePayment.id.desc()
        ).all()
        waiver = _active_waiver(bill.id)
        audit_logs = AuditLog.query.filter_by(entity_type="finance_bill", entity_id=str(bill.id)).order_by(
            AuditLog.created_at.desc()
        ).limit(100).all()
        view = request.args.get("view", "detail")
        if view not in {"detail", "payments", "history"}:
            view = "detail"
        return render_template(
            "finance_v15b2/bill_detail.html",
            active_tab="administration",
            bill=bill,
            student=student,
            charge_type=charge,
            payments=payments,
            waiver=waiver,
            audit_logs=audit_logs,
            detail_view=view,
            format_wib=_format_wib,
            today=date.today().isoformat(),
        )

    @_finance_admin_required
    def finance_bill_edit(bill_id: int):
        bill = db.get_or_404(FinanceBill, bill_id)
        if bill.is_archived:
            flash("Tagihan berada di arsip. Restore terlebih dahulu sebelum mengedit.", "warning")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        active_payment_count = _active_payments(bill.id).count()
        waiver = _active_waiver(bill.id)
        if request.method == "POST":
            before = _bill_dict(bill)
            try:
                posted_version = _integer(request.form.get("version"), "Versi data", 1)
                if posted_version != int(bill.version or 1):
                    raise ValueError("Tagihan telah diperbarui oleh pengguna lain. Muat ulang halaman sebelum menyimpan.")
                amount = _integer(request.form.get("amount"), "Nominal", 0, 2_000_000_000)
                if amount < int(bill.paid_amount or 0):
                    raise ValueError("Nominal tagihan tidak boleh lebih kecil dari total pembayaran aktif.")
                due_raw = _clean(request.form.get("due_date"), 20)
                due_date = date.fromisoformat(due_raw) if due_raw else None

                if active_payment_count == 0 and not waiver:
                    charge_type_id = _integer(request.form.get("charge_type_id"), "Jenis tagihan", 1)
                    charge = db.session.get(ChargeType, charge_type_id)
                    if not charge or not charge.is_active:
                        raise ValueError("Jenis tagihan tidak tersedia atau tidak aktif.")
                    period_label = _clean(request.form.get("period_label"), 80)
                    period_year = _integer(request.form.get("period_year"), "Tahun", 2020, 2100)
                    if not period_label:
                        raise ValueError("Periode wajib diisi.")
                    new_key = _canonical_key(
                        bill.santri_id, charge.id, bill.academic_year, bill.semester,
                        period_label, period_year,
                    )
                    duplicate = FinanceBill.query.filter(
                        FinanceBill.id != bill.id,
                        FinanceBill.active_dedupe_key == new_key,
                    ).first()
                    if duplicate:
                        raise ValueError(f"Tagihan yang sama sudah tersedia: {duplicate.bill_number}.")
                    bill.charge_type_id = charge.id
                    bill.period_label = period_label
                    bill.period_month = MONTH_NUMBERS.get(period_label)
                    bill.period_year = period_year
                    bill.canonical_key = new_key
                    bill.active_dedupe_key = new_key

                bill.amount = amount
                bill.due_date = due_date
                bill.notes = _clean(request.form.get("notes"), 2000)
                bill.updated_by = current_user.id
                bill.version = int(bill.version or 1) + 1
                bill.status = _derive_status(amount, int(bill.paid_amount or 0), bool(waiver))
                _audit("Mengubah tagihan", "finance_bill", bill.id, before, _bill_dict(bill))
                db.session.commit()
                flash("Tagihan berhasil diperbarui.", "success")
                return redirect(url_for("finance_bill_detail", bill_id=bill.id))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        student = db.session.get(Santri, bill.santri_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        charge_types = ChargeType.query.filter_by(is_active=True).order_by(ChargeType.sort_order, ChargeType.name).all()
        return render_template(
            "finance_v15b2/bill_edit.html",
            active_tab="administration",
            bill=bill,
            student=student,
            charge_type=charge,
            charge_types=charge_types,
            months=MONTHS,
            active_payment_count=active_payment_count,
            waiver=waiver,
        )

    @app.route("/finance/bills/<int:bill_id>/payments/new", methods=["GET", "POST"])
    @_finance_admin_required
    def finance_payment_new(bill_id: int):
        bill = db.get_or_404(FinanceBill, bill_id)
        if bill.is_archived:
            flash("Tagihan berada di arsip.", "warning")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        if _active_waiver(bill.id):
            flash("Tagihan sedang dibebaskan. Batalkan pembebasan sebelum mencatat pembayaran.", "warning")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        if int(bill.remaining_amount or 0) <= 0:
            flash("Tagihan sudah lunas.", "info")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id, view="payments"))

        student = db.session.get(Santri, bill.santri_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        channels = PaymentChannel.query.filter_by(is_active=True).order_by(
            PaymentChannel.is_primary.desc(), PaymentChannel.sort_order, PaymentChannel.id
        ).all()
        token_key = f"finance_payment_token_{bill.id}"
        if request.method == "GET" or not session.get(token_key):
            session[token_key] = uuid.uuid4().hex

        if request.method == "POST":
            saved_proof = ""
            try:
                token = _clean(request.form.get("idempotency_key"), 80)
                expected_token = session.get(token_key)
                if not token or not expected_token or token != expected_token:
                    existing = FinancePayment.query.filter_by(idempotency_key=token).first() if token else None
                    if existing:
                        flash("Pembayaran tersebut sudah tersimpan.", "info")
                        return redirect(url_for("finance_payment_receipt", payment_id=existing.id))
                    raise ValueError("Sesi pembayaran tidak valid atau sudah digunakan. Muat ulang formulir.")
                posted_version = _integer(request.form.get("bill_version"), "Versi tagihan", 1)
                if posted_version != int(bill.version or 1):
                    raise ValueError("Tagihan telah diperbarui oleh pengguna lain. Muat ulang formulir pembayaran.")

                payment_date = date.fromisoformat(_clean(request.form.get("payment_date"), 20))
                amount = _integer(request.form.get("amount"), "Nominal dibayar", 1, 2_000_000_000)
                method = _clean(request.form.get("method"), 30)
                if method not in PAYMENT_METHODS:
                    raise ValueError("Metode pembayaran tidak valid.")
                allow_overpayment = request.form.get("allow_overpayment") in {"1", "on", "true"}
                remaining_before = int(bill.remaining_amount or 0)
                if amount > remaining_before and not allow_overpayment:
                    raise ValueError("Nominal pembayaran melebihi sisa tagihan.")

                channel = None
                channel_id = None
                if method == "Transfer":
                    channel_id = _integer(request.form.get("payment_channel_id"), "Rekening tujuan", 1)
                    channel = db.session.get(PaymentChannel, channel_id)
                    if not channel or not channel.is_active:
                        raise ValueError("Rekening tujuan tidak tersedia atau tidak aktif.")

                receiver = _clean(request.form.get("receiver_name") or current_user.full_name, 160)
                if not receiver:
                    raise ValueError("Nama admin/penerima wajib diisi.")
                saved_proof = _save_proof(request.files.get("proof"))
                before_bill = _bill_dict(bill)
                payment = FinancePayment(
                    transaction_number=_next_payment_number(payment_date.year),
                    bill_id=bill.id,
                    payment_date=payment_date,
                    amount=amount,
                    method=method,
                    payment_channel_id=channel_id,
                    receiver_name=receiver,
                    notes=_clean(request.form.get("notes"), 2000),
                    proof_path=saved_proof,
                    snapshot_json=json.dumps(_payment_snapshot(bill, student, charge, channel, receiver), ensure_ascii=False),
                    idempotency_key=token,
                    created_by=current_user.id,
                )
                db.session.add(payment)
                db.session.flush()
                _recalculate_bill(bill)
                _audit("Mencatat pembayaran", "finance_bill", bill.id, before_bill, {
                    **_bill_dict(bill),
                    "payment": _payment_dict(payment),
                    "overpayment_confirmed": bool(amount > remaining_before),
                })
                db.session.commit()
                session.pop(token_key, None)
                flash("Pembayaran berhasil disimpan dan status tagihan diperbarui otomatis.", "success")
                return redirect(url_for("finance_payment_receipt", payment_id=payment.id))
            except Exception as exc:
                db.session.rollback()
                if saved_proof:
                    try:
                        (proof_dir / saved_proof).unlink(missing_ok=True)
                    except OSError:
                        pass
                flash(str(exc), "danger")

        return render_template(
            "finance_v15b2/payment_form.html",
            active_tab="administration",
            bill=bill,
            student=student,
            charge_type=charge,
            channels=channels,
            idempotency_key=session.get(token_key, ""),
            today=date.today().isoformat(),
        )

    @app.route("/finance/payments/<int:payment_id>/cancel", methods=["POST"])
    @_finance_admin_required
    def finance_payment_cancel(payment_id: int):
        payment = db.get_or_404(FinancePayment, payment_id)
        bill = db.get_or_404(FinanceBill, payment.bill_id)
        if payment.is_cancelled:
            flash("Transaksi pembayaran sudah dibatalkan.", "info")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id, view="payments"))
        reason = _clean(request.form.get("reason"), 2000)
        if not reason:
            flash("Alasan pembatalan wajib diisi.", "danger")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id, view="payments"))
        before_bill = _bill_dict(bill)
        before_payment = _payment_dict(payment)
        payment.is_cancelled = True
        payment.cancelled_at = datetime.utcnow()
        payment.cancelled_by = current_user.id
        payment.cancellation_reason = reason
        _recalculate_bill(bill)
        _audit("Membatalkan pembayaran", "finance_bill", bill.id, {
            **before_bill, "payment": before_payment,
        }, {
            **_bill_dict(bill), "payment": _payment_dict(payment), "reason": reason,
        })
        db.session.commit()
        flash("Transaksi dibatalkan. Total dibayar, sisa, dan status sudah dihitung ulang.", "success")
        return redirect(url_for("finance_bill_detail", bill_id=bill.id, view="payments"))

    @app.route("/finance/bills/<int:bill_id>/waive", methods=["POST"])
    @_finance_admin_required
    def finance_bill_waive(bill_id: int):
        bill = db.get_or_404(FinanceBill, bill_id)
        if bill.is_archived:
            flash("Tagihan berada di arsip.", "warning")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        if _active_waiver(bill.id):
            flash("Tagihan sudah dibebaskan.", "info")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        if _active_payments(bill.id).count() > 0:
            flash("Tagihan yang sudah memiliki pembayaran tidak dapat dibebaskan. Batalkan transaksi terlebih dahulu bila diperlukan.", "danger")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id, view="payments"))
        try:
            waiver_date = date.fromisoformat(_clean(request.form.get("waiver_date"), 20))
            reason = _clean(request.form.get("reason"), 2000)
            approved_by = _clean(request.form.get("approved_by_name"), 160)
            notes = _clean(request.form.get("notes"), 2000)
            if not reason or not approved_by:
                raise ValueError("Alasan pembebasan dan nama pemberi persetujuan wajib diisi.")
            before = _bill_dict(bill)
            waiver = FinanceWaiver(
                bill_id=bill.id,
                waiver_date=waiver_date,
                reason=reason,
                approved_by_name=approved_by,
                notes=notes,
                created_by=current_user.id,
            )
            db.session.add(waiver)
            db.session.flush()
            _recalculate_bill(bill)
            _audit("Membebaskan tagihan", "finance_bill", bill.id, before, {
                **_bill_dict(bill),
                "waiver": {"date": waiver_date.isoformat(), "reason": reason, "approved_by": approved_by, "notes": notes},
            })
            db.session.commit()
            flash("Tagihan berhasil dibebaskan dan tidak dihitung sebagai tunggakan.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("finance_bill_detail", bill_id=bill.id))

    @app.route("/finance/bills/<int:bill_id>/unwaive", methods=["POST"])
    @_finance_admin_required
    def finance_bill_unwaive(bill_id: int):
        bill = db.get_or_404(FinanceBill, bill_id)
        waiver = _active_waiver(bill.id)
        if not waiver:
            flash("Tagihan tidak sedang dibebaskan.", "info")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        reason = _clean(request.form.get("reason"), 2000)
        if not reason:
            flash("Alasan pembatalan pembebasan wajib diisi.", "danger")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        before = _bill_dict(bill)
        waiver.is_active = False
        waiver.cancelled_at = datetime.utcnow()
        waiver.cancelled_by = current_user.id
        waiver.cancellation_reason = reason
        _recalculate_bill(bill)
        _audit("Membatalkan pembebasan", "finance_bill", bill.id, before, {
            **_bill_dict(bill), "reason": reason,
        })
        db.session.commit()
        flash("Pembebasan dibatalkan dan status tagihan dihitung ulang.", "success")
        return redirect(url_for("finance_bill_detail", bill_id=bill.id))

    @app.route("/finance/bills/<int:bill_id>/whatsapp")
    @_finance_admin_required
    def finance_bill_whatsapp(bill_id: int):
        bill = db.get_or_404(FinanceBill, bill_id)
        if bill.status not in {"Belum Lunas", "Sebagian"}:
            flash("Pengingat WhatsApp hanya tersedia untuk tagihan Belum Lunas atau Sebagian.", "warning")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))
        student = db.session.get(Santri, bill.santri_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        try:
            phone = _normalize_phone(student.guardian_phone if student else "")
            whatsapp = db.session.get(WhatsAppSetting, 1)
            template = whatsapp.reminder_template if whatsapp else ""
            message = template.format(
                nama_santri=student.name if student else "Santri",
                jenis_tagihan=charge.name if charge else "Tagihan",
                periode=f"{bill.period_label} {bill.period_year}",
                nominal=_rupiah(bill.amount),
                dibayar=_rupiah(bill.paid_amount),
                sisa=_rupiah(bill.remaining_amount),
            )
            _audit("Membuka pengingat WhatsApp", "finance_bill", bill.id, {}, {"phone": phone})
            db.session.commit()
            return redirect(f"https://wa.me/{phone}?text={quote(message)}")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("finance_bill_detail", bill_id=bill.id))

    @app.route("/finance/payments/<int:payment_id>/receipt")
    @_finance_admin_required
    def finance_payment_receipt(payment_id: int):
        payment = db.get_or_404(FinancePayment, payment_id)
        bill = db.get_or_404(FinanceBill, payment.bill_id)
        student = db.session.get(Santri, bill.santri_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        return render_template(
            "finance_v15b2/receipt_preview.html",
            payment=payment,
            bill=bill,
            student=student,
            charge_type=charge,
            snapshot=payment.snapshot(),
        )

    @app.route("/finance/payments/<int:payment_id>/receipt.pdf")
    @_finance_admin_required
    def finance_payment_receipt_pdf(payment_id: int):
        """Unduh PDF dengan struktur visual yang sama seperti halaman preview."""
        payment = db.get_or_404(FinancePayment, payment_id)
        bill = db.get_or_404(FinanceBill, payment.bill_id)
        student = db.session.get(Santri, bill.santri_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        snapshot = payment.snapshot()
        try:
            from html import escape
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_LEFT, TA_RIGHT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
            )
        except ImportError as exc:
            raise RuntimeError("ReportLab belum tersedia pada server.") from exc

        def _safe(value, fallback="Belum diisi"):
            value = fallback if value is None or str(value).strip() == "" else value
            return escape(str(value))

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=f"Bukti {payment.transaction_number}",
            author=snapshot.get("tpq_name") or "TPQ HMarisa",
        )

        styles = getSampleStyleSheet()
        tpq_name_style = ParagraphStyle(
            "ReceiptTpqName",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=19,
            textColor=colors.HexColor("#146B45"),
            spaceAfter=2,
        )
        address_style = ParagraphStyle(
            "ReceiptAddress",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12,
            textColor=colors.HexColor("#66716C"),
        )
        receipt_label_style = ParagraphStyle(
            "ReceiptHeaderLabel",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#6B746F"),
            uppercase=True,
        )
        receipt_number_style = ParagraphStyle(
            "ReceiptHeaderNumber",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#1E293B"),
        )
        grid_label_style = ParagraphStyle(
            "ReceiptGridLabel",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=9,
            textColor=colors.HexColor("#7B8580"),
            spaceAfter=2,
        )
        grid_value_style = ParagraphStyle(
            "ReceiptGridValue",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.2,
            leading=13,
            textColor=colors.HexColor("#315444"),
        )
        grid_value_bold_style = ParagraphStyle(
            "ReceiptGridValueBold",
            parent=grid_value_style,
            fontName="Helvetica-Bold",
        )
        note_style = ParagraphStyle(
            "ReceiptFooterNote",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12,
            textColor=colors.HexColor("#66716C"),
        )
        treasurer_position_style = ParagraphStyle(
            "ReceiptTreasurerPosition",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=10,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#6B746F"),
        )
        treasurer_name_style = ParagraphStyle(
            "ReceiptTreasurerName",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#315444"),
        )
        account_style = ParagraphStyle(
            "ReceiptAccount",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12,
            textColor=colors.HexColor("#315444"),
        )
        cancelled_style = ParagraphStyle(
            "ReceiptCancelled",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            alignment=1,
            textColor=colors.HexColor("#B42318"),
        )

        def _grid_cell(label, value, bold=False):
            style = grid_value_bold_style if bold else grid_value_style
            return [
                Paragraph(_safe(label, ""), grid_label_style),
                Paragraph(_safe(value), style),
            ]

        tpq_name = snapshot.get("tpq_name") or "TPQ HMarisa"
        tpq_address = snapshot.get("tpq_address") or ""
        guardian_name = (
            student.guardian_name
            if student and getattr(student, "guardian_name", None)
            else snapshot.get("guardian_name")
        )
        student_name = student.name if student else snapshot.get("student_name")
        student_class = student.class_name if student else snapshot.get("student_class")
        charge_name = charge.name if charge else snapshot.get("charge_type")

        header = Table(
            [[
                [
                    Paragraph(_safe(tpq_name, "TPQ HMarisa"), tpq_name_style),
                    Paragraph(_safe(tpq_address, ""), address_style),
                ],
                [
                    Paragraph("BUKTI<br/>PEMBAYARAN", receipt_label_style),
                    Paragraph(_safe(payment.transaction_number), receipt_number_style),
                ],
            ]],
            colWidths=[118 * mm, 38 * mm],
        )
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        details = [
            [_grid_cell("NAMA SANTRI", student_name), _grid_cell("KELAS", student_class)],
            [_grid_cell("ORANG TUA/WALI", guardian_name), _grid_cell("JENIS TAGIHAN", charge_name)],
            [_grid_cell("PERIODE", f"{bill.period_label} {bill.period_year}"), _grid_cell("NOMINAL TAGIHAN", _rupiah(bill.amount))],
            [_grid_cell("NOMINAL DIBAYAR", _rupiah(payment.amount), True), _grid_cell("TOTAL DIBAYAR", _rupiah(bill.paid_amount))],
            [_grid_cell("SISA TAGIHAN", _rupiah(bill.remaining_amount)), _grid_cell("STATUS", bill.status, True)],
            [_grid_cell("TANGGAL", payment.payment_date.strftime("%d/%m/%Y")), _grid_cell("METODE", payment.method)],
            [_grid_cell("ADMIN/PENERIMA", payment.receiver_name), _grid_cell("CATATAN", payment.notes or "Belum diisi")],
        ]
        grid = Table(details, colWidths=[78 * mm, 78 * mm], rowHeights=[18 * mm] * 7)
        grid_style = [
            ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#DDE6E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ]
        status_colors = {
            "Lunas": colors.HexColor("#E7F6EC"),
            "Sebagian": colors.HexColor("#FFF3D6"),
            "Belum Lunas": colors.HexColor("#FDE8E7"),
            "Dibebaskan": colors.HexColor("#E6F1FF"),
        }
        grid_style.append(("BACKGROUND", (1, 4), (1, 4), status_colors.get(bill.status, colors.white)))
        grid.setStyle(TableStyle(grid_style))

        story = [header, Spacer(1, 5 * mm)]
        line = Table([[""]], colWidths=[156 * mm], rowHeights=[0.8 * mm])
        line.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#3B8064")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([line, Spacer(1, 7 * mm)])

        if payment.is_cancelled:
            story.extend([Paragraph("TRANSAKSI DIBATALKAN", cancelled_style), Spacer(1, 4 * mm)])

        story.append(grid)

        channel = snapshot.get("payment_channel") or {}
        if channel.get("account_number"):
            account_text = (
                f"<b>Informasi Rekening</b><br/>"
                f"{_safe(channel.get('bank_name') or channel.get('label'))} · "
                f"{_safe(channel.get('account_number'))} · "
                f"a.n. {_safe(channel.get('account_holder'))}"
            )
            account_box = Table([[Paragraph(account_text, account_style)]], colWidths=[156 * mm])
            account_box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F8F5")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE6E1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]))
            story.extend([Spacer(1, 5 * mm), account_box])

        footer_line = Table([[""]], colWidths=[156 * mm], rowHeights=[0.35 * mm])
        footer_line.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E1E8E4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        footer_note = snapshot.get("footer_note") or "Dokumen ini dibuat melalui Portal TPQ HMarisa."
        treasurer_name = snapshot.get("treasurer_name")
        treasurer_position = snapshot.get("treasurer_position") or "Bendahara TPQ"
        footer_right = []
        if treasurer_name:
            footer_right = [
                Paragraph(_safe(treasurer_position), treasurer_position_style),
                Paragraph(_safe(treasurer_name), treasurer_name_style),
            ]
        footer = Table(
            [[[Paragraph(_safe(footer_note), note_style)], footer_right]],
            colWidths=[111 * mm, 45 * mm],
        )
        footer.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([Spacer(1, 7 * mm), footer_line, Spacer(1, 5 * mm), KeepTogether(footer)])

        doc.build(story)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"Bukti_{payment.transaction_number}.pdf",
        )

    @app.route("/finance/payments/<int:payment_id>/proof")
    @_finance_admin_required
    def finance_payment_proof(payment_id: int):
        payment = db.get_or_404(FinancePayment, payment_id)
        if not payment.proof_path:
            abort(404)
        safe = secure_filename(payment.proof_path)
        if safe != payment.proof_path:
            abort(404)
        return send_from_directory(proof_dir, safe, as_attachment=False)

    # Route V15-B tetap digunakan; hanya fungsi tampilannya diganti secara terarah.
    app.view_functions["finance_administration"] = finance_administration
    app.view_functions["finance_bill_detail"] = finance_bill_detail
    app.view_functions["finance_bill_edit"] = finance_bill_edit

    app.extensions["finance_administration_v15b2"] = {
        "models": {"payment": FinancePayment, "waiver": FinanceWaiver},
        "backfill_legacy_payments": backfill_legacy_payments,
        "recalculate_bill": _recalculate_bill,
        "version": "V15-B2",
    }
    return app.extensions["finance_administration_v15b2"]
