"use strict";

const NEED_LABEL = { audio: "audio", screen: "tela", sensors: "sensores" };

let showAllPresets = false;
let presetCat = "todos";

const FAV_KEY = "spectra.favoritos";

function loadFavs() {
  try {
    const v = JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
    return new Set(Array.isArray(v) ? v : []);
  } catch (e) { return new Set(); }
}

function saveFavs(set) {
  try { localStorage.setItem(FAV_KEY, JSON.stringify([...set])); } catch (e) {}
}

let FAVS = loadFavs();

function presetById(id) {
  for (const g of ((S.catalog && S.catalog.presets) || []))
    for (const p of g.presets) if (p.id === id) return p;
  return null;
}

function allPresets() {
  const out = [];
  for (const g of ((S.catalog && S.catalog.presets) || []))
    for (const p of g.presets) out.push(p);
  return out;
}

/* --------------------------------------------------------- barra rapida */

const QUICK_COLORS = ["#ff2d55", "#ff7a00", "#ffd60a", "#22e08a",
                      "#00d9ff", "#4361ee", "#a855f7", "#ffffff"];

function buildQuickBar() {
  const box = $("#quickSwatches");
  if (!box) return;
  box.innerHTML = "";
  for (const c of QUICK_COLORS) {
    const b = document.createElement("button");
    b.className = "sw";
    b.style.background = c;
    b.title = c;
    b.addEventListener("click", () => applySolid(c));
    box.appendChild(b);
  }
  $("#quickColor").addEventListener("input", (e) => applySolidSoon(e.target.value));
  $("#btnShuffle").addEventListener("click", () => {
    const pool = allPresets().filter((p) => showAllPresets || p.refined !== false);
    if (!pool.length) return;
    applyPreset(pool[Math.floor(Math.random() * pool.length)].id);
  });
}

/** Troca a cena inteira por uma cor chapada. E o caso de uso mais comum de
 *  todos, e antes exigia montar uma camada na aba Avancado. */
async function applySolid(hex) {
  $("#quickColor").value = hex;
  const antes = snapshotScene();
  try {
    await API.post("/api/layers", {
      preset: null,
      layers: [{ effect: "static", params: { color: hex, intensity: 1.0 },
                 blend: "normal", opacity: 1.0, enabled: true, name: "Cor unica" }],
    });
    S.selected = null;
    await refreshState();
    renderParams();
    renderNowPlaying();
    markActivePreset();
    toast(`Cor ${hex} aplicada`, false, undoAction(antes));
  } catch (e) {
    toast(e.message, true);
  }
}

// o throttle mora no app.js, que carrega depois deste arquivo: por isso a
// versao espacada e montada na primeira chamada, e nao aqui em cima
let _solidSoon = null;
function applySolidSoon(hex) {
  if (!_solidSoon) _solidSoon = throttle((h) => applySolid(h), 180);
  _solidSoon(hex);
}

function snapshotScene() {
  const st = S.state || {};
  return {
    layers: (st.layers || []).map((l) => ({ ...l })),
    preset: st.last_preset || null,
  };
}

function undoAction(antes) {
  if (!antes || !antes.layers.length) return null;
  return {
    label: "Desfazer",
    run: async () => {
      try {
        await API.post("/api/layers", { layers: antes.layers, preset: antes.preset });
        S.selected = null;
        await refreshState();
        renderParams();
        renderNowPlaying();
        markActivePreset();
        toast("Cena anterior restaurada");
      } catch (e) { toast(e.message, true); }
    },
  };
}

/* ---------------------------------------------------------- vitrine */

function renderPresets(filter) {
  const box = $("#presetGrid");
  if (!box || !S.catalog) return;
  const q = (filter !== undefined ? filter : ($("#presetSearch").value || ""))
    .trim().toLowerCase();
  renderPresetChips();
  box.innerHTML = "";

  const disponivel = (p) => {
    if (!p.needs.length) return true;
    const s = (S.state && S.state.sources) || {};
    return p.needs.every((n) => !(s[n] && s[n].error && !s[n].running));
  };

  let mostrados = 0;
  const grupos = presetCat === "favoritos"
    ? [{ category: "Favoritos", presets: allPresets().filter((p) => FAVS.has(p.id)) }]
    : (S.catalog.presets || []).filter(
        (g) => presetCat === "todos" || g.category === presetCat);

  for (const g of grupos) {
    const items = g.presets.filter(
      (p) => (showAllPresets || p.refined !== false || FAVS.has(p.id)) &&
             (!q || p.name.toLowerCase().includes(q) ||
              p.description.toLowerCase().includes(q) ||
              g.category.toLowerCase().includes(q)));
    if (!items.length) continue;

    const t = document.createElement("div");
    t.className = "cat-title";
    t.innerHTML = `${esc(g.category)}<span class="n">${items.length}</span>`;
    box.appendChild(t);

    const grid = document.createElement("div");
    grid.className = "preset-grid";
    for (const p of items) {
      mostrados++;
      grid.appendChild(presetCard(p, disponivel(p)));
    }
    box.appendChild(grid);
  }

  if (!mostrados) {
    box.innerHTML = presetCat === "favoritos"
      ? `<p class="muted center" style="padding:30px">Nenhum favorito ainda. Passe o mouse
         num efeito e clique na estrela.</p>`
      : `<p class="muted center" style="padding:30px">Nada encontrado.</p>`;
  }

  const escondidos = allPresets().filter((p) => p.refined === false && !FAVS.has(p.id)).length;
  if (escondidos && presetCat !== "favoritos") {
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

function presetCard(p, disponivel) {
  const b = document.createElement("button");
  b.className = "preset";
  b.dataset.preset = p.id;
  const cols = p.swatch.concat(p.swatch[0]).join(",");
  const badge = p.needs.length
    ? `<span class="badge">usa ${p.needs.map((n) => NEED_LABEL[n] || n).join(" + ")}</span>`
    : (p.refined === false ? `<span class="badge forte">intenso</span>` : "");
  b.innerHTML =
    `<div class="swatch" style="--sw:linear-gradient(90deg,${cols})"></div>` +
    badge +
    `<span class="playing" hidden>tocando</span>` +
    `<div class="body"><div class="t">${esc(p.name)}</div>` +
    `<div class="d">${esc(p.description)}</div></div>` +
    `<button class="fav${FAVS.has(p.id) ? " on" : ""}" title="Favoritar">${ICON_STAR}</button>`;
  if (!disponivel) b.title = "A fonte que este efeito usa esta indisponivel agora";
  b.addEventListener("click", (e) => {
    if (e.target.closest(".fav")) return;
    applyPreset(p.id);
  });
  b.querySelector(".fav").addEventListener("click", (e) => {
    e.stopPropagation();
    FAVS.has(p.id) ? FAVS.delete(p.id) : FAVS.add(p.id);
    saveFavs(FAVS);
    e.currentTarget.classList.toggle("on", FAVS.has(p.id));
    renderPresetChips();
  });
  return b;
}

function renderPresetChips() {
  const box = $("#presetChips");
  if (!box || !S.catalog) return;
  const cats = (S.catalog.presets || []).map((g) => g.category);
  const total = allPresets().filter((p) => showAllPresets || p.refined !== false).length;
  const opts = [["todos", "Todos", total]];
  if (FAVS.size) opts.push(["favoritos", "Favoritos", FAVS.size]);
  for (const g of (S.catalog.presets || [])) {
    const n = g.presets.filter((p) => showAllPresets || p.refined !== false).length;
    if (n) opts.push([g.category, g.category, n]);
  }
  if (!cats.includes(presetCat) && presetCat !== "todos" && presetCat !== "favoritos")
    presetCat = "todos";

  box.innerHTML = "";
  for (const [id, label, n] of opts) {
    const b = document.createElement("button");
    b.className = "chip" + (presetCat === id ? " on" : "");
    b.innerHTML = `${esc(label)}<span class="n">${n}</span>`;
    b.addEventListener("click", () => {
      presetCat = id;
      renderPresets();
    });
    box.appendChild(b);
  }
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
  const antes = snapshotScene();
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
    toast(msg, false, undoAction(antes));
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------------------------------------------------------- tocando agora */

/** Alem do nome da cena, traz os controles que a pessoa mais quer mexer logo
 *  depois de aplicar um efeito: velocidade, paleta e cor da primeira camada.
 *  Antes isso exigia ir ate a aba Avancado e selecionar a camada. */
function renderNowPlaying() {
  const box = $("#nowPlaying");
  if (!box) return;
  // o estado chega a cada 1,5 s; remontar por baixo de quem esta arrastando
  // um slider ou com o seletor de cor aberto aqui cortaria o gesto no meio
  const foco = document.activeElement;
  if (foco && box.contains(foco) && typing(foco)) return;
  const st = S.state || {};
  const p = presetById(st.last_preset);
  const layers = st.layers || [];
  if (!layers.length) {
    box.innerHTML = `<p class="muted center" style="padding:12px 0">Nada tocando.</p>`;
    return;
  }
  box.innerHTML =
    `<div class="np-name">${esc(p ? p.name : "Cena personalizada")}</div>` +
    `<div class="np-desc">${esc(p ? p.description : "Montada na aba Avancado.")}</div>`;

  const acts = document.createElement("div");
  acts.className = "np-actions";
  const edit = document.createElement("button");
  edit.className = "btn sm";
  edit.textContent = "Editar na aba Avancado";
  edit.addEventListener("click", () => {
    const first = layers[layers.length - 1];
    if (first) S.selected = first.id;
    showTab("scene");
    renderLayers();
    renderParams();
  });
  acts.appendChild(edit);
  box.appendChild(acts);

  const visiveis = [...layers].reverse().slice(0, 3);
  for (const L of visiveis) {
    const d = effectDef(L.effect);
    if (!d) continue;
    const wrap = document.createElement("div");
    wrap.className = "np-layer";
    const head = document.createElement("div");
    head.className = "np-head";
    head.innerHTML = `<b>${esc(L.name || d.label)}</b><span>${esc(d.label)}</span>` +
      (L.enabled ? "" : `<span class="np-off">desligada</span>`);
    wrap.appendChild(head);

    const quick = d.params.filter((q) => ["speed", "palette", "color", "intensity"]
      .includes(q.name)).slice(0, 3);
    for (const q of quick) {
      const el = paramControl(q, L, (v) => {
        Object.assign(L.params, { [q.name]: v });
        API.post("/api/layer/update", { id: L.id, patch: { params: { [q.name]: v } } })
          .catch(() => {});
      }, true);
      if (el) wrap.appendChild(el);
    }
    if (!quick.length) {
      const none = document.createElement("p");
      none.className = "hint";
      none.style.margin = "0";
      none.textContent = "Sem ajuste rapido; abra a aba Avancado para os parametros.";
      wrap.appendChild(none);
    }
    box.appendChild(wrap);
  }
  if (layers.length > visiveis.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = `Mais ${layers.length - visiveis.length} camada(s) na aba Avancado.`;
    box.appendChild(p);
  }
}

/* ----------------------------------------------------- aviso de instalacao */

function renderSetupBanner(force) {
  const box = $("#setupBanner");
  if (!box) return;
  // nao apagar a contagem que a pessoa esta digitando: sem isso o proximo
  // estado, 1,5 s depois, remontava a linha e o campo voltava vazio
  const foco = document.activeElement;
  if (!force && foco && box.contains(foco) && typing(foco)) return;
  const st = S.state || {};
  const todo = st.setup_todo || [];
  const leds = (st.canvas && st.canvas.led_count) || 0;
  const resizable = st.zones_resizable || [];

  if (st.connecting && !st.connected) {
    box.innerHTML = `
      <div class="setup info">
        <div class="head-row">
          <h3>Conectando ao OpenRGB</h3>
          <span class="spin"></span>
        </div>
        <p>Subindo o servidor e detectando o hardware. Na primeira vez isso
        pode levar alguns segundos.</p>
      </div>`;
    return;
  }

  if (!st.connected) {
    box.innerHTML = `
      <div class="setup err">
        <div class="head-row">
          <h3>Sem conexao com o OpenRGB</h3>
          <button class="btn sm" id="bannerReconnect">Tentar de novo</button>
        </div>
        <p>${esc(st.status || "o servidor do OpenRGB nao respondeu")}.
        O Spectra usa o OpenRGB so como camada de hardware: sem ele no ar,
        nenhum LED e alcancado. Baixe em <code>openrgb.org</code> e deixe
        instalado em <code>C:\\Program Files</code> que o Spectra sobe sozinho.</p>
      </div>`;
    const b = $("#bannerReconnect");
    if (b) b.addEventListener("click", async () => {
      b.classList.add("busy");
      try { await API.post("/api/reconnect"); } catch (e) { toast(e.message, true); }
      b.classList.remove("busy");
      refreshState();
    });
    return;
  }

  if (!todo.length) {
    if (!leds) {
      box.innerHTML = `
        <div class="setup">
          <h3>Nenhum LED controlavel</h3>
          <p>O Spectra conectou no OpenRGB, mas nao ha LEDs ativos. Confira a aba
          <b>Hardware</b>: pode ser que todos os dispositivos estejam desligados
          do controle, ou que nenhum tenha modo Direct.</p>
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
      para voce — ele acende trechos e pergunta o que voce ve, achando o
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
                row.querySelector(".nm").textContent.split("·")[0].trim()));
    const aplicar = async (btn) => {
      const n = parseInt(inp.value, 10);
      if (!(n > 0)) return toast("Digite quantos LEDs esse conector tem", true);
      btn.classList.add("busy");
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
      btn.classList.remove("busy");
      await refreshState();
      renderSetupBanner(true);
      renderPresets();
    };
    row.querySelector(".apply").addEventListener("click", (e) => aplicar(e.currentTarget));
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") aplicar(row.querySelector(".apply"));
    });
  });
}
