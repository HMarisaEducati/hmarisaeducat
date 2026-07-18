(() => {
  const root = document.querySelector('.finance-v15b-page, .finance-v15a-page');
  if (!root) return;

  const classSelect = document.querySelector('[data-finance-class]');
  const wholeClass = document.querySelector('[data-whole-class]');
  const studentLabels = [...document.querySelectorAll('[data-student-class]')];
  const filterStudents = () => {
    const selectedClass = classSelect?.value || '';
    studentLabels.forEach(label => {
      const visible = !selectedClass || label.dataset.studentClass === selectedClass;
      label.hidden = !visible;
      const checkbox = label.querySelector('input[type="checkbox"]');
      if (checkbox) checkbox.disabled = !visible || Boolean(wholeClass?.checked);
    });
  };
  classSelect?.addEventListener('change', filterStudents);
  wholeClass?.addEventListener('change', filterStudents);
  filterStudents();

  const chargeType = document.querySelector('[data-charge-type]');
  const amount = document.querySelector('[data-bill-amount]');
  const dueDate = document.querySelector('[data-due-date]');
  const periodLabel = document.querySelector('[data-period-label]');
  const periodYear = document.querySelector('[data-period-year]');
  const months = {Januari:1,Februari:2,Maret:3,April:4,Mei:5,Juni:6,Juli:7,Agustus:8,September:9,Oktober:10,November:11,Desember:12};
  const setDefaults = () => {
    const option = chargeType?.selectedOptions?.[0];
    if (option && amount && !amount.value) amount.value = option.dataset.amount || '';
    const month = months[periodLabel?.value];
    const year = Number(periodYear?.value || 0);
    const day = Number(option?.dataset.dueDay || 10);
    if (month && year && dueDate && !dueDate.value) {
      const last = new Date(year, month, 0).getDate();
      dueDate.value = `${year}-${String(month).padStart(2,'0')}-${String(Math.min(day,last)).padStart(2,'0')}`;
    }
  };
  chargeType?.addEventListener('change', () => { if (amount) amount.value = ''; if (dueDate) dueDate.value = ''; setDefaults(); });
  periodLabel?.addEventListener('change', () => { if (dueDate) dueDate.value = ''; setDefaults(); });
  periodYear?.addEventListener('change', () => { if (dueDate) dueDate.value = ''; setDefaults(); });
  setDefaults();

  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm(form.dataset.confirm || 'Lanjutkan?')) event.preventDefault();
    });
  });

  let dirty = false;
  const draftForm = document.querySelector('form[data-finance-draft]');
  if (draftForm) {
    const key = `tpq-finance-draft:${draftForm.dataset.financeDraft}`;
    const serialize = () => {
      const data = {};
      new FormData(draftForm).forEach((value, name) => {
        if (value instanceof File) return;
        if (data[name] === undefined) data[name] = value;
        else data[name] = Array.isArray(data[name]) ? [...data[name], value] : [data[name], value];
      });
      return data;
    };
    const save = () => { try { localStorage.setItem(key, JSON.stringify({savedAt:Date.now(),data:serialize()})); } catch (_) {} };
    let timer;
    draftForm.addEventListener('input', () => { dirty = true; clearTimeout(timer); timer = setTimeout(save, 350); });
    draftForm.addEventListener('change', () => { dirty = true; clearTimeout(timer); timer = setTimeout(save, 350); });
    draftForm.addEventListener('submit', () => { dirty = false; try { localStorage.removeItem(key); } catch (_) {} });
    try {
      const stored = JSON.parse(localStorage.getItem(key) || 'null');
      if (stored?.data && Date.now() - stored.savedAt < 7*24*60*60*1000 && !document.querySelector('.preview-panel') && window.confirm('Ditemukan draft yang belum disimpan. Lanjutkan draft?')) {
        Object.entries(stored.data).forEach(([name,value]) => {
          const values = Array.isArray(value) ? value : [value];
          draftForm.querySelectorAll(`[name="${CSS.escape(name)}"]`).forEach(field => {
            if (field.type === 'checkbox' || field.type === 'radio') field.checked = values.includes(field.value);
            else if (values.length) field.value = values[0];
          });
        });
        filterStudents(); setDefaults();
      }
    } catch (_) {}
    window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  }

  const filterForm = document.querySelector('form[data-finance-filter]');
  if (filterForm) {
    const key = `tpq-finance-filter:${filterForm.dataset.financeFilter}`;
    filterForm.addEventListener('change', () => {
      const data = Object.fromEntries(new FormData(filterForm).entries());
      try { localStorage.setItem(key, JSON.stringify(data)); } catch (_) {}
    });
  }

  document.querySelectorAll('button[data-loading-text]').forEach(button => {
    button.closest('form')?.addEventListener('submit', () => {
      button.disabled = true;
      button.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${button.dataset.loadingText}`;
      root.classList.add('finance-loading');
    });
  });

  const started = Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || dirty || Date.now() - started < 60000 || document.querySelector('.finance-refresh-banner')) return;
    const banner = document.createElement('div');
    banner.className = 'finance-refresh-banner';
    banner.innerHTML = '<span>Data mungkin telah diperbarui oleh admin lain.</span><button type="button">Muat Data Terbaru</button>';
    banner.querySelector('button').addEventListener('click', () => location.reload());
    document.body.appendChild(banner);
  });
})();
