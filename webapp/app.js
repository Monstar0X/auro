(() => {
const tg = window.Telegram && Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); try { tg.setHeaderColor("#0e101e"); tg.setBackgroundColor("#0e101e"); } catch (e) {} }
const q = new URLSearchParams(location.search);
// Local development (server run with DEV_AUTH=1):  /?dev=1:Alice&night=1
const DEV = q.get("dev");
const initData = (tg && tg.initData) || "";
const startParam = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || "";
let nightId = q.get("night") || (startParam.startsWith("night_") ? startParam.slice(6) : null);

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const toast = (m) => { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 2400); };

async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (DEV) headers["X-Dev-User"] = DEV; else headers["X-Init-Data"] = initData;
  const r = await fetch(path, { method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.blob();
  if (!r.ok) throw new Error((data && data.error) || "Request failed");
  return data;
}

// ---------------------------------------------------------------- tabs
document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => show(b.dataset.tab));
function show(tab) {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x.id === tab));
  if (tab === "board") loadBoard(); if (tab === "dna") loadDna();
}

// ---------------------------------------------------------------- swipe deck
let deck = [], night = null, busy = false;
const COLORS = ["#3a1f66", "#1f3a66", "#661f4a", "#1f6652", "#66531f"];

function cardHtml(c) {
  const bg = c.cover ? `background-image:url('${esc(c.cover)}')` : `background:linear-gradient(135deg,${COLORS[c.id % 5]},#0e101e)`;
  const chips = [];
  if (c.badge) chips.push(`<span class="chip hot">${esc(c.badge)}</span>`);
  if (c.airing) chips.push(`<span class="chip live">airing</span>`);
  if (c.episodes) chips.push(`<span class="chip">${c.episodes} eps</span>`);
  if (c.runtime) chips.push(`<span class="chip">${Math.floor(c.runtime / 60)}h${String(c.runtime % 60).padStart(2, "0")}m</span>`);
  (c.genres || []).slice(0, 3).forEach((g) => chips.push(`<span class="chip">${esc(g)}</span>`));
  return `<div class="art" style="${bg}"></div><div class="shade"></div>
  <div class="stamp l">LIKE</div><div class="stamp n">NOPE</div><div class="stamp s">SUPER</div>
  <div class="info"><h2>${esc(c.title)}</h2><div class="chips">${chips.join("")}</div>
  <div class="score">${c.my_score != null ? `<span>You'd rate it <b>${c.my_score}</b></span>` : ""}${c.avg ? `<span>Crowd ${c.avg}</span>` : ""}</div></div>`;
}

function renderDeck() {
  const el = $("#deck"); el.innerHTML = "";
  if (!deck.length) {
    el.innerHTML = `<div class="empty">That's the whole deck 🎉<br>Open <b>Verdict</b> to see what the group is leaning towards.</div>`;
    $("#actions").style.display = "none"; return;
  }
  $("#actions").style.display = "flex";
  deck.slice(0, 3).reverse().forEach((c, i, arr) => {
    const d = document.createElement("div"); d.className = "card"; d.dataset.id = c.id; d.innerHTML = cardHtml(c);
    const depth = arr.length - 1 - i; d.style.transform = `scale(${1 - depth * .04}) translateY(${depth * 10}px)`;
    el.appendChild(d); if (depth === 0) attachDrag(d, c);
  });
}

function attachDrag(el, c) {
  let sx = 0, sy = 0, dx = 0, dy = 0, on = false;
  const L = el.querySelector(".stamp.l"), N = el.querySelector(".stamp.n"), S = el.querySelector(".stamp.s");
  el.onpointerdown = (e) => { on = true; sx = e.clientX; sy = e.clientY; el.classList.add("drag"); el.setPointerCapture(e.pointerId); };
  el.onpointermove = (e) => {
    if (!on) return; dx = e.clientX - sx; dy = e.clientY - sy;
    el.style.transform = `translate(${dx}px,${dy}px) rotate(${dx / 18}deg)`;
    L.style.opacity = Math.max(0, dx / 110); N.style.opacity = Math.max(0, -dx / 110); S.style.opacity = Math.max(0, -dy / 110);
  };
  el.onpointerup = () => {
    if (!on) return; on = false; el.classList.remove("drag");
    if (dy < -110 && Math.abs(dx) < 90) return vote("super"); if (dx > 100) return vote("like"); if (dx < -100) return vote("nope");
    el.style.transform = ""; L.style.opacity = N.style.opacity = S.style.opacity = 0;
  };
}

async function vote(v) {
  if (busy || !deck.length) return; busy = true;
  const c = deck[0], el = $("#deck .card:last-child");
  if (el) { el.classList.remove("drag"); const x = v === "like" ? 500 : v === "nope" ? -500 : 0, y = v === "super" ? -600 : v === "veto" ? 500 : 0;
    el.style.transform = `translate(${x}px,${y}px) rotate(${x / 14}deg)`; el.style.opacity = 0; }
  try { await api(`/api/night/${nightId}/swipe`, { media_id: c.id, vote: v }); }
  catch (e) { toast(e.message); busy = false; return; }
  deck.shift(); setTimeout(() => { renderDeck(); busy = false; }, 200);
  if (v === "veto") toast("Vetoed for everyone 🚫");
  if (deck.length % 8 === 0) refreshDeck();   // swipes teach the engine - re-rank the remaining cards
}
$("#b-like").onclick = () => vote("like"); $("#b-nope").onclick = () => vote("nope");
$("#b-super").onclick = () => vote("super"); $("#b-veto").onclick = () => confirmVeto();
function confirmVeto() {
  if (tg && tg.showConfirm) tg.showConfirm("Veto removes this show for EVERYONE tonight. Sure?", (ok) => ok && vote("veto"));
  else if (confirm("Veto removes this show for everyone. Sure?")) vote("veto");
}

async function refreshDeck() {
  try { const r = await api(`/api/night/${nightId}`); deck = r.deck; night = r.night; renderDeck(); } catch (e) { /* keep current deck */ }
}

async function loadNight() {
  if (!nightId) {
    $("#night-meta").textContent = "";
    $("#deck").innerHTML = `<div class="empty">No night selected.<br>Start one in your group with <b>/night</b>, then tap the Swipe button on that message.</div>`;
    $("#actions").style.display = "none"; return;
  }
  try {
    const r = await api(`/api/night/${nightId}`); deck = r.deck; night = r.night;
    $("#night-meta").textContent = `Night #${night.id}${night.mood_label ? " · " + night.mood_label : ""} · ${r.members.length} in`;
    if (night.status !== "open") { show("board"); return; }
    renderDeck();
  } catch (e) { $("#deck").innerHTML = `<div class="empty">${esc(e.message)}</div>`; $("#actions").style.display = "none"; }
}

// ---------------------------------------------------------------- verdict board
async function loadBoard() {
  const body = $("#board-body");
  if (!nightId) { body.innerHTML = `<div class="empty">Open a night first.</div>`; return; }
  body.innerHTML = `<div class="empty">Crunching…</div>`;
  try {
    const r = await api(`/api/night/${nightId}/result`); const n = r.night, done = n.status !== "open";
    let h = `<div class="panel"><h3>${done ? "Decided ✅" : "Live standings"} ${r.fairness != null ? `<span class="pill">fairness ${r.fairness}%</span>` : ""}</h3>
      <div style="color:var(--mut);font-size:12px">${r.members.map((m) => esc(m.name) + (m.linked ? " ✓" : " (guest)") + ` · ${m.swipes} swipes`).join("  |  ")}</div></div>`;
    h += r.ranking.map((c, i) => `<div class="panel ${i === 0 ? "win" : ""}"><div class="row">
      ${c.cover ? `<img src="${esc(c.cover)}" alt="">` : `<div class="ph"></div>`}
      <div class="t"><b>${i + 1}. ${esc(c.title)}</b><span>${esc(c.badge || "")}${c.runtime ? " · " + Math.floor(c.runtime / 60) + "h" + String(c.runtime % 60).padStart(2, "0") : ""}${c.likes ? " · 👍 " + c.likes : ""}</span>
      ${c.sacrifice ? `<span style="color:var(--pink)">🤝 ${esc(c.sacrifice)} compromises</span>` : ""}</div><b style="color:var(--cyan)">${c.score}</b></div>
      ${c.per_member.map((p) => `<div style="font-size:12px;color:var(--mut)">${esc(p.name)} ${p.score}<div class="bar"><i style="width:${p.score}%"></i></div></div>`).join("")}</div>`).join("");
    if (!r.ranking.length) h += `<div class="empty">Nothing survives everyone's filters yet.<br>Loosen the rules or swipe more.</div>`;
    if (!done && r.ranking.length && night && night.creator === myId) h += `<button class="btn" id="lock">⚡ Lock the verdict</button>`;
    body.innerHTML = h;
    const lock = $("#lock"); if (lock) lock.onclick = async () => {
      lock.disabled = true;
      try { await api(`/api/night/${nightId}/decide`, {}); toast("Locked! Posted to the group."); loadBoard(); } catch (e) { toast(e.message); lock.disabled = false; } };
  } catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// ---------------------------------------------------------------- DNA
let myId = null;
async function loadDna() {
  const body = $("#dna-body");
  try {
    const me = await api("/api/me"); myId = me.user.id;
    if (!me.dna) {
      body.innerHTML = `<div class="panel"><h3>Link your AniList</h3><p style="color:var(--mut);font-size:13px">Your profile must be public. Quorum reads your ratings to build your Taste DNA and predict what you'll enjoy.</p>
        <input id="al" placeholder="AniList username" autocapitalize="off" autocomplete="off"><button class="btn" id="go">Build my DNA</button></div>`;
      $("#go").onclick = async () => { const v = $("#al").value.trim(); if (!v) return; $("#go").disabled = true; $("#go").textContent = "Reading your list…";
        try { await api("/api/link", { anilist: v }); loadDna(); refreshDeck(); } catch (e) { toast(e.message); $("#go").disabled = false; $("#go").textContent = "Build my DNA"; } };
      return;
    }
    const d = me.dna;
    const blob = await api("/api/me/card.png"); const url = URL.createObjectURL(blob);
    body.innerHTML = `<img class="dna-card" src="${url}" alt="Taste DNA card">
      <div class="panel"><h3>${esc(d.archetype)}</h3><div style="color:var(--mut);font-size:13px">${esc(d.blurb)}</div></div>
      <div class="panel"><h3>Top genres</h3>${d.genres.map((g) => `<div style="font-size:13px">${esc(g.name)}<div class="bar"><i style="width:${Math.max(5, Math.min(100, 50 + g.weight * 100))}%"></i></div></div>`).join("")}</div>
      <button class="btn ghost" id="relink">Re-sync / change AniList</button>`;
    $("#relink").onclick = async () => { const v = prompt("AniList username", me.user.anilist || ""); if (!v) return;
      try { toast("Syncing…"); await api("/api/link", { anilist: v }); loadDna(); refreshDeck(); } catch (e) { toast(e.message); } };
  } catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

(async () => { try { const me = await api("/api/me"); myId = me.user.id; if (!nightId && me.start_param.startsWith("night_")) nightId = me.start_param.slice(6); } catch (e) { toast(e.message); }
  await loadNight(); if (!nightId) show("dna"); })();
})();
