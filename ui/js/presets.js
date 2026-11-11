"use strict";

const NEED_LABEL = { audio: "audio", screen: "tela", sensors: "sensores" };

let showAllPresets = false;
let presetCat = "todos";

// Favoritos e inventario moram na configuracao do app. No navegador eles
// sumiam a cada reinicio: a janela roda em modo privado, que apaga o
// armazenamento ao fechar. As chaves antigas so servem para migrar.
const FAV_KEY = "spectra.favoritos";
const INV_KEY = "spectra.inventory";

let FAVS = new Set();

function saveFavs(set) {
  const ids = [...set];
  orderedPost("favorites", "/api/favoritos", { ids })
    .then((r) => { if (S.state) S.state.favoritos = r.favoritos || ids; })
    .catch((e) => toast(e.message, true));
}

/** Leva para a configuracao o que ficou no armazenamento do navegador, de
 *  quem usava o modo --browser ou uma versao anterior. */
async function migraArmazenamentoAntigo() {
  const st = S.state || {};
  let favs = null, inv = null;
  try { favs = JSON.parse(localStorage.getItem(FAV_KEY) || "null"); } catch (e) {}
  try { inv = JSON.parse(localStorage.getItem(INV_KEY) || "null"); } catch (e) {}
  let ok = true;
  if (Array.isArray(favs) && favs.length && !(st.favoritos || []).length) {
    try {
      const r = await API.post("/api/favoritos", { ids: favs });
      FAVS = new Set(r.favoritos || []);
    } catch (e) { ok = false; }
  }
  if (Array.isArray(inv) && inv.length && !Array.isArray(st.inventario)) {
    try { await API.post("/api/inventario", { itens: inv }); } catch (e) { ok = false; }
  }
  if (ok) {
    try { localStorage.removeItem(FAV_KEY); localStorage.removeItem(INV_KEY); } catch (e) {}
  }
}

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
    b.setAttribute("aria-label", `Aplicar cor ${c}`);
    b.addEventListener("click", () => applySolid(c, snapshotScene()));
    box.appendChild(b);
  }
  // O retrato da cena sai no primeiro passo do arrasto e vale ate o seletor
  // fechar. Tirado a cada passo, o Desfazer voltava para a cor anterior do
  // proprio arrasto, e nao para o efeito que estava antes.
  let antesDoArrasto = null;
  $("#quickColor").addEventListener("input", (e) => {
    if (!antesDoArrasto) antesDoArrasto = snapshotScene();
    applySolidSoon(e.target.value);
  });
  $("#quickColor").addEventListener("change", (e) => {
    if (_solidSoon) _solidSoon.cancel();
    const antes = antesDoArrasto;
    antesDoArrasto = null;
    applySolid(e.target.value, antes || snapshotScene());
  });
  $("#btnShuffle").addEventListener("click", () => {
    const pool = allPresets().filter(
      (p) => (showAllPresets || p.refined !== false) && presetDisponivel(p));
    if (!pool.length) return;
    applyPreset(pool[Math.floor(Math.random() * pool.length)].id);
  });
}

function avisoPausado() {
  return S.state && S.state.settings && S.state.settings.paused
    ? " (efeitos pausados: Retomar no topo)" : "";
}

/** Troca a cena inteira por uma cor chapada. E o caso de uso mais comum de
 *  todos, e antes exigia montar uma camada na aba Avancado. Sem `antes`,
 *  e um passo do arrasto do seletor: aplica calado, sem aviso. */
async function applySolid(hex, antes) {
  $("#quickColor").value = hex;
  const calado = antes === undefined;
  try {
    await orderedPost("scene", "/api/layers", {
      preset: null,
      layers: [{ effect: "static", params: { color: hex, intensity: 1.0 },
                 blend: "normal", opacity: 1.0, enabled: true, name: "Cor unica" }],
    });
    S.selected = null;
    await refreshState();
    renderParams();
    renderNowPlaying();
    markActivePreset();
    if (!calado) toast(`Cor ${hex} aplicada${avisoPausado()}`, false, undoAction(antes));
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

/** Retrato da cena para o desfazer. `comAjustes` inclui brilho e afins,
 *  que carregar um perfil tambem troca. */
function snapshotScene(comAjustes) {
  const st = S.state || {};
  const s = st.settings || {};
  return {
    layers: JSON.parse(JSON.stringify(st.layers || [])),
    preset: st.last_preset || null,
    perfil: st.perfil_atual || null,
    ajustes: comAjustes ? { brightness: s.brightness, gamma: s.gamma,
                            fps: s.fps, smoothing: s.smoothing } : null,
  };
}

function undoAction(antes) {
  if (!antes) return null;
  return {
    label: "Desfazer",
    run: async () => {
      try {
        if (_solidSoon) _solidSoon.cancel();
        await orderedPost("scene", "/api/layers", { layers: antes.layers, preset: antes.preset,
                                        perfil: antes.perfil });
        if (antes.ajustes) await orderedPost("settings", "/api/settings", antes.ajustes);
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

/** Leituras de sensor que a maquina entrega, ou null enquanto nao se sabe. */
function sensoresPossiveis() {
  const s = (S.state && S.state.sources && S.state.sources.sensors) || {};
  if (s.running && s.available && s.available.length) return new Set(s.available);
  if (s.lhm === false || s.dll_present === false) return new Set(["cpu_load", "ram_load"]);
  return null;
}

/** O que o preset pede de sensor e a maquina nao mede. */
function sensoresFaltando(p) {
  const pos = sensoresPossiveis();
  return pos ? (p.sensores || []).filter((k) => !pos.has(k)) : [];
}

function presetDisponivel(p) {
  if (!p.needs.length) return true;
  const s = (S.state && S.state.sources) || {};
  return p.needs.every((n) => !(s[n] && s[n].error && !s[n].running)) &&
         !sensoresFaltando(p).length;
}

function renderPresets(filter) {
  const box = $("#presetGrid");
  if (!box || !S.catalog) return;
  const q = semAcento(filter !== undefined ? filter : ($("#presetSearch").value || "")).trim();
  // com texto na busca vale a vitrine inteira: presa ao chip marcado, a busca
  // por "fogo" com Cabo selecionado dizia que nada existia
  const cat = q ? "todos" : presetCat;
  renderPresetChips(cat);
  box.innerHTML = "";

  let mostrados = 0;
  const grupos = cat === "favoritos"
    ? [{ category: "Favoritos", presets: allPresets().filter((p) => FAVS.has(p.id)) }]
    : (S.catalog.presets || []).filter(
        (g) => cat === "todos" || g.category === cat);

  for (const g of grupos) {
    const items = g.presets.filter(
      (p) => (showAllPresets || p.refined !== false || FAVS.has(p.id)) &&
             (!q || semAcento(p.name).includes(q) ||
              semAcento(p.description).includes(q) ||
              semAcento(g.category).includes(q)));
    if (!items.length) continue;

    const t = document.createElement("div");
    t.className = "cat-title";
    t.innerHTML = `${esc(g.category)}<span class="n">${items.length}</span>`;
    box.appendChild(t);

    const grid = document.createElement("div");
    grid.className = "preset-grid";
    for (const p of items) {
      mostrados++;
      grid.appendChild(presetCard(p, presetDisponivel(p)));
    }
    box.appendChild(grid);
  }

  if (!mostrados) {
    box.innerHTML = cat === "favoritos"
      ? `<p class="muted center" style="padding:30px">Nenhum favorito ainda. Passe o mouse
         num efeito e clique na estrela.</p>`
      : `<p class="muted center" style="padding:30px">Nenhum efeito para ${q ? `“${esc(filter !== undefined ? filter : $("#presetSearch").value)}”` : "esta categoria"}. Tente outro nome ou categoria.</p>`;
  }
  const count = $("#presetCount");
  if (count) count.textContent = `${mostrados} ${mostrados === 1 ? "cena" : "cenas"}`;

  const escondidos = allPresets().filter((p) => p.refined === false && !FAVS.has(p.id)).length;
  if (escondidos && cat !== "favoritos") {
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
  const b = document.createElement("div");
  b.className = "preset";
  b.dataset.preset = p.id;
  const cols = p.swatch.concat(p.swatch[0]).join(",");
  // efeito de temperatura numa maquina sem como medi-la fica azul parado:
  // o selo avisa antes do clique
  const falta = sensoresFaltando(p);
  const semTemp = falta.some((k) => k === "cpu_temp" || k === "gpu_temp");
  const badge = falta.length
    ? `<span class="badge falta">${semTemp ? "sem temperatura" : "sem sensor"}</span>`
    : p.needs.length
    ? `<span class="badge">usa ${p.needs.map((n) => NEED_LABEL[n] || n).join(" + ")}</span>`
    : (p.refined === false ? `<span class="badge forte">intenso</span>` : "");
  b.innerHTML =
    `<button class="preset-apply" type="button" aria-label="Aplicar ${esc(p.name)}" aria-pressed="false">` +
    `<div class="swatch" style="--sw:linear-gradient(90deg,${cols})"></div>` +
    badge +
    `<span class="playing" hidden>tocando</span>` +
    `<div class="body"><div class="t">${esc(p.name)}</div>` +
    `<div class="d">${esc(p.description)}</div></div></button>` +
    `<button type="button" class="fav${FAVS.has(p.id) ? " on" : ""}" title="${FAVS.has(p.id) ? "Remover dos favoritos" : "Favoritar"}" aria-label="Favoritar ${esc(p.name)}" aria-pressed="${FAVS.has(p.id)}">${ICON_STAR}</button>`;
  if (falta.length) b.title = "Esta maquina nao mede o que este efeito usa: veja a aba Fontes";
  else if (!disponivel) b.title = "A fonte que este efeito usa esta indisponivel agora";
  b.querySelector(".preset-apply").addEventListener("click", () => applyPreset(p.id));
  b.querySelector(".fav").addEventListener("click", (e) => {
    e.stopPropagation();
    FAVS.has(p.id) ? FAVS.delete(p.id) : FAVS.add(p.id);
    saveFavs(FAVS);
    e.currentTarget.classList.toggle("on", FAVS.has(p.id));
    e.currentTarget.setAttribute("aria-pressed", String(FAVS.has(p.id)));
    e.currentTarget.title = FAVS.has(p.id) ? "Remover dos favoritos" : "Favoritar";
    if (presetCat === "favoritos" && !$("#presetSearch").value.trim()) {
      renderPresets();
      $("#presetGrid .fav, #presetChips .chip")?.focus();
      return;
    }
    renderPresetChips();
  });
  return b;
}

function renderPresetChips(marcado) {
  const box = $("#presetChips");
  if (!box || !S.catalog) return;
  const cats = (S.catalog.presets || []).map((g) => g.category);
  const total = allPresets().filter((p) => showAllPresets || p.refined !== false || FAVS.has(p.id)).length;
  const opts = [["todos", "Todos", total]];
  if (FAVS.size || presetCat === "favoritos") opts.push(["favoritos", "Favoritos", FAVS.size]);
  for (const g of (S.catalog.presets || [])) {
    const n = g.presets.filter((p) => showAllPresets || p.refined !== false || FAVS.has(p.id)).length;
    if (n) opts.push([g.category, g.category, n]);
  }
  if (!cats.includes(presetCat) && presetCat !== "todos" && presetCat !== "favoritos")
    presetCat = "todos";
  const on = marcado || presetCat;

  box.innerHTML = "";
  for (const [id, label, n] of opts) {
    const b = document.createElement("button");
    b.className = "chip" + (on === id ? " on" : "");
    b.dataset.category = id;
    b.setAttribute("aria-pressed", String(on === id));
    b.innerHTML = `${esc(label)}<span class="n">${n}</span>`;
    b.addEventListener("click", () => {
      presetCat = id;
      // escolher categoria e deixar a busca de lado
      $("#presetSearch").value = "";
      renderPresets();
      $$("#presetChips .chip").find((chip) => chip.dataset.category === id)?.focus();
    });
    box.appendChild(b);
  }
}

function markActivePreset() {
  const cur = S.state && S.state.last_preset;
  $$(".preset").forEach((el) => {
    const on = el.dataset.preset === cur;
    el.classList.toggle("on", on);
    el.querySelector(".preset-apply")?.setAttribute("aria-pressed", String(on));
    const tag = el.querySelector(".playing");
    if (tag) tag.hidden = !on;
  });
}

async function applyPreset(id) {
  if (_solidSoon) _solidSoon.cancel();
  const antes = snapshotScene();
  try {
    const r = await orderedPost("scene", "/api/preset/apply", { id });
    if (!r.ok) return toast(r.error || "falhou ao aplicar", true);
    S.selected = null;
    await refreshState();
    renderParams();
    markActivePreset();
    renderNowPlaying();
    const p = presetById(id);
    const nome = p ? p.name : "Preset";
    // a fonte que nao abriu vira erro na hora; antes o aviso dizia "ligando
    // tela" e o gabinete ficava parado sem explicacao
    if (r.falhou && r.falhou.length)
      return toast(`${nome} aplicado, mas ${r.falhou[0]}`, true, undoAction(antes));
    let msg = `${nome} aplicado`;
    if (r.needs && r.needs.length)
      msg += ` — usando ${r.needs.map((n) => NEED_LABEL[n] || n).join(" + ")}`;
    toast(msg + avisoPausado(), false, undoAction(antes));
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
  const layers = st.layers || [];
  if (!layers.length) {
    box.innerHTML = `<p class="muted center" style="padding:12px 0">Nada tocando.</p>`;
    return;
  }
  const cena = descreveCena(st, layers);
  box.innerHTML =
    `<div class="np-name">${esc(cena.nome)}</div>` +
    `<div class="np-desc">${esc(cena.desc)}</div>`;

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
    const aviso = avisoDaCamada(L);
    if (aviso) {
      const w = document.createElement("p");
      w.className = "src-err";
      w.style.margin = "0 0 6px";
      w.textContent = `${aviso[0].toUpperCase()}${aviso.slice(1)}.`;
      wrap.appendChild(w);
    }

    const quick = d.params.filter((q) => ["speed", "palette", "color", "intensity"]
      .includes(q.name)).slice(0, 3);
    for (const q of quick) {
      const el = paramControl(q, L, (v) => {
        patchLayerSoon({ params: { [q.name]: v } }, L.id);
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

/** Nome e descricao do que esta no ar. Perfil carregado e cor unica diziam
 *  "Cena personalizada, montada na aba Avancado", coisa que a pessoa nao fez,
 *  e o preset de antes seguia no painel depois de carregar um perfil. */
function descreveCena(st, layers) {
  if (st.perfil_atual)
    return { nome: `Perfil ${st.perfil_atual}`, desc: "Carregado da aba Perfis." };
  const p = presetById(st.last_preset);
  if (p) return { nome: p.name, desc: p.description };
  const L = layers[0];
  if (layers.length === 1 && L.effect === "static" && L.name === "Cor unica")
    return { nome: "Cor unica", desc: `Todos os LEDs em ${(L.params || {}).color || "uma cor so"}.` };
  return { nome: "Cena personalizada", desc: "Montada na aba Avancado." };
}

/* ------------------------------------------------ aviso de concorrentes */

// O que o fechamento automatico derrubou na abertura. Sem isto a pessoa
// descobria sozinha que o NZXT CAM ou o iCUE tinham sumido: o status dizia
// "fechei" por um instante e logo virava "conectado".
let avisoExclusivoVisto = null;
function renderAvisoExclusivo() {
  const box = $("#avisoExclusivo");
  if (!box) return;
  const ex = (S.state && S.state.exclusive) || null;
  const nomes = (lista) => [...new Set((lista || []).map((c) => c.rotulo))];
  const fechados = nomes(ex && ex.fechados), falhou = nomes(ex && ex.falhou);
  const chave = JSON.stringify([fechados, falhou]);
  if (!ex || !ex.ao_iniciar || (!fechados.length && !falhou.length) ||
      avisoExclusivoVisto === chave) {
    box.innerHTML = "";
    delete box.dataset.k;
    return;
  }
  if (box.dataset.k === chave) return;
  box.dataset.k = chave;
  const partes = [];
  if (fechados.length)
    partes.push(`Fechei ${esc(listaNomes(fechados))} ao iniciar, para nao disputarem
      os LEDs com o Spectra.`);
  if (falhou.length)
    partes.push(`Nao consegui fechar ${esc(listaNomes(falhou))}: roda como servico ou
      com mais privilegio. Se o gabinete piscar, feche pelo proprio programa.`);
  box.innerHTML = `
    <div class="setup info">
      <div class="head-row">
        <h3>Programas de RGB fechados</h3>
        <button class="btn sm" data-a="nunca">Nao fechar mais</button>
        <button class="btn sm ghost" data-a="ok">Ok</button>
      </div>
      <p>${partes.join(" ")} Eles podem cuidar tambem da curva dos fans: a chave
      fica na aba Ajustes.</p>
    </div>`;
  box.querySelector('[data-a="ok"]').addEventListener("click", () => {
    avisoExclusivoVisto = chave;
    renderAvisoExclusivo();
  });
  box.querySelector('[data-a="nunca"]').addEventListener("click", async () => {
    avisoExclusivoVisto = chave;
    renderAvisoExclusivo();
    try {
      await API.post("/api/settings", { exclusive_mode: false });
      toast("O Spectra nao fecha mais outros programas ao iniciar");
    } catch (e) { toast(e.message, true); }
  });
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
    renderSemConexao(box, st);
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
    // Tudo configurado nao e aviso: a faixa verde de todo dia empurrava a
    // vitrine para baixo. Conferir a contagem mora na aba Hardware.
    box.innerHTML = "";
    return;
  }

  const nomes = todo.map((z) => `<b>${esc(z.zone_name)}</b>`).join(", ");

  // O aviso da RAM so quando ela esta mesmo de fora, e apontando para o
  // Corrigir da aba Hardware: o script que ele mandava rodar nao vem no
  // app instalado.
  const e = st.elevacao || {};
  const ramDeFora = e.servidor_elevado === false ||
    (e.servidor_elevado === true && !e.dram && !e.pawnio);

  // Sem chute de contagem aqui: os numeros prontos acertavam por sorte, e
  // o que passa da conta fica aceso numa cor que ninguem escolheu.
  box.innerHTML = `
    <div class="setup">
      <div class="head-row">
        <h3>Falta dizer quantos LEDs voce tem</h3>
        <button class="btn primary sm" id="startWizard">Configurar LEDs</button>
      </div>
      <p>Sem contagem ainda: ${nomes}. Nada acende ${todo.length > 1 ? "neles" : "nele"} ate isso. O padrao
      ARGB e mao unica, a fita nunca diz quantos LEDs tem. Em <b>Configurar
      LEDs</b> voce clica nos LEDs de uma regua e ve no gabinete o que acende,
      conector por conector e peca por peca.</p>
      ${ramDeFora ? `<p class="note">Faltando RAM, water cooler ou GPU na lista?
      Veja o aviso na aba Hardware. <button class="btn sm ghost" id="bannerHardware">Abrir
      Hardware</button></p>` : ""}
    </div>`;

  const wz = $("#startWizard");
  if (wz) wz.addEventListener("click", () => startWizard(todo));
  const hw = $("#bannerHardware");
  if (hw) hw.addEventListener("click", () => showTab("devices"));
}

/** O aviso de sem conexao, com a acao que resolve o motivo de verdade. O
 *  texto antigo mandava instalar em Program Files "que o Spectra sobe
 *  sozinho" mesmo com a partida automatica desligada, e mostrava o erro cru
 *  do Windows. */
function renderSemConexao(box, st) {
  const motivo = st.motivo_conexao || "recusada";
  // remontar a cada estado apagaria o caminho que a pessoa esta digitando
  if (box.dataset.motivo === motivo && box.querySelector(".setup.err")) return;
  const textos = {
    nao_instalado: st.platform === "linux"
      ? `O OpenRGB nao foi encontrado. Instale o OpenRGB e coloque-o no PATH,
         ou informe abaixo o caminho do executavel ou AppImage.`
      : `O OpenRGB nao foi encontrado nesta maquina. Instale pelo
      <code>openrgb.org</code> em <code>C:\\Program Files</code>, ou diga abaixo
      onde esta o <code>OpenRGB.exe</code>, se usa a versao portatil.`,
    partida_desligada: `O servidor do OpenRGB nao esta no ar, e a partida
      automatica esta desligada na aba Ajustes. Abra o OpenRGB com o SDK Server
      ligado, ou deixe o Spectra subir ele.`,
    sem_resposta: `O OpenRGB foi aberto, mas o servidor nao respondeu na porta
      6742 a tempo. Confira se o SDK Server esta ligado nas configuracoes do
      OpenRGB e tente de novo.`,
    servidor_fechado: `O OpenRGB foi fechado. O Spectra nao reabre ele sozinho;
      clique em Tentar de novo para subir o servidor.`,
    falha_partida: `Nao consegui abrir o OpenRGB.`,
    recusada: `O servidor do OpenRGB nao aceitou a conexao. Confira se o SDK
      Server esta ligado nas configuracoes do OpenRGB, na porta 6742.`,
  };
  box.dataset.motivo = motivo;
  box.innerHTML = `
    <div class="setup err">
      <div class="head-row">
        <h3>Sem conexao com o OpenRGB</h3>
        ${motivo === "partida_desligada"
          ? `<button class="btn sm primary" id="bannerAutostart">Ligar partida automatica</button>` : ""}
        <button class="btn sm" id="bannerReconnect">Tentar de novo</button>
      </div>
      <p>${textos[motivo] || textos.recusada} O Spectra usa o OpenRGB so como
      camada de hardware: sem ele no ar, nenhum LED e alcancado.</p>
      ${motivo === "nao_instalado" ? `
      <div class="row">
        <input type="text" id="bannerExe" placeholder="${st.platform === "linux" ? "/usr/bin/openrgb" : "C:\\Programas\\OpenRGB\\OpenRGB.exe"}">
        <button class="btn sm" id="bannerUsarExe">Usar este</button>
      </div>` : ""}
      ${st.erro_conexao ? `<p class="note">Detalhe: ${esc(st.erro_conexao)}</p>` : ""}
    </div>`;
  const tentar = $("#bannerReconnect");
  tentar.addEventListener("click", () => reconectar(tentar));
  const auto = $("#bannerAutostart");
  if (auto) auto.addEventListener("click", async () => {
    try {
      await API.post("/api/settings", { autostart_openrgb: true });
    } catch (e) { return toast(e.message, true); }
    reconectar(auto);
  });
  const usar = $("#bannerUsarExe");
  if (usar) usar.addEventListener("click", async () => {
    try {
      await API.post("/api/openrgb/exe", { path: $("#bannerExe").value });
    } catch (e) { return toast(e.message, true); }
    toast("Caminho do OpenRGB guardado");
    reconectar(usar);
  });
}
