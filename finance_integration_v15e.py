"""Keuangan V15-E — integrasi, hak akses, dan finalisasi portal.

Modul ini dipasang setelah V15-A, V15-B, V15-B2, dan V15-C/D. Fokusnya:
- integrasi Keuangan pada detail santri;
- akses baca-saja wali santri;
- peran Bendahara yang dibatasi hanya ke modul Keuangan;
- akses baca-saja Guru per kelas setelah diberi izin;
- halaman Audit Trail Keuangan.

Tidak ada fitur kas, pemasukan, pengeluaran, atau akuntansi.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from html import escape
from io import BytesIO
from typing import Any

from flask import (
    abort, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

PAGE_SIZES = {25, 50, 100}
FINANCE_STATUSES = ("Lunas", "Sebagian", "Belum Lunas", "Dibebaskan")


def install_finance_integration_v15e(app, db, namespace: dict[str, Any]):
    """Daftarkan integrasi Keuangan V15-E secara aditif dan terisolasi."""
    if app.extensions.get("finance_integration_v15e"):
        return app.extensions["finance_integration_v15e"]

    v15a = app.extensions.get("finance_v15a")
    v15b = app.extensions.get("finance_v15b")
    v15b2 = app.extensions.get("finance_administration_v15b2")
    v15cd = app.extensions.get("finance_history_reports_v15cd")
    if not all((v15a, v15b, v15b2, v15cd)):
        raise RuntimeError(
            "Keuangan V15-A, V15-B, V15-B2, dan V15-C/D harus terpasang sebelum V15-E."
        )

    User = namespace["User"]
    Santri = namespace["Santri"]
    selected_guardian_student = namespace["selected_guardian_student"]
    normalize_class_name = namespace["normalize_class_name"]
    superadmin_required = namespace["superadmin_required"]

    models_a = v15a["models"]
    GeneralSetting = models_a["general"]
    ChargeType = models_a["charge_type"]
    PaymentChannel = models_a["payment_channel"]
    AuditLog = models_a["audit"]

    FinanceBill = v15b["models"]["bill"]
    FinancePayment = v15b2["models"]["payment"]

    class FinanceAccessPermission(db.Model):
        __tablename__ = "finance_access_permission"
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True, index=True)
        can_view_class_status = db.Column(db.Boolean, nullable=False, default=False)
        can_download_class_report = db.Column(db.Boolean, nullable=False, default=False)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def _clean(value: Any, limit: int = 255) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())[:limit]

    def _integer(value: Any, default: int, minimum: int = 1, maximum: int = 100000) -> int:
        try:
            result = int(str(value or default))
        except (TypeError, ValueError):
            result = default
        return min(max(result, minimum), maximum)

    def _format_wib(value: datetime | None) -> str:
        if not value:
            return "Belum diisi"
        return (value + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M WIB")

    def _rupiah(value: Any) -> str:
        try:
            return "Rp{:,.0f}".format(int(value or 0)).replace(",", ".")
        except (TypeError, ValueError):
            return "Rp0"

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

    def _general_setting():
        row = GeneralSetting.query.order_by(GeneralSetting.id.asc()).first()
        if row is None:
            row, _, _, _ = v15a["ensure_defaults"]()
        return row

    def _permission_for(user_id: int | None):
        if not user_id:
            return None
        return FinanceAccessPermission.query.filter_by(user_id=user_id).first()

    def _student_maps(bills: list[Any]):
        charge_ids = {row.charge_type_id for row in bills}
        charge_map = {
            row.id: row for row in ChargeType.query.filter(ChargeType.id.in_(charge_ids or {-1})).all()
        }
        return charge_map

    def _bill_rows(student_id: int, include_archived: bool = False):
        query = FinanceBill.query.filter_by(santri_id=student_id)
        if not include_archived:
            query = query.filter_by(is_archived=False)
        bills = query.order_by(
            FinanceBill.period_year.desc(), FinanceBill.period_month.desc(), FinanceBill.id.desc()
        ).all()
        bill_ids = [row.id for row in bills]
        payments = []
        if bill_ids:
            payments = FinancePayment.query.filter(
                FinancePayment.bill_id.in_(bill_ids)
            ).order_by(FinancePayment.payment_date.desc(), FinancePayment.id.desc()).all()
        payment_map: dict[int, list[Any]] = {bill_id: [] for bill_id in bill_ids}
        for payment in payments:
            payment_map.setdefault(payment.bill_id, []).append(payment)
        return bills, payment_map, _student_maps(bills)

    def _student_summary(student_id: int) -> dict[str, Any]:
        bills = FinanceBill.query.filter_by(santri_id=student_id, is_archived=False).all()
        total = sum(int(row.amount or 0) for row in bills)
        paid = sum(int(row.paid_amount or 0) for row in bills)
        status_counts = {status: 0 for status in FINANCE_STATUSES}
        for row in bills:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
        return {
            "bill_count": len(bills),
            "total": total,
            "paid": paid,
            "remaining": max(0, total - paid),
            "unpaid_count": status_counts.get("Belum Lunas", 0) + status_counts.get("Sebagian", 0),
            "status_counts": status_counts,
        }

    def _admin_or_superadmin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if getattr(current_user, "role", "") not in {"admin_utama", "admin"}:
                abort(403)
            if not getattr(current_user, "is_active", True):
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def _teacher_permission_required(download: bool = False):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if getattr(current_user, "role", "") != "guru" or not getattr(current_user, "is_active", True):
                    abort(403)
                permission = _permission_for(current_user.id)
                allowed = permission and permission.can_view_class_status
                if download:
                    allowed = allowed and permission.can_download_class_report
                if not allowed:
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    # Bendahara masuk melalui panel staf, tetapi dibatasi hanya pada Keuangan.
    sensitive_bendahara_endpoints = {
        "finance_settings", "finance_settings_general", "finance_settings_billing",
        "finance_settings_payment", "finance_settings_whatsapp", "finance_settings_receipt",
        "finance_settings_asset", "finance_access_v15e", "finance_audit_v15e",
        "finance_bill_archive", "finance_archive", "finance_bill_restore",
        "finance_bill_waive", "finance_bill_unwaive", "backup_database",
    }

    @app.before_request
    def _restrict_bendahara_scope():
        if not current_user.is_authenticated or getattr(current_user, "role", "") != "bendahara":
            return None
        endpoint = request.endpoint or ""
        if endpoint == "dashboard":
            return redirect(url_for("finance_summary"))
        if endpoint in {"static", "logout"}:
            return None
        if endpoint in sensitive_bendahara_endpoints:
            abort(403)
        if endpoint.startswith("finance_") or endpoint == "finance":
            return None
        abort(403)

    @app.route("/student/<int:student_id>/finance")
    @_admin_or_superadmin_required
    def student_finance_v15e(student_id: int):
        student = db.get_or_404(Santri, student_id)
        bills, payment_map, charge_map = _bill_rows(student.id)
        summary = _student_summary(student.id)
        return render_template(
            "finance_v15e/student_finance.html",
            student=student,
            bills=bills,
            payment_map=payment_map,
            charge_map=charge_map,
            summary=summary,
            active_student_tab="finance",
        )

    @app.route("/ananda/<int:student_id>/keuangan")
    @login_required
    def guardian_finance_v15e(student_id: int):
        if current_user.is_admin:
            return redirect(url_for("student_finance_v15e", student_id=student_id))
        student = db.get_or_404(Santri, student_id)
        selected = selected_guardian_student()
        if not selected or selected.id != student.id:
            abort(403)
        bills, payment_map, charge_map = _bill_rows(student.id)
        channels = PaymentChannel.query.filter_by(is_active=True).order_by(
            PaymentChannel.is_primary.desc(), PaymentChannel.sort_order, PaymentChannel.id
        ).all()
        return render_template(
            "finance_v15e/guardian_finance.html",
            student=student,
            bills=bills,
            payment_map=payment_map,
            charge_map=charge_map,
            summary=_student_summary(student.id),
            channels=channels,
            general=_general_setting(),
        )

    def _guardian_payment(student_id: int, payment_id: int):
        if current_user.is_admin:
            abort(403)
        selected = selected_guardian_student()
        if not selected or selected.id != student_id:
            abort(403)
        payment = db.get_or_404(FinancePayment, payment_id)
        bill = db.get_or_404(FinanceBill, payment.bill_id)
        if bill.santri_id != student_id or bill.is_archived:
            abort(403)
        student = db.get_or_404(Santri, student_id)
        charge = db.session.get(ChargeType, bill.charge_type_id)
        return student, bill, payment, charge

    @app.route("/ananda/<int:student_id>/keuangan/pembayaran/<int:payment_id>/bukti")
    @login_required
    def guardian_finance_receipt_v15e(student_id: int, payment_id: int):
        student, bill, payment, charge = _guardian_payment(student_id, payment_id)
        return render_template(
            "finance_v15e/guardian_receipt.html",
            student=student,
            bill=bill,
            payment=payment,
            charge_type=charge,
            snapshot=payment.snapshot(),
        )

    @app.route("/ananda/<int:student_id>/keuangan/pembayaran/<int:payment_id>/bukti.pdf")
    @login_required
    def guardian_finance_receipt_pdf_v15e(student_id: int, payment_id: int):
        student, bill, payment, charge = _guardian_payment(student_id, payment_id)
        snapshot = payment.snapshot()
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_RIGHT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("ReportLab belum tersedia pada server.") from exc

        def safe(value: Any, fallback: str = "Belum diisi") -> str:
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
        title_style = ParagraphStyle(
            "Title", parent=styles["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=19, textColor=colors.HexColor("#146B45"),
        )
        small = ParagraphStyle(
            "Small", parent=styles["BodyText"], fontSize=8.5, leading=11,
            textColor=colors.HexColor("#66716C"),
        )
        right = ParagraphStyle(
            "Right", parent=small, alignment=TA_RIGHT, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1E293B"),
        )
        label_style = ParagraphStyle(
            "Label", parent=small, fontSize=7.4, textColor=colors.HexColor("#7B8580"),
        )
        value_style = ParagraphStyle(
            "Value", parent=styles["BodyText"], fontSize=10, leading=12,
            textColor=colors.HexColor("#315444"),
        )
        value_bold = ParagraphStyle("ValueBold", parent=value_style, fontName="Helvetica-Bold")

        header = Table([[
            [Paragraph(safe(snapshot.get("tpq_name"), "TPQ HMarisa"), title_style),
             Paragraph(safe(snapshot.get("tpq_address"), ""), small)],
            [Paragraph("BUKTI PEMBAYARAN", right), Paragraph(safe(payment.transaction_number), right)],
        ]], colWidths=[118 * mm, 38 * mm])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))

        def cell(label: str, value: Any, bold: bool = False):
            return [Paragraph(safe(label, ""), label_style), Paragraph(safe(value), value_bold if bold else value_style)]

        guardian_name = student.guardian_name or snapshot.get("guardian_name")
        charge_name = charge.name if charge else snapshot.get("charge_type")
        rows = [
            [cell("NAMA SANTRI", student.name), cell("KELAS", student.class_name)],
            [cell("ORANG TUA/WALI", guardian_name), cell("JENIS TAGIHAN", charge_name)],
            [cell("PERIODE", f"{bill.period_label} {bill.period_year}"), cell("NOMINAL TAGIHAN", _rupiah(bill.amount))],
            [cell("NOMINAL DIBAYAR", _rupiah(payment.amount), True), cell("TOTAL DIBAYAR", _rupiah(bill.paid_amount))],
            [cell("SISA TAGIHAN", _rupiah(bill.remaining_amount)), cell("STATUS", bill.status, True)],
            [cell("TANGGAL", payment.payment_date.strftime("%d/%m/%Y")), cell("METODE", payment.method)],
            [cell("ADMIN/PENERIMA", payment.receiver_name), cell("CATATAN", payment.notes or "Belum diisi")],
        ]
        grid = Table(rows, colWidths=[78 * mm, 78 * mm], rowHeights=[18 * mm] * 7)
        grid.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#DDE6E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        line = Table([[""]], colWidths=[156 * mm], rowHeights=[0.8 * mm])
        line.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#3B8064"))]))
        footer = Paragraph(
            safe(snapshot.get("footer_note"), "Dokumen ini dibuat melalui Portal TPQ HMarisa."), small
        )
        story = [header, Spacer(1, 5 * mm), line, Spacer(1, 7 * mm)]
        if payment.is_cancelled:
            story.extend([Paragraph("TRANSAKSI DIBATALKAN", title_style), Spacer(1, 4 * mm)])
        story.extend([grid, Spacer(1, 7 * mm), footer])
        doc.build(story)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"Bukti_{payment.transaction_number}.pdf",
        )

    @app.route("/finance/settings/access", methods=["GET", "POST"])
    @superadmin_required
    def finance_access_v15e():
        teachers = User.query.filter_by(role="guru").order_by(User.full_name).all()
        if request.method == "POST":
            user_id = request.form.get("user_id", type=int)
            teacher = db.session.get(User, user_id) if user_id else None
            if not teacher or teacher.role != "guru":
                abort(400)
            row = _permission_for(teacher.id)
            before = {
                "can_view_class_status": bool(row.can_view_class_status) if row else False,
                "can_download_class_report": bool(row.can_download_class_report) if row else False,
            }
            if row is None:
                row = FinanceAccessPermission(user_id=teacher.id)
                db.session.add(row)
            row.can_view_class_status = request.form.get("can_view_class_status") == "1"
            row.can_download_class_report = (
                row.can_view_class_status and request.form.get("can_download_class_report") == "1"
            )
            row.updated_by = current_user.id
            after = {
                "can_view_class_status": row.can_view_class_status,
                "can_download_class_report": row.can_download_class_report,
                "assigned_class": teacher.assigned_class,
            }
            _audit("Mengubah hak akses keuangan guru", "finance_access_permission", teacher.id, before, after)
            db.session.commit()
            flash(f"Hak akses Keuangan untuk {teacher.full_name} berhasil diperbarui.", "success")
            return redirect(url_for("finance_access_v15e"))
        permission_map = {
            row.user_id: row for row in FinanceAccessPermission.query.filter(
                FinanceAccessPermission.user_id.in_([teacher.id for teacher in teachers] or {-1})
            ).all()
        }
        return render_template(
            "finance_v15e/access.html",
            teachers=teachers,
            permission_map=permission_map,
            section="access",
        )

    @app.route("/finance/class-status")
    @_teacher_permission_required(download=False)
    def finance_teacher_status_v15e():
        class_name = normalize_class_name(current_user.assigned_class)
        general = _general_setting()
        academic_year = _clean(request.args.get("academic_year") or general.academic_year_active, 20)
        semester = _clean(request.args.get("semester") or general.semester_active, 20)
        period = _clean(request.args.get("period"), 80)
        status = _clean(request.args.get("status"), 30)
        student_ids = [row[0] for row in db.session.query(Santri.id).filter_by(
            class_name=class_name, is_active=True
        ).all()]
        query = FinanceBill.query.filter(
            FinanceBill.is_archived.is_(False),
            FinanceBill.santri_id.in_(student_ids or {-1}),
            FinanceBill.academic_year == academic_year,
            FinanceBill.semester == semester,
        )
        if period:
            query = query.filter(FinanceBill.period_label == period)
        if status in FINANCE_STATUSES:
            query = query.filter(FinanceBill.status == status)
        bills = query.order_by(FinanceBill.period_year.desc(), FinanceBill.period_month.desc()).all()
        student_map = {
            row.id: row for row in Santri.query.filter(Santri.id.in_({b.santri_id for b in bills} or {-1})).all()
        }
        charge_map = _student_maps(bills)
        permission = _permission_for(current_user.id)
        return render_template(
            "finance_v15e/teacher_status.html",
            bills=bills,
            student_map=student_map,
            charge_map=charge_map,
            class_name=class_name,
            academic_year=academic_year,
            semester=semester,
            period=period,
            status=status,
            general=general,
            can_download=bool(permission and permission.can_download_class_report),
        )

    @app.route("/finance/class-status.xlsx")
    @_teacher_permission_required(download=True)
    def finance_teacher_export_v15e():
        class_name = normalize_class_name(current_user.assigned_class)
        general = _general_setting()
        academic_year = _clean(request.args.get("academic_year") or general.academic_year_active, 20)
        semester = _clean(request.args.get("semester") or general.semester_active, 20)
        student_ids = [row[0] for row in db.session.query(Santri.id).filter_by(
            class_name=class_name, is_active=True
        ).all()]
        bills = FinanceBill.query.filter(
            FinanceBill.is_archived.is_(False),
            FinanceBill.santri_id.in_(student_ids or {-1}),
            FinanceBill.academic_year == academic_year,
            FinanceBill.semester == semester,
        ).order_by(FinanceBill.period_year, FinanceBill.period_month, FinanceBill.id).all()
        student_map = {
            row.id: row for row in Santri.query.filter(Santri.id.in_({b.santri_id for b in bills} or {-1})).all()
        }
        charge_map = _student_maps(bills)
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openpyxl belum tersedia pada server.") from exc
        wb = Workbook()
        ws = wb.active
        ws.title = "Status Iuran"
        ws.append(["Nama Santri", "Kelas", "Jenis Tagihan", "Periode", "Nominal", "Dibayar", "Sisa", "Status"])
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
        for bill in bills:
            student = student_map.get(bill.santri_id)
            charge = charge_map.get(bill.charge_type_id)
            ws.append([
                student.name if student else "Santri tidak ditemukan",
                class_name,
                charge.name if charge else "Tagihan",
                f"{bill.period_label} {bill.period_year}",
                int(bill.amount or 0),
                int(bill.paid_amount or 0),
                int(bill.remaining_amount or 0),
                bill.status,
            ])
        for column in "ABCDEFGH":
            ws.column_dimensions[column].width = 22
        stream = BytesIO()
        wb.save(stream)
        stream.seek(0)
        safe_class = re.sub(r"[^a-z0-9]+", "_", class_name.lower()).strip("_")
        return send_file(
            stream,
            as_attachment=True,
            download_name=f"status_iuran_{safe_class}_{academic_year.replace('/', '-')}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/finance/audit")
    @superadmin_required
    def finance_audit_v15e():
        q = _clean(request.args.get("q"), 120)
        action = _clean(request.args.get("action"), 80)
        entity_type = _clean(request.args.get("entity_type"), 80)
        page = _integer(request.args.get("page"), 1)
        per_page = _integer(request.args.get("per_page"), 25)
        if per_page not in PAGE_SIZES:
            per_page = 25
        query = AuditLog.query
        if q:
            pattern = f"%{q}%"
            query = query.filter(
                or_(
                    AuditLog.user_name.ilike(pattern),
                    AuditLog.entity_id.ilike(pattern),
                    AuditLog.request_id.ilike(pattern),
                    AuditLog.ip_address.ilike(pattern),
                )
            )
        if action:
            query = query.filter(AuditLog.action == action)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        total = query.count()
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(max(page, 1), pages)
        rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page).all()
        actions = [row[0] for row in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
        entities = [row[0] for row in db.session.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()]
        return render_template(
            "finance_v15e/audit.html",
            rows=rows,
            q=q,
            action=action,
            entity_type=entity_type,
            actions=actions,
            entities=entities,
            page=page,
            per_page=per_page,
            total=total,
            pages=pages,
            format_wib=_format_wib,
            section="audit",
        )

    @app.context_processor
    def _finance_v15e_context():
        context: dict[str, Any] = {
            "finance_teacher_allowed": False,
            "finance_teacher_can_download": False,
            "guardian_finance_unpaid_count": 0,
            "guardian_finance_bills": [],
            "guardian_finance_summary": None,
            "student_finance_summary_v15e": None,
        }
        try:
            if not current_user.is_authenticated:
                return context
            role = getattr(current_user, "role", "")
            if role == "guru":
                permission = _permission_for(current_user.id)
                context["finance_teacher_allowed"] = bool(permission and permission.can_view_class_status)
                context["finance_teacher_can_download"] = bool(permission and permission.can_download_class_report)
            if not current_user.is_admin:
                student = selected_guardian_student()
                if student:
                    summary = _student_summary(student.id)
                    bills = FinanceBill.query.filter_by(
                        santri_id=student.id, is_archived=False
                    ).order_by(FinanceBill.updated_at.desc(), FinanceBill.id.desc()).limit(6).all()
                    charge_map = _student_maps(bills)
                    context.update(
                        guardian_finance_unpaid_count=summary["unpaid_count"],
                        guardian_finance_summary=summary,
                        guardian_finance_bills=[
                            {"bill": row, "charge": charge_map.get(row.charge_type_id)} for row in bills
                        ],
                    )
            if request.endpoint == "student_detail" and request.view_args and request.view_args.get("student_id"):
                context["student_finance_summary_v15e"] = _student_summary(int(request.view_args["student_id"]))
        except Exception:
            app.logger.exception("Gagal memuat konteks integrasi Keuangan V15-E")
        return context

    app.extensions["finance_integration_v15e"] = {
        "models": {"access_permission": FinanceAccessPermission},
        "version": "V15-E",
    }
    return app.extensions["finance_integration_v15e"]
