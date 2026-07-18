(() => {
  const root = document.querySelector('.finance-admin-v15b2-page');
  if (!root) return;

  const classSelect = root.querySelector('[data-admin-class-select]');
  const filterForm = root.querySelector('[data-admin-filter-form]');
  classSelect?.addEventListener('change', () => {
    if (!classSelect.value) return;
    const submit = filterForm?.querySelector('button[type="submit"]');
    if (submit) {
      submit.disabled = true;
      submit.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sedang memuat data...';
    }
    filterForm?.submit();
  });


  root.querySelectorAll('.finance-action-menu').forEach(menu => {
    menu.addEventListener('toggle', () => {
      if (!menu.open) return;
      root.querySelectorAll('.finance-action-menu[open]').forEach(other => {
        if (other !== menu) other.removeAttribute('open');
      });
    });
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.finance-action-menu')) {
      root.querySelectorAll('.finance-action-menu[open]').forEach(menu => menu.removeAttribute('open'));
    }
  });

  const offline = root.querySelector('[data-finance-offline]');
  const updateNetwork = () => { if (offline) offline.hidden = navigator.onLine; };
  window.addEventListener('online', updateNetwork);
  window.addEventListener('offline', updateNetwork);
  updateNetwork();

  const paymentForm = root.querySelector('[data-payment-form]');
  if (paymentForm) {
    const method = paymentForm.querySelector('[data-payment-method]');
    const channelWrap = paymentForm.querySelector('[data-payment-channel-wrap]');
    const channel = channelWrap?.querySelector('select');
    const amount = paymentForm.querySelector('[data-payment-amount]');
    const overpaymentWrap = paymentForm.querySelector('[data-overpayment-wrap]');
    const remaining = Number(paymentForm.dataset.remaining || 0);
    const dialog = root.querySelector('[data-payment-preview-dialog]');

    const rupiah = value => new Intl.NumberFormat('id-ID', {style:'currency', currency:'IDR', maximumFractionDigits:0}).format(Number(value || 0));
    const updateMethod = () => {
      const transfer = method?.value === 'Transfer';
      if (channelWrap) channelWrap.hidden = !transfer;
      if (channel) channel.required = transfer;
    };
    const updateOverpayment = () => {
      const current = Number(amount?.value || 0);
      if (overpaymentWrap) overpaymentWrap.hidden = !(current > remaining);
    };
    method?.addEventListener('change', updateMethod);
    amount?.addEventListener('input', updateOverpayment);
    updateMethod(); updateOverpayment();

    root.querySelector('[data-preview-payment]')?.addEventListener('click', () => {
      if (!paymentForm.reportValidity()) return;
      const pay = Number(amount?.value || 0);
      const after = remaining - pay;
      const over = pay > remaining;
      const allow = paymentForm.querySelector('[name="allow_overpayment"]')?.checked;
      if (over && !allow) {
        overpaymentWrap.hidden = false;
        paymentForm.querySelector('[name="allow_overpayment"]')?.focus();
        return;
      }
      dialog.querySelector('[data-preview-amount]').textContent = rupiah(pay);
      dialog.querySelector('[data-preview-remaining]').textContent = rupiah(Math.max(0, after));
      dialog.querySelector('[data-preview-status]').textContent = after <= 0 ? 'Lunas' : 'Sebagian';
      dialog.querySelector('[data-preview-method]').textContent = method?.value || 'Belum diisi';
      dialog.querySelector('[data-preview-date]').textContent = paymentForm.querySelector('[name="payment_date"]')?.value || 'Belum diisi';
      dialog.querySelector('[data-preview-receiver]').textContent = paymentForm.querySelector('[name="receiver_name"]')?.value || 'Belum diisi';
      const warning = dialog.querySelector('[data-preview-overpayment]');
      if (warning) warning.hidden = !over;
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else if (window.confirm(`Simpan pembayaran ${rupiah(pay)}?`)) paymentForm.requestSubmit();
    });

    root.querySelector('[data-confirm-payment]')?.addEventListener('click', event => {
      if (!paymentForm.reportValidity()) return;
      event.currentTarget.disabled = true;
      event.currentTarget.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sedang menyimpan...';
      dialog?.close();
      const submitter = document.createElement('button');
      submitter.type = 'submit';
      submitter.hidden = true;
      paymentForm.appendChild(submitter);
      submitter.click();
    });
  }
})();
