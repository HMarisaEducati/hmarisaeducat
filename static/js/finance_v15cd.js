(() => {
  const selectAll = document.querySelector('[data-select-all-payments]');
  const paymentBoxes = [...document.querySelectorAll('[data-payment-checkbox]')];
  if (selectAll) selectAll.addEventListener('change', () => paymentBoxes.forEach(box => { box.checked = selectAll.checked; }));

  document.querySelectorAll('[data-bulk-receipts]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!paymentBoxes.some(box => box.checked)) {
        event.preventDefault();
        window.alert('Pilih minimal satu transaksi untuk dicetak.');
      }
    });
  });

  document.querySelectorAll('[data-finance-filter]').forEach(form => {
    const key = `finance-filter:${form.dataset.financeFilter || 'default'}`;
    form.addEventListener('submit', () => {
      const values = {};
      new FormData(form).forEach((value, name) => { if (name !== 'preview') values[name] = value; });
      try { localStorage.setItem(key, JSON.stringify(values)); } catch (_) {}
    });
  });
})();
