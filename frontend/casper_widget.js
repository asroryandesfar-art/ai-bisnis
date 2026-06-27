// Casper Agentic Buildathon 2026 — AI session anchor widget
// Injects a "Anchor to Casper" button into the dashboard topbar.
// On click: POSTs to /api/casper/anchor → shows deploy hash + explorer link.

(function () {
  function getToken() {
    return localStorage.getItem('bn_token') || sessionStorage.getItem('bn_token') || '';
  }

  function buildButton() {
    const btn = document.createElement('button');
    btn.id = 'casper-anchor-btn';
    btn.title = 'Anchor AI session hash ke Casper Testnet';
    btn.innerHTML = `
      <img src="https://cspr.live/assets/icons/favicon.png"
           onerror="this.style.display='none'"
           style="width:14px;height:14px;vertical-align:middle;margin-right:4px" alt="">
      Anchor to Casper`;
    Object.assign(btn.style, {
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      padding: '5px 12px', borderRadius: '6px', border: '1px solid #7e57c2',
      background: '#ede7f6', color: '#4527a0', fontWeight: '600',
      fontSize: '13px', cursor: 'pointer', marginLeft: '8px',
      transition: 'background .15s',
    });
    btn.onmouseenter = () => { btn.style.background = '#d1c4e9'; };
    btn.onmouseleave = () => { btn.style.background = '#ede7f6'; };
    return btn;
  }

  function buildModal(data) {
    const overlay = document.createElement('div');
    Object.assign(overlay.style, {
      position: 'fixed', inset: '0', background: 'rgba(0,0,0,.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: '9999', fontFamily: 'system-ui, sans-serif',
    });
    const box = document.createElement('div');
    Object.assign(box.style, {
      background: '#fff', borderRadius: '12px', padding: '28px 32px',
      maxWidth: '480px', width: '90%', boxShadow: '0 8px 32px rgba(0,0,0,.2)',
    });
    const isDemo = data.proof_mode === 'demo' || (data.deploy_hash || '').startsWith('demo-');
    const modeNote = isDemo
      ? `<p style="margin:0 0 8px;font-size:12px;padding:6px 10px;background:#fff3e0;border-radius:4px;color:#e65100">
           ◎ Demo mode — deterministic proof hash (real Casper tx unavailable${data.real_mode_error ? ': ' + data.real_mode_error : ''})
         </p>`
      : `<p style="margin:0 0 8px;font-size:12px;color:#555">✓ Real transaction on Casper Testnet — verifiable on cspr.live</p>`;
    box.innerHTML = `
      <h3 style="margin:0 0 12px;color:#4527a0;font-size:18px">
        ${isDemo ? '◎' : '✅'} ${isDemo ? 'Proof Generated (Demo Mode)' : 'Anchored to Casper Testnet'}
      </h3>
      ${modeNote}
      <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:16px">
        <tr><td style="padding:4px 0;color:#777;width:130px">Deploy Hash</td>
            <td style="word-break:break-all;font-family:monospace;color:#222">${data.deploy_hash}</td></tr>
        <tr><td style="padding:4px 0;color:#777">Session Hash</td>
            <td style="word-break:break-all;font-family:monospace;color:#222">${data.session_hash}</td></tr>
        <tr><td style="padding:4px 0;color:#777">Contract Package</td>
            <td style="word-break:break-all;font-family:monospace;color:#222">${(data.contract_package_hash||'').slice(0,20)}…</td></tr>
        <tr><td style="padding:4px 0;color:#777">Mode</td>
            <td style="font-family:monospace;color:#222">${data.proof_mode || 'real'}</td></tr>
      </table>
      <a href="${data.explorer_url}" target="_blank" rel="noopener"
         style="display:inline-block;padding:8px 16px;background:#7e57c2;color:#fff;
                border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;margin-right:8px">
        View Deploy ↗
      </a>
      <a href="${data.contract_url||'https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0'}" target="_blank" rel="noopener"
         style="display:inline-block;padding:8px 16px;background:#4527a0;color:#fff;
                border-radius:6px;text-decoration:none;font-size:13px;font-weight:600">
        View Contract ↗
      </a>
      <button id="casper-modal-close"
              style="float:right;padding:8px 16px;border:1px solid #ccc;border-radius:6px;
                     background:#f5f5f5;cursor:pointer;font-size:13px">
        Tutup
      </button>`;
    overlay.appendChild(box);
    document.getElementById('casper-modal-close')?.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    box.querySelector('#casper-modal-close')?.addEventListener('click', () => overlay.remove());
    return overlay;
  }

  async function handleAnchor(btn) {
    const token = getToken();
    if (!token) { alert('Silakan login terlebih dahulu.'); return; }

    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '⏳ Submitting…';

    try {
      const sessionId = 'sess-' + Date.now();
      const summary = `BotNesia AI session anchored at ${new Date().toISOString()}`;
      const res = await fetch('/api/casper/anchor', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, summary }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      document.body.appendChild(buildModal(data));
      // Wire close button after modal is in DOM
      document.querySelector('#casper-modal-close')?.addEventListener('click', () => {
        document.querySelector('[style*="9999"]')?.remove();
      });
    } catch (err) {
      console.error('[Casper] anchor error:', err);
      alert('Casper anchor gagal — ' + (err.message || 'Unknown error. Cek server logs.'));
    } finally {
      btn.disabled = false;
      btn.innerHTML = original;
    }
  }

  function inject() {
    const topbar = document.getElementById('topbar');
    if (!topbar || document.getElementById('casper-anchor-btn')) return;
    const btn = buildButton();
    btn.addEventListener('click', () => handleAnchor(btn));
    topbar.appendChild(btn);
  }

  // Re-inject on every SPA navigation — topbar gets re-rendered when page changes.
  setInterval(inject, 800);
})();
