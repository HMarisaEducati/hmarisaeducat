"""Pusat Kendali Portal TPQ HMarisa V17.

Builder aman untuk halaman, formulir, konten, menu dinamis, media,
kontak WhatsApp, dan rekening. Admin Utama mengelola semuanya melalui
Draft -> Preview -> Terbitkan tanpa menjalankan Python/SQL/JS/CSS bebas.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import abort, flash, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PHONE_RE = re.compile(r"^62\d{8,13}$")
ALLOWED_ROLES = {"admin_utama", "admin", "bendahara", "guru", "guardian"}
ALLOWED_SCOPES = {"admin", "guardian", "public", "both"}
ALLOWED_BLOCKS = {"heading", "text", "banner", "image", "button", "cards", "list", "announcement", "contact", "form"}
ALLOWED_FIELDS = {"text", "textarea", "number", "date", "email", "phone", "select", "radio", "checkbox", "file", "class", "consent"}
ALLOWED_CONTENT_TYPES = {"announcement", "banner", "monthly_achievement", "contact", "custom"}
ALLOWED_MEDIA_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf", "doc", "docx", "xlsx"}
MAX_MEDIA_BYTES = 10 * 1024 * 1024

ICON_OPTIONS = {
    "file-lines": "fa-file-lines", "file-pen": "fa-file-pen", "clipboard-list": "fa-clipboard-list",
    "bullhorn": "fa-bullhorn", "image": "fa-image", "star": "fa-star", "award": "fa-award",
    "phone": "fa-phone", "whatsapp": "fa-whatsapp", "wallet": "fa-wallet", "building-columns": "fa-building-columns",
    "user-plus": "fa-user-plus", "calendar": "fa-calendar", "book-open": "fa-book-open", "house": "fa-house",
    "link": "fa-link", "circle-info": "fa-circle-info", "mosque": "fa-mosque", "children": "fa-children",
}

REGISTRATION_FIELDS = [
    {"name": "nama_santri", "label": "Nama Lengkap Santri", "type": "text", "required": True, "options": [], "help": "Sesuai dokumen resmi."},
    {"name": "nama_panggilan", "label": "Nama Panggilan", "type": "text", "required": False, "options": [], "help": ""},
    {"name": "tempat_lahir", "label": "Tempat Lahir", "type": "text", "required": True, "options": [], "help": ""},
    {"name": "tanggal_lahir", "label": "Tanggal Lahir", "type": "date", "required": True, "options": [], "help": ""},
    {"name": "jenis_kelamin", "label": "Jenis Kelamin", "type": "radio", "required": True, "options": ["Laki-laki", "Perempuan"], "help": ""},
    {"name": "nama_wali", "label": "Nama Orang Tua/Wali", "type": "text", "required": True, "options": [], "help": ""},
    {"name": "nomor_wa", "label": "Nomor WhatsApp", "type": "phone", "required": True, "options": [], "help": "Contoh: 081234567890"},
    {"name": "alamat", "label": "Alamat", "type": "textarea", "required": True, "options": [], "help": ""},
    {"name": "pilihan_kelas", "label": "Pilihan Kelas", "type": "class", "required": True, "options": [], "help": ""},
    {"name": "foto", "label": "Foto Santri", "type": "file", "required": False, "options": [], "help": "PNG/JPG maksimal 5 MB."},
    {"name": "akta", "label": "Akta Kelahiran/Kartu Keluarga", "type": "file", "required": False, "options": [], "help": "PDF/JPG maksimal 10 MB."},
    {"name": "persetujuan", "label": "Saya menyatakan data yang diisi benar", "type": "consent", "required": True, "options": [], "help": ""},
]


def install_portal_control_v17(app, db, namespace: dict[str, Any]):
    if app.extensions.get("portal_control_v17"):
        return app.extensions["portal_control_v17"]

    superadmin_required = namespace["superadmin_required"]
    login_required = namespace.get("login_required")
    User = namespace.get("User")
    Santri = namespace.get("Santri")
    CLASSES = namespace.get("CLASSES", ["Ar Rahman", "Ar Rahim", "Al-Bayyan"])
    upload_root = Path(namespace.get("UPLOAD_DIR") or (Path(app.root_path) / "uploads"))
    media_root = upload_root / "portal_control_v17"
    submission_root = media_root / "submissions"
    media_root.mkdir(parents=True, exist_ok=True)
    submission_root.mkdir(parents=True, exist_ok=True)

    class ControlPage(db.Model):
        __tablename__ = "portal_control_page_v17"
        id = db.Column(db.Integer, primary_key=True)
        slug = db.Column(db.String(140), nullable=False, unique=True, index=True)
        title = db.Column(db.String(180), nullable=False)
        target_scope = db.Column(db.String(20), nullable=False, default="guardian", index=True)
        menu_label = db.Column(db.String(100), nullable=False, default="")
        menu_icon = db.Column(db.String(60), nullable=False, default="fa-file-lines")
        show_in_menu = db.Column(db.Boolean, nullable=False, default=False)
        sort_order = db.Column(db.Integer, nullable=False, default=100)
        roles_json = db.Column(db.Text, nullable=False, default="[]")
        draft_json = db.Column(db.Text, nullable=False, default="[]")
        published_json = db.Column(db.Text, nullable=False, default="[]")
        status = db.Column(db.String(20), nullable=False, default="draft", index=True)
        version_no = db.Column(db.Integer, nullable=False, default=0)
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        published_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        published_at = db.Column(db.DateTime)
        archived_at = db.Column(db.DateTime)

        def blocks(self, published: bool = False):
            return _json_list(self.published_json if published else self.draft_json)

        def roles(self):
            values = _json_list(self.roles_json)
            return [v for v in values if v in ALLOWED_ROLES]

    class ControlForm(db.Model):
        __tablename__ = "portal_control_form_v17"
        id = db.Column(db.Integer, primary_key=True)
        slug = db.Column(db.String(140), nullable=False, unique=True, index=True)
        title = db.Column(db.String(180), nullable=False)
        description = db.Column(db.Text, nullable=False, default="")
        target_scope = db.Column(db.String(20), nullable=False, default="public", index=True)
        menu_label = db.Column(db.String(100), nullable=False, default="")
        menu_icon = db.Column(db.String(60), nullable=False, default="fa-clipboard-list")
        show_in_menu = db.Column(db.Boolean, nullable=False, default=False)
        sort_order = db.Column(db.Integer, nullable=False, default=100)
        roles_json = db.Column(db.Text, nullable=False, default="[]")
        fields_draft_json = db.Column(db.Text, nullable=False, default="[]")
        fields_published_json = db.Column(db.Text, nullable=False, default="[]")
        settings_json = db.Column(db.Text, nullable=False, default="{}")
        workflow_json = db.Column(db.Text, nullable=False, default="{}")
        status = db.Column(db.String(20), nullable=False, default="draft", index=True)
        version_no = db.Column(db.Integer, nullable=False, default=0)
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        published_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        published_at = db.Column(db.DateTime)
        archived_at = db.Column(db.DateTime)

        def fields(self, published: bool = False):
            return _json_list(self.fields_published_json if published else self.fields_draft_json)

        def settings(self):
            return _json_dict(self.settings_json)

        def workflow(self):
            return _json_dict(self.workflow_json)

        def roles(self):
            return [v for v in _json_list(self.roles_json) if v in ALLOWED_ROLES]

    class ControlSubmission(db.Model):
        __tablename__ = "portal_control_submission_v17"
        id = db.Column(db.Integer, primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey("portal_control_form_v17.id"), nullable=False, index=True)
        reference_no = db.Column(db.String(60), nullable=False, unique=True, index=True)
        status = db.Column(db.String(40), nullable=False, default="Menunggu Verifikasi", index=True)
        data_json = db.Column(db.Text, nullable=False, default="{}")
        files_json = db.Column(db.Text, nullable=False, default="{}")
        submitter_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        student_id = db.Column(db.Integer, db.ForeignKey("santri.id"))
        admin_note = db.Column(db.Text, nullable=False, default="")
        reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
        reviewed_at = db.Column(db.DateTime)
        ip_address = db.Column(db.String(80), nullable=False, default="")
        user_agent = db.Column(db.String(300), nullable=False, default="")

        def data(self):
            return _json_dict(self.data_json)

        def files(self):
            return _json_dict(self.files_json)

    class ControlContent(db.Model):
        __tablename__ = "portal_control_content_v17"
        id = db.Column(db.Integer, primary_key=True)
        key = db.Column(db.String(140), nullable=False, unique=True, index=True)
        content_type = db.Column(db.String(40), nullable=False, default="announcement", index=True)
        target_scope = db.Column(db.String(20), nullable=False, default="both", index=True)
        title = db.Column(db.String(180), nullable=False)
        draft_json = db.Column(db.Text, nullable=False, default="{}")
        published_json = db.Column(db.Text, nullable=False, default="{}")
        status = db.Column(db.String(20), nullable=False, default="draft", index=True)
        sort_order = db.Column(db.Integer, nullable=False, default=100)
        start_at = db.Column(db.DateTime)
        end_at = db.Column(db.DateTime)
        version_no = db.Column(db.Integer, nullable=False, default=0)
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        published_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        published_at = db.Column(db.DateTime)
        archived_at = db.Column(db.DateTime)

        def data(self, published: bool = False):
            return _json_dict(self.published_json if published else self.draft_json)

    class ControlMedia(db.Model):
        __tablename__ = "portal_control_media_v17"
        id = db.Column(db.Integer, primary_key=True)
        filename = db.Column(db.String(255), nullable=False, unique=True)
        original_name = db.Column(db.String(255), nullable=False)
        mime_type = db.Column(db.String(100), nullable=False, default="")
        size_bytes = db.Column(db.Integer, nullable=False, default=0)
        alt_text = db.Column(db.String(180), nullable=False, default="")
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        archived_at = db.Column(db.DateTime)

    class ControlRevision(db.Model):
        __tablename__ = "portal_control_revision_v17"
        id = db.Column(db.Integer, primary_key=True)
        entity_type = db.Column(db.String(40), nullable=False, index=True)
        entity_id = db.Column(db.Integer, nullable=False, index=True)
        version_no = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False, default="{}")
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    class ControlAudit(db.Model):
        __tablename__ = "portal_control_audit_v17"
        id = db.Column(db.Integer, primary_key=True)
        entity_type = db.Column(db.String(50), nullable=False, index=True)
        entity_id = db.Column(db.String(80), nullable=False, default="")
        action = db.Column(db.String(100), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        user_name = db.Column(db.String(160), nullable=False, default="Sistem")
        before_json = db.Column(db.Text, nullable=False, default="{}")
        after_json = db.Column(db.Text, nullable=False, default="{}")
        reason = db.Column(db.Text, nullable=False, default="")
        ip_address = db.Column(db.String(80), nullable=False, default="")
        user_agent = db.Column(db.String(300), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def _json_list(raw: str | None) -> list:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except (ValueError, TypeError, json.JSONDecodeError):
            return []

    def _json_dict(raw: str | None) -> dict:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _slug(value: str) -> str:
        result = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
        if not result or not SLUG_RE.fullmatch(result):
            raise ValueError("Slug hanya boleh berisi huruf kecil, angka, dan tanda hubung.")
        return result[:140]

    def _bool(name: str) -> bool:
        return request.form.get(name) in {"1", "true", "on", "yes"}

    def _integer(value: Any, default: int = 0, minimum: int = 0, maximum: int = 9999) -> int:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    def _normalize_phone(value: str) -> str:
        finance = app.extensions.get("finance_v15a", {})
        normalizer = finance.get("normalize_phone")
        if normalizer:
            return normalizer(value)
        digits = re.sub(r"\D", "", value or "")
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
        if not PHONE_RE.fullmatch(digits):
            raise ValueError("Nomor WhatsApp tidak valid.")
        return digits

    def _clean_url(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if value.startswith("/") and not value.startswith("//"):
            return value[:500]
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value[:500]
        raise ValueError("Tautan harus berupa alamat internal /... atau URL http/https.")

    def _clean_blocks(raw: str) -> list[dict[str, Any]]:
        rows = _json_list(raw)
        cleaned = []
        for index, row in enumerate(rows[:60]):
            if not isinstance(row, dict):
                continue
            kind = str(row.get("type", "text")).strip()
            if kind not in ALLOWED_BLOCKS:
                continue
            item = {
                "id": str(row.get("id") or uuid.uuid4().hex[:10]),
                "type": kind,
                "title": str(row.get("title", ""))[:180],
                "body": str(row.get("body", ""))[:8000],
                "link_label": str(row.get("link_label", ""))[:100],
                "link_url": _clean_url(str(row.get("link_url", ""))) if row.get("link_url") else "",
                "image": str(row.get("image", ""))[:255],
                "form_slug": str(row.get("form_slug", ""))[:140],
                "style": str(row.get("style", "default"))[:40],
                "order": index,
            }
            cleaned.append(item)
        return cleaned

    def _clean_fields(raw: str) -> list[dict[str, Any]]:
        rows = _json_list(raw)
        cleaned, names = [], set()
        for row in rows[:80]:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("type", "text"))
            if kind not in ALLOWED_FIELDS:
                continue
            name = re.sub(r"[^a-z0-9_]+", "_", str(row.get("name", "")).strip().lower()).strip("_")[:80]
            label = str(row.get("label", "")).strip()[:180]
            if not name or not label or name in names:
                continue
            names.add(name)
            options = row.get("options", [])
            if isinstance(options, str):
                options = [x.strip() for x in options.split("\n") if x.strip()]
            if not isinstance(options, list):
                options = []
            cleaned.append({
                "name": name,
                "label": label,
                "type": kind,
                "required": bool(row.get("required")),
                "options": [str(x)[:120] for x in options[:100]],
                "help": str(row.get("help", ""))[:500],
            })
        if not cleaned:
            raise ValueError("Formulir harus memiliki minimal satu kolom.")
        return cleaned

    def _request_ip() -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",", 1)[0].strip() if forwarded else request.remote_addr or "")[:80]

    def _audit(action: str, entity_type: str, entity_id: Any, before: Any = None, after: Any = None, reason: str = ""):
        db.session.add(ControlAudit(
            entity_type=entity_type,
            entity_id=str(entity_id or ""),
            action=action,
            user_id=getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None,
            user_name=(getattr(current_user, "full_name", "Sistem") or "Sistem") if getattr(current_user, "is_authenticated", False) else "Sistem",
            before_json=json.dumps(before or {}, ensure_ascii=False, default=str),
            after_json=json.dumps(after or {}, ensure_ascii=False, default=str),
            reason=(reason or "")[:2000],
            ip_address=_request_ip(),
            user_agent=(request.headers.get("User-Agent", "") or "")[:300],
        ))

    def _snapshot(entity_type: str, entity_id: int, version_no: int, payload: dict):
        db.session.add(ControlRevision(
            entity_type=entity_type,
            entity_id=entity_id,
            version_no=version_no,
            snapshot_json=json.dumps(payload, ensure_ascii=False, default=str),
            created_by=getattr(current_user, "id", None),
        ))

    def _row_snapshot(row, entity_type: str) -> dict:
        if entity_type == "page":
            return {"title": row.title, "slug": row.slug, "scope": row.target_scope, "menu_label": row.menu_label,
                    "menu_icon": row.menu_icon, "show_in_menu": row.show_in_menu, "sort_order": row.sort_order,
                    "roles": row.roles(), "blocks": row.blocks(True)}
        if entity_type == "form":
            return {"title": row.title, "slug": row.slug, "description": row.description, "scope": row.target_scope,
                    "menu_label": row.menu_label, "menu_icon": row.menu_icon, "show_in_menu": row.show_in_menu,
                    "sort_order": row.sort_order, "roles": row.roles(), "fields": row.fields(True),
                    "settings": row.settings(), "workflow": row.workflow()}
        return {"key": row.key, "title": row.title, "type": row.content_type, "scope": row.target_scope, "data": row.data(True)}

    def _save_media(file_storage, alt_text: str = "") -> ControlMedia:
        if not file_storage or not file_storage.filename:
            raise ValueError("Pilih file terlebih dahulu.")
        original = secure_filename(file_storage.filename)
        ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if ext not in ALLOWED_MEDIA_EXTENSIONS:
            raise ValueError("Tipe file tidak diizinkan.")
        stream = file_storage.stream
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size <= 0 or size > MAX_MEDIA_BYTES:
            raise ValueError("Ukuran file maksimal 10 MB.")
        if ext in {"png", "jpg", "jpeg", "webp"} and Image is not None:
            try:
                img = Image.open(stream)
                img.verify()
            except Exception as exc:
                raise ValueError("File gambar rusak atau tidak valid.") from exc
            finally:
                stream.seek(0)
        filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}.{ext}"
        file_storage.save(media_root / filename)
        row = ControlMedia(filename=filename, original_name=original[:255], mime_type=file_storage.mimetype or "",
                           size_bytes=size, alt_text=(alt_text or "")[:180], created_by=getattr(current_user, "id", None))
        db.session.add(row)
        db.session.flush()
        return row

    def _scope_allowed(scope: str, roles: list[str] | None = None) -> bool:
        if scope == "public":
            return True
        if not getattr(current_user, "is_authenticated", False):
            return False
        role = getattr(current_user, "role", "guardian")
        if roles and role not in roles and role != "admin_utama":
            return False
        if scope == "admin":
            return bool(getattr(current_user, "is_admin", False))
        if scope == "guardian":
            return role == "guardian" or not getattr(current_user, "is_admin", False)
        return True

    def _published_content(scope: str) -> list[ControlContent]:
        now = datetime.utcnow()
        query = ControlContent.query.filter_by(status="published").filter(ControlContent.archived_at.is_(None))
        rows = query.order_by(ControlContent.sort_order, ControlContent.id).all()
        result = []
        for row in rows:
            if row.target_scope not in {scope, "both"}:
                continue
            if row.start_at and row.start_at > now:
                continue
            if row.end_at and row.end_at < now:
                continue
            result.append(row)
        return result

    def _menu_items(scope: str) -> list[dict[str, Any]]:
        role = getattr(current_user, "role", "guardian") if getattr(current_user, "is_authenticated", False) else "public"
        items = []
        for row in ControlPage.query.filter_by(status="published", show_in_menu=True).filter(ControlPage.archived_at.is_(None)).all():
            if row.target_scope not in {scope, "both"} or (row.roles() and role not in row.roles() and role != "admin_utama"):
                continue
            items.append({"kind": "page", "label": row.menu_label or row.title, "icon": row.menu_icon, "order": row.sort_order,
                          "url": url_for("portal_page_view_v17", slug=row.slug)})
        for row in ControlForm.query.filter_by(status="published", show_in_menu=True).filter(ControlForm.archived_at.is_(None)).all():
            if row.target_scope not in {scope, "both", "public"} or (row.roles() and role not in row.roles() and role != "admin_utama"):
                continue
            items.append({"kind": "form", "label": row.menu_label or row.title, "icon": row.menu_icon, "order": row.sort_order,
                          "url": url_for("portal_form_view_v17", slug=row.slug)})
        return sorted(items, key=lambda x: (x["order"], x["label"].lower()))

    def _render_page_context(row: ControlPage, preview: bool = False):
        blocks = row.blocks(False if preview else True)
        form_map = {f.slug: f for f in ControlForm.query.filter(ControlForm.archived_at.is_(None)).all()}
        return {"page": row, "blocks": blocks, "form_map": form_map, "preview_mode": preview,
                "portal_v17_media_url": lambda filename: url_for("portal_media_file_v17", filename=filename)}

    def _ensure_seed():
        changed = False
        if ControlForm.query.filter_by(slug="pendaftaran-santri-baru").first() is None:
            settings = {"success_title": "Pendaftaran berhasil dikirim", "success_message": "Data akan diperiksa oleh Admin TPQ HMarisa.",
                        "preset": "student_registration", "accepting": True, "quota": 0}
            workflow = {"reference_number": True, "admin_notification": True, "whatsapp_confirmation": False}
            row = ControlForm(slug="pendaftaran-santri-baru", title="Pendaftaran Santri Baru",
                              description="Formulir pendaftaran calon santri TPQ HMarisa.", target_scope="public",
                              menu_label="Pendaftaran Santri Baru", menu_icon="fa-user-plus", show_in_menu=False,
                              fields_draft_json=json.dumps(REGISTRATION_FIELDS, ensure_ascii=False),
                              fields_published_json="[]", settings_json=json.dumps(settings, ensure_ascii=False),
                              workflow_json=json.dumps(workflow, ensure_ascii=False), status="draft")
            db.session.add(row)
            changed = True
        if changed:
            db.session.commit()

    # ---------- Dashboard ----------
    @app.route("/admin/control")
    @superadmin_required
    def portal_control_dashboard_v17():
        counts = {
            "pages": ControlPage.query.filter(ControlPage.archived_at.is_(None)).count(),
            "forms": ControlForm.query.filter(ControlForm.archived_at.is_(None)).count(),
            "submissions": ControlSubmission.query.count(),
            "waiting": ControlSubmission.query.filter_by(status="Menunggu Verifikasi").count(),
            "contents": ControlContent.query.filter(ControlContent.archived_at.is_(None)).count(),
            "media": ControlMedia.query.filter(ControlMedia.archived_at.is_(None)).count(),
        }
        recent = ControlAudit.query.order_by(ControlAudit.id.desc()).limit(10).all()
        return render_template("portal_control_v17/dashboard.html", counts=counts, recent=recent)

    # ---------- Pages ----------
    @app.route("/admin/control/pages")
    @superadmin_required
    def portal_control_pages_v17():
        rows = ControlPage.query.order_by(ControlPage.archived_at.isnot(None), ControlPage.sort_order, ControlPage.title).all()
        return render_template("portal_control_v17/pages.html", rows=rows)

    @app.route("/admin/control/pages/new", methods=["GET", "POST"])
    @app.route("/admin/control/pages/<int:page_id>/edit", methods=["GET", "POST"])
    @superadmin_required
    def portal_control_page_edit_v17(page_id: int | None = None):
        row = db.session.get(ControlPage, page_id) if page_id else None
        if page_id and not row:
            abort(404)
        if request.method == "POST":
            before = _row_snapshot(row, "page") if row else {}
            try:
                title = request.form.get("title", "").strip()[:180]
                if not title:
                    raise ValueError("Judul halaman wajib diisi.")
                slug = _slug(request.form.get("slug") or title)
                duplicate = ControlPage.query.filter_by(slug=slug).first()
                if duplicate and (row is None or duplicate.id != row.id):
                    raise ValueError("Slug halaman sudah digunakan.")
                scope = request.form.get("target_scope", "guardian")
                if scope not in ALLOWED_SCOPES:
                    raise ValueError("Target portal tidak valid.")
                blocks = _clean_blocks(request.form.get("blocks_json", "[]"))
                if row is None:
                    row = ControlPage(slug=slug, title=title, created_by=current_user.id)
                    db.session.add(row)
                row.slug, row.title, row.target_scope = slug, title, scope
                row.menu_label = request.form.get("menu_label", "").strip()[:100]
                row.menu_icon = request.form.get("menu_icon", "fa-file-lines") if request.form.get("menu_icon") in ICON_OPTIONS.values() else "fa-file-lines"
                row.show_in_menu = _bool("show_in_menu")
                row.sort_order = _integer(request.form.get("sort_order"), 100)
                row.roles_json = json.dumps([r for r in request.form.getlist("roles") if r in ALLOWED_ROLES])
                row.draft_json = json.dumps(blocks, ensure_ascii=False)
                row.status = "draft" if row.status != "published" else "published"
                row.updated_by = current_user.id
                db.session.flush()
                _audit("Menyimpan draft halaman", "page", row.id, before, _row_snapshot(row, "page"))
                db.session.commit()
                flash("Draft halaman berhasil disimpan.", "success")
                return redirect(url_for("portal_control_page_edit_v17", page_id=row.id))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("portal_control_v17/page_edit.html", row=row, blocks=(row.blocks() if row else []),
                               icons=ICON_OPTIONS, roles=sorted(ALLOWED_ROLES), scopes=sorted(ALLOWED_SCOPES),
                               forms=ControlForm.query.filter(ControlForm.archived_at.is_(None)).order_by(ControlForm.title).all(),
                               media=ControlMedia.query.filter(ControlMedia.archived_at.is_(None)).order_by(ControlMedia.id.desc()).all())

    @app.route("/admin/control/pages/<int:page_id>/preview")
    @superadmin_required
    def portal_control_page_preview_v17(page_id: int):
        row = db.session.get(ControlPage, page_id) or abort(404)
        return render_template("portal_control_v17/page_preview.html", **_render_page_context(row, preview=True))

    @app.post("/admin/control/pages/<int:page_id>/publish")
    @superadmin_required
    def portal_control_page_publish_v17(page_id: int):
        row = db.session.get(ControlPage, page_id) or abort(404)
        blocks = row.blocks()
        if not blocks:
            flash("Halaman kosong tidak dapat diterbitkan.", "danger")
            return redirect(url_for("portal_control_page_edit_v17", page_id=row.id))
        before = _row_snapshot(row, "page")
        row.published_json = row.draft_json
        row.status = "published"
        row.version_no += 1
        row.published_by = current_user.id
        row.published_at = datetime.utcnow()
        snapshot = _row_snapshot(row, "page")
        _snapshot("page", row.id, row.version_no, snapshot)
        _audit("Menerbitkan halaman", "page", row.id, before, snapshot, request.form.get("reason", ""))
        db.session.commit()
        flash("Halaman berhasil diterbitkan.", "success")
        return redirect(url_for("portal_control_page_preview_v17", page_id=row.id))

    @app.post("/admin/control/pages/<int:page_id>/archive")
    @superadmin_required
    def portal_control_page_archive_v17(page_id: int):
        row = db.session.get(ControlPage, page_id) or abort(404)
        row.archived_at = None if row.archived_at else datetime.utcnow()
        _audit("Memulihkan halaman" if row.archived_at is None else "Mengarsipkan halaman", "page", row.id)
        db.session.commit()
        return redirect(url_for("portal_control_pages_v17"))

    # ---------- Forms ----------
    @app.route("/admin/control/forms")
    @superadmin_required
    def portal_control_forms_v17():
        rows = ControlForm.query.order_by(ControlForm.archived_at.isnot(None), ControlForm.sort_order, ControlForm.title).all()
        return render_template("portal_control_v17/forms.html", rows=rows)

    @app.route("/admin/control/forms/new", methods=["GET", "POST"])
    @app.route("/admin/control/forms/<int:form_id>/edit", methods=["GET", "POST"])
    @superadmin_required
    def portal_control_form_edit_v17(form_id: int | None = None):
        row = db.session.get(ControlForm, form_id) if form_id else None
        if form_id and not row:
            abort(404)
        if request.method == "POST":
            before = _row_snapshot(row, "form") if row else {}
            try:
                title = request.form.get("title", "").strip()[:180]
                if not title:
                    raise ValueError("Judul formulir wajib diisi.")
                slug = _slug(request.form.get("slug") or title)
                duplicate = ControlForm.query.filter_by(slug=slug).first()
                if duplicate and (row is None or duplicate.id != row.id):
                    raise ValueError("Slug formulir sudah digunakan.")
                scope = request.form.get("target_scope", "public")
                if scope not in ALLOWED_SCOPES:
                    raise ValueError("Target formulir tidak valid.")
                fields = _clean_fields(request.form.get("fields_json", "[]"))
                settings = {
                    "success_title": request.form.get("success_title", "Data berhasil dikirim").strip()[:180],
                    "success_message": request.form.get("success_message", "Data akan diperiksa oleh admin.").strip()[:1000],
                    "accepting": _bool("accepting"),
                    "quota": _integer(request.form.get("quota"), 0, 0, 100000),
                    "preset": request.form.get("preset", "custom")[:60],
                }
                workflow = {
                    "reference_number": _bool("workflow_reference"),
                    "admin_notification": _bool("workflow_notification"),
                    "whatsapp_confirmation": _bool("workflow_whatsapp"),
                }
                if row is None:
                    row = ControlForm(slug=slug, title=title, created_by=current_user.id)
                    db.session.add(row)
                row.slug, row.title, row.target_scope = slug, title, scope
                row.description = request.form.get("description", "").strip()[:4000]
                row.menu_label = request.form.get("menu_label", "").strip()[:100]
                row.menu_icon = request.form.get("menu_icon", "fa-clipboard-list") if request.form.get("menu_icon") in ICON_OPTIONS.values() else "fa-clipboard-list"
                row.show_in_menu = _bool("show_in_menu")
                row.sort_order = _integer(request.form.get("sort_order"), 100)
                row.roles_json = json.dumps([r for r in request.form.getlist("roles") if r in ALLOWED_ROLES])
                row.fields_draft_json = json.dumps(fields, ensure_ascii=False)
                row.settings_json = json.dumps(settings, ensure_ascii=False)
                row.workflow_json = json.dumps(workflow, ensure_ascii=False)
                row.updated_by = current_user.id
                db.session.flush()
                _audit("Menyimpan draft formulir", "form", row.id, before, _row_snapshot(row, "form"))
                db.session.commit()
                flash("Draft formulir berhasil disimpan.", "success")
                return redirect(url_for("portal_control_form_edit_v17", form_id=row.id))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        fields = row.fields() if row else []
        settings = row.settings() if row else {"accepting": True, "quota": 0, "preset": "custom"}
        workflow = row.workflow() if row else {"reference_number": True, "admin_notification": True, "whatsapp_confirmation": False}
        return render_template("portal_control_v17/form_edit.html", row=row, fields=fields, settings=settings, workflow=workflow,
                               icons=ICON_OPTIONS, roles=sorted(ALLOWED_ROLES), scopes=sorted(ALLOWED_SCOPES), field_types=sorted(ALLOWED_FIELDS))

    @app.post("/admin/control/forms/preset/registration")
    @superadmin_required
    def portal_control_registration_preset_v17():
        row = ControlForm.query.filter_by(slug="pendaftaran-santri-baru").first()
        if row is None:
            row = ControlForm(slug="pendaftaran-santri-baru", title="Pendaftaran Santri Baru", created_by=current_user.id)
            db.session.add(row)
        row.description = "Formulir pendaftaran calon santri TPQ HMarisa."
        row.target_scope = "public"
        row.menu_label = "Pendaftaran Santri Baru"
        row.menu_icon = "fa-user-plus"
        row.fields_draft_json = json.dumps(REGISTRATION_FIELDS, ensure_ascii=False)
        row.settings_json = json.dumps({"success_title": "Pendaftaran berhasil dikirim", "success_message": "Data akan diperiksa oleh Admin TPQ HMarisa.", "accepting": True, "quota": 0, "preset": "student_registration"}, ensure_ascii=False)
        row.workflow_json = json.dumps({"reference_number": True, "admin_notification": True, "whatsapp_confirmation": False})
        row.updated_by = current_user.id
        db.session.flush()
        _audit("Membuat preset pendaftaran santri", "form", row.id)
        db.session.commit()
        return redirect(url_for("portal_control_form_edit_v17", form_id=row.id))

    @app.route("/admin/control/forms/<int:form_id>/preview")
    @superadmin_required
    def portal_control_form_preview_v17(form_id: int):
        row = db.session.get(ControlForm, form_id) or abort(404)
        return render_template("portal_control_v17/form_preview.html", form=row, fields=row.fields(), settings=row.settings(), preview_mode=True, classes=CLASSES)

    @app.post("/admin/control/forms/<int:form_id>/publish")
    @superadmin_required
    def portal_control_form_publish_v17(form_id: int):
        row = db.session.get(ControlForm, form_id) or abort(404)
        fields = row.fields()
        if not fields:
            flash("Formulir kosong tidak dapat diterbitkan.", "danger")
            return redirect(url_for("portal_control_form_edit_v17", form_id=row.id))
        before = _row_snapshot(row, "form")
        row.fields_published_json = row.fields_draft_json
        row.status = "published"
        row.version_no += 1
        row.published_by = current_user.id
        row.published_at = datetime.utcnow()
        snapshot = _row_snapshot(row, "form")
        _snapshot("form", row.id, row.version_no, snapshot)
        _audit("Menerbitkan formulir", "form", row.id, before, snapshot, request.form.get("reason", ""))
        db.session.commit()
        flash("Formulir berhasil diterbitkan.", "success")
        return redirect(url_for("portal_control_form_preview_v17", form_id=row.id))

    @app.post("/admin/control/forms/<int:form_id>/archive")
    @superadmin_required
    def portal_control_form_archive_v17(form_id: int):
        row = db.session.get(ControlForm, form_id) or abort(404)
        row.archived_at = None if row.archived_at else datetime.utcnow()
        _audit("Memulihkan formulir" if row.archived_at is None else "Mengarsipkan formulir", "form", row.id)
        db.session.commit()
        return redirect(url_for("portal_control_forms_v17"))

    # ---------- Submission management ----------
    @app.route("/admin/control/submissions")
    @superadmin_required
    def portal_control_submissions_v17():
        form_id = request.args.get("form_id", type=int)
        status = request.args.get("status", "")
        query = ControlSubmission.query
        if form_id:
            query = query.filter_by(form_id=form_id)
        if status:
            query = query.filter_by(status=status)
        rows = query.order_by(ControlSubmission.id.desc()).limit(500).all()
        forms = {f.id: f for f in ControlForm.query.all()}
        return render_template("portal_control_v17/submissions.html", rows=rows, forms=forms, form_id=form_id, status=status)

    @app.route("/admin/control/submissions/<int:submission_id>", methods=["GET", "POST"])
    @superadmin_required
    def portal_control_submission_detail_v17(submission_id: int):
        row = db.session.get(ControlSubmission, submission_id) or abort(404)
        form = db.session.get(ControlForm, row.form_id) or abort(404)
        if request.method == "POST":
            before = {"status": row.status, "note": row.admin_note}
            new_status = request.form.get("status", row.status)
            if new_status not in {"Menunggu Verifikasi", "Diperiksa", "Disetujui", "Ditolak", "Diarsipkan"}:
                abort(400)
            row.status = new_status
            row.admin_note = request.form.get("admin_note", "").strip()[:4000]
            row.reviewed_by = current_user.id
            row.reviewed_at = datetime.utcnow()
            _audit("Memperbarui status data formulir", "submission", row.id, before, {"status": row.status, "note": row.admin_note})
            db.session.commit()
            flash("Status data formulir berhasil diperbarui.", "success")
            return redirect(url_for("portal_control_submission_detail_v17", submission_id=row.id))
        field_map = {f["name"]: f for f in form.fields(True)}
        return render_template("portal_control_v17/submission_detail.html", row=row, form=form, data=row.data(), files=row.files(), field_map=field_map)

    @app.route("/admin/control/submissions/export.xlsx")
    @superadmin_required
    def portal_control_submissions_export_v17():
        form_id = request.args.get("form_id", type=int)
        if not form_id:
            abort(400)
        form = db.session.get(ControlForm, form_id) or abort(404)
        rows = ControlSubmission.query.filter_by(form_id=form_id).order_by(ControlSubmission.id).all()
        try:
            from openpyxl import Workbook
        except ImportError:
            flash("openpyxl belum tersedia pada server.", "danger")
            return redirect(url_for("portal_control_submissions_v17", form_id=form_id))
        from io import BytesIO
        fields = form.fields(True)
        wb = Workbook()
        ws = wb.active
        ws.title = "Data Formulir"
        headers = ["Nomor", "Status", "Tanggal"] + [f["label"] for f in fields] + ["Catatan Admin"]
        ws.append(headers)
        for row in rows:
            data = row.data()
            ws.append([row.reference_no, row.status, (row.submitted_at + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")] + [str(data.get(f["name"], "")) for f in fields] + [row.admin_note])
        stream = BytesIO()
        wb.save(stream)
        stream.seek(0)
        return send_file(stream, as_attachment=True, download_name=f"Data_{form.slug}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ---------- Content ----------
    @app.route("/admin/control/content")
    @superadmin_required
    def portal_control_content_v17():
        rows = ControlContent.query.order_by(ControlContent.archived_at.isnot(None), ControlContent.sort_order, ControlContent.title).all()
        return render_template("portal_control_v17/content.html", rows=rows)

    @app.route("/admin/control/content/new", methods=["GET", "POST"])
    @app.route("/admin/control/content/<int:content_id>/edit", methods=["GET", "POST"])
    @superadmin_required
    def portal_control_content_edit_v17(content_id: int | None = None):
        row = db.session.get(ControlContent, content_id) if content_id else None
        if content_id and not row:
            abort(404)
        if request.method == "POST":
            before = _row_snapshot(row, "content") if row else {}
            try:
                title = request.form.get("title", "").strip()[:180]
                if not title:
                    raise ValueError("Judul konten wajib diisi.")
                key = _slug(request.form.get("key") or title)
                duplicate = ControlContent.query.filter_by(key=key).first()
                if duplicate and (row is None or duplicate.id != row.id):
                    raise ValueError("Kunci konten sudah digunakan.")
                ctype = request.form.get("content_type", "announcement")
                if ctype not in ALLOWED_CONTENT_TYPES:
                    raise ValueError("Jenis konten tidak valid.")
                scope = request.form.get("target_scope", "both")
                if scope not in ALLOWED_SCOPES:
                    raise ValueError("Target konten tidak valid.")
                data = {
                    "body": request.form.get("body", "").strip()[:10000],
                    "link_label": request.form.get("link_label", "").strip()[:100],
                    "link_url": _clean_url(request.form.get("link_url", "")) if request.form.get("link_url") else "",
                    "image": request.form.get("image", "").strip()[:255],
                    "period_label": request.form.get("period_label", "").strip()[:100],
                    "whatsapp_number": _normalize_phone(request.form.get("whatsapp_number")) if request.form.get("whatsapp_number", "").strip() else "",
                    "whatsapp_message": request.form.get("whatsapp_message", "").strip()[:4000],
                    "winners": _json_list(request.form.get("winners_json", "[]"))[:20],
                }
                if row is None:
                    row = ControlContent(key=key, title=title, created_by=current_user.id)
                    db.session.add(row)
                row.key, row.title, row.content_type, row.target_scope = key, title, ctype, scope
                row.draft_json = json.dumps(data, ensure_ascii=False)
                row.sort_order = _integer(request.form.get("sort_order"), 100)
                row.updated_by = current_user.id
                db.session.flush()
                _audit("Menyimpan draft konten", "content", row.id, before, _row_snapshot(row, "content"))
                db.session.commit()
                flash("Draft konten berhasil disimpan.", "success")
                return redirect(url_for("portal_control_content_edit_v17", content_id=row.id))
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template("portal_control_v17/content_edit.html", row=row, data=(row.data() if row else {}),
                               content_types=sorted(ALLOWED_CONTENT_TYPES), scopes=sorted(ALLOWED_SCOPES),
                               media=ControlMedia.query.filter(ControlMedia.archived_at.is_(None)).order_by(ControlMedia.id.desc()).all())

    @app.post("/admin/control/content/<int:content_id>/publish")
    @superadmin_required
    def portal_control_content_publish_v17(content_id: int):
        row = db.session.get(ControlContent, content_id) or abort(404)
        before = _row_snapshot(row, "content")
        row.published_json = row.draft_json
        row.status = "published"
        row.version_no += 1
        row.published_by = current_user.id
        row.published_at = datetime.utcnow()
        snapshot = _row_snapshot(row, "content")
        _snapshot("content", row.id, row.version_no, snapshot)
        _audit("Menerbitkan konten", "content", row.id, before, snapshot)
        db.session.commit()
        flash("Konten berhasil diterbitkan.", "success")
        return redirect(url_for("portal_control_content_v17"))

    @app.post("/admin/control/content/<int:content_id>/archive")
    @superadmin_required
    def portal_control_content_archive_v17(content_id: int):
        row = db.session.get(ControlContent, content_id) or abort(404)
        row.archived_at = None if row.archived_at else datetime.utcnow()
        _audit("Memulihkan konten" if row.archived_at is None else "Mengarsipkan konten", "content", row.id)
        db.session.commit()
        return redirect(url_for("portal_control_content_v17"))

    # ---------- Contact & payment master, reusing Finance V15 tables ----------
    @app.route("/admin/control/contacts", methods=["GET", "POST"])
    @superadmin_required
    def portal_control_contacts_v17():
        ext = app.extensions.get("finance_v15a", {})
        models = ext.get("models", {})
        Contact = models.get("whatsapp_contact")
        Channel = models.get("payment_channel")
        if not Contact or not Channel:
            flash("Master kontak Keuangan V15 belum tersedia.", "danger")
            return redirect(url_for("portal_control_dashboard_v17"))
        if request.method == "POST":
            action = request.form.get("action")
            try:
                if action == "add_contact":
                    phone = _normalize_phone(request.form.get("phone", ""))
                    if Contact.query.filter_by(phone=phone).first():
                        raise ValueError("Nomor WhatsApp sudah tersedia.")
                    row = Contact(name=request.form.get("name", "").strip()[:140], phone=phone,
                                  position=request.form.get("position", "Admin").strip()[:100] or "Admin",
                                  is_active=True, is_primary=not bool(Contact.query.filter_by(is_primary=True).first()),
                                  sort_order=Contact.query.count() * 10, updated_by=current_user.id)
                    if not row.name:
                        raise ValueError("Nama admin wajib diisi.")
                    db.session.add(row); db.session.flush(); _audit("Menambah kontak WhatsApp", "finance_contact", row.id, after={"name": row.name, "phone": row.phone})
                elif action == "update_contact":
                    row = db.session.get(Contact, request.form.get("id", type=int)) or abort(404)
                    before = {"name": row.name, "phone": row.phone, "position": row.position}
                    phone = _normalize_phone(request.form.get("phone", ""))
                    duplicate = Contact.query.filter_by(phone=phone).first()
                    if duplicate and duplicate.id != row.id:
                        raise ValueError("Nomor WhatsApp sudah digunakan kontak lain.")
                    row.name = request.form.get("name", "").strip()[:140]
                    row.phone = phone
                    row.position = request.form.get("position", "Admin").strip()[:100] or "Admin"
                    if not row.name:
                        raise ValueError("Nama admin wajib diisi.")
                    row.updated_by = current_user.id
                    _audit("Mengedit kontak WhatsApp", "finance_contact", row.id, before, {"name": row.name, "phone": row.phone, "position": row.position})
                elif action == "toggle_contact":
                    row = db.session.get(Contact, request.form.get("id", type=int)) or abort(404)
                    before = {"active": row.is_active, "primary": row.is_primary}
                    row.is_active = not row.is_active
                    if not row.is_active:
                        row.is_primary = False
                    row.updated_by = current_user.id
                    _audit("Mengubah status kontak WhatsApp", "finance_contact", row.id, before, {"active": row.is_active, "primary": row.is_primary})
                elif action == "primary_contact":
                    row = db.session.get(Contact, request.form.get("id", type=int)) or abort(404)
                    for item in Contact.query.all(): item.is_primary = item.id == row.id
                    row.is_active = True; row.updated_by = current_user.id
                    _audit("Menetapkan kontak WhatsApp utama", "finance_contact", row.id)
                elif action == "add_channel":
                    number = re.sub(r"\s+", "", request.form.get("account_number", ""))[:80]
                    if not number:
                        raise ValueError("Nomor rekening wajib diisi.")
                    if Channel.query.filter_by(account_number=number).first():
                        raise ValueError("Nomor rekening sudah tersedia.")
                    row = Channel(channel_type="bank", label=request.form.get("label", "").strip()[:120],
                                  bank_name=request.form.get("bank_name", "").strip()[:100], account_number=number,
                                  account_holder=request.form.get("account_holder", "").strip()[:160], is_active=True,
                                  is_primary=not bool(Channel.query.filter_by(is_primary=True).first()), show_on_receipt=True,
                                  sort_order=Channel.query.count()*10, updated_by=current_user.id)
                    if not row.bank_name or not row.account_holder:
                        raise ValueError("Bank dan Atas Nama wajib diisi.")
                    db.session.add(row); db.session.flush(); _audit("Menambah rekening", "finance_channel", row.id, after={"bank": row.bank_name, "number": row.account_number})
                elif action == "update_channel":
                    row = db.session.get(Channel, request.form.get("id", type=int)) or abort(404)
                    before = {"bank": row.bank_name, "number": row.account_number, "holder": row.account_holder, "label": row.label}
                    number = re.sub(r"\s+", "", request.form.get("account_number", ""))[:80]
                    duplicate = Channel.query.filter_by(account_number=number).first()
                    if duplicate and duplicate.id != row.id:
                        raise ValueError("Nomor rekening sudah digunakan rekening lain.")
                    row.bank_name = request.form.get("bank_name", "").strip()[:100]
                    row.account_number = number
                    row.account_holder = request.form.get("account_holder", "").strip()[:160]
                    row.label = request.form.get("label", "").strip()[:120]
                    if not row.bank_name or not row.account_number or not row.account_holder:
                        raise ValueError("Bank, nomor rekening, dan atas nama wajib diisi.")
                    row.updated_by = current_user.id
                    _audit("Mengedit rekening", "finance_channel", row.id, before, {"bank": row.bank_name, "number": row.account_number, "holder": row.account_holder, "label": row.label})
                elif action == "toggle_channel":
                    row = db.session.get(Channel, request.form.get("id", type=int)) or abort(404)
                    before = {"active": row.is_active, "primary": row.is_primary, "receipt": row.show_on_receipt}
                    row.is_active = not row.is_active
                    if not row.is_active: row.is_primary = False; row.show_on_receipt = False
                    row.updated_by = current_user.id
                    _audit("Mengubah status rekening", "finance_channel", row.id, before, {"active": row.is_active, "primary": row.is_primary, "receipt": row.show_on_receipt})
                elif action == "primary_channel":
                    row = db.session.get(Channel, request.form.get("id", type=int)) or abort(404)
                    for item in Channel.query.all(): item.is_primary = item.id == row.id
                    row.is_active = True; row.updated_by = current_user.id
                    _audit("Menetapkan rekening utama", "finance_channel", row.id)
                elif action == "receipt_channel":
                    row = db.session.get(Channel, request.form.get("id", type=int)) or abort(404)
                    row.show_on_receipt = row.is_active and not row.show_on_receipt
                    row.updated_by = current_user.id
                    _audit("Mengubah rekening pada bukti pembayaran", "finance_channel", row.id)
                else:
                    abort(400)
                db.session.commit()
                flash("Pengaturan berhasil disimpan.", "success")
                return redirect(url_for("portal_control_contacts_v17"))
            except Exception as exc:
                db.session.rollback(); flash(str(exc), "danger")
        return render_template("portal_control_v17/contacts.html",
                               contacts=Contact.query.order_by(Contact.sort_order, Contact.id).all(),
                               channels=Channel.query.order_by(Channel.sort_order, Channel.id).all())

    # ---------- Media ----------
    @app.route("/admin/control/media", methods=["GET", "POST"])
    @superadmin_required
    def portal_control_media_v17():
        if request.method == "POST":
            try:
                row = _save_media(request.files.get("file"), request.form.get("alt_text", ""))
                _audit("Mengunggah media", "media", row.id, after={"filename": row.filename, "name": row.original_name})
                db.session.commit(); flash("Media berhasil diunggah.", "success")
                return redirect(url_for("portal_control_media_v17"))
            except Exception as exc:
                db.session.rollback(); flash(str(exc), "danger")
        rows = ControlMedia.query.order_by(ControlMedia.archived_at.isnot(None), ControlMedia.id.desc()).all()
        return render_template("portal_control_v17/media.html", rows=rows)

    @app.post("/admin/control/media/<int:media_id>/archive")
    @superadmin_required
    def portal_control_media_archive_v17(media_id: int):
        row = db.session.get(ControlMedia, media_id) or abort(404)
        row.archived_at = None if row.archived_at else datetime.utcnow()
        _audit("Memulihkan media" if row.archived_at is None else "Mengarsipkan media", "media", row.id)
        db.session.commit(); return redirect(url_for("portal_control_media_v17"))

    @app.route("/portal-media-v17/<path:filename>")
    def portal_media_file_v17(filename: str):
        safe = secure_filename(filename)
        if not safe or safe != filename:
            abort(404)
        row = ControlMedia.query.filter_by(filename=safe, archived_at=None).first()
        if not row:
            abort(404)
        return send_from_directory(media_root, safe)

    @app.route("/portal-submission-v17/<path:filename>")
    @superadmin_required
    def portal_submission_file_v17(filename: str):
        safe = secure_filename(filename)
        if not safe or safe != filename:
            abort(404)
        return send_from_directory(submission_root, safe)

    # ---------- History ----------
    @app.route("/admin/control/history")
    @superadmin_required
    def portal_control_history_v17():
        rows = ControlAudit.query.order_by(ControlAudit.id.desc()).limit(500).all()
        return render_template("portal_control_v17/history.html", rows=rows)

    @app.post("/admin/control/revisions/<int:revision_id>/restore")
    @superadmin_required
    def portal_control_revision_restore_v17(revision_id: int):
        rev = db.session.get(ControlRevision, revision_id) or abort(404)
        payload = _json_dict(rev.snapshot_json)
        if rev.entity_type == "page":
            row = db.session.get(ControlPage, rev.entity_id) or abort(404)
            row.title = payload.get("title", row.title); row.slug = payload.get("slug", row.slug)
            row.target_scope = payload.get("scope", row.target_scope); row.menu_label = payload.get("menu_label", row.menu_label)
            row.menu_icon = payload.get("menu_icon", row.menu_icon); row.show_in_menu = bool(payload.get("show_in_menu"))
            row.sort_order = int(payload.get("sort_order", row.sort_order)); row.roles_json = json.dumps(payload.get("roles", []))
            row.draft_json = json.dumps(payload.get("blocks", []), ensure_ascii=False)
        elif rev.entity_type == "form":
            row = db.session.get(ControlForm, rev.entity_id) or abort(404)
            row.title = payload.get("title", row.title); row.slug = payload.get("slug", row.slug)
            row.description = payload.get("description", row.description); row.target_scope = payload.get("scope", row.target_scope)
            row.menu_label = payload.get("menu_label", row.menu_label); row.menu_icon = payload.get("menu_icon", row.menu_icon)
            row.show_in_menu = bool(payload.get("show_in_menu")); row.sort_order = int(payload.get("sort_order", row.sort_order))
            row.roles_json = json.dumps(payload.get("roles", [])); row.fields_draft_json = json.dumps(payload.get("fields", []), ensure_ascii=False)
            row.settings_json = json.dumps(payload.get("settings", {}), ensure_ascii=False); row.workflow_json = json.dumps(payload.get("workflow", {}), ensure_ascii=False)
        else:
            row = db.session.get(ControlContent, rev.entity_id) or abort(404)
            row.title = payload.get("title", row.title); row.key = payload.get("key", row.key)
            row.content_type = payload.get("type", row.content_type); row.target_scope = payload.get("scope", row.target_scope)
            row.draft_json = json.dumps(payload.get("data", {}), ensure_ascii=False)
        _audit("Memulihkan versi ke draft", rev.entity_type, rev.entity_id, reason=f"Versi {rev.version_no}")
        db.session.commit(); flash("Versi berhasil dipulihkan sebagai draft. Terbitkan setelah preview.", "success")
        return redirect(url_for("portal_control_history_v17"))

    # ---------- Dynamic page/form front-end ----------
    @app.route("/portal/page/<slug>")
    def portal_page_view_v17(slug: str):
        row = ControlPage.query.filter_by(slug=slug, status="published", archived_at=None).first_or_404()
        if not _scope_allowed(row.target_scope, row.roles()):
            abort(403)
        context = _render_page_context(row, preview=False)
        template = "portal_control_v17/public_page.html" if not getattr(current_user, "is_authenticated", False) else "portal_control_v17/dynamic_page.html"
        return render_template(template, **context)

    @app.route("/portal/form/<slug>", methods=["GET", "POST"])
    def portal_form_view_v17(slug: str):
        row = ControlForm.query.filter_by(slug=slug, status="published", archived_at=None).first_or_404()
        if not _scope_allowed(row.target_scope, row.roles()):
            abort(403)
        fields, settings = row.fields(True), row.settings()
        if not settings.get("accepting", True):
            return render_template("portal_control_v17/form_closed.html", form=row)
        quota = int(settings.get("quota") or 0)
        if quota and ControlSubmission.query.filter_by(form_id=row.id).count() >= quota:
            return render_template("portal_control_v17/form_closed.html", form=row, quota_reached=True)
        errors, values = {}, {}
        if request.method == "POST":
            data, files = {}, {}
            for field in fields:
                name, kind = field["name"], field["type"]
                value = request.form.getlist(name) if kind == "checkbox" else request.form.get(name, "")
                if isinstance(value, str): value = value.strip()
                if field.get("required") and (value == "" or value == [] or value is None):
                    errors[name] = f"{field['label']} wajib diisi."
                if kind == "email" and value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(value)):
                    errors[name] = "Format email tidak valid."
                if kind == "phone" and value:
                    try: value = _normalize_phone(str(value))
                    except ValueError as exc: errors[name] = str(exc)
                if kind == "file":
                    upload = request.files.get(name)
                    if upload and upload.filename:
                        try:
                            original = secure_filename(upload.filename)
                            ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
                            if ext not in ALLOWED_MEDIA_EXTENSIONS: raise ValueError("Tipe file tidak diizinkan.")
                            upload.stream.seek(0, os.SEEK_END); size = upload.stream.tell(); upload.stream.seek(0)
                            if size <= 0 or size > MAX_MEDIA_BYTES: raise ValueError("Ukuran file maksimal 10 MB.")
                            filename = f"submission_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}.{ext}"
                            upload.save(submission_root / filename); files[name] = {"filename": filename, "original": original}
                        except Exception as exc: errors[name] = str(exc)
                    elif field.get("required"): errors[name] = f"{field['label']} wajib diunggah."
                    value = ""
                data[name] = value
                values[name] = value
            if not errors:
                row_submission = ControlSubmission(form_id=row.id, reference_no="TEMP", status="Menunggu Verifikasi",
                                                   data_json=json.dumps(data, ensure_ascii=False), files_json=json.dumps(files, ensure_ascii=False),
                                                   submitter_user_id=getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None,
                                                   student_id=session.get("guardian_student_id"), ip_address=_request_ip(),
                                                   user_agent=(request.headers.get("User-Agent", "") or "")[:300])
                db.session.add(row_submission); db.session.flush()
                row_submission.reference_no = f"FRM-{datetime.utcnow().year}-{row_submission.id:06d}"
                _audit("Menerima data formulir", "submission", row_submission.id, after={"form": row.slug, "reference": row_submission.reference_no})
                db.session.commit()
                return redirect(url_for("portal_form_success_v17", reference=row_submission.reference_no))
        template = "portal_control_v17/public_form.html" if not getattr(current_user, "is_authenticated", False) else "portal_control_v17/dynamic_form.html"
        return render_template(template, form=row, fields=fields, settings=settings, errors=errors, values=values, classes=CLASSES)

    @app.route("/portal/form/success/<reference>")
    def portal_form_success_v17(reference: str):
        submission = ControlSubmission.query.filter_by(reference_no=reference).first_or_404()
        form = db.session.get(ControlForm, submission.form_id) or abort(404)
        settings, workflow = form.settings(), form.workflow()
        whatsapp_url = ""
        if workflow.get("whatsapp_confirmation"):
            ext = app.extensions.get("finance_v15a", {})
            Contact = ext.get("models", {}).get("whatsapp_contact")
            contact = Contact.query.filter_by(is_primary=True, is_active=True).first() if Contact else None
            if contact:
                from urllib.parse import quote
                message = f"Assalamu'alaikum. Saya sudah mengirim {form.title} dengan nomor {reference}."
                whatsapp_url = f"https://wa.me/{contact.phone}?text={quote(message)}"
        return render_template("portal_control_v17/form_success.html", form=form, submission=submission, settings=settings, whatsapp_url=whatsapp_url)

    # ---------- Context ----------
    @app.context_processor
    def _portal_control_context_v17():
        try:
            if getattr(current_user, "is_authenticated", False):
                scope = "admin" if getattr(current_user, "is_admin", False) else "guardian"
                menus = _menu_items(scope)
            else:
                scope, menus = "public", []
            contents = _published_content(scope if scope in {"admin", "guardian"} else "public")
            data = [{"id": c.id, "key": c.key, "title": c.title, "type": c.content_type, "data": c.data(True)} for c in contents]
            monthly = next((x for x in data if x["type"] == "monthly_achievement"), None)
            banners = [x for x in data if x["type"] in {"announcement", "banner"}]
            return {
                "portal_v17_menu_items": menus,
                "portal_v17_contents": data,
                "portal_v17_banners": banners,
                "portal_v17_monthly_achievement": monthly,
                "portal_v17_media_url": lambda filename: url_for("portal_media_file_v17", filename=filename),
            }
        except Exception:
            return {"portal_v17_menu_items": [], "portal_v17_contents": [], "portal_v17_banners": [], "portal_v17_monthly_achievement": None}

    app.extensions["portal_control_v17"] = {
        "models": {"page": ControlPage, "form": ControlForm, "submission": ControlSubmission, "content": ControlContent,
                   "media": ControlMedia, "revision": ControlRevision, "audit": ControlAudit},
        "version": "V17",
        "ensure_seed": _ensure_seed,
    }
    return app.extensions["portal_control_v17"]
