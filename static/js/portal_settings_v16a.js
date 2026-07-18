(() => {
  const root = document.querySelector('[data-settings-page]');
  if (!root) return;
  root.querySelectorAll('[data-image-input]').forEach((input) => {
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      const key = input.getAttribute('data-image-input');
      const preview = root.querySelector(`[data-image-preview="${key}"]`);
      if (!file || !preview) return;
      const url = URL.createObjectURL(file);
      preview.src = url;
      preview.onload = () => URL.revokeObjectURL(url);
    });
  });
  root.querySelectorAll('[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.getAttribute('data-confirm'))) event.preventDefault();
    });
  });
  const modal = root.querySelector('[data-publish-modal]');
  const open = root.querySelector('[data-publish-open]');
  if (modal && open) {
    const close = () => { modal.hidden = true; document.body.style.overflow = ''; };
    open.addEventListener('click', () => { modal.hidden = false; document.body.style.overflow = 'hidden'; });
    modal.querySelectorAll('[data-publish-close]').forEach((button) => button.addEventListener('click', close));
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !modal.hidden) close(); });
  }
  root.querySelectorAll('[data-dirty-form]').forEach((form) => {
    let dirty = false;
    form.addEventListener('input', () => { dirty = true; });
    form.addEventListener('change', () => { dirty = true; });
    form.addEventListener('submit', () => { dirty = false; });
    window.addEventListener('beforeunload', (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    });
  });
})();