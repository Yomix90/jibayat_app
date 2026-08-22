// ── Sidebar collapse ─────────────────────────────────────
function toggleSidebarMenu() {
    const sb = document.getElementById('sidebar');
    sb.classList.toggle('collapsed');
    if (sb.classList.contains('collapsed')) {
        document.documentElement.style.setProperty('--sw', '72px');
        localStorage.setItem('sidebarCollapsed', '1');
    } else {
        document.documentElement.style.setProperty('--sw', '272px');
        localStorage.setItem('sidebarCollapsed', '0');
    }
}
if (localStorage.getItem('sidebarCollapsed') === '1') {
   document.getElementById('sidebar').classList.add('collapsed');
   document.documentElement.style.setProperty('--sw', '72px');
}

// ── User Dropdown Menu ──────────────────────────────────────
function toggleUserMenu() {
    const menu = document.getElementById('user-dropdown-menu');
    if (menu) {
        menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
    }
}

document.addEventListener('click', function(e) {
    const wrap = document.querySelector('.user-dropdown-wrap');
    const menu = document.getElementById('user-dropdown-menu');
    if (wrap && menu && !wrap.contains(e.target)) {
        menu.style.display = 'none';
    }
});

// ── Sub-menu toggle ──────────────────────────────────────
function toggleSubMenu(id) {
    const item = document.getElementById(id);
    const wasOpen = item.classList.contains('open');
    item.classList.toggle('open', !wasOpen);
    const openMenus = Array.from(document.querySelectorAll('.nav-item.open')).map(i => i.id);
    localStorage.setItem('openMenus', JSON.stringify(openMenus));
}

document.addEventListener('DOMContentLoaded', function() {
    try {
        const openMenus = JSON.parse(localStorage.getItem('openMenus') || '[]');
        openMenus.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.add('open');
        });
    } catch(e) {}
});

// ── Modals ───────────────────────────────────────────────
function openModal(id){document.getElementById(id).classList.add('active')}
function closeModal(id){document.getElementById(id).classList.remove('active')}
document.querySelectorAll('.modal-overlay').forEach(m=>{
  m.addEventListener('click',e=>{if(e.target===m)m.classList.remove('active')})
})
function showTab(tabId,btn){
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'))
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'))
  document.getElementById(tabId).classList.add('active')
  btn.classList.add('active')
}

// ── Clock ────────────────────────────────────────────────
function updateClock() {
  const clock = document.getElementById('topbar-clock');
  if(!clock) return;
  const now = new Date();
  const opts = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
  clock.innerHTML = '\uD83D\uDD52 ' + now.toLocaleDateString('fr-FR', opts);
}
setInterval(updateClock, 1000);
updateClock();

// ── Modale confirmation globale unifiée ───────────────────
let _confirmResolver = null;
let _confirmTargetForm = null;

const CONFIRM_TYPES = {
  danger: {
    icon: '🗑️',
    class: 'confirm-type-danger',
    okBg: 'linear-gradient(135deg, #ef4444, #dc2626)',
    okColor: '#ffffff',
    okLabel: 'Supprimer'
  },
  warning: {
    icon: '⚠️',
    class: 'confirm-type-warning',
    okBg: 'linear-gradient(135deg, #f59e0b, #d97706)',
    okColor: '#ffffff',
    okLabel: 'Confirmer'
  },
  success: {
    icon: '✅',
    class: 'confirm-type-success',
    okBg: 'linear-gradient(135deg, #10b981, #059669)',
    okColor: '#ffffff',
    okLabel: 'Valider'
  },
  info: {
    icon: 'ℹ️',
    class: 'confirm-type-info',
    okBg: 'linear-gradient(135deg, #3b82f6, #2563eb)',
    okColor: '#ffffff',
    okLabel: 'Continuer'
  }
};

/**
 * Affiche la boîte de confirmation unifiée.
 * Supporte Promise, callback et soumission de formulaire.
 */
function showConfirm(optsOrFn, extraOpts = {}) {
  let opts = {};
  let callback = null;

  if (typeof optsOrFn === 'function') {
    callback = optsOrFn;
    opts = extraOpts || {};
  } else if (typeof optsOrFn === 'object' && optsOrFn !== null) {
    opts = optsOrFn;
    if (typeof opts.onOk === 'function') callback = opts.onOk;
  } else if (typeof optsOrFn === 'string') {
    opts = { msg: optsOrFn, ...extraOpts };
  }

  const typeKey = (opts.type && CONFIRM_TYPES[opts.type]) ? opts.type : 'danger';
  const typeConfig = CONFIRM_TYPES[typeKey];

  const overlay   = document.getElementById('confirm-overlay');
  const box       = document.getElementById('confirm-box');
  const iconEl    = document.getElementById('confirm-icon');
  const titleEl   = document.getElementById('confirm-title');
  const msgEl     = document.getElementById('confirm-msg');
  const detEl     = document.getElementById('confirm-detail');
  const okBtn     = document.getElementById('confirm-ok-btn');
  const cancelBtn = document.getElementById('confirm-cancel-btn');

  if (!overlay || !box) {
    const res = window.confirm(opts.msg || opts.title || 'Confirmer l\'action ?');
    if (res && callback) callback();
    return Promise.resolve(res);
  }

  box.className = '';
  box.classList.add(typeConfig.class);

  if (iconEl) iconEl.textContent = opts.icon || typeConfig.icon;
  if (titleEl) titleEl.textContent = opts.title || 'Confirmation requise';
  if (msgEl) msgEl.innerHTML = opts.msg || 'Êtes-vous sûr de vouloir effectuer cette action ?';

  if (detEl) {
    if (opts.detail) {
      detEl.style.display = 'block';
      detEl.innerHTML = opts.detail;
    } else {
      detEl.style.display = 'none';
      detEl.innerHTML = '';
    }
  }

  const okLabel = opts.confirmText || opts.okLabel || typeConfig.okLabel;
  if (okBtn) {
    okBtn.textContent = okLabel;
    okBtn.style.background = opts.okBg || typeConfig.okBg;
    okBtn.style.color = opts.okColor || typeConfig.okColor;
    okBtn.classList.remove('loading');
  }

  if (cancelBtn) {
    cancelBtn.style.display = opts.hideCancel ? 'none' : 'inline-block';
    cancelBtn.textContent = opts.cancelText || '✕ Annuler';
  }

  _confirmTargetForm = opts.form || null;

  return new Promise((resolve) => {
    _confirmResolver = (confirmed) => {
      overlay.classList.remove('active');
      if (confirmed) {
        if (callback) {
          try {
            const res = callback();
            if (res instanceof Promise) {
              if (okBtn) okBtn.classList.add('loading');
              res.finally(() => {
                if (okBtn) okBtn.classList.remove('loading');
                resolve(true);
              });
              return;
            }
          } catch (e) {
            console.error('Erreur dans callback confirm:', e);
          }
        }
        if (_confirmTargetForm) {
          _confirmTargetForm.dataset.confirmed = 'true';
          _confirmTargetForm.submit();
        }
        resolve(true);
      } else {
        if (typeof opts.onCancel === 'function') opts.onCancel();
        resolve(false);
      }
      _confirmTargetForm = null;
      _confirmResolver = null;
    };

    overlay.classList.add('active');

    setTimeout(() => {
      if (typeKey === 'danger' && cancelBtn && !opts.hideCancel) {
        cancelBtn.focus();
      } else if (okBtn) {
        okBtn.focus();
      }
    }, 50);
  });
}

window.confirmAction = showConfirm;
window.customConfirm = showConfirm;

function showAlert(msg, opts = {}) {
  return showConfirm({
    type: opts.type || 'info',
    icon: opts.icon || (opts.type === 'danger' ? '❌' : (opts.type === 'success' ? '✅' : 'ℹ️')),
    title: opts.title || 'Information',
    msg: msg,
    detail: opts.detail || '',
    confirmText: opts.okLabel || 'D\'accord',
    hideCancel: true
  });
}
window.showAlert = showAlert;

function confirmForm(form, opts = {}) {
  if (form.dataset.confirmed === 'true') {
    delete form.dataset.confirmed;
    return true;
  }
  opts.form = form;
  showConfirm(opts);
  return false;
}
window.confirmForm = confirmForm;

function _confirmResolve() {
  if (_confirmResolver) _confirmResolver(true);
}

function _confirmReject() {
  if (_confirmResolver) _confirmResolver(false);
}

document.addEventListener('DOMContentLoaded', function() {
  const overlay = document.getElementById('confirm-overlay');
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) _confirmReject();
    });
  }
});

document.addEventListener('keydown', function(e) {
  const overlay = document.getElementById('confirm-overlay');
  if (overlay && overlay.classList.contains('active')) {
    if (e.key === 'Escape') {
      e.preventDefault();
      _confirmReject();
    }
  }
});

// ── CSRF auto-inject ─────────────────────────────────────
document.addEventListener('submit', function(e) {
  const form = e.target;
  if (!form.querySelector('input[name="_csrf_token"]')) {
    const input = document.createElement('input');
    input.type = 'hidden'; input.name = '_csrf_token';
    input.value = document.querySelector('meta[name="csrf-token"]')?.content || '';
    form.appendChild(input);
  }
}, false);

// Intercepteur Fetch global pour X-CSRF-Token
(function() {
  const _origFetch = window.fetch;
  window.fetch = function(resource, init) {
    init = init || {};
    const method = (init.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
      if (csrfToken) {
        if (!init.headers) {
          init.headers = { 'X-CSRF-Token': csrfToken };
        } else if (init.headers instanceof Headers) {
          if (!init.headers.has('X-CSRF-Token')) init.headers.append('X-CSRF-Token', csrfToken);
        } else if (typeof init.headers === 'object' && !init.headers['X-CSRF-Token']) {
          init.headers['X-CSRF-Token'] = csrfToken;
        }
      }
    }
    return _origFetch.call(this, resource, init);
  };
})();

// ── Auto-confirm forms ───────────────────────────────────
document.addEventListener('submit', function(e) {
  const form = e.target;
  const confirmType  = form.dataset.confirm;
  const confirmTitle = form.dataset.confirmTitle;
  const confirmMsg   = form.dataset.confirmMsg;
  const confirmDet   = form.dataset.confirmDetail;
  if (confirmType) {
    e.preventDefault();
    confirmAction({
      type: confirmType, title: confirmTitle,
      msg: confirmMsg, detail: confirmDet, form: form,
    });
  }
}, true);

// ── Searchify contribuable selects ───────────────────────
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('select[name="contribuable_id"]').forEach(function(select) {
    if (select.dataset.searchified) return;
    const wrapper = document.createElement('div');
    wrapper.style.position = 'relative';
    wrapper.style.marginBottom = '5px';
    select.parentNode.insertBefore(wrapper, select);
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '\uD83D\uDD0D Chercher un contribuable (Nom, N\u00B0, CIN...)';
    input.style.cssText = 'width:100%;padding:8px 10px;margin-bottom:6px;border:1.5px solid var(--border);border-radius:6px;font-size:0.85rem;box-sizing:border-box;background:var(--bg);color:var(--text);';
    wrapper.appendChild(input);
    wrapper.appendChild(select);
    select.dataset.searchified = "true";
    const originalOptions = Array.from(select.options);
    input.addEventListener('input', function() {
      const term = this.value.toLowerCase().trim();
      const currentSelected = select.value;
      select.innerHTML = '';
      originalOptions.forEach(opt => {
        const text = opt.text.toLowerCase();
        if (text.includes(term)) select.appendChild(opt);
      });
      if(currentSelected && Array.from(select.options).some(o => o.value === currentSelected)) {
         select.value = currentSelected;
      }
    });
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (select.options.length > 0 && select.options[0].value === "") {
           if(select.options.length > 1) select.value = select.options[1].value;
        } else if (select.options.length > 0) {
           select.value = select.options[0].value;
        }
      }
    });
  });
});
