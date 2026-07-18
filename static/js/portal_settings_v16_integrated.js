(() => {
  const root = document.querySelector('[data-settings-page]');
  if (!root) return;
  const palettes = {
    current: {primary:'#075F46',secondary:'#0B7657',accent:'#D2A62C',page_bg:'#F4F8F6',surface:'#FFFFFF',text:'#17212B'},
    'green-gold': {primary:'#064E3B',secondary:'#0A7A58',accent:'#D4A72C',page_bg:'#F8F7F1',surface:'#FFFFFF',text:'#18352C'},
    minimal: {primary:'#305F52',secondary:'#4E7B6F',accent:'#97AD9F',page_bg:'#F6F8F7',surface:'#FFFFFF',text:'#253630'},
    'child-friendly': {primary:'#087A58',secondary:'#1FA475',accent:'#F1B943',page_bg:'#F5FBF8',surface:'#FFFFFF',text:'#173C31'}
  };
  root.querySelectorAll('[data-theme-form]').forEach((form) => {
    const presetInput = form.querySelector('[data-preset-input]');
    form.querySelectorAll('[data-preset]').forEach((button) => {
      if (presetInput && presetInput.value === button.dataset.preset) button.classList.add('is-active');
      button.addEventListener('click', () => {
        const values = palettes[button.dataset.preset] || palettes.current;
        Object.entries(values).forEach(([key,value]) => {
          const input = form.querySelector(`[name="${key}"]`); if (!input) return; input.value = value; input.dispatchEvent(new Event('input',{bubbles:true}));
        });
        if (presetInput) presetInput.value = button.dataset.preset;
        form.querySelectorAll('[data-preset]').forEach((node) => node.classList.toggle('is-active', node === button));
      });
    });
  });
  root.querySelectorAll('.ps16x-color input[type=color]').forEach((input) => {
    const code = input.parentElement.querySelector('code');
    input.addEventListener('input', () => { if (code) code.textContent = input.value.toUpperCase(); });
  });
  const reportPalettes = {
    current:{primary:'#075B46',primary_dark:'#043D31',accent:'#C9972E',accent_light:'#E8C56B',soft:'#EAF4EE'},
    emerald:{primary:'#0B7A5B',primary_dark:'#064B39',accent:'#D7AA3B',accent_light:'#F0D27F',soft:'#E7F7F0'},
    'navy-gold':{primary:'#224A66',primary_dark:'#102E43',accent:'#C49A3A',accent_light:'#E8CB7A',soft:'#EAF1F6'},
    minimal:{primary:'#3E6659',primary_dark:'#25453B',accent:'#93A59B',accent_light:'#C7D2CC',soft:'#F1F5F3'}
  };
  root.querySelectorAll('[data-eraport-preset]').forEach((button) => button.addEventListener('click', () => {
    const form = button.closest('form'); const values = reportPalettes[button.dataset.eraportPreset] || reportPalettes.current;
    Object.entries(values).forEach(([key,value]) => { const input=form.querySelector(`[name="${key}"]`); if(input){input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));} });
    const hidden=form.querySelector('[data-eraport-preset-input]'); if(hidden) hidden.value=button.dataset.eraportPreset;
  }));
})();
