"use strict";

/* Configurar LEDs: uma regua clicavel por conector ARGB.
 *
 * Conector ARGB e mao unica, a fita nunca diz quantos LEDs tem. A regua
 * acende no gabinete o que a pessoa clica: do 1 ate o LED escolhido em
 * verde e o resto do conector em vermelho. Vermelho aparecendo quer dizer
 * que ainda tem LED depois. A mesma regua marca onde cada peca termina,
 * para saber quantos LEDs cada fan, fita ou placa tem.
 */

// ---- regua: funcoes puras, testadas em tests/test_frontend.js ----

const CAL_VERDE = "00ff3c";
const CAL_VERMELHO = "ff0000";
const CAL_BRANCO = "ffffff";
const CAL_SOBRA = "303030";
const CAL_APAGADO = "000000";
const CAL_CORES_PECAS = ["ff2d55", "00b4ff", "8cff00", "ffb000", "aa5aff", "00ffc8"];

/** Contagem do conector depois de o cursor andar. No "ate", o que fica
 *  verde e o que vai ser salvo; nos outros modos o cursor so aponta. Com
 *  um botao a parte para gravar a contagem, clicar no LED e salvar nao
 *  gravava nada. */
function contagemDoCursor(modo, cursor, contagem) {
  return modo === "ate" ? cursor : contagem;
}

/** Fim de cada peca, contado do primeiro LED do conector. */
function fimDasPecas(pecas) {
  let acc = 0;
  return pecas.map((p) => (acc += p.count));
}

/** Indice da peca que contem o LED, ou -1 quando ele nao tem peca. */
function pecaDoLed(pecas, led) {
  const fins = fimDasPecas(pecas);
  return fins.findIndex((fim) => led <= fim);
}

/** Cores de cada LED do conector, em hexadecimal corrido.
 *
 * "ate": do 1 ao cursor em verde, o cursor em branco e o resto em vermelho.
 * "so": so o LED do cursor, em branco.
 * "pecas": cada peca numa cor, LED sem peca em cinza e o que passa da
 * contagem em vermelho. */
function coresDaRegua(modo, cursor, max, contagem, pecas) {
  const out = new Array(max).fill(CAL_APAGADO);
  if (modo === "so") {
    if (cursor >= 1 && cursor <= max) out[cursor - 1] = CAL_BRANCO;
  } else if (modo === "pecas") {
    let ini = 0;
    pecas.forEach((p, i) => {
      for (let k = ini; k < Math.min(ini + p.count, max); k++)
        out[k] = CAL_CORES_PECAS[i % CAL_CORES_PECAS.length];
      ini += p.count;
    });
    for (let k = ini; k < max; k++) out[k] = k < contagem ? CAL_SOBRA : CAL_VERMELHO;
  } else {
    for (let k = 0; k < max; k++) out[k] = k < cursor ? CAL_VERDE : CAL_VERMELHO;
    if (cursor >= 1 && cursor <= max) out[cursor - 1] = CAL_BRANCO;
  }
  return out.join("");
}

/** Marca o fim de uma peca no LED do cursor.
 *
 * Dentro de uma peca, ela se divide em duas no cursor. Depois da ultima,
 * nasce uma peca nova do fim dela ate o cursor. */
function marcarFim(pecas, cursor) {
  if (cursor < 1) return pecas;
  const fins = fimDasPecas(pecas);
  if (fins.includes(cursor)) return pecas;
  const total = fins.length ? fins[fins.length - 1] : 0;
  if (cursor > total) return [...pecas, { count: cursor - total }];
  const i = pecaDoLed(pecas, cursor);
  const ini = i > 0 ? fins[i - 1] : 0;
  return [...pecas.slice(0, i), { count: cursor - ini }, { count: fins[i] - cursor },
          ...pecas.slice(i + 1)];
}

/** Tira o fim da peca `i`: ela se junta com a seguinte, e a ultima some. */
function tirarFim(pecas, i) {
  if (i < 0 || i >= pecas.length) return pecas;
  if (i === pecas.length - 1) return pecas.slice(0, -1);
  return [...pecas.slice(0, i), { count: pecas[i].count + pecas[i + 1].count },
          ...pecas.slice(i + 2)];
}

/** Corta as pecas na contagem do conector; o que passa dela deixa de existir. */
function cortarPecas(pecas, contagem) {
  const out = [];
  let acc = 0;
  for (const p of pecas) {
    if (acc >= contagem) break;
    const c = Math.min(p.count, contagem - acc);
    out.push({ count: c });
    acc += c;
  }
  return out;
}

/** Divisao gravada de um conector, cortada na contagem dele. */
function pecasSalvas(contas, contagem) {
  if (!Array.isArray(contas) || !contagem) return [];
  const pecas = contas.map((n) => ({ count: parseInt(n, 10) || 0 })).filter((p) => p.count > 0);
  return cortarPecas(pecas, contagem);
}

// ---- regua: fim das funcoes puras ----

const CAL = {
  zonas: [],
  atual: 0,
  modo: "ate",
  busy: false,
  aplicado: null,
  pintando: false,
  pendente: null,
  timer: null,
};

const CAL_DICAS = {
  ate: `Clique no ultimo LED que acende. No gabinete, do 1 ate ele fica
    <b>verde</b>, ele mesmo fica <b>branco</b> e o resto do conector fica
    <b>vermelho</b>. Se aparecer vermelho em qualquer lugar, ainda tem LED
    depois. <b>O que fica verde e o que vai ser salvo.</b>`,
  so: `So o LED clicado acende, em <b>branco</b>. Serve para ver onde cada
    numero fica no gabinete. Aqui o cursor nao muda a contagem.`,
  pecas: `Cada peca acende numa cor. Cinza e LED sem peca e <b>vermelho</b> e
    LED depois do ultimo LED do conector. Aqui o cursor nao muda a contagem.`,
};

function zonaAtual() { return CAL.zonas[CAL.atual]; }

/** Pecas que cabem na contagem de agora. A lista inteira fica guardada:
 *  descer o cursor e subir de novo devolve as pecas que tinham saido. */
function pecasValidas(z) { return cortarPecas(z.pecas, z.contagem); }

/** Diz se o mapa salvo da zona e um plano de varias pecas. Ele foi feito
 *  para uma contagem; mudando a contagem, a zona volta ao automatico. */
function temPlanoNoMapa(device, zone) {
  const zi = (S.zones || []).find((x) => x.device_key === device && x.zone_index === zone);
  return !!(zi && zi.geometry && zi.geometry.shape === "multi");
}

/** Abre a configuracao. Com uma lista, comeca no primeiro conector dela. */
async function startWizard(list) {
  if (CAL.busy || !$("#probeModal").hidden) return;
  CAL.busy = true;
  try {
    const r = await API.post("/api/probe/multi/start", { max: 512 });
    if (!r.ok) return toast(r.error || "nao consegui iniciar", true);
    CAL.zonas = r.zones.map((z) => {
      const antes = Math.max(0, Math.min(z.antes || 0, z.max));
      const salvas = ((S.state && S.state.pecas) || {})[`${z.device}:${z.zone}`];
      return {
        device: z.device, zone: z.zone, nome: z.zone_name,
        aparelho: z.device_name, max: Math.max(1, z.max), antes,
        contagem: antes, cursor: antes,
        pecas: pecasSalvas(salvas, antes),
        tinhaPlano: temPlanoNoMapa(z.device, z.zone),
        mexeuPecas: false,
        // conector que a pessoa nem abriu nao vira "vazio" gravado
        respondido: false,
      };
    });
    CAL.atual = 0;
    if (list && list.length) {
      const i = CAL.zonas.findIndex((z) => z.device === list[0].device && z.zone === list[0].zone);
      if (i >= 0) CAL.atual = i;
    }
    CAL.modo = "ate";
    CAL.aplicado = null;
    render();
    openModal("#probeModal", $("#calRegua"));
    pintar();
  } catch (e) {
    toast(e.message, true);
  } finally {
    CAL.busy = false;
  }
}

function openProbe(device, zone) {
  return startWizard([{ device, zone }]);
}

/** Manda para o gabinete o estado da regua. So vai o ultimo pedido: com a
 *  seta segurada, os do meio seriam pintados atrasados um atras do outro. */
function pintar() {
  clearTimeout(CAL.timer);
  CAL.timer = setTimeout(() => {
    const z = zonaAtual();
    if (!z) return;
    CAL.pendente = {
      device: z.device, zone: z.zone,
      cores: coresDaRegua(CAL.modo, z.cursor, z.max, z.contagem, pecasValidas(z)),
    };
    if (!CAL.pintando) enviaPintura();
  }, 30);
}

async function enviaPintura() {
  CAL.pintando = true;
  while (CAL.pendente) {
    const corpo = CAL.pendente;
    CAL.pendente = null;
    try {
      const r = await API.post("/api/probe/pintar", corpo);
      if (!r.ok) toast(r.error || "nao consegui acender", true);
    } catch (e) {
      toast(e.message, true);
    }
  }
  CAL.pintando = false;
}

function mudou() {
  render();
  pintar();
}

function moverCursor(n) {
  const z = zonaAtual();
  const minimo = CAL.modo === "so" ? 1 : 0;
  z.cursor = clamp(Math.round(n), minimo, z.max);
  const nova = contagemDoCursor(CAL.modo, z.cursor, z.contagem);
  if (nova !== z.contagem) {
    z.contagem = nova;
    z.respondido = true;
  }
  mudou();
}

function render() {
  renderConectores();
  renderCorpo();
}

function rotuloConector(z) {
  if (!z.contagem) return "sem LEDs";
  const n = pecasValidas(z).length;
  return n ? `${z.contagem} LEDs · ${n} pecas` : `${z.contagem} LEDs`;
}

function renderConectores() {
  const box = $("#calConectores");
  box.innerHTML = "";
  CAL.zonas.forEach((z, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "cal-con" + (i === CAL.atual ? " on" : "");
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", i === CAL.atual ? "true" : "false");
    b.innerHTML = `<b>${esc(z.nome)}</b><span>${esc(rotuloConector(z))}</span>`;
    b.addEventListener("click", () => {
      if (i === CAL.atual) return;
      CAL.atual = i;
      if (CAL.modo === "ate") zonaAtual().cursor = zonaAtual().contagem;
      if (CAL.modo === "so" && zonaAtual().cursor < 1) zonaAtual().cursor = 1;
      mudou();
      $("#calRegua")?.focus();
    });
    box.appendChild(b);
  });
}

function renderCorpo() {
  const z = zonaAtual();
  const box = $("#probeBody");
  const focoNaRegua = document.activeElement && document.activeElement.id === "calRegua";
  box.innerHTML = "";
  if (!z) return;

  box.insertAdjacentHTML("beforeend", `
    <div class="cal-topo">
      <div class="cal-modos" role="group" aria-label="O que acender">
        ${[["ate", "Ate aqui"], ["so", "So este LED"], ["pecas", "Ver pecas"]].map(([m, t]) =>
          `<button type="button" class="btn sm${CAL.modo === m ? " on" : ""}" data-modo="${m}"
             aria-pressed="${CAL.modo === m}">${t}</button>`).join("")}
      </div>
      <span class="cal-aparelho">${esc(z.aparelho)}</span>
    </div>
    <p class="probe-lead cal-dica">${CAL_DICAS[CAL.modo]}</p>
    <div class="cal-cursor">
      <span class="cal-num">LED <b>${z.cursor}</b> <small>de ${z.max}</small></span>
      <div class="cal-passos">
        <button type="button" class="btn sm" data-d="-10">-10</button>
        <button type="button" class="btn sm" data-d="-1">-1</button>
        <button type="button" class="btn sm" data-d="1">+1</button>
        <button type="button" class="btn sm" data-d="10">+10</button>
      </div>
    </div>`);

  $$("[data-modo]", box).forEach((b) => b.addEventListener("click", () => {
    CAL.modo = b.dataset.modo;
    // voltando ao "ate", o cursor mostra a contagem em vez de troca-la
    if (CAL.modo === "ate") z.cursor = z.contagem;
    if (CAL.modo === "so" && z.cursor < 1) z.cursor = 1;
    mudou();
  }));
  $$(".cal-passos [data-d]", box).forEach((b) =>
    b.addEventListener("click", () => moverCursor(z.cursor + parseInt(b.dataset.d, 10))));

  box.appendChild(regua(z));

  box.insertAdjacentHTML("beforeend", `<div class="cal-legenda">${legenda()}</div>`);

  const acoes = document.createElement("div");
  acoes.className = "cal-acoes";
  acoes.innerHTML = `
    <button type="button" class="btn sm primary" data-a="peca" ${z.cursor < 1 ? "disabled" : ""}>Fim de uma peca no LED ${z.cursor}</button>
    <button type="button" class="btn sm ghost" data-a="vazio">Conector vazio</button>`;
  acoes.addEventListener("click", (e) => {
    const a = e.target.closest("[data-a]");
    if (!a || a.disabled) return;
    z.respondido = true;
    if (a.dataset.a === "peca") {
      z.pecas = marcarFim(z.pecas, z.cursor);
      z.contagem = Math.max(z.contagem, z.cursor);
      z.mexeuPecas = true;
    } else {
      z.contagem = 0;
      z.cursor = 0;
      if (z.pecas.length) z.mexeuPecas = true;
      z.pecas = [];
    }
    mudou();
  });
  box.appendChild(acoes);

  box.appendChild(resumo(z));
  box.appendChild(tabelaPecas(z));

  const barra = document.createElement("div");
  barra.className = "probe-actions";
  barra.innerHTML = `
    <button type="button" class="btn sm" id="calSair">Sair sem salvar</button>
    <button type="button" class="btn primary" id="calSalvar">Salvar tudo</button>`;
  $("#calSair", barra).addEventListener("click", sairDoAssistente);
  $("#calSalvar", barra).addEventListener("click", salvarTudo);
  box.appendChild(barra);

  if (focoNaRegua) $("#calRegua").focus();
}

function regua(z) {
  const fins = new Set(fimDasPecas(pecasValidas(z)));
  const el = document.createElement("div");
  el.id = "calRegua";
  el.className = "cal-regua";
  el.tabIndex = 0;
  el.setAttribute("role", "slider");
  el.setAttribute("aria-label", `LED do conector ${z.nome}`);
  el.setAttribute("aria-valuemin", CAL.modo === "so" ? "1" : "0");
  el.setAttribute("aria-valuemax", String(z.max));
  el.setAttribute("aria-valuenow", String(z.cursor));
  const cores = coresDaRegua(CAL.modo, z.cursor, z.max, z.contagem, pecasValidas(z));
  let html = "";
  for (let led = 1; led <= z.max; led++) {
    const cor = cores.slice((led - 1) * 6, led * 6);
    const cls = ["led"];
    if (led === z.cursor) cls.push("cur");
    if (fins.has(led)) cls.push("fim-peca");
    if (led === z.contagem) cls.push("fim-con");
    if (led > z.contagem) cls.push("alem");
    const marca = led % 10 === 0 || led === 1 ? `<i>${led}</i>` : "";
    // apagado na regua vira o fundo das celulas, senao a grade some no
    // modo de um LED so
    const fundo = cor === CAL_APAGADO ? "var(--line)" : "#" + cor;
    html += `<span class="${cls.join(" ")}" data-led="${led}" style="--c:${fundo}" title="LED ${led}">${marca}</span>`;
  }
  el.innerHTML = html;
  el.addEventListener("click", (e) => {
    const c = e.target.closest("[data-led]");
    if (c) moverCursor(parseInt(c.dataset.led, 10));
  });
  el.addEventListener("keydown", (e) => {
    const passo = e.shiftKey ? 10 : 1;
    const mapa = { ArrowRight: passo, ArrowUp: passo, ArrowLeft: -passo, ArrowDown: -passo };
    if (e.key in mapa) { e.preventDefault(); moverCursor(z.cursor + mapa[e.key]); }
    else if (e.key === "Home") { e.preventDefault(); moverCursor(0); }
    else if (e.key === "End") { e.preventDefault(); moverCursor(z.max); }
  });
  return el;
}

function legenda() {
  const cor = (c, t) => `<span><i class="lg" style="--c:#${c}"></i>${t}</span>`;
  const itens = {
    ate: [cor(CAL_VERDE, "aceso ate o cursor"), cor(CAL_VERMELHO, "depois do cursor")],
    so: [cor(CAL_BRANCO, "o LED do cursor")],
    pecas: [cor(CAL_CORES_PECAS[0], "uma cor por peca"), cor(CAL_SOBRA, "sem peca"),
            cor(CAL_VERMELHO, "depois do ultimo LED")],
  }[CAL.modo];
  return [...itens,
    `<span><i class="lg cur"></i>cursor</span>`,
    `<span><i class="lg fim-peca"></i>fim de peca</span>`,
    `<span><i class="lg fim-con"></i>ultimo LED do conector</span>`].join("");
}

function resumo(z) {
  const el = document.createElement("p");
  el.className = "cal-resumo";
  if (!z.contagem) {
    el.innerHTML = `Este conector esta <b>sem LEDs</b>. Em <b>Ate aqui</b>,
      clique no ultimo LED que acende. Sem nada ligado nele, use
      <b>Conector vazio</b>.`;
    return el;
  }
  const pecas = pecasValidas(z);
  const soma = pecas.reduce((a, p) => a + p.count, 0);
  const contas = pecas.length ? `Pecas: ${pecas.map((p) => p.count).join(" + ")} = ${soma}.` : "";
  const sobra = pecas.length && soma < z.contagem
    ? ` <span class="warn">Sobram ${z.contagem - soma} LEDs sem peca.</span>` : "";
  el.innerHTML = `Conector com <b>${z.contagem} LEDs</b>. ${contas}${sobra}`;
  return el;
}

function tabelaPecas(z) {
  const box = document.createElement("div");
  box.className = "cal-pecas";
  const pecas = pecasValidas(z);
  if (!pecas.length) {
    box.innerHTML = `<p class="hint">Sem pecas marcadas. Para saber quantos LEDs
      cada fan, fita ou placa tem, va ate o ultimo LED de cada uma e clique em
      <b>Fim de uma peca</b>.</p>`;
    return box;
  }
  let ini = 1;
  pecas.forEach((p, i) => {
    const fim = ini + p.count - 1;
    const row = document.createElement("div");
    row.className = "cal-peca";
    row.style.setProperty("--c", "#" + CAL_CORES_PECAS[i % CAL_CORES_PECAS.length]);
    row.innerHTML = `
      <button type="button" class="cal-faixa" title="Levar o cursor ao fim desta peca">
        <i class="dot"></i><span class="nm">Peca ${i + 1}</span>
        <span class="faixa">LEDs ${ini} a ${fim}</span><b>${p.count} LEDs</b></button>
      <button type="button" class="inv-del" title="Juntar com a proxima peca"
        aria-label="Tirar o fim da peca ${i + 1}">&times;</button>`;
    $(".cal-faixa", row).addEventListener("click", () => {
      if (CAL.modo === "so") CAL.modo = "pecas";
      moverCursor(fim);
    });
    $(".inv-del", row).addEventListener("click", () => {
      z.pecas = tirarFim(z.pecas, i);
      z.mexeuPecas = true;
      mudou();
    });
    box.appendChild(row);
    ini = fim + 1;
  });
  return box;
}

function temMudanca() {
  return CAL.zonas.some((z) => z.respondido || z.contagem !== z.antes || z.mexeuPecas);
}

/** Grava tudo em tres fases. Cada fase concluida fica anotada: se uma
 *  falhar, o botao volta como "Tentar de novo" e pula o que ja foi feito. */
async function salvarTudo() {
  if (CAL.busy) return;
  CAL.busy = true;
  const btn = $("#calSalvar");
  if (btn) { btn.disabled = true; btn.textContent = "Salvando…"; }
  const feito = CAL.aplicado || (CAL.aplicado = { contagens: false, fim: false, mapas: new Set() });
  try {
    if (!feito.contagens) {
      for (const z of CAL.zonas) {
        if (!z.respondido && z.contagem === z.antes) continue;
        await API.post("/api/probe/commit", { device: z.device, zone: z.zone, count: z.contagem });
      }
      feito.contagens = true;
    }
    if (!feito.fim) {
      await API.post("/api/probe/finish", {});
      feito.fim = true;
    }
    for (const z of CAL.zonas) {
      const k = `${z.device}:${z.zone}`;
      if (feito.mapas.has(k) || (!z.mexeuPecas && z.contagem === z.antes)) continue;
      await API.post("/api/zone/pecas", {
        device: z.device, zone: z.zone, pecas: pecasValidas(z).map((p) => p.count) });
      // plano de pecas do mapa feito para outra contagem volta ao automatico
      if (z.tinhaPlano && z.contagem !== z.antes)
        await API.post("/api/zone/geometry", { device: z.device, zone: z.zone, geometry: null });
      feito.mapas.add(k);
    }
    CAL.aplicado = null;
    closeModal("#probeModal");
    toast(`Salvo: ${CAL.zonas.map((z) => `${z.nome} = ${z.contagem}`).join(", ")}`);
  } catch (e) {
    const falta = !feito.contagens ? "Nada foi gravado ainda."
      : !feito.fim ? "As contagens foram enviadas, mas nao foram gravadas."
      : "As contagens foram gravadas, mas a divisao em pecas de algum conector nao.";
    toast(`${e.message}. ${falta}`, true);
    if (btn) { btn.disabled = false; btn.textContent = "Tentar de novo"; }
  } finally {
    CAL.busy = false;
  }
  await depoisDeFechar();
}

async function depoisDeFechar() {
  await refreshState();
  renderSetupBanner();
  renderPresets();
  renderNowPlaying();
  if ($("#tab-devices").classList.contains("active")) renderDevices();
  if ($("#tab-layout").classList.contains("active")) drawLayout();
}

async function sairDoAssistente() {
  if (CAL.busy) return;
  const jaGravou = CAL.aplicado && CAL.aplicado.fim;
  if (!jaGravou && temMudanca() &&
      !confirm("Sair sem salvar? O que voce marcou nesta configuracao se perde.")) return;
  CAL.busy = true;
  try {
    if (!jaGravou) await API.post("/api/probe/finish", {});
    closeModal("#probeModal");
  } catch (e) {
    toast(`${e.message} A configuracao continua aberta; tente sair de novo.`, true);
    return;
  } finally {
    CAL.busy = false;
  }
  await depoisDeFechar();
}

document.addEventListener("DOMContentLoaded", () => {
  $("#probeCancel").addEventListener("click", sairDoAssistente);
  $("#probeModal").addEventListener("click", (e) => {
    if (e.target.id === "probeModal") sairDoAssistente();
  });
});
