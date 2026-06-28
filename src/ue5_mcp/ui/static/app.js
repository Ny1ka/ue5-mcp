/* ue5-mcp chat UI — vanilla JS SPA */

/* ─── Marked setup (v9+ API — highlight option was removed) ─── */
// marked.use() instead of the deprecated marked.setOptions()
marked.use({ breaks: true, gfm: true });

/* ─── Helpers ─────────────────────────────────────────────────── */
function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}
function dateGroup(iso) {
  const days = Math.floor((Date.now() - new Date(iso)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7)  return "Previous 7 days";
  return "Older";
}

const MODEL_LABELS = {
  "claude-opus-4-5":   "Claude Opus 4.5",
  "claude-sonnet-4-5": "Claude Sonnet 4.5",
  "claude-haiku-4-5":  "Claude Haiku 4.5",
  "claude-opus-4-0":   "Claude Opus 4",
};

/* ─── LocalStorage persistence ────────────────────────────────── */
const Store = {
  CONV_KEY:  "ue5-mcp-conversations",
  MODEL_KEY: "ue5-mcp-model",

  loadConvos() {
    try { return JSON.parse(localStorage.getItem(this.CONV_KEY) || "[]"); }
    catch { return []; }
  },
  saveConvos(convos) {
    localStorage.setItem(this.CONV_KEY, JSON.stringify(convos));
  },
  loadModel() {
    return localStorage.getItem(this.MODEL_KEY) || "claude-opus-4-5";
  },
  saveModel(m) {
    localStorage.setItem(this.MODEL_KEY, m);
  },
};

/* ─── App ─────────────────────────────────────────────────────── */
const App = {
  convos:      [],
  activeId:    null,
  streaming:   false,
  pendingFiles:[],
  selectedModel: "claude-opus-4-5",
  connectionStatus: null,

  // ── Init ──────────────────────────────────────────────────────
  init() {
    this.convos        = Store.loadConvos();
    this.selectedModel = Store.loadModel();
    this.bindEvents();
    this.renderAll();
    this.updateModelPill();
    this.refreshStatus();
    setInterval(() => this.refreshStatus(), 15_000);
  },

  renderAll() {
    this.renderSidebar();
    this.renderMainView();
  },

  // ── Event bindings ────────────────────────────────────────────
  bindEvents() {
    $("new-chat-btn").addEventListener("click", () => this.newConvo());

    // Settings open
    $("settings-btn").addEventListener("click", () => this.openSettings());

    // Settings close — all three paths
    $("close-modal-btn").addEventListener("click",  () => this.closeSettings());
    $("overlay").addEventListener("click",          () => this.closeSettings());
    $("cancel-settings").addEventListener("click",  () => this.closeSettings());
    $("save-settings").addEventListener("click",    () => this.saveSettings());

    // Escape key also closes modal
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.closeSettings();
    });

    // API key eye toggle
    $("toggle-key").addEventListener("click", () => {
      const inp  = $("s-apikey");
      const show = $("eye-show");
      const hide = $("eye-hide");
      if (inp.type === "password") {
        inp.type = "text";
        show.style.display = "none";
        hide.style.display = "";
      } else {
        inp.type = "password";
        show.style.display = "";
        hide.style.display = "none";
      }
    });

    // File attach
    $("attach-btn").addEventListener("click", () => $("file-input").click());
    $("file-input").addEventListener("change", (e) => this.handleFiles(e.target.files));

    // Textarea auto-resize + send enable
    const inp = $("msg-input");
    inp.addEventListener("input", () => {
      inp.style.height = "auto";
      inp.style.height = Math.min(inp.scrollHeight, 200) + "px";
      $("send-btn").disabled = inp.value.trim() === "" && this.pendingFiles.length === 0;
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!$("send-btn").disabled && !this.streaming) this.send();
      }
    });

    $("send-btn").addEventListener("click", () => {
      if (!this.streaming) this.send();
    });

    // Quick cards
    document.querySelectorAll(".quick-card").forEach(btn => {
      btn.addEventListener("click", () => {
        $("msg-input").value = btn.dataset.prompt;
        $("msg-input").dispatchEvent(new Event("input"));
        this.send();
      });
    });

    // Model picker
    $("model-pill-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      $("model-menu").classList.toggle("is-open");
      $("model-pill-btn").setAttribute(
        "aria-expanded",
        $("model-menu").classList.contains("is-open"),
      );
    });

    document.addEventListener("click", () => {
      $("model-menu").classList.remove("is-open");
    });

    document.querySelectorAll(".model-opt").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.selectModel(btn.dataset.model);
        $("model-menu").classList.remove("is-open");
      });
    });
  },

  // ── Model selector ────────────────────────────────────────────
  selectModel(model) {
    this.selectedModel = model;
    Store.saveModel(model);
    this.updateModelPill();

    // Persist to server as well (fire-and-forget)
    fetch("/api/settings", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ llm_model: model }),
    }).catch(() => {});
  },

  updateModelPill() {
    $("model-pill-label").textContent = MODEL_LABELS[this.selectedModel] || this.selectedModel;
    // Mark active option in dropdown
    document.querySelectorAll(".model-opt").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.model === this.selectedModel);
    });
    // Sync model select in settings modal if it's open
    const sel = $("s-model");
    if (sel) sel.value = this.selectedModel;
  },

  // ── Conversations ─────────────────────────────────────────────
  newConvo() {
    const c = {
      id:        uid(),
      title:     "New conversation",
      messages:  [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    this.convos.unshift(c);
    Store.saveConvos(this.convos);
    this.activeId = c.id;
    this.renderAll();
    $("msg-input").focus();
  },

  deleteConvo(id, ev) {
    ev.stopPropagation();
    this.convos = this.convos.filter(c => c.id !== id);
    Store.saveConvos(this.convos);
    if (this.activeId === id) {
      this.activeId = this.convos.length ? this.convos[0].id : null;
    }
    this.renderAll();
  },

  activeConvo() {
    return this.convos.find(c => c.id === this.activeId) ?? null;
  },

  // ── Render sidebar ────────────────────────────────────────────
  renderSidebar() {
    const nav   = $("conversations-nav");
    const empty = $("nav-empty");

    if (!this.convos.length) {
      nav.innerHTML = "";
      nav.appendChild(empty);
      empty.style.display = "";
      return;
    }

    const groups = {};
    for (const c of this.convos) {
      const g = dateGroup(c.updatedAt);
      (groups[g] = groups[g] || []).push(c);
    }

    const ORDER = ["Today", "Yesterday", "Previous 7 days", "Older"];
    let html = "";
    for (const g of ORDER) {
      if (!groups[g]) continue;
      html += `<p class="nav-group-label">${esc(g)}</p>`;
      for (const c of groups[g]) {
        html += `
          <button class="nav-item${c.id === this.activeId ? " active" : ""}"
                  data-id="${esc(c.id)}" type="button">
            <span class="nav-item-text">${esc(c.title)}</span>
            <button class="nav-delete-btn" data-del="${esc(c.id)}"
                    title="Delete" aria-label="Delete conversation">✕</button>
          </button>`;
      }
    }

    nav.innerHTML = html;

    nav.querySelectorAll(".nav-item").forEach(btn => {
      btn.addEventListener("click", (e) => {
        if (e.target.closest(".nav-delete-btn")) return;
        this.activeId = btn.dataset.id;
        this.renderAll();
      });
    });

    nav.querySelectorAll(".nav-delete-btn").forEach(btn => {
      btn.addEventListener("click", (e) => this.deleteConvo(btn.dataset.del, e));
    });
  },

  // ── Render main (welcome vs chat) ─────────────────────────────
  renderMainView() {
    const convo   = this.activeConvo();
    const welcome = $("welcome");
    const chat    = $("chat");

    if (!convo) {
      welcome.classList.add("is-visible");
      chat.classList.remove("is-visible");
      $("topbar-title").textContent = "UE5 Assistant";
      return;
    }

    welcome.classList.remove("is-visible");
    chat.classList.add("is-visible");
    $("topbar-title").textContent = convo.title;

    const msgs = $("messages");
    msgs.innerHTML = "";
    for (const m of convo.messages) {
      msgs.appendChild(this.buildMsgEl(m));
    }
    this.scrollBottom();
  },

  // ── Build message DOM element ─────────────────────────────────
  buildMsgEl(msg) {
    const wrap = document.createElement("div");
    wrap.className = `msg msg-${msg.role}`;
    wrap.dataset.msgId = msg.id;

    const header = document.createElement("div");
    header.className = "msg-header";

    const av = document.createElement("div");
    av.className = `msg-avatar msg-avatar-${msg.role}`;
    av.textContent = msg.role === "user" ? "U" : "AI";

    const lbl = document.createElement("span");
    lbl.className = "msg-role-label";
    lbl.textContent = msg.role === "user" ? "You" : "UE5 Assistant";

    header.append(av, lbl);

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.dataset.bubbleId = msg.id;

    if (msg.role === "user") {
      bubble.textContent = msg.content;
    } else {
      const segs = msg.segments?.length
        ? msg.segments
        : [{ type: "text", content: msg.content || "" }];
      this.renderSegments(bubble, segs);
    }

    wrap.append(header, bubble);
    return wrap;
  },

  renderSegments(bubble, segments) {
    bubble.innerHTML = "";
    for (const seg of segments) {
      if (seg.type === "text") {
        const div = document.createElement("div");
        div.className = "md-content";
        div.innerHTML = marked.parse(seg.content || "");
        bubble.appendChild(div);
        div.querySelectorAll("pre code").forEach(el => hljs.highlightElement(el));
      } else if (seg.type === "tool") {
        bubble.appendChild(this.buildToolCard(seg));
      }
    }
  },

  buildToolCard(seg) {
    const card = document.createElement("div");
    card.className = "tool-call-card" + (seg.expanded ? " expanded" : "");
    card.dataset.toolId = seg.id;

    const sc = seg.status === "done" ? "done" : seg.status === "error" ? "error" : "pending";
    const sl = seg.status === "done" ? "✓ Done" : seg.status === "error" ? "✕ Error" : "Running…";

    card.innerHTML = `
      <div class="tool-call-header">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:var(--text-dim)">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
        </svg>
        <span class="tool-call-name">${esc(seg.name)}</span>
        <span class="tool-call-status ${sc}">${sl}</span>
      </div>
      <div class="tool-call-body">
        <pre>${esc(seg.result || "")}</pre>
      </div>`;

    card.querySelector(".tool-call-header").addEventListener("click", () => {
      card.classList.toggle("expanded");
    });

    return card;
  },

  // ── Send message ──────────────────────────────────────────────
  async send() {
    const inp  = $("msg-input");
    const text = inp.value.trim();
    if (!text && !this.pendingFiles.length) return;
    if (this.streaming) return;

    let content = text;
    for (const f of this.pendingFiles) {
      content = `[File: ${f.name}]\n\`\`\`\n${f.content}\n\`\`\`\n\n` + content;
    }
    this.pendingFiles = [];
    this.renderAttachments();

    inp.value = "";
    inp.style.height = "auto";
    $("send-btn").disabled = true;

    if (!this.activeId) this.newConvo();
    const convo = this.activeConvo();

    const userMsg = { id: uid(), role: "user", content };
    convo.messages.push(userMsg);
    if (convo.title === "New conversation" && text) {
      convo.title = text.slice(0, 48) + (text.length > 48 ? "…" : "");
      $("topbar-title").textContent = convo.title;
    }
    convo.updatedAt = new Date().toISOString();

    const assistantMsg = { id: uid(), role: "assistant", content: "", segments: [] };
    convo.messages.push(assistantMsg);
    Store.saveConvos(this.convos);

    // Append to DOM
    const msgs = $("messages");
    msgs.appendChild(this.buildMsgEl(userMsg));

    const aEl    = this.buildMsgEl(assistantMsg);
    const bubble = aEl.querySelector(".msg-bubble");
    bubble.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
    msgs.appendChild(aEl);
    this.scrollBottom();

    // Switch to chat view if on welcome
    $("welcome").classList.remove("is-visible");
    $("chat").classList.add("is-visible");

    this.streaming = true;
    this.renderSidebar();

    const history = convo.messages
      .filter(m => m.id !== assistantMsg.id)
      .map(m => ({ role: m.role, content: m.content }));

    try {
      const resp = await fetch("/api/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ messages: history, model: this.selectedModel }),
      });

      if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
      await this.streamResponse(resp, assistantMsg, bubble);

    } catch (err) {
      const div = document.createElement("div");
      div.style.cssText = "color:var(--danger);font-size:13px";
      div.textContent   = err.message;
      bubble.innerHTML  = "";
      bubble.appendChild(div);
      assistantMsg.content = err.message;
    } finally {
      this.streaming = false;
      Store.saveConvos(this.convos);
      $("send-btn").disabled = $("msg-input").value.trim() === "";
      this.renderSidebar();
    }
  },

  // ── SSE streaming ─────────────────────────────────────────────
  async streamResponse(resp, assistantMsg, bubble) {
    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = "";
    let   bubbleReady = false;

    const ensureBubble = () => {
      if (!bubbleReady) { bubble.innerHTML = ""; bubbleReady = true; }
    };

    const lastTextSeg = () => {
      const last = assistantMsg.segments.at(-1);
      if (last?.type === "text") return last;
      const s = { type: "text", content: "" };
      assistantMsg.segments.push(s);
      return s;
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }
          this.handleEvent(ev, assistantMsg, bubble, ensureBubble, lastTextSeg);
        }
      }
    }
  },

  handleEvent(ev, assistantMsg, bubble, ensureBubble, lastTextSeg) {
    switch (ev.type) {

      case "text": {
        ensureBubble();
        const seg = lastTextSeg();
        seg.content += ev.content;
        assistantMsg.content += ev.content;

        // Update or create the last .md-content div
        let md = bubble.querySelector(".md-content:last-of-type");
        if (!md || bubble.lastElementChild?.classList.contains("tool-call-card")) {
          md = document.createElement("div");
          md.className = "md-content";
          bubble.appendChild(md);
        }
        md.innerHTML = marked.parse(seg.content);
        md.querySelectorAll("pre code").forEach(el => hljs.highlightElement(el));
        this.scrollBottom();
        break;
      }

      case "tool_start": {
        ensureBubble();
        const seg = { type: "tool", id: ev.id, name: ev.name, input: ev.input,
                      result: "", status: "pending", expanded: false };
        assistantMsg.segments.push(seg);
        bubble.appendChild(this.buildToolCard(seg));
        this.scrollBottom();
        break;
      }

      case "tool_end": {
        const seg = assistantMsg.segments.find(s => s.type === "tool" && s.id === ev.id);
        if (seg) { seg.result = ev.result; seg.status = "done"; }
        const card = bubble.querySelector(`.tool-call-card[data-tool-id="${esc(ev.id)}"]`);
        if (card) {
          const st = card.querySelector(".tool-call-status");
          if (st) { st.className = "tool-call-status done"; st.textContent = "✓ Done"; }
          const pre = card.querySelector(".tool-call-body pre");
          if (pre) pre.textContent = ev.result;
        }
        this.scrollBottom();
        break;
      }

      case "error": {
        ensureBubble();
        const d = document.createElement("div");
        d.style.cssText = "color:var(--danger);margin:.4em 0;font-size:13px";
        d.textContent = ev.message;
        bubble.appendChild(d);
        assistantMsg.content += `\n\nError: ${ev.message}`;
        this.scrollBottom();
        break;
      }

      case "done":
        break;
    }
  },

  scrollBottom() {
    const m = $("messages");
    if (m) m.scrollTop = m.scrollHeight;
  },

  // ── File attachments ──────────────────────────────────────────
  handleFiles(fileList) {
    for (const file of Array.from(fileList)) {
      const reader = new FileReader();
      reader.onload = (e) => {
        this.pendingFiles.push({ name: file.name, content: e.target.result });
        this.renderAttachments();
        $("send-btn").disabled = false;
      };
      reader.readAsText(file);
    }
    $("file-input").value = "";
  },

  renderAttachments() {
    const row = $("attachments-row");
    if (!this.pendingFiles.length) { row.innerHTML = ""; return; }
    row.innerHTML = this.pendingFiles.map((f, i) => `
      <div class="attachment-chip">
        <span>${esc(f.name)}</span>
        <button data-idx="${i}" aria-label="Remove ${esc(f.name)}">✕</button>
      </div>`).join("");
    row.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        this.pendingFiles.splice(Number(btn.dataset.idx), 1);
        this.renderAttachments();
        if (!this.pendingFiles.length && !$("msg-input").value.trim()) {
          $("send-btn").disabled = true;
        }
      });
    });
  },

  // ── Connection status ─────────────────────────────────────────
  async refreshStatus() {
    try {
      const r = await fetch("/api/status");
      if (!r.ok) throw new Error();
      this.connectionStatus = await r.json();
      this.updateConnBadge(this.connectionStatus);
    } catch {
      this.updateConnBadge(null);
    }
  },

  updateConnBadge(status) {
    const dot   = $("conn-dot");
    const label = $("conn-label");
    if (!status) {
      dot.className   = "conn-dot disconnected";
      label.textContent = "Server unreachable";
      return;
    }
    const cls = { editor:"connected", mock:"connected", filesystem:"partial" }[status.mode] || "disconnected";
    const txt = {
      editor:       "Connected to editor",
      mock:         "Mock mode active",
      filesystem:   "Filesystem scan",
      disconnected: "Editor disconnected",
    }[status.mode] || status.mode;
    dot.className   = `conn-dot ${cls}`;
    label.textContent = txt;
  },

  // ── Settings modal ────────────────────────────────────────────
  async openSettings() {
    // Show modal via CSS class (NOT the hidden attribute which is overridden by display:flex)
    $("overlay").classList.add("is-open");
    $("modal").classList.add("is-open");

    // Populate LLM fields
    try {
      const r    = await fetch("/api/settings");
      const data = await r.json();
      $("s-provider").value = data.llm_provider || "anthropic";
      $("s-model").value    = this.selectedModel;   // use client-side selection
      if (data.has_api_key) {
        $("s-apikey").placeholder = data.llm_api_key; // shows masked version
        $("s-apikey").value = "";
      }
    } catch {}

    // Populate MCP status
    const status = this.connectionStatus;
    if (status) {
      this.populateMcpCard(status);
    } else {
      try {
        const r = await fetch("/api/status");
        this.populateMcpCard(await r.json());
      } catch {}
    }

    // Load tools list
    try {
      const r = await fetch("/api/tools");
      const d = await r.json();
      $("tool-badge").textContent = d.total;
      $("modal-tools").innerHTML  = d.tools.map(t => `
        <div class="tool-row">
          <span class="tool-row-name">${esc(t.name)}</span>
          <span class="tool-row-desc">${esc(t.description.split("\n")[0].slice(0, 130))}</span>
        </div>`).join("");
    } catch {
      $("modal-tools").innerHTML = `<p class="muted">Could not load tools</p>`;
    }
  },

  populateMcpCard(status) {
    const MODE = {
      editor:       "Connected to editor",
      mock:         "Mock mode active",
      filesystem:   "Filesystem scan",
      disconnected: "Not connected",
    };
    const cls = { editor:"connected", mock:"connected", filesystem:"partial" }[status.mode] || "disconnected";
    $("modal-conn-dot").className    = `conn-dot ${cls}`;
    $("modal-conn-mode").textContent = MODE[status.mode] || status.mode;
    $("modal-project").textContent   = status.project || "—";
    $("modal-endpoint").textContent  = `${status.config.host}:${status.config.http_port}`;
    $("modal-path").textContent      = status.config.project_path || "Not set";
  },

  closeSettings() {
    $("overlay").classList.remove("is-open");
    $("modal").classList.remove("is-open");
  },

  async saveSettings() {
    const btn = $("save-settings");
    btn.textContent = "Saving…";
    btn.disabled    = true;

    const newModel = $("s-model").value;
    const updates  = {
      llm_provider: $("s-provider").value,
      llm_model:    newModel,
    };
    const keyVal = $("s-apikey").value.trim();
    if (keyVal) updates.llm_api_key = keyVal;

    try {
      const r = await fetch("/api/settings", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(updates),
      });
      if (!r.ok) throw new Error("Save failed");
      // Sync the client-side model selector too
      this.selectModel(newModel);
      this.closeSettings();
    } catch (err) {
      alert("Could not save settings: " + err.message);
    } finally {
      btn.textContent = "Save settings";
      btn.disabled    = false;
    }
  },
};

/* ─── Boot ────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => App.init());
