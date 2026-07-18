(() => {
  const raw = document.getElementById('portal-experience-config');
  let config = {};
  try { config = raw ? JSON.parse(raw.textContent || '{}') : {}; } catch (_) { config = {}; }
  const body = document.body;
  const theme = config.theme || {};
  if (theme.enabled) {
    const vars = {
      '--pe-primary': theme.primary,
      '--pe-secondary': theme.secondary,
      '--pe-accent': theme.accent,
      '--pe-bg': theme.page_bg,
      '--pe-surface': theme.surface,
      '--pe-text': theme.text,
      '--pe-radius': theme.card_radius === 'compact' ? '10px' : (theme.card_radius === 'soft' ? '24px' : '18px'),
      '--pe-custom-image': theme.banner_image_url || theme.header_image_url || theme.entry_image_url || theme.login_image_url ? `url("${theme.banner_image_url || theme.header_image_url || theme.entry_image_url || theme.login_image_url}")` : 'none'
    };
    Object.entries(vars).forEach(([key, value]) => { if (value) body.style.setProperty(key, value); });
    body.dataset.fontScale = theme.font_scale || 'normal';
    body.dataset.density = theme.density || 'comfortable';
    body.dataset.sidebarStyle = theme.sidebar_style || 'solid';
  }
  if (config.navigation_enabled) {
    const menu = config.navigation || {};
    document.querySelectorAll('[data-portal-menu-key]').forEach((link) => {
      const row = menu[link.dataset.portalMenuKey];
      if (!row) return;
      if (row.visible === false && link.dataset.portalMenuKey !== 'settings') { link.hidden = true; return; }
      link.style.order = String(row.order || 100);
      const label = link.querySelector('[data-menu-label]');
      if (label) label.firstChild ? label.firstChild.nodeValue = row.label || label.textContent : label.textContent = row.label || label.textContent;
      const icon = link.querySelector('i');
      if (icon && row.icon) {
        [...icon.classList].filter((name) => name.startsWith('fa-') && name !== 'fa-solid').forEach((name) => icon.classList.remove(name));
        icon.classList.add(row.icon);
      }
    });
  }
})();
