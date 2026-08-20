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

// ── Modale confirmation globale ──────────────────────────
let _confirmCallback = null;
let _confirmForm     = null;

const CONFIRM_TYPES = {
  danger: { icon:'\uD83D\uDDD1\uFE0F', iconBg:'#fef2f2', iconColor:'#dc2626', okBg:'#dc2626', okColor:'#fff', okLabel:'Supprimer' },
  warning: { icon:'\u270F\uFE0F', iconBg:'#fffbeb', iconColor:'#d97706', okBg:'#d97706', okColor:'#fff', okLabel:'Modifier' },
  info: { icon:'\u2139\uFE0F', iconBg:'#eff6ff', iconColor:'#2563eb', okBg:'#2563eb', okColor:'#fff', okLabel:'Confirmer' },
  success: { icon:'\u2705', iconBg:'#f0fdf4', iconColor:'#16a34a', okBg:'#16a34a', okColor:'#fff', okLabel:'Valider' },
};

function confirmAction(opts) {
  const type = CONFIRM_TYPES[opts.type || 'danger'];
  const icon  = document.getElementById('confirm-icon');
  const title = document.getElementById('confirm-title');
  const msg   = document.getElementById('confirm-msg');
  const det   = document.getElementById('confirm-detail');
  const okBtn = document.getElementById('confirm-ok-btn');

  icon.textContent  = type.icon;
  icon.style.background = type.iconBg;
  icon.style.color      = type.iconColor;
  title.textContent = opts.title || 'Confirmer l\'action';
  msg.textContent   = opts.msg   || 'Êtes-vous sûr ?';
  okBtn.textContent = opts.okLabel || type.okLabel;
  okBtn.style.background = type.okBg;
  okBtn.style.color      = type.okColor;

  if (opts.detail) {
    det.style.display = 'block';
    det.textContent   = opts.detail;
  } else {
    det.style.display = 'none';
  }

  _confirmCallback = opts.onOk || null;
  _confirmForm     = opts.form || null;
  document.getElementById('confirm-overlay').classList.add('active');
}

function _confirmResolve() {
  document.getElementById('confirm-overlay').classList.remove('active');
  if (_confirmForm) { _confirmForm.submit(); }
  else if (_confirmCallback) { _confirmCallback(); }
  _confirmCallback = null;
  _confirmForm = null;
}

function _confirmReject() {
  document.getElementById('confirm-overlay').classList.remove('active');
  _confirmCallback = null;
  _confirmForm = null;
}

const _confirmOverlay = document.getElementById('confirm-overlay');
if (_confirmOverlay) {
  _confirmOverlay.addEventListener('click', function(e) {
    if (e.target === this) _confirmReject();
  });
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') _confirmReject();
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

// ── Promise-based confirm helpers (override confirmAction) ──
function confirmForm(form, opts) {
  return confirmActionPromise(() => {}, opts).then(ok => { if (ok) form.submit(); });
}

function confirmAction(fn, opts = {}) {
  return confirmActionPromise(fn, opts);
}

function confirmActionPromise(fn, opts = {}) {
  return new Promise(resolve => {
    const type = CONFIRM_TYPES[opts.type || 'danger'] || CONFIRM_TYPES.danger;
    const icon = document.getElementById('confirm-icon');
    const title = document.getElementById('confirm-title');
    const msg = document.getElementById('confirm-msg');
    const det = document.getElementById('confirm-detail');
    const okBtn = document.getElementById('confirm-ok-btn');
    const cancelBtn = document.getElementById('confirm-cancel-btn');

    icon.textContent = opts.icon || type.icon;
    icon.style.background = opts.iconBg || type.iconBg;
    icon.style.color = opts.iconColor || type.iconColor;
    title.textContent = opts.title || 'Confirmer l\'action';
    msg.textContent = opts.msg || 'Êtes-vous sûr ?';
    okBtn.textContent = opts.okLabel || type.okLabel;
    okBtn.style.background = opts.okBg || type.okBg;
    okBtn.style.color = opts.okColor || type.okColor;
    cancelBtn.textContent = opts.cancelText || '✕ Annuler';

    if (opts.detail) {
      det.style.display = 'block';
      det.textContent = opts.detail;
    } else {
      det.style.display = 'none';
    }

    _confirmCallback = () => { fn(); resolve(true); };
    _confirmForm = null;
    document.getElementById('confirm-overlay').classList.add('active');
  });
}
