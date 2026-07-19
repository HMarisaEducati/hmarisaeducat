"""Pengaturan Portal TPQ HMarisa V16 Terpadu.

Modul ini menambah pengaturan tampilan Portal Admin, Portal Wali, menu,
visibilitas bagian dashboard, preset E-Raport, dan desain Prestasi Bulanan.
Semua bagian memakai draft, preview, publish per bagian, fallback, audit,
dan pemulihan versi. Nilai awal identik dengan portal aktif dan seluruh
fitur baru nonaktif sampai Admin Utama menerbitkannya.
"""
from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import abort, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

SECTIONS = (
    "admin_theme",
    "guardian_theme",
    "guru_theme",
    "navigation",
    "module_visibility",
    "guru_module_visibility",
    "eraport_design",
    "achievement_design",
)
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

ICON_OPTIONS = {
    "chart-pie": "fa-chart-pie",
    "users": "fa-users",
    "sliders": "fa-sliders",
    "table-list": "fa-table-list",
    "book-open-reader": "fa-book-open-reader",
    "file-pen": "fa-file-pen",
    "wallet": "fa-wallet",
    "book-open": "fa-book-open",
    "quote-right": "fa-quote-right",
    "gear": "fa-gear",
    "child-reaching": "fa-child-reaching",
    "house": "fa-house",
    "graduation-cap": "fa-graduation-cap",
    "mosque": "fa-mosque",
}

ADMIN_MENU_DEFAULTS = {
    "dashboard": {"label": "Dasbor", "icon": "fa-chart-pie", "visible": True, "order": 10},
    "students": {"label": "Database Santri", "icon": "fa-users", "visible": True, "order": 20},
    "data_master": {"label": "Data Master", "icon": "fa-sliders", "visible": True, "order": 30},
    "curriculum": {"label": "Silabus Bulanan", "icon": "fa-table-list", "visible": True, "order": 40},
    "progress": {"label": "Prestasi Harian", "icon": "fa-book-open-reader", "visible": True, "order": 50},
    "eraport": {"label": "E-Raport", "icon": "fa-file-pen", "visible": True, "order": 60},
    "finance": {"label": "Sistem Keuangan", "icon": "fa-wallet", "visible": True, "order": 70},
    "library": {"label": "Perpustakaan Digital", "icon": "fa-book-open", "visible": True, "order": 80},
    "hadith": {"label": "Hadis Harian", "icon": "fa-quote-right", "visible": True, "order": 90},
    "settings": {"label": "Pengaturan Portal", "icon": "fa-gear", "visible": True, "order": 100},
}

GUARDIAN_MENU_DEFAULTS = {
    "dashboard": {"label": "Dasbor", "icon": "fa-chart-pie", "visible": True, "order": 10},
    "guardian_development": {"label": "Perkembangan Ananda", "icon": "fa-child-reaching", "visible": True, "order": 20},
    "guardian_finance": {"label": "Keuangan Ananda", "icon": "fa-wallet", "visible": True, "order": 30},
    "library": {"label": "Perpustakaan Digital", "icon": "fa-book-open", "visible": True, "order": 40},
}

DEFAULT_PAYLOADS: dict[str, dict[str, Any]] = {
    "admin_theme": {
        "enabled": False,
        "preset": "current",
        "primary": "#075F46",
        "secondary": "#0B7657",
        "accent": "#D2A62C",
        "page_bg": "#F4F8F6",
        "surface": "#FFFFFF",
        "text": "#17212B",
        "font_scale": "normal",
        "card_radius": "current",
        "density": "comfortable",
        "sidebar_style": "solid",
        "header_style": "clean",
        "dashboard_title": "Dasbor Administrasi TPQ",
        "dashboard_subtitle": "Pantau operasional TPQ HMarisa dalam satu tempat.",
        "login_title": "Login Admin",
        "login_subtitle": "Masukkan username dan kata sandi administrator untuk membuka panel pengelolaan.",
        "header_image_path": "",
        "login_image_path": "",
    },
    "guardian_theme": {
        "enabled": False,
        "preset": "current",
        "primary": "#075F46",
        "secondary": "#0B7657",
        "accent": "#D2A62C",
        "page_bg": "#F4F8F6",
        "surface": "#FFFFFF",
        "text": "#17212B",
        "font_scale": "normal",
        "card_radius": "current",
        "density": "comfortable",
        "sidebar_style": "solid",
        "header_style": "clean",
        "entry_title": "Buka Data Ananda",
        "entry_subtitle": "Pilih kelas terlebih dahulu, kemudian nama santri akan muncul otomatis.",
        "welcome_title": "Assalamu'alaikum, Ayah/Bunda",
        "welcome_text": "Pantau mutabaah, hafalan, tagihan, dan buku digital ananda dengan mudah.",
        "footer_text": "Portal Pendidikan Al-Qur'an",
        "banner_image_path": "",
        "entry_image_path": "",
    },
    "guru_theme": {
        "enabled": False,
        "preset": "current",
        "primary": "#075F46",
        "secondary": "#0B7657",
        "accent": "#D2A62C",
        "page_bg": "#F4F8F6",
        "surface": "#FFFFFF",
        "text": "#17212B",
        "font_scale": "normal",
        "card_radius": "current",
        "density": "comfortable",
        "sidebar_style": "solid",
        "header_style": "clean",
        "entry_title": "Buka Data Ananda",
        "entry_subtitle": "Pilih kelas terlebih dahulu, kemudian nama santri akan muncul otomatis.",
        "welcome_title": "Assalamu'alaikum, Ayah/Bunda",
        "welcome_text": "Pantau mutabaah, hafalan, tagihan, dan buku digital ananda dengan mudah.",
        "footer_text": "Portal Pendidikan Al-Qur'an",
        "banner_image_path": "",
        "entry_image_path": "",
    },
    "navigation": {
        "enabled": False,
        "admin": deepcopy(ADMIN_MENU_DEFAULTS),
        "guardian": deepcopy(GUARDIAN_MENU_DEFAULTS),
    },
    "module_visibility": {
        "enabled": False,
        "admin_show_date": True,
        "admin_show_stats": True,
        "admin_show_hadith": True,
        "admin_show_monthly_winners": True,
        "admin_show_monthly_poster": True,
        "admin_show_syllabus": True,
        "guardian_show_date": True,
        "guardian_show_stats": True,
        "guardian_show_mutabaah": True,
        "guardian_show_hafalan": True,
        "guardian_show_finance": True,
        "guardian_show_access_note": True,
        "guardian_show_monthly_winner_entry": True,
    },
    "guru_module_visibility": {
        "enabled": False,
        "guardian_show_teaching_schedule": True,
        "guardian_show_class_list": True,
        "guardian_show_grade_input": True,
        "guardian_show_attendance": True,
        "guardian_show_announcements": True,
        "guardian_show_materials": True,
        "guardian_card_schedule_order": 10,
        "guardian_card_class_list_order": 20,
        "guardian_card_grades_order": 30,
        "guardian_card_attendance_order": 40,
        "guardian_card_announcements_order": 50,
        "guardian_card_material_order": 60,
    },
    "eraport_design": {
        "enabled": False,
        "preset": "current",
        "primary": "#075B46",
        "primary_dark": "#043D31",
        "accent": "#C9972E",
        "accent_light": "#E8C56B",
        "soft": "#EAF4EE",
        "title": "RAPORT SANTRI",
        "subtitle": "TPQ HMarisa",
        "quote": "Sebaik-baik kalian adalah yang belajar Al-Qur'an dan mengajarkannya.",
        "quote_source": "HR. Bukhari",
        "show_quote": True,
        "footer_address_mode": "portal",
        "custom_footer_address": "",
    },
    "achievement_design": {
        "enabled": False,
        "preset": "current",
        "period_prefix": "Bulan",
        "class_prefix": "Kelas",
        "title_color": "#C58805",
        "title_shadow": "#7B5715",
        "name_color": "#075B46",
        "card_fill": "#FCFAF3",
        "template_image_path": "",
    },
}


def install_portal_settings_v16_integrated(app, db, namespace: dict[str, Any]):
    if app.extensions.get("portal_settings_v16_integrated"):
        return app.extensions["portal_settings_v16_integrated"]

    superadmin_required = namespace["superadmin_required"]
    upload_root = Path(namespace.get("UPLOAD_DIR") or (Path(app.root_path) / "uploads"))
    asset_dir = upload_root / "portal_settings_v16"
    asset_dir.mkdir(parents=True, exist_ok=True)

    class PortalExperienceVersion(db.Model):
        __tablename__ = "portal_experience_version"
        id = db.Column(db.Integer, primary_key=True)
        section = db.Column(db.String(60), nullable=False, index=True)
        version_no = db.Column(db.Integer, nullable=False)
        status = db.Column(db.String(20), nullable=False, default="draft", index=True)
        payload_json = db.Column(db.Text, nullable=False, default="{}")
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        published_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        published_at = db.Column(db.DateTime)
        __table_args__ = (db.UniqueConstraint("section", "version_no", name="uq_portal_experience_section_version"),)

        def payload(self) -> dict[str, Any]:
            try:
                value = json.loads(self.payload_json or "{}")
                return value if isinstance(value, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}

    class PortalExperienceState(db.Model):
        __tablename__ = "portal_experience_state"
        section = db.Column(db.String(60), primary_key=True)
        active_version_id = db.Column(db.Integer, db.ForeignKey("portal_experience_version.id"))
        draft_version_id = db.Column(db.Integer, db.ForeignKey("portal_experience_version.id"))
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class PortalExperienceAudit(db.Model):
        __tablename__ = "portal_experience_audit"
        id = db.Column(db.Integer, primary_key=True)
        section = db.Column(db.String(60), nullable=False, index=True)
        action = db.Column(db.String(80), nullable=False, index=True)
        version_id = db.Column(db.Integer, db.ForeignKey("portal_experience_version.id"))
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        user_name = db.Column(db.String(160), nullable=False, default="")
        before_json = db.Column(db.Text, nullable=False, default="{}")
        after_json = db.Column(db.Text, nullable=False, default="{}")
        reason = db.Column(db.Text, nullable=False, default="")
        ip_address = db.Column(db.String(80), nullable=False, default="")
        user_agent = db.Column(db.String(255), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def _default(section: str) -> dict[str, Any]:
        return deepcopy(DEFAULT_PAYLOADS[section])

    def _payload(row: PortalExperienceVersion | None, section: str) -> dict[str, Any]:
        base = _default(section)
        if row:
            base.update(row.payload())
        if section == "navigation":
            base["admin"] = {**deepcopy(ADMIN_MENU_DEFAULTS), **(base.get("admin") or {})}
            base["guardian"] = {**deepcopy(GUARDIAN_MENU_DEFAULTS), **(base.get("guardian") or {})}
            for key, item in ADMIN_MENU_DEFAULTS.items():
                base["admin"][key] = {**item, **(base["admin"].get(key) or {})}
            for key, item in GUARDIAN_MENU_DEFAULTS.items():
                base["guardian"][key] = {**item, **(base["guardian"].get(key) or {})}
        return base

    def _ensure_section(section: str):
        if section not in SECTIONS:
            abort(404)
        state = db.session.get(PortalExperienceState, section)
        if state and state.active_version_id and state.draft_version_id:
            active = db.session.get(PortalExperienceVersion, state.active_version_id)
            draft = db.session.get(PortalExperienceVersion, state.draft_version_id)
            if active and draft:
                return state, active, draft
        maximum = (db.session.query(db.func.max(PortalExperienceVersion.version_no))
                   .filter(PortalExperienceVersion.section == section).scalar() or 0)
        active = PortalExperienceVersion(
            section=section, version_no=maximum + 1, status="published",
            payload_json=json.dumps(_default(section), ensure_ascii=False),
            published_at=datetime.utcnow(),
        )
        db.session.add(active)
        db.session.flush()
        draft = PortalExperienceVersion(
            section=section, version_no=maximum + 2, status="draft",
            payload_json=json.dumps(_default(section), ensure_ascii=False),
        )
        db.session.add(draft)
        db.session.flush()
        state = PortalExperienceState(section=section, active_version_id=active.id, draft_version_id=draft.id)
        db.session.add(state)
        db.session.commit()
        return state, active, draft

    def _get_active_payload(section: str) -> dict[str, Any]:
        try:
            _, active, _ = _ensure_section(section)
            return _payload(active, section)
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal memuat Pengaturan Portal terpadu bagian %s", section)
            return _default(section)

    def _get_draft_payload(section: str) -> dict[str, Any]:
        _, _, draft = _ensure_section(section)
        return _payload(draft, section)

    def _save_draft(section: str, payload: dict[str, Any], action: str = "Simpan Draft") -> None:
        _, _, draft = _ensure_section(section)
        before = _payload(draft, section)
        draft.payload_json = json.dumps(payload, ensure_ascii=False)
        draft.updated_by = current_user.id
        _audit(section, action, draft, before, payload)
        db.session.commit()

    def _audit(section: str, action: str, version: PortalExperienceVersion | None,
               before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
               reason: str = "") -> None:
        user_id = getattr(current_user, "id", None) if current_user.is_authenticated else None
        user_name = getattr(current_user, "full_name", "Sistem") if current_user.is_authenticated else "Sistem"
        db.session.add(PortalExperienceAudit(
            section=section,
            action=action,
            version_id=version.id if version else None,
            user_id=user_id,
            user_name=user_name or "Sistem",
            before_json=json.dumps(before or {}, ensure_ascii=False),
            after_json=json.dumps(after or {}, ensure_ascii=False),
            reason=reason,
            ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:80],
            user_agent=(request.headers.get("User-Agent") or "")[:255],
        ))

    def _hex(raw: str, fallback: str) -> str:
        value = (raw or "").strip().upper()
        return value if HEX_RE.fullmatch(value) else fallback

    def _bool(name: str) -> bool:
        return request.form.get(name) in {"1", "true", "on", "yes"}

    def _text(name: str, fallback: str = "", max_len: int = 300) -> str:
        return (request.form.get(name, fallback) or "").strip()[:max_len]

    def _save_image(upload, kind: str) -> str:
        if not upload or not upload.filename:
            return ""
        safe = secure_filename(upload.filename)
        extension = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("Gambar harus berformat PNG, JPG, JPEG, atau WEBP.")
        upload.stream.seek(0, 2)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size > MAX_IMAGE_BYTES:
            raise ValueError("Ukuran gambar maksimal 8 MB.")
        filename = f"{kind}_{uuid.uuid4().hex[:14]}.{extension}"
        destination = asset_dir / filename
        upload.save(destination)
        if Image is not None:
            try:
                with Image.open(destination) as image:
                    image.verify()
            except Exception as exc:
                destination.unlink(missing_ok=True)
                raise ValueError("File yang diunggah bukan gambar valid.") from exc
        return filename

    def _asset_url(filename: str) -> str:
        if not filename:
            return ""
        if not (asset_dir / Path(filename).name).exists():
            return ""
        return url_for("portal_experience_asset_v16", filename=Path(filename).name)

    def _asset_path(filename: str) -> str | None:
        if not filename:
            return None
        path = asset_dir / Path(filename).name
        return str(path) if path.exists() else None

    def _v16a_context() -> dict[str, Any]:
        ext = app.extensions.get("portal_settings_v16a", {})
        models = ext.get("models", {})
        state_model = models.get("state")
        version_model = models.get("version")
        try:
            getter = ext.get("get_active")
            if getter:
                getter()  # memastikan state V16-A tersedia sebelum template terpadu dirender
        except Exception:
            db.session.rollback()
        state = db.session.get(state_model, 1) if state_model else None
        active = db.session.get(version_model, state.active_version_id) if state and version_model else None
        draft = db.session.get(version_model, state.draft_version_id) if state and version_model else None
        return {"active_settings": active, "draft_settings": draft}

    def _section_context(section: str, active_section: str, **extra) -> dict[str, Any]:
        state, active, draft = _ensure_section(section)
        context = {
            **_v16a_context(),
            "active_section": active_section,
            "experience_section": section,
            "experience_state": state,
            "experience_active": active,
            "experience_draft": draft,
            "active_payload": _payload(active, section),
            "draft_payload": _payload(draft, section),
            "icon_options": ICON_OPTIONS,
        }
        context.update(extra)
        return context

    def _parse_theme(section: str) -> dict[str, Any]:
        old = _get_draft_payload(section)
        is_admin = section == "admin_theme"
        payload = {
            **old,
            "enabled": _bool("enabled"),
            "preset": _text("preset", "current", 30),
            "primary": _hex(request.form.get("primary", ""), old["primary"]),
            "secondary": _hex(request.form.get("secondary", ""), old["secondary"]),
            "accent": _hex(request.form.get("accent", ""), old["accent"]),
            "page_bg": _hex(request.form.get("page_bg", ""), old["page_bg"]),
            "surface": _hex(request.form.get("surface", ""), old["surface"]),
            "text": _hex(request.form.get("text", ""), old["text"]),
            "font_scale": _text("font_scale", "normal", 20),
            "card_radius": _text("card_radius", "current", 20),
            "density": _text("density", "comfortable", 20),
            "sidebar_style": _text("sidebar_style", "solid", 20),
            "header_style": _text("header_style", "clean", 20),
        }
        if is_admin:
            payload.update({
                "dashboard_title": _text("dashboard_title", old["dashboard_title"], 120),
                "dashboard_subtitle": _text("dashboard_subtitle", old["dashboard_subtitle"], 240),
                "login_title": _text("login_title", old["login_title"], 100),
                "login_subtitle": _text("login_subtitle", old["login_subtitle"], 260),
            })
            image_keys = ("header_image", "login_image")
        else:
            payload.update({
                "entry_title": _text("entry_title", old["entry_title"], 100),
                "entry_subtitle": _text("entry_subtitle", old["entry_subtitle"], 260),
                "welcome_title": _text("welcome_title", old["welcome_title"], 120),
                "welcome_text": _text("welcome_text", old["welcome_text"], 260),
                "footer_text": _text("footer_text", old["footer_text"], 160),
            })
            image_keys = ("banner_image", "entry_image")
        for key in image_keys:
            path_key = f"{key}_path"
            if _bool(f"reset_{key}"):
                payload[path_key] = ""
            upload = request.files.get(key)
            if upload and upload.filename:
                payload[path_key] = _save_image(upload, key)
        return payload

    @app.route("/admin/settings/appearance/admin", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_admin_theme_v16():
        if request.method == "POST":
            try:
                _save_draft("admin_theme", _parse_theme("admin_theme"))
                flash("Draft Tampilan Portal Admin berhasil disimpan.", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            return redirect(url_for("portal_settings_admin_theme_v16"))
        context = _section_context("admin_theme", "admin_theme")
        context["draft_header_url"] = _asset_url(context["draft_payload"].get("header_image_path", ""))
        context["draft_login_url"] = _asset_url(context["draft_payload"].get("login_image_path", ""))
        return render_template("portal_settings_v16/admin_theme.html", **context)

    @app.route("/admin/settings/appearance/guardian", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_guardian_theme_v16():
        if request.method == "POST":
            try:
                _save_draft("guardian_theme", _parse_theme("guardian_theme"))
                flash("Draft Tampilan Portal Wali berhasil disimpan.", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            return redirect(url_for("portal_settings_guardian_theme_v16"))
        context = _section_context("guardian_theme", "guardian_theme")
        context["draft_banner_url"] = _asset_url(context["draft_payload"].get("banner_image_path", ""))
        context["draft_entry_url"] = _asset_url(context["draft_payload"].get("entry_image_path", ""))
        return render_template("portal_settings_v16/guardian_theme.html", **context)

    @app.route("/admin/settings/navigation", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_navigation_v16():
        if request.method == "POST":
            old = _get_draft_payload("navigation")
            payload = {"enabled": _bool("enabled"), "admin": {}, "guardian": {}}
            for scope, defaults in (("admin", ADMIN_MENU_DEFAULTS), ("guardian", GUARDIAN_MENU_DEFAULTS)):
                for key, default in defaults.items():
                    prefix = f"{scope}_{key}"
                    icon = _text(f"{prefix}_icon", default["icon"], 40)
                    if icon not in ICON_OPTIONS.values():
                        icon = default["icon"]
                    try:
                        order = max(1, min(999, int(request.form.get(f"{prefix}_order", default["order"]))))
                    except (TypeError, ValueError):
                        order = default["order"]
                    visible = True if key == "settings" else _bool(f"{prefix}_visible")
                    payload[scope][key] = {
                        "label": _text(f"{prefix}_label", default["label"], 50) or default["label"],
                        "icon": icon,
                        "visible": visible,
                        "order": order,
                    }
            _save_draft("navigation", payload)
            flash("Draft Menu & Navigasi berhasil disimpan.", "success")
            return redirect(url_for("portal_settings_navigation_v16"))
        return render_template("portal_settings_v16/navigation.html", **_section_context("navigation", "navigation", admin_defaults=ADMIN_MENU_DEFAULTS, guardian_defaults=GUARDIAN_MENU_DEFAULTS))

    @app.route("/admin/settings/modules", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_modules_v16():
        if request.method == "POST":
            payload = {"enabled": _bool("enabled")}
            for key in DEFAULT_PAYLOADS["module_visibility"]:
                if key != "enabled":
                    payload[key] = _bool(key)
            _save_draft("module_visibility", payload)
            flash("Draft visibilitas bagian portal berhasil disimpan.", "success")
            return redirect(url_for("portal_settings_modules_v16"))
        return render_template("portal_settings_v16/modules.html", **_section_context("module_visibility", "modules"))

    @app.route("/admin/settings/design/eraport", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_eraport_design_v16():
        if request.method == "POST":
            old = _get_draft_payload("eraport_design")
            payload = {
                "enabled": _bool("enabled"),
                "preset": _text("preset", "current", 30),
                "primary": _hex(request.form.get("primary", ""), old["primary"]),
                "primary_dark": _hex(request.form.get("primary_dark", ""), old["primary_dark"]),
                "accent": _hex(request.form.get("accent", ""), old["accent"]),
                "accent_light": _hex(request.form.get("accent_light", ""), old["accent_light"]),
                "soft": _hex(request.form.get("soft", ""), old["soft"]),
                "title": _text("title", old["title"], 80) or old["title"],
                "subtitle": _text("subtitle", old["subtitle"], 100) or old["subtitle"],
                "quote": _text("quote", old["quote"], 260),
                "quote_source": _text("quote_source", old["quote_source"], 100),
                "show_quote": _bool("show_quote"),
                "footer_address_mode": _text("footer_address_mode", "portal", 20),
                "custom_footer_address": _text("custom_footer_address", "", 260),
            }
            _save_draft("eraport_design", payload)
            flash("Draft Desain E-Raport berhasil disimpan.", "success")
            return redirect(url_for("portal_settings_eraport_design_v16"))
        return render_template("portal_settings_v16/eraport_design.html", **_section_context("eraport_design", "eraport_design"))

    @app.route("/admin/settings/design/achievement", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_achievement_design_v16():
        if request.method == "POST":
            old = _get_draft_payload("achievement_design")
            payload = {
                **old,
                "enabled": _bool("enabled"),
                "preset": _text("preset", "current", 30),
                "period_prefix": _text("period_prefix", "Bulan", 30) or "Bulan",
                "class_prefix": _text("class_prefix", "Kelas", 30) or "Kelas",
                "title_color": _hex(request.form.get("title_color", ""), old["title_color"]),
                "title_shadow": _hex(request.form.get("title_shadow", ""), old["title_shadow"]),
                "name_color": _hex(request.form.get("name_color", ""), old["name_color"]),
                "card_fill": _hex(request.form.get("card_fill", ""), old["card_fill"]),
            }
            if _bool("reset_template_image"):
                payload["template_image_path"] = ""
            upload = request.files.get("template_image")
            if upload and upload.filename:
                payload["template_image_path"] = _save_image(upload, "achievement_template")
            _save_draft("achievement_design", payload)
            flash("Draft Desain Prestasi Bulanan berhasil disimpan.", "success")
            return redirect(url_for("portal_settings_achievement_design_v16"))
        context = _section_context("achievement_design", "achievement_design")
        context["draft_template_url"] = _asset_url(context["draft_payload"].get("template_image_path", ""))
        return render_template("portal_settings_v16/achievement_design.html", **context)

    @app.route("/admin/settings/integrated/preview")
    @superadmin_required
    def portal_settings_integrated_preview_v16():
        section = request.args.get("section", "admin_theme")
        if section not in SECTIONS:
            section = "admin_theme"
        context = _section_context(section, "integrated_preview")
        context["all_active"] = {key: _get_active_payload(key) for key in SECTIONS}
        context["all_draft"] = {key: _get_draft_payload(key) for key in SECTIONS}
        return render_template("portal_settings_v16/preview.html", **context)

    @app.route("/admin/settings/integrated/publish/<section>", methods=["POST"])
    @superadmin_required
    def portal_settings_integrated_publish_v16(section: str):
        if section not in SECTIONS:
            abort(404)
        state, active, draft = _ensure_section(section)
        before = _payload(active, section)
        after = _payload(draft, section)
        reason = _text("reason", "", 500)
        try:
            active.status = "archived"
            draft.status = "published"
            draft.published_at = datetime.utcnow()
            draft.published_by = current_user.id
            maximum = (db.session.query(db.func.max(PortalExperienceVersion.version_no))
                       .filter(PortalExperienceVersion.section == section).scalar() or draft.version_no)
            next_draft = PortalExperienceVersion(
                section=section, version_no=maximum + 1, status="draft",
                payload_json=json.dumps(after, ensure_ascii=False),
                created_by=current_user.id, updated_by=current_user.id,
            )
            db.session.add(next_draft)
            db.session.flush()
            state.active_version_id = draft.id
            state.draft_version_id = next_draft.id
            _audit(section, "Terbitkan", draft, before, after, reason)
            db.session.commit()
            flash("Bagian pengaturan berhasil diterbitkan. Bagian lain tidak berubah.", "success")
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal menerbitkan Pengaturan Portal bagian %s", section)
            flash("Pengaturan tidak dapat diterbitkan. Portal tetap memakai versi sebelumnya.", "danger")
        return redirect(request.referrer or url_for("portal_settings_v16a"))

    @app.route("/admin/settings/integrated/discard/<section>", methods=["POST"])
    @superadmin_required
    def portal_settings_integrated_discard_v16(section: str):
        if section not in SECTIONS:
            abort(404)
        _, active, draft = _ensure_section(section)
        before = _payload(draft, section)
        after = _payload(active, section)
        draft.payload_json = json.dumps(after, ensure_ascii=False)
        draft.updated_by = current_user.id
        _audit(section, "Batalkan Draft", draft, before, after)
        db.session.commit()
        flash("Draft bagian tersebut dikembalikan ke versi aktif.", "success")
        return redirect(request.referrer or url_for("portal_settings_v16a"))

    @app.route("/admin/settings/integrated/history")
    @superadmin_required
    def portal_settings_integrated_history_v16():
        selected = request.args.get("section", "")
        query = PortalExperienceVersion.query.filter(PortalExperienceVersion.status.in_(["published", "archived"]))
        if selected in SECTIONS:
            query = query.filter_by(section=selected)
        versions = query.order_by(PortalExperienceVersion.published_at.desc(), PortalExperienceVersion.id.desc()).limit(200).all()
        audits_query = PortalExperienceAudit.query
        if selected in SECTIONS:
            audits_query = audits_query.filter_by(section=selected)
        audits = audits_query.order_by(PortalExperienceAudit.created_at.desc(), PortalExperienceAudit.id.desc()).limit(200).all()
        return render_template(
            "portal_settings_v16/history.html",
            versions=versions,
            audits=audits,
            selected_section=selected,
            section_names={
                "admin_theme": "Tampilan Admin", "guardian_theme": "Tampilan Wali", "guru_theme": "Tampilan Guru",
                "navigation": "Menu & Navigasi", "module_visibility": "Pengaturan Modul", "guru_module_visibility": "Visibilitas Dashboard Guru",
                "eraport_design": "Desain E-Raport", "achievement_design": "Prestasi Bulanan",
            },
            format_wib=lambda value: "Belum tersedia" if value is None else (value + timedelta(hours=7)).strftime("%d-%m-%Y %H:%M WIB"),
            active_section="integrated_history",
            **_v16a_context(),
        )

    @app.route("/admin/settings/integrated/restore/<int:version_id>", methods=["POST"])
    @superadmin_required
    def portal_settings_integrated_restore_v16(version_id: int):
        source = db.session.get(PortalExperienceVersion, version_id)
        if source is None or source.status == "draft" or source.section not in SECTIONS:
            abort(404)
        section = source.section
        state, active, draft = _ensure_section(section)
        before = _payload(active, section)
        restored_payload = _payload(source, section)
        maximum = (db.session.query(db.func.max(PortalExperienceVersion.version_no))
                   .filter(PortalExperienceVersion.section == section).scalar() or source.version_no)
        try:
            active.status = "archived"
            draft.status = "discarded"
            restored = PortalExperienceVersion(
                section=section, version_no=maximum + 1, status="published",
                payload_json=json.dumps(restored_payload, ensure_ascii=False),
                created_by=current_user.id, updated_by=current_user.id,
                published_by=current_user.id, published_at=datetime.utcnow(),
            )
            db.session.add(restored)
            db.session.flush()
            next_draft = PortalExperienceVersion(
                section=section, version_no=maximum + 2, status="draft",
                payload_json=json.dumps(restored_payload, ensure_ascii=False),
                created_by=current_user.id, updated_by=current_user.id,
            )
            db.session.add(next_draft)
            db.session.flush()
            state.active_version_id = restored.id
            state.draft_version_id = next_draft.id
            _audit(section, "Pulihkan Versi", restored, before, restored_payload, _text("reason", "Pulihkan versi sebelumnya", 500))
            db.session.commit()
            flash("Versi terpilih berhasil dipulihkan sebagai versi aktif baru.", "success")
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal memulihkan Pengaturan Portal bagian %s", section)
            flash("Versi tidak dapat dipulihkan. Pengaturan aktif tidak berubah.", "danger")
        return redirect(url_for("portal_settings_integrated_history_v16", section=section))

    @app.route("/portal-assets/v16/<path:filename>")
    def portal_experience_asset_v16(filename: str):
        safe_name = Path(filename).name
        if safe_name != filename:
            abort(404)
        return send_from_directory(asset_dir, safe_name, max_age=3600)

    @app.context_processor
    def _portal_experience_context_v16():
        try:
            sections = {key: _get_active_payload(key) for key in SECTIONS}
            endpoint = request.endpoint or ""
            admin_scope = bool(
                (current_user.is_authenticated and getattr(current_user, "is_admin", False))
                or endpoint in {"admin_login", "login"}
            )
            theme_key = "admin_theme"
            if not admin_scope and current_user.is_authenticated and getattr(current_user, "is_teacher", False):
                theme_key = "guru_theme"
            elif not admin_scope:
                theme_key = "guardian_theme"
            scope = "admin" if admin_scope else "guardian"
            theme = sections[theme_key]
            nav = sections["navigation"]
            modules = sections["guru_module_visibility"] if theme_key == "guru_theme" else sections["module_visibility"]
            theme_with_assets = dict(theme)
            for key in ("header_image_path", "login_image_path", "banner_image_path", "entry_image_path"):
                theme_with_assets[key.replace("_path", "_url")] = _asset_url(theme.get(key, ""))
            achievement = dict(sections["achievement_design"])
            achievement["template_image_url"] = _asset_url(achievement.get("template_image_path", ""))
            client = {
                "scope": scope,
                "theme": theme_with_assets,
                "navigation": nav.get(scope, {}),
                "navigation_enabled": bool(nav.get("enabled")),
            }
            classes = [
                "portal-experience-v16",
                f"portal-scope-{scope}",
                "portal-theme-enabled" if theme.get("enabled") else "portal-theme-disabled",
            ]
            if modules.get("enabled"):
                classes.append("portal-modules-enabled")
                for key, value in modules.items():
                    if key != "enabled" and not value:
                        classes.append("pe-hide-" + key.replace("_", "-"))
            return {
                "portal_experience": sections,
                "portal_current_theme": theme_with_assets,
                "portal_admin_theme": sections["admin_theme"],
                "portal_guardian_theme": sections["guardian_theme"],
                "portal_navigation": nav,
                "portal_nav_admin": nav.get("admin", deepcopy(ADMIN_MENU_DEFAULTS)),
                "portal_nav_guardian": nav.get("guardian", deepcopy(GUARDIAN_MENU_DEFAULTS)),
                "portal_module_visibility": modules,
                "portal_eraport_design": sections["eraport_design"],
                "portal_achievement_design": achievement,
                "portal_experience_scope": scope,
                "portal_experience_body_classes": " ".join(classes),
                "portal_experience_client": client,
            }
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal memuat Pengaturan Portal V16 Terpadu; fallback digunakan")
            scope = "admin" if current_user.is_authenticated and getattr(current_user, "is_admin", False) else "guardian"
            current_theme = _default("admin_theme")
            module_visibility = _default("module_visibility")
            if scope == "guardian":
                if getattr(current_user, "is_teacher", False):
                    current_theme = _default("guru_theme")
                    module_visibility = _default("guru_module_visibility")
                else:
                    current_theme = _default("guardian_theme")
            return {
                "portal_experience": deepcopy(DEFAULT_PAYLOADS),
                "portal_current_theme": current_theme,
                "portal_admin_theme": _default("admin_theme"),
                "portal_guardian_theme": _default("guardian_theme"),
                "portal_navigation": _default("navigation"),
                "portal_nav_admin": deepcopy(ADMIN_MENU_DEFAULTS),
                "portal_nav_guardian": deepcopy(GUARDIAN_MENU_DEFAULTS),
                "portal_module_visibility": module_visibility,
                "portal_eraport_design": _default("eraport_design"),
                "portal_achievement_design": _default("achievement_design"),
                "portal_experience_scope": scope,
                "portal_experience_body_classes": "portal-experience-v16 portal-theme-disabled",
                "portal_experience_client": {"scope": scope, "theme": current_theme, "navigation": ADMIN_MENU_DEFAULTS if scope == "admin" else GUARDIAN_MENU_DEFAULTS, "navigation_enabled": False},
            }

    app.extensions["portal_settings_v16_integrated"] = {
        "models": {
            "version": PortalExperienceVersion,
            "state": PortalExperienceState,
            "audit": PortalExperienceAudit,
        },
        "get_active_payload": _get_active_payload,
        "get_draft_payload": _get_draft_payload,
        "resolve_asset_path": _asset_path,
        "sections": SECTIONS,
        "version": "V16-TERPADU",
    }
    return app.extensions["portal_settings_v16_integrated"]
