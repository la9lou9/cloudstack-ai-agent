(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const messages = $("messages");
  const input = $("input");
  const form = $("chat-form");
  const sendBtn = $("send-btn");
  const statusDot = $("status-dot");

  const threadId =
    (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
    `thread-${Date.now()}`;

  let busy = false;

  // ── Rendering ────────────────────────────────────────────────────────────
  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function inlineFormat(text) {
    return text
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function renderMarkdown(text) {
    const lines = escapeHtml(text).split("\n");
    let html = "";
    let inList = false;

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("- ")) {
        if (!inList) {
          html += "<ul>";
          inList = true;
        }
        html += `<li>${inlineFormat(trimmed.slice(2))}</li>`;
        continue;
      }
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      if (!trimmed) {
        html += '<div class="spacer"></div>';
      } else {
        html += `<p>${inlineFormat(trimmed)}</p>`;
      }
    }
    if (inList) html += "</ul>";
    return html;
  }

  function scrollToBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function addMessage(role, text, meta = {}) {
    const row = document.createElement("div");
    row.className = `msg ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "user" ? "You" : "CS";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = renderMarkdown(text);

    if (meta.mode || (meta.toolsUsed && meta.toolsUsed.length) || meta.note) {
      const metaRow = document.createElement("div");
      metaRow.className = "msg-meta";
      if (meta.mode) {
        const mode = document.createElement("span");
        mode.className = "mode-chip";
        mode.textContent = meta.mode === "agent" ? "LLM agent" : "Demo mode";
        metaRow.appendChild(mode);
      }
      for (const tool of meta.toolsUsed || []) {
        const chip = document.createElement("span");
        chip.className = "tool-chip";
        chip.textContent = tool;
        metaRow.appendChild(chip);
      }
      bubble.appendChild(metaRow);
    }

    if (meta.note) {
      const note = document.createElement("div");
      note.className = "note";
      note.textContent = meta.note;
      bubble.appendChild(note);
    }

    row.appendChild(avatar);
    row.appendChild(bubble);
    messages.appendChild(row);
    scrollToBottom();
    return row;
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "msg assistant typing";
    row.id = "typing";
    row.innerHTML = '<div class="avatar">CS</div><div class="bubble"><span></span><span></span><span></span></div>';
    messages.appendChild(row);
    scrollToBottom();
    return row;
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    statusDot.classList.toggle("busy", value);
  }

  // ── API ──────────────────────────────────────────────────────────────────
  async function api(path, options) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options && options.headers) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || data.error || `request failed (${response.status})`);
    }
    return data;
  }

  async function sendMessage(text) {
    const message = String(text || "").trim();
    if (!message || busy) return;

    addMessage("user", message);
    input.value = "";
    resizeInput();
    setBusy(true);
    showTyping();

    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message, thread_id: threadId }),
      });
      const typing = $("typing");
      if (typing) typing.remove();
      addMessage("assistant", data.answer || "No answer.", {
        mode: data.mode,
        toolsUsed: data.tools_used,
        note: data.note,
      });
      // A drift question can change the summary; a health question usually
      // does not. Refresh quietly either way so the sidebar stays current.
      loadHealth(false);
    } catch (error) {
      const typing = $("typing");
      if (typing) typing.remove();
      addMessage("assistant", `**Request failed**\n\n${error.message}`, { mode: "demo" });
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  // ── Sidebar ──────────────────────────────────────────────────────────────
  async function loadConfig() {
    try {
      const data = await api("/api/config");
      $("mode-badge").textContent = data.llm ? "LLM agent" : "Demo mode";
      $("source-badge").textContent = data.mock ? "Mock data" : "Live CloudStack";
      $("write-badge").classList.toggle("hidden", !data.allow_write);
      $("chat-subtitle").textContent = data.llm
        ? `LangGraph · ${data.model || "model"}`
        : "Demo mode · MCP tools available";
    } catch {
      $("mode-badge").textContent = "Offline";
      $("source-badge").textContent = "unknown";
    }
  }

  function stat(value, label, tone = "") {
    const el = document.createElement("div");
    el.className = "stat";
    const valueEl = document.createElement("div");
    valueEl.className = `stat-value ${tone}`.trim();
    valueEl.textContent = value;
    const labelEl = document.createElement("div");
    labelEl.className = "stat-label";
    labelEl.textContent = label;
    el.append(valueEl, labelEl);
    return el;
  }

  function issueRow(issue) {
    const row = document.createElement("div");
    row.className = "issue";
    const dot = document.createElement("span");
    dot.className = "issue-dot";
    const lower = issue.toLowerCase();
    if (lower.includes("not running") || lower.includes("critical")) dot.classList.add("error");
    const text = document.createElement("span");
    text.textContent = issue;
    row.append(dot, text);
    return row;
  }

  async function loadHealth(showErrors = true) {
    const stats = $("stats");
    const issues = $("issues");
    try {
      const health = await api("/api/health");
      stats.replaceChildren(
        stat(health.hosts.total, "hosts", health.hosts.down > 0 ? "bad" : ""),
        stat(
          health.system_vms.unhealthy,
          `system VMs unhealthy / ${health.system_vms.total}`,
          health.system_vms.unhealthy > 0 ? "bad" : "ok"
        ),
        stat(health.alerts.total, `alerts · ${health.alerts.warning} warn`, health.alerts.total > 0 ? "warn" : ""),
        stat(health.zones.total, "zones")
      );

      issues.replaceChildren();
      if (!health.issues || health.issues.length === 0) {
        const ok = document.createElement("div");
        ok.className = "issue-ok";
        ok.textContent = "No issues detected";
        issues.appendChild(ok);
      } else {
        for (const issue of health.issues.slice(0, 6)) {
          issues.appendChild(issueRow(issue));
        }
        if (health.issues.length > 6) {
          const more = document.createElement("p");
          more.className = "muted small";
          more.textContent = `+ ${health.issues.length - 6} more issue(s)`;
          issues.appendChild(more);
        }
      }
    } catch (error) {
      if (!showErrors) return;
      stats.replaceChildren();
      issues.innerHTML = `<p class="muted small">Could not load health: ${escapeHtml(error.message)}</p>`;
    }
  }

  // ── Composer ─────────────────────────────────────────────────────────────
  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input.value);
    }
  });

  document.querySelectorAll(".chip[data-q]").forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.dataset.q));
  });

  $("refresh-health").addEventListener("click", () => loadHealth(true));
  $("run-drift").addEventListener("click", () =>
    sendMessage("Show the drift against the deployment contract")
  );

  // ── Boot ─────────────────────────────────────────────────────────────────
  loadConfig();
  loadHealth();
  input.focus();
})();
