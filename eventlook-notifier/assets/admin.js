(function () {
  function flash(button, label) {
    const original = button.textContent;
    button.textContent = label;
    setTimeout(function () { button.textContent = original; }, 1500);
  }

  document.addEventListener('click', function (event) {
    const copy = event.target.closest('.eln-copy');
    if (copy) {
      const field = document.querySelector(copy.dataset.target);
      field.select();
      field.setSelectionRange(0, 99999);
      navigator.clipboard.writeText(field.value).then(function () {
        flash(copy, ELN.copied);
      });
      return;
    }

    const toggle = event.target.closest('.eln-toggle');
    if (toggle) {
      const pre = toggle.parentNode.querySelector('.eln-raw');
      pre.hidden = !pre.hidden;
      return;
    }

    const sounds = event.target.closest('#eln-sounds');
    if (sounds) {
      const list = document.getElementById('eln-sound-list');
      const field = document.getElementById('eln-po-sound');
      const result = document.getElementById('eln-sound-result');

      sounds.disabled = true;
      sounds.textContent = ELN.loading;
      result.textContent = '';
      result.className = 'eln-result';

      fetch(ELN.ajaxUrl, {
        method: 'POST',
        credentials: 'same-origin',
        body: new URLSearchParams({ action: 'eln_sounds', nonce: ELN.nonce })
      })
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          if (!payload.success) {
            result.textContent = payload.data.message;
            result.className = 'eln-result eln-fail';
            return;
          }

          list.innerHTML = '';
          Object.keys(payload.data.sounds).forEach(function (key) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = payload.data.sounds[key] + ' (' + key + ')';
            option.selected = key === field.value;
            list.appendChild(option);
          });
          list.hidden = false;
          list.onchange = function () { field.value = list.value; };
        })
        .catch(function (error) {
          result.textContent = String(error);
          result.className = 'eln-result eln-fail';
        })
        .finally(function () {
          sounds.disabled = false;
          sounds.textContent = ELN.sounds;
        });

      return;
    }

    const test = event.target.closest('#eln-test');
    if (!test) {
      return;
    }

    const result = document.getElementById('eln-test-result');
    test.disabled = true;
    test.textContent = ELN.sending;
    result.textContent = '';
    result.className = 'eln-result';

    const body = new URLSearchParams({ action: 'eln_test', nonce: ELN.nonce });

    fetch(ELN.ajaxUrl, { method: 'POST', credentials: 'same-origin', body: body })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        result.textContent = payload.data && payload.data.message ? payload.data.message : '';
        result.className = 'eln-result ' + (payload.success ? 'eln-ok' : 'eln-fail');
      })
      .catch(function (error) {
        result.textContent = String(error);
        result.className = 'eln-result eln-fail';
      })
      .finally(function () {
        test.disabled = false;
        test.textContent = ELN.test;
      });
  });
})();
