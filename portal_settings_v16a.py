"""Pusat Pengaturan Portal TPQ HMarisa V16-A.

Tahap ini bersifat aditif dan aman: profil/identitas, tahun ajaran/semester,
dan aset portal dikelola sebagai draft dan baru memengaruhi portal setelah
Admin Utama menekan Terbitkan. Nilai lama selalu tersedia sebagai fallback.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import abort, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

ACADEMIC_YEAR_RE = re.compile(r"^(20\d{2})/(20\d{2})$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_FAVICON_EXTENSIONS = {"png", "ico"}
MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LETTERHEAD_BYTES = 8 * 1024 * 1024
DEFAULT_IDENTITY = {
    "tpq_name": "TPQ HMarisa",
    "foundation_name": "Yayasan Nuurul Hasanah",
    "address": "",
    "phone": "",
    "whatsapp": "",
    "email": "",
    "principal_name": "Bunda Hj. Maryamah, S.Ag",
    "short_description": "Portal Pendidikan Al-Qur'an",
    "academic_year": "2026/2027",
    "semester": "Semester 1",
}


def install_portal_settings_v16a(app, db, namespace: dict[str, Any]):
    if app.extensions.get("portal_settings_v16a"):
        return app.extensions["portal_settings_v16a"]

    superadmin_required = namespace["superadmin_required"]
    upload_root = Path(namespace.get("UPLOAD_DIR") or (Path(app.root_path) / "uploads"))
    asset_dir = upload_root / "portal_settings"
    asset_dir.mkdir(parents=True, exist_ok=True)

    class PortalSettingsVersion(db.Model):
        __tablename__ = "portal_settings_version"
        id = db.Column(db.Integer, primary_key=True)
        version_no = db.Column(db.Integer, nullable=False, unique=True)
        status = db.Column(db.String(20), nullable=False, default="draft", index=True)
        tpq_name = db.Column(db.String(160), nullable=False, default=DEFAULT_IDENTITY["tpq_name"])
        foundation_name = db.Column(db.String(180), nullable=False, default=DEFAULT_IDENTITY["foundation_name"])
        address = db.Column(db.Text, nullable=False, default="")
        phone = db.Column(db.String(40), nullable=False, default="")
        whatsapp = db.Column(db.String(40), nullable=False, default="")
        email = db.Column(db.String(160), nullable=False, default="")
        principal_name = db.Column(db.String(180), nullable=False, default=DEFAULT_IDENTITY["principal_name"])
        short_description = db.Column(db.String(240), nullable=False, default=DEFAULT_IDENTITY["short_description"])
        academic_year = db.Column(db.String(20), nullable=False, default=DEFAULT_IDENTITY["academic_year"])
        semester = db.Column(db.String(20), nullable=False, default=DEFAULT_IDENTITY["semester"])
        logo_path = db.Column(db.String(255), nullable=False, default="")
        favicon_path = db.Column(db.String(255), nullable=False, default="")
        letterhead_path = db.Column(db.String(255), nullable=False, default="")
        created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        published_by = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
        published_at = db.Column(db.DateTime)

    class PortalSettingsState(db.Model):
        __tablename__ = "portal_settings_state"
        id = db.Column(db.Integer, primary_key=True, default=1)
        active_version_id = db.Column(db.Integer, db.ForeignKey("portal_settings_version.id"))
        draft_version_id = db.Column(db.Integer, db.ForeignKey("portal_settings_version.id"))
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    class PortalSettingsAudit(db.Model):
        __tablename__ = "portal_settings_audit"
        id = db.Column(db.Integer, primary_key=True)
        action = db.Column(db.String(80), nullable=False, index=True)
        section = db.Column(db.String(80), nullable=False, default="general", index=True)
        version_id = db.Column(db.Integer, db.ForeignKey("portal_settings_version.id"))
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        user_name = db.Column(db.String(160), nullable=False, default="")
        before_json = db.Column(db.Text, nullable=False, default="{}")
        after_json = db.Column(db.Text, nullable=False, default="{}")
        reason = db.Column(db.Text, nullable=False, default="")
        ip_address = db.Column(db.String(80), nullable=False, default="")
        user_agent = db.Column(db.String(255), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def _year_options() -> list[str]:
        return [f"{year}/{year + 1}" for year in range(2020, 2050)]

    def _normalise_whatsapp(raw: str) -> str:
        digits = re.sub(r"\D", "", raw or "")
        if not digits:
            return ""
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
        if not digits.startswith("62") or not 10 <= len(digits) <= 15:
            raise ValueError("Nomor WhatsApp tidak valid. Gunakan nomor Indonesia yang aktif.")
        return digits

    def _version_dict(row: PortalSettingsVersion | None) -> dict[str, Any]:
        if row is None:
            return dict(DEFAULT_IDENTITY)
        return {
            "tpq_name": row.tpq_name,
            "foundation_name": row.foundation_name,
            "address": row.address,
            "phone": row.phone,
            "whatsapp": row.whatsapp,
            "email": row.email,
            "principal_name": row.principal_name,
            "short_description": row.short_description,
            "academic_year": row.academic_year,
            "semester": row.semester,
            "logo_path": row.logo_path,
            "favicon_path": row.favicon_path,
            "letterhead_path": row.letterhead_path,
            "version_no": row.version_no,
            "status": row.status,
        }

    def _copy_fields(source: PortalSettingsVersion, target: PortalSettingsVersion) -> None:
        for field in (
            "tpq_name", "foundation_name", "address", "phone", "whatsapp", "email",
            "principal_name", "short_description", "academic_year", "semester",
            "logo_path", "favicon_path", "letterhead_path",
        ):
            setattr(target, field, getattr(source, field))

    def _best_defaults() -> dict[str, str]:
        values = dict(DEFAULT_IDENTITY)
        values["principal_name"] = namespace.get("PRINCIPAL") or values["principal_name"]
        try:
            current_year_fn = namespace.get("current_academic_year")
            current = current_year_fn() if current_year_fn else None
            if current:
                values["academic_year"] = current.name
                values["semester"] = current.semester
        except Exception:
            pass
        try:
            finance_ext = app.extensions.get("finance_v15a", {})
            general_model = finance_ext.get("models", {}).get("general")
            finance_general = general_model.query.first() if general_model else None
            if finance_general:
                values["academic_year"] = finance_general.academic_year_active or values["academic_year"]
                values["semester"] = finance_general.semester_active or values["semester"]
                # Nama portal tetap memakai nilai tampilan lama pada instalasi awal.
                values["address"] = finance_general.tpq_address or values["address"]
        except Exception:
            pass
        return values

    def _ensure_state() -> tuple[PortalSettingsState, PortalSettingsVersion, PortalSettingsVersion]:
        state = db.session.get(PortalSettingsState, 1)
        if state and state.active_version_id and state.draft_version_id:
            active = db.session.get(PortalSettingsVersion, state.active_version_id)
            draft = db.session.get(PortalSettingsVersion, state.draft_version_id)
            if active and draft:
                return state, active, draft

        defaults = _best_defaults()
        max_version = db.session.query(db.func.max(PortalSettingsVersion.version_no)).scalar() or 0
        active = PortalSettingsVersion(
            version_no=max_version + 1,
            status="published",
            published_at=datetime.utcnow(),
            **defaults,
        )
        db.session.add(active)
        db.session.flush()
        draft = PortalSettingsVersion(version_no=max_version + 2, status="draft", **defaults)
        db.session.add(draft)
        db.session.flush()
        if state is None:
            state = PortalSettingsState(id=1)
            db.session.add(state)
        state.active_version_id = active.id
        state.draft_version_id = draft.id
        db.session.commit()
        return state, active, draft

    def _audit(action: str, section: str, version: PortalSettingsVersion | None,
               before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
               reason: str = "") -> None:
        user_id = getattr(current_user, "id", None) if current_user.is_authenticated else None
        user_name = getattr(current_user, "full_name", "Sistem") if current_user.is_authenticated else "Sistem"
        db.session.add(PortalSettingsAudit(
            action=action,
            section=section,
            version_id=version.id if version else None,
            user_id=user_id,
            user_name=user_name or "Sistem",
            before_json=json.dumps(before or {}, ensure_ascii=False),
            after_json=json.dumps(after or {}, ensure_ascii=False),
            reason=reason or "",
            ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip() if request else ""),
            user_agent=(request.user_agent.string[:255] if request else ""),
        ))

    def _validate_version(row: PortalSettingsVersion) -> None:
        if not row.tpq_name.strip():
            raise ValueError("Nama TPQ wajib diisi.")
        match = ACADEMIC_YEAR_RE.match(row.academic_year or "")
        if not match or int(match.group(2)) != int(match.group(1)) + 1 or row.academic_year not in _year_options():
            raise ValueError("Tahun ajaran tidak valid.")
        if row.semester not in {"Semester 1", "Semester 2"}:
            raise ValueError("Semester tidak valid.")
        if row.email and not EMAIL_RE.match(row.email):
            raise ValueError("Alamat email tidak valid.")
        if row.whatsapp:
            _normalise_whatsapp(row.whatsapp)

    def _asset_url(row: PortalSettingsVersion | None, kind: str) -> str:
        path_value = getattr(row, f"{kind}_path", "") if row else ""
        if path_value:
            return url_for("portal_settings_asset_v16a", filename=path_value)
        defaults = {
            "logo": "img/logo_portal_cropped.png",
            "favicon": "img/logo_portal_cropped.png",
            "letterhead": "img/kop_surat_tpq_hmarisa.png",
        }
        return url_for("static", filename=defaults[kind])

    def _save_asset(file_storage, kind: str) -> str:
        if not file_storage or not file_storage.filename:
            return ""
        original = secure_filename(file_storage.filename)
        ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        allowed = ALLOWED_FAVICON_EXTENSIONS if kind == "favicon" else ALLOWED_IMAGE_EXTENSIONS
        if ext not in allowed:
            raise ValueError(f"Format {kind} tidak didukung. Gunakan: {', '.join(sorted(allowed))}.")
        max_size = MAX_LETTERHEAD_BYTES if kind == "letterhead" else MAX_LOGO_BYTES
        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if size <= 0 or size > max_size:
            raise ValueError(f"Ukuran file {kind} tidak valid atau terlalu besar.")
        filename = f"{kind}_{uuid.uuid4().hex}.{ext}"
        destination = asset_dir / filename
        file_storage.save(destination)
        if Image is not None and ext != "ico":
            try:
                with Image.open(destination) as image:
                    image.verify()
            except Exception as exc:
                destination.unlink(missing_ok=True)
                raise ValueError(f"File {kind} bukan gambar yang valid.") from exc
        return filename

    def _sync_active_period(row: PortalSettingsVersion) -> None:
        AcademicYear = namespace.get("AcademicYear")
        if AcademicYear is not None:
            start_year = int(row.academic_year.split("/")[0])
            if row.semester == "Semester 1":
                start_date, end_date = date(start_year, 7, 1), date(start_year, 12, 31)
            else:
                start_date, end_date = date(start_year + 1, 1, 1), date(start_year + 1, 6, 30)
            AcademicYear.query.update({AcademicYear.is_primary: False}, synchronize_session=False)
            period = AcademicYear.query.filter_by(name=row.academic_year, semester=row.semester).first()
            if period is None:
                period = AcademicYear(
                    name=row.academic_year, semester=row.semester,
                    start_date=start_date, end_date=end_date,
                    is_active=True, is_primary=True,
                )
                db.session.add(period)
            else:
                period.start_date = period.start_date or start_date
                period.end_date = period.end_date or end_date
                period.is_active = True
                period.is_primary = True
        finance_ext = app.extensions.get("finance_v15a", {})
        general_model = finance_ext.get("models", {}).get("general")
        if general_model is not None:
            general = general_model.query.first()
            if general:
                general.academic_year_active = row.academic_year
                general.semester_active = row.semester

    def _format_wib(value: datetime | None) -> str:
        if value is None:
            return "Belum tersedia"
        return (value + timedelta(hours=7)).strftime("%d-%m-%Y %H:%M") + " WIB"

    def _settings_context(active_section: str, **extra):
        state, active, draft = _ensure_state()
        context = {
            "settings_state": state,
            "active_settings": active,
            "draft_settings": draft,
            "active_section": active_section,
            "year_options": _year_options(),
            "draft_logo_url": _asset_url(draft, "logo"),
            "draft_favicon_url": _asset_url(draft, "favicon"),
            "draft_letterhead_url": _asset_url(draft, "letterhead"),
            "active_logo_url": _asset_url(active, "logo"),
            "active_favicon_url": _asset_url(active, "favicon"),
            "active_letterhead_url": _asset_url(active, "letterhead"),
        }
        context.update(extra)
        return context

    @app.route("/admin/settings")
    @superadmin_required
    def portal_settings_v16a():
        return render_template("portal_settings_v16a/overview.html", **_settings_context("overview"))

    @app.route("/admin/settings/profile", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_profile_v16a():
        state, active, draft = _ensure_state()
        if request.method == "POST":
            before = _version_dict(draft)
            try:
                draft.tpq_name = request.form.get("tpq_name", "").strip()
                draft.foundation_name = request.form.get("foundation_name", "").strip()
                draft.address = request.form.get("address", "").strip()
                draft.phone = request.form.get("phone", "").strip()
                draft.whatsapp = _normalise_whatsapp(request.form.get("whatsapp", "").strip())
                draft.email = request.form.get("email", "").strip().lower()
                draft.principal_name = request.form.get("principal_name", "").strip()
                draft.short_description = request.form.get("short_description", "").strip()
                draft.updated_by = current_user.id
                _validate_version(draft)
                _audit("Simpan Draft", "Profil & Identitas", draft, before, _version_dict(draft))
                db.session.commit()
                flash("Draft Profil & Identitas berhasil disimpan. Portal aktif belum berubah.", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            return redirect(url_for("portal_settings_profile_v16a"))
        return render_template("portal_settings_v16a/profile.html", **_settings_context("profile"))

    @app.route("/admin/settings/academic", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_academic_v16a():
        state, active, draft = _ensure_state()
        if request.method == "POST":
            before = _version_dict(draft)
            try:
                draft.academic_year = request.form.get("academic_year", "").strip()
                draft.semester = request.form.get("semester", "").strip()
                draft.updated_by = current_user.id
                _validate_version(draft)
                _audit("Simpan Draft", "Tahun Ajaran & Semester", draft, before, _version_dict(draft))
                db.session.commit()
                flash("Draft tahun ajaran dan semester berhasil disimpan. Portal aktif belum berubah.", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            return redirect(url_for("portal_settings_academic_v16a"))
        return render_template("portal_settings_v16a/academic.html", **_settings_context("academic"))

    @app.route("/admin/settings/assets", methods=["GET", "POST"])
    @superadmin_required
    def portal_settings_assets_v16a():
        state, active, draft = _ensure_state()
        if request.method == "POST":
            before = _version_dict(draft)
            try:
                for kind in ("logo", "favicon", "letterhead"):
                    if request.form.get(f"reset_{kind}"):
                        setattr(draft, f"{kind}_path", "")
                    uploaded = request.files.get(kind)
                    if uploaded and uploaded.filename:
                        setattr(draft, f"{kind}_path", _save_asset(uploaded, kind))
                draft.updated_by = current_user.id
                _audit("Simpan Draft", "Aset Portal", draft, before, _version_dict(draft))
                db.session.commit()
                flash("Draft aset portal berhasil disimpan. Aset aktif belum berubah.", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            return redirect(url_for("portal_settings_assets_v16a"))
        return render_template("portal_settings_v16a/assets.html", **_settings_context("assets"))

    @app.route("/admin/settings/preview")
    @superadmin_required
    def portal_settings_preview_v16a():
        return render_template("portal_settings_v16a/preview.html", **_settings_context("preview"))

    @app.route("/admin/settings/publish", methods=["POST"])
    @superadmin_required
    def portal_settings_publish_v16a():
        state, active, draft = _ensure_state()
        before = _version_dict(active)
        reason = request.form.get("reason", "").strip()
        try:
            _validate_version(draft)
            active.status = "archived"
            draft.status = "published"
            draft.published_at = datetime.utcnow()
            draft.published_by = current_user.id
            _sync_active_period(draft)
            next_version = (db.session.query(db.func.max(PortalSettingsVersion.version_no)).scalar() or draft.version_no) + 1
            next_draft = PortalSettingsVersion(version_no=next_version, status="draft", created_by=current_user.id, updated_by=current_user.id)
            _copy_fields(draft, next_draft)
            db.session.add(next_draft)
            db.session.flush()
            state.active_version_id = draft.id
            state.draft_version_id = next_draft.id
            _audit("Terbitkan", "Pengaturan Portal", draft, before, _version_dict(draft), reason)
            db.session.commit()
            flash(f"Pengaturan Portal versi {draft.version_no} berhasil diterbitkan.", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal menerbitkan Pengaturan Portal V16-A")
            flash("Pengaturan tidak dapat diterbitkan. Portal tetap memakai versi aktif sebelumnya.", "danger")
        return redirect(url_for("portal_settings_v16a"))

    @app.route("/admin/settings/discard-draft", methods=["POST"])
    @superadmin_required
    def portal_settings_discard_v16a():
        state, active, draft = _ensure_state()
        before = _version_dict(draft)
        _copy_fields(active, draft)
        draft.updated_by = current_user.id
        _audit("Batalkan Draft", "Pengaturan Portal", draft, before, _version_dict(draft))
        db.session.commit()
        flash("Draft dikembalikan ke pengaturan aktif.", "success")
        return redirect(url_for("portal_settings_v16a"))

    @app.route("/admin/settings/history")
    @superadmin_required
    def portal_settings_history_v16a():
        rows = PortalSettingsVersion.query.filter(PortalSettingsVersion.status.in_(["published", "archived"])).order_by(PortalSettingsVersion.version_no.desc()).all()
        audits = PortalSettingsAudit.query.order_by(PortalSettingsAudit.created_at.desc(), PortalSettingsAudit.id.desc()).limit(100).all()
        user_model = namespace.get("User")
        user_ids = {row.user_id for row in audits if row.user_id}
        user_map = {u.id: u for u in user_model.query.filter(user_model.id.in_(user_ids)).all()} if user_model and user_ids else {}
        return render_template(
            "portal_settings_v16a/history.html",
            rows=rows,
            audits=audits,
            user_map=user_map,
            format_wib=_format_wib,
            **_settings_context("history"),
        )

    @app.route("/admin/settings/restore/<int:version_id>", methods=["POST"])
    @superadmin_required
    def portal_settings_restore_v16a(version_id: int):
        state, active, draft = _ensure_state()
        source = db.session.get(PortalSettingsVersion, version_id)
        if source is None or source.status == "draft":
            abort(404)
        if source.id == active.id:
            flash("Versi tersebut sedang aktif.", "info")
            return redirect(url_for("portal_settings_history_v16a"))
        before = _version_dict(active)
        reason = request.form.get("reason", "").strip() or f"Pulihkan versi {source.version_no}"
        try:
            max_version = db.session.query(db.func.max(PortalSettingsVersion.version_no)).scalar() or source.version_no
            draft.status = "discarded"
            restored = PortalSettingsVersion(version_no=max_version + 1, status="published", created_by=current_user.id, updated_by=current_user.id, published_by=current_user.id, published_at=datetime.utcnow())
            _copy_fields(source, restored)
            db.session.add(restored)
            db.session.flush()
            active.status = "archived"
            _sync_active_period(restored)
            next_draft = PortalSettingsVersion(version_no=max_version + 2, status="draft", created_by=current_user.id, updated_by=current_user.id)
            _copy_fields(restored, next_draft)
            db.session.add(next_draft)
            db.session.flush()
            state.active_version_id = restored.id
            state.draft_version_id = next_draft.id
            _audit("Pulihkan Versi", "Pengaturan Portal", restored, before, _version_dict(restored), reason)
            db.session.commit()
            flash(f"Versi {source.version_no} dipulihkan sebagai versi baru {restored.version_no}.", "success")
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal memulihkan versi Pengaturan Portal")
            flash("Versi tidak dapat dipulihkan. Pengaturan aktif tidak berubah.", "danger")
        return redirect(url_for("portal_settings_history_v16a"))

    @app.route("/portal-assets/v16a/<path:filename>")
    def portal_settings_asset_v16a(filename: str):
        safe_name = Path(filename).name
        if safe_name != filename:
            abort(404)
        return send_from_directory(asset_dir, safe_name, max_age=3600)

    @app.context_processor
    def _portal_settings_context_v16a():
        fallback = dict(DEFAULT_IDENTITY)
        fallback.update({
            "logo_url": url_for("static", filename="img/logo_portal_cropped.png"),
            "favicon_url": url_for("static", filename="img/logo_portal_cropped.png"),
            "letterhead_url": url_for("static", filename="img/kop_surat_tpq_hmarisa.png"),
            "version_no": 0,
        })
        try:
            state, active, _ = _ensure_state()
            identity = _version_dict(active)
            identity.update({
                "logo_url": _asset_url(active, "logo"),
                "favicon_url": _asset_url(active, "favicon"),
                "letterhead_url": _asset_url(active, "letterhead"),
            })
            return {"portal_identity": identity}
        except Exception:
            db.session.rollback()
            app.logger.exception("Gagal memuat Pengaturan Portal V16-A; fallback digunakan")
            return {"portal_identity": fallback}

    app.extensions["portal_settings_v16a"] = {
        "models": {
            "version": PortalSettingsVersion,
            "state": PortalSettingsState,
            "audit": PortalSettingsAudit,
        },
        "get_active": lambda: _ensure_state()[1],
        "version": "V16-A",
    }
    return app.extensions["portal_settings_v16a"]
