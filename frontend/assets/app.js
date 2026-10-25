/* ============================================================
   MCP 智能办公助手 · 前端交互
   功能：SSE 流式对话、工具调用可视化、多轮会话、语音输入/朗读
   ============================================================ */
(() => {
  "use strict";

  const API_BASE = (window.__AGENT_API__ || "").replace(/\/$/, "");
  const STORAGE = {
    sessions: "mcp-agent-sessions",
    current: "mcp-agent-current",
    theme: "mcp-agent-theme",
    voice: "mcp-agent-voice",
  };

  const ICONS = {
    tool: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.2-2.2z"/></svg>',
    chevron: '<svg class="trace-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    alert: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.6 17.1A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.9L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
    speak: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>',
  };

  const els = {
    welcome: document.getElementById("welcome"),
    messages: document.getElementById("messages"),
    composer: document.getElementById("composer"),
    input: document.getElementById("input"),
    sendBtn: document.getElementById("sendBtn"),
    micBtn: document.getElementById("micBtn"),
    voiceToggle: document.getElementById("voiceToggle"),
    themeToggle: document.getElementById("themeToggle"),
    newChatBtn: document.getElementById("newChatBtn"),
    sessionList: document.getElementById("sessionList"),
    sessionCount: document.getElementById("sessionCount"),
    chatTitle: document.getElementById("chatTitle"),
    chatSubtitle: document.getElementById("chatSubtitle"),
    menuBtn: document.getElementById("menuBtn"),
    sidebarOverlay: document.getElementById("sidebarOverlay"),
    statusCard: document.getElementById("statusCard"),
    statusText: document.getElementById("statusText"),
    statusSub: document.getElementById("statusSub"),
    voiceHint: document.getElementById("voiceHint"),
    suggestions: document.getElementById("suggestions"),
    toast: document.getElementById("toast"),
  };

  const state = {
    sessionId: null,
    sessions: loadSessions(),
    busy: false,
    controller: null,
    voiceOn: loadBool(STORAGE.voice, false),
    recognition: null,
    listening: false,
  };

  /* ============================================================
     工具函数
     ============================================================ */
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch]);
  }

  function loadSessions() {
    try {
      const list = JSON.parse(localStorage.getItem(STORAGE.sessions) || "[]");
      return Array.isArray(list) ? list.filter((s) => s && s.id) : [];
    } catch {
      return [];
    }
  }

  function saveSessions() {
    try {
      localStorage.setItem(STORAGE.sessions, JSON.stringify(state.sessions.slice(0, 30)));
    } catch {
      /* 忽略隐私模式下的存储异常 */
    }
  }

  function loadBool(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : raw === "true";
    } catch {
      return fallback;
    }
  }

  function uuid() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID().replace(/-/g, "");
    }
    return "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function nowTime() {
    return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  function formatClock(ts) {
    if (!ts) return nowTime();
    const value = Number(ts);
    if (!Number.isFinite(value)) return nowTime();
    const ms = value > 1e12 ? value : value * 1000;
    return new Date(ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  function timeAgo(ts) {
    const diff = Date.now() - Number(ts || 0);
    if (!Number.isFinite(diff) || diff < 0) return "刚刚";
    if (diff < 60 * 1000) return "刚刚";
    if (diff < 3600 * 1000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400 * 1000) return `${Math.floor(diff / 3600000)} 小时前`;
    return new Date(Number(ts)).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  }

  function makeTitle(text) {
    const clean = String(text).replace(/\s+/g, " ").trim();
    return clean.length > 20 ? clean.slice(0, 20) + "…" : clean || "新对话";
  }

  let toastTimer = null;
  function showToast(message, duration = 2600) {
    if (!els.toast) return;
    els.toast.textContent = message;
    els.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("show"), duration);
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function scrollAfterPaint() {
    requestAnimationFrame(() => requestAnimationFrame(scrollToBottom));
  }

  /* ============================================================
     Markdown 渲染（轻量、无第三方依赖、默认转义防 XSS）
     ============================================================ */
  function inlineFormat(text) {
    let out = escapeHtml(text);
    const codes = [];

    out = out.replace(/`([^`\n]+)`/g, (_m, code) => {
      codes.push(code);
      return `\u0001C${codes.length - 1}\u0001`;
    });

    out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
    out = out.replace(/(^|[\s(（])\*([^\s*][^*\n]*?)\*(?=$|[\s)）,.!?，。！？])/g, "$1<em>$2</em>");

    return out.replace(/\u0001C(\d+)\u0001/g, (_m, idx) => `<code>${codes[Number(idx)]}</code>`);
  }

  function codeBlockHtml(block) {
    const label = escapeHtml(block.lang || "code");
    return (
      '<div class="code-block"><div class="code-head"><span>' + label + "</span>" +
      '<button class="copy-code" type="button">复制</button></div>' +
      `<pre><code>${escapeHtml(block.code)}</code></pre></div>`
    );
  }

  function splitTableRow(line) {
    let row = line.trim();
    if (row.startsWith("|")) row = row.slice(1);
    if (row.endsWith("|")) row = row.slice(0, -1);
    return row.split("|").map((cell) => cell.trim());
  }

  function isTableSeparator(line) {
    const trimmed = line.trim();
    return trimmed.includes("|") && trimmed.includes("-") && /^[\s|:-]+$/.test(trimmed);
  }

  function renderMarkdown(source) {
    let text = String(source ?? "").replace(/\r\n?/g, "\n");
    const codeBlocks = [];

    text = text.replace(/```([^\n`]*)\n?([\s\S]*?)```/g, (_m, lang, code) => {
      codeBlocks.push({ lang: String(lang || "").trim(), code: String(code).replace(/\n$/, "") });
      return `\n\u0000CB${codeBlocks.length - 1}\u0000\n`;
    });

    const lines = text.split("\n");
    const html = [];
    let paragraph = [];
    let listType = null;
    let i = 0;

    const flushParagraph = () => {
      if (!paragraph.length) return;
      html.push(`<p>${paragraph.map(inlineFormat).join("<br>")}</p>`);
      paragraph = [];
    };
    const closeList = () => {
      if (!listType) return;
      html.push(`</${listType}>`);
      listType = null;
    };

    while (i < lines.length) {
      const raw = lines[i];
      const trimmed = raw.trim();

      if (!trimmed) {
        flushParagraph();
        closeList();
        i += 1;
        continue;
      }

      const codeMatch = trimmed.match(/^\u0000CB(\d+)\u0000$/);
      if (codeMatch) {
        flushParagraph();
        closeList();
        const block = codeBlocks[Number(codeMatch[1])];
        if (block) html.push(codeBlockHtml(block));
        i += 1;
        continue;
      }

      const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        closeList();
        const level = Math.min(heading[1].length, 4);
        html.push(`<h${level}>${inlineFormat(heading[2])}</h${level}>`);
        i += 1;
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushParagraph();
        closeList();
        html.push("<hr>");
        i += 1;
        continue;
      }

      if (trimmed.startsWith(">")) {
        flushParagraph();
        closeList();
        const quotes = [];
        while (i < lines.length && lines[i].trim().startsWith(">")) {
          quotes.push(lines[i].trim().replace(/^>\s?/, ""));
          i += 1;
        }
        html.push(`<blockquote>${quotes.map(inlineFormat).join("<br>")}</blockquote>`);
        continue;
      }

      if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        flushParagraph();
        closeList();
        const headers = splitTableRow(trimmed);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          rows.push(splitTableRow(lines[i]));
          i += 1;
        }
        const head = headers.map((cell) => `<th>${inlineFormat(cell)}</th>`).join("");
        const body = rows
          .map((cells) => {
            const padded = headers.map((_h, idx) => cells[idx] ?? "");
            return `<tr>${padded.map((cell) => `<td>${inlineFormat(cell)}</td>`).join("")}</tr>`;
          })
          .join("");
        html.push(`<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
        continue;
      }

      const unordered = trimmed.match(/^[-*+]\s+(.*)$/);
      const ordered = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (unordered || ordered) {
        flushParagraph();
        const wanted = unordered ? "ul" : "ol";
        if (listType !== wanted) {
          closeList();
          html.push(`<${wanted}>`);
          listType = wanted;
        }
        html.push(`<li>${inlineFormat(unordered ? unordered[1] : ordered[1])}</li>`);
        i += 1;
        continue;
      }

      closeList();
      paragraph.push(trimmed);
      i += 1;
    }

    flushParagraph();
    closeList();
    return html.join("");
  }

  function plainText(markdown) {
    return String(markdown ?? "")
      .replace(/```[\s\S]*?```/g, "（代码略）")
      .replace(/`([^`]*)`/g, "$1")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^[#>\s*-]+/gm, "")
      .replace(/[*_~|]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  /* ============================================================
     主题 / 语音偏好
     ============================================================ */
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(STORAGE.theme, theme); } catch { /* ignore */ }
    if (els.themeToggle) {
      els.themeToggle.setAttribute("aria-label", theme === "dark" ? "切换浅色模式" : "切换深色模式");
    }
  }

  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem(STORAGE.theme); } catch { /* ignore */ }
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(saved || (prefersDark ? "dark" : "light"));
  }

  function updateVoiceButton() {
    els.voiceToggle.setAttribute("aria-pressed", String(state.voiceOn));
    els.voiceToggle.setAttribute("aria-label", state.voiceOn ? "关闭自动朗读" : "开启自动朗读");
    els.voiceToggle.title = state.voiceOn ? "自动朗读：开" : "自动朗读：关";
  }

  /* ============================================================
     会话列表
     ============================================================ */
  function renderSessions() {
    els.sessionList.innerHTML = "";
    els.sessionCount.textContent = String(state.sessions.length);

    if (!state.sessions.length) {
      const empty = document.createElement("p");
      empty.className = "session-empty";
      empty.textContent = "还没有对话记录，发送第一条指令试试。";
      els.sessionList.appendChild(empty);
      return;
    }

    state.sessions.forEach((session) => {
      const item = document.createElement("div");
      item.className = "session-item" + (session.id === state.sessionId ? " active" : "");

      const open = document.createElement("button");
      open.type = "button";
      open.className = "session-open";
      open.innerHTML =
        `<span class="session-title">${escapeHtml(session.title || "新对话")}</span>` +
        `<span class="session-time">${escapeHtml(timeAgo(session.updatedAt))}</span>`;
      open.addEventListener("click", () => openSession(session.id));

      const del = document.createElement("button");
      del.type = "button";
      del.className = "session-del";
      del.title = "删除对话";
      del.setAttribute("aria-label", "删除对话");
      del.textContent = "×";
      del.addEventListener("click", (event) => deleteSession(session.id, event));

      item.appendChild(open);
      item.appendChild(del);
      els.sessionList.appendChild(item);
    });
  }

  function upsertSession(id, title) {
    const existing = state.sessions.find((s) => s.id === id);
    if (existing) {
      existing.updatedAt = Date.now();
      if (title) existing.title = title;
      state.sessions = [existing, ...state.sessions.filter((s) => s.id !== id)];
    } else {
      state.sessions.unshift({ id, title: title || "新对话", updatedAt: Date.now() });
    }
    saveSessions();
    renderSessions();
  }

  function updateHeader(title, subtitle) {
    els.chatTitle.textContent = title || "新对话";
    els.chatSubtitle.textContent = subtitle || "多轮记忆已开启 · 工具调用实时可见";
  }

  function clearMessages() {
    els.messages.querySelectorAll(".msg, .history-loading").forEach((node) => node.remove());
  }

  function showWelcome() {
    clearMessages();
    els.welcome.hidden = false;
    updateHeader("新对话");
  }

  function ensureSession() {
    if (!state.sessionId) {
      state.sessionId = uuid();
      try { localStorage.setItem(STORAGE.current, state.sessionId); } catch { /* ignore */ }
    }
    return state.sessionId;
  }

  function newChat() {
    if (state.busy) {
      showToast("正在生成回复，请先停止当前任务");
      return;
    }
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    state.sessionId = uuid();
    try { localStorage.setItem(STORAGE.current, state.sessionId); } catch { /* ignore */ }
    showWelcome();
    renderSessions();
    closeSidebar();
    els.input.focus();
  }

  async function openSession(id) {
    if (state.busy) {
      showToast("正在生成回复，请先停止当前任务");
      return;
    }
    closeSidebar();
    state.sessionId = id;
    try { localStorage.setItem(STORAGE.current, id); } catch { /* ignore */ }
    renderSessions();

    const meta = state.sessions.find((s) => s.id === id);
    updateHeader(meta ? meta.title : "对话", "正在加载对话记录…");
    clearMessages();
    els.welcome.hidden = true;

    const loading = document.createElement("div");
    loading.className = "history-loading thinking";
    loading.innerHTML = '<span class="dots"><i></i><i></i><i></i></span><span>正在读取历史对话…</span>';
    els.messages.appendChild(loading);

    try {
      const response = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(id)}`, { cache: "no-store" });
      if (!response.ok) throw new Error("读取失败");
      const data = await response.json();
      loading.remove();
      renderHistory(data.messages || []);
      updateHeader(meta ? meta.title : "对话", `${(data.messages || []).length} 条消息 · 多轮记忆已开启`);
    } catch {
      loading.remove();
      showWelcome();
      showToast("未能读取历史记录，可能是后端已重启");
    }
  }

  async function deleteSession(id, event) {
    event.stopPropagation();
    if (state.busy && id === state.sessionId) {
      showToast("请先停止当前生成任务");
      return;
    }
    state.sessions = state.sessions.filter((s) => s.id !== id);
    saveSessions();
    if (id === state.sessionId) {
      newChat();
    } else {
      renderSessions();
    }
    try {
      await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    } catch {
      /* 本地已删除，忽略网络错误 */
    }
    showToast("对话已删除");
  }

  function renderHistory(messages) {
    clearMessages();
    if (!messages.length) {
      els.welcome.hidden = false;
      return;
    }
    els.welcome.hidden = true;

    messages.forEach((message) => {
      if (message.role === "user") {
        addUserMessage(message.content, false, message.ts);
      } else if (message.role === "assistant") {
        const turn = addAssistantTurn(false, message.ts);
        (message.tool_calls || []).forEach((call) => {
          turn.addTool({ id: call.id, name: call.name, arguments: call.arguments || {} });
          turn.finishTool({ id: call.id, name: call.name, result: call.result || "" });
        });
        turn.setAnswer(message.content || "", false);
        turn.finalize();
      }
    });
    scrollAfterPaint();
  }

  /* ============================================================
     消息渲染
     ============================================================ */
  function addUserMessage(content, scroll = true, ts = null) {
    els.welcome.hidden = true;

    const row = document.createElement("div");
    row.className = "msg user";

    const col = document.createElement("div");
    col.className = "msg-col";

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.innerHTML = `<span class="name">你</span><span>${escapeHtml(formatClock(ts))}</span>`;

    const bubble = document.createElement("div");
    bubble.className = "bubble user";
    bubble.textContent = content;

    col.appendChild(meta);
    col.appendChild(bubble);

    const avatar = document.createElement("div");
    avatar.className = "avatar user-avatar";
    avatar.textContent = "你";

    row.appendChild(col);
    row.appendChild(avatar);
    els.messages.appendChild(row);
    if (scroll) scrollAfterPaint();
  }

  function addAssistantTurn(scroll = true, ts = null) {
    els.welcome.hidden = true;

    const row = document.createElement("div");
    row.className = "msg assistant";

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.innerHTML = '<img src="/assets/logo.svg" alt="MCP Agent" />';

    const col = document.createElement("div");
    col.className = "msg-col";

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.innerHTML =
      '<span class="name">MCP Agent</span><span class="badge">AGENT</span>' +
      `<span>${escapeHtml(formatClock(ts))}</span>`;

    const bubble = document.createElement("div");
    bubble.className = "bubble assistant";

    const thinking = document.createElement("div");
    thinking.className = "thinking";
    thinking.innerHTML =
      '<span class="dots"><i></i><i></i><i></i></span><span data-stage>正在理解你的需求…</span>';

    const trace = document.createElement("div");
    trace.className = "trace";
    trace.setAttribute("aria-label", "MCP 工具调用记录");

    const content = document.createElement("div");
    content.className = "markdown";

    const actions = document.createElement("div");
    actions.className = "msg-actions";
    actions.hidden = true;
    actions.innerHTML =
      `<button class="msg-action" type="button" data-action="copy">${ICONS.copy}复制</button>` +
      `<button class="msg-action" type="button" data-action="speak">${ICONS.speak}朗读</button>`;

    bubble.appendChild(thinking);
    bubble.appendChild(trace);
    bubble.appendChild(content);
    bubble.appendChild(actions);

    col.appendChild(meta);
    col.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(col);
    els.messages.appendChild(row);
    if (scroll) scrollAfterPaint();

    const stageEl = thinking.querySelector("[data-stage]");
    const toolMap = new Map();
    let answered = false;
    let errored = false;

    function setStage(text) {
      if (!thinking.isConnected) return;
      thinking.hidden = false;
      if (stageEl) stageEl.textContent = text;
    }

    function ensureThinking() {
      if (!answered && !errored) {
        thinking.hidden = false;
      }
    }

    function addTool(data) {
      answered = false;
      errored = false;
      ensureThinking();
      const id = String(data.id || `tool-${toolMap.size}`);
      let item = toolMap.get(id);

      if (!item) {
        item = document.createElement("div");
        item.className = "trace-item running open";
        item.innerHTML =
          '<button class="trace-head" type="button">' +
            `<span class="trace-icon">${ICONS.tool}</span>` +
            '<span class="trace-name"></span>' +
            '<span class="trace-status"><span class="trace-dot"></span>运行中…</span>' +
            ICONS.chevron +
          "</button>" +
          '<div class="trace-body">' +
            '<div class="trace-block"><span class="trace-label">参数</span><pre class="trace-args"></pre></div>' +
            '<div class="trace-block"><span class="trace-label">返回</span><pre class="trace-result">等待执行…</pre></div>' +
          "</div>";

        const head = item.querySelector(".trace-head");
        head.addEventListener("click", () => item.classList.toggle("open"));

        item.querySelector(".trace-name").textContent = `MCP · ${data.name || "tool"}`;
        item.querySelector(".trace-args").textContent = JSON.stringify(data.arguments || {}, null, 2);
        trace.appendChild(item);
        toolMap.set(id, item);
      }

      if (scroll) scrollAfterPaint();
    }

    function finishTool(data) {
      const id = String(data.id || "");
      const item = toolMap.get(id) || Array.from(toolMap.values()).find(
        (el) => el.querySelector(".trace-name").textContent === `MCP · ${data.name || "tool"}`
      );
      if (!item) return;

      item.classList.remove("running");
      const resultText = String(data.result ?? "");
      const failed = /^(错误|工具执行失败|计算出错)/.test(resultText.trim());
      item.classList.add(failed ? "error" : "done");

      const status = item.querySelector(".trace-status");
      status.innerHTML = failed ? "执行出错" : "已完成";
      item.querySelector(".trace-result").textContent = resultText || "（无返回内容）";

      if (scroll) scrollAfterPaint();
    }

    function setAnswer(text, speak = true) {
      answered = true;
      errored = false;
      thinking.hidden = true;
      content.innerHTML = renderMarkdown(text);
      bubble._raw = text;
      actions.hidden = false;
      if (speak && state.voiceOn) speakText(text);
      if (scroll) scrollAfterPaint();
    }

    function setError(message) {
      errored = true;
      answered = false;
      thinking.hidden = true;
      bubble.classList.add("error-bubble");
      content.innerHTML = `<div class="error-text">${ICONS.alert}<span>${escapeHtml(message)}</span></div>`;
      actions.hidden = true;
      if (scroll) scrollAfterPaint();
    }

    function markStopped() {
      thinking.hidden = true;
      if (answered || errored) return;
      const note = document.createElement("div");
      note.className = "stopped-note";
      note.innerHTML = `${ICONS.stop}已停止生成`;
      bubble.insertBefore(note, content);
    }

    function finalize() {
      if (answered || errored) return;
      setError("本次没有收到有效回复，请稍后重试。");
    }

    return { row, bubble, addTool, finishTool, setAnswer, setError, markStopped, finalize, setStage };
  }

  /* ============================================================
     SSE 读取
     ============================================================ */
  async function readSSE(response, onEvent) {
    if (!response.body) throw new Error("当前浏览器不支持流式响应");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        let event = "message";
        const dataLines = [];
        chunk.split("\n").forEach((line) => {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        });

        if (dataLines.length) {
          const raw = dataLines.join("\n");
          try { onEvent(event, JSON.parse(raw)); } catch { /* 忽略无法解析的心跳 */ }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  function friendlyError(error) {
    const message = String(error && error.message ? error.message : error);
    if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {
      return "无法连接后端服务。请先在项目根目录运行 python frontend/app.py，再刷新页面。";
    }
    return message || "发生未知错误，请稍后重试。";
  }

  function handleEvent(event, data, turn) {
    switch (event) {
      case "session":
        if (data.session_id) {
          state.sessionId = data.session_id;
          try { localStorage.setItem(STORAGE.current, data.session_id); } catch { /* ignore */ }
        }
        break;
      case "status":
        turn.setStage(data.stage === "planning" ? "正在整理工具返回的结果…" : "正在理解你的需求…");
        break;
      case "tool_call":
        turn.addTool(data);
        break;
      case "tool_result":
        turn.finishTool(data);
        break;
      case "answer":
        turn.setAnswer(data.content || "");
        break;
      case "error":
        turn.setError(data.message || "智能体执行失败");
        break;
      default:
        break;
    }
  }

  /* ============================================================
     发送消息
     ============================================================ */
  function setBusy(busy) {
    state.busy = busy;
    els.composer.classList.toggle("busy", busy);
    els.input.disabled = busy;
    els.micBtn.disabled = busy;
    els.sendBtn.setAttribute("aria-label", busy ? "停止生成" : "发送消息");
    els.sendBtn.title = busy ? "停止生成" : "发送消息";
    if (busy) {
      stopListening();
      els.voiceHint.textContent = "智能体正在执行任务，可点击右侧按钮停止";
    } else {
      els.voiceHint.textContent = "Agent 可能会调用本地工具，请确认指令安全";
    }
  }

  async function sendMessage(raw) {
    const text = String(raw ?? "").trim();
    if (!text || state.busy) return;

    const sessionId = ensureSession();
    const isNew = !state.sessions.some((s) => s.id === sessionId);

    addUserMessage(text);
    els.input.value = "";
    autoResize();
    setBusy(true);

    if (isNew) {
      upsertSession(sessionId, makeTitle(text));
    } else {
      upsertSession(sessionId, null);
    }
    updateHeader(makeTitle(text), "智能体正在理解并执行任务…");

    const turn = addAssistantTurn();
    const controller = new AbortController();
    state.controller = controller;
    let failed = false;

    try {
      const response = await fetch(`${API_BASE}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
        signal: controller.signal,
      });

      if (!response.ok) {
        let detail = `请求失败（HTTP ${response.status}）`;
        try {
          const payload = await response.json();
          if (payload && payload.detail) {
            detail = Array.isArray(payload.detail)
              ? payload.detail.map((item) => item.msg || item).join("；")
              : payload.detail;
          }
        } catch { /* ignore */ }
        throw new Error(detail);
      }

      await readSSE(response, (event, data) => {
        if (event === "error") failed = true;
        handleEvent(event, data, turn);
      });
      turn.finalize();
    } catch (error) {
      if (error && error.name === "AbortError") {
        turn.markStopped();
      } else {
        failed = true;
        turn.setError(friendlyError(error));
      }
    } finally {
      state.controller = null;
      setBusy(false);
      const meta = state.sessions.find((s) => s.id === state.sessionId);
      if (meta) {
        meta.updatedAt = Date.now();
        saveSessions();
        renderSessions();
        updateHeader(meta.title, failed ? "本次任务执行失败，可重试或换个说法" : "多轮记忆已开启 · 工具调用实时可见");
      }
      els.input.focus();
    }
  }

  function stopGeneration() {
    if (!state.busy) return;
    if (state.controller) state.controller.abort();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    showToast("已停止生成");
  }

  /* ============================================================
     语音输入 / 朗读
     ============================================================ */
  function speakText(text) {
    if (!("speechSynthesis" in window)) {
      showToast("当前浏览器不支持语音朗读");
      return;
    }
    const spoken = plainText(text).slice(0, 1200);
    if (!spoken) return;

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.lang = "zh-CN";
    utterance.rate = 1.02;
    utterance.pitch = 1;

    const voices = window.speechSynthesis.getVoices();
    const chinese = voices.find((v) => /zh[-_]CN|Chinese|中文/i.test(`${v.lang} ${v.name}`));
    if (chinese) utterance.voice = chinese;

    window.speechSynthesis.speak(utterance);
  }

  function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      els.micBtn.disabled = true;
      els.micBtn.title = "当前浏览器不支持语音输入（推荐 Chrome / Edge）";
      els.voiceHint.textContent = "当前浏览器不支持语音输入，可改用 Chrome 或 Edge";
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = true;

    let baseText = "";
    let finalText = "";

    recognition.onstart = () => {
      state.listening = true;
      els.micBtn.classList.add("listening");
      els.voiceHint.textContent = "正在聆听… 说完后会自动停止";
    };

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += transcript;
        else interim += transcript;
      }
      const joined = `${baseText ? baseText + " " : ""}${finalText}${interim}`.trim();
      els.input.value = joined;
      autoResize();
    };

    recognition.onerror = (event) => {
      if (event.error === "not-allowed") {
        showToast("麦克风权限被拒绝，请在浏览器中允许访问");
      } else if (event.error === "no-speech") {
        showToast("没有听到语音，请再试一次");
      } else if (event.error !== "aborted") {
        showToast("语音输入出错：" + event.error);
      }
    };

    recognition.onend = () => {
      state.listening = false;
      els.micBtn.classList.remove("listening");
      els.voiceHint.textContent = state.busy
        ? "智能体正在执行任务，可点击右侧按钮停止"
        : "Agent 可能会调用本地工具，请确认指令安全";
      els.input.focus();
    };

    recognition.onstart = ((original) => () => {
      baseText = els.input.value.trim();
      finalText = "";
      original();
    })(recognition.onstart);

    state.recognition = recognition;

    els.micBtn.addEventListener("click", () => {
      if (state.busy) return;
      if (state.listening) {
        recognition.stop();
        return;
      }
      try {
        recognition.start();
      } catch {
        showToast("语音识别启动失败，请稍后重试");
      }
    });
  }

  function stopListening() {
    if (state.recognition && state.listening) {
      try { state.recognition.stop(); } catch { /* ignore */ }
    }
  }

  /* ============================================================
     输入框 / 侧边栏
     ============================================================ */
  function autoResize() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 160) + "px";
  }

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }

  function toggleSidebar() {
    document.body.classList.toggle("sidebar-open");
  }

  function bindEvents() {
    els.composer.addEventListener("submit", (event) => {
      event.preventDefault();
      if (state.busy) {
        stopGeneration();
        return;
      }
      sendMessage(els.input.value);
    });

    els.input.addEventListener("input", autoResize);
    els.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!state.busy) sendMessage(els.input.value);
      }
    });

    els.newChatBtn.addEventListener("click", newChat);

    els.suggestions.addEventListener("click", (event) => {
      const button = event.target.closest(".suggestion");
      if (!button) return;
      if (state.busy) {
        showToast("正在生成回复，请先停止当前任务");
        return;
      }
      const prompt = button.dataset.prompt || button.textContent.trim();
      els.input.value = prompt;
      autoResize();
      sendMessage(prompt);
    });

    els.themeToggle.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
    });

    els.voiceToggle.addEventListener("click", () => {
      state.voiceOn = !state.voiceOn;
      try { localStorage.setItem(STORAGE.voice, String(state.voiceOn)); } catch { /* ignore */ }
      updateVoiceButton();
      if (!state.voiceOn && "speechSynthesis" in window) window.speechSynthesis.cancel();
      showToast(state.voiceOn ? "已开启自动朗读" : "已关闭自动朗读");
    });

    els.menuBtn.addEventListener("click", toggleSidebar);
    els.sidebarOverlay.addEventListener("click", closeSidebar);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSidebar();
    });

    els.messages.addEventListener("click", async (event) => {
      const traceHead = event.target.closest(".trace-head");
      if (traceHead) {
        const item = traceHead.closest(".trace-item");
        if (item) item.classList.toggle("open");
        return;
      }

      const copyCode = event.target.closest(".copy-code");
      if (copyCode) {
        const block = copyCode.closest(".code-block");
        const code = block ? block.querySelector("code") : null;
        if (code) {
          const ok = await copyToClipboard(code.textContent || "");
          showToast(ok ? "代码已复制" : "复制失败，请手动选择");
        }
        return;
      }

      const action = event.target.closest(".msg-action");
      if (!action) return;
      const bubble = action.closest(".bubble");
      if (!bubble) return;

      if (action.dataset.action === "copy") {
        const text = bubble._raw || bubble.textContent || "";
        const ok = await copyToClipboard(text);
        showToast(ok ? "已复制回复内容" : "复制失败，请手动选择");
      } else if (action.dataset.action === "speak") {
        speakText(bubble._raw || bubble.textContent || "");
      }
    });
  }

  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch { /* 回退到 execCommand */ }

    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand("copy");
      textarea.remove();
      return ok;
    } catch {
      return false;
    }
  }

  /* ============================================================
     后端状态检查
     ============================================================ */
  async function checkHealth() {
    if (location.protocol === "file:") {
      els.statusCard.classList.add("offline");
      els.statusText.textContent = "请通过本地服务打开";
      els.statusSub.textContent = "运行 python frontend/app.py";
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
      if (!response.ok) throw new Error("unhealthy");
      const data = await response.json();
      if (!data.model_configured) {
        els.statusCard.classList.remove("online");
        els.statusCard.classList.add("offline");
        els.statusText.textContent = "需要配置模型密钥";
        els.statusSub.textContent = "设置 DASHSCOPE_API_KEY 后重启服务";
        return;
      }
      els.statusCard.classList.remove("offline");
      els.statusCard.classList.add("online");
      els.statusText.textContent = "Agent 在线";
      els.statusSub.textContent = `${(data.tools || []).length} 个 MCP 工具可用`;
    } catch {
      els.statusCard.classList.remove("online");
      els.statusCard.classList.add("offline");
      els.statusText.textContent = "服务未连接";
      els.statusSub.textContent = "请启动 python frontend/app.py";
    }
  }

  /* ============================================================
     初始化
     ============================================================ */
  async function init() {
    initTheme();
    updateVoiceButton();
    renderSessions();
    bindEvents();
    setupSpeechRecognition();
    checkHealth();

    if ("speechSynthesis" in window) {
      // 触发一次语音列表加载，部分浏览器需要异步获取
      window.speechSynthesis.getVoices();
    }

    let current = null;
    try { current = localStorage.getItem(STORAGE.current); } catch { /* ignore */ }

    if (current && state.sessions.some((s) => s.id === current)) {
      await openSession(current);
    } else {
      state.sessionId = uuid();
      try { localStorage.setItem(STORAGE.current, state.sessionId); } catch { /* ignore */ }
      updateHeader("新对话");
      renderSessions();
    }

    if (location.protocol === "file:") {
      showToast("请运行 python frontend/app.py 后访问 http://127.0.0.1:8000", 6000);
    }

    els.input.focus();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
