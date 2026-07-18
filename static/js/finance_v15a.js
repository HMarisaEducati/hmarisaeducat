(() => {
  const root = document.querySelector('[data-finance-settings]');
  if (!root) return;

  let submitted = false;
  const dirtyForms = [...root.querySelectorAll('[data-dirty-form]')];
  dirtyForms.forEach((form) => {
    let dirty = false;
    form.addEventListener('input', () => { dirty = true; });
    form.addEventListener('change', () => { dirty = true; });
    form.addEventListener('submit', () => {
      submitted = true;
      dirty = false;
      const button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.dataset.originalText = button.innerHTML;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Menyimpan...';
      }
    });
    form.dataset.isDirty = () => dirty;
    form.addEventListener('reset', () => { dirty = false; });
  });

  window.addEventListener('beforeunload', (event) => {
    if (submitted) return;
    const hasDirty = dirtyForms.some((form) => {
      const fields = [...form.elements].filter((el) => ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName));
      return fields.some((field) => {
        if (field.type === 'checkbox' || field.type === 'radio') return field.checked !== field.defaultChecked;
        return field.value !== field.defaultValue;
      });
    });
    if (hasDirty) {
      event.preventDefault();
      event.returnValue = '';
    }
  });

  root.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm || 'Lanjutkan perubahan ini?')) {
        event.preventDefault();
        submitted = false;
      }
    });
  });

  const channelType = root.querySelector('[data-channel-type]');
  const updateChannelFields = () => {
    if (!channelType) return;
    const isQris = channelType.value === 'qris';
    root.querySelectorAll('[data-bank-field]').forEach((el) => el.classList.toggle('is-hidden', isQris));
    root.querySelectorAll('[data-qris-field]').forEach((el) => el.classList.toggle('is-hidden', !isQris));
    const preview = document.getElementById('new-qris-preview');
    if (preview && !isQris) preview.classList.add('is-hidden');
  };
  if (channelType) {
    channelType.addEventListener('change', updateChannelFields);
    updateChannelFields();
  }

  root.querySelectorAll('[data-image-input]').forEach((input) => {
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      const targetId = input.dataset.previewTarget;
      const target = targetId ? document.getElementById(targetId) : null;
      if (!file || !target) return;
      if (!file.type.startsWith('image/')) {
        window.alert('File harus berupa gambar.');
        input.value = '';
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        window.alert('Ukuran gambar maksimal 5 MB.');
        input.value = '';
        return;
      }
      const url = URL.createObjectURL(file);
      target.classList.remove('is-hidden');
      if (target.tagName === 'IMG') {
        target.src = url;
      } else {
        target.innerHTML = '';
        const image = document.createElement('img');
        image.alt = 'Preview gambar';
        image.src = url;
        target.appendChild(image);
      }
    });
  });
})();
