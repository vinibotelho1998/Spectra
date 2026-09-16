"use strict";

const HEADER_COLORS = ["#ff2d55", "#00d9ff", "#7cff00", "#ffb020", "#a855f7"];
const PROBE_MAX = 256;

const W = {
  step: 0,
  zones: [],
  inventory: [],
  assign: {},
  perPiece: {},
  round: 0,
  seen: new Set(),
  busy: false,
};

const zoneKey = (z) => `${z.device}:${z.zone}`;

function defaultInventory() {
  return [
    { id: "fans1", label: "Fans (grupo 1)", kind: "fan", pieces: 3, spot: "topo_centro" },
    { id: "fans2", label: "Fans (grupo 2)", kind: "fan", pieces: 3, spot: "base_centro" },
    { id: "cabo24", label: "Fita do cabo 24 pinos", kind: "cable", pieces: 1, lanes: 12, spot: "placa_mae" },
  ];
}

async function startWizard(list) {
  if (W.busy) return;
  W.busy = true;
  try {
    const r = await API.post("/api/probe/multi/start", { max: PROBE_MAX });
    if (!r.ok) return toast(r.error || "nao consegui iniciar", true);

    let zs = r.zones;
    if (list && list.length) {
      const want = new Set(list.map((z) => `${z.device}:${z.zone}`));
      zs = zs.filter((z) => want.has(`${z.device}:${z.zone}`));
    }
    W.zones = zs.map((z, i) => ({
      device: z.device, zone: z.zone, name: z.zone_name,
      color: HEADER_COLORS[i % HEADER_COLORS.length],
      lo: 1, hi: PROBE_MAX, count: null, empty: false,
    }));
    W.inventory = loadInventory();
    W.assign = {};
    W.perPiece = {};
    W.round = 0;
    W.step = 0;
    $("#probeModal").hidden = false;
    renderStep();
  } catch (e) {
    toast(e.message, true);
  } finally {
    W.busy = false;
  }
}

function openProbe(device, zone, name) {
  return startWizard([{ device, zone }]);
}

function loadInventory() {
  try {
    const raw = localStorage.getItem("spectra.inventory");
    if (raw) {
      const v = JSON.parse(raw);
      if (Array.isArray(v) && v.length) return v;
    }
  } catch (e) {}
  return defaultInventory();
}

function saveInventory() {
  try {
    localStorage.setItem("spectra.inventory", JSON.stringify(W.inventory));
  } catch (e) {}
}

async function closeWizard(apply) {
  $("#probeModal").hidden = true;
  try {
    await API.post("/api/probe/finish", {});
  } catch (e) {}
  await refreshState();
  renderSetupBanner();
  renderPresets();
  renderNowPlaying();
  if ($("#tab-devices").classList.contains("active")) renderDevices();
  if ($("#tab-layout").classList.contains("active")) drawLayout();
}

const STEPS = ["Inventario", "Contagem", "Conferencia", "Atribuicao",
               "Divisao", "Aplicar"];

function renderStepper() {
  $("#probeStepper").innerHTML = STEPS.map((s, i) =>
    `<span class="stp${i === W.step ? " on" : ""}${i < W.step ? " done" : ""}">
       <b>${i + 1}</b>${esc(s)}</span>`).join("");
}

function renderStep() {
  renderStepper();
  const b = $("#probeBody");
  b.innerHTML = "";
  if (W.step === 0) stepInventory(b);
  else if (W.step === 1) stepCount(b);
  else if (W.step === 2) stepVerify(b);
  else if (W.step === 3) stepAssign(b);
  else if (W.step === 4) stepSplit(b);
  else stepApply(b);
}

function nav(box, backLabel, back, nextLabel, next, nextDisabled) {
  const d = document.createElement("div");
  d.className = "probe-actions";
  if (backLabel) {
    const bb = document.createElement("button");
    bb.className = "btn sm";
    bb.textContent = backLabel;
    bb.addEventListener("click", back);
    d.appendChild(bb);
  }
  if (nextLabel) {
    const nb = document.createElement("button");
    nb.className = "btn primary";
    nb.textContent = nextLabel;
    nb.disabled = !!nextDisabled;
    nb.addEventListener("click", next);
    d.appendChild(nb);
  }
  box.appendChild(d);
  return d;
}

function stepInventory(box) {
  box.insertAdjacentHTML("beforeend", `
    <p class="probe-lead">Descreva o que existe no gabinete. O assistente usa
    isso para <b>calcular</b> o tamanho de cada peca em vez de perguntar, e para
    montar o mapa fisico sozinho.</p>`);

  box.insertAdjacentHTML("beforeend", `
    <div class="inv-cols">
      <span>Peca</span><span>Tipo</span><span>Quantas</span>
      <span>Laminas</span><span>Onde fica</span><span></span>
    </div>`);

  const list = document.createElement("div");
  list.className = "inv-list";
  const spots = (S.catalog && S.catalog.spots) || [];

  W.inventory.forEach((it, i) => {
    const row = document.createElement("div");
    row.className = "inv-row";
    row.innerHTML = `
      <input class="inv-label" type="text" value="${esc(it.label)}">
      <select class="inv-kind">
        <option value="fan"${it.kind === "fan" ? " selected" : ""}>Fan (anel)</option>
        <option value="strip"${it.kind === "strip" ? " selected" : ""}>Fita (linha)</option>
        <option value="cable"${it.kind === "cable" ? " selected" : ""}>Fita de cabo (laminas)</option>
      </select>
      <input class="inv-pieces" type="number" min="1" max="24" value="${it.pieces}" title="Quantas pecas">
      <input class="inv-lanes" type="number" min="2" max="48" value="${it.lanes || 12}"
             title="Quantas laminas paralelas" ${it.kind === "cable" ? "" : "hidden"}>
      <select class="inv-spot">${spots.map((s) =>
        `<option value="${s.value}"${s.value === it.spot ? " selected" : ""}>${esc(s.label)}</option>`).join("")}</select>
      <button class="inv-del" title="Remover">&times;</button>`;
    row.querySelector(".inv-label").addEventListener("change", (e) => { it.label = e.target.value; saveInventory(); });
    row.querySelector(".inv-kind").addEventListener("change", (e) => {
      it.kind = e.target.value;
      if (it.kind === "cable" && !it.lanes) it.lanes = 12;
      saveInventory();
      renderStep();
    });
    row.querySelector(".inv-lanes").addEventListener("change", (e) => {
      it.lanes = Math.max(2, parseInt(e.target.value, 10) || 12); saveInventory();
    });
    row.querySelector(".inv-pieces").addEventListener("change", (e) => {
      it.pieces = Math.max(1, parseInt(e.target.value, 10) || 1); saveInventory();
    });
    row.querySelector(".inv-spot").addEventListener("change", (e) => { it.spot = e.target.value; saveInventory(); });
    row.querySelector(".inv-del").addEventListener("click", () => {
      W.inventory.splice(i, 1); saveInventory(); renderStep();
    });
    list.appendChild(row);
  });
  box.appendChild(list);

  const add = document.createElement("div");
  add.className = "inv-add";
  add.innerHTML = `<button class="btn sm" data-k="fan">+ Fans</button>
                   <button class="btn sm" data-k="strip">+ Fita</button>
                   <button class="btn sm ghost" data-k="reset">Restaurar sugestao</button>`;
  add.addEventListener("click", (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    if (k === "reset") W.inventory = defaultInventory();
    else W.inventory.push({
      id: "i" + Date.now().toString(36),
      label: k === "fan" ? "Novos fans" : "Nova fita",
      kind: k, pieces: 1, spot: "meio",
    });
    saveInventory();
    renderStep();
  });
  box.appendChild(add);

  nav(box, "Cancelar", () => closeWizard(false), "Comecar a contagem", () => {
    saveInventory();
    W.step = 1;
    W.round = 0;
    renderStep();
    paintRound();
  });
}

function pending() {
  return W.zones.filter((z) => z.count === null && !z.empty);
}

function midOf(z) {
  return Math.ceil((z.lo + z.hi) / 2);
}

async function paintRound() {
  const items = pending().map((z) => ({
    device: z.device, zone: z.zone, index: midOf(z), color: z.color,
    tail: true,
  }));
  if (!items.length) return;
  try {
    await API.post("/api/probe/multi/paint", { items });
  } catch (e) { toast(e.message, true); }
}

function stepCount(box) {
  const left = pending();
  if (!left.length) {
    W.step = 2;
    W._verifyIdx = 0;
    return renderStep();
  }
  W.round++;
  box.insertAdjacentHTML("beforeend", `
    <p class="probe-lead">Cada conector acendeu <b>a partir de um ponto ate o
    fim</b>, numa cor propria. Marque as cores que voce <b>consegue ver agora</b>
    no gabinete — pode ser um trecho pequeno, basta ver <b>qualquer</b> LED
    daquela cor. Uma resposta avanca os tres conectores de uma vez.</p>`);

  const grid = document.createElement("div");
  grid.className = "seen-grid";
  for (const z of left) {
    const b = document.createElement("button");
    b.className = "seen" + (W.seen.has(zoneKey(z)) ? " on" : "");
    b.style.setProperty("--c", z.color);
    b.innerHTML = `<span class="dot"></span>
      <span class="nm">${esc(z.name)}</span>
      <span class="idx">aceso do LED ${midOf(z)} em diante · faixa ${z.lo}–${z.hi}</span>`;
    b.addEventListener("click", () => {
      const k = zoneKey(z);
      if (W.seen.has(k)) W.seen.delete(k); else W.seen.add(k);
      b.classList.toggle("on", W.seen.has(k));
    });
    grid.appendChild(b);
  }
  box.appendChild(grid);
  box.insertAdjacentHTML("beforeend",
    `<p class="hint">Na duvida, olhe o gabinete inteiro antes de responder: se
     uma cor aparecer em <b>qualquer</b> fan ou fita, marque. Errar um "nao vi"
     faz a contagem terminar baixa demais — mas o proximo passo confere isso.</p>`);

  nav(box, "Voltar", () => { W.step = 0; renderStep(); },
      "Responder", async () => {
        const vistos = new Set(W.seen);
        W.seen = new Set();
        for (const z of left) {
          const m = midOf(z);
          if (vistos.has(zoneKey(z))) z.lo = m; else z.hi = m - 1;
          if (z.hi < 1) { z.empty = true; z.count = 0; }
          else if (z.lo >= z.hi) z.count = z.lo;
        }
        renderStep();
        await paintRound();
      });
}

async function lightVerify(z, n) {
  try {
    await API.post("/api/probe/isolate", {
      device: z.device, zone: z.zone, start: 0,
      count: n != null ? n : z.count, color: z.color,
    });
  } catch (e) {}
}

function stepVerify(box) {
  const zs = activeZones();
  if (!zs.length) {
    box.insertAdjacentHTML("beforeend",
      `<p class="probe-lead">Nenhum conector respondeu na contagem. Verifique se
       os cabos ARGB estao ligados e refaca.</p>`);
    return nav(box, "Refazer contagem", () => {
      W.zones.forEach((z) => { z.lo = 1; z.hi = PROBE_MAX; z.count = null; z.empty = false; });
      W.step = 1; renderStep(); paintRound();
    }, "Sair", () => closeWizard(false));
  }

  const idx = Math.min(W._verifyIdx || 0, zs.length - 1);
  const z = zs[idx];
  lightVerify(z);

  box.insertAdjacentHTML("beforeend", `
    <p class="probe-lead">Acendi <b>${z.count} LEDs</b> no conector
    <b style="color:${z.color}">${esc(z.name)}</b>, do primeiro ao ultimo.
    <b>Alguma fan ou pedaco de fita desse conector continua apagado?</b>
    Se sim, aumente ate tudo acender.</p>`);

  const big = document.createElement("div");
  big.className = "probe-big";
  big.innerHTML = `<span id="vfCount">${z.count}</span> <small>LEDs</small>`;
  box.appendChild(big);

  const sl = document.createElement("input");
  sl.type = "range";
  sl.min = 1;
  sl.max = PROBE_MAX;
  sl.value = z.count;
  box.appendChild(sl);

  const ctrl = document.createElement("div");
  ctrl.className = "verify-controls";
  ctrl.innerHTML = `
    <button class="btn sm" data-d="-5">− 5</button>
    <button class="btn sm" data-d="-1">− 1</button>
    <button class="btn sm" data-d="1">+ 1</button>
    <button class="btn sm" data-d="5">+ 5</button>
    <button class="btn sm ghost" id="vfMax">Acender o maximo (${PROBE_MAX})</button>`;
  box.appendChild(ctrl);

  let timer = null;
  const setN = (n) => {
    z.count = clamp(Math.round(n), 1, PROBE_MAX);
    $("#vfCount").textContent = z.count;
    sl.value = z.count;
    clearTimeout(timer);
    timer = setTimeout(() => lightVerify(z), 40);
  };
  sl.addEventListener("input", () => setN(parseInt(sl.value, 10)));
  ctrl.querySelectorAll("[data-d]").forEach((b) =>
    b.addEventListener("click", () => setN(z.count + parseInt(b.dataset.d, 10))));
  $("#vfMax", ctrl).addEventListener("click", () => {
    lightVerify(z, PROBE_MAX);
    toast(`Acendi ${PROBE_MAX}. Se acendeu mais coisa, suba o numero ate igualar.`);
  });

  box.insertAdjacentHTML("beforeend",
    `<p class="hint">Dica: clique em <b>Acender o maximo</b>. Se acender alguma
     peca que estava apagada, a contagem esta baixa — suba ate os dois estados
     ficarem iguais. Conector ${idx + 1} de ${zs.length}.</p>`);

  nav(box, idx > 0 ? "Conector anterior" : "Refazer contagem",
      () => {
        if (idx > 0) { W._verifyIdx = idx - 1; renderStep(); }
        else {
          W.zones.forEach((x) => { x.lo = 1; x.hi = PROBE_MAX; x.count = null; x.empty = false; });
          W.step = 1; renderStep(); paintRound();
        }
      },
      idx < zs.length - 1 ? "Proximo conector" : "Tudo aceso, continuar",
      () => {
        if (idx < zs.length - 1) { W._verifyIdx = idx + 1; renderStep(); }
        else { W._verifyIdx = 0; W._assignIdx = 0; W.step = 3; renderStep(); }
      });
}

function activeZones() {
  return W.zones.filter((z) => (z.count || 0) > 0);
}

async function stepAssign(box) {
  const zs = activeZones();
  if (!zs.length) {
    box.insertAdjacentHTML("beforeend",
      `<p class="probe-lead">Nenhum conector respondeu. Verifique se os cabos
       ARGB estao ligados e tente de novo.</p>`);
    return nav(box, "Refazer contagem", () => {
      W.zones.forEach((z) => { z.lo = 1; z.hi = PROBE_MAX; z.count = null; z.empty = false; });
      W.step = 1; renderStep(); paintRound();
    }, "Sair", () => closeWizard(false));
  }

  const idx = W._assignIdx || 0;
  const z = zs[Math.min(idx, zs.length - 1)];
  API.post("/api/probe/isolate", {
    device: z.device, zone: z.zone, start: 0, count: z.count, color: z.color,
  }).catch(() => {});

  box.insertAdjacentHTML("beforeend", `
    <p class="probe-lead">O conector <b style="color:${z.color}">${esc(z.name)}</b>
    está todo aceso agora (${z.count} LEDs). <b>Quais pecas do seu gabinete
    acenderam?</b></p>`);

  const cur = new Set(W.assign[zoneKey(z)] || []);
  const grid = document.createElement("div");
  grid.className = "pick-grid";
  for (const it of W.inventory) {
    const b = document.createElement("button");
    b.className = "pick" + (cur.has(it.id) ? " on" : "");
    b.innerHTML = `<span class="t">${esc(it.label)}</span>
                   <span class="s">${it.pieces} ${it.kind === "fan" ? "peca(s)" : "fita(s)"}</span>`;
    b.addEventListener("click", () => {
      if (cur.has(it.id)) cur.delete(it.id); else cur.add(it.id);
      W.assign[zoneKey(z)] = [...cur];
      b.classList.toggle("on", cur.has(it.id));
    });
    grid.appendChild(b);
  }
  box.appendChild(grid);
  box.insertAdjacentHTML("beforeend",
    `<p class="hint">Conector ${idx + 1} de ${zs.length}. Se este conector tem um
     hub com varios grupos, marque todos os que acenderam.</p>`);

  nav(box, idx > 0 ? "Conector anterior" : "Voltar",
      () => {
        if (idx > 0) { W._assignIdx = idx - 1; renderStep(); }
        else { W.step = 2; W._assignIdx = 0; renderStep(); }
      },
      idx < zs.length - 1 ? "Proximo conector" : "Continuar",
      () => {
        if (idx < zs.length - 1) { W._assignIdx = idx + 1; renderStep(); }
        else { W._assignIdx = 0; W.step = 4; renderStep(); }
      });
}

function piecesOf(z) {
  const ids = W.assign[zoneKey(z)] || [];
  const out = [];
  for (const id of ids) {
    const it = W.inventory.find((x) => x.id === id);
    if (it) out.push(it);
  }
  return out;
}

function autoSplit(z) {
  const items = piecesOf(z);
  const totalPieces = items.reduce((a, it) => a + it.pieces, 0);
  const key = zoneKey(z);
  for (const it of items) {
    const k = key + "|" + it.id;
    if (W.perPiece[k] == null) {
      W.perPiece[k] = totalPieces > 0
        ? Math.max(1, Math.floor(z.count / totalPieces)) : z.count;
    }
  }
  return items;
}

function splitTotal(z, items) {
  const key = zoneKey(z);
  return items.reduce((a, it) => a + (W.perPiece[key + "|" + it.id] || 0) * it.pieces, 0);
}

let splitTimer = null;
function previewSplitSoon(z, items) {
  clearTimeout(splitTimer);
  splitTimer = setTimeout(() => previewSplit(z, items), 120);
}

async function previewSplit(z, items) {
  const key = zoneKey(z);
  const sizes = items.flatMap((it) => Array(it.pieces).fill(W.perPiece[key + "|" + it.id] || 0));
  if (!sizes.length) return;
  await API.post("/api/probe/split", {
    device: z.device, zone: z.zone, size: Math.max(1, sizes[0]),
    total: Math.min(z.count, sizes.reduce((a, b) => a + b, 0)),
  }).catch(() => {});
}

function stepSplit(box) {
  const zs = activeZones().filter((z) => piecesOf(z).length);
  if (!zs.length) { W.step = 5; return renderStep(); }

  const idx = Math.min(W._splitIdx || 0, zs.length - 1);
  const z = zs[idx];
  const items = autoSplit(z);
  previewSplitSoon(z, items);

  const used = splitTotal(z, items);
  const diff = z.count - used;

  box.insertAdjacentHTML("beforeend", `
    <p class="probe-lead">O conector <b style="color:${z.color}">${esc(z.name)}</b>
    tem <b>${z.count} LEDs</b>. Dividindo entre as pecas que voce marcou, cada
    uma fica com o valor abaixo. As cores no gabinete mostram onde uma peca
    termina e a outra comeca — ajuste se as fronteiras nao baterem.</p>`);

  const wrap = document.createElement("div");
  wrap.className = "split-list";
  for (const it of items) {
    const k = zoneKey(z) + "|" + it.id;
    const row = document.createElement("div");
    row.className = "split-row";
    row.innerHTML = `
      <span class="nm">${esc(it.label)}</span>
      <span class="mult">${it.pieces} x</span>
      <button class="mini" data-d="-1">−</button>
      <input type="number" min="1" max="${z.count}" value="${W.perPiece[k]}">
      <button class="mini" data-d="1">+</button>
      <span class="tot">= ${W.perPiece[k] * it.pieces} LEDs</span>`;
    const inp = row.querySelector("input");
    const bump = (d) => {
      W.perPiece[k] = Math.max(1, (W.perPiece[k] || 1) + d);
      renderStep();
    };
    row.querySelectorAll(".mini").forEach((b) =>
      b.addEventListener("click", () => bump(parseInt(b.dataset.d, 10))));
    inp.addEventListener("change", () => {
      W.perPiece[k] = Math.max(1, parseInt(inp.value, 10) || 1);
      renderStep();
    });
    wrap.appendChild(row);
  }
  box.appendChild(wrap);

  const cls = diff === 0 ? "ok" : (diff > 0 ? "warn" : "err");
  const msg = diff === 0 ? "bate exatamente com os LEDs do conector"
    : diff > 0 ? `sobram ${diff} LEDs sem peca atribuida`
    : `faltam ${-diff} LEDs: a soma passou do total do conector`;
  box.insertAdjacentHTML("beforeend",
    `<p class="split-sum ${cls}">${used} de ${z.count} LEDs — ${msg}</p>`);

  nav(box, idx > 0 ? "Conector anterior" : "Voltar",
      () => {
        if (idx > 0) { W._splitIdx = idx - 1; renderStep(); }
        else { W._splitIdx = 0; W.step = 3; renderStep(); }
      },
      idx < zs.length - 1 ? "Proximo conector" : "Ver resumo",
      () => {
        if (idx < zs.length - 1) { W._splitIdx = idx + 1; renderStep(); }
        else { W._splitIdx = 0; W.step = 5; renderStep(); }
      },
      diff < 0);
}

function stepApply(box) {
  const zs = activeZones();
  box.insertAdjacentHTML("beforeend",
    `<p class="probe-lead">Confira e aplique. Isto grava a contagem de cada
     conector e monta o mapa fisico: cada fan vira um anel na posicao que voce
     indicou, cada fita vira uma linha.</p>`);

  const t = document.createElement("div");
  t.className = "sum-list";
  for (const z of W.zones) {
    if (!z.count) {
      t.insertAdjacentHTML("beforeend",
        `<div class="sum-row empty"><b>${esc(z.name)}</b><span>vazio — nenhum LED respondeu</span></div>`);
      continue;
    }
    const items = piecesOf(z);
    const desc = items.length
      ? items.map((it) => `${it.pieces}x ${esc(it.label)} (${W.perPiece[zoneKey(z) + "|" + it.id]} LEDs cada)`).join("<br>")
      : "sem pecas atribuidas — vira uma linha unica";
    t.insertAdjacentHTML("beforeend",
      `<div class="sum-row"><b style="color:${z.color}">${esc(z.name)}</b>
       <span><b>${z.count} LEDs</b><br>${desc}</span></div>`);
  }
  box.appendChild(t);

  nav(box, "Voltar", () => { W.step = 4; renderStep(); },
      "Aplicar tudo", () => applyAll());
}

async function applyAll() {
  const btn = $("#probeBody .probe-actions .primary");
  if (btn) { btn.disabled = true; btn.textContent = "Aplicando…"; }
  try {
    for (const z of W.zones) {
      await API.post("/api/probe/commit", {
        device: z.device, zone: z.zone, count: z.count || 0 });
    }
    await API.post("/api/probe/finish", {});

    for (const z of activeZones()) {
      const items = piecesOf(z);
      if (!items.length) continue;
      const parts = [];
      for (const it of items) {
        const c = W.perPiece[zoneKey(z) + "|" + it.id] || 0;
        for (let i = 0; i < it.pieces; i++)
          parts.push({ kind: it.kind, count: c, spot: it.spot,
                       lanes: it.lanes || 12 });
      }
      await API.post("/api/zone/plan", {
        device: z.device, zone: z.zone, parts });
    }
    $("#probeModal").hidden = true;
    toast(`Configurado: ${W.zones.filter((z) => z.count)
      .map((z) => `${z.name} = ${z.count}`).join(", ")}`);
  } catch (e) {
    toast(e.message, true);
  }
  await refreshState();
  renderSetupBanner();
  renderPresets();
  renderNowPlaying();
  if ($("#tab-devices").classList.contains("active")) renderDevices();
  if ($("#tab-layout").classList.contains("active")) drawLayout();
}

function sairDoAssistente() {
  if (W.step > 0 && !confirm(
      "Sair do assistente? As contagens descobertas ate aqui sao descartadas.")) {
    return;
  }
  closeWizard(false);
}

document.addEventListener("DOMContentLoaded", () => {
  $("#probeCancel").addEventListener("click", sairDoAssistente);
  $("#probeModal").addEventListener("click", (e) => {
    if (e.target.id === "probeModal") sairDoAssistente();
  });
});
