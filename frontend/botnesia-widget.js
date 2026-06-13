(() => {
  "use strict";
  const script = document.currentScript;
  const connectionId = script?.dataset.connectionId || "";
  const apiBase = (script?.dataset.apiBase || new URL(script?.src || location.href).origin).replace(/\/$/, "");

  function start() {
    const host = document.getElementById("botnesia-chat");
    if (!host || host.dataset.botnesiaReady === "true") return;
    host.dataset.botnesiaReady = "true";
    if (!connectionId) {
      host.textContent = "BotNesia: data-connection-id belum dikonfigurasi.";
      return;
    }
    const root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
    const sessionKey = `botnesia_session_${connectionId}`;
    const sessionId = localStorage.getItem(sessionKey) || (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
    localStorage.setItem(sessionKey, sessionId);
    root.innerHTML = `<style>
      :host{--bn-brand:#7867ff;font-family:Inter,system-ui,sans-serif;color:#172033}
      *{box-sizing:border-box}.shell{position:fixed;right:20px;bottom:20px;z-index:2147483000;width:min(370px,calc(100vw - 24px));filter:drop-shadow(0 20px 45px rgba(20,25,40,.2))}
      .toggle{float:right;width:58px;height:58px;border:0;border-radius:50%;background:var(--bn-brand);color:white;font-size:24px;cursor:pointer}
      .panel{display:none;height:min(580px,calc(100vh - 110px));margin-bottom:12px;border:1px solid #e4e7ef;border-radius:18px;background:#fff;overflow:hidden}.panel.open{display:flex;flex-direction:column}
      header{padding:16px 18px;background:linear-gradient(135deg,var(--bn-brand),#5542df);color:#fff}header strong{display:block;font-size:15px}header span{font-size:11px;opacity:.8}
      .messages{flex:1;padding:16px;overflow:auto;background:#f7f8fb}.msg{max-width:84%;margin:0 0 11px;padding:10px 12px;border-radius:13px;background:#fff;border:1px solid #e5e8f0;font-size:13px;line-height:1.5;white-space:pre-wrap}.msg.user{margin-left:auto;background:var(--bn-brand);border-color:var(--bn-brand);color:#fff}.msg.error{color:#b42318}
      form{display:flex;gap:8px;padding:12px;border-top:1px solid #e5e8f0;background:#fff}input{flex:1;min-width:0;padding:11px 12px;border:1px solid #d7dbe5;border-radius:10px;outline:0;font:inherit}input:focus{border-color:var(--bn-brand)}button.send{padding:0 15px;border:0;border-radius:10px;background:var(--bn-brand);color:#fff;font-weight:700;cursor:pointer}button:disabled{opacity:.55}
      @media(max-width:520px){.shell{right:12px;bottom:12px}.panel{height:calc(100vh - 92px)}}
    </style><div class="shell"><section class="panel" aria-label="BotNesia chat"><header><strong>BotNesia Assistant</strong><span>AI customer assistant</span></header><div class="messages" role="log" aria-live="polite"><div class="msg">Halo, ada yang bisa saya bantu?</div></div><form><input name="message" maxlength="10000" autocomplete="off" placeholder="Tulis pesan..." aria-label="Pesan"><button class="send" type="submit">Kirim</button></form></section><button class="toggle" aria-label="Buka chat" aria-expanded="false">✦</button></div>`;
    const panel = root.querySelector(".panel");
    const toggle = root.querySelector(".toggle");
    const form = root.querySelector("form");
    const input = root.querySelector("input");
    const messages = root.querySelector(".messages");
    toggle.addEventListener("click", () => {
      const open = panel.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      if (open) input.focus();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      append(text, "user"); input.value = ""; input.disabled = true; form.querySelector("button").disabled = true;
      try {
        const response = await fetch(`${apiBase}/api/channels/webchat/${encodeURIComponent(connectionId)}/messages`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text,user_id:`web:${sessionId}`,session_id:sessionId,username:null})});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `Chat gagal (${response.status})`);
        append(data.answer || "Maaf, belum ada jawaban.");
      } catch (error) { append(error.message || "Chat tidak tersedia.", "error"); }
      finally { input.disabled = false; form.querySelector("button").disabled = false; input.focus(); }
    });
    function append(text, type = "") {
      const node = document.createElement("div"); node.className = `msg ${type}`; node.textContent = text; messages.appendChild(node); messages.scrollTop = messages.scrollHeight;
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
