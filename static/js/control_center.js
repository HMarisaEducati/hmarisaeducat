/* Control Center v1 — TPQ HMarisa */
(function () {
  'use strict';

  // ── Theme ───────────────────────────────────
  const html = document.documentElement;
  const savedTheme = localStorage.getItem('cc-theme') || 'light';
  html.dataset.ccTheme = savedTheme;

  const themeToggle = document.getElementById('themeToggle');
  const themeIcon   = document.getElementById('themeIcon');
  const themeLabel  = document.getElementById('themeLabel');

  function applyTheme(t) {
    html.dataset.ccTheme = t;
    localStorage.setItem('cc-theme', t);
    if (themeIcon)  themeIcon.className  = t === 'dark' ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
    if (themeLabel) themeLabel.textContent = t === 'dark' ? 'Light Mode' : 'Dark Mode';
  }

  applyTheme(savedTheme);

  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      applyTheme(html.dataset.ccTheme === 'dark' ? 'light' : 'dark');
    });
  }

  // ── Sidebar collapse ────────────────────────
  const sidebar = document.getElementById('ccSidebar');
  const sidebarToggle = document.getElementById('sidebarToggle');
  const mainEl = document.querySelector('.cc-main');

  const collapsed = localStorage.getItem('cc-sidebar') === '1';
  if (collapsed && sidebar) sidebar.classList.add('collapsed');

  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', function () {
      sidebar.classList.toggle('collapsed');
      localStorage.setItem('cc-sidebar', sidebar.classList.contains('collapsed') ? '1' : '0');
    });
  }

  // ── Mobile sidebar ──────────────────────────
  const mobileToggle = document.getElementById('mobileToggle');
  const overlay = document.getElementById('ccOverlay');

  function closeMobileSidebar() {
    sidebar && sidebar.classList.remove('mobile-open');
    overlay && overlay.classList.remove('open');
  }

  if (mobileToggle) {
    mobileToggle.addEventListener('click', function () {
      sidebar.classList.toggle('mobile-open');
      overlay.classList.toggle('open');
    });
  }

  if (overlay) {
    overlay.addEventListener('click', closeMobileSidebar);
  }

  // ── Flash auto-dismiss ───────────────────────
  document.querySelectorAll('.cc-flash').forEach(function (el) {
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transition = 'opacity .4s';
      setTimeout(function () { el.remove(); }, 400);
    }, 5000);
  });

  // ── Global search ────────────────────────────
  const searchInput   = document.getElementById('ccGlobalSearch');
  const searchResults = document.getElementById('ccSearchResults');

  if (searchInput && searchResults) {
    let timer;

    searchInput.addEventListener('input', function () {
      clearTimeout(timer);
      const q = this.value.trim();
      if (q.length < 2) {
        searchResults.classList.remove('open');
        searchResults.innerHTML = '';
        return;
      }
      timer = setTimeout(function () {
        fetch('/control-center/search?q=' + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.results || data.results.length === 0) {
              searchResults.innerHTML = '<div class="cc-search-empty">Tidak ada hasil untuk "' + q + '"</div>';
            } else {
              searchResults.innerHTML = data.results.map(function (r) {
                return '<a class="cc-search-result-item" href="' + r.url + '">'
                  + '<i class="fa-solid ' + r.icon + '"></i>'
                  + '<div><div class="cc-sr-label">' + r.label + '</div>'
                  + '<div class="cc-sr-sub">' + r.category + '</div></div>'
                  + '</a>';
              }).join('');
            }
            searchResults.classList.add('open');
          })
          .catch(function () {
            searchResults.classList.remove('open');
          });
      }, 300);
    });

    document.addEventListener('click', function (e) {
      if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
        searchResults.classList.remove('open');
      }
    });
  }

  // ── Notification panel ──────────────────────
  const notifBell  = document.getElementById('notifBell');
  const notifPanel = document.getElementById('notifPanel');

  if (notifBell && notifPanel) {
    notifBell.addEventListener('click', function (e) {
      e.stopPropagation();
      notifPanel.classList.toggle('open');
    });

    document.addEventListener('click', function (e) {
      if (notifPanel && !notifPanel.contains(e.target) && !notifBell.contains(e.target)) {
        notifPanel.classList.remove('open');
      }
    });
  }

  // ── Confirm delete modals ────────────────────
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      if (!confirm(this.dataset.confirm || 'Apakah Anda yakin?')) {
        e.preventDefault();
      }
    });
  });

  // ── Inline filter for tables ─────────────────
  const tableFilter = document.getElementById('tableFilter');
  if (tableFilter) {
    tableFilter.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll('.cc-table tbody tr').forEach(function (row) {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? '' : 'none';
      });
    });
  }

  // ── Auto-render charts if Chart.js is loaded ─
  window.ccRenderChart = function (id, type, labels, datasets, options) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    if (!window.Chart) {
      // Lazy-load Chart.js
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
      script.onload = function () { doRender(); };
      document.head.appendChild(script);
    } else {
      doRender();
    }

    function doRender() {
      const ctx = canvas.getContext('2d');
      const isDark = document.documentElement.dataset.ccTheme === 'dark';
      const gridColor = isDark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.06)';
      const textColor = isDark ? '#94a3b8' : '#6b7280';

      new window.Chart(ctx, {
        type: type,
        data: { labels: labels, datasets: datasets },
        options: Object.assign({
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: textColor, font: { family: 'Inter', size: 11 } } }
          },
          scales: type !== 'pie' && type !== 'doughnut' ? {
            x: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
            y: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } }
          } : {}
        }, options || {})
      });
    }
  };

  // ── Copy to clipboard ────────────────────────
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      navigator.clipboard && navigator.clipboard.writeText(this.dataset.copy).then(function () {
        btn.textContent = 'Tersalin!';
        setTimeout(function () { btn.textContent = 'Salin'; }, 2000);
      });
    });
  });

  // ── Password show/hide ───────────────────────
  document.querySelectorAll('[data-toggle-pw]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const target = document.getElementById(this.dataset.togglePw);
      if (!target) return;
      const isText = target.type === 'text';
      target.type = isText ? 'password' : 'text';
      this.querySelector('i').className = 'fa-solid ' + (isText ? 'fa-eye' : 'fa-eye-slash');
    });
  });

})();

  // ── FAB (Floating Action Button) ─────────────
  (function () {
    var fabMain = document.getElementById('ccFabMain');
    var fabMenu = document.getElementById('ccFabMenu');
    if (!fabMain || !fabMenu) return;

    fabMain.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = fabMenu.classList.toggle('open');
      fabMain.classList.toggle('open', open);
    });

    document.addEventListener('click', function (e) {
      if (!fabMenu.contains(e.target) && e.target !== fabMain) {
        fabMenu.classList.remove('open');
        fabMain.classList.remove('open');
      }
    });

    // FAB confirm items — submit as POST form
    fabMenu.querySelectorAll('.cc-fab-confirm').forEach(function (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        var msg = this.getAttribute('onclick') ? null : 'Yakin?';
        var confirmed = msg ? confirm(msg) : true;
        if (!confirmed) return;
        var form = document.getElementById('ccFabBackupForm');
        if (form) form.submit();
      });
    });
  })();

  // ── Notification Bell Dropdown ────────────────
  (function () {
    var bell = document.getElementById('notifBell');
    var drop = document.getElementById('notifDropdown');
    if (!bell || !drop) return;

    bell.addEventListener('click', function (e) {
      e.stopPropagation();
      drop.classList.toggle('open');
    });

    document.addEventListener('click', function (e) {
      if (!bell.contains(e.target)) {
        drop.classList.remove('open');
      }
    });
  })();

