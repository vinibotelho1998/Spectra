"use strict";

const NEED_LABEL = { audio: "audio", screen: "tela", sensors: "sensores" };

let showAllPresets = false;

function presetById(id) {
  for (const g of ((S.catalog && S.catalog.presets) || []))
    for (const p of g.presets) if (p.id === id) return p;
  return null;
}

function renderPresets(filter) {
  const box = $("#presetGrid");
  if (!box || !S.catalog) return;
  const q = (filter !== undefined ? filter : ($("#presetSearch").value || ""))
    .trim().toLowerCase();
  box.innerHTML = "";
  for (const g of (S.catalog.presets || [])) {
    const items = g.presets.filter(
      (p) => (showAllPresets || p.refined !== false) &&
             (!q || p.name.toLowerCase().includes(q) ||
              p.description.toLowerCase().includes(q) ||
              g.category.toLowerCase().includes(q)));
    if (!items.length) continue;

    const t = document.createElement("div");
    t.className = "cat-title";
    t.textContent = g.category;
    box.appendChild(t);

    const grid = document.createElement("div");
    grid.className = "preset-grid";
    for (const p of items) {
      const b = document.createElement("button");
      b.className = "preset";
      b.dataset.preset = p.id;
      const cols = p.swatch.concat(p.swatch[0]).join(",");
      const badge = p.needs.length
        ? `<span class="badge">usa ${p.needs.map((n) => NEED_LABEL[n] || n).join(" + ")}</span>`
        : (p.refined === false ? `<span class="badge forte">intenso</span>` : "");
      b.innerHTML =
        `<div class="swatch" style="background-image:linear-gradient(90deg,${cols})"></div>` +
        badge +
        `<span class="playing" hidden>tocando</span>` +
        `<div class="body"><div class="t">${esc(p.name)}</div>` +
        `<div class="d">${esc(p.description)}</div></div>`;
      b.addEventListener("click", () => applyPreset(p.id));
      grid.appendChild(b);
    }
    box.appendChild(grid);
  }
  if (!box.children.length)
    box.innerHTML = `<p class="muted center" style="padding:30px">Nada encontrado.</p>`;

  const escondidos = (S.catalog.presets || [])
    .reduce((a, g) => a + g.presets.filter((p) => p.refined === false).length, 0);
  if (escondidos) {
    const bar = document.createElement("div");
    bar.className = "preset-more";
    bar.innerHTML = showAllPresets
      ? `<button class="btn sm">Mostrar so os refinados</button>
         <span class="muted">${escondidos} efeitos intensos visiveis</span>`
      : `<button class="btn sm">Mostrar todos</button>
         <span class="muted">${escondidos} efeitos mais intensos estao ocultos
         (estrobo, flashes bruscos)</span>`;
    bar.querySelector("button").addEventListener("click", () => {
      showAllPresets = !showAllPresets;
      renderPresets();
    });
    box.appendChild(bar);
  }
  markActivePreset();
}

function markActivePreset() {
  const cur = S.state && S.state.last_preset;
  $$(".preset").forEach((el) => {
    const on = el.dataset.preset === cur;
    el.classList.toggle("on", on);
    const tag = el.querySelector(".playing");
    if (tag) tag.hidden = !on;
  });
}

async function applyPreset(id) {
  try {
    const r = await API.post("/api/preset/apply", { id });
    if (!r.ok) return toast(r.error || "falhou ao aplicar", true);
    S.selected = null;
    await refreshState();
    renderParams();
    markActivePreset();
    renderNowPlaying();
    const p = presetById(id);
    let msg = p ? `${p.name} aplicado` : "aplicado";
    if (r.needs && r.needs.length)
      msg += ` — ligando ${r.needs.map((n) => NEED_LABEL[n] || n).join(" + ")}`;
    toast(msg);
  } catch (e) {
    toast(e.message, true);
  }
}

function renderNowPlaying() {
  const box = $("#nowPlaying");
  if (!box) return;
  const st = S.state || {};
  const p = presetById(st.last_preset);
  const layers = st.layers || [];
  if (!layers.length) {
    box.innerHTML = `<p class="muted center" style="padding:12px 0">Nada tocando.</p>`;
    return;
  }
  const names = layers.filter((l) => l.enabled)
    .map((l) => esc(l.name || l.effect)).join(" + ");
  box.innerHTML =
    `<div class="np-name">${esc(p ? p.name : "Cena personalizada")}</div>` +
    `<div class="np-desc">${esc(p ? p.description : "Montada na aba Avancado.")}</div>` +
    `<div class="np-layers">Camadas: <b>${names || "nenhuma ativa"}</b></div>`;
}

function renderSetupBanner() {
  const box = $("#setupBanner");
  if (!box) return;
  const st = S.state || {};
  const todo = st.setup_todo || [];
  const leds = (st.canvas && st.canvas.led_count) || 0;

  const resizable = st.zones_resizable || [];

  if (!todo.length) {
    if (!leds) {
      box.innerHTML = `
        <div class="setup">
          <h3>Nenhum LED controlavel</h3>
          <p>O Prism conectou no OpenRGB, mas nao ha LEDs ativos. Confira a aba
          <b>Hardware</b>.</p>
        </div>`;
      return;
    }
    box.innerHTML = resizable.length ? `
      <div class="setup ok">
        <div class="head-row">
          <h3>${leds} LEDs sob controle</h3>
          <button class="btn sm" id="startWizard">Conferir quantidade de LEDs</button>
        </div>
        <p>${resizable.map((z) => `${esc(z.zone_name)}: <b>${z.count}</b>`).join(" · ")}
        — se algum LED do gabinete fica aceso numa cor que voce nao escolheu, o
        numero desse conector esta <b>menor</b> que o real: os LEDs alem da conta
        nunca recebem dado e ficam com a ultima cor do controlador.</p>
      </div>` : "";
    const w = $("#startWizard");
    if (w) w.addEventListener("click", () => startWizard(resizable));
    return;
  }

  const rows = todo.map((z) => `
    <div class="row" data-dev="${esc(z.device)}" data-zone="${z.zone}">
      <span class="nm">${esc(z.zone_name)} <small>· ${esc(z.device_name)}</small></span>
      <div class="quick">
        <button data-n="8">8</button><button data-n="12">12</button>
        <button data-n="18">18</button><button data-n="24">24</button>
        <button data-n="36">36</button><button data-n="54">54</button>
      </div>
      <input type="number" min="1" max="${z.max}" placeholder="LEDs">
      <button class="btn sm apply">Aplicar</button>
      <button class="btn sm primary find">Descobrir</button>
    </div>`).join("");

  box.innerHTML = `
    <div class="setup">
      <div class="head-row">
        <h3>Falta dizer quantos LEDs voce tem</h3>
        <button class="btn primary sm" id="startWizard">Abrir assistente</button>
      </div>
      <p>Estes conectores estao com <b>0 LEDs</b>, entao nada acende neles.
      Ninguem consegue detectar isso automaticamente: o padrao ARGB e mao unica,
      a fita nunca responde quantos LEDs tem. Mas o <b>assistente</b> descobre
      para voce — ele acende um LED de cada vez e pergunta se acendeu, achando o
      numero exato em poucos cliques.</p>
      <div class="rows">${rows}</div>
      <p class="note">Faltando RAM, water cooler ou GPU na lista? Esses vao por
      SMBus/USB e so aparecem com o servidor do OpenRGB <b>elevado</b>. Rode uma
      vez num PowerShell como administrador:<br>
      <code>powershell -ExecutionPolicy Bypass -File tools\\setup-admin.ps1</code></p>
    </div>`;

  const wz = $("#startWizard");
  if (wz) wz.addEventListener("click", () => startWizard(todo));

  $$("#setupBanner .row").forEach((row) => {
    const inp = row.querySelector("input");
    $$(".quick button", row).forEach((qb) =>
      qb.addEventListener("click", () => { inp.value = qb.dataset.n; inp.focus(); }));
    row.querySelector(".find").addEventListener("click", () =>
      openProbe(row.dataset.dev, parseInt(row.dataset.zone, 10),
                row.querySelector(".nm").textContent.split("·")[0].trim(), false));
    row.querySelector(".apply").addEventListener("click", async (e) => {
      const btn = e.target;
      const n = parseInt(inp.value, 10);
      if (!(n > 0)) return toast("Digite quantos LEDs esse conector tem", true);
      btn.disabled = true;
      btn.textContent = "…";
      try {
        const r = await API.post("/api/zone/resize", {
          device: row.dataset.dev,
          zone: parseInt(row.dataset.zone, 10),
          size: n,
        });
        toast(r.ok ? `${n} LEDs configurados` : (r.error || "falhou"), !r.ok);
      } catch (err) {
        toast(err.message, true);
      }
      await refreshState();
      renderSetupBanner();
      renderPresets();
    });
  });
}
