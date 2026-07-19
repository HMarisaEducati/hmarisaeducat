"""
Control Center v1 — TPQ HMarisa
================================
Pusat kendali admin modern yang terintegrasi dengan sistem yang sudah ada.
Semua fitur lama TETAP berjalan — ini murni penambahan.

Route prefix: /control-center
Akses: hanya superadmin (role == 'admin_utama')
"""

import csv
import io
import json
import os
import platform
import shutil
import sys
import uuid
from copy import deepcopy
from datetime import datetime, date, timedelta
from functools import wraps

import flask
from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect,
    render_template, request, send_file, session, url_for
)
from flask_login import current_user, login_required
from sqlalchemy import inspect, text
from sqlalchemy import or_ as sa_or
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

# ── Start time for uptime calc ──────────────────────────────────────────────
_CC_START_TIME = datetime.utcnow()


# ═══════════════════════════════════════════════════════════════════════════
# Models (added alongside existing tables — no existing tables touched)
# ═══════════════════════════════════════════════════════════════════════════

def _register_models(db):
    """Create new CC models on the shared db instance."""

    class CCActivityLog(db.Model):
        __tablename__ = "cc_activity_log"
        id          = db.Column(db.Integer, primary_key=True)
        user_id     = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
        username    = db.Column(db.String(80), default="")
        action_type = db.Column(db.String(30), default="other")   # login,logout,create,update,delete,upload,backup,other
        action      = db.Column(db.String(200), nullable=False)
        detail      = db.Column(db.Text, default="")
        ip_address  = db.Column(db.String(45), default="")
        user_agent  = db.Column(db.String(400), default="")
        created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

        ACTION_TYPE_LABELS = {
            "login": "Login", "logout": "Logout", "create": "Tambah Data",
            "update": "Edit Data", "delete": "Hapus Data", "upload": "Upload",
            "backup": "Backup", "other": "Lainnya",
        }
        ACTION_TYPE_ICONS = {
            "login": "fa-right-to-bracket", "logout": "fa-right-from-bracket",
            "create": "fa-plus", "update": "fa-pen", "delete": "fa-trash",
            "upload": "fa-upload", "backup": "fa-box-archive", "other": "fa-circle-dot",
        }

        @property
        def action_type_label(self):
            return self.ACTION_TYPE_LABELS.get(self.action_type, self.action_type)

        @property
        def icon(self):
            return self.ACTION_TYPE_ICONS.get(self.action_type, "fa-circle-dot")

    class CCSiteSetting(db.Model):
        __tablename__ = "cc_site_setting"
        id         = db.Column(db.Integer, primary_key=True)
        key        = db.Column(db.String(80), unique=True, nullable=False, index=True)
        value      = db.Column(db.Text, default="")
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        updated_by = db.Column(db.String(80), default="")

    class CCBackupRecord(db.Model):
        __tablename__ = "cc_backup_record"
        id         = db.Column(db.Integer, primary_key=True)
        filename   = db.Column(db.String(200), nullable=False)
        size_bytes = db.Column(db.Integer, default=0)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        created_by = db.Column(db.String(80), default="")

        @property
        def size(self):
            b = self.size_bytes or 0
            if b < 1024:      return f"{b} B"
            if b < 1024**2:   return f"{b/1024:.1f} KB"
            return f"{b/1024**2:.2f} MB"

    return CCActivityLog, CCSiteSetting, CCBackupRecord


# ═══════════════════════════════════════════════════════════════════════════
# Install function (called from app.py)
# ═══════════════════════════════════════════════════════════════════════════

def install_control_center_v1(app, db, app_globals):
    """
    Register Control Center routes and models with the Flask app.
    Call this AFTER all existing install_* functions in app.py.
    """
    CCActivityLog, CCSiteSetting, CCBackupRecord = _register_models(db)

    # Make models accessible in app globals for convenience
    app_globals["CCActivityLog"]  = CCActivityLog
    app_globals["CCSiteSetting"]  = CCSiteSetting
    app_globals["CCBackupRecord"] = CCBackupRecord

    # ── Shortcuts for models already in app_globals ──────────────────────
    def _User():
        return app_globals["User"]
    def _Santri():
        return app_globals["Santri"]
    def _Raport():
        return app_globals.get("Raport")
    def _Iuran():
        return app_globals.get("Iuran")
    def _Kitab():
        return app_globals.get("Kitab")

    # ── Helpers ──────────────────────────────────────────────────────────
    def cc_log(action, detail="", action_type="other"):
        """Write an activity log entry."""
        try:
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
            ip = ip.split(",")[0].strip()
            ua = request.headers.get("User-Agent", "")[:400]
            log = CCActivityLog(
                user_id=current_user.id if current_user.is_authenticated else None,
                username=current_user.username if current_user.is_authenticated else "sistem",
                action_type=action_type,
                action=action,
                detail=detail,
                ip_address=ip,
                user_agent=ua,
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()

    def get_setting(key, default=""):
        row = CCSiteSetting.query.filter_by(key=key).first()
        return row.value if row else default

    def set_setting(key, value):
        row = CCSiteSetting.query.filter_by(key=key).first()
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
            row.updated_by = current_user.username if current_user.is_authenticated else "sistem"
        else:
            row = CCSiteSetting(
                key=key, value=value,
                updated_by=current_user.username if current_user.is_authenticated else "sistem"
            )
            db.session.add(row)

    def superadmin_required_cc(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_superadmin or not getattr(current_user, "is_active", True):
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def _get_db_path():
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if uri.startswith("sqlite:///"):
            rel = uri[len("sqlite:///"):]
            return os.path.join(app.root_path, "instance", rel) if not os.path.isabs(rel) else rel
        return None

    def _get_db_size_mb():
        try:
            path = _get_db_path()
            if path and os.path.exists(path):
                return round(os.path.getsize(path) / (1024 * 1024), 2)
        except Exception:
            pass
        return 0

    def _get_table_list():
        """Return list of dicts with table name, row count, col count."""
        results = []
        try:
            insp = inspect(db.engine)
            for tname in sorted(insp.get_table_names()):
                try:
                    col_count = len(insp.get_columns(tname))
                    row_count = db.session.execute(text(f"SELECT COUNT(*) FROM \"{tname}\"")).scalar() or 0
                except Exception:
                    col_count = 0
                    row_count = 0
                results.append({"name": tname, "row_count": row_count, "col_count": col_count})
        except Exception:
            pass
        return results

    def _get_stats():
        """Collect dashboard statistics."""
        User   = _User()
        Santri = _Santri()
        Raport = _Raport()
        Iuran  = _Iuran()
        Kitab  = _Kitab()

        try: total_santri  = Santri.query.count()
        except Exception: total_santri = 0
        try: active_santri = Santri.query.filter_by(is_active=True).count()
        except Exception: active_santri = 0
        try: total_guru    = User.query.filter(User.role.in_(["admin_utama","admin","bendahara","guru"])).count()
        except Exception: total_guru = 0
        try: guru_count    = User.query.filter_by(role="guru").count()
        except Exception: guru_count = 0
        try: admin_count   = User.query.filter(User.role.in_(["admin_utama","admin","bendahara"])).count()
        except Exception: admin_count = 0
        try: total_wali    = User.query.filter_by(role="guardian").count()
        except Exception: total_wali = 0

        unpaid_bills = 0; total_unpaid_amount = 0
        if Iuran:
            try:
                unpaid = Iuran.query.filter_by(status="Belum Bayar").all()
                unpaid_bills = len(unpaid)
                total_unpaid_amount = sum(getattr(i, "nominal", 0) or 0 for i in unpaid)
            except Exception: pass

        raport_published = 0; raport_draft = 0
        if Raport:
            try:
                raport_published = Raport.query.filter_by(status="Diterbitkan").count()
                raport_draft     = Raport.query.filter_by(status="Draf").count()
            except Exception: pass

        total_books = 0
        if Kitab:
            try: total_books = Kitab.query.count()
            except Exception: pass

        today_start = datetime.combine(date.today(), datetime.min.time())
        try:
            activity_today = CCActivityLog.query.filter(CCActivityLog.created_at >= today_start).count()
        except Exception:
            activity_today = 0

        return dict(
            total_santri=total_santri,
            active_santri=active_santri,
            inactive_santri=total_santri - active_santri,
            total_guru=total_guru,
            guru_count=guru_count,
            admin_count=admin_count,
            total_wali=total_wali,
            unpaid_bills=unpaid_bills,
            total_unpaid_amount=total_unpaid_amount,
            raport_published=raport_published,
            raport_draft=raport_draft,
            total_books=total_books,
            activity_today=activity_today,
            db_size_mb=_get_db_size_mb(),
        )

    # ── Notification helper ───────────────────────────────────────────────
    def _build_notifications():
        """Build list of actionable notifications for the topbar bell."""
        notes = []
        Iuran  = _Iuran()
        Raport = _Raport()

        # Unpaid bills
        if Iuran:
            try:
                unpaid = Iuran.query.filter_by(status="Belum Bayar").count()
                if unpaid > 0:
                    notes.append({
                        "title": f"{unpaid} Tagihan Belum Dibayar",
                        "desc": "Ada santri yang memiliki tunggakan iuran.",
                        "icon": "fa-file-invoice-dollar",
                        "level": "warning",
                        "url": url_for("finance_administration"),
                    })
            except Exception:
                pass

        # Draft raport
        if Raport:
            try:
                drafts = Raport.query.filter_by(status="Draf").count()
                if drafts > 0:
                    notes.append({
                        "title": f"{drafts} E-Raport Masih Draf",
                        "desc": "E-raport belum diterbitkan untuk santri.",
                        "icon": "fa-file-pen",
                        "level": "info",
                        "url": url_for("eraport"),
                    })
            except Exception:
                pass

        # DB size warning (> 50 MB)
        db_mb = _get_db_size_mb()
        if db_mb > 50:
            notes.append({
                "title": f"Database Besar ({db_mb} MB)",
                "desc": "Pertimbangkan membuat backup rutin.",
                "icon": "fa-database",
                "level": "warning",
                "url": url_for("control_center_backup"),
            })

        return notes

    # ── Blueprint routes ─────────────────────────────────────────────────
    ROLE_LABELS = {
        "admin_utama": "Super Admin",
        "admin": "Admin",
        "bendahara": "Bendahara",
        "guru": "Guru",
        "guardian": "Wali Santri",
    }

    CLASSES = app_globals.get("CLASSES", ["Ar Rahman", "Ar Rahim", "Al-Bayyan"])

    def _backup_dir():
        d = os.path.join(app.root_path, "backups", "database")
        os.makedirs(d, exist_ok=True)
        return d

    def _make_backup_filename():
        now = datetime.now()
        base = f"HMARISA_DB_Backup_{now:%Y-%m-%d}_{now:%H-%M}.sqlite"
        candidate = base
        counter = 1
        while os.path.exists(os.path.join(_backup_dir(), candidate)):
            candidate = f"HMARISA_DB_Backup_{now:%Y-%m-%d}_{now:%H-%M}_{counter}.sqlite"
            counter += 1
        return candidate

    def _get_database_backup_summary():
        db_path = _get_db_path()
        backup_dir = _backup_dir()
        db_name = os.path.basename(db_path) if db_path else "database.sqlite"
        db_size_bytes = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else 0
        db_size_label = f"{db_size_bytes / (1024 * 1024):.2f} MB" if db_size_bytes else "0 MB"

        latest_record = CCBackupRecord.query.order_by(CCBackupRecord.created_at.desc()).first()
        backup_files = []
        for name in sorted(os.listdir(backup_dir)):
            if name.lower().endswith((".sqlite", ".db", ".sqlite3")):
                path = os.path.join(backup_dir, name)
                if os.path.isfile(path):
                    backup_files.append({
                        "filename": name,
                        "size_bytes": os.path.getsize(path),
                        "created_at": datetime.fromtimestamp(os.path.getmtime(path)),
                    })

        if latest_record:
            last_backup_time = latest_record.created_at.strftime("%d/%m/%Y %H:%M")
        elif backup_files:
            last_backup_time = backup_files[-1]["created_at"].strftime("%d/%m/%Y %H:%M")
        else:
            last_backup_time = "Belum ada backup"

        return {
            "db_name": db_name,
            "db_size_label": db_size_label,
            "last_backup_time": last_backup_time,
            "backup_count": len(backup_files),
            "backup_dir": backup_dir,
        }

    def _portal_experience_models():
        extension = app.extensions.get("portal_settings_v16_integrated") or {}
        models = extension.get("models") or {}
        return {
            "version": models.get("version"),
            "state": models.get("state"),
            "audit": models.get("audit"),
        }

    def _default_admin_layout_payload():
        return {
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
        }

    def _default_module_visibility_payload():
        return {
            "enabled": False,
            "admin_show_date": True,
            "admin_show_stats": True,
            "admin_show_hadith": True,
            "admin_show_monthly_winners": True,
            "admin_show_monthly_poster": True,
            "admin_show_syllabus": True,
        }

    def _ensure_portal_experience_section(section: str, default_payload: dict):
        models = _portal_experience_models()
        version_model = models.get("version")
        state_model = models.get("state")
        if not version_model or not state_model:
            return None, None, None

        state = db.session.get(state_model, section)
        if state and state.active_version_id and state.draft_version_id:
            active = db.session.get(version_model, state.active_version_id)
            draft = db.session.get(version_model, state.draft_version_id)
            if active and draft:
                return state, active, draft

        maximum = (
            db.session.query(db.func.max(version_model.version_no))
            .filter(version_model.section == section)
            .scalar() or 0
        )
        active = version_model(
            section=section,
            version_no=maximum + 1,
            status="published",
            payload_json=json.dumps(default_payload, ensure_ascii=False),
            published_at=datetime.utcnow(),
        )
        db.session.add(active)
        db.session.flush()

        draft = version_model(
            section=section,
            version_no=maximum + 2,
            status="draft",
            payload_json=json.dumps(default_payload, ensure_ascii=False),
        )
        db.session.add(draft)
        db.session.flush()

        state = state_model(section=section, active_version_id=active.id, draft_version_id=draft.id)
        db.session.add(state)
        db.session.commit()
        return state, active, draft

    def _portal_payload_from_version(version, section: str, default_payload: dict):
        base = deepcopy(default_payload)
        if version is None:
            return base
        payload_json = getattr(version, "payload_json", "{}") or "{}"
        try:
            parsed = json.loads(payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        if isinstance(parsed, dict):
            base.update(parsed)
        return base

    def _get_portal_experience_payload(section: str, draft: bool, default_payload: dict):
        _, active, draft_row = _ensure_portal_experience_section(section, default_payload)
        return _portal_payload_from_version(draft_row if draft else active, section, default_payload)

    def _save_portal_experience_draft(section: str, payload: dict, default_payload: dict, action: str = "Simpan Draft"):
        _, _, draft = _ensure_portal_experience_section(section, default_payload)
        before = _portal_payload_from_version(draft, section, default_payload)
        draft.payload_json = json.dumps(payload, ensure_ascii=False)
        draft.updated_by = current_user.id

        models = _portal_experience_models()
        audit_model = models.get("audit")
        if audit_model:
            db.session.add(audit_model(
                section=section,
                action=action,
                version_id=draft.id,
                user_id=getattr(current_user, "id", None),
                user_name=getattr(current_user, "full_name", "Sistem") or "Sistem",
                before_json=json.dumps(before, ensure_ascii=False),
                after_json=json.dumps(payload, ensure_ascii=False),
                reason="",
                ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:80],
                user_agent=(request.headers.get("User-Agent") or "")[:255],
            ))
        db.session.commit()
        return draft

    def _publish_portal_experience_section(section: str, default_payload: dict):
        models = _portal_experience_models()
        version_model = models.get("version")
        state_model = models.get("state")
        audit_model = models.get("audit")
        if not version_model or not state_model:
            return None

        state, active, draft = _ensure_portal_experience_section(section, default_payload)
        if not state or not active or not draft:
            return None

        before = _portal_payload_from_version(active, section, default_payload)
        after = _portal_payload_from_version(draft, section, default_payload)
        active.status = "archived"
        draft.status = "published"
        draft.published_at = datetime.utcnow()
        draft.published_by = current_user.id

        maximum = (
            db.session.query(db.func.max(version_model.version_no))
            .filter(version_model.section == section)
            .scalar() or draft.version_no
        )
        next_draft = version_model(
            section=section,
            version_no=maximum + 1,
            status="draft",
            payload_json=json.dumps(after, ensure_ascii=False),
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.session.add(next_draft)
        db.session.flush()

        state.active_version_id = draft.id
        state.draft_version_id = next_draft.id

        if audit_model:
            db.session.add(audit_model(
                section=section,
                action="Terbitkan",
                version_id=draft.id,
                user_id=getattr(current_user, "id", None),
                user_name=getattr(current_user, "full_name", "Sistem") or "Sistem",
                before_json=json.dumps(before, ensure_ascii=False),
                after_json=json.dumps(after, ensure_ascii=False),
                reason="",
                ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:80],
                user_agent=(request.headers.get("User-Agent") or "")[:255],
            ))
        db.session.commit()
        return draft

    def _portal_experience_image_url(filename: str) -> str:
        if not filename:
            return ""
        upload_root = Path(app.root_path) / "uploads"
        asset_dir = upload_root / "portal_settings_v16"
        path = asset_dir / Path(filename).name
        if path.exists():
            return url_for("portal_experience_asset_v16", filename=Path(filename).name)
        return ""

    def _save_portal_experience_image(upload, kind: str) -> str:
        if not upload or not upload.filename:
            return ""
        upload_root = Path(app.root_path) / "uploads"
        asset_dir = upload_root / "portal_settings_v16"
        asset_dir.mkdir(parents=True, exist_ok=True)
        safe_name = secure_filename(upload.filename)
        ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if ext not in {"png", "jpg", "jpeg", "webp"}:
            raise ValueError("Format gambar tidak valid.")
        filename = f"{kind}_{uuid.uuid4().hex[:10]}.{ext}"
        destination = asset_dir / filename
        upload.save(destination)
        return filename

    def _coerce_hex(value: str, fallback: str) -> str:
        value = (value or "").strip()
        if value.startswith("#") and len(value) == 7:
            return value.upper()
        return fallback

    def _get_layout_center_status():
        """Read existing portal layout configuration without changing schema."""
        status = {
            "admin_theme_enabled": False,
            "guardian_theme_enabled": False,
            "navigation_enabled": False,
            "module_visibility_enabled": False,
            "admin_nav_items": 0,
            "guardian_nav_items": 0,
            "module_visibility_count": 0,
            "tpq_name": get_setting("tpq_name") or "",
            "short_description": get_setting("short_description") or "",
            "primary_color": get_setting("primary_color") or "",
            "secondary_color": get_setting("secondary_color") or "",
            "identity_year": "",
            "identity_semester": "",
            "source": "Data portal settings dan portal experience yang sudah ada",
        }

        portal_settings_integrated = app.extensions.get("portal_settings_v16_integrated")
        if portal_settings_integrated:
            try:
                get_active_payload = portal_settings_integrated.get("get_active_payload")
                if callable(get_active_payload):
                    admin_theme = get_active_payload("admin_theme") or {}
                    guardian_theme = get_active_payload("guardian_theme") or {}
                    navigation = get_active_payload("navigation") or {}
                    module_visibility = get_active_payload("module_visibility") or {}

                    status["admin_theme_enabled"] = bool(admin_theme.get("enabled"))
                    status["guardian_theme_enabled"] = bool(guardian_theme.get("enabled"))
                    status["navigation_enabled"] = bool(navigation.get("enabled"))
                    status["module_visibility_enabled"] = bool(module_visibility.get("enabled"))

                    def _count_menu_items(payload):
                        if not isinstance(payload, dict):
                            return 0
                        for key in ("items", "menu", "links"):
                            value = payload.get(key)
                            if isinstance(value, list):
                                return len(value)
                            if isinstance(value, dict):
                                return len(value)
                        count = 0
                        for key, value in payload.items():
                            if isinstance(value, (list, dict)) and key not in {"enabled", "label", "title", "description"}:
                                count += 1
                        return count

                    status["admin_nav_items"] = _count_menu_items(navigation.get("admin", {}))
                    status["guardian_nav_items"] = _count_menu_items(navigation.get("guardian", {}))
                    status["module_visibility_count"] = sum(
                        1 for key, value in module_visibility.items()
                        if key != "enabled" and isinstance(value, bool) and value
                    )
            except Exception:
                pass

        portal_settings_v16a = app.extensions.get("portal_settings_v16a")
        if portal_settings_v16a:
            try:
                get_active = portal_settings_v16a.get("get_active")
                if callable(get_active):
                    active_row = get_active()
                    if active_row:
                        status["tpq_name"] = getattr(active_row, "tpq_name", "") or status["tpq_name"]
                        status["identity_year"] = getattr(active_row, "academic_year", "") or ""
                        status["identity_semester"] = getattr(active_row, "semester", "") or ""
            except Exception:
                pass

        return status

    # ── DASHBOARD ────────────────────────────────────────────────────────
    def _render_cc(template, **kwargs):
        """Wrapper: inject shared CC context (notifications, etc.) into every render."""
        kwargs.setdefault("notifications", _build_notifications())
        kwargs.setdefault("now", datetime.now())
        return render_template(template, **kwargs)

    @app.route("/control-center")
    @app.route("/control-center/")
    @superadmin_required_cc
    def control_center_dashboard():
        stats = _get_stats()
        User   = _User()
        Santri = _Santri()
        Iuran  = _Iuran()
        Raport = _Raport()

        # Recent activities
        recent_activities = CCActivityLog.query.order_by(
            CCActivityLog.created_at.desc()
        ).limit(12).all()

        # Recent users
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()

        # Role distribution
        role_distribution = {}
        for role_key in ["admin_utama", "admin", "bendahara", "guru", "guardian"]:
            cnt = User.query.filter_by(role=role_key).count()
            if cnt > 0:
                role_distribution[role_key] = cnt

        # Chart data: santri per kelas
        class_labels = []
        class_counts = []
        for cls in CLASSES:
            class_labels.append(cls)
            try:
                class_counts.append(Santri.query.filter_by(class_name=cls, is_active=True).count())
            except Exception:
                class_counts.append(0)

        # Payment status
        payment_status_data = [0, 0, 0]
        if Iuran:
            try:
                payment_status_data = [
                    Iuran.query.filter_by(status="Lunas").count(),
                    Iuran.query.filter_by(status="Belum Bayar").count(),
                    Iuran.query.filter(Iuran.status.in_(["Dibebaskan","Gratis"])).count(),
                ]
            except Exception:
                pass

        # Raport status
        raport_status_data = [0, 0, 0]
        if Raport:
            try:
                raport_status_data = [
                    Raport.query.filter_by(status="Diterbitkan").count(),
                    Raport.query.filter_by(status="Draf").count(),
                    Raport.query.filter_by(status="Selesai").count(),
                ]
            except Exception:
                pass

        # System info
        insp = inspect(db.engine)
        total_tables = len(insp.get_table_names())
        total_rows = sum(
            db.session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
            for t in insp.get_table_names()
        )
        uptime_delta = datetime.utcnow() - _CC_START_TIME
        hours, rem = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes = rem // 60
        uptime_str = f"{hours}j {minutes}m"

        sys_info = dict(
            python=sys.version.split()[0],
            flask=flask.__version__,
            total_tables=total_tables,
            total_rows=f"{total_rows:,}".replace(",", "."),
            uptime=uptime_str,
        )

        return render_template(
            "control_center/dashboard.html",
            stats=stats,
            recent_activities=recent_activities,
            recent_users=recent_users,
            role_distribution=role_distribution,
            role_labels=ROLE_LABELS,
            class_labels=class_labels,
            class_counts=class_counts,
            payment_status_data=payment_status_data,
            raport_status_data=raport_status_data,
            sys_info=sys_info,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/layout-center")
    @superadmin_required_cc
    def control_center_layout_center():
        layout_status = _get_layout_center_status()
        return _render_cc("control_center/layout_center.html", layout_status=layout_status)

    @app.route("/control-center/layout-center/admin", methods=["GET", "POST"])
    @superadmin_required_cc
    def control_center_layout_admin():
        defaults_admin = _default_admin_layout_payload()
        defaults_module = _default_module_visibility_payload()

        if request.method == "POST":
            try:
                admin_payload = deepcopy(_get_portal_experience_payload("admin_theme", True, defaults_admin))
                admin_payload.update({
                    "enabled": request.form.get("admin_enabled") in {"1", "on", "true", "yes"},
                    "preset": (request.form.get("preset", admin_payload.get("preset", "current")) or "current").strip()[:30],
                    "primary": _coerce_hex(request.form.get("primary", ""), admin_payload.get("primary", defaults_admin["primary"])),
                    "secondary": _coerce_hex(request.form.get("secondary", ""), admin_payload.get("secondary", defaults_admin["secondary"])),
                    "accent": _coerce_hex(request.form.get("accent", ""), admin_payload.get("accent", defaults_admin["accent"])),
                    "page_bg": _coerce_hex(request.form.get("page_bg", ""), admin_payload.get("page_bg", defaults_admin["page_bg"])),
                    "surface": _coerce_hex(request.form.get("surface", ""), admin_payload.get("surface", defaults_admin["surface"])),
                    "text": _coerce_hex(request.form.get("text", ""), admin_payload.get("text", defaults_admin["text"])),
                    "font_scale": (request.form.get("font_scale") or admin_payload.get("font_scale", "normal")).strip()[:20],
                    "card_radius": (request.form.get("card_radius") or admin_payload.get("card_radius", "current")).strip()[:20],
                    "density": (request.form.get("density") or admin_payload.get("density", "comfortable")).strip()[:20],
                    "sidebar_style": (request.form.get("sidebar_style") or admin_payload.get("sidebar_style", "solid")).strip()[:20],
                    "header_style": (request.form.get("header_style") or admin_payload.get("header_style", "clean")).strip()[:20],
                    "dashboard_title": (request.form.get("dashboard_title") or admin_payload.get("dashboard_title", defaults_admin["dashboard_title"])).strip()[:120],
                    "dashboard_subtitle": (request.form.get("dashboard_subtitle") or admin_payload.get("dashboard_subtitle", defaults_admin["dashboard_subtitle"])).strip()[:240],
                    "login_title": (request.form.get("login_title") or admin_payload.get("login_title", defaults_admin["login_title"])).strip()[:100],
                    "login_subtitle": (request.form.get("login_subtitle") or admin_payload.get("login_subtitle", defaults_admin["login_subtitle"])).strip()[:260],
                })
                if request.form.get("reset_header_image") == "1":
                    admin_payload["header_image_path"] = ""
                upload_header = request.files.get("header_image")
                if upload_header and upload_header.filename:
                    admin_payload["header_image_path"] = _save_portal_experience_image(upload_header, "header_image")
                if request.form.get("reset_login_image") == "1":
                    admin_payload["login_image_path"] = ""
                upload_login = request.files.get("login_image")
                if upload_login and upload_login.filename:
                    admin_payload["login_image_path"] = _save_portal_experience_image(upload_login, "login_image")

                module_payload = deepcopy(_get_portal_experience_payload("module_visibility", True, defaults_module))
                module_payload.update({"enabled": request.form.get("module_enabled") in {"1", "on", "true", "yes"}})
                for key in [
                    "admin_show_date", "admin_show_stats", "admin_show_hadith",
                    "admin_show_monthly_winners", "admin_show_monthly_poster", "admin_show_syllabus"
                ]:
                    module_payload[key] = request.form.get(key) in {"1", "on", "true", "yes"}

                _save_portal_experience_draft("admin_theme", admin_payload, defaults_admin, action="Simpan Draft Tampilan Admin")
                _save_portal_experience_draft("module_visibility", module_payload, defaults_module, action="Simpan Draft Bagian Dashboard")

                if request.form.get("action") == "publish":
                    _publish_portal_experience_section("admin_theme", defaults_admin)
                    _publish_portal_experience_section("module_visibility", defaults_module)
                    flash("Draft tampilan Portal Admin berhasil diterbitkan.", "success")
                else:
                    flash("Draft tampilan Portal Admin berhasil disimpan.", "success")
            except Exception as exc:
                db.session.rollback()
                flash(f"Gagal menyimpan layout portal admin: {exc}", "danger")
            return redirect(url_for("control_center_layout_admin"))

        admin_payload = _get_portal_experience_payload("admin_theme", True, defaults_admin)
        module_payload = _get_portal_experience_payload("module_visibility", True, defaults_module)
        active_admin = _get_portal_experience_payload("admin_theme", False, defaults_admin)
        active_module = _get_portal_experience_payload("module_visibility", False, defaults_module)

        return _render_cc(
            "control_center/layout_admin.html",
            admin_payload=admin_payload,
            module_payload=module_payload,
            active_admin=active_admin,
            active_module=active_module,
            draft_header_url=_portal_experience_image_url(admin_payload.get("header_image_path", "")),
            draft_login_url=_portal_experience_image_url(admin_payload.get("login_image_path", "")),
            current_logo_url=(getattr(current_user, "is_admin", False) and app.extensions.get("portal_settings_v16a", {}).get("get_active") and getattr(app.extensions["portal_settings_v16a"]["get_active"](), "logo_path", "")) or "",
        )

    # ── USERS ────────────────────────────────────────────────────────────
    @app.route("/control-center/users")
    @superadmin_required_cc
    def control_center_users():
        User = _User()
        users = User.query.order_by(User.created_at.desc()).all()
        role_counts = {}
        for u in users:
            role_counts[u.role] = role_counts.get(u.role, 0) + 1
        return render_template(
            "control_center/users.html",
            users=users,
            role_counts=role_counts,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/users/add", methods=["GET", "POST"])
    @superadmin_required_cc
    def control_center_user_add():
        User = _User()
        if request.method == "POST":
            username  = request.form.get("username", "").strip().lower()
            full_name = request.form.get("full_name", "").strip()
            role      = request.form.get("role", "guardian")
            password  = request.form.get("password", "").strip()
            password_confirm = request.form.get("password_confirm", "").strip()
            is_active = request.form.get("is_active", "1") == "1"
            assigned_class = request.form.get("assigned_class", "")

            if not username or not full_name:
                flash("Username dan nama lengkap wajib diisi.", "danger")
            elif User.query.filter_by(username=username).first():
                flash(f"Username '{username}' sudah digunakan.", "danger")
            elif password and password != password_confirm:
                flash("Password dan konfirmasi tidak cocok.", "danger")
            else:
                pw = password if password else "tpqhmarisa"
                u = User(
                    username=username,
                    full_name=full_name,
                    role=role,
                    is_active=is_active,
                    assigned_class=assigned_class if role == "guru" else "",
                    created_at=datetime.utcnow(),
                )
                u.set_password(pw)
                db.session.add(u)
                db.session.commit()
                cc_log(f"Tambah pengguna: {full_name} ({username})", f"Role: {role}", "create")
                flash(f"Pengguna '{full_name}' berhasil dibuat.", "success")
                return redirect(url_for("control_center_users"))

        return render_template(
            "control_center/user_form.html",
            edit_mode=False,
            classes=CLASSES,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/users/<int:user_id>/edit", methods=["GET", "POST"])
    @superadmin_required_cc
    def control_center_user_edit(user_id):
        User = _User()
        target_user = User.query.get_or_404(user_id)

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            role      = request.form.get("role", target_user.role)
            password  = request.form.get("password", "").strip()
            password_confirm = request.form.get("password_confirm", "").strip()
            is_active = request.form.get("is_active", "1") == "1"
            assigned_class = request.form.get("assigned_class", "")

            # Don't allow deactivating or changing role of self
            if target_user.id == current_user.id:
                role      = "admin_utama"
                is_active = True

            if not full_name:
                flash("Nama lengkap wajib diisi.", "danger")
            elif password and password != password_confirm:
                flash("Password dan konfirmasi tidak cocok.", "danger")
            else:
                old_role = target_user.role
                target_user.full_name     = full_name
                target_user.role          = role
                target_user.is_active     = is_active
                target_user.assigned_class = assigned_class if role == "guru" else ""
                if password:
                    target_user.set_password(password)
                db.session.commit()
                detail = f"Role: {old_role}→{role}" if old_role != role else f"Role: {role}"
                cc_log(f"Edit pengguna: {full_name}", detail, "update")
                flash(f"Data '{full_name}' berhasil diperbarui.", "success")
                return redirect(url_for("control_center_users"))

        return render_template(
            "control_center/user_form.html",
            edit_mode=True,
            target_user=target_user,
            classes=CLASSES,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/users/<int:user_id>/delete", methods=["POST"])
    @superadmin_required_cc
    def control_center_user_delete(user_id):
        User = _User()
        target_user = User.query.get_or_404(user_id)
        if target_user.id == current_user.id:
            flash("Anda tidak bisa menghapus akun sendiri.", "danger")
            return redirect(url_for("control_center_users"))
        name = target_user.full_name
        uname = target_user.username
        # Detach santri before delete to avoid FK issues
        for s in target_user.students:
            # Reassign to a system guardian or keep as-is
            pass
        db.session.delete(target_user)
        db.session.commit()
        cc_log(f"Hapus pengguna: {name} ({uname})", "", "delete")
        flash(f"Pengguna '{name}' berhasil dihapus.", "success")
        return redirect(url_for("control_center_users"))

    @app.route("/control-center/users/<int:user_id>/toggle", methods=["POST"])
    @superadmin_required_cc
    def control_center_user_toggle(user_id):
        User = _User()
        target_user = User.query.get_or_404(user_id)
        if target_user.id == current_user.id:
            flash("Anda tidak bisa menonaktifkan akun sendiri.", "danger")
            return redirect(url_for("control_center_users"))
        target_user.is_active = not target_user.is_active
        db.session.commit()
        status = "diaktifkan" if target_user.is_active else "dinonaktifkan"
        cc_log(f"Status pengguna {target_user.username} {status}", "", "update")
        flash(f"Akun '{target_user.full_name}' berhasil {status}.", "success")
        return redirect(url_for("control_center_users"))

    @app.route("/control-center/users/<int:user_id>/reset-password", methods=["POST"])
    @superadmin_required_cc
    def control_center_user_reset_password(user_id):
        User = _User()
        target_user = User.query.get_or_404(user_id)
        default_pw = "tpqhmarisa"
        target_user.set_password(default_pw)
        db.session.commit()
        cc_log(f"Reset password: {target_user.username}", "Password direset ke default", "update")
        flash(f"Password '{target_user.full_name}' direset ke '{default_pw}'. Minta pengguna segera menggantinya.", "warning")
        return redirect(url_for("control_center_users"))

    # ── ACTIVITY LOG ─────────────────────────────────────────────────────
    @app.route("/control-center/activity-log", methods=["GET"])
    @superadmin_required_cc
    def control_center_activity_log():
        User = _User()
        q           = request.args.get("q", "").strip()
        action_type = request.args.get("action_type", "")
        user_id_f   = request.args.get("user_id", "")
        date_from   = request.args.get("date_from", "")
        date_to     = request.args.get("date_to", "")
        page        = max(1, int(request.args.get("page", 1)))
        per_page    = 50

        # Export CSV
        if request.args.get("export") == "csv":
            logs = CCActivityLog.query.order_by(CCActivityLog.created_at.desc()).limit(5000).all()
            si = io.StringIO()
            cw = csv.writer(si)
            cw.writerow(["ID", "Waktu", "Username", "Tipe", "Aksi", "Detail", "IP", "Browser"])
            for lg in logs:
                cw.writerow([lg.id, lg.created_at, lg.username, lg.action_type, lg.action, lg.detail, lg.ip_address, lg.user_agent])
            output = io.BytesIO(si.getvalue().encode("utf-8-sig"))
            return send_file(output, mimetype="text/csv",
                             as_attachment=True,
                             download_name=f"activity_log_{date.today()}.csv")

        query = CCActivityLog.query
        if q:
            like = f"%{q}%"
            query = query.filter(
                sa_or(CCActivityLog.action.ilike(like),
                      CCActivityLog.detail.ilike(like),
                      CCActivityLog.username.ilike(like))
            )
        if action_type:
            query = query.filter_by(action_type=action_type)
        if user_id_f:
            try: query = query.filter_by(user_id=int(user_id_f))
            except ValueError: pass
        if date_from:
            try: query = query.filter(CCActivityLog.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
            except ValueError: pass
        if date_to:
            try:
                dt_end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
                query = query.filter(CCActivityLog.created_at < dt_end)
            except ValueError: pass

        total       = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        logs        = query.order_by(CCActivityLog.created_at.desc()).offset((page-1)*per_page).limit(per_page).all()
        all_users   = User.query.order_by(User.full_name).all()

        filters = dict(q=q, action_type=action_type, user_id=user_id_f, date_from=date_from, date_to=date_to)

        return render_template(
            "control_center/activity_log.html",
            logs=logs,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            all_users=all_users,
            filters=filters,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/activity-log/clear", methods=["POST"])
    @superadmin_required_cc
    def control_center_activity_log_clear():
        try:
            CCActivityLog.query.delete()
            db.session.commit()
            # Log the clear itself
            cc_log("Log aktivitas dibersihkan", f"Oleh: {current_user.username}", "delete")
            flash("Log aktivitas berhasil dibersihkan.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Gagal membersihkan log: {e}", "danger")
        return redirect(url_for("control_center_activity_log"))

    # ── SETTINGS ─────────────────────────────────────────────────────────
    SETTINGS_KEYS = [
        "site_name","tpq_name","short_description","tagline",
        "meta_title","meta_description","meta_keywords",
        "phone","email","whatsapp","website","address","city","maps_url",
        "primary_color","secondary_color","accent_color","footer_text","copyright_text","announcement_text",
        "jam_senin_jumat","jam_sabtu","jam_ahad","jam_note",
        "maintenance_mode","maintenance_message",
        "facebook","instagram","youtube","twitter","tiktok","telegram",
        "timezone","language","admin_email","active_academic_year","active_semester","default_kkm",
        # hex mirrors
        "primary_color_hex","secondary_color_hex","accent_color_hex",
    ]

    @app.route("/control-center/settings", methods=["GET", "POST"])
    @superadmin_required_cc
    def control_center_settings():
        if request.method == "POST":
            for key in SETTINGS_KEYS:
                val = request.form.get(key, "")
                set_setting(key, val)
            db.session.commit()
            cc_log("Pengaturan website diperbarui", "", "update")
            flash("Pengaturan berhasil disimpan.", "success")
            return redirect(url_for("control_center_settings"))

        settings = {}
        for key in SETTINGS_KEYS:
            settings[key] = get_setting(key)

        return render_template(
            "control_center/settings.html",
            settings=settings,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    # ── DATABASE MANAGER ─────────────────────────────────────────────────
    @app.route("/control-center/database")
    @superadmin_required_cc
    def control_center_database():
        tables     = _get_table_list()
        total_rows = sum(t["row_count"] for t in tables)

        last_backup = CCBackupRecord.query.order_by(CCBackupRecord.created_at.desc()).first()
        last_backup_str = last_backup.created_at.strftime("%d/%m/%Y %H:%M") if last_backup else None

        return render_template(
            "control_center/database.html",
            tables=tables,
            total_rows=total_rows,
            db_size_mb=_get_db_size_mb(),
            last_backup=last_backup_str,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/database/table/<table_name>")
    @superadmin_required_cc
    def control_center_db_table(table_name):
        try:
            insp = inspect(db.engine)
            table_names = insp.get_table_names()
            if table_name not in table_names:
                abort(404)
            raw_cols = insp.get_columns(table_name)
            pk_cols  = set(insp.get_pk_constraint(table_name).get("constrained_columns", []))
            columns  = [
                {"name": c["name"], "type": str(c["type"]), "nullable": c.get("nullable", True), "primary_key": c["name"] in pk_cols}
                for c in raw_cols
            ]
            rows      = db.session.execute(text(f'SELECT * FROM "{table_name}" LIMIT 100')).fetchall()
            row_count = db.session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
        except Exception as e:
            flash(f"Gagal membuka tabel: {e}", "danger")
            return redirect(url_for("control_center_database"))

        return render_template(
            "control_center/table_view.html",
            table_name=table_name,
            columns=columns,
            rows=rows,
            row_count=row_count,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/database/export/<table_name>")
    @superadmin_required_cc
    def control_center_db_export_table(table_name):
        try:
            insp = inspect(db.engine)
            if table_name not in insp.get_table_names():
                abort(404)
            cols = [c["name"] for c in insp.get_columns(table_name)]
            rows = db.session.execute(text(f'SELECT * FROM "{table_name}"')).fetchall()
        except Exception as e:
            flash(f"Gagal export: {e}", "danger")
            return redirect(url_for("control_center_database"))

        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(cols)
        for row in rows:
            cw.writerow(list(row))
        output = io.BytesIO(si.getvalue().encode("utf-8-sig"))
        cc_log(f"Export tabel: {table_name}", f"{len(rows)} baris", "other")
        return send_file(output, mimetype="text/csv",
                         as_attachment=True,
                         download_name=f"{table_name}_{date.today()}.csv")

    @app.route("/control-center/database/export-all")
    @superadmin_required_cc
    def control_center_db_export_all():
        """Export all tables as ZIP of CSVs."""
        import zipfile
        insp = inspect(db.engine)
        buf  = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for tname in insp.get_table_names():
                try:
                    cols = [c["name"] for c in insp.get_columns(tname)]
                    rows = db.session.execute(text(f'SELECT * FROM "{tname}"')).fetchall()
                    si   = io.StringIO()
                    cw   = csv.writer(si)
                    cw.writerow(cols)
                    for row in rows:
                        cw.writerow(list(row))
                    zf.writestr(f"{tname}.csv", si.getvalue().encode("utf-8-sig"))
                except Exception:
                    pass
        buf.seek(0)
        cc_log("Export semua tabel (ZIP)", "", "other")
        return send_file(buf, mimetype="application/zip",
                         as_attachment=True,
                         download_name=f"tpq_export_{date.today()}.zip")

    # ── BACKUP ───────────────────────────────────────────────────────────
    @app.route("/control-center/backup")
    @superadmin_required_cc
    def control_center_backup():
        records = CCBackupRecord.query.order_by(CCBackupRecord.created_at.desc()).limit(50).all()
        backup_history = []
        bdir = _backup_dir()
        for rec in records:
            fpath = os.path.join(bdir, rec.filename)
            exists = os.path.exists(fpath)
            backup_history.append({
                "filename": rec.filename,
                "created_at": rec.created_at.strftime("%d/%m/%Y %H:%M"),
                "size": rec.size,
                "created_by": rec.created_by,
                "exists": exists,
            })

        summary = _get_database_backup_summary()
        last_backup_info = None
        if records:
            last_backup_info = {
                "created_at": records[0].created_at.strftime("%d/%m/%Y %H:%M"),
                "size": records[0].size,
            }

        return render_template(
            "control_center/backup.html",
            backup_history=backup_history,
            last_backup_info=last_backup_info,
            backup_summary=summary,
            now=datetime.now(),
            unread_notifications_count=0,
        )

    @app.route("/control-center/backup/create", methods=["POST"])
    @superadmin_required_cc
    def control_center_backup_create():
        db_path = _get_db_path()
        if not db_path or not os.path.exists(db_path):
            flash("File database tidak ditemukan.", "danger")
            return redirect(url_for("control_center_backup"))

        try:
            backup_dir = _backup_dir()
            filename = _make_backup_filename()
            dest = os.path.join(backup_dir, filename)
            shutil.copy2(db_path, dest)
            size_bytes = os.path.getsize(dest)

            rec = CCBackupRecord(
                filename=filename,
                size_bytes=size_bytes,
                created_by=current_user.username,
            )
            db.session.add(rec)
            db.session.commit()

            cc_log(f"Backup database dibuat: {filename}", f"Ukuran: {rec.size}", "backup")
            flash(f"Backup berhasil dibuat: {filename} ({rec.size})", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Backup gagal: {e}", "danger")

        return redirect(url_for("control_center_backup"))

    @app.route("/control-center/backup/download")
    @superadmin_required_cc
    def control_center_backup_download():
        """Download the most recent backup."""
        rec = CCBackupRecord.query.order_by(CCBackupRecord.created_at.desc()).first()
        if not rec:
            flash("Belum ada backup. Buat backup terlebih dahulu.", "warning")
            return redirect(url_for("control_center_backup"))
        fpath = os.path.join(_backup_dir(), rec.filename)
        if not os.path.exists(fpath):
            flash("File backup tidak ditemukan di server.", "danger")
            return redirect(url_for("control_center_backup"))
        cc_log(f"Unduh backup: {rec.filename}", "", "other")
        return send_file(fpath, as_attachment=True, download_name=rec.filename)

    @app.route("/control-center/backup/delete/<filename>", methods=["POST"])
    @superadmin_required_cc
    def control_center_backup_delete(filename):
        try:
            rec = CCBackupRecord.query.filter_by(filename=filename).first()
            fpath = os.path.join(_backup_dir(), filename)
            if rec:
                db.session.delete(rec)
            if os.path.exists(fpath):
                os.remove(fpath)
            db.session.commit()
            cc_log(f"Hapus backup: {filename}", "", "delete")
            flash("Backup berhasil dihapus.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Gagal menghapus backup: {e}", "danger")
        return redirect(url_for("control_center_backup"))

    @app.route("/control-center/backup/download/<filename>")
    @superadmin_required_cc
    def control_center_backup_download_file(filename):
        fpath = os.path.join(_backup_dir(), filename)
        if not os.path.exists(fpath):
            flash("File backup tidak ditemukan.", "danger")
            return redirect(url_for("control_center_backup"))
        cc_log(f"Unduh backup: {filename}", "", "other")
        return send_file(fpath, as_attachment=True, download_name=filename)

    @app.route("/control-center/backup/restore", methods=["POST"])
    @superadmin_required_cc
    def control_center_backup_restore():
        uploaded = request.files.get("backup_file")
        if not uploaded or uploaded.filename == "":
            flash("Pilih file backup terlebih dahulu.", "danger")
            return redirect(url_for("control_center_backup"))

        db_path = _get_db_path()
        if not db_path:
            flash("Lokasi database tidak diketahui.", "danger")
            return redirect(url_for("control_center_backup"))

        try:
            # Save upload to temp
            tmp_path = db_path + ".restore_tmp"
            uploaded.save(tmp_path)
            # Replace active DB
            shutil.copy2(db_path, db_path + ".pre_restore_bak")  # safety backup
            shutil.move(tmp_path, db_path)
            cc_log("Database di-restore dari upload", uploaded.filename, "backup")
            flash("Database berhasil di-restore. Restart aplikasi mungkin diperlukan.", "success")
        except Exception as e:
            flash(f"Restore gagal: {e}", "danger")

        return redirect(url_for("control_center_backup"))

    # ── GLOBAL SEARCH API ────────────────────────────────────────────────
    @app.route("/control-center/search")
    @superadmin_required_cc
    def control_center_search():
        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return jsonify({"results": []})

        results = []
        like = f"%{q}%"
        User   = _User()
        Santri = _Santri()

        # Search users
        users = User.query.filter(
            sa_or(User.full_name.ilike(like), User.username.ilike(like))
        ).limit(5).all()
        for u in users:
            results.append({
                "label":    u.full_name,
                "category": f"Pengguna · {u.role_label}",
                "icon":     "fa-user",
                "url":      url_for("control_center_user_edit", user_id=u.id),
            })

        # Search santri
        santris = Santri.query.filter(
            sa_or(Santri.name.ilike(like), Santri.nis.ilike(like))
        ).limit(5).all()
        for s in santris:
            results.append({
                "label":    s.name,
                "category": f"Santri · {s.class_name}",
                "icon":     "fa-child-reaching",
                "url":      url_for("student_detail", student_id=s.id),
            })

        # Settings shortcut
        if "pengaturan" in q.lower() or "setting" in q.lower():
            results.append({
                "label": "Pengaturan Website", "category": "Control Center",
                "icon": "fa-sliders", "url": url_for("control_center_settings"),
            })

        return jsonify({"results": results[:12]})

    # ── SANTRI MANAGER ───────────────────────────────────────────────────
    @app.route("/control-center/santri")
    @superadmin_required_cc
    def control_center_santri():
        Santri = _Santri()
        santri_list = Santri.query.order_by(Santri.class_name, Santri.name).all()
        total  = len(santri_list)
        active = sum(1 for s in santri_list if s.is_active)
        by_class = {}
        for s in santri_list:
            by_class[s.class_name] = by_class.get(s.class_name, 0) + 1

        return _render_cc(
            "control_center/santri.html",
            santri_list=santri_list,
            total=total,
            active=active,
            by_class=by_class,
            classes=CLASSES,
        )

    # ── MODULE HUB ───────────────────────────────────────────────────────
    @app.route("/control-center/modules")
    @superadmin_required_cc
    def control_center_modules():
        stats = _get_stats()
        return _render_cc("control_center/modules.html", stats=stats)

    # ── CONTENT / PENGUMUMAN ─────────────────────────────────────────────
    @app.route("/control-center/content")
    @superadmin_required_cc
    def control_center_content():
        # Try to get ControlContent from portal_control_v17
        ControlContent = app_globals.get("ControlContent")
        ControlPage    = app_globals.get("ControlPage")
        ControlForm    = app_globals.get("ControlForm")

        recent_contents = []
        content_counts  = {"announcement": 0, "banner": 0, "pages": 0, "forms": 0}
        if ControlContent:
            try:
                recent_contents = ControlContent.query.order_by(
                    ControlContent.created_at.desc()
                ).limit(20).all()
                content_counts["announcement"] = ControlContent.query.filter_by(
                    content_type="announcement", is_active=True
                ).count()
                content_counts["banner"] = ControlContent.query.filter_by(
                    content_type="banner", is_active=True
                ).count()
            except Exception:
                pass
        if ControlPage:
            try:
                content_counts["pages"] = ControlPage.query.count()
            except Exception:
                pass
        if ControlForm:
            try:
                content_counts["forms"] = ControlForm.query.count()
            except Exception:
                pass

        # Settings for display
        setting_keys = ["site_name", "tpq_name", "short_description", "tagline",
                        "announcement_text", "footer_text", "address", "phone"]
        site_settings = {k: get_setting(k) for k in setting_keys}

        return _render_cc(
            "control_center/content.html",
            recent_contents=recent_contents,
            content_counts=content_counts,
            site_settings=site_settings,
        )

    # ── NOTIFICATIONS JSON ────────────────────────────────────────────────
    @app.route("/control-center/notifications")
    @superadmin_required_cc
    def control_center_notifications():
        return jsonify({"notifications": _build_notifications()})

    # ── Sidebar link in base.html nav (add to existing sidebar entry) ───
    # The existing base.html already links to portal_control_dashboard_v17 for superadmin.
    # We also inject a "Control Center" link into the sidebar via a context processor.
    @app.context_processor
    def _inject_cc_link():
        """Make Control Center URL available in all templates."""
        return {"control_center_url": "/control-center"}

    # ── Schema init ──────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    # ── Seed default settings ────────────────────────────────────────────
    with app.app_context():
        defaults = {
            "site_name":       "Portal TPQ HMarisa",
            "tpq_name":        "TPQ HMarisa",
            "short_description": "Portal Pendidikan Al-Qur'an",
            "primary_color":   "#075f46",
            "secondary_color": "#10b981",
            "timezone":        "Asia/Jakarta",
            "language":        "id",
            "maintenance_mode": "0",
            "maintenance_message": "Sistem sedang dalam pemeliharaan. Mohon coba beberapa saat lagi.",
            "active_academic_year": "2025/2026",
            "active_semester":  "Semester 1",
            "default_kkm":     "70",
        }
        for key, val in defaults.items():
            if not CCSiteSetting.query.filter_by(key=key).first():
                db.session.add(CCSiteSetting(key=key, value=val, updated_by="sistem"))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
