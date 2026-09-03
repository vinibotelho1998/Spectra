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
  colors: [],
  positions: [],
  zones: [],
  glow: true,
  labels: false,
  selZone: null,
  effectPickTarget: null,
};

let toastTimer = null;
function toast(msg, isErr) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", !!isErr);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isErr ? 5200 : 2400);
}

$$(".navbtn").forEach((b) =>
  b.addEventListener("click", () => {
    $$(".navbtn").forEach((x) => x.classList.remove("active"));
    $$(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#tab-" + b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "effects") { renderPresets(); renderSetupBanner(); renderNowPlaying(); }
    if (b.dataset.tab === "layout") drawLayout();
    if (b.dataset.tab === "sources") renderSources();
    if (b.dataset.tab === "devices") renderDevices();
    if (b.dataset.tab === "profiles") renderProfiles();
  })
);

const pv = $("#preview");
const pctx = pv.getContext("2d", { alpha: false });
const pv2 = $("#preview2");
const pctx2 = pv2.getContext("2d", { alpha: false });
const lc = $("#layoutCanvas");
const lctx = lc.getContext("2d");

function fitCanvas(cv) {
  const r = cv.parentElement.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  if (cv.width !== w * dpr || cv.height !== h * dpr) {
    cv.width = w * dpr;
    cv.height = h * dpr;
  }
  return { w, h, dpr };
}

const PAD = 26;
function project(x, y, w, h) {
  return [PAD + x * (w - PAD * 2), PAD + y * (h - PAD * 2)];
}

function drawPreview(cv, pctx) {
  const { w, h, dpr } = fitCanvas(cv);
  pctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  pctx.fillStyle = "#05070a";
  pctx.fillRect(0, 0, w, h);

  const pos = S.positions;
  if (!pos.length) return;
  const n = pos.length;
  const radius = clamp(Math.min(w, h) / Math.sqrt(n) / 3.4, 2.6, 11);

  if (S.glow) {
    pctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < n; i++) {
      const c = S.colors[i] || "#000000";
      if (c === "#000000") continue;
      const [px, py] = project(pos[i][0], pos[i][1], w, h);
      const g = pctx.createRadialGradient(px, py, 0, px, py, radius * 4.2);
      g.addColorStop(0, c + "88");
      g.addColorStop(0.45, c + "22");
      g.addColorStop(1, c + "00");
      pctx.fillStyle = g;
      pctx.beginPath();
      pctx.arc(px, py, radius * 4.2, 0, 6.284);
      pctx.fill();
    }
    pctx.globalCompositeOperation = "source-over";
  }

  for (let i = 0; i < n; i++) {
    const [px, py] = project(pos[i][0], pos[i][1], w, h);
    pctx.fillStyle = S.colors[i] || "#0a0d12";
    pctx.beginPath();
    pctx.arc(px, py, radius, 0, 6.284);
    pctx.fill();
    pctx.strokeStyle = "rgba(255,255,255,.10)";
    pctx.lineWidth = 1;
    pctx.stroke();
  }

  if (S.labels) {
    pctx.font = "10px 'Segoe UI', sans-serif";
    pctx.textAlign = "center";
    for (const z of S.zones) {
      const p = zoneCentroid(z, w, h);
      if (!p) continue;
      pctx.fillStyle = "rgba(0,0,0,.65)";
      const tw = pctx.measureText(z.zone_name).width + 8;
      pctx.fillRect(p[0] - tw / 2, p[1] - 22, tw, 14);
      pctx.fillStyle = "#cbd5e5";
      pctx.fillText(z.zone_name, p[0], p[1] - 12);
    }
  }
}

function zoneCentroid(z, w, h) {
  const pos = S.positions.slice(z.start, z.start + z.count);
  if (!pos.length) return null;
  let sx = 0, sy = 0;
  for (const p of pos) { sx += p[0]; sy += p[1]; }
  return project(sx / pos.length, sy / pos.length, w, h);
}

let previewBusy = false;
async function pollPreview() {
  if (previewBusy) return;
  previewBusy = true;
  try {
    const d = await API.get("/api/preview");
    S.colors = d.colors;
    $("#fpsVal").textContent = d.fps != null ? d.fps.toFixed(0) : "—";
  } catch (e) {
  } finally {
    previewBusy = false;
  }
}

function rafLoop() {
  if ($("#tab-scene").classList.contains("active")) drawPreview(pv, pctx);
  else if ($("#tab-effects").classList.contains("active")) drawPreview(pv2, pctx2);
  requestAnimationFrame(rafLoop);
}

async function refreshState() {
  let st;
  try {
    st = await API.get("/api/state");
  } catch (e) {
    setStatus(false, "servidor local fora do ar");
    return;
  }
  S.state = st;
  S.positions = (st.canvas && st.canvas.positions) || [];
  S.zones = (st.canvas && st.canvas.zones) || [];
  setStatus(st.connected, st.status);
  $("#ledVal").textContent = st.canvas ? st.canvas.led_count : "—";
  $("#canvasEmpty").hidden = !!(st.canvas && st.canvas.led_count);

  if (st.settings) {
    const b = Math.round((st.settings.brightness ?? 1) * 100);
    if (document.activeElement !== $("#brightness")) {
      $("#brightness").value = b;
      $("#brightVal").textContent = b + "%";
    }
    $("#btnPause").textContent = st.settings.paused ? "Retomar" : "Pausar";
  }
  $("#canvasEmpty2").hidden = !!(st.canvas && st.canvas.led_count);
  renderLayers();
  if ($("#tab-effects").classList.contains("active")) {
    renderSetupBanner();
    renderNowPlaying();
    markActivePreset();
  }
  if ($("#tab-devices").classList.contains("active")) renderDevices();
  if ($("#tab-sources").classList.contains("active")) updateSensorMeters();
  if ($("#tab-layout").classList.contains("active")) drawLayout();
  if (st.last_error) console.warn("render:", st.last_error);
}

function setStatus(ok, text) {
  const d = $("#statusDot");
  d.classList.toggle("ok", !!ok);
  d.classList.toggle("err", !ok);
  $("#statusText").textContent = text || (ok ? "conectado" : "desconectado");
}

const ICON_EYE = `<svg viewBox="0 0 24 24" class="ic"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>`;
const ICON_EYE_OFF = `<svg viewBox="0 0 24 24" class="ic"><path d="M3 3l18 18M10.6 5.2A9.9 9.9 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.3 6.4A17 17 0 0 0 2 12s3.6 7 10 7c1.6 0 3-.4 4.2-1"/></svg>`;
const ICON_GRIP = `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>`;
const ICON_X = `<svg viewBox="0 0 24 24" class="ic"><path d="M18 6L6 18M6 6l12 12"/></svg>`;

function effectDef(id) {
  if (!S.catalog) return null;
  for (const g of S.catalog.effects) {
    const f = g.effects.find((e) => e.id === id);
    if (f) return f;
  }
  return null;
}

function renderLayers() {
  const ul = $("#layerList");
  const layers = (S.state && S.state.layers) || [];
  ul.innerHTML = "";
  [...layers].reverse().forEach((L) => {
    const d = effectDef(L.effect);
    const li = document.createElement("li");
    li.className = "layer" + (L.id === S.selected ? " selected" : "") + (L.enabled ? "" : " off");
    li.draggable = true;
    li.dataset.id = L.id;
    const scope = L.targets && L.targets.length ? `${L.targets.length} alvo(s)` : "tudo";
    li.innerHTML =
      `<span class="grip">${ICON_GRIP}</span>` +
      `<div class="layer-body">` +
      `<div class="layer-name">${esc(L.name || (d ? d.label : L.effect))}</div>` +
      `<div class="layer-sub">${esc(d ? d.label : L.effect)} · ${esc(L.blend)} · ${Math.round(L.opacity * 100)}% · ${scope}</div>` +
      `</div>` +
      `<button class="eye" title="Ligar/desligar">${L.enabled ? ICON_EYE : ICON_EYE_OFF}</button>` +
      `<button class="del" title="Remover">${ICON_X}</button>`;

    li.addEventListener("click", (e) => {
      if (e.target.closest(".eye") || e.target.closest(".del")) return;
      S.selected = L.id;
      renderLayers();
      renderParams();
    });
    li.querySelector(".eye").addEventListener("click", async (e) => {
      e.stopPropagation();
      await API.post("/api/layer/update", { id: L.id, patch: { enabled: !L.enabled } });
      refreshState();
    });
    li.querySelector(".del").addEventListener("click", async (e) => {
      e.stopPropagation();
      await API.post("/api/layer/remove", { id: L.id });
      if (S.selected === L.id) { S.selected = null; renderParams(); }
      refreshState();
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

let dragId = null;
function attachDrag(li) {
  li.addEventListener("dragstart", (e) => {
    dragId = li.dataset.id;
    li.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  li.addEventListener("dragend", () => {
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
    const to = visual.indexOf(li.dataset.id);
    visual.splice(to, 0, visual.splice(from, 1)[0]);
    await API.post("/api/layer/reorder", { order: visual.slice().reverse() });
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

function renderParams() {
  const body = $("#paramsBody");
  const L = currentLayer();
  $("#btnChangeEffect").hidden = !L;
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

  body.appendChild(field("Nome", inputText(L.name || "", (v) => patchLayer({ name: v }))));
  body.appendChild(
    field("Mistura", selectEl(S.catalog.blends, L.blend, (v) => { patchLayer({ blend: v }); renderLayers(); }))
  );
  body.appendChild(
    sliderField("Opacidade", L.opacity, 0, 1, 0.01, (v) => { patchLayer({ opacity: v }); renderLayers(); },
      (v) => Math.round(v * 100) + "%")
  );

  const tw = document.createElement("div");
  tw.className = "field";
  tw.innerHTML = `<label>Aplicar em <span class="val">${L.targets.length ? L.targets.length + " selecionado(s)" : "tudo"}</span></label>`;
  const tg = document.createElement("div");
  tg.className = "targets";
  for (const dev of (S.state.canvas.devices || [])) {
    tg.appendChild(chipToggle(dev.name, L.targets.includes(dev.key), (on) => {
      const t = new Set(L.targets);
      on ? t.add(dev.key) : t.delete(dev.key);
      patchLayer({ targets: [...t] });
      renderParams(); renderLayers();
    }));
  }
  for (const z of S.zones) {
    const tag = `${z.device_key}:${z.zone_index}`;
    tg.appendChild(chipToggle(z.zone_name, L.targets.includes(tag), (on) => {
      const t = new Set(L.targets);
      on ? t.add(tag) : t.delete(tag);
      patchLayer({ targets: [...t] });
      renderParams(); renderLayers();
    }));
  }
  tw.appendChild(tg);
  body.appendChild(tw);

  if (!d) return;
  const sep = document.createElement("div");
  sep.style.cssText = "height:1px;background:var(--line);margin:14px 0";
  body.appendChild(sep);

  for (const q of d.params) {
    const val = L.params[q.name] !== undefined ? L.params[q.name] : q.default;
    const set = (v) => patchLayer({ params: { [q.name]: v } });
    let el;
    if (q.type === "float" || q.type === "int") {
      const fmt = (v) => (q.type === "int" ? String(Math.round(v)) : (+v).toFixed(2)) + (q.unit ? " " + q.unit : "");
      el = sliderField(q.label, val, q.min, q.max, q.step, (v) => set(q.type === "int" ? Math.round(v) : v), fmt);
    } else if (q.type === "color") {
      el = field(q.label, inputColor(val, set));
    } else if (q.type === "colors") {
      el = field(q.label, colorList(val, set));
    } else if (q.type === "bool") {
      el = switchEl(q.label, val, set);
    } else if (q.type === "select") {
      el = field(q.label, selectEl(q.options, val, set));
    } else if (q.type === "palette") {
      el = field(q.label, paletteGrid(val, set));
    }
    if (el) body.appendChild(el);
  }
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
      `<span class="nm">${esc(p.name.replace(/_/g, " "))}</span>`;
    b.addEventListener("click", () => {
      onChange(p.name);
      $$(".pal", g).forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    });
    g.appendChild(b);
  }
  return g;
}

function chipToggle(label, on, onChange) {
  const b = document.createElement("button");
  b.className = "target-chip" + (on ? " on" : "");
  b.textContent = label;
  b.addEventListener("click", () => onChange(!on));
  return b;
}

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
  const needle = q.trim().toLowerCase();
  for (const g of S.catalog.effects) {
    const items = g.effects.filter(
      (e) => !needle || e.label.toLowerCase().includes(needle) ||
             e.description.toLowerCase().includes(needle) ||
             g.category.toLowerCase().includes(needle));
    if (!items.length) continue;
    const t = document.createElement("div");
    t.className = "cat-title";
    t.textContent = `${g.category} · ${items.length}`;
    box.appendChild(t);
    const grid = document.createElement("div");
    grid.className = "fx-grid";
    for (const e of items) {
      const b = document.createElement("button");
      b.className = "fx";
      const need = e.needs.length
        ? `<span class="need">precisa de ${e.needs.map(n => ({audio:"audio",screen:"tela",sensors:"sensores"}[n]||n)).join(" + ")}</span>` : "";
      b.innerHTML = `<div class="t">${esc(e.label)}</div><div class="d">${esc(e.description)}</div>${need}`;
      b.addEventListener("click", () => pickEffect(e.id));
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
    } else {
      await API.post("/api/layer/update", { id: S.effectPickTarget, patch: { effect: id } });
    }
    await refreshState();
    renderParams();
  } catch (e) {
    toast(e.message, true);
  }
}

$("#presetSearch").addEventListener("input", (e) => renderPresets(e.target.value));
$("#btnAddLayer").addEventListener("click", () => openEffectPicker("new"));
$("#btnChangeEffect").addEventListener("click", () => S.selected && openEffectPicker(S.selected));
$("#btnCloseModal").addEventListener("click", () => ($("#effectModal").hidden = true));
$("#effectSearch").addEventListener("input", (e) => buildEffectGrid(e.target.value));
$("#effectModal").addEventListener("click", (e) => {
  if (e.target.id === "effectModal") $("#effectModal").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#effectModal").hidden = true;
});

let drag = null;

function drawLayout() {
  const { w, h, dpr } = fitCanvas(lc);
  lctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  lctx.fillStyle = "#05070a";
  lctx.fillRect(0, 0, w, h);

  lctx.strokeStyle = "rgba(255,255,255,.045)";
  lctx.lineWidth = 1;
  for (let i = 1; i < 8; i++) {
    const x = PAD + (i / 8) * (w - PAD * 2), y = PAD + (i / 8) * (h - PAD * 2);
    lctx.beginPath(); lctx.moveTo(x, PAD); lctx.lineTo(x, h - PAD); lctx.stroke();
    lctx.beginPath(); lctx.moveTo(PAD, y); lctx.lineTo(w - PAD, y); lctx.stroke();
  }

  for (const z of S.zones) {
    const sel = S.selZone && S.selZone.device_key === z.device_key &&
                S.selZone.zone_index === z.zone_index;
    const pts = S.positions.slice(z.start, z.start + z.count).map((p) => project(p[0], p[1], w, h));
    if (!pts.length) continue;

    if (pts.length > 1) {
      lctx.strokeStyle = sel ? "rgba(0,217,255,.75)" : "rgba(255,255,255,.16)";
      lctx.lineWidth = sel ? 2 : 1;
      lctx.beginPath();
      pts.forEach((p, i) => (i ? lctx.lineTo(p[0], p[1]) : lctx.moveTo(p[0], p[1])));
      lctx.stroke();
    }
    for (const p of pts) {
      lctx.fillStyle = sel ? "#00d9ff" : "#57647a";
      lctx.beginPath();
      lctx.arc(p[0], p[1], sel ? 4 : 3, 0, 6.284);
      lctx.fill();
    }

    const c = zoneCentroid(z, w, h);
    lctx.font = sel ? "600 11px 'Segoe UI',sans-serif" : "11px 'Segoe UI',sans-serif";
    lctx.textAlign = "center";
    lctx.fillStyle = sel ? "#00d9ff" : "rgba(200,210,225,.55)";
    lctx.fillText(z.zone_name, c[0], c[1] - 12);

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
}

function handlesFor(z, w, h) {
  const g = z.geometry || {};
  const out = [];
  if (g.shape === "line") {
    out.push({ id: "p1", ...pxy(g.x1, g.y1, w, h) });
    out.push({ id: "p2", ...pxy(g.x2, g.y2, w, h) });
  } else if (g.shape === "ring") {
    out.push({ id: "c", ...pxy(g.cx, g.cy, w, h) });
    out.push({ id: "r", ...pxy(g.cx + g.radius, g.cy, w, h) });
  } else if (g.shape === "grid" || g.shape === "serpentine") {
    out.push({ id: "o", ...pxy(g.x, g.y, w, h) });
    out.push({ id: "s", ...pxy(g.x + g.w, g.y + g.h, w, h) });
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
  return [clamp((px - PAD) / (w - PAD * 2), -0.2, 1.2),
          clamp((py - PAD) / (h - PAD * 2), -0.2, 1.2)];
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
    const c = zoneCentroid(best, w, h);
    drag = { mode: "move", zone: best, w, h, ox: mx - c[0], oy: my - c[1] };
    lc.setPointerCapture(e.pointerId);
  } else {
    S.selZone = null;
    renderZoneEditor();
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
    const dx = cx - cur[0], dy = cy - cur[1];
    shiftGeom(g, dx, dy);
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
  lc.releasePointerCapture(e.pointerId);
  await saveZoneGeometry(z);
});

function zoneByKey(k) {
  return S.zones.find((z) => z.device_key === k.device_key && z.zone_index === k.zone_index);
}

function geomCenter(g) {
  if (g.shape === "line") return [(g.x1 + g.x2) / 2, (g.y1 + g.y2) / 2];
  if (g.shape === "ring") return [g.cx, g.cy];
  if (g.shape === "grid" || g.shape === "serpentine") return [g.x + g.w / 2, g.y + g.h / 2];
  return [g.x, g.y];
}

function shiftGeom(g, dx, dy) {
  if (g.shape === "line") { g.x1 += dx; g.y1 += dy; g.x2 += dx; g.y2 += dy; }
  else if (g.shape === "ring") { g.cx += dx; g.cy += dy; }
  else { g.x += dx; g.y += dy; }
}

function applyGeomLocal(z, g) {
  const n = z.count;
  const out = [];
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
  } else {
    for (let i = 0; i < n; i++) {
      const t = n === 1 ? 0.5 : i / (n - 1);
      out.push([g.x1 + (g.x2 - g.x1) * t, g.y1 + (g.y2 - g.y1) * t]);
    }
  }
  if (g.reverse) out.reverse();
  for (let i = 0; i < n; i++) S.positions[z.start + i] = out[i];
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

function renderZoneEditor() {
  const box = $("#zoneEditor");
  if (!S.selZone) {
    box.innerHTML = `<p class="muted center">Clique numa zona no mapa.</p>`;
    return;
  }
  const z = zoneByKey(S.selZone);
  if (!z) { box.innerHTML = ""; return; }
  const g = z.geometry || {};
  box.innerHTML = `<p class="hint" style="margin:0 0 12px">
      <b style="color:var(--text)">${esc(z.zone_name)}</b><br>${z.count} leds
    </p>`;

  const shapes = [
    { value: "point", label: "Ponto" }, { value: "line", label: "Linha" },
    { value: "ring", label: "Anel (fan)" }, { value: "grid", label: "Grade" },
    { value: "serpentine", label: "Serpentina" },
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
  };
  numeric.serpentine = numeric.grid;

  for (const [k, lbl] of (numeric[g.shape] || numeric.line)) {
    const isDeg = k.endsWith("_deg");
    const isCount = k === "cols" || k === "rows";
    const min = isDeg ? -360 : isCount ? 1 : -0.5;
    const max = isDeg ? 720 : isCount ? 64 : 1.5;
    const step = isDeg ? 1 : isCount ? 1 : 0.005;
    box.appendChild(sliderField(lbl, g[k] ?? 0, min, max, step, (v) => {
      z.geometry[k] = v;
      applyGeomLocal(z, z.geometry);
      drawLayout();
      clearTimeout(z._t);
      z._t = setTimeout(() => saveZoneGeometry(z), 220);
    }, (v) => (isDeg || isCount ? Math.round(v) : (+v).toFixed(3))));
  }

  box.appendChild(switchEl("Inverter ordem dos LEDs", !!g.reverse, (v) => {
    z.geometry.reverse = v;
    applyGeomLocal(z, z.geometry);
    saveZoneGeometry(z);
    drawLayout();
  }));
}

function defaultGeom(shape, old) {
  const [cx, cy] = geomCenter(old);
  if (shape === "point") return { shape, x: cx, y: cy };
  if (shape === "ring") return { shape, cx, cy, radius: 0.13, start_deg: -90, end_deg: 270 };
  if (shape === "grid" || shape === "serpentine")
    return { shape, x: cx - 0.2, y: cy - 0.1, w: 0.4, h: 0.2, cols: 0, rows: 0 };
  return { shape: "line", x1: cx - 0.25, y1: cy, x2: cx + 0.25, y2: cy };
}

$("#btnResetLayout").addEventListener("click", async () => {
  await API.post("/api/layout/reset");
  S.selZone = null;
  await refreshState();
  renderZoneEditor();
  drawLayout();
  toast("Layout restaurado");
});

function renderDevices() {
  const box = $("#deviceList");
  const devs = (S.state && S.state.devices) || [];
  box.innerHTML = "";
  if (!devs.length) {
    box.innerHTML = `<p class="muted center" style="padding:24px">Nenhum dispositivo. Verifique se o OpenRGB esta rodando.</p>`;
    return;
  }
  const enabled = (S.state.enabled_devices) || {};
  for (const d of devs) {
    const el = document.createElement("div");
    el.className = "device";
    const on = enabled[d.key] !== false;
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
      <div class="device-meta">${esc(d.vendor || "")} ${esc(d.description || "")}</div>`;

    const sw = switchEl("Controlar pelo Prism", on, async (v) => {
      const e2 = { ...enabled, [d.key]: v };
      await API.post("/api/settings", { enabled_devices: e2 });
      refreshState();
    });
    el.querySelector(".device-head").appendChild(sw.querySelector(".switch"));

    for (const z of d.zones) {
      const row = document.createElement("div");
      row.className = "zone-row";
      row.innerHTML = `<span class="zn">${esc(z.name)}</span>
                       <span class="zt">${esc(z.type_name)} · ${z.leds_count} leds</span>`;
      if (z.resizable) {
        const rz = document.createElement("div");
        rz.className = "resize";
        const inp = document.createElement("input");
        inp.type = "number";
        inp.min = z.leds_min; inp.max = Math.min(z.leds_max, 512);
        inp.value = z.leds_count;
        const find = document.createElement("button");
        find.className = "btn sm primary";
        find.textContent = "Descobrir";
        find.addEventListener("click", () =>
          openProbe(d.key, z.index, z.name, false));
        const b = document.createElement("button");
        b.className = "btn sm";
        b.textContent = "Aplicar";
        b.addEventListener("click", async () => {
          b.disabled = true; b.textContent = "…";
          try {
            const r = await API.post("/api/zone/resize", {
              device: d.key, zone: z.index, size: parseInt(inp.value, 10) });
            toast(r.ok ? `${z.name}: ${inp.value} leds` : r.error, !r.ok);
          } catch (e) { toast(e.message, true); }
          b.disabled = false; b.textContent = "Aplicar";
          refreshState();
        });
        rz.append(document.createTextNode("LEDs:"), inp, b, find);
        row.appendChild(rz);
      }
      el.appendChild(row);
    }
    box.appendChild(el);
  }
}

$("#btnReconnect").addEventListener("click", async () => {
  toast("Reconectando…");
  try { await API.post("/api/reconnect"); } catch (e) { toast(e.message, true); }
  refreshState();
});

async function renderSources() {
  const box = $("#sourcesBody");
  const src = (S.state && S.state.sources) || {};
  const needed = (S.state && S.state.needed) || [];
  box.innerHTML = "";

  box.appendChild(sourceCard("Audio", "audio", src.audio, needed, async (card) => {
    const d = await API.get("/api/audio-devices");
    const opts = [{ value: "", label: "Saida padrao (automatico)" }].concat(
      (d.devices || []).map((x) => ({ value: String(x.index), label: x.name })));
    const cur = String((src.audio.config || {}).device ?? "");
    card.appendChild(field("Dispositivo de loopback", selectEl(opts, cur, async (v) => {
      await API.post("/api/source", { kind: "audio", config: { device: v === "" ? null : parseInt(v, 10) } });
      toast("Fonte de audio atualizada");
      refreshState();
    })));
    if (d.error) card.insertAdjacentHTML("beforeend", `<p class="src-err">${esc(d.error)}</p>`);
    if (src.audio.device_name)
      card.insertAdjacentHTML("beforeend", `<p class="hint">Capturando: ${esc(src.audio.device_name)}</p>`);
  }));

  box.appendChild(sourceCard("Tela", "screen", src.screen, needed, async (card) => {
    const d = await API.get("/api/screen-outputs");
    const opts = (d.outputs || []).map((x) => ({ value: String(x.index), label: x.name }));
    if (!opts.length) opts.push({ value: "0", label: "Saida 0" });
    const cfg = src.screen.config || {};
    card.appendChild(field("Monitor", selectEl(opts, String(cfg.output ?? 0), async (v) => {
      await API.post("/api/source", { kind: "screen", config: { ...cfg, output: parseInt(v, 10) } });
      toast("Monitor atualizado");
      refreshState();
    })));
    card.appendChild(sliderField("Taxa de captura", cfg.fps ?? 30, 10, 60, 1, (v) => {
      clearTimeout(card._t);
      card._t = setTimeout(() => API.post("/api/source", {
        kind: "screen", config: { ...cfg, fps: Math.round(v) } }).then(refreshState), 400);
    }, (v) => Math.round(v) + " fps"));
    if (src.screen.fps) card.insertAdjacentHTML("beforeend",
      `<p class="hint">Capturando a ${src.screen.fps} fps</p>`);
    if (d.error) card.insertAdjacentHTML("beforeend", `<p class="src-err">${esc(d.error)}</p>`);
  }));

  const s = src.sensors || {};
  box.appendChild(sourceCard("Sensores", "sensors", s, needed, async (card) => {
    const ctx = S.state || {};
    const rows = [
      ["CPU temp", "cpu_temp", "°C", 100], ["GPU temp", "gpu_temp", "°C", 100],
      ["CPU uso", "cpu_load", "%", 100], ["GPU uso", "gpu_load", "%", 100],
      ["RAM uso", "ram_load", "%", 100],
    ];
    const avail = new Set(s.available || []);
    for (const [lbl, key, unit, max] of rows) {
      const has = avail.has(key);
      const row = document.createElement("div");
      row.className = "sensor-row";
      row.innerHTML = `<span class="lb">${lbl}</span>
        <span class="meter"><i data-k="${key}"></i></span>
        <span class="vl" data-v="${key}">${has ? "…" : "n/d"}</span>`;
      card.appendChild(row);
    }
    card.dataset.sensors = "1";
    updateSensorMeters();
    if (!s.lhm) {
      card.insertAdjacentHTML("beforeend",
        `<p class="src-err">Temperaturas indisponiveis: ${esc(s.error || "LibreHardwareMonitorLib.dll ausente")}.
         Coloque a DLL em <code>vendor/</code> e rode o Prism como administrador.</p>`);
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

function sourceCard(title, kind, st, needed, fill) {
  const card = document.createElement("div");
  card.className = "panel";
  const running = st && st.running;
  const wanted = needed.includes(kind);
  card.innerHTML = `<div class="panel-head"><h2>${title}</h2></div>
    <div class="src-state"><span class="dot ${running ? "on" : ""}"></span>
      <span>${running ? "ativa" : wanted ? "solicitada, mas parada" : "ociosa (nenhuma camada usa)"}</span></div>`;
  if (st && st.error && !running)
    card.insertAdjacentHTML("beforeend", `<p class="src-err">${esc(st.error)}</p>`);
  fill(card).catch((e) => card.insertAdjacentHTML("beforeend",
    `<p class="src-err">${esc(e.message)}</p>`));
  return card;
}

function renderProfiles() {
  const ul = $("#profileList");
  const list = (S.state && S.state.profiles) || [];
  const cur = S.state && S.state.last_profile;
  ul.innerHTML = "";
  if (!list.length) {
    ul.innerHTML = `<li class="muted" style="justify-content:center">Nenhum perfil salvo ainda.</li>`;
    return;
  }
  for (const name of list) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="nm">${esc(name)}</span>` +
      (name === cur ? `<span class="cur">atual</span>` : "");
    const load = document.createElement("button");
    load.className = "btn sm";
    load.textContent = "Carregar";
    load.addEventListener("click", async () => {
      await API.post("/api/profile/load", { name });
      S.selected = null;
      await refreshState();
      renderParams();
      toast(`Perfil "${name}" carregado`);
    });
    const del = document.createElement("button");
    del.className = "btn sm danger";
    del.textContent = "Excluir";
    del.addEventListener("click", async () => {
      await API.post("/api/profile/delete", { name });
      refreshState();
    });
    li.append(load, del);
    ul.appendChild(li);
  }
}

$("#btnSaveProfile").addEventListener("click", async () => {
  const name = $("#profileName").value.trim();
  if (!name) return toast("Digite um nome", true);
  try {
    const r = await API.post("/api/profile/save", { name });
    if (r.ok) { $("#profileName").value = ""; toast(`Perfil "${r.name}" salvo`); refreshState(); }
    else toast(r.error, true);
  } catch (e) { toast(e.message, true); }
});

let brightTimer = null;
$("#brightness").addEventListener("input", (e) => {
  const v = parseInt(e.target.value, 10);
  $("#brightVal").textContent = v + "%";
  clearTimeout(brightTimer);
  brightTimer = setTimeout(() => API.post("/api/settings", { brightness: v / 100 }), 60);
});

$("#btnPause").addEventListener("click", async () => {
  const paused = !(S.state && S.state.settings && S.state.settings.paused);
  await API.post("/api/settings", { paused });
  refreshState();
});

$("#btnGlow").addEventListener("click", (e) => {
  S.glow = !S.glow;
  e.target.dataset.on = S.glow ? "1" : "0";
});
$("#btnLabels").addEventListener("click", (e) => {
  S.labels = !S.labels;
  e.target.dataset.on = S.labels ? "1" : "0";
});

async function boot() {
  try {
    S.catalog = await API.get("/api/catalog");
  } catch (e) {
    setStatus(false, "falha ao carregar o catalogo");
    return;
  }
  await refreshState();
  renderPresets();
  renderSetupBanner();
  renderNowPlaying();
  renderParams();
  rafLoop();
  setInterval(pollPreview, 33);
  setInterval(refreshState, 1500);
  window.addEventListener("resize", () => { drawPreview(pv, pctx); drawLayout(); });
}

boot();
