// League chat: prove you own a Sleeper team, then talk with your leaguemates.
// Everything a user typed is set with textContent — this file never builds HTML.
// Loaded after app.js, so $, api, state, activeTeam and showToast are in scope.

const CHAT_POLL_MS = 5000;
const CHAT_FULL_REFRESH_EVERY = 6; // every 6th poll re-reads the latest page so deleted messages vanish for everyone

const chatState = { leagueId: null, lastId: 0, timer: null, role: null, me: null, polls: 0, busy: false };

function mk(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function chatSend(path, method, body) {
  return api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

function chatLeagues() {
  const seen = new Map();
  (state.teams || []).filter((t) => t.platform === "sleeper").forEach((t) => {
    if (!seen.has(t.league_id)) seen.set(t.league_id, t.league_name || `League ${t.league_id}`);
  });
  return [...seen].map(([id, name]) => ({ id, name }));
}

function stopChatPolling() {
  if (chatState.timer) clearInterval(chatState.timer);
  chatState.timer = null;
}

function startChatPolling() {
  stopChatPolling();
  chatState.timer = setInterval(() => { if (!document.hidden) pollChat(false); }, CHAT_POLL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { stopChatPolling(); return; }
  if (state.tab === "chat" && $("#chat-list")) { pollChat(true); startChatPolling(); }
});

async function loadChatTab() {
  stopChatPolling();
  const root = $("#chat-body");
  root.replaceChildren();
  if (!state.user) { root.append(mk("p", "hint", "Sign in to chat with your league.")); return; }

  const leagues = chatLeagues();
  if (!leagues.length) {
    root.append(mk("p", "hint", (state.teams || []).length
      ? "League chat is Sleeper-only for now."
      : "Connect a Sleeper league in Settings to chat with your league."));
    return;
  }
  if (!leagues.some((l) => l.id === chatState.leagueId)) {
    const active = activeTeam();
    chatState.leagueId = (active && leagues.find((l) => l.id === active.league_id) || leagues[0]).id;
  }
  if (leagues.length > 1) root.append(chatLeaguePicker(leagues));

  const panel = mk("div", "chat-panel");
  root.append(panel);
  const league = chatState.leagueId;
  try {
    const res = await api(`/api/chat/messages?platform=sleeper&league_id=${encodeURIComponent(league)}`);
    if (state.tab !== "chat" || chatState.leagueId !== league) return;
    chatState.role = res.role;
    showChat(panel, res.messages);
  } catch (e) {
    if (state.tab !== "chat" || chatState.leagueId !== league) return;
    if (e.status === 403) showChatVerify(panel); else panel.append(mk("p", "hint", e.message));
  }
}

function chatLeaguePicker(leagues) {
  const select = mk("select", "chat-league-picker");
  select.setAttribute("aria-label", "League");
  leagues.forEach((l) => {
    const opt = mk("option", null, l.name);
    opt.value = l.id;
    opt.selected = l.id === chatState.leagueId;
    select.append(opt);
  });
  select.addEventListener("change", () => { chatState.leagueId = select.value; loadChatTab(); });
  return select;
}

function showChatVerify(panel) {
  panel.replaceChildren();
  panel.append(mk("h3", null, "Verify your Sleeper team"));
  panel.append(mk("p", "hint",
    "Only people who own a team in this league can read or post. We give you a short code: " +
    "put it anywhere in your Sleeper team name, save it in Sleeper, then press Verify. " +
    "You can remove it afterwards."));

  const codeLine = mk("div", "chat-code");
  const getBtn = mk("button", "primary-btn", "Get my code");
  const verifyBtn = mk("button", "primary-btn", "I saved it — verify");
  verifyBtn.style.display = "none";
  panel.append(getBtn, codeLine, verifyBtn);

  getBtn.addEventListener("click", async () => {
    getBtn.disabled = true;
    try {
      const res = await chatSend("/api/chat/challenge", "POST", { platform: "sleeper", league_id: chatState.leagueId });
      codeLine.textContent = res.token;
      verifyBtn.style.display = "";
      getBtn.textContent = "Get a new code";
    } catch (e) { showToast(e.message, "error"); }
    getBtn.disabled = false;
  });

  verifyBtn.addEventListener("click", async () => {
    verifyBtn.disabled = true;
    try {
      await chatSend("/api/chat/join", "POST", { platform: "sleeper", league_id: chatState.leagueId, token: codeLine.textContent });
      loadChatTab();
    } catch (e) { showToast(e.message, "error"); }
    verifyBtn.disabled = false;
  });
}

function showChat(panel, messages) {
  panel.replaceChildren();
  const list = mk("div", "chat-list");
  list.id = "chat-list";
  list.setAttribute("aria-live", "polite");
  const form = mk("form", "chat-composer");
  const input = mk("input");
  input.type = "text";
  input.maxLength = 500;
  input.placeholder = "Message your league";
  input.setAttribute("aria-label", "Message");
  const send = mk("button", "primary-btn", "Send");
  send.type = "submit";
  form.append(input, send);
  panel.append(list, form);

  chatState.lastId = 0;
  chatState.polls = 0;
  renderChatMessages(list, messages, true);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = input.value.trim();
    if (!body) return;
    send.disabled = true;
    try {
      await chatSend("/api/chat/messages", "POST", { platform: "sleeper", league_id: chatState.leagueId, body });
      input.value = "";
      pollChat(false);
    } catch (e) { showToast(e.message, "error"); }
    send.disabled = false;
    input.focus();
  });
  startChatPolling();
}

async function pollChat(full) {
  const list = $("#chat-list");
  if (!list || chatState.busy || state.tab !== "chat") return;
  chatState.polls += 1;
  const refresh = full || chatState.polls % CHAT_FULL_REFRESH_EVERY === 0;
  const league = chatState.leagueId;
  chatState.busy = true;
  try {
    const after = refresh ? 0 : chatState.lastId;
    const res = await api(`/api/chat/messages?platform=sleeper&league_id=${encodeURIComponent(league)}&after=${after}`);
    if (chatState.leagueId !== league || $("#chat-list") !== list) return;
    chatState.role = res.role;
    renderChatMessages(list, res.messages, refresh);
  } catch (e) {
    if (e.status === 403) loadChatTab();
  } finally {
    chatState.busy = false;
  }
}

function renderChatMessages(list, messages, replace) {
  const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  if (replace) list.replaceChildren();
  if (replace && !messages.length) list.append(mk("p", "hint chat-empty", "No messages yet. Say hi."));
  if (!replace && messages.length) list.querySelector(".chat-empty")?.remove();
  messages.forEach((m) => {
    list.append(chatMessageNode(m));
    chatState.lastId = Math.max(chatState.lastId, m.id);
  });
  if (replace || nearBottom) list.scrollTop = list.scrollHeight;
}

function chatMessageNode(m) {
  const row = mk("div", "chat-msg");
  row.dataset.id = m.id;
  const head = mk("div", "chat-msg-head");
  head.append(mk("span", "chat-author", m.username));
  head.append(mk("time", "chat-time", new Date(m.created_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })));
  row.append(head, mk("div", "chat-body-text", m.body));

  const mine = state.user && m.user_id === state.user.id;
  const actions = mk("div", "chat-actions");
  const act = (label, fn) => {
    const b = mk("button", "chat-action", label);
    b.type = "button";
    b.addEventListener("click", fn);
    actions.append(b);
  };
  if (!mine) act("Report", async () => {
    try { await chatSend("/api/chat/report", "POST", { message_id: m.id }); showToast("Reported. Thanks.", "success"); }
    catch (e) { showToast(e.message, "error"); }
  });
  if (mine || chatState.role === "moderator") act("Delete", async () => {
    if (!confirm("Delete this message?")) return;
    try { await chatSend(`/api/chat/messages/${m.id}`, "DELETE"); row.remove(); }
    catch (e) { showToast(e.message, "error"); }
  });
  if (!mine && chatState.role === "moderator") act("Mute 1h", async () => {
    try {
      await chatSend("/api/chat/mute", "POST", { platform: "sleeper", league_id: chatState.leagueId, user_id: m.user_id, minutes: 60 });
      showToast(`${m.username} is muted for an hour.`, "success");
    } catch (e) { showToast(e.message, "error"); }
  });
  row.append(actions);
  return row;
}
