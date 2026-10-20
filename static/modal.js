/* Custom modal dialogs for the law firm app — Card Flow design language.
   Replaces native confirm()/alert()/prompt() with styled, themed modals.

   API:
     showConfirm({title, message, confirmText, cancelText, danger, icon}) -> Promise<boolean>
     showAlert({title, message, buttonText, icon})                        -> Promise<void>
     showPrompt({title, message, defaultValue, placeholder, confirmText, cancelText}) -> Promise<string|null>

   Keyboard: Enter confirms, Escape cancels.
   Click-outside dismisses (except danger confirms).
   Danger variant focuses Cancel by default; others focus Confirm.
*/
(function () {
  'use strict';

  /* Inline SVG icons — same 24x24 stroke style as templates/_icons.html */
  var ICONS = {
    trash: '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/>',
    alert: '<path d="M12 3L2 20h20z"/><path d="M12 9.5V14"/><circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none"/>',
    checkmark: '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 4.5-5.5"/>',
    edit: '<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 10.5V17"/><circle cx="12" cy="7.5" r="0.6" fill="currentColor" stroke="none"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>'
  };

  function svgIcon(name, size) {
    size = size || 22;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || ICONS.info) + '</svg>';
  }

  var root = null;        // overlay element
  var current = null;     // active dialog state
  var lastFocus = null;   // element focused before opening

  function ensureRoot() {
    if (root) return root;
    root = document.createElement('div');
    root.className = 'modal-overlay';
    root.setAttribute('role', 'presentation');
    root.innerHTML =
      '<div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modalTitle">' +
        '<div class="modal-icon" id="modalIcon"></div>' +
        '<div class="modal-body">' +
          '<h3 class="modal-title" id="modalTitle"></h3>' +
          '<p class="modal-message" id="modalMessage"></p>' +
          '<div class="modal-input-wrap" id="modalInputWrap" hidden>' +
            '<input type="text" class="modal-input" id="modalInput" autocomplete="off">' +
          '</div>' +
        '</div>' +
        '<div class="modal-actions" id="modalActions"></div>' +
      '</div>';
    document.body.appendChild(root);

    // Click-outside-to-dismiss (only when allowed)
    root.addEventListener('mousedown', function (e) {
      if (e.target === root && current && current.dismissOutside) {
        close(false);
      }
    });

    // Keyboard
    document.addEventListener('keydown', function (e) {
      if (!current) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
      } else if (e.key === 'Enter' && current.kind !== 'prompt') {
        // Don't double-fire when focus is on a button (buttons handle Enter natively)
        if (document.activeElement && document.activeElement.tagName === 'BUTTON') return;
        e.preventDefault();
        close(true);
      }
    });

    return root;
  }

  function open(opts) {
    ensureRoot();
    lastFocus = document.activeElement;

    var iconEl = root.querySelector('#modalIcon');
    var titleEl = root.querySelector('#modalTitle');
    var msgEl = root.querySelector('#modalMessage');
    var inputWrap = root.querySelector('#modalInputWrap');
    var input = root.querySelector('#modalInput');
    var actions = root.querySelector('#modalActions');

    // Icon in colored circle — matches dashboard widget icon treatment
    var tone = opts.danger ? 'danger' : (opts.tone || 'info');
    iconEl.className = 'modal-icon modal-icon-' + tone;
    iconEl.innerHTML = svgIcon(opts.icon || (opts.danger ? 'trash' : 'info'));

    titleEl.textContent = opts.title || '';
    msgEl.textContent = opts.message || '';
    msgEl.style.display = opts.message ? '' : 'none';

    inputWrap.hidden = opts.kind !== 'prompt';
    if (opts.kind === 'prompt') {
      input.value = opts.defaultValue || '';
      input.placeholder = opts.placeholder || '';
    }

    // Buttons
    actions.innerHTML = '';
    function makeBtn(label, cls, value) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn ' + cls;
      b.textContent = label;
      b.addEventListener('click', function () { close(value); });
      return b;
    }

    if (opts.kind === 'alert') {
      actions.appendChild(makeBtn(opts.buttonText || 'OK', 'btn-primary', true));
    } else {
      actions.appendChild(makeBtn(opts.cancelText || 'Cancel', '', false));
      var confirmBtn = makeBtn(
        opts.confirmText || (opts.kind === 'prompt' ? 'OK' : 'Confirm'),
        opts.danger ? 'btn-modal-danger' : 'btn-primary',
        true
      );
      actions.appendChild(confirmBtn);
    }

    return new Promise(function (resolve) {
      current = {
        kind: opts.kind,
        resolve: resolve,
        dismissOutside: !opts.danger,   // danger modals require an explicit choice
        input: input
      };

      // Entrance animation
      root.classList.remove('modal-open');
      void root.offsetWidth; // reflow to restart animation
      root.classList.add('modal-open');

      // Focus: danger -> cancel (safe default), otherwise confirm / prompt input
      setTimeout(function () {
        var btns = actions.querySelectorAll('button');
        if (opts.kind === 'prompt') {
          input.focus();
          input.select();
        } else if (opts.danger) {
          if (btns[0]) btns[0].focus(); // Cancel first
        } else {
          var last = btns[btns.length - 1];
          if (last) last.focus();
        }
      }, 60);
    });
  }

  function close(value) {
    if (!current) return;
    var st = current;
    current = null;
    root.classList.remove('modal-open');

    var result = value;
    if (st.kind === 'prompt') {
      result = value ? st.input.value : null;
    } else if (st.kind === 'alert') {
      result = undefined;
    }
    st.resolve(result);

    if (lastFocus && lastFocus.focus) {
      try { lastFocus.focus(); } catch (e) { /* noop */ }
    }
  }

  /* Public API */
  window.showConfirm = function (opts) {
    return open(Object.assign({ kind: 'confirm' }, opts || {}));
  };

  window.showAlert = function (opts) {
    return open(Object.assign({ kind: 'alert', dismissOutside: true }, opts || {}));
  };

  window.showPrompt = function (opts) {
    return open(Object.assign({ kind: 'prompt' }, opts || {}));
  };

  /* Track WHICH submit button started a form submission. Some forms put
     routing data on the button itself (e.g. payroll's
     <button name="action" value="generate">) and the server only acts
     when that name/value arrives. programmatic form.submit() drops the
     submitter entirely — that was the v2.4.2 "Generate paychecks confirms
     then nothing happens" bug — so we remember the button and re-submit
     WITH it via requestSubmit(). Captured on click, in the capture
     phase, before the form's onsubmit runs. */
  var lastSubmitter = {};
  document.addEventListener('click', function (e) {
    var btn = null;
    var t = e.target;
    if (t && t.closest) {
      btn = t.closest('button, input[type="submit"]');
      // A <button> without a type defaults to "submit" inside a form.
      if (btn && btn.tagName === 'BUTTON' && (btn.type || 'submit') !== 'submit') btn = null;
    } else if (t && (t.type === 'submit')) {
      btn = t;
    }
    if (btn && btn.form) { lastSubmitter.form = btn.form; lastSubmitter.btn = btn; }
  }, true);

  /* Drop-in helper for form onsubmit handlers:
     onsubmit="return modalConfirmSubmit(this, 'Delete this?')"
     options: {title, danger, confirmText} */
  window.modalConfirmSubmit = function (form, message, opts) {
    // Second pass: requestSubmit() below re-fires onsubmit — don't reopen
    // the modal, just let the submission proceed (with submitter data).
    if (form._modalConfirmed) {
      form._modalConfirmed = false;
      return true;
    }
    opts = opts || {};
    var submitter = (lastSubmitter.form === form) ? lastSubmitter.btn : null;
    showConfirm({
      title: opts.title || 'Please confirm',
      message: message,
      confirmText: opts.confirmText || 'Delete',
      danger: opts.danger !== false
    }).then(function (ok) {
      if (!ok) return;
      form._modalConfirmed = true;
      if (form.requestSubmit) {
        try {
          // Submitter's name/value IS included, exactly like a real click.
          form.requestSubmit(submitter || undefined);
          return;
        } catch (err) { /* fall through to legacy submit */ }
      }
      // Last resort (very old browsers): plain submit. The submitter's
      // name/value is normally dropped by form.submit(), so inject it as
      // a hidden field first to preserve the form's intent.
      if (submitter && submitter.name) {
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = submitter.name;
        hidden.value = submitter.value;
        form.appendChild(hidden);
      }
      HTMLFormElement.prototype.submit.call(form);
    });
    return false;
  };
})();
