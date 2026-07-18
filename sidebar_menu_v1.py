"""
Pengelolaan Menu Sidebar Dinamis — v1
Menyimpan struktur menu sidebar di database sehingga Admin dapat mengelola
navigasi tanpa mengubah kode. Mendukung parent-child, role-based access,
pengurutan, dan badge count dinamis.
"""

from datetime import datetime
from functools import wraps
from flask import (
    request, redirect, url_for, flash,
    render_template, abort, session as flask_session,
)
from flask_login import login_required, current_user

SIDEBAR_MENU_VERSION = "1.0.0"

ALL_ROLES = ["admin_utama", "admin", "bendahara", "guru", "guardian"]

# Pilihan ikon Font Awesome 6 Solid untuk admin UI
ICON_OPTIONS = [
    ("fa-chart-pie", "Diagram"),
    ("fa-users", "Pengguna"),
    ("fa-user-graduate", "Santri"),
    ("fa-user-plus", "Tambah User"),
    ("fa-users-gear", "Kelola User"),
    ("fa-sliders", "Pengaturan Slider"),
    ("fa-table-list", "Tabel Daftar"),
    ("fa-book-open-reader", "Buku Baca"),
    ("fa-book-open", "Buku Terbuka"),
    ("fa-file-pen", "File Pena"),
    ("fa-file-invoice-dollar", "Tagihan"),
    ("fa-wallet", "Dompet"),
    ("fa-chart-bar", "Grafik"),
    ("fa-receipt", "Kuitansi"),
    ("fa-quote-right", "Kutipan"),
    ("fa-gears", "Pengaturan"),
    ("fa-circle-nodes", "Simpul"),
    ("fa-child-reaching", "Anak"),
    ("fa-school", "Sekolah"),
    ("fa-mosque", "Masjid"),
    ("fa-star-and-crescent", "Islam"),
    ("fa-graduation-cap", "Toga"),
    ("fa-calendar-week", "Kalender"),
    ("fa-list-check", "Daftar Centang"),
    ("fa-bell", "Lonceng"),
    ("fa-envelope", "Amplop"),
    ("fa-folder-open", "Folder"),
    ("fa-shield-halved", "Keamanan"),
    ("fa-key", "Kunci"),
    ("fa-link", "Tautan"),
    ("fa-house", "Rumah"),
    ("fa-circle-info", "Info"),
    ("fa-circle", "Lingkaran"),
    ("fa-star", "Bintang"),
    ("fa-bolt", "Petir"),
]


def install_sidebar_menu_v1(app, db, globs):
    """Install the dynamic sidebar menu management module."""

    # ─────────────────────────────────────────────────────────────────────────
    # MODEL
    # ─────────────────────────────────────────────────────────────────────────

    class SidebarMenu(db.Model):
        __tablename__ = "sidebar_menu"
        __table_args__ = {"extend_existing": True}

        id           = db.Column(db.Integer, primary_key=True)
        label        = db.Column(db.String(100), nullable=False)
        icon         = db.Column(db.String(80), default="fa-circle", nullable=False)
        endpoint     = db.Column(db.String(200), default="", nullable=False)
        url          = db.Column(db.String(255), default="", nullable=False)
        parent_id    = db.Column(
            db.Integer,
            db.ForeignKey("sidebar_menu.id", ondelete="CASCADE"),
            nullable=True,
        )
        sort_order      = db.Column(db.Integer, default=0, nullable=False)
        is_active       = db.Column(db.Boolean, default=True, nullable=False)
        is_system       = db.Column(db.Boolean, default=False, nullable=False)
        roles           = db.Column(db.String(255), default="admin_utama,admin", nullable=False)
        active_endpoints= db.Column(db.String(1000), default="", nullable=False)
        url_param       = db.Column(db.String(80), default="", nullable=False)
        badge_key       = db.Column(db.String(80), default="", nullable=False)
        extra_style     = db.Column(db.Text, default="", nullable=False)
        description     = db.Column(db.Text, default="", nullable=False)
        menu_function   = db.Column(db.Text, default="", nullable=False)
        menu_purpose    = db.Column(db.Text, default="", nullable=False)
        created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        updated_at      = db.Column(db.DateTime, default=datetime.utcnow,
                                    onupdate=datetime.utcnow, nullable=False)

        children = db.relationship(
            "SidebarMenu",
            backref=db.backref("parent", remote_side=[id]),
            order_by="SidebarMenu.sort_order",
            lazy="select",
            passive_deletes=True,
        )

        # ── helpers ──

        def roles_list(self):
            return [r.strip() for r in self.roles.split(",") if r.strip()]

        def visible_for(self, effective_roles: set) -> bool:
            return bool(effective_roles.intersection(self.roles_list()))

        def is_active_for(self, endpoint_name: str, path: str = "") -> bool:
            eps = set()
            for ep in (self.active_endpoints + "," + self.endpoint).split(","):
                ep = ep.strip()
                if ep:
                    eps.add(ep)
            if endpoint_name in eps:
                return True
            if (
                self.url
                and path
                and self.url not in ("#", "")
                and path.startswith(self.url)
            ):
                return True
            return False

        def resolved_url(self, student_id=None):
            if self.url:
                return self.url
            if self.endpoint:
                try:
                    if self.url_param == "guardian_student_id" and student_id:
                        return url_for(self.endpoint, student_id=student_id)
                    return url_for(self.endpoint)
                except Exception:
                    return "#"
            return "#"

        def __repr__(self):
            return f"<SidebarMenu {self.id}: {self.label}>"

    globs["SidebarMenu"] = SidebarMenu

    # ─────────────────────────────────────────────────────────────────────────
    # SEED DATA — struktur menu awal berdasarkan menu existing
    # ─────────────────────────────────────────────────────────────────────────

    def _migrate_sidebar_schema():
        """Tambah kolom baru ke tabel sidebar_menu jika belum ada."""
        from sqlalchemy import inspect as sa_inspect, text
        try:
            existing = {c["name"] for c in sa_inspect(db.engine).get_columns("sidebar_menu")}
            migrations = []
            if "description" not in existing:
                migrations.append("ALTER TABLE sidebar_menu ADD COLUMN description TEXT DEFAULT ''")
            if "menu_function" not in existing:
                migrations.append("ALTER TABLE sidebar_menu ADD COLUMN menu_function TEXT DEFAULT ''")
            if "menu_purpose" not in existing:
                migrations.append("ALTER TABLE sidebar_menu ADD COLUMN menu_purpose TEXT DEFAULT ''")
            if migrations:
                with db.engine.connect() as conn:
                    for sql in migrations:
                        conn.execute(text(sql))
                    conn.commit()
        except Exception:
            pass

    def seed_sidebar_menus():
        _migrate_sidebar_schema()
        if SidebarMenu.query.count() > 0:
            return  # Sudah pernah di-seed

        now = datetime.utcnow()

        # Endpoint groups untuk active-state detection
        S_EP = (
            "students,bulk_students,student_detail,edit_student,toggle_student,"
            "delete_student,export_students_excel,export_students_pdf,"
            "student_import_template,student_finance_v15e"
        )
        C_EP = (
            "curriculum,curriculum_database,curriculum_detail,curriculum_import,"
            "edit_curriculum,curriculum_pdf,curriculum_excel,curriculum_preview,"
            "curriculum_semester,duplicate_curriculum"
        )
        P_EP = (
            "daily_progress,academics,mutabaah_history,mutabaah_detail,"
            "edit_mutabaah,hafalan_tracker,save_hafalan_tracker,edit_hafalan,"
            "delete_hafalan,reset_hafalan,mutabaah_import,mutabaah_export,"
            "mutabaah_import_template,mutabaah_export_xlsx"
        )
        E_EP = (
            "eraport,eraport_class_dashboard,eraport_academic,eraport_hafalan,"
            "eraport_hafalan_detail,eraport_attitude,eraport_development,"
            "eraport_publication,eraport_bulk,report_edit,report_preview,report_pdf"
        )
        F_EP = (
            "finance,finance_summary,finance_bill_new,finance_administration,"
            "finance_bill_detail,finance_bill_edit,finance_bill_archive,"
            "finance_archive,finance_bill_restore,finance_payments,finance_reports,"
            "finance_payment_new,finance_payment_cancel,finance_bill_waive,"
            "finance_bill_unwaive,finance_payment_detail_v15cd,finance_access_v15e,"
            "finance_audit_v15e,finance_legacy,edit_bill,bill_receipt,"
            "finance_teacher_status_v15e,finance_teacher_export_v15e"
        )
        PC_EP = (
            "portal_control_dashboard_v17,portal_control_pages_v17,"
            "portal_control_page_edit_v17,portal_control_forms_v17,"
            "portal_control_form_edit_v17,portal_control_submissions_v17,"
            "portal_control_content_v17,portal_control_media_v17,"
            "portal_control_history_v17,portal_settings_v16a,"
            "portal_settings_profile_v16a,portal_settings_academic_v16a,"
            "portal_settings_assets_v16a,portal_settings_navigation_v16,"
            "portal_settings_modules_v16,portal_settings_eraport_design_v16"
        )
        SM_EP = "sidebar_menu_admin,sidebar_menu_add,sidebar_menu_edit"

        # ── Top-level menus ──
        top = [
            SidebarMenu(
                label="Dasbor", icon="fa-chart-pie", endpoint="dashboard",
                active_endpoints="dashboard", sort_order=10,
                roles="admin_utama,admin,guru,bendahara",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Database Santri", icon="fa-users", endpoint="",
                active_endpoints=S_EP, sort_order=20,
                roles="admin_utama,admin",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Data Master", icon="fa-sliders", endpoint="",
                active_endpoints="data_master,user_management", sort_order=30,
                roles="admin_utama,admin",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Silabus Bulanan", icon="fa-table-list", endpoint="curriculum",
                active_endpoints=C_EP, sort_order=40,
                roles="admin_utama,admin,guru",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Prestasi Harian", icon="fa-book-open-reader",
                endpoint="daily_progress", active_endpoints=P_EP, sort_order=50,
                roles="admin_utama,admin,guru",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="E-Raport", icon="fa-file-pen", endpoint="eraport",
                active_endpoints=E_EP, sort_order=60,
                roles="admin_utama,admin,guru",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Sistem Keuangan", icon="fa-wallet", endpoint="",
                active_endpoints=F_EP, sort_order=70,
                roles="admin_utama,admin,bendahara,guru",
                badge_key="finance_unpaid_count",
                is_system=True, created_at=now, updated_at=now,
            ),
            # Guardian menus
            SidebarMenu(
                label="Perkembangan Ananda", icon="fa-child-reaching",
                endpoint="guardian_student_detail",
                active_endpoints="guardian_student_detail,guardian_report",
                sort_order=10, roles="guardian",
                url_param="guardian_student_id",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Keuangan Ananda", icon="fa-wallet",
                endpoint="guardian_finance_v15e",
                active_endpoints="guardian_finance_v15e,guardian_finance_receipt_v15e",
                sort_order=20, roles="guardian",
                url_param="guardian_student_id",
                badge_key="guardian_finance_unpaid_count",
                is_system=True, created_at=now, updated_at=now,
            ),
            # Common
            SidebarMenu(
                label="Perpustakaan Digital", icon="fa-book-open", endpoint="library",
                active_endpoints="library,upload_book,edit_book,book_preview,download_book",
                sort_order=80, roles="admin_utama,admin,guru,guardian",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Hadis Harian", icon="fa-quote-right", endpoint="hadith_manager",
                active_endpoints="hadith_manager", sort_order=90,
                roles="admin_utama,admin",
                is_system=True, created_at=now, updated_at=now,
            ),
            # Admin tools
            SidebarMenu(
                label="Kelola Menu Sidebar", icon="fa-list-check",
                endpoint="sidebar_menu_admin", active_endpoints=SM_EP,
                sort_order=95, roles="admin_utama",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Pusat Kendali Portal", icon="fa-gears",
                endpoint="portal_control_dashboard_v17",
                active_endpoints=PC_EP, sort_order=100,
                roles="admin_utama",
                is_system=True, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="⚡ Control Center", icon="fa-circle-nodes",
                url="/control-center", endpoint="", active_endpoints="",
                sort_order=110, roles="admin_utama",
                extra_style=(
                    "background:linear-gradient(90deg,rgba(5,150,105,.18),transparent);"
                    "border-left:3px solid #10b981;color:#10b981;font-weight:700"
                ),
                is_system=True, created_at=now, updated_at=now,
            ),
        ]
        db.session.add_all(top)
        db.session.flush()

        def _q(label):
            return SidebarMenu.query.filter_by(label=label).first()

        db_santri  = _q("Database Santri")
        data_mstr  = _q("Data Master")
        keuangan   = _q("Sistem Keuangan")

        # ── Children ──
        children = [
            # Database Santri
            SidebarMenu(
                label="Data Santri", icon="fa-user-graduate", endpoint="students",
                active_endpoints=S_EP, sort_order=1,
                roles="admin_utama,admin", is_system=True,
                parent_id=db_santri.id, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Tambah / Import Santri", icon="fa-user-plus",
                endpoint="bulk_students", active_endpoints="bulk_students",
                sort_order=2, roles="admin_utama,admin", is_system=True,
                parent_id=db_santri.id, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Pendaftaran Santri Baru", icon="fa-user-check",
                url="/students?tab=baru", active_endpoints="",
                sort_order=3, roles="admin_utama,admin", is_system=False,
                parent_id=db_santri.id, created_at=now, updated_at=now,
            ),
            # Data Master
            SidebarMenu(
                label="Kelas & Tahun Ajaran", icon="fa-school",
                endpoint="data_master", active_endpoints="data_master",
                sort_order=1, roles="admin_utama,admin", is_system=True,
                parent_id=data_mstr.id, created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Manajemen Pengguna", icon="fa-users-gear",
                url="/data-master?tab=users",
                active_endpoints="user_management",
                sort_order=2, roles="admin_utama,admin", is_system=True,
                parent_id=data_mstr.id, created_at=now, updated_at=now,
            ),
            # Sistem Keuangan
            SidebarMenu(
                label="Tagihan & Pembayaran", icon="fa-file-invoice-dollar",
                endpoint="finance",
                active_endpoints=(
                    "finance,finance_summary,finance_bill_new,finance_payments,"
                    "finance_administration,finance_bill_detail,finance_bill_edit,"
                    "finance_payment_new,finance_payment_cancel,finance_access_v15e,"
                    "finance_audit_v15e,finance_legacy,edit_bill,bill_receipt"
                ),
                sort_order=1, roles="admin_utama,admin,bendahara",
                badge_key="finance_unpaid_count",
                is_system=True, parent_id=keuangan.id,
                created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Laporan Keuangan", icon="fa-chart-bar",
                endpoint="finance_reports",
                active_endpoints=(
                    "finance_reports,finance_report_xlsx_v15cd,"
                    "finance_report_pdf_v15cd,finance_payment_bulk_receipts_v15cd"
                ),
                sort_order=2, roles="admin_utama,admin,bendahara",
                is_system=True, parent_id=keuangan.id,
                created_at=now, updated_at=now,
            ),
            SidebarMenu(
                label="Status Iuran Kelas", icon="fa-receipt",
                endpoint="finance_teacher_status_v15e",
                active_endpoints="finance_teacher_status_v15e,finance_teacher_export_v15e",
                sort_order=3, roles="guru",
                is_system=True, parent_id=keuangan.id,
                created_at=now, updated_at=now,
            ),
        ]
        db.session.add_all(children)
        db.session.commit()

    globs["seed_sidebar_menus"] = seed_sidebar_menus

    # ─────────────────────────────────────────────────────────────────────────
    # CONTEXT PROCESSOR — inject sidebar_menus, nav_badges, resolve_nav_url
    # ─────────────────────────────────────────────────────────────────────────

    @app.context_processor
    def inject_sidebar_menus():
        if not current_user.is_authenticated:
            return {}

        role = current_user.role or ""
        effective = {role}

        # Teacher dengan akses finance: cek FinanceSetting
        if getattr(current_user, "is_teacher", False):
            try:
                FinanceSetting = globs.get("FinanceSetting")
                if FinanceSetting:
                    fs = FinanceSetting.query.first()
                    if fs and getattr(fs, "teacher_can_view_status", False):
                        effective.add("guru_finance")
            except Exception:
                pass
            # Fallback: finance module sets finance_teacher_allowed via context
            # — guru akan tetap melihat Sistem Keuangan (routes yang proteksi akses)

        # Bangun tree menu terfilter
        all_top = (
            SidebarMenu.query
            .filter_by(parent_id=None, is_active=True)
            .order_by(SidebarMenu.sort_order)
            .all()
        )

        result = []
        for menu in all_top:
            if not menu.visible_for(effective):
                continue
            visible_children = [
                c for c in (menu.children or [])
                if c.is_active and c.visible_for(effective)
            ]
            menu._nav_children = visible_children
            result.append(menu)

        # Badge counts (simple COUNT queries)
        nav_badges = {}
        try:
            from sqlalchemy import text as _t
            with db.engine.connect() as _conn:
                if current_user.is_admin:
                    nav_badges["finance_unpaid_count"] = (
                        _conn.execute(
                            _t("SELECT COUNT(*) FROM iuran WHERE status='Belum Lunas'")
                        ).scalar() or 0
                    )
                else:
                    _sid = flask_session.get("guardian_student_id")
                    if _sid:
                        nav_badges["guardian_finance_unpaid_count"] = (
                            _conn.execute(
                                _t(
                                    "SELECT COUNT(*) FROM iuran "
                                    "WHERE santri_id=:sid AND status='Belum Lunas'"
                                ),
                                {"sid": _sid},
                            ).scalar() or 0
                        )
        except Exception:
            pass

        # URL resolver
        def resolve_nav_url(menu):
            return menu.resolved_url(
                student_id=flask_session.get("guardian_student_id")
            )

        return {
            "sidebar_menus":      result,
            "nav_badges":         nav_badges,
            "resolve_nav_url":    resolve_nav_url,
            "SIDEBAR_ICON_OPTIONS": ICON_OPTIONS,
            "ALL_SIDEBAR_ROLES":  ALL_ROLES,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # DECORATOR
    # ─────────────────────────────────────────────────────────────────────────

    def superadmin_required(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            if not getattr(current_user, "is_superadmin", False):
                abort(403)
            return f(*args, **kwargs)
        return decorated

    # ─────────────────────────────────────────────────────────────────────────
    # ADMIN ROUTES
    # ─────────────────────────────────────────────────────────────────────────

    @app.route("/admin/sidebar-menu")
    @superadmin_required
    def sidebar_menu_admin():
        top_menus = (
            SidebarMenu.query
            .filter_by(parent_id=None)
            .order_by(SidebarMenu.sort_order)
            .all()
        )
        return render_template("sidebar_menu_admin.html", top_menus=top_menus)

    @app.route("/admin/sidebar-menu/tambah", methods=["GET", "POST"])
    @superadmin_required
    def sidebar_menu_add():
        if request.method == "POST":
            menu = _fill_from_form(SidebarMenu())
            if menu is None:
                return render_template(
                    "sidebar_menu_form.html",
                    mode="add", all_roles=ALL_ROLES,
                    icon_options=ICON_OPTIONS,
                    parent_choices=_parent_choices(),
                    form=request.form,
                )
            db.session.add(menu)
            db.session.commit()
            flash(f'Menu "{menu.label}" berhasil ditambahkan.', "success")
            # Auto-create CMS page jika diminta
            if request.form.get("auto_create_cms") == "1":
                from urllib.parse import urlencode
                params = urlencode({
                    "name": menu.label,
                    "parent_menu_id": menu.id if menu.parent_id else "",
                    "icon": menu.icon,
                })
                return redirect(f"/control-center/cms-builder/new?{params}")
            return redirect(url_for("sidebar_menu_admin"))
        return render_template(
            "sidebar_menu_form.html",
            mode="add", all_roles=ALL_ROLES,
            icon_options=ICON_OPTIONS,
            parent_choices=_parent_choices(),
            form={},
        )

    @app.route("/admin/sidebar-menu/<int:menu_id>/ubah", methods=["GET", "POST"])
    @superadmin_required
    def sidebar_menu_edit(menu_id):
        menu = db.session.get(SidebarMenu, menu_id)
        if not menu:
            abort(404)
        if request.method == "POST":
            updated = _fill_from_form(menu)
            if updated is not None:
                db.session.commit()
                flash(f'Menu "{menu.label}" berhasil diperbarui.', "success")
            return redirect(url_for("sidebar_menu_admin"))
        return render_template(
            "sidebar_menu_form.html",
            mode="edit", all_roles=ALL_ROLES,
            icon_options=ICON_OPTIONS,
            parent_choices=_parent_choices(exclude_id=menu_id),
            editing=menu, form={},
        )

    @app.route("/admin/sidebar-menu/<int:menu_id>/hapus", methods=["POST"])
    @superadmin_required
    def sidebar_menu_delete(menu_id):
        menu = db.session.get(SidebarMenu, menu_id)
        if not menu:
            abort(404)
        if menu.is_system:
            flash("Menu sistem tidak dapat dihapus, hanya bisa dinonaktifkan.", "danger")
            return redirect(url_for("sidebar_menu_admin"))
        label = menu.label
        db.session.delete(menu)
        db.session.commit()
        flash(f'Menu "{label}" telah dihapus.', "success")
        return redirect(url_for("sidebar_menu_admin"))

    @app.route("/admin/sidebar-menu/<int:menu_id>/toggle", methods=["POST"])
    @superadmin_required
    def sidebar_menu_toggle(menu_id):
        menu = db.session.get(SidebarMenu, menu_id)
        if not menu:
            abort(404)
        menu.is_active = not menu.is_active
        menu.updated_at = datetime.utcnow()
        db.session.commit()
        state = "diaktifkan" if menu.is_active else "dinonaktifkan"
        flash(f'Menu "{menu.label}" berhasil {state}.', "success")
        return redirect(url_for("sidebar_menu_admin"))

    @app.route("/admin/sidebar-menu/<int:menu_id>/naik", methods=["POST"])
    @superadmin_required
    def sidebar_menu_move_up(menu_id):
        _reorder(menu_id, "up")
        return redirect(url_for("sidebar_menu_admin"))

    @app.route("/admin/sidebar-menu/<int:menu_id>/turun", methods=["POST"])
    @superadmin_required
    def sidebar_menu_move_down(menu_id):
        _reorder(menu_id, "down")
        return redirect(url_for("sidebar_menu_admin"))

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _parent_choices(exclude_id=None):
        q = SidebarMenu.query.filter_by(parent_id=None).order_by(SidebarMenu.sort_order)
        if exclude_id:
            q = q.filter(SidebarMenu.id != exclude_id)
        return [(m.id, m.label) for m in q.all()]

    def _fill_from_form(menu):
        label = request.form.get("label", "").strip()
        if not label:
            flash("Nama menu tidak boleh kosong.", "danger")
            return None
        menu.label           = label
        menu.icon            = request.form.get("icon", "fa-circle").strip() or "fa-circle"
        menu.endpoint        = request.form.get("endpoint", "").strip()
        menu.url             = request.form.get("url", "").strip()
        menu.active_endpoints= request.form.get("active_endpoints", "").strip()
        menu.url_param       = request.form.get("url_param", "").strip()
        menu.badge_key       = request.form.get("badge_key", "").strip()
        menu.extra_style     = request.form.get("extra_style", "").strip()
        menu.description     = request.form.get("description", "").strip()
        menu.menu_function   = request.form.get("menu_function", "").strip()
        menu.menu_purpose    = request.form.get("menu_purpose", "").strip()
        raw_pid              = request.form.get("parent_id", "").strip()
        menu.parent_id       = int(raw_pid) if raw_pid.isdigit() else None
        so                   = request.form.get("sort_order", "0").strip()
        menu.sort_order      = int(so) if so.lstrip("-").isdigit() else 0
        menu.is_active       = request.form.get("is_active") == "1"
        selected_roles       = request.form.getlist("roles")
        menu.roles           = ",".join(selected_roles) if selected_roles else "admin_utama"
        menu.updated_at      = datetime.utcnow()
        return menu

    def _reorder(menu_id, direction):
        menu = db.session.get(SidebarMenu, menu_id)
        if not menu:
            return
        siblings = (
            SidebarMenu.query
            .filter_by(parent_id=menu.parent_id)
            .order_by(SidebarMenu.sort_order, SidebarMenu.id)
            .all()
        )
        idx = next((i for i, m in enumerate(siblings) if m.id == menu_id), None)
        if idx is None:
            return
        if direction == "up" and idx > 0:
            other = siblings[idx - 1]
        elif direction == "down" and idx < len(siblings) - 1:
            other = siblings[idx + 1]
        else:
            return
        # Swap sort orders
        so1, so2 = menu.sort_order, other.sort_order
        if so1 == so2:
            so1 = so2 - 1 if direction == "up" else so2 + 1
        menu.sort_order  = so2
        other.sort_order = so1
        menu.updated_at  = other.updated_at = datetime.utcnow()
        db.session.commit()

    return SidebarMenu
