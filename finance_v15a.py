"""Fondasi Pengaturan Keuangan V15-A untuk Portal TPQ HMarisa.

Modul ini sengaja terisolasi dari transaksi Iuran lama. V15-A hanya menambah
master konfigurasi: umum, tagihan, kanal pembayaran, WhatsApp, dan bukti
pembayaran. Seluruh tabel baru bersifat aditif dan tidak mengubah data lama.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import abort, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user
from sqlalchemy import UniqueConstraint
from werkzeug.utils import secure_filename

try:
    from PIL import Image
except ImportError:  # pragma: no cover - diverifikasi oleh requirements portal
    Image = None


ACADEMIC_YEAR_RE = re.compile(r"^\d{4}/\d{4}$")
PHONE_RE = re.compile(r"^62\d{8,13}$")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_SETTINGS_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_REMINDER_TEMPLATE = (
    "Assalamu’alaikum Ayah/Bunda.\n"
    "Kami mengingatkan bahwa administrasi iuran ananda {nama_santri} untuk "
    "{jenis_tagihan} periode {periode} masih belum tercatat lunas.\n"
    "Total tagihan: {nominal}\nSudah dibayar: {dibayar}\nSisa: {sisa}\n"
    "Apabila sudah melakukan pembayaran, mohon abaikan pesan ini atau kirimkan "
    "bukti pembayaran kepada admin.\nJazakumullahu khairan."
)


def install_finance_v15a(app, db, namespace: dict[str, Any]):
    """Daftarkan model dan route V15-A tanpa menimpa route keuangan lama."""
    if app.extensions.get("finance_v15a"):
        return app.extensions["finance_v15a"]

    superadmin_required = namespace["superadmin_required"]
    upload_root = Path(namespace.get("UPLOAD_DIR") or (Path(app.root_path) / "uploads"))
    settings_upload_dir = upload_root / "finance_settings"
    settings_upload_dir.mkdir(parents=True, exist_ok=True)

    class FinanceGeneralSetting(db.Model):
        __tablename__ = "finance_general_setting"
        id = db.Column(db.Integer, primary_key=True)
        academic_year_active = db.Column(db.String(20), nullable=False, default="2026/2027")
        semester_active = db.Column(db.String(20), nullable=False, default="Semester 1")
        tpq_name = db.Column(db.String(160), nullable=False, default="TPQ HMarisa")
        tpq_address = db.Column(db.Text, nullable=False, default="")
        logo_path = db.Column(db.String(255), nullable=False, default="")
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class FinanceBillingSetting(db.Model):
        __tablename__ = "finance_billing_setting"
        id = db.Column(db.Integer, primary_key=True)
        default_due_day = db.Column(db.Integer, nullable=False, default=10)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class FinanceChargeType(db.Model):
        __tablename__ = "finance_charge_type"
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(100), nullable=False)
        slug = db.Column(db.String(110), nullable=False, unique=True, index=True)
        default_amount = db.Column(db.Integer, nullable=False, default=0)
        due_day = db.Column(db.Integer)
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        archived_at = db.Column(db.DateTime)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class FinancePaymentChannel(db.Model):
        __tablename__ = "finance_payment_channel"
        id = db.Column(db.Integer, primary_key=True)
        channel_type = db.Column(db.String(20), nullable=False, default="bank")
        label = db.Column(db.String(120), nullable=False, default="")
        bank_name = db.Column(db.String(100), nullable=False, default="")
        account_number = db.Column(db.String(80), nullable=False, default="")
        account_holder = db.Column(db.String(160), nullable=False, default="")
        qris_path = db.Column(db.String(255), nullable=False, default="")
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        is_primary = db.Column(db.Boolean, nullable=False, default=False)
        show_on_receipt = db.Column(db.Boolean, nullable=False, default=False)
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        archived_at = db.Column(db.DateTime)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        __table_args__ = (
            UniqueConstraint("channel_type", "account_number", name="uq_finance_payment_channel_number"),
        )

    class FinanceWhatsAppSetting(db.Model):
        __tablename__ = "finance_whatsapp_setting"
        id = db.Column(db.Integer, primary_key=True)
        reminder_template = db.Column(db.Text, nullable=False, default=DEFAULT_REMINDER_TEMPLATE)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class FinanceWhatsAppContact(db.Model):
        __tablename__ = "finance_whatsapp_contact"
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(140), nullable=False)
        phone = db.Column(db.String(20), nullable=False, unique=True, index=True)
        position = db.Column(db.String(100), nullable=False, default="Admin")
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        is_primary = db.Column(db.Boolean, nullable=False, default=False)
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        archived_at = db.Column(db.DateTime)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class FinanceReceiptSetting(db.Model):
        __tablename__ = "finance_receipt_setting"
        id = db.Column(db.Integer, primary_key=True)
        treasurer_name = db.Column(db.String(140), nullable=False, default="")
        treasurer_position = db.Column(db.String(100), nullable=False, default="Bendahara TPQ")
        footer_note = db.Column(db.Text, nullable=False, default="")
        show_logo = db.Column(db.Boolean, nullable=False, default=True)
        show_qris = db.Column(db.Boolean, nullable=False, default=True)
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class FinanceAuditLog(db.Model):
        __tablename__ = "finance_audit_log"
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        user_name = db.Column(db.String(140), nullable=False, default="Sistem")
        action = db.Column(db.String(80), nullable=False)
        entity_type = db.Column(db.String(80), nullable=False)
        entity_id = db.Column(db.String(80), nullable=False, default="")
        before_json = db.Column(db.Text, nullable=False, default="{}")
        after_json = db.Column(db.Text, nullable=False, default="{}")
        ip_address = db.Column(db.String(80), nullable=False, default="")
        user_agent = db.Column(db.String(500), nullable=False, default="")
        request_id = db.Column(db.String(40), nullable=False, index=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def _slug(value: str) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
        return value.strip("-") or "tagihan"

    def _integer(value: Any, field: str, minimum: int = 0, maximum: int | None = None) -> int:
        try:
            result = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} harus berupa angka.") from exc
        if result < minimum or (maximum is not None and result > maximum):
            range_text = f"{minimum}–{maximum}" if maximum is not None else f"minimal {minimum}"
            raise ValueError(f"{field} harus {range_text}.")
        return result

    def _bool(name: str) -> bool:
        return request.form.get(name) in {"1", "true", "on", "yes"}

    def _normalize_phone(value: str) -> str:
        digits = re.sub(r"\D", "", value or "")
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
        elif digits.startswith("620"):
            digits = "62" + digits[3:]
        if not PHONE_RE.fullmatch(digits):
            raise ValueError("Nomor WhatsApp tidak valid. Gunakan nomor Indonesia yang aktif.")
        return digits

    def _record_dict(row, fields: tuple[str, ...]) -> dict[str, Any]:
        if row is None:
            return {}
        result = {}
        for field in fields:
            value = getattr(row, field, None)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[field] = value
        return result

    def _request_ip() -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",", 1)[0].strip() if forwarded else request.remote_addr or "")[:80]

    def _format_wib(value: datetime | None) -> str:
        if value is None:
            return "Belum diisi"
        return (value + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M WIB")

    def _audit(action: str, entity_type: str, entity_id: Any, before: dict, after: dict) -> None:
        log = FinanceAuditLog(
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
        )
        db.session.add(log)

    def _save_image(file_storage, prefix: str) -> str:
        if not file_storage or not file_storage.filename:
            return ""
        original = secure_filename(file_storage.filename)
        extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("File harus berupa PNG, JPG, JPEG, atau WEBP.")
        stream = file_storage.stream
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size <= 0 or size > MAX_SETTINGS_IMAGE_BYTES:
            raise ValueError("Ukuran gambar harus lebih dari 0 dan maksimal 5 MB.")
        if Image is not None:
            try:
                image = Image.open(stream)
                image.verify()
            except Exception as exc:
                raise ValueError("File gambar tidak valid atau rusak.") from exc
            finally:
                stream.seek(0)
        filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{extension}"
        file_storage.save(settings_upload_dir / filename)
        return filename

    def _ensure_defaults():
        changed = False
        general = db.session.get(FinanceGeneralSetting, 1)
        if general is None:
            general = FinanceGeneralSetting(id=1)
            db.session.add(general)
            changed = True
        billing = db.session.get(FinanceBillingSetting, 1)
        if billing is None:
            billing = FinanceBillingSetting(id=1)
            db.session.add(billing)
            changed = True
        whatsapp = db.session.get(FinanceWhatsAppSetting, 1)
        if whatsapp is None:
            whatsapp = FinanceWhatsAppSetting(id=1)
            db.session.add(whatsapp)
            changed = True
        receipt = db.session.get(FinanceReceiptSetting, 1)
        if receipt is None:
            receipt = FinanceReceiptSetting(id=1)
            db.session.add(receipt)
            changed = True
        if FinanceChargeType.query.count() == 0:
            defaults = [
                ("SPP", 50000), ("Pendaftaran", 0), ("Buku", 0),
                ("Seragam", 0), ("Ujian", 0), ("Kegiatan", 0), ("Lainnya", 0),
            ]
            for order, (name, amount) in enumerate(defaults, 1):
                db.session.add(FinanceChargeType(
                    name=name, slug=_slug(name), default_amount=amount,
                    due_day=None, sort_order=order, is_active=True,
                ))
            changed = True
        if changed:
            db.session.commit()
        return general, billing, whatsapp, receipt

    def _settings_context(section: str) -> dict[str, Any]:
        general, billing, whatsapp, receipt = _ensure_defaults()
        charge_types = FinanceChargeType.query.order_by(
            FinanceChargeType.sort_order, FinanceChargeType.name
        ).all()
        payment_channels = FinancePaymentChannel.query.order_by(
            FinancePaymentChannel.sort_order, FinancePaymentChannel.id
        ).all()
        contacts = FinanceWhatsAppContact.query.order_by(
            FinanceWhatsAppContact.sort_order, FinanceWhatsAppContact.id
        ).all()
        audit_logs = FinanceAuditLog.query.order_by(FinanceAuditLog.created_at.desc()).limit(12).all()
        return {
            "section": section,
            "general": general,
            "billing": billing,
            "whatsapp": whatsapp,
            "receipt": receipt,
            "charge_types": charge_types,
            "payment_channels": payment_channels,
            "contacts": contacts,
            "audit_logs": audit_logs,
            "format_wib": _format_wib,
        }

    @app.route("/finance/settings")
    @superadmin_required
    def finance_settings():
        return redirect(url_for("finance_settings_general"))

    @app.route("/finance/settings/general", methods=["GET", "POST"])
    @superadmin_required
    def finance_settings_general():
        general, _, _, _ = _ensure_defaults()
        if request.method == "POST":
            before = _record_dict(general, (
                "academic_year_active", "semester_active", "tpq_name", "tpq_address", "logo_path"
            ))
            try:
                academic_year = request.form.get("academic_year_active", "").strip()
                semester = request.form.get("semester_active", "").strip()
                tpq_name = request.form.get("tpq_name", "").strip()
                if not ACADEMIC_YEAR_RE.fullmatch(academic_year):
                    raise ValueError("Tahun ajaran harus menggunakan format 2026/2027.")
                first, second = map(int, academic_year.split("/"))
                if second != first + 1:
                    raise ValueError("Tahun kedua harus satu tahun setelah tahun pertama.")
                if semester not in {"Semester 1", "Semester 2"}:
                    raise ValueError("Semester aktif tidak valid.")
                if not tpq_name:
                    raise ValueError("Nama TPQ wajib diisi.")
                logo = _save_image(request.files.get("logo"), "logo")
                general.academic_year_active = academic_year
                general.semester_active = semester
                general.tpq_name = tpq_name[:160]
                general.tpq_address = request.form.get("tpq_address", "").strip()
                if logo:
                    general.logo_path = logo
                general.updated_by = current_user.id
                after = _record_dict(general, tuple(before.keys()))
                _audit("Mengubah pengaturan umum", "finance_general_setting", general.id, before, after)
                db.session.commit()
                flash("Pengaturan umum berhasil disimpan.", "success")
                return redirect(url_for("finance_settings_general"))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("finance_v15a/settings.html", **_settings_context("general"))

    @app.route("/finance/settings/billing", methods=["GET", "POST"])
    @superadmin_required
    def finance_settings_billing():
        _, billing, _, _ = _ensure_defaults()
        if request.method == "POST":
            action = request.form.get("action", "save_defaults")
            try:
                if action == "save_defaults":
                    spp = FinanceChargeType.query.filter_by(slug="spp").first()
                    if spp is None:
                        spp = FinanceChargeType(name="SPP", slug="spp", sort_order=1)
                        db.session.add(spp)
                        db.session.flush()
                    before = {
                        "default_due_day": billing.default_due_day,
                        "spp_default_amount": spp.default_amount,
                    }
                    billing.default_due_day = _integer(request.form.get("default_due_day"), "Jatuh tempo", 1, 31)
                    spp.default_amount = _integer(request.form.get("spp_amount"), "Nominal SPP", 0)
                    billing.updated_by = spp.updated_by = current_user.id
                    after = {
                        "default_due_day": billing.default_due_day,
                        "spp_default_amount": spp.default_amount,
                    }
                    _audit("Mengubah default tagihan", "finance_billing_setting", billing.id, before, after)
                elif action == "add_type":
                    name = request.form.get("name", "").strip()
                    if not name:
                        raise ValueError("Nama jenis tagihan wajib diisi.")
                    slug = _slug(name)
                    existing = FinanceChargeType.query.filter_by(slug=slug).first()
                    if existing:
                        raise ValueError("Jenis tagihan sudah tersedia. Aktifkan atau edit data yang sudah ada.")
                    row = FinanceChargeType(
                        name=name[:100], slug=slug,
                        default_amount=_integer(request.form.get("default_amount", 0), "Nominal default", 0),
                        due_day=_integer(request.form.get("due_day"), "Jatuh tempo", 1, 31)
                        if request.form.get("due_day", "").strip() else None,
                        sort_order=_integer(request.form.get("sort_order", 0), "Urutan", 0, 999),
                        is_active=True, updated_by=current_user.id,
                    )
                    db.session.add(row)
                    db.session.flush()
                    _audit("Menambah jenis tagihan", "finance_charge_type", row.id, {}, _record_dict(
                        row, ("name", "slug", "default_amount", "due_day", "is_active", "sort_order")
                    ))
                elif action == "update_type":
                    row = db.get_or_404(FinanceChargeType, _integer(request.form.get("type_id"), "ID jenis", 1))
                    before = _record_dict(row, ("name", "default_amount", "due_day", "is_active", "sort_order"))
                    name = request.form.get("name", "").strip()
                    if not name:
                        raise ValueError("Nama jenis tagihan wajib diisi.")
                    new_slug = _slug(name)
                    duplicate = FinanceChargeType.query.filter(
                        FinanceChargeType.slug == new_slug, FinanceChargeType.id != row.id
                    ).first()
                    if duplicate:
                        raise ValueError("Nama jenis tagihan sudah digunakan.")
                    row.name = name[:100]
                    row.slug = new_slug
                    row.default_amount = _integer(request.form.get("default_amount", 0), "Nominal default", 0)
                    row.due_day = (_integer(request.form.get("due_day"), "Jatuh tempo", 1, 31)
                                   if request.form.get("due_day", "").strip() else None)
                    row.sort_order = _integer(request.form.get("sort_order", 0), "Urutan", 0, 999)
                    row.updated_by = current_user.id
                    _audit("Mengubah jenis tagihan", "finance_charge_type", row.id, before, _record_dict(
                        row, tuple(before.keys())
                    ))
                elif action == "toggle_type":
                    row = db.get_or_404(FinanceChargeType, _integer(request.form.get("type_id"), "ID jenis", 1))
                    before = _record_dict(row, ("is_active", "archived_at"))
                    row.is_active = not row.is_active
                    row.archived_at = None if row.is_active else datetime.utcnow()
                    row.updated_by = current_user.id
                    _audit("Mengaktifkan jenis tagihan" if row.is_active else "Menonaktifkan jenis tagihan",
                           "finance_charge_type", row.id, before, _record_dict(row, tuple(before.keys())))
                else:
                    abort(400)
                db.session.commit()
                flash("Pengaturan tagihan berhasil diperbarui.", "success")
                return redirect(url_for("finance_settings_billing"))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("finance_v15a/settings.html", **_settings_context("billing"))

    @app.route("/finance/settings/payment", methods=["GET", "POST"])
    @superadmin_required
    def finance_settings_payment():
        _ensure_defaults()
        if request.method == "POST":
            action = request.form.get("action", "add_channel")
            try:
                if action == "add_channel":
                    channel_type = request.form.get("channel_type", "bank").strip()
                    if channel_type not in {"bank", "qris"}:
                        raise ValueError("Jenis kanal pembayaran tidak valid.")
                    label = request.form.get("label", "").strip()
                    bank_name = request.form.get("bank_name", "").strip()
                    account_number = re.sub(r"\s+", "", request.form.get("account_number", "").strip())
                    holder = request.form.get("account_holder", "").strip()
                    qris_path = ""
                    if channel_type == "bank":
                        if not bank_name or not account_number or not holder:
                            raise ValueError("Nama bank, nomor rekening, dan atas nama wajib diisi.")
                        if not re.fullmatch(r"[0-9A-Za-z.-]{3,80}", account_number):
                            raise ValueError("Nomor rekening mengandung karakter yang tidak valid.")
                        duplicate = FinancePaymentChannel.query.filter_by(
                            channel_type="bank", account_number=account_number
                        ).first()
                        if duplicate:
                            raise ValueError("Nomor rekening sudah tersedia. Edit data yang sudah ada.")
                        label = label or bank_name
                    else:
                        qris_path = _save_image(request.files.get("qris_image"), "qris")
                        if not qris_path:
                            raise ValueError("Gambar QRIS wajib diunggah.")
                        account_number = uuid.uuid4().hex
                        label = label or "QRIS TPQ HMarisa"
                    row = FinancePaymentChannel(
                        channel_type=channel_type, label=label[:120], bank_name=bank_name[:100],
                        account_number=account_number[:80], account_holder=holder[:160],
                        qris_path=qris_path, is_active=True,
                        is_primary=_bool("is_primary"), show_on_receipt=_bool("show_on_receipt"),
                        sort_order=_integer(request.form.get("sort_order", 0), "Urutan", 0, 999),
                        updated_by=current_user.id,
                    )
                    if row.is_primary:
                        FinancePaymentChannel.query.filter_by(channel_type=channel_type).update({"is_primary": False})
                    db.session.add(row)
                    db.session.flush()
                    _audit("Menambah kanal pembayaran", "finance_payment_channel", row.id, {}, _record_dict(
                        row, ("channel_type", "label", "bank_name", "account_number", "account_holder",
                              "qris_path", "is_active", "is_primary", "show_on_receipt", "sort_order")
                    ))
                elif action == "update_channel":
                    row = db.get_or_404(FinancePaymentChannel, _integer(request.form.get("channel_id"), "ID kanal", 1))
                    fields = ("label", "bank_name", "account_number", "account_holder", "qris_path",
                              "is_active", "is_primary", "show_on_receipt", "sort_order")
                    before = _record_dict(row, fields)
                    row.label = request.form.get("label", "").strip()[:120] or row.label
                    if row.channel_type == "bank":
                        bank_name = request.form.get("bank_name", "").strip()
                        account_number = re.sub(r"\s+", "", request.form.get("account_number", "").strip())
                        holder = request.form.get("account_holder", "").strip()
                        if not bank_name or not account_number or not holder:
                            raise ValueError("Nama bank, nomor rekening, dan atas nama wajib diisi.")
                        duplicate = FinancePaymentChannel.query.filter(
                            FinancePaymentChannel.channel_type == "bank",
                            FinancePaymentChannel.account_number == account_number,
                            FinancePaymentChannel.id != row.id,
                        ).first()
                        if duplicate:
                            raise ValueError("Nomor rekening sudah digunakan kanal lain.")
                        row.bank_name, row.account_number, row.account_holder = bank_name[:100], account_number[:80], holder[:160]
                    else:
                        new_qris = _save_image(request.files.get("qris_image"), "qris")
                        if new_qris:
                            row.qris_path = new_qris
                    row.is_active = _bool("is_active")
                    row.is_primary = _bool("is_primary") and row.is_active
                    row.show_on_receipt = _bool("show_on_receipt") and row.is_active
                    row.sort_order = _integer(request.form.get("sort_order", 0), "Urutan", 0, 999)
                    row.archived_at = None if row.is_active else datetime.utcnow()
                    row.updated_by = current_user.id
                    if row.is_primary:
                        FinancePaymentChannel.query.filter(
                            FinancePaymentChannel.channel_type == row.channel_type,
                            FinancePaymentChannel.id != row.id,
                        ).update({"is_primary": False})
                    _audit("Mengubah kanal pembayaran", "finance_payment_channel", row.id, before,
                           _record_dict(row, fields))
                elif action == "toggle_channel":
                    row = db.get_or_404(FinancePaymentChannel, _integer(request.form.get("channel_id"), "ID kanal", 1))
                    before = _record_dict(row, ("is_active", "is_primary", "show_on_receipt", "archived_at"))
                    row.is_active = not row.is_active
                    if not row.is_active:
                        row.is_primary = False
                        row.show_on_receipt = False
                        row.archived_at = datetime.utcnow()
                    else:
                        row.archived_at = None
                    row.updated_by = current_user.id
                    _audit("Mengaktifkan kanal pembayaran" if row.is_active else "Menonaktifkan kanal pembayaran",
                           "finance_payment_channel", row.id, before, _record_dict(row, tuple(before.keys())))
                else:
                    abort(400)
                db.session.commit()
                flash("Informasi pembayaran berhasil diperbarui.", "success")
                return redirect(url_for("finance_settings_payment"))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("finance_v15a/settings.html", **_settings_context("payment"))

    @app.route("/finance/settings/whatsapp", methods=["GET", "POST"])
    @superadmin_required
    def finance_settings_whatsapp():
        _, _, whatsapp, _ = _ensure_defaults()
        if request.method == "POST":
            action = request.form.get("action", "save_template")
            try:
                if action == "save_template":
                    before = {"reminder_template": whatsapp.reminder_template}
                    template = request.form.get("reminder_template", "").strip()
                    if not template:
                        raise ValueError("Template WhatsApp wajib diisi.")
                    whatsapp.reminder_template = template
                    whatsapp.updated_by = current_user.id
                    _audit("Mengubah template WhatsApp", "finance_whatsapp_setting", whatsapp.id,
                           before, {"reminder_template": template})
                elif action == "add_contact":
                    phone = _normalize_phone(request.form.get("phone", ""))
                    if FinanceWhatsAppContact.query.filter_by(phone=phone).first():
                        raise ValueError("Nomor WhatsApp sudah terdaftar. Edit kontak yang sudah ada.")
                    row = FinanceWhatsAppContact(
                        name=request.form.get("name", "").strip()[:140], phone=phone,
                        position=request.form.get("position", "Admin").strip()[:100] or "Admin",
                        is_active=True, is_primary=_bool("is_primary"),
                        sort_order=_integer(request.form.get("sort_order", 0), "Urutan", 0, 999),
                        updated_by=current_user.id,
                    )
                    if not row.name:
                        raise ValueError("Nama admin wajib diisi.")
                    if row.is_primary:
                        FinanceWhatsAppContact.query.update({"is_primary": False})
                    db.session.add(row)
                    db.session.flush()
                    _audit("Menambah kontak WhatsApp", "finance_whatsapp_contact", row.id, {}, _record_dict(
                        row, ("name", "phone", "position", "is_active", "is_primary", "sort_order")
                    ))
                elif action == "update_contact":
                    row = db.get_or_404(FinanceWhatsAppContact, _integer(request.form.get("contact_id"), "ID kontak", 1))
                    fields = ("name", "phone", "position", "is_active", "is_primary", "sort_order")
                    before = _record_dict(row, fields)
                    phone = _normalize_phone(request.form.get("phone", ""))
                    duplicate = FinanceWhatsAppContact.query.filter(
                        FinanceWhatsAppContact.phone == phone, FinanceWhatsAppContact.id != row.id
                    ).first()
                    if duplicate:
                        raise ValueError("Nomor WhatsApp sudah digunakan kontak lain.")
                    name = request.form.get("name", "").strip()
                    if not name:
                        raise ValueError("Nama admin wajib diisi.")
                    row.name, row.phone = name[:140], phone
                    row.position = request.form.get("position", "Admin").strip()[:100] or "Admin"
                    row.is_active = _bool("is_active")
                    row.is_primary = _bool("is_primary") and row.is_active
                    row.sort_order = _integer(request.form.get("sort_order", 0), "Urutan", 0, 999)
                    row.archived_at = None if row.is_active else datetime.utcnow()
                    row.updated_by = current_user.id
                    if row.is_primary:
                        FinanceWhatsAppContact.query.filter(FinanceWhatsAppContact.id != row.id).update({"is_primary": False})
                    _audit("Mengubah kontak WhatsApp", "finance_whatsapp_contact", row.id, before,
                           _record_dict(row, fields))
                elif action == "toggle_contact":
                    row = db.get_or_404(FinanceWhatsAppContact, _integer(request.form.get("contact_id"), "ID kontak", 1))
                    before = _record_dict(row, ("is_active", "is_primary", "archived_at"))
                    row.is_active = not row.is_active
                    if not row.is_active:
                        row.is_primary = False
                        row.archived_at = datetime.utcnow()
                    else:
                        row.archived_at = None
                    row.updated_by = current_user.id
                    _audit("Mengaktifkan kontak WhatsApp" if row.is_active else "Menonaktifkan kontak WhatsApp",
                           "finance_whatsapp_contact", row.id, before, _record_dict(row, tuple(before.keys())))
                else:
                    abort(400)
                db.session.commit()
                flash("Pengaturan WhatsApp berhasil diperbarui.", "success")
                return redirect(url_for("finance_settings_whatsapp"))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("finance_v15a/settings.html", **_settings_context("whatsapp"))

    @app.route("/finance/settings/receipt", methods=["GET", "POST"])
    @superadmin_required
    def finance_settings_receipt():
        _, _, _, receipt = _ensure_defaults()
        if request.method == "POST":
            before = _record_dict(receipt, ("treasurer_name", "treasurer_position", "footer_note", "show_logo", "show_qris"))
            channel_before = {
                str(row.id): row.show_on_receipt for row in FinancePaymentChannel.query.all()
            }
            try:
                receipt.treasurer_name = request.form.get("treasurer_name", "").strip()[:140]
                receipt.treasurer_position = request.form.get("treasurer_position", "Bendahara TPQ").strip()[:100] or "Bendahara TPQ"
                receipt.footer_note = request.form.get("footer_note", "").strip()
                receipt.show_logo = _bool("show_logo")
                receipt.show_qris = _bool("show_qris")
                receipt.updated_by = current_user.id
                selected_ids = {
                    int(value) for value in request.form.getlist("receipt_channel_ids") if str(value).isdigit()
                }
                channels = FinancePaymentChannel.query.all()
                for channel in channels:
                    channel.show_on_receipt = channel.is_active and channel.id in selected_ids
                    channel.updated_by = current_user.id
                after = _record_dict(receipt, tuple(before.keys()))
                after["selected_channel_ids"] = sorted(selected_ids)
                before["selected_channels"] = channel_before
                _audit("Mengubah pengaturan bukti pembayaran", "finance_receipt_setting", receipt.id, before, after)
                db.session.commit()
                flash("Pengaturan bukti pembayaran berhasil disimpan.", "success")
                return redirect(url_for("finance_settings_receipt"))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("finance_v15a/settings.html", **_settings_context("receipt"))

    @app.route("/finance/settings/asset/<path:filename>")
    @superadmin_required
    def finance_settings_asset(filename):
        safe = secure_filename(filename)
        if not safe or safe != filename:
            abort(404)
        return send_from_directory(settings_upload_dir, safe)

    app.extensions["finance_v15a"] = {
        "models": {
            "general": FinanceGeneralSetting,
            "billing": FinanceBillingSetting,
            "charge_type": FinanceChargeType,
            "payment_channel": FinancePaymentChannel,
            "whatsapp_setting": FinanceWhatsAppSetting,
            "whatsapp_contact": FinanceWhatsAppContact,
            "receipt": FinanceReceiptSetting,
            "audit": FinanceAuditLog,
        },
        "ensure_defaults": _ensure_defaults,
        "normalize_phone": _normalize_phone,
        "version": "V15-A",
    }
    return app.extensions["finance_v15a"]
