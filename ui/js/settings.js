"use strict";

// Aba Ajustes: saida (gama, fps, suavizacao), comportamento (exclusividade,
// OpenRGB automatico) e informacoes do app. Tudo aqui ja existia no backend;
// so nao tinha lugar na interface.

const FPS_OPTIONS = [30, 45, 60, 90, 120].map((v) => ({ value: String(v), label: v + " fps" }));

function renderSettings() {
  const box = $("#settingsBody");
  if (!box) return;
  const st = S.state || {};
  const cfg = st.settings || {};
  box.innerHTML = "";

  const out = panel("Saida para o hardware");
  out.appendChild(sliderField("Gama", cfg.gamma ?? 2.2, 1.0, 3.0, 0.05,
    throttle((v) => API.post("/api/settings", { gamma: v }), 80),
    (v) => (+v).toFixed(2)));
  out.appendChild(hintEl("LED responde quase linear a corrente: sem gama, meio brilho parece " +
    "claro demais. 2.2 e o padrao; suba se os tons escuros ficarem lavados."));
  out.appendChild(field("Taxa de quadros", selectEl(FPS_OPTIONS, String(cfg.fps ?? 60), (v) => {
    API.post("/api/settings", { fps: parseInt(v, 10) }).then(() => toast(`Render a ${v} fps`));
  })));
  out.appendChild(sliderField("Suavizacao", cfg.smoothing ?? 0, 0, 0.95, 0.01,
    throttle((v) => API.post("/api/settings", { smoothing: v }), 80),
    (v) => Math.round(v * 100) + "%"));
  out.appendChild(hintEl("Mistura cada quadro com o anterior. Deixa transicoes bruscas mais " +
    "macias; acima de 70% comeca a borrar efeitos rapidos."));
  box.appendChild(out);

  const beh = panel("Comportamento");
  // o aviso usa as palavras da chave: "modo exclusivo" nao aparece na tela
  beh.appendChild(switchEl("Fechar softwares de RGB concorrentes ao iniciar", st.exclusive_mode !== false,
    (v) => API.post("/api/settings", { exclusive_mode: v })
      .then(() => toast(v ? "Os concorrentes serao fechados ao iniciar"
                          : "O Spectra nao fecha mais outros programas ao iniciar"))));
  beh.appendChild(hintEl("iCUE, GIGABYTE Control Center, Mystic Light, L-Connect, SignalRGB e afins. " +
    "Dois programas escrevendo no mesmo controlador e a causa classica de gabinete piscando."));
  beh.appendChild(switchEl("Subir o servidor do OpenRGB sozinho", st.autostart_openrgb !== false,
    (v) => API.post("/api/settings", { autostart_openrgb: v })
      .then(() => toast(v ? "OpenRGB sobe automaticamente" : "OpenRGB nao sera iniciado pelo Spectra"))));
  const acts = document.createElement("div");
  acts.className = "settings-actions";
  const excl = document.createElement("button");
  excl.className = "btn sm";
  excl.textContent = "Fechar concorrentes agora";
  excl.addEventListener("click", async () => {
    excl.classList.add("busy");
    try {
      // vale mesmo com o fechamento automatico desligado: e para quem o
      // desligou e quer fechar na mao quando precisar
      const r = await API.post("/api/exclusive", { forcar: true });
      const nomes = (lista) => listaNomes([...new Set((lista || []).map((c) => c.rotulo))]);
      const fechados = nomes(r.fechados), falhou = nomes(r.falhou);
      if (falhou)
        toast(`${fechados ? `Fechei ${fechados}. ` : ""}Nao consegui fechar ${falhou}: ` +
              "roda como servico, feche pelo proprio programa", true);
      else toast(fechados ? `Fechei ${fechados}` : "Nenhum concorrente rodando");
    } catch (e) { toast(e.message, true); }
    excl.classList.remove("busy");
  });
  acts.appendChild(excl);
  beh.appendChild(acts);
  box.appendChild(beh);

  const about = panel("Sobre");
  const kv = document.createElement("div");
  kv.className = "kv";
  const rows = [
    ["Versao", st.version || "?"],
    ["Protocolo OpenRGB", st.protocol != null ? "v" + st.protocol : "?"],
    ["Conexao", st.connected ? "conectado" : (st.connecting ? "conectando…" : "desconectado")],
    ["Reconexoes", String(st.reconnects ?? 0)],
    ["Ultimo erro de render", st.last_error ? `<span class="err">${esc(st.last_error)}</span>` : "nenhum"],
    ["Configuracao em", st.config_dir ? `<code>${esc(st.config_dir)}</code>` : "?"],
  ];
  kv.innerHTML = rows.map(([k, v]) => `<span>${esc(k)}</span><span>${v}</span>`).join("");
  about.appendChild(kv);
  const bandeja = hintEl("Fechar a janela minimiza para a bandeja e os efeitos continuam. " +
    "Sair de verdade e pelo menu da bandeja; ao sair, os LEDs apagam.");
  bandeja.style.margin = "12px 0 0";
  about.appendChild(bandeja);
  box.appendChild(about);

  const keys = panel("Atalhos de teclado");
  const sc = document.createElement("div");
  sc.className = "shortcuts";
  sc.innerHTML = [
    ["Espaco", "pausar ou retomar os efeitos"],
    ["/", "buscar efeito pronto"],
    ["Ctrl + 1 … 7", "trocar de aba"],
    ["Esc", "fechar o seletor de efeitos"],
    ["Setas", "mover a zona selecionada no Layout (Shift move mais)"],
    ["Enter", "no seletor de efeitos, escolhe o primeiro da busca"],
  ].map(([k, v]) => `<kbd>${esc(k)}</kbd><span>${esc(v)}</span>`).join("");
  keys.appendChild(sc);
  box.appendChild(keys);
}

function panel(title) {
  const p = document.createElement("div");
  p.className = "panel";
  p.innerHTML = `<div class="panel-head"><h2>${esc(title)}</h2></div>`;
  return p;
}

function hintEl(text) {
  const p = document.createElement("p");
  p.className = "hint";
  p.style.margin = "-4px 0 12px";
  p.textContent = text;
  return p;
}
