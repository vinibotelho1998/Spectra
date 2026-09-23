"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

const API = {
  async get(p) {
    const r = await fetch(p, { cache: "no-store" });
    if (!r.ok) throw new Error(`${p}: ${r.status}`);
    return r.json();
  },
  async post(p, body) {
    const r = await fetch(p, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const j = await r.json().catch(() => ({}));
    if (j && j.error) throw new Error(j.error);
    return j;
  },
};

const S = {
  catalog: null,
  state: null,
  selected: null,
  hex: "",
  positions: [],
  zones: [],
  glow: true,
  labels: false,
  liveLayout: true,
  selZone: null,
  effectPickTarget: null,
  fps: null,
  live: {},
  prevBright: 100,
  undo: null,
};

/** Espaca as chamadas de uma funcao: o slider dispara a cada pixel, mas so o
 *  ultimo valor de cada janela precisa virar pedido para o servidor. */
function throttle(fn, ms) {
  let t = null, last = null;
  return (...a) => {
    last = a;
    if (t) return;
    t = setTimeout(() => { t = null; fn(...last); }, ms);
  };
}

let toastTimer = null;
function toast(msg, isErr, action) {
  const el = $("#toast");
  el.innerHTML = "";
  el.appendChild(document.createTextNode(msg));
  if (action) {
    const b = document.createElement("button");
    b.className = "act";
    b.textContent = action.label;
    b.addEventListener("click", () => { el.hidden = true; action.run(); });
    el.appendChild(b);
  }
  el.classList.toggle("err", !!isErr);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true),
                          isErr ? 6000 : action ? 7000 : 2400);
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Texto para comparar em busca: sem acento e em minusculas. Os rotulos
 *  estao sem acento, e quem digitava "fumaça" recebia "Nada encontrado". */
function semAcento(s) {
  return String(s || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** "A", "A e B", "A, B e C". */
function listaNomes(nomes) {
  if (nomes.length <= 1) return nomes.join("");
  return nomes.slice(0, -1).join(", ") + " e " + nomes[nomes.length - 1];
}

/** Contagens de LED digitadas e ainda nao aplicadas, por conector. A lista
 *  e remontada quando o estado muda, e sem isso o numero digitado num
 *  conector sumia assim que a pessoa ia digitar no seguinte. Cada rascunho
 *  guarda a contagem que valia ao ser digitado: se ela mudou por outro
 *  caminho, como o assistente, o rascunho perde a validade, senao o campo
 *  mostraria o numero velho e um Aplicar desfaria a contagem nova. */
const RASCUNHO_LEDS = new Map();

function rascunhoLeds(chave, atual) {
  const r = RASCUNHO_LEDS.get(chave);
  return r && r.base === atual ? r.valor : null;
}

function guardaRascunhoLeds(chave, atual, valor) {
  RASCUNHO_LEDS.set(chave, { valor, base: atual });
}

/* ------------------------------------------------------------- navegacao */

function showTab(name) {
  const btn = $(`.navbtn[data-tab="${name}"]`);
  if (!btn) return;
  $$(".navbtn").forEach((x) => x.classList.remove("active"));
  $$(".tab").forEach((x) => x.classList.remove("active"));
  btn.classList.add("active");
  $("#tab-" + name).classList.add("active");
  if (name === "effects") {
    renderPresets(); renderAvisoExclusivo(); renderSetupBanner(); renderNowPlaying();
  }
  if (name === "layout") { renderZoneChips(); drawLayout(); }
  if (name === "sources") renderSources();
  if (name === "devices") renderDevices(true);
  if (name === "profiles") renderProfiles();
  if (name === "settings") renderSettings();
}

function activeTab() {
  const el = $(".tab.active");
  return el ? el.id.replace("tab-", "") : "effects";
}

$$(".navbtn").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));

$("#status").addEventListener("click", () => showTab("devices"));

/* -------------------------------------------------------------- desenho */

const pv = $("#preview");
const pctx = pv.getContext("2d", { alpha: false });
const pv2 = $("#preview2");
const pctx2 = pv2.getContext("2d", { alpha: false });
const lc = $("#layoutCanvas");
const lctx = lc.getContext("2d");

function fitCanvas(cv) {
  const r = cv.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  if (cv.width !== w * dpr || cv.height !== h * dpr) {
    cv.width = w * dpr;
    cv.height = h * dpr;
  }
  return { w, h, dpr };
}

const PAD = 26;
/** Escala unica nos dois eixos, centrada. O motor trata o gabinete como um
 *  quadrado, com anel de raio unico; esticar cada eixo para a medida do
 *  canvas fazia fan virar elipse e cada aba mostrar um gabinete de formato
 *  diferente. */
function escala(w, h) {
  const s = Math.max(1, Math.min(w, h) - PAD * 2);
  return { s, ox: (w - s) / 2, oy: (h - s) / 2 };
}

function project(x, y, w, h) {
  const { s, ox, oy } = escala(w, h);
  return [ox + x * s, oy + y * s];
}

/** Cor do LED i no quadro atual, direto da string hex que veio do stream. */
function ledColor(i) {
  const off = i * 6;
  return off + 6 <= S.hex.length ? "#" + S.hex.slice(off, off + 6) : "#000000";
}

function ledIsOff(i) {
  const off = i * 6;
  return off + 6 > S.hex.length || S.hex.charCodeAt(off) === 48 &&
         S.hex.slice(off, off + 6) === "000000";
}

/* Um brilho radial por LED custava um gradiente novo a cada quadro. Em vez
   disso, cada cor ganha um sprite de 64px desenhado uma vez e reaproveitado. */
const glowCache = new Map();
function glowSprite(color) {
  let c = glowCache.get(color);
  if (c) return c;
  if (glowCache.size > 400) glowCache.clear();
  c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, color + "88");
  grad.addColorStop(0.45, color + "22");
  grad.addColorStop(1, color + "00");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  glowCache.set(color, c);
  return c;
}

function drawPreview(cv, ctx) {
  const { w, h, dpr } = fitCanvas(cv);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#05070a";
  ctx.fillRect(0, 0, w, h);

  const pos = S.positions;
  if (!pos.length) return;
  const n = pos.length;
  const radius = clamp(Math.min(w, h) / Math.sqrt(n) / 3.4, 2.6, 11);

  if (S.glow) {
    ctx.globalCompositeOperation = "lighter";
    const R = radius * 4.2;
    for (let i = 0; i < n; i++) {
      if (ledIsOff(i)) continue;
      const [px, py] = project(pos[i][0], pos[i][1], w, h);
      ctx.drawImage(glowSprite(ledColor(i)), px - R, py - R, R * 2, R * 2);
    }
    ctx.globalCompositeOperation = "source-over";
  }

  ctx.strokeStyle = "rgba(255,255,255,.10)";
  ctx.lineWidth = 1;
  for (let i = 0; i < n; i++) {
    const [px, py] = project(pos[i][0], pos[i][1], w, h);
    ctx.fillStyle = S.hex ? ledColor(i) : "#0a0d12";
    ctx.beginPath();
    ctx.arc(px, py, radius, 0, 6.284);
    ctx.fill();
    ctx.stroke();
  }

  if (S.labels) {
    ctx.font = "10px 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    const rotulos = [];
    for (const z of S.zones) {
      const p = zoneCentroid(z, w, h);
      if (p) rotulos.push({ txt: z.zone_name, x: p[0], y: p[1] - 12 });
    }
    for (const r of afastaRotulos(ctx, rotulos)) {
      ctx.fillStyle = "rgba(0,0,0,.65)";
      ctx.fillRect(r.x - r.w / 2, r.y - 10, r.w, 14);
      ctx.fillStyle = "#cbd5e5";
      ctx.fillText(r.txt, r.x, r.y);
    }
  }
}

/** Desce o rotulo que cairia em cima de outro ja posto. Zonas vizinhas no
 *  mapa, como um pente de RAM e um conector da placa-mae, escreviam o nome
 *  uma por cima da outra e nenhum dos dois dava para ler. */
function afastaRotulos(ctx, itens) {
  const postos = [];
  for (const it of itens) {
    const w = ctx.measureText(it.txt).width + 8;
    let y = it.y;
    for (let tentativa = 0; tentativa < 12; tentativa++) {
      const bate = postos.some((o) => Math.abs(o.x - it.x) < (o.w + w) / 2 &&
                                     Math.abs(o.y - y) < 15);
      if (!bate) break;
      y += 15;
    }
    postos.push({ ...it, y, w });
  }
  return postos;
}

function zoneCentroid(z, w, h) {
  const pos = S.positions.slice(z.start, z.start + z.count);
  if (!pos.length) return null;
  let sx = 0, sy = 0;
  for (const p of pos) { sx += p[0]; sy += p[1]; }
  return project(sx / pos.length, sy / pos.length, w, h);
}

/** Redesenha assim que a janela volta a aparecer: com ela escondida o
 *  navegador congela o requestAnimationFrame, e o canvas ficaria no ultimo
 *  quadro de antes. */
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) redrawAll();
});

function redrawAll() {
  drawPreview(pv, pctx);
  drawPreview(pv2, pctx2);
  drawLayout();
}

function rafLoop() {
  if (!document.hidden) {
    const t = activeTab();
    if (t === "scene") drawPreview(pv, pctx);
    else if (t === "effects") drawPreview(pv2, pctx2);
    else if (t === "layout" && S.liveLayout) drawLayout();
  }
  requestAnimationFrame(rafLoop);
}

/* --------------------------------------------------------------- estado */

/** Recebe os quadros por Server-Sent Events, com volta ao laco de pedidos
 *  se o navegador nao sustentar o stream. */
function startStream() {
  let opened = false;
  let es;
  try {
    es = new EventSource("/api/stream");
  } catch (e) {
    return startPolling();
  }
  es.onopen = () => { opened = true; };
  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    S.hex = d.h || "";
    S.live = d.src || {};
    if (d.fps != null) setFps(d.fps);
    if (activeTab() === "sources") updateLiveMeters();
  };
  es.onerror = () => {
    if (!opened) { es.close(); startPolling(); }
  };
}

let pollTimer = null;
function startPolling() {
  if (pollTimer) return;
  let busy = false;
  pollTimer = setInterval(async () => {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const d = await API.get("/api/preview");
      S.hex = d.hex || "";
      S.live = d.src || {};
      setFps(d.fps);
    } catch (e) {
    } finally { busy = false; }
  }, 40);
}

function setFps(v) {
  S.fps = v;
  $("#fpsVal").textContent = v != null ? v.toFixed(0) : "—";
}

async function refreshState() {
  let st;
  try {
    st = await API.get("/api/state");
  } catch (e) {
    setStatus("err", "servidor local fora do ar");
    return;
  }
  const before = S.state;
  S.state = st;
  S.positions = (st.canvas && st.canvas.positions) || [];
  S.zones = (st.canvas && st.canvas.zones) || [];
  const pausado = !!(st.settings && st.settings.paused);
  setStatus(st.connected ? "ok" : st.connecting ? "busy" : "err",
            (st.status || "") + (pausado && st.connected ? " · efeitos pausados" : ""));
  $("#ledVal").textContent = st.canvas ? st.canvas.led_count : "—";
  // sem o motor no ar, a vitrine e o + Camada so devolviam erro de Python
  document.body.classList.toggle("sem-motor", !st.canvas);
  renderCanvasVazio($("#canvasEmpty"), st, false);
  renderCanvasVazio($("#canvasEmpty2"), st, true);
  renderCanvasVazio($("#layoutEmpty"), st, false);

  if (st.settings) {
    const b = Math.round((st.settings.brightness ?? 1) * 100);
    if (document.activeElement !== $("#brightness")) {
      $("#brightness").value = b;
      $("#brightVal").textContent = b + "%";
    }
    if (b > 0) S.prevBright = b;
    const power = $("#btnPower");
    power.classList.toggle("on", b > 0);
    power.classList.toggle("off", b === 0);
    power.title = b === 0 ? "Acender os LEDs" : "Apagar os LEDs";
    $("#btnPause").textContent = st.settings.paused ? "Retomar" : "Pausar";
    $("#btnPause").classList.toggle("primary", !!st.settings.paused);
  }

  renderLayers();
  const tab = activeTab();
  if (tab === "effects") {
    renderAvisoExclusivo();
    renderSetupBanner();
    renderNowPlaying();
    markActivePreset();
  }
  if (tab === "devices") renderDevices();
  if (tab === "sources") {
    updateSensorMeters();
    // a captura que caiu ou o dispositivo que nao abriu aparecem sem
    // precisar trocar de aba; com um campo em uso, espera ele sair
    if (fontesSig(st) !== ultimoFontesSig && !digitandoEm($("#sourcesBody"))) renderSources();
  }
  if (tab === "layout") renderZoneChips();
  if (tab === "settings" && settingsNeedsRedraw(before, st)) renderSettings();

  // conectou depois da janela abrir: a vitrine e o mapa mudam de vez
  if (before && !before.connected && st.connected) {
    renderPresets();
    if (tab === "devices") renderDevices(true);
    if (tab === "sources") renderSources();
  }
  if (st.last_error) console.warn("render:", st.last_error);
}

function digitandoEm(box) {
  const foco = document.activeElement;
  return !!(box && foco && box.contains(foco) && typing(foco));
}

/** O aviso por cima do mapa quando nao ha LED para desenhar, com o motivo
 *  certo: antes dizia para configurar os conectores mesmo quando o problema
 *  era o OpenRGB fora do ar. */
function renderCanvasVazio(el, st, compacto) {
  if (!el) return;
  const temLeds = !!(st.canvas && st.canvas.led_count);
  el.hidden = temLeds;
  if (temLeds) return;
  const k = st.connecting && !st.connected ? "conectando"
    : !st.connected || !st.canvas ? "sem_conexao"
    : (st.zones_resizable || []).length ? "sem_leds" : "sem_controle";
  if (el.dataset.k === k) return;
  el.dataset.k = k;
  const textos = {
    conectando: ["Conectando ao OpenRGB…", "Subindo o servidor e detectando o hardware."],
    sem_conexao: ["Sem conexao com o OpenRGB", "Sem ele no ar nenhum LED e alcancado."],
    sem_leds: ["Nenhum LED no mapa", "Diga quantos LEDs cada conector tem."],
    sem_controle: ["Nenhum LED ativo", "Confira a aba Hardware: os dispositivos podem estar fora do controle."],
  }[k];
  el.innerHTML = `<p>${esc(textos[0])}</p>` +
    (compacto ? "" : `<p class="muted">${esc(textos[1])}</p>`);
  if (compacto) return;
  const b = document.createElement("button");
  b.className = "btn sm";
  if (k === "sem_conexao") {
    b.textContent = "Tentar de novo";
    b.addEventListener("click", () => reconectar(b));
  } else if (k === "sem_leds") {
    b.className = "btn sm primary";
    b.textContent = "Abrir assistente";
    b.addEventListener("click", () => startWizard());
  } else if (k === "sem_controle") {
    b.textContent = "Abrir Hardware";
    b.addEventListener("click", () => showTab("devices"));
  } else return;
  el.appendChild(b);
}

async function reconectar(btn) {
  if (btn) btn.classList.add("busy");
  setStatus("busy", "reconectando…");
  try { await API.post("/api/reconnect"); } catch (e) { toast(e.message, true); }
  if (btn) btn.classList.remove("busy");
  refreshState();
}

function settingsNeedsRedraw(a, b) {
  if (!a) return true;
  const k = (s) => JSON.stringify([s.connected, s.connecting, s.reconnects,
                                   s.last_error, s.exclusive_mode,
                                   s.autostart_openrgb, s.protocol]);
  return k(a) !== k(b);
}

function setStatus(kind, text) {
  const d = $("#statusDot");
  d.classList.toggle("ok", kind === "ok");
  d.classList.toggle("err", kind === "err");
  d.classList.toggle("busy", kind === "busy");
  const t = text ||
    (kind === "ok" ? "conectado" : kind === "busy" ? "conectando…" : "desconectado");
  $("#statusText").textContent = t;
  // a barra corta o texto longo; o inteiro fica ao passar o mouse
  $("#status").title = `${t}. Clique para abrir a aba Hardware.`;
}

function blendLabel(v) {
  const b = ((S.catalog && S.catalog.blends) || []).find((x) => x.value === v);
  return b ? b.label : v;
}

const ICON_EYE = `<svg viewBox="0 0 24 24" class="ic"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>`;
const ICON_EYE_OFF = `<svg viewBox="0 0 24 24" class="ic"><path d="M3 3l18 18M10.6 5.2A9.9 9.9 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.3 6.4A17 17 0 0 0 2 12s3.6 7 10 7c1.6 0 3-.4 4.2-1"/></svg>`;
const ICON_GRIP = `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>`;
const ICON_X = `<svg viewBox="0 0 24 24" class="ic"><path d="M18 6L6 18M6 6l12 12"/></svg>`;
const ICON_COPY = `<svg viewBox="0 0 24 24" class="ic"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>`;
const ICON_STAR = `<svg viewBox="0 0 24 24" class="ic"><path d="M12 3l2.5 5.6 6.1.5-4.6 4 1.4 6-5.4-3.2L6.6 19l1.4-6-4.6-4 6.1-.5z"/></svg>`;

function effectDef(id) {
  if (!S.catalog) return null;
  for (const g of S.catalog.effects) {
    const f = g.effects.find((e) => e.id === id);
    if (f) return f;
  }
  return null;
}

/* -------------------------------------------------------------- camadas */

let layersSig = null;
function renderLayers(force) {
  const ul = $("#layerList");
  const layers = (S.state && S.state.layers) || [];
  // remontar a lista durante o arrasto cancelaria o proprio arrasto
  if (dragId) return;
  const sig = JSON.stringify([S.selected, layers.map(
    (l) => [l.id, l.name, l.effect, l.blend, l.opacity, l.enabled, l.targets])]);
  if (!force && sig === layersSig) return;
  layersSig = sig;
  ul.innerHTML = "";
  [...layers].reverse().forEach((L) => {
    const d = effectDef(L.effect);
    const li = document.createElement("li");
    li.className = "layer" + (L.id === S.selected ? " selected" : "") + (L.enabled ? "" : " off");
    li.draggable = true;
    li.dataset.id = L.id;
    const scope = L.targets && L.targets.length ? `${L.targets.length} alvo(s)` : "tudo";
    li.innerHTML =
      `<span class="grip" title="Arraste para reordenar">${ICON_GRIP}</span>` +
      `<div class="layer-body">` +
      `<div class="layer-name">${esc(L.name || (d ? d.label : L.effect))}</div>` +
      `<div class="layer-sub">${esc(d ? d.label : L.effect)} · ${esc(blendLabel(L.blend))} · ${Math.round(L.opacity * 100)}% · ${scope}</div>` +
      `</div>` +
      `<button class="dup" title="Duplicar">${ICON_COPY}</button>` +
      `<button class="eye" title="${L.enabled ? "Desligar" : "Ligar"}">${L.enabled ? ICON_EYE : ICON_EYE_OFF}</button>` +
      `<button class="del" title="Remover">${ICON_X}</button>`;

    li.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      S.selected = L.id;
      renderLayers();
      renderParams();
    });
    li.querySelector(".eye").addEventListener("click", async (e) => {
      e.stopPropagation();
      await API.post("/api/layer/update", { id: L.id, patch: { enabled: !L.enabled } });
      refreshState();
    });
    li.querySelector(".dup").addEventListener("click", async (e) => {
      e.stopPropagation();
      await duplicateLayer(L);
    });
    li.querySelector(".del").addEventListener("click", async (e) => {
      e.stopPropagation();
      // A pilha inteira, e nao so a camada: recriada sozinha ela voltava no
      // topo, ligada e com id novo, e como a mistura e de baixo para cima a
      // cena restaurada saia diferente da original.
      const antes = snapshotScene();
      await API.post("/api/layer/remove", { id: L.id });
      if (S.selected === L.id) { S.selected = null; renderParams(); }
      await refreshState();
      toast(`Camada "${L.name || L.effect}" removida`, false, {
        label: "Desfazer",
        run: async () => {
          try {
            await API.post("/api/layers", { layers: antes.layers });
            S.selected = L.id;
            await refreshState();
            renderParams();
          } catch (err) { toast(err.message, true); }
        },
      });
    });
    attachDrag(li);
    ul.appendChild(li);
  });

  if (!layers.length) {
    ul.innerHTML = `<li class="muted center" style="padding:18px 0">Nenhuma camada. Adicione uma.</li>`;
  }
  if (S.selected && !layers.find((l) => l.id === S.selected)) {
    S.selected = null;
    renderParams();
  }
}

async function duplicateLayer(L) {
  // logo acima da original: no topo, a copia de uma camada de fundo cobria
  // todas as outras e a cena mudava inteira
  const nova = await API.post("/api/layer/add", {
    effect: L.effect, params: L.params, blend: L.blend, opacity: L.opacity,
    targets: L.targets, name: (L.name || L.effect) + " (copia)", acima_de: L.id });
  S.selected = nova.id;
  await refreshState();
  renderParams();
  toast("Camada duplicada");
}

let dragId = null;
function attachDrag(li) {
  li.addEventListener("dragstart", (e) => {
    dragId = li.dataset.id;
    li.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", dragId); } catch (err) {}
  });
  li.addEventListener("dragend", () => {
    dragId = null;
    li.classList.remove("dragging");
    $$(".layer").forEach((x) => x.classList.remove("drop-target"));
  });
  li.addEventListener("dragover", (e) => {
    e.preventDefault();
    li.classList.add("drop-target");
  });
  li.addEventListener("dragleave", () => li.classList.remove("drop-target"));
  li.addEventListener("drop", async (e) => {
    e.preventDefault();
    li.classList.remove("drop-target");
    if (!dragId || dragId === li.dataset.id) return;
    const visual = $$("#layerList .layer").map((x) => x.dataset.id);
    const from = visual.indexOf(dragId);
    const target = visual.indexOf(li.dataset.id);
    if (from < 0 || target < 0) return;
    visual.splice(from, 1);
    // o indice do alvo anda um para tras quando o item saiu de cima dele
    visual.splice(target > from ? target - 1 : target, 0, dragId);
    dragId = null;
    await API.post("/api/layer/reorder", { order: visual.slice().reverse() });
    layersSig = null;
    refreshState();
  });
}

function currentLayer() {
  return ((S.state && S.state.layers) || []).find((l) => l.id === S.selected) || null;
}

async function patchLayer(patch) {
  const L = currentLayer();
  if (!L) return;
  Object.assign(L, patch.params ? { params: { ...L.params, ...patch.params } } : patch);
  await API.post("/api/layer/update", { id: L.id, patch });
}

const patchLayerSoon = throttle((patch) => patchLayer(patch), 40);

/* ----------------------------------------------------------- parametros */

function renderParams() {
  const body = $("#paramsBody");
  const L = currentLayer();
  $("#paramsActions").hidden = !L;
  if (!L) {
    $("#paramsTitle").textContent = "Parametros";
    body.innerHTML = `<p class="muted center">Selecione uma camada.</p>`;
    return;
  }
  const d = effectDef(L.effect);
  $("#paramsTitle").textContent = d ? d.label : L.effect;
  body.innerHTML = "";

  if (d && d.description) {
    const p = document.createElement("p");
    p.className = "hint";
    p.style.margin = "0 0 12px";
    p.textContent = d.description;
    body.appendChild(p);
  }
  if (d && d.needs && d.needs.length) {
    // o aviso do servidor diz o motivo, inclusive a falta de temperatura com
    // a fonte de sensores no ar, que antes passava calada
    const aviso = avisoDaCamada(L);
    const miss = d.needs.filter((n) => !sourceRunning(n));
    if (aviso || miss.length) {
      const w = document.createElement("p");
      w.className = "src-err";
      w.style.margin = "0 0 12px";
      w.textContent = aviso
        ? `${aviso[0].toUpperCase()}${aviso.slice(1)}. O efeito fica parado; veja a aba Fontes.`
        : `Precisa de ${miss.map(needLabel).join(" + ")}: sem essa fonte ` +
          `no ar o efeito fica parado. Veja a aba Fontes.`;
      body.appendChild(w);
    }
  }

  body.appendChild(field("Nome", inputText(L.name || "", (v) => patchLayer({ name: v }))));
  body.appendChild(
    field("Mistura", selectEl(S.catalog.blends, L.blend, (v) => { patchLayer({ blend: v }); renderLayers(); }))
  );
  body.appendChild(
    sliderField("Opacidade", L.opacity, 0, 1, 0.01,
      (v) => { patchLayerSoon({ opacity: v }); },
      (v) => Math.round(v * 100) + "%")
  );

  const tw = document.createElement("div");
  tw.className = "field";
  const lab = document.createElement("label");
  lab.innerHTML = `Aplicar em <span class="val"></span>`;
  const valEl = lab.querySelector(".val");
  const setVal = () => {
    valEl.textContent = L.targets.length ? L.targets.length + " selecionado(s)" : "tudo";
  };
  setVal();
  tw.appendChild(lab);
  const tg = document.createElement("div");
  tg.className = "targets";
  const toggleTarget = (tag, btn) => {
    const t = new Set(L.targets);
    t.has(tag) ? t.delete(tag) : t.add(tag);
    patchLayer({ targets: [...t] });
    btn.classList.toggle("on", t.has(tag));
    setVal();
    renderLayers();
  };
  for (const dev of ((S.state.canvas && S.state.canvas.devices) || [])) {
    const b = chipToggle(dev.name, L.targets.includes(dev.key));
    b.addEventListener("click", () => toggleTarget(dev.key, b));
    tg.appendChild(b);
  }
  for (const z of S.zones) {
    const tag = `${z.device_key}:${z.zone_index}`;
    const b = chipToggle(z.zone_name, L.targets.includes(tag));
    b.addEventListener("click", () => toggleTarget(tag, b));
    tg.appendChild(b);
  }
  tw.appendChild(tg);
  body.appendChild(tw);

  if (!d) return;
  const sep = document.createElement("div");
  sep.style.cssText = "height:1px;background:var(--line);margin:14px 0";
  body.appendChild(sep);

  for (const q of d.params) {
    const el = paramControl(q, L, (v) => patchLayerSoon({ params: { [q.name]: v } }));
    if (el) body.appendChild(el);
  }
}

/** Monta o controle de um parametro do efeito, no tipo declarado por ele.
 *  Em `compact` a paleta vira uma lista, que cabe na coluna estreita do
 *  painel lateral sem virar uma grade de 26 itens. */
function paramControl(q, L, set, compact) {
  const val = L.params[q.name] !== undefined ? L.params[q.name] : q.default;
  if (q.type === "float" || q.type === "int") {
    const fmt = (v) => (q.type === "int" ? String(Math.round(v)) : (+v).toFixed(2)) +
                       (q.unit ? " " + q.unit : "");
    return sliderField(q.label, val, q.min, q.max, q.step,
      (v) => set(q.type === "int" ? Math.round(v) : v), fmt);
  }
  if (q.type === "color") return field(q.label, inputColor(val, set));
  // copia: sem cores proprias a camada usa a lista do catalogo, e editar
  // ali mudava o padrao do efeito para todas as camadas e para o Restaurar
  if (q.type === "colors") return field(q.label, colorList([...(val || [])], set));
  if (q.type === "bool") return switchEl(q.label, val, set);
  if (q.type === "select") return field(q.label, selectEl(q.options, val, set));
  if (q.type === "palette")
    return field(q.label, compact ? paletteSelect(val, set) : paletteGrid(val, set));
  return null;
}

function field(label, control) {
  const w = document.createElement("div");
  w.className = "field";
  const l = document.createElement("label");
  l.textContent = label;
  w.appendChild(l);
  w.appendChild(control);
  return w;
}

function sliderField(label, value, min, max, step, onChange, fmt) {
  const w = document.createElement("div");
  w.className = "field";
  const l = document.createElement("label");
  const val = document.createElement("span");
  val.className = "val";
  val.textContent = fmt ? fmt(value) : value;
  l.append(document.createTextNode(label), val);
  const inp = document.createElement("input");
  inp.type = "range";
  inp.min = min; inp.max = max; inp.step = step; inp.value = value;
  inp.addEventListener("input", () => {
    const v = parseFloat(inp.value);
    val.textContent = fmt ? fmt(v) : v;
    onChange(v);
  });
  w.append(l, inp);
  return w;
}

function inputText(value, onChange) {
  const i = document.createElement("input");
  i.type = "text";
  i.value = value;
  i.addEventListener("change", () => onChange(i.value));
  return i;
}

function inputColor(value, onChange) {
  const i = document.createElement("input");
  i.type = "color";
  i.value = value;
  i.addEventListener("input", () => onChange(i.value));
  return i;
}

function colorList(values, onChange) {
  const wrap = document.createElement("div");
  wrap.className = "color-row";
  const rebuild = () => {
    wrap.innerHTML = "";
    values.forEach((c, i) => {
      const inp = document.createElement("input");
      inp.type = "color";
      inp.value = c;
      inp.addEventListener("input", () => { values[i] = inp.value; onChange([...values]); });
      inp.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        if (values.length > 1) { values.splice(i, 1); onChange([...values]); rebuild(); }
      });
      inp.title = "Botao direito remove";
      wrap.appendChild(inp);
    });
    const add = document.createElement("button");
    add.className = "mini";
    add.textContent = "+";
    add.title = "Adicionar cor";
    add.addEventListener("click", () => { values.push("#ffffff"); onChange([...values]); rebuild(); });
    wrap.appendChild(add);
  };
  rebuild();
  return wrap;
}

function switchEl(label, value, onChange) {
  const w = document.createElement("div");
  w.className = "field";
  const lab = document.createElement("label");
  lab.className = "switch";
  lab.style.cssText = "margin:0";
  const inp = document.createElement("input");
  inp.type = "checkbox";
  inp.checked = !!value;
  const tr = document.createElement("span");
  tr.className = "track";
  const txt = document.createElement("span");
  txt.textContent = label;
  inp.addEventListener("change", () => onChange(inp.checked));
  lab.append(inp, tr, txt);
  w.appendChild(lab);
  return w;
}

function selectEl(options, value, onChange) {
  const s = document.createElement("select");
  for (const o of options) {
    const op = document.createElement("option");
    op.value = o.value;
    op.textContent = o.label;
    if (o.value === value) op.selected = true;
    s.appendChild(op);
  }
  s.addEventListener("change", () => onChange(s.value));
  return s;
}

function paletteGrid(value, onChange) {
  const g = document.createElement("div");
  g.className = "palette-grid";
  for (const p of S.catalog.palettes) {
    const b = document.createElement("button");
    b.className = "pal" + (p.name === value ? " sel" : "");
    b.innerHTML = `<div class="bar" style="background:linear-gradient(90deg,${p.colors.join(",")})"></div>` +
      `<span class="nm">${esc(p.label || p.name)}</span>`;
    b.addEventListener("click", () => {
      onChange(p.name);
      $$(".pal", g).forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    });
    g.appendChild(b);
  }
  return g;
}

/** A paleta em lista compacta, com a faixa de cores ao lado: so o nome, sem
 *  cor nenhuma, fazia a escolha virar tentativa e erro. */
function paletteSelect(value, onChange) {
  const wrap = document.createElement("div");
  wrap.className = "pal-select";
  const bar = document.createElement("span");
  bar.className = "bar";
  const pinta = (nome) => {
    const p = S.catalog.palettes.find((x) => x.name === nome);
    bar.style.background = p ? `linear-gradient(90deg,${p.colors.join(",")})` : "var(--bg-2)";
  };
  const opts = S.catalog.palettes.map((p) => ({ value: p.name, label: p.label || p.name }));
  wrap.append(bar, selectEl(opts, value, (v) => { pinta(v); onChange(v); }));
  pinta(value);
  return wrap;
}

function chipToggle(label, on) {
  const b = document.createElement("button");
  b.className = "target-chip" + (on ? " on" : "");
  b.textContent = label;
  return b;
}

$("#btnDupLayer").addEventListener("click", () => {
  const L = currentLayer();
  if (L) duplicateLayer(L);
});

$("#btnResetParams").addEventListener("click", async () => {
  const L = currentLayer();
  const d = L && effectDef(L.effect);
  if (!d) return;
  const antes = { ...L.params };
  const padroes = {};
  for (const q of d.params)
    padroes[q.name] = Array.isArray(q.default) ? [...q.default] : q.default;
  await API.post("/api/layer/update", { id: L.id, patch: { params: padroes } });
  await refreshState();
  renderParams();
  toast("Parametros de volta ao padrao", false, {
    label: "Desfazer",
    run: async () => {
      await API.post("/api/layer/update", { id: L.id, patch: { params: antes } });
      await refreshState();
      renderParams();
    },
  });
});

/* ------------------------------------------------- seletor de efeitos */

function openEffectPicker(target) {
  S.effectPickTarget = target;
  $("#effectSearch").value = "";
  buildEffectGrid("");
  $("#effectModal").hidden = false;
  $("#effectSearch").focus();
}

function buildEffectGrid(q) {
  const box = $("#effectGrid");
  box.innerHTML = "";
  const needle = semAcento(q).trim();
  let first = null;
  for (const g of S.catalog.effects) {
    const items = g.effects.filter(
      (e) => !needle || semAcento(e.label).includes(needle) ||
             semAcento(e.description).includes(needle) ||
             semAcento(g.category).includes(needle));
    if (!items.length) continue;
    const t = document.createElement("div");
    t.className = "cat-title";
    t.innerHTML = `${esc(g.category)}<span class="n">${items.length}</span>`;
    box.appendChild(t);
    const grid = document.createElement("div");
    grid.className = "fx-grid";
    for (const e of items) {
      const b = document.createElement("button");
      b.className = "fx";
      const need = e.needs.length
        ? `<span class="need">precisa de ${e.needs.map(needLabel).join(" + ")}</span>` : "";
      b.innerHTML = `<div class="t">${esc(e.label)}</div><div class="d">${esc(e.description)}</div>${need}`;
      b.addEventListener("click", () => pickEffect(e.id));
      if (!first) { first = b; if (needle) b.classList.add("kb"); }
      grid.appendChild(b);
    }
    box.appendChild(grid);
  }
  if (!box.children.length) {
    box.innerHTML = `<p class="muted center" style="padding:26px">Nada encontrado.</p>`;
  }
}

async function pickEffect(id) {
  $("#effectModal").hidden = true;
  try {
    if (S.effectPickTarget === "new") {
      const L = await API.post("/api/layer/add", { effect: id });
      S.selected = L.id;
      await refreshState();
      renderParams();
      return;
    }
    // trocar o efeito zera os parametros: o desfazer devolve os de antes
    const alvo = S.effectPickTarget;
    const L = ((S.state && S.state.layers) || []).find((l) => l.id === alvo);
    const antes = L ? { effect: L.effect, params: { ...L.params }, name: L.name } : null;
    await API.post("/api/layer/update", { id: alvo, patch: { effect: id } });
    await refreshState();
    renderParams();
    const d = effectDef(id);
    toast(`Efeito trocado para ${d ? d.label : id}`, false, antes && {
      label: "Desfazer",
      run: async () => {
        try {
          await API.post("/api/layer/update", { id: alvo, patch: antes });
          await refreshState();
          renderParams();
        } catch (e) { toast(e.message, true); }
      },
    });
  } catch (e) {
    toast(e.message, true);
  }
}

$("#presetSearch").addEventListener("input", (e) => renderPresets(e.target.value));
$("#btnAddLayer").addEventListener("click", () => openEffectPicker("new"));
$("#btnChangeEffect").addEventListener("click", () => S.selected && openEffectPicker(S.selected));
$("#btnCloseModal").addEventListener("click", () => ($("#effectModal").hidden = true));
$("#effectSearch").addEventListener("input", (e) => buildEffectGrid(e.target.value));
$("#effectSearch").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const first = $("#effectGrid .fx");
  if (first) first.click();
});
$("#effectModal").addEventListener("click", (e) => {
  if (e.target.id === "effectModal") $("#effectModal").hidden = true;
});

/* --------------------------------------------------------------- layout */

let drag = null;

function drawLayout() {
  const { w, h, dpr } = fitCanvas(lc);
  lctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  lctx.fillStyle = "#05070a";
  lctx.fillRect(0, 0, w, h);

  const [gx0, gy0] = project(0, 0, w, h);
  const [gx1, gy1] = project(1, 1, w, h);
  lctx.strokeStyle = "rgba(255,255,255,.045)";
  lctx.lineWidth = 1;
  for (let i = 1; i < 8; i++) {
    const x = gx0 + (i / 8) * (gx1 - gx0), y = gy0 + (i / 8) * (gy1 - gy0);
    lctx.beginPath(); lctx.moveTo(x, gy0); lctx.lineTo(x, gy1); lctx.stroke();
    lctx.beginPath(); lctx.moveTo(gx0, y); lctx.lineTo(gx1, y); lctx.stroke();
  }
  lctx.strokeStyle = "rgba(255,255,255,.09)";
  lctx.strokeRect(gx0, gy0, gx1 - gx0, gy1 - gy0);

  const live = S.liveLayout && S.hex;
  const rotulos = [];
  for (const z of S.zones) {
    const sel = S.selZone && S.selZone.device_key === z.device_key &&
                S.selZone.zone_index === z.zone_index;
    const pts = S.positions.slice(z.start, z.start + z.count).map((p) => project(p[0], p[1], w, h));
    if (!pts.length) continue;

    if (pts.length > 1) {
      lctx.strokeStyle = sel ? "rgba(0,217,255,.75)" : "rgba(255,255,255,.16)";
      lctx.lineWidth = sel ? 2 : 1;
      // um traco por peca: numa zona com tres fans, a linha unica ligava o
      // ultimo LED de um fan ao primeiro do seguinte, e os aneis nao fechavam
      for (const seg of segmentosDaZona(z.geometry || {}, pts.length)) {
        const parte = pts.slice(seg.ini, seg.ini + seg.n);
        if (parte.length < 2) continue;
        lctx.beginPath();
        parte.forEach((p, i) => (i ? lctx.lineTo(p[0], p[1]) : lctx.moveTo(p[0], p[1])));
        if (seg.fecha) lctx.closePath();
        lctx.stroke();
      }
    }
    pts.forEach((p, i) => {
      lctx.fillStyle = live ? ledColor(z.start + i) : (sel ? "#00d9ff" : "#57647a");
      lctx.beginPath();
      lctx.arc(p[0], p[1], sel ? 4 : 3, 0, 6.284);
      lctx.fill();
      if (sel) {
        lctx.strokeStyle = "rgba(0,217,255,.9)";
        lctx.lineWidth = 1;
        lctx.stroke();
      }
    });

    const c = zoneCentroid(z, w, h);
    rotulos.push({ txt: z.zone_name, x: c[0], y: c[1] - 12, sel });

    if (sel) {
      for (const hd of handlesFor(z, w, h)) {
        lctx.fillStyle = "#ff2d75";
        lctx.beginPath();
        lctx.arc(hd.x, hd.y, 6, 0, 6.284);
        lctx.fill();
        lctx.strokeStyle = "#0b0f16";
        lctx.lineWidth = 2;
        lctx.stroke();
      }
    }
  }

  lctx.font = "600 11px 'Segoe UI',sans-serif";
  lctx.textAlign = "center";
  for (const r of afastaRotulos(lctx, rotulos)) {
    lctx.fillStyle = r.sel ? "#00d9ff" : "rgba(200,210,225,.55)";
    lctx.fillText(r.txt, r.x, r.y);
  }
}

/** Trechos da zona que formam uma peca so, na ordem dos LEDs. */
function segmentosDaZona(g, n) {
  const anelFechado = (p) => p.shape === "ring" &&
    Math.abs((p.end_deg ?? 360) - (p.start_deg ?? 0)) >= 359;
  if (g.shape !== "multi") return [{ ini: 0, n, fecha: anelFechado(g) }];
  const out = [];
  let usado = 0;
  for (const p of (g.parts || [])) {
    const c = Math.min(parseInt(p.count, 10) || 0, n - usado);
    if (c <= 0) continue;
    out.push({ ini: usado, n: c, fecha: anelFechado(p) });
    usado += c;
    if (usado >= n) break;
  }
  if (usado < n) out.push({ ini: usado, n: n - usado, fecha: false });
  // com a ordem invertida a zona inteira vem de tras para frente
  if (g.reverse) for (const s of out) s.ini = n - s.ini - s.n;
  return out;
}

function renderZoneChips() {
  const box = $("#zoneChips");
  if (!box) return;
  box.innerHTML = "";
  if (!S.zones.length) {
    box.innerHTML = `<span class="muted" style="font-size:11.5px">Nenhuma zona ativa.</span>`;
    return;
  }
  for (const z of S.zones) {
    const on = S.selZone && S.selZone.device_key === z.device_key &&
               S.selZone.zone_index === z.zone_index;
    const b = document.createElement("button");
    b.className = "chip" + (on ? " on" : "");
    b.innerHTML = `<span class="dot"></span>${esc(z.zone_name)}<span class="n">${z.count}</span>`;
    b.addEventListener("click", () => {
      S.selZone = { device_key: z.device_key, zone_index: z.zone_index };
      renderZoneChips();
      renderZoneEditor();
      drawLayout();
    });
    box.appendChild(b);
  }
}

function handlesFor(z, w, h) {
  const g = z.geometry || {};
  const out = [];
  if (g.shape === "line" || g.shape === "cable") {
    out.push({ id: "p1", ...pxy(g.x1, g.y1, w, h) });
    out.push({ id: "p2", ...pxy(g.x2, g.y2, w, h) });
  } else if (g.shape === "ring") {
    out.push({ id: "c", ...pxy(g.cx, g.cy, w, h) });
    out.push({ id: "r", ...pxy(g.cx + g.radius, g.cy, w, h) });
  } else if (g.shape === "grid" || g.shape === "serpentine") {
    out.push({ id: "o", ...pxy(g.x, g.y, w, h) });
    out.push({ id: "s", ...pxy(g.x + g.w, g.y + g.h, w, h) });
  } else if (g.shape === "multi") {
    return out;
  } else {
    out.push({ id: "c", ...pxy(g.x, g.y, w, h) });
  }
  return out;
}

function pxy(x, y, w, h) {
  const [a, b] = project(x, y, w, h);
  return { x: a, y: b };
}

function unproject(px, py, w, h) {
  const { s, ox, oy } = escala(w, h);
  return [clamp((px - ox) / s, -0.2, 1.2), clamp((py - oy) / s, -0.2, 1.2)];
}

lc.addEventListener("pointerdown", (e) => {
  const r = lc.getBoundingClientRect();
  const w = r.width, h = r.height;
  const mx = e.clientX - r.left, my = e.clientY - r.top;

  if (S.selZone) {
    const z = zoneByKey(S.selZone);
    if (z) {
      for (const hd of handlesFor(z, w, h)) {
        if (Math.hypot(hd.x - mx, hd.y - my) < 11) {
          drag = { mode: "handle", handle: hd.id, zone: z, w, h };
          lc.setPointerCapture(e.pointerId);
          return;
        }
      }
    }
  }

  let best = null, bestD = 18;
  for (const z of S.zones) {
    for (let i = z.start; i < z.start + z.count; i++) {
      const [x, y] = project(S.positions[i][0], S.positions[i][1], w, h);
      const d = Math.hypot(x - mx, y - my);
      if (d < bestD) { bestD = d; best = z; }
    }
  }
  if (best) {
    S.selZone = { device_key: best.device_key, zone_index: best.zone_index };
    renderZoneEditor();
    renderZoneChips();
    const c = zoneCentroid(best, w, h);
    drag = { mode: "move", zone: best, w, h, ox: mx - c[0], oy: my - c[1] };
    lc.setPointerCapture(e.pointerId);
  } else {
    S.selZone = null;
    renderZoneEditor();
    renderZoneChips();
  }
  drawLayout();
});

lc.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const r = lc.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const { w, h, zone } = drag;
  const g = { ...(zone.geometry || {}) };
  const [ux, uy] = unproject(mx, my, w, h);

  if (drag.mode === "move") {
    const [cx, cy] = unproject(mx - drag.ox, my - drag.oy, w, h);
    const cur = geomCenter(g);
    shiftGeom(g, cx - cur[0], cy - cur[1]);
  } else if (drag.handle === "p1") { g.x1 = ux; g.y1 = uy; }
  else if (drag.handle === "p2") { g.x2 = ux; g.y2 = uy; }
  else if (drag.handle === "c") { if (g.shape === "ring") { g.cx = ux; g.cy = uy; } else { g.x = ux; g.y = uy; } }
  else if (drag.handle === "r") { g.radius = Math.max(0.02, Math.hypot(ux - g.cx, uy - g.cy)); }
  else if (drag.handle === "o") { g.x = ux; g.y = uy; }
  else if (drag.handle === "s") { g.w = Math.max(0.02, ux - g.x); g.h = Math.max(0.02, uy - g.y); }

  zone.geometry = g;
  applyGeomLocal(zone, g);
  drawLayout();
});

lc.addEventListener("pointerup", async (e) => {
  if (!drag) return;
  const z = drag.zone;
  drag = null;
  try { lc.releasePointerCapture(e.pointerId); } catch (err) {}
  await saveZoneGeometry(z);
});

function zoneByKey(k) {
  return S.zones.find((z) => z.device_key === k.device_key && z.zone_index === k.zone_index);
}

function geomCenter(g) {
  if (g.shape === "line" || g.shape === "cable")
    return [(g.x1 + g.x2) / 2, (g.y1 + g.y2) / 2];
  if (g.shape === "ring") return [g.cx, g.cy];
  if (g.shape === "grid" || g.shape === "serpentine") return [g.x + g.w / 2, g.y + g.h / 2];
  if (g.shape === "multi") {
    const parts = g.parts || [];
    if (!parts.length) return [0.5, 0.5];
    const cs = parts.map(geomCenter);
    return [cs.reduce((a, c) => a + c[0], 0) / cs.length,
            cs.reduce((a, c) => a + c[1], 0) / cs.length];
  }
  return [g.x ?? 0.5, g.y ?? 0.5];
}

function shiftGeom(g, dx, dy) {
  if (g.shape === "line" || g.shape === "cable") {
    g.x1 += dx; g.y1 += dy; g.x2 += dx; g.y2 += dy;
  } else if (g.shape === "ring") { g.cx += dx; g.cy += dy; }
  else if (g.shape === "multi") {
    g.parts = (g.parts || []).map((p) => { const q = { ...p }; shiftGeom(q, dx, dy); return q; });
  } else { g.x = (g.x ?? 0.5) + dx; g.y = (g.y ?? 0.5) + dy; }
}

/** Recalcula as posicoes da zona no navegador, para o arrasto responder na
 *  hora sem esperar a volta do servidor. */
function applyGeomLocal(z, g) {
  const n = z.count;
  const out = geomPoints(g, n);
  if (g.reverse) out.reverse();
  for (let i = 0; i < n; i++) S.positions[z.start + i] = out[i] || [0.5, 0.5];
}

function geomPoints(g, n) {
  const out = [];
  if (g.shape === "multi") {
    let used = 0;
    for (const p of (g.parts || [])) {
      const c = Math.min(parseInt(p.count, 10) || 0, n - used);
      if (c <= 0) continue;
      const pts = geomPoints(p, c);
      if (p.reverse) pts.reverse();
      out.push(...pts);
      used += c;
      if (used >= n) break;
    }
    while (out.length < n) out.push([0.5, 0.98]);
    return out;
  }
  if (g.shape === "point") {
    for (let i = 0; i < n; i++) out.push([g.x, g.y]);
  } else if (g.shape === "ring") {
    const a0 = ((g.start_deg ?? 0) * Math.PI) / 180;
    const a1 = ((g.end_deg ?? 360) * Math.PI) / 180;
    const full = Math.abs(a1 - a0 - 2 * Math.PI) < 1e-6;
    for (let i = 0; i < n; i++) {
      const t = full ? i / n : i / Math.max(n - 1, 1);
      const a = a0 + (a1 - a0) * t;
      out.push([g.cx + g.radius * Math.cos(a), g.cy + g.radius * Math.sin(a)]);
    }
  } else if (g.shape === "grid" || g.shape === "serpentine") {
    const cols = g.cols || Math.max(1, Math.round(Math.sqrt(n)));
    const rows = g.rows || Math.max(1, Math.ceil(n / cols));
    for (let i = 0; i < n; i++) {
      const r = Math.floor(i / cols), c = i % cols;
      out.push([g.x + g.w * (c / Math.max(cols - 1, 1)),
                g.y + g.h * (r / Math.max(rows - 1, 1))]);
    }
  } else if (g.shape === "cable") {
    const lanes = Math.max(parseInt(g.lanes, 10) || 12, 1);
    const per = Math.max(1, Math.round(n / lanes));
    const dx = g.x2 - g.x1, dy = g.y2 - g.y1;
    const comp = Math.hypot(dx, dy) || 1;
    const px = -dy / comp, py = dx / comp;
    const wid = g.width ?? 0.16;
    for (let i = 0; i < n; i++) {
      const lane = g.order === "along" ? i % lanes : Math.min(Math.floor(i / per), lanes - 1);
      const pos = g.order === "along" ? Math.floor(i / lanes) : i % per;
      const fl = lane / Math.max(lanes - 1, 1) - 0.5;
      const fp = pos / Math.max(per - 1, 1);
      out.push([g.x1 + dx * fp + px * wid * fl, g.y1 + dy * fp + py * wid * fl]);
    }
  } else {
    for (let i = 0; i < n; i++) {
      const t = n === 1 ? 0.5 : i / (n - 1);
      out.push([g.x1 + (g.x2 - g.x1) * t, g.y1 + (g.y2 - g.y1) * t]);
    }
  }
  return out;
}

async function saveZoneGeometry(z) {
  try {
    await API.post("/api/zone/geometry", {
      device: z.device_key, zone: z.zone_index, geometry: z.geometry,
    });
  } catch (e) {
    toast(e.message, true);
  }
}

const saveZoneSoon = throttle((z) => saveZoneGeometry(z), 220);

function renderZoneEditor() {
  const box = $("#zoneEditor");
  if (!S.selZone) {
    box.innerHTML = `<p class="muted center">Clique numa zona no mapa.</p>`;
    return;
  }
  const z = zoneByKey(S.selZone);
  if (!z) { box.innerHTML = ""; return; }
  const g = z.geometry || {};
  box.innerHTML = "";

  const head = document.createElement("div");
  head.className = "zone-editor-head";
  head.innerHTML = `<span class="nm">${esc(z.zone_name)}</span>
                    <span class="cnt">${z.count} leds</span>`;
  const blink = document.createElement("button");
  blink.className = "btn sm";
  blink.textContent = "Piscar";
  blink.title = "Acende so esta zona no gabinete por 2 segundos";
  blink.addEventListener("click", () => identifyZone(z.device_key, z.zone_index, blink));
  head.appendChild(blink);
  box.appendChild(head);

  if (g.shape === "multi") {
    const p = document.createElement("p");
    p.className = "hint";
    p.style.margin = "0 0 12px";
    p.innerHTML = `Esta zona foi montada pelo assistente com
      <b>${(g.parts || []).length} pecas</b>. Arraste no mapa para mover o
      conjunto inteiro, ou refaca o assistente para mudar a divisao.`;
    box.appendChild(p);
    box.appendChild(switchEl("Inverter ordem dos LEDs", !!g.reverse, (v) => {
      z.geometry.reverse = v;
      applyGeomLocal(z, z.geometry);
      saveZoneGeometry(z);
      drawLayout();
    }));
    return;
  }

  // Sem a fita de cabo aqui, a que o assistente monta sozinha num conector
  // aparecia como Ponto, sem campo nenhum, e mexer no select perdia as
  // laminas e com elas os efeitos 2D.
  const shapes = [
    { value: "point", label: "Ponto" }, { value: "line", label: "Linha" },
    { value: "ring", label: "Anel (fan)" }, { value: "grid", label: "Grade" },
    { value: "serpentine", label: "Serpentina" },
    { value: "cable", label: "Fita de cabo (laminas)" },
  ];
  box.appendChild(field("Forma", selectEl(shapes, g.shape || "line", (v) => {
    z.geometry = defaultGeom(v, g);
    applyGeomLocal(z, z.geometry);
    saveZoneGeometry(z);
    renderZoneEditor();
    drawLayout();
  })));

  const numeric = {
    point: [["x", "X"], ["y", "Y"]],
    line: [["x1", "X inicial"], ["y1", "Y inicial"], ["x2", "X final"], ["y2", "Y final"]],
    ring: [["cx", "Centro X"], ["cy", "Centro Y"], ["radius", "Raio"],
           ["start_deg", "Angulo inicial"], ["end_deg", "Angulo final"]],
    grid: [["x", "X"], ["y", "Y"], ["w", "Largura"], ["h", "Altura"],
           ["cols", "Colunas"], ["rows", "Linhas"]],
    cable: [["x1", "X inicial"], ["y1", "Y inicial"], ["x2", "X final"], ["y2", "Y final"],
            ["width", "Largura"], ["lanes", "Laminas"]],
  };
  numeric.serpentine = numeric.grid;
  const faixa = {
    cols: [1, 64, 1], rows: [1, 64, 1], lanes: [2, 48, 1],
    width: [0.02, 0.5, 0.005], start_deg: [-360, 720, 1], end_deg: [-360, 720, 1],
  };

  for (const [k, lbl] of (numeric[g.shape] || numeric.line)) {
    const [min, max, step] = faixa[k] || [-0.5, 1.5, 0.005];
    const inteiro = step >= 1;
    const padrao = k === "lanes" ? 12 : k === "width" ? 0.14 : 0;
    box.appendChild(sliderField(lbl, g[k] ?? padrao, min, max, step, (v) => {
      z.geometry[k] = inteiro ? Math.round(v) : v;
      applyGeomLocal(z, z.geometry);
      drawLayout();
      saveZoneSoon(z);
    }, (v) => (inteiro ? Math.round(v) : (+v).toFixed(3))));
  }

  if (g.shape === "cable") {
    box.appendChild(field("Ordem dos LEDs", selectEl([
      { value: "lane", label: "Uma lamina inteira, depois a proxima" },
      { value: "along", label: "Atravessando as laminas a cada passo" },
    ], g.order || "lane", (v) => {
      z.geometry.order = v;
      applyGeomLocal(z, z.geometry);
      saveZoneGeometry(z);
      drawLayout();
    })));
  }

  box.appendChild(switchEl("Inverter ordem dos LEDs", !!g.reverse, (v) => {
    z.geometry.reverse = v;
    applyGeomLocal(z, z.geometry);
    saveZoneGeometry(z);
    drawLayout();
  }));

  const kb = document.createElement("p");
  kb.className = "kbd-hint";
  kb.innerHTML = `Use <kbd>setas</kbd> para mover a zona no mapa,
                  <kbd>Shift</kbd> + setas para passos maiores.`;
  box.appendChild(kb);
}

async function identifyZone(device, zone, btn) {
  if (btn) btn.classList.add("busy");
  try {
    const r = await API.post("/api/zone/identify", { device, zone, seconds: 2.0 });
    if (!r.ok) toast(r.error || "nao consegui acender", true);
  } catch (e) {
    toast(e.message, true);
  }
  setTimeout(() => btn && btn.classList.remove("busy"), 2000);
}

function defaultGeom(shape, old) {
  const [cx, cy] = geomCenter(old);
  if (shape === "point") return { shape, x: cx, y: cy };
  if (shape === "ring") return { shape, cx, cy, radius: 0.13, start_deg: -90, end_deg: 270 };
  if (shape === "grid" || shape === "serpentine")
    return { shape, x: cx - 0.2, y: cy - 0.1, w: 0.4, h: 0.2, cols: 0, rows: 0 };
  if (shape === "cable")
    return { shape, x1: cx - 0.25, y1: cy, x2: cx + 0.25, y2: cy, width: 0.14,
             lanes: old.lanes || 12, order: old.order || "lane" };
  return { shape: "line", x1: cx - 0.25, y1: cy, x2: cx + 0.25, y2: cy };
}

async function aposMudarMapa() {
  S.selZone = null;
  await refreshState();
  renderZoneEditor();
  renderZoneChips();
  drawLayout();
}

// Confirmacao em dois cliques, como o Excluir de perfil, e Desfazer depois:
// um clique ali, ao lado do Ao vivo, apagava o mapa que o assistente montou.
let resetArmado = null;
$("#btnResetLayout").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  if (!resetArmado) {
    b.textContent = "Apagar o mapa?";
    b.classList.add("confirm");
    resetArmado = setTimeout(() => {
      resetArmado = null;
      b.textContent = "Voltar ao automatico";
      b.classList.remove("confirm");
    }, 3500);
    return;
  }
  clearTimeout(resetArmado);
  resetArmado = null;
  b.textContent = "Voltar ao automatico";
  b.classList.remove("confirm");
  let r;
  try {
    r = await API.post("/api/layout/reset");
  } catch (err) { return toast(err.message, true); }
  await aposMudarMapa();
  const anterior = r.anterior || {};
  toast("Mapa de volta ao posicionamento automatico", false,
    Object.keys(anterior).length ? {
      label: "Desfazer",
      run: async () => {
        try {
          await API.post("/api/layout", { layout: anterior });
          await aposMudarMapa();
          toast("Mapa restaurado");
        } catch (err) { toast(err.message, true); }
      },
    } : null);
});

$("#btnLiveLayout").addEventListener("click", (e) => {
  S.liveLayout = !S.liveLayout;
  e.currentTarget.dataset.on = S.liveLayout ? "1" : "0";
  drawLayout();
});

/* -------------------------------------------------------------- hardware */

// O OpenRGB so abre o SMBus rodando como administrador, e e por ali que
// passam os pentes de memoria RGB. Sem privilegio a RAM nao aparece na
// lista e nada indica o motivo, entao o aviso precisa ser explicito.
function avisoElevacao(st) {
  const e = st.elevacao || {};
  const semPriv = e.servidor_elevado === false;
  const semDriver = e.servidor_elevado === true && !e.dram && !e.pawnio;
  if (!semPriv && !semDriver) return null;

  const el = document.createElement("div");
  el.className = "device";
  if (semDriver) {
    el.innerHTML = `
      <div class="device-head">
        <span class="nm">Memoria RAM fora da lista</span>
        <span class="tag err">driver ausente</span>
      </div>
      <p class="hint">O servidor OpenRGB esta rodando com privilegio, mas o driver
       PawnIO nao esta instalado, e sem ele o barramento SMBus fica fechado.
       Instale o PawnIO em <b>pawnio.eu</b> e reconecte.</p>`;
    return el;
  }

  el.innerHTML = `
    <div class="device-head">
      <span class="nm">Memoria RAM fora da lista</span>
      <span class="tag err">sem privilegio</span>
    </div>
    <p class="hint">O servidor OpenRGB subiu sem direitos de administrador, entao o
     barramento SMBus ficou fechado e os pentes de memoria RGB nao foram
     detectados. Corrigir cria uma tarefa agendada e reinicia o servidor
     elevado: o aviso do controle de conta aparece uma vez so.</p>`;

  const b = document.createElement("button");
  b.className = "btn sm primary";
  b.textContent = "Corrigir";
  b.addEventListener("click", async () => {
    b.classList.add("busy");
    setStatus("busy", "reiniciando o OpenRGB elevado…");
    try {
      const r = await API.post("/api/elevacao/reparar");
      toast(r.ok ? (r.aviso || "servidor elevado, RAM detectada") : r.erro, !r.ok);
    } catch (err) { toast(err.message, true); }
    b.classList.remove("busy");
    refreshState();
  });
  el.querySelector(".device-head").appendChild(b);
  return el;
}

// O teclado Akko nao vem do OpenRGB, entao nao aparece na lista normal de
// dispositivos. Sem um cartao proprio ele seria invisivel na interface,
// mesmo estando aceso na mesa.
function cartaoTeclado(st) {
  const t = st.teclado;
  if (!t) return null;

  const el = document.createElement("div");
  const solto = st.akko_keyboard === false;
  el.className = "device" + (t.connected && !solto ? "" : " disabled");
  el.innerHTML = `
    <div class="device-head">
      <span class="nm">${esc(t.name)}</span>
      <span class="tag">Teclado</span>
      ${solto ? `<span class="tag">fora do controle</span>`
        : t.connected ? `<span class="tag ok">HID direto</span>`
        : `<span class="tag err">sem conexao</span>`}
      <span class="spacer"></span>
    </div>
    <p class="hint">Fora do OpenRGB, que nao tem driver para ele. Acompanha a
     cena ao vivo com uma cor so, pelo canal de fluxo do firmware: cor por
     tecla ele so aceita como imagem parada, porque reaplica a luz a cada
     comando e animar faria ele piscar.${t.error ? " <b>" + esc(t.error) + "</b>" : ""}</p>`;

  const sw = switchEl("Controlar pelo Spectra", st.akko_keyboard !== false,
    async (v) => {
      await API.post("/api/teclado", { enabled: v });
      refreshState();
    });
  el.querySelector(".device-head").appendChild(sw.querySelector(".switch"));
  return el;
}

let devicesSig = null;
function renderDevices(force) {
  const box = $("#deviceList");
  const info = $("#deviceInfo");
  // nao remontar por baixo de quem esta digitando a contagem de LEDs; so o
  // campo numerico conta, porque a chave de liga e desliga tambem e INPUT e
  // fica com o foco depois do clique, e o cartao nao se atualizava mais
  const foco = document.activeElement;
  if (foco && foco.tagName === "INPUT" && foco.type === "number" &&
      box.contains(foco)) return;
  const st = S.state || {};
  const devs = st.devices || [];
  // So remonta quando algo que aparece aqui mudou. O estado chega a cada
  // 1,5 s, e cada remontagem descartava o que estava sendo digitado.
  const sig = JSON.stringify([st.connecting, st.enabled_devices, st.elevacao,
    st.teclado, st.akko_keyboard, st.reconnects, st.canvas && st.canvas.led_count,
    devs.map((d) => [d.key, d.led_count, d.direct_ok, d.has_direct,
                     d.zones.map((z) => z.leds_count)])]);
  if (!force && sig === devicesSig) return;
  devicesSig = sig;
  box.innerHTML = "";
  info.innerHTML = "";

  if (!devs.length) {
    box.innerHTML = st.connecting
      ? `<p class="muted center" style="padding:24px">Procurando dispositivos…</p>`
      : `<p class="muted center" style="padding:24px">Nenhum dispositivo. Verifique se o OpenRGB esta rodando.</p>`;
    return;
  }

  const totalLeds = devs.reduce((a, d) => a + d.led_count, 0);
  const semDirect = devs.filter((d) => !d.has_direct).length;
  info.innerHTML =
    `<span><b>${devs.length}</b> dispositivos</span>` +
    `<span><b>${totalLeds}</b> LEDs no total</span>` +
    `<span><b>${st.canvas ? st.canvas.led_count : 0}</b> sob controle do Spectra</span>` +
    (st.reconnects ? `<span><b>${st.reconnects}</b> reconexoes</span>` : "") +
    (semDirect ? `<span class="err">${semDirect} sem modo Direct</span>` : "");

  // O conferir mora aqui, e nao numa faixa fixa no topo da aba Efeitos: e
  // assunto de hardware, e a faixa empurrava a vitrine para baixo todo dia.
  const resizable = st.zones_resizable || [];
  if (resizable.length) {
    const conf = document.createElement("button");
    conf.className = "btn sm";
    conf.textContent = "Conferir quantidade de LEDs";
    conf.title = "Acende o que ja foi contado em cada conector, sem contar de novo";
    conf.addEventListener("click", () => startWizard(resizable, { conferir: true }));
    info.appendChild(conf);
    box.insertAdjacentHTML("beforeend",
      `<p class="hint" style="margin:0">LED aceso numa cor que voce nao escolheu? A
       contagem daquele conector esta <b>menor</b> que o real: os LEDs alem da
       conta nunca recebem dado e ficam com a ultima cor do controlador.</p>`);
  }

  const av = avisoElevacao(st);
  if (av) box.appendChild(av);

  const tec = cartaoTeclado(st);
  if (tec) box.appendChild(tec);

  const enabled = st.enabled_devices || {};
  for (const d of devs) {
    const el = document.createElement("div");
    const on = enabled[d.key] !== false;
    el.className = "device" + (on ? "" : " disabled");
    const directTag = d.direct_ok === true
      ? `<span class="tag ok">Direct</span>`
      : d.has_direct ? `<span class="tag">Direct disponivel</span>`
      : `<span class="tag err">sem modo Direct</span>`;
    el.innerHTML = `
      <div class="device-head">
        <span class="nm">${esc(d.name)}</span>
        <span class="tag">${esc(d.type_name)}</span>
        ${directTag}
        <span class="tag">${d.led_count} leds</span>
        <span class="spacer"></span>
      </div>
      <div class="device-meta">${esc([d.vendor, d.description].filter(Boolean).join(" · "))}</div>`;

    const sw = switchEl("Controlar pelo Spectra", on, async (v) => {
      const e2 = { ...enabled, [d.key]: v };
      await API.post("/api/settings", { enabled_devices: e2 });
      refreshState();
    });
    el.querySelector(".device-head").appendChild(sw.querySelector(".switch"));

    if (!d.has_direct) {
      el.insertAdjacentHTML("beforeend",
        `<p class="hint">Este dispositivo nao anuncia modo de cor por LED, entao o
         Spectra nao consegue animar nele. E limitacao do driver do OpenRGB para
         esse hardware, nao do Spectra.</p>`);
    }

    for (const z of d.zones) {
      const row = document.createElement("div");
      row.className = "zone-row";
      row.innerHTML = `<span class="zn">${esc(z.name)}</span>
                       <span class="zt">${esc(z.type_name)} · ${z.leds_count} leds</span>`;

      const acts = document.createElement("div");
      acts.className = "resize";
      if (z.resizable) {
        const chave = `${d.key}:${z.index}`;
        const lo = Math.max(1, z.leds_min), hi = Math.min(z.leds_max, 512);
        const inp = document.createElement("input");
        inp.type = "number";
        inp.min = lo; inp.max = hi;
        const rascunho = rascunhoLeds(chave, z.leds_count);
        inp.value = rascunho !== null ? rascunho : z.leds_count;
        inp.title = "Quantos LEDs estao plugados neste conector";
        inp.addEventListener("input", () => guardaRascunhoLeds(chave, z.leds_count, inp.value));
        const b = document.createElement("button");
        b.className = "btn sm";
        b.textContent = "Aplicar";
        b.addEventListener("click", async () => {
          const n = parseInt(inp.value, 10);
          // campo vazio ia como nulo e voltava erro de Python; fora da faixa
          // passava sem conferencia
          if (!(n >= lo && n <= hi)) return toast(`${z.name}: digite de ${lo} a ${hi}`, true);
          b.classList.add("busy");
          try {
            const r = await API.post("/api/zone/resize", { device: d.key, zone: z.index, size: n });
            if (r.ok) RASCUNHO_LEDS.delete(chave);
            toast(r.ok ? `${z.name}: ${n} LEDs` : r.error, !r.ok);
          } catch (e) { toast(e.message, true); }
          b.classList.remove("busy");
          refreshState();
        });
        inp.addEventListener("keydown", (e) => { if (e.key === "Enter") b.click(); });
        const find = document.createElement("button");
        // gradiente so onde ainda falta contar; com a contagem feita, tres
        // botoes coloridos empilhados chamavam mais atencao que o resto
        find.className = z.leds_count ? "btn sm ghost" : "btn sm primary";
        find.textContent = "Descobrir";
        find.title = "Abre o assistente para achar a contagem certa";
        find.addEventListener("click", () => openProbe(d.key, z.index, z.name));
        acts.append(document.createTextNode("LEDs:"), inp, b, find);
      }
      if (z.leds_count > 0 && on && d.has_direct) {
        const blink = document.createElement("button");
        blink.className = "btn sm ghost";
        blink.textContent = "Piscar";
        blink.title = "Acende so esta zona, para saber qual peca e";
        blink.addEventListener("click", () => identifyZone(d.key, z.index, blink));
        acts.appendChild(blink);
      }
      if (acts.childNodes.length) row.appendChild(acts);
      el.appendChild(row);
    }
    box.appendChild(el);
  }

  // Quem tem uma peca que nao esta nesta lista fica sem explicacao nenhuma:
  // a ausencia nao gera erro, o hardware simplesmente nao existe para o app.
  box.insertAdjacentHTML("beforeend",
    `<p class="hint muted">Aparece aqui so o que o OpenRGB tem driver para
     controlar. Peca que nao esta na lista nao tem suporte no OpenRGB, e o
     Spectra nao alcanca ela: o app fala com o hardware exclusivamente por ele.
     Teclado e mouse de fabricante com protocolo fechado sao os casos mais
     comuns.</p>`);
}

$("#btnReconnect").addEventListener("click", (e) => reconectar(e.currentTarget));

/* --------------------------------------------------------------- fontes */

const NEED_NAMES = { audio: "audio", screen: "tela", sensors: "sensores" };
function needLabel(n) { return NEED_NAMES[n] || n; }

function sourceRunning(kind) {
  const s = (S.state && S.state.sources) || {};
  return !!(s[kind] && s[kind].running);
}

/** O motivo que o servidor da para a camada estar sem dado, ou null. */
function avisoDaCamada(L) {
  return ((S.state && S.state.avisos) || {})[L.id] || null;
}

let ultimoFontesSig = null;
function fontesSig(st) {
  const s = st.sources || {};
  return JSON.stringify([st.needed, ["audio", "screen", "sensors"].map((k) => {
    const x = s[k] || {};
    return [x.running, x.error, x.device_name, x.lhm, x.dll_present];
  })]);
}

/** Troca a configuracao de uma fonte e diz se a captura abriu de verdade.
 *  Antes o aviso era "atualizada" em todo caso, e o dispositivo que falhava
 *  so aparecia trocando de aba. */
async function aplicaFonte(kind, config, msgOk) {
  try {
    const r = await API.post("/api/source", { kind, config });
    toast(r.em_uso ? msgOk : `${msgOk}; liga quando alguma camada usar`);
  } catch (e) {
    toast(e.message, true);
  }
  await refreshState();
  renderSources();
}

async function renderSources() {
  const box = $("#sourcesBody");
  const src = (S.state && S.state.sources) || {};
  const needed = (S.state && S.state.needed) || [];
  ultimoFontesSig = fontesSig(S.state || {});
  box.innerHTML = "";

  box.appendChild(sourceCard("Audio", "audio", src.audio, needed, async (card) => {
    const d = await API.get("/api/audio-devices");
    const lista = d.devices || [];
    const opts = [{ value: "", label: "Saida padrao (automatico)" }].concat(
      lista.map((x) => ({ value: String(x.index), label: x.name })));
    const cfgA = (src.audio || {}).config || {};
    // o numero do dispositivo muda quando se pluga outro; o nome guardado e
    // o que acha o escolhido
    const peloNome = cfgA.nome ? lista.find((x) => x.name === cfgA.nome) : null;
    const cur = peloNome ? String(peloNome.index) : String(cfgA.device ?? "");
    card.appendChild(field("Dispositivo de loopback", selectEl(opts, cur, (v) => {
      const escolhido = lista.find((x) => String(x.index) === v);
      aplicaFonte("audio", { device: v === "" ? null : parseInt(v, 10),
                             nome: escolhido ? escolhido.name : null },
                  "Fonte de audio atualizada");
    })));
    if (d.error) card.insertAdjacentHTML("beforeend", `<p class="src-err">${esc(d.error)}</p>`);
    if (src.audio && src.audio.device_name)
      card.insertAdjacentHTML("beforeend", `<p class="hint">Capturando: ${esc(src.audio.device_name)}</p>`);
    card.insertAdjacentHTML("beforeend",
      `<p class="hint">Captura o que sai pela placa de som, sem microfone. Liga
       sozinha quando alguma camada usa audio.</p>`);
    const spec = document.createElement("div");
    spec.className = "spectrum idle";
    spec.id = "audioSpectrum";
    spec.innerHTML = Array.from({ length: 24 }, () => "<i></i>").join("");
    card.appendChild(spec);
  }));

  box.appendChild(sourceCard("Tela", "screen", src.screen, needed, async (card) => {
    const d = await API.get("/api/screen-outputs");
    const opts = (d.outputs || []).map((x) => ({ value: String(x.index), label: x.name }));
    if (!opts.length) opts.push({ value: "0", label: "Saida 0" });
    // Um objeto so, atualizado a cada mudanca: os dois controles espalhavam a
    // configuracao lida ao montar o cartao, e mexer na taxa depois de trocar
    // de monitor voltava a captura para o monitor antigo.
    const cfg = { output: 0, fps: 30, ...((src.screen || {}).config || {}) };
    card.appendChild(field("Monitor", selectEl(opts, String(cfg.output ?? 0), (v) => {
      cfg.output = parseInt(v, 10);
      aplicaFonte("screen", { ...cfg }, "Monitor atualizado");
    })));
    const send = throttle((v) => {
      cfg.fps = Math.round(v);
      API.post("/api/source", { kind: "screen", config: { ...cfg } })
        .catch((e) => toast(e.message, true)).then(refreshState);
    }, 400);
    card.appendChild(sliderField("Taxa de captura", cfg.fps ?? 30, 10, 60, 1, send,
      (v) => Math.round(v) + " fps"));
    if (src.screen && src.screen.fps) card.insertAdjacentHTML("beforeend",
      `<p class="hint">Capturando a ${src.screen.fps} fps</p>`);
    if (d.error) card.insertAdjacentHTML("beforeend", `<p class="src-err">${esc(d.error)}</p>`);
    const live = document.createElement("div");
    live.className = "src-live";
    live.innerHTML = `<span class="sw" id="screenSwatch"></span><span>cor media da tela</span>`;
    card.appendChild(live);
  }));

  const s = src.sensors || {};
  box.appendChild(sourceCard("Sensores", "sensors", s, needed, async (card) => {
    const rows = [
      ["CPU temp", "cpu_temp"], ["GPU temp", "gpu_temp"],
      ["CPU uso", "cpu_load"], ["GPU uso", "gpu_load"], ["RAM uso", "ram_load"],
    ];
    const avail = new Set(s.available || []);
    for (const [lbl, key] of rows) {
      const row = document.createElement("div");
      row.className = "sensor-row";
      row.innerHTML = `<span class="lb">${lbl}</span>
        <span class="meter"><i data-k="${key}"></i></span>
        <span class="vl" data-v="${key}">${avail.has(key) ? "…" : "n/d"}</span>`;
      card.appendChild(row);
    }
    updateSensorMeters();
    // Com a DLL no lugar e a fonte ainda parada nao ha o que dizer. Faltando
    // ela, vai o caminho inteiro: no app instalado a vendor/ do proprio app
    // fica escondida em _internal, e "vendor/" sozinho nao levava a lugar
    // nenhum.
    if (!s.lhm && !(s.dll_present && !s.running)) {
      card.insertAdjacentHTML("beforeend", s.dll_present === false
        ? `<p class="src-err">Temperaturas indisponiveis: falta a
           LibreHardwareMonitorLib.dll. Coloque o arquivo em
           <code>${esc(s.dll_dir || "vendor")}</code> e abra o Spectra de novo.
           Uso de CPU e RAM continua funcionando sem ela.</p>`
        : `<p class="src-err">Temperaturas indisponiveis: ${esc(s.error || "a biblioteca de sensores nao abriu")}.
           Rode o Spectra como administrador. Uso de CPU e RAM continua
           funcionando sem ela.</p>`);
    }
  }));
}

const SENSOR_MAX = { cpu_temp: 100, gpu_temp: 100, cpu_load: 100, gpu_load: 100, ram_load: 100 };
const SENSOR_UNIT = { cpu_temp: "°C", gpu_temp: "°C", cpu_load: "%", gpu_load: "%", ram_load: "%" };

function updateSensorMeters() {
  const vals = (S.state && S.state.sensor_values) || {};
  const avail = new Set(((S.state && S.state.sources && S.state.sources.sensors) || {}).available || []);
  for (const [k, max] of Object.entries(SENSOR_MAX)) {
    const bar = document.querySelector(`.meter i[data-k="${k}"]`);
    const lbl = document.querySelector(`.vl[data-v="${k}"]`);
    if (!bar || !lbl) continue;
    if (!avail.has(k)) { bar.style.width = "0%"; lbl.textContent = "n/d"; continue; }
    const v = vals[k] || 0;
    bar.style.width = clamp((v / max) * 100, 0, 100) + "%";
    lbl.textContent = v.toFixed(v < 10 ? 1 : 0) + SENSOR_UNIT[k];
  }
}

/** Desenha o espectro do audio e a cor media da tela com o que chega do
 *  stream, sem pedido extra por quadro. */
function updateLiveMeters() {
  const spec = $("#audioSpectrum");
  if (spec) {
    const bands = (S.live.audio && S.live.audio.bands) || [];
    const bars = spec.children;
    spec.classList.toggle("idle", !bands.length);
    for (let i = 0; i < bars.length; i++) {
      const v = bands[i] != null ? clamp(bands[i], 0, 1) : 0;
      bars[i].style.height = (2 + v * 40) + "px";
    }
  }
  const sw = $("#screenSwatch");
  if (sw) {
    const c = S.live.screen;
    sw.style.background = c
      ? `rgb(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)})`
      : "var(--bg-2)";
  }
}

function sourceCard(title, kind, st, needed, fill) {
  const card = document.createElement("div");
  card.className = "panel";
  const running = st && st.running;
  const wanted = needed.includes(kind);
  // pedida e parada e problema, e nao pode ter a bolinha cinza da ociosa
  card.innerHTML = `<div class="panel-head"><h2>${title}</h2></div>
    <div class="src-state"><span class="dot ${running ? "on" : wanted ? "err" : ""}"></span>
      <span>${running ? "ativa" : wanted ? "solicitada, mas parada" : "ociosa (nenhuma camada usa)"}</span></div>`;
  if (st && st.error && !running)
    card.insertAdjacentHTML("beforeend", `<p class="src-err">${esc(st.error)}</p>`);
  fill(card).catch((e) => card.insertAdjacentHTML("beforeend",
    `<p class="src-err">${esc(e.message)}</p>`));
  return card;
}

/* --------------------------------------------------------------- perfis */

function renderProfiles() {
  const ul = $("#profileList");
  const list = (S.state && S.state.profiles) || [];
  // "atual" so enquanto a cena no ar e mesmo a do perfil: depois de aplicar
  // um preset a marca seguia no perfil antigo
  const cur = S.state && S.state.perfil_atual;
  ul.innerHTML = "";
  if (!list.length) {
    ul.innerHTML = `<li class="muted" style="justify-content:center">Nenhum perfil salvo ainda.</li>`;
    return;
  }
  for (const name of list) {
    const li = document.createElement("li");
    if (name === cur) li.className = "cur-row";
    li.innerHTML = `<span class="nm">${esc(name)}</span>` +
      (name === cur ? `<span class="cur">atual</span>` : "");
    const load = document.createElement("button");
    load.className = "btn sm";
    load.textContent = "Carregar";
    load.addEventListener("click", async () => {
      // com desfazer, como o preset: um clique errado na lista trocava a cena
      // montada a mao sem volta; o brilho entra, porque o perfil traz o dele
      const antes = snapshotScene(true);
      // perfil recusado, como um arquivo corrompido, volta com ok falso e sem
      // erro: sem conferir, o aviso dizia que tinha carregado
      let r;
      try {
        r = await API.post("/api/profile/load", { name });
      } catch (e) { return toast(e.message, true); }
      if (!r.ok) return toast(`Nao consegui carregar o perfil "${name}"`, true);
      S.selected = null;
      await refreshState();
      renderParams();
      renderProfiles();
      toast(`Perfil "${name}" carregado`, false, undoAction(antes));
    });
    const del = document.createElement("button");
    del.className = "btn sm danger";
    del.textContent = "Excluir";
    let armed = false;
    del.addEventListener("click", async () => {
      if (!armed) {
        armed = true;
        del.textContent = "Confirmar";
        del.classList.add("confirm");
        setTimeout(() => {
          armed = false; del.textContent = "Excluir"; del.classList.remove("confirm");
        }, 3500);
        return;
      }
      await API.post("/api/profile/delete", { name });
      toast(`Perfil "${name}" excluido`);
      refreshState();
      renderProfiles();
    });
    li.append(load, del);
    ul.appendChild(li);
  }
}

$("#btnSaveProfile").addEventListener("click", saveProfile);
$("#profileName").addEventListener("keydown", (e) => {
  if (e.key === "Enter") saveProfile();
});
$("#profileName").addEventListener("input", desarmaSalvar);

// Nome que ja existe pede um segundo clique, no mesmo padrao do Excluir.
// A conferencia e do servidor, pelo nome ja limpo: "Jogo!" vira "Jogo", e
// comparando o texto cru a interface sobrescrevia dizendo que era novo.
let salvarArmado = null, salvarTimer = null;
function desarmaSalvar() {
  salvarArmado = null;
  clearTimeout(salvarTimer);
  const b = $("#btnSaveProfile");
  b.textContent = "Salvar cena atual";
  b.classList.remove("confirm");
}

async function saveProfile() {
  const inp = $("#profileName");
  const name = inp.value.trim();
  if (!name) return toast("Digite um nome para o perfil", true);
  const confirmado = salvarArmado === name;
  try {
    const r = await API.post("/api/profile/save", { name, sobrescrever: confirmado });
    if (r.existe) {
      desarmaSalvar();
      salvarArmado = name;
      const b = $("#btnSaveProfile");
      b.textContent = `Sobrescrever "${r.name}"?`;
      b.classList.add("confirm");
      salvarTimer = setTimeout(desarmaSalvar, 3500);
      return;
    }
    desarmaSalvar();
    if (r.ok) {
      inp.value = "";
      toast(confirmado ? `Perfil "${r.name}" sobrescrito`
        : r.name !== name ? `Perfil salvo como "${r.name}"` : `Perfil "${r.name}" salvo`);
      await refreshState();
      renderProfiles();
    } else toast(r.error, true);
  } catch (e) { desarmaSalvar(); toast(e.message, true); }
}

/* ------------------------------------------------------ controles do topo */

const sendBright = throttle((v) => API.post("/api/settings", { brightness: v / 100 }), 60);
$("#brightness").addEventListener("input", (e) => {
  const v = parseInt(e.target.value, 10);
  $("#brightVal").textContent = v + "%";
  if (v > 0) S.prevBright = v;
  $("#btnPower").classList.toggle("on", v > 0);
  $("#btnPower").classList.toggle("off", v === 0);
  sendBright(v);
});

$("#btnPower").addEventListener("click", async () => {
  const cur = parseInt($("#brightness").value, 10);
  const alvo = cur > 0 ? 0 : (S.prevBright || 100);
  $("#brightness").value = alvo;
  $("#brightVal").textContent = alvo + "%";
  $("#btnPower").classList.toggle("on", alvo > 0);
  $("#btnPower").classList.toggle("off", alvo === 0);
  await API.post("/api/settings", { brightness: alvo / 100 });
  toast(alvo === 0 ? "LEDs apagados" : `Brilho em ${alvo}%`);
});

$("#btnPause").addEventListener("click", togglePause);

async function togglePause() {
  const paused = !(S.state && S.state.settings && S.state.settings.paused);
  await API.post("/api/settings", { paused });
  toast(paused ? "Efeitos pausados, LEDs congelados" : "Efeitos retomados");
  refreshState();
}

$("#btnGlow").addEventListener("click", (e) => {
  S.glow = !S.glow;
  e.currentTarget.dataset.on = S.glow ? "1" : "0";
});
$("#btnLabels").addEventListener("click", (e) => {
  S.labels = !S.labels;
  e.currentTarget.dataset.on = S.labels ? "1" : "0";
});

/* ------------------------------------------------------ atalhos globais */

function typing(el) {
  return el && (el.tagName === "INPUT" || el.tagName === "SELECT" ||
                el.tagName === "TEXTAREA" || el.isContentEditable);
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    $("#effectModal").hidden = true;
    return;
  }
  if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key >= "1" && e.key <= "7") {
    const tabs = ["effects", "scene", "layout", "devices", "sources", "profiles", "settings"];
    showTab(tabs[+e.key - 1]);
    e.preventDefault();
    return;
  }
  if (typing(document.activeElement)) return;
  if (!$("#effectModal").hidden || !$("#probeModal").hidden) return;

  if (e.key === " ") { e.preventDefault(); togglePause(); return; }
  if (e.key === "/") {
    e.preventDefault();
    showTab("effects");
    $("#presetSearch").focus();
    return;
  }
  if (activeTab() === "layout" && S.selZone && e.key.startsWith("Arrow")) {
    const z = zoneByKey(S.selZone);
    if (!z) return;
    e.preventDefault();
    const d = e.shiftKey ? 0.02 : 0.004;
    const dx = e.key === "ArrowLeft" ? -d : e.key === "ArrowRight" ? d : 0;
    const dy = e.key === "ArrowUp" ? -d : e.key === "ArrowDown" ? d : 0;
    const g = { ...(z.geometry || {}) };
    shiftGeom(g, dx, dy);
    z.geometry = g;
    applyGeomLocal(z, g);
    drawLayout();
    saveZoneSoon(z);
  }
});

/* ------------------------------------------------------------------ boot */

async function boot() {
  try {
    S.catalog = await API.get("/api/catalog");
  } catch (e) {
    setStatus("err", "falha ao carregar o catalogo");
    return;
  }
  buildQuickBar();
  await refreshState();
  FAVS = new Set((S.state && S.state.favoritos) || []);
  await migraArmazenamentoAntigo();
  // Recarregar a pagina com o assistente aberto deixava a sessao dele no
  // servidor: render pausado e conectores expandidos para a sondagem.
  if (S.state && S.state.assistente_ativo && $("#probeModal").hidden) {
    try { await API.post("/api/probe/finish", {}); } catch (e) {}
    await refreshState();
  }
  renderPresets();
  renderSetupBanner();
  renderNowPlaying();
  renderParams();
  rafLoop();
  startStream();
  setInterval(refreshState, 1500);
  window.addEventListener("resize", throttle(redrawAll, 100));
}

boot();
