"""Cenas prontas, cada uma com sua pilha de camadas ja ajustada.

Um preset e o que a pessoa clica na tela inicial. Ele descreve as
camadas, os parametros de cada uma e como elas se compoem, sem exigir
que ninguem monte a cena do zero.

`AGRESSIVOS` marca as cenas que piscam forte, que ficam atras do filtro
de refinados por serem cansativas em uso prolongado.
"""

from __future__ import annotations


def L(effect, params=None, blend="normal", opacity=1.0, name="", targets=None):
    """Monta uma camada de preset, com efeito, parametros e composicao."""
    return {"effect": effect, "params": params or {}, "blend": blend,
            "opacity": opacity, "enabled": True, "name": name or effect,
            "targets": targets or []}


class Preset:
    """Uma cena pronta, com as camadas e os metadados da vitrine."""

    def __init__(self, id, name, category, description, swatch, layers,
                 needs=(), refined=True):
        self.id = id
        self.name = name
        self.category = category
        self.description = description
        self.swatch = swatch
        self.layers = layers
        self.needs = needs
        self.refined = refined

    def to_json(self):
        """Descreve o preset para a grade da tela inicial."""
        return {"id": self.id, "name": self.name, "category": self.category,
                "description": self.description, "swatch": self.swatch,
                "needs": list(self.needs), "layer_count": len(self.layers),
                "refined": self.refined}

    def scene(self):
        """Devolve as camadas no formato que o renderizador carrega."""
        return {"layers": self.layers}


PRESETS = [
    Preset("cabo_cross", "Cross Over", "Cabo",
           "Dois feixes diagonais atravessando o cabo em sentidos opostos e se "
           "cruzando no meio. O efeito que mais mostra a largura da fita.",
           ["#000000", "#ff2d55", "#ffffff", "#00d9ff", "#000000"],
           [L("cb_cross", {"speed": 0.5, "slant": 1.0}, name="Cross over")]),

    Preset("cabo_paralelo", "Paralelo", "Cabo",
           "As laminas acendem uma depois da outra, atravessando a largura do "
           "cabo. Cada lamina com sua cor.",
           ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"],
           [L("cb_parallel", {"speed": 0.35, "duty": 0.3}, name="Paralelo")]),

    Preset("cabo_onda", "Onda no Cabo", "Cabo",
           "Uma onda percorre o comprimento com cada lamina defasada: a crista "
           "atravessa o cabo na diagonal.",
           ["#03045e", "#0077b6", "#48cae4", "#caf0f8"],
           [L("cb_wave", {"speed": 0.4, "freq": 1.5, "lane_phase": 0.5},
              name="Onda")]),

    Preset("cabo_ripple", "Ondulacao no Cabo", "Cabo",
           "Aneis se expandindo de um ponto do cabo, atravessando laminas e "
           "comprimento ao mesmo tempo.",
           ["#000814", "#0055a4", "#8ae1ff", "#ffffff"],
           [L("cb_ripple", {"speed": 0.5, "freq": 3.0}, name="Ondulacao")]),

    Preset("cabo_bullets", "Projeteis", "Cabo",
           "Cada lamina dispara um ponto que corre ate o fim e fica acumulado, "
           "ate a fita encher. Depois esvazia.",
           ["#000000", "#3a86ff", "#00f5d4", "#ffbe0b"],
           [L("cb_bullets", {"speed": 0.9, "stack_time": 6.0},
              name="Projeteis")]),

    Preset("cabo_chuva", "Chuva no Cabo", "Cabo",
           "Gotas caem por laminas diferentes em tempos diferentes, deixando "
           "boa parte do cabo escura.",
           ["#000000", "#001d3d", "#00a6fb", "#caf0f8"],
           [L("cb_drizzle", {"speed": 0.8, "density": 0.5}, name="Chuva")]),

    Preset("cabo_transfer", "Transferencia", "Cabo",
           "A cor passa de uma lamina para a seguinte, como se escorresse pela "
           "largura do cabo.",
           ["#12043a", "#c22e63", "#ff6b35", "#ffc15e"],
           [L("cb_transfer", {"speed": 0.3}, name="Transferencia")]),

    Preset("cabo_disputa", "Disputa", "Cabo",
           "Duas frentes correm das pontas para o centro e recuam, disputando "
           "o territorio do cabo.",
           ["#ff0040", "#ff0040", "#00d4ff", "#00d4ff"],
           [L("cb_contest", {"speed": 0.35}, name="Disputa")]),

    Preset("cabo_lamina", "Lamina a Lamina", "Cabo",
           "Uma lamina inteira acende por vez, correndo pela largura. Bem "
           "marcado, quase um contador.",
           ["#0d0221", "#7b2cbf", "#e0218a", "#00f5d4"],
           [L("cb_lane_chase", {"speed": 3.0, "lit": 1}, name="Lamina")]),

    Preset("cabo_diagonal", "Diagonal", "Cabo",
           "Faixas inclinadas deslizando pelo cabo, com borda dura.",
           ["#2d00f7", "#8900f2", "#f20089", "#01c5c4"],
           [L("cb_diagonal", {"speed": 0.4, "bands": 2.0, "slant": 1.0},
              name="Diagonal")]),

    Preset("cabo_twinkle", "Cintilar 2D", "Cabo",
           "LEDs individuais acendem espalhados pela matriz do cabo, sem "
           "padrao de linha. Cada LED por si.",
           ["#000000", "#ff9ff3", "#48dbfb", "#1dd1a1"],
           [L("cb_twinkle2d", {"rate": 14.0, "density": 0.2},
              name="Cintilar 2D")]),

    Preset("cabo_espiral", "Espiral no Cabo", "Cabo",
           "A cor gira em torno do eixo do cabo enquanto avanca — parece uma "
           "helice percorrendo a fita.",
           ["#0d0887", "#b12a90", "#e16462", "#fca636"],
           [L("cb_spiral", {"speed": 0.5, "turns": 2.0}, name="Espiral")]),

    Preset("cabo_espectro", "Espectro no Cabo", "Cabo",
           "Cada lamina e uma faixa de frequencia e a altura acesa mostra a "
           "intensidade: um analisador de espectro de verdade.",
           ["#30123b", "#4145ab", "#1ddfa3", "#a4fc3b", "#fb8022"],
           [L("cb_spectrum2d", {"gain": 1.5}, name="Espectro 2D")],
           needs=("audio",)),

    Preset("cabo_completo", "Cabo + Fans", "Cabo",
           "Cross over 2D nas fitas de cabo e cometa girando nos fans — cada "
           "peca com o efeito que a forma dela pede.",
           ["#000000", "#ff2d55", "#a855f7", "#00d9ff"],
           [L("comet_piece", {"speed": 0.4, "tail": 0.5, "phase": 0.33,
                              "palette": "cyberpunk"}, name="Fans"),
            L("cb_cross", {"speed": 0.5},
              blend="add", name="Cabo")]),

    Preset("fita_ponto", "Ponto Fino", "Fitas Finas",
           "Poucos LEDs correndo pela fita, o resto apagado. Borda seca, sem "
           "degrade — o que realmente rende numa fita de cabo.",
           ["#000000", "#ff0040", "#000000", "#00d4ff", "#000000"],
           [L("px_chase", {"width": 2, "heads": 1, "speed": 0.6},
              name="Ponto fino")]),

    Preset("fita_tracejado", "Tracejado", "Fitas Finas",
           "Um LED aceso a cada quatro, deslizando. Marca as laminas da fita "
           "uma a uma.",
           ["#0d0221", "#e0218a", "#0d0221", "#00f5d4", "#0d0221"],
           [L("px_marching", {"spacing": 4, "width": 1, "speed": 0.4},
              name="Tracejado")]),

    Preset("fita_cometa", "Cometa Fino", "Fitas Finas",
           "Cabeca de um LED com rastro curto que apaga em degraus, nao num "
           "degrade continuo.",
           ["#000000", "#003b5c", "#00a6fb", "#ffffff"],
           [L("px_comet", {"tail": 4, "speed": 0.7}, name="Cometa fino")]),

    Preset("fita_codigo", "Codigo", "Fitas Finas",
           "Pontos caindo como chuva de codigo: cabeca clara, rastro curto, "
           "muita fita apagada entre eles.",
           ["#000000", "#00461e", "#00ff6a", "#c8ffe0"],
           [L("px_matrix", {"speed": 0.9, "tail": 5, "rate": 1.6},
              name="Codigo")]),

    Preset("fita_varredura", "Varredura Fina", "Fitas Finas",
           "Uma linha de um LED varrendo a fita de ponta a ponta, resto "
           "totalmente escuro.",
           ["#000000", "#000000", "#ffffff", "#000000"],
           [L("px_scan", {"width": 1, "tail": 3, "speed": 0.5},
              name="Varredura")]),

    Preset("fita_barras", "Barras", "Fitas Finas",
           "Blocos acesos e apagados deslizando. Marca bem as laminas.",
           ["#2d00f7", "#000000", "#f20089", "#000000", "#01c5c4"],
           [L("px_bars", {"on": 3, "off": 5, "speed": 0.35}, name="Barras")]),

    Preset("fita_esparso", "Cintilar Esparso", "Fitas Finas",
           "Fita quase toda escura, com poucos LEDs vivos que trocam de lugar "
           "devagar. Discreto.",
           ["#000000", "#001d3d", "#8ae1ff", "#000000"],
           [L("px_twinkle_gap", {"lit": 3, "hz": 1.2}, name="Esparso")]),

    Preset("fita_faisca", "Faisca Fina", "Fitas Finas",
           "LEDs isolados acendendo e apagando secamente, densidade baixa.",
           ["#000000", "#ff9ff3", "#000000", "#feca57", "#000000"],
           [L("px_sparkle", {"rate": 8.0, "density": 0.12}, name="Faisca")]),

    Preset("fita_abertura", "Abertura", "Fitas Finas",
           "Dois LEDs saem do centro da fita para as pontas e voltam.",
           ["#000000", "#ff006e", "#000000", "#3a86ff", "#000000"],
           [L("px_split", {"width": 1, "tail": 3, "speed": 0.5},
              name="Abertura")]),

    Preset("fita_cruzado", "Pares Cruzados", "Fitas Finas",
           "Dois pontos correndo em sentidos opostos, cruzando no meio.",
           ["#000000", "#ff2d55", "#ffffff", "#00d9ff", "#000000"],
           [L("px_pairs", {"width": 2, "speed": 0.5}, name="Cruzado")]),

    Preset("fita_espectro", "Espectro Fino", "Fitas Finas",
           "Cada LED da fita e uma faixa de frequencia, com corte seco: "
           "analisador de barras finas.",
           ["#30123b", "#4145ab", "#1ddfa3", "#a4fc3b", "#fb8022"],
           [L("px_spectrum", {"gain": 1.4, "threshold": 0.25},
              name="Espectro fino")],
           needs=("audio",)),

    Preset("fita_medidor", "Medidor de Audio", "Fitas Finas",
           "A fita vira um VU de LEDs individuais, com o topo destacado em "
           "branco.",
           ["#0000ff", "#00ff88", "#ffff00", "#ff0000", "#ffffff"],
           [L("px_audio_bars", {"gain": 1.3}, name="Medidor")],
           needs=("audio",)),

    Preset("misto_fita_fan", "Fitas Finas + Fans Suaves", "Fitas Finas",
           "O melhor dos dois: pontos finos correndo nas fitas, e um gradiente "
           "suave girando nos fans — cada peca com o que rende nela.",
           ["#000000", "#00d4ff", "#a855f7", "#ff2d75"],
           [L("comet_piece", {"speed": 0.4, "tail": 0.5, "phase": 0.33,
                              "palette": "cyberpunk"}, name="Fans suaves"),
            L("px_chase", {"width": 2, "heads": 2, "speed": 0.6,
                           "palette": "neon"},
              blend="add", name="Fitas finas")]),

    Preset("pista", "Pista", "Fluxo",
           "Faixas de cor correndo do inicio ao fim de cada fita e dando a "
           "volta em cada fan. O efeito assinatura das fitas de cabo.",
           ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"],
           [L("runway", {"speed": 0.5, "bands": 2.0}, name="Pista")]),

    Preset("pista_cascata", "Pista em Cascata", "Fluxo",
           "Igual a Pista, mas cada peca entra defasada da anterior: a cor "
           "parece atravessar o gabinete peca a peca.",
           ["#2d00f7", "#8900f2", "#f20089", "#01c5c4"],
           [L("runway", {"speed": 0.4, "bands": 1.0, "phase": 1.0,
                         "palette": "vaporwave"}, name="Pista defasada")]),

    Preset("neon", "Neon", "Fluxo",
           "Um ponto brilhante percorre cada peca deixando rastro. Fundo bem "
           "escuro — parece tubo de neon.",
           ["#03060c", "#006b80", "#00e5ff", "#c8faff"],
           [L("neon_flow", {"speed": 0.6, "tail": 0.35}, name="Neon")]),

    Preset("neon_duplo", "Neon Duplo", "Fluxo",
           "Dois pontos por peca, em cores opostas, se perseguindo.",
           ["#03060c", "#ff2d55", "#00d9ff", "#ffffff"],
           [L("neon_flow", {"speed": 0.5, "heads": 2, "tail": 0.3,
                            "color": "#00d9ff"}, name="Neon ciano"),
            L("neon_flow", {"speed": -0.5, "heads": 2, "tail": 0.3,
                            "color": "#ff2d55", "bg": "#000000"},
              blend="add", name="Neon rosa")]),

    Preset("fluxo_duplo", "Fluxo Duplo", "Fluxo",
           "Duas cores correndo em sentidos opostos dentro da mesma peca, "
           "cruzando no meio.",
           ["#03060c", "#ff2d55", "#8a4d9e", "#00d9ff"],
           [L("dual_stream", {"speed": 0.45, "width": 0.3}, name="Fluxo duplo")]),

    Preset("empilhar", "Empilhar", "Fluxo",
           "A luz viaja ate o fim da peca e vai se acumulando ate encher, "
           "depois esvazia.",
           ["#03045e", "#0077b6", "#48cae4", "#caf0f8"],
           [L("stack", {"speed": 0.8, "phase": 0.15}, name="Empilhar")]),

    Preset("vaivem", "Vai e Vem", "Fluxo",
           "Uma barra quicando entre as pontas de cada peca, com brilho "
           "residual.",
           ["#03060c", "#3d6b00", "#7cff00", "#e4ff9a"],
           [L("bounce", {"speed": 0.7, "width": 0.22, "phase": 0.3},
              name="Vai e vem")]),

    Preset("cascata", "Cascata", "Fluxo",
           "As pecas acendem em sequencia, uma apos a outra.",
           ["#12043a", "#c22e63", "#ff6b35", "#ffc15e"],
           [L("cascade", {"speed": 0.5, "hold": 0.35}, name="Cascata")]),

    Preset("cobra", "Cobra", "Fluxo",
           "Um corpo de luz percorre TODAS as pecas em serie, como se o "
           "gabinete fosse uma fita unica.",
           ["#03060c", "#1f4d00", "#a8e10c", "#e4ff1a"],
           [L("snake", {"speed": 0.3, "length": 0.25}, name="Cobra")]),

    Preset("arco_encadeado", "Arco-Iris Encadeado", "Fluxo",
           "A paleta percorre todas as pecas em serie, dando a volta no "
           "gabinete inteiro.",
           ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"],
           [L("chain_rainbow", {"speed": 0.25, "repeat": 1.0},
              name="Arco encadeado")]),

    Preset("corrida_dividida", "Corrida Dividida", "Fluxo",
           "Duas frentes saem do meio de cada peca para as pontas.",
           ["#000004", "#8c2981", "#de4968", "#fe9f6d"],
           [L("split_run", {"speed": 0.5, "width": 0.18}, name="Corrida")]),

    Preset("respiracao_seq", "Respiracao Sequencial", "Fluxo",
           "Cada peca respira com atraso em relacao a anterior. Calmo, mas com "
           "movimento perceptivel.",
           ["#000814", "#0055a4", "#8ae1ff", "#ffffff"],
           [L("piece_breathe", {"speed": 0.3, "phase": 0.5},
              name="Respiracao seq.")]),

    Preset("cometa_fans", "Cometa nos Fans", "Fluxo",
           "Um cometa girando em cada fan e correndo em cada fita, todos "
           "defasados entre si.",
           ["#ff006e", "#fb5607", "#ffbe0b", "#3a86ff"],
           [L("comet_piece", {"speed": 0.55, "tail": 0.45, "phase": 0.33},
              name="Cometa por peca")]),

    Preset("pista_audio", "Pista Reativa", "Fluxo",
           "A Pista correndo pelas pecas, com o grave da musica pulsando por "
           "cima.",
           ["#050014", "#ff0055", "#00d9ff", "#ffffff"],
           [L("runway", {"speed": 0.45, "bands": 2.0, "palette": "cyberpunk"},
              name="Pista"),
            L("audio_bass_pulse", {"gain": 1.5, "from_center": False,
                                   "bg": "#000000"},
              blend="add", opacity=0.75, name="Grave")],
           needs=("audio",)),

    Preset("arco_iris", "Arco-Iris", "Essenciais",
           "A paleta inteira atravessando o gabinete.",
           ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"],
           [L("rainbow_wave", {"speed": 0.35, "repeat": 1.0}, name="Arco-iris")]),

    Preset("respiracao", "Respiracao", "Essenciais",
           "Uma cor so, subindo e descendo de brilho devagar.",
           ["#001b26", "#00d4ff", "#8ae1ff", "#00d4ff", "#001b26"],
           [L("breathing", {"color": "#00d4ff", "speed": 0.35}, name="Respiracao")]),

    Preset("solida", "Cor Unica", "Essenciais",
           "Uma cor parada. Ponto de partida para personalizar.",
           ["#ff2d55", "#ff2d55", "#ff2d55"],
           [L("static", {"color": "#ff2d55"}, name="Cor unica")]),

    Preset("ciclo", "Ciclo de Cor", "Essenciais",
           "Tudo junto trocando de cor lentamente.",
           ["#ff006e", "#8338ec", "#3a86ff", "#00f5d4", "#ff006e"],
           [L("color_cycle", {"speed": 0.12}, name="Ciclo")]),

    Preset("gradiente_sunset", "Por do Sol", "Essenciais",
           "Gradiente quente parado, com uma pulsacao suave por cima.",
           ["#12043a", "#c22e63", "#ff6b35", "#ffc15e"],
           [L("gradient", {"palette": "sunset", "repeat": 1.0}, name="Gradiente"),
            L("breathing", {"color": "#ffffff", "speed": 0.18, "floor": 0.75},
              blend="multiply", opacity=0.5, name="Pulsacao")]),

    Preset("fogo", "Fogo", "Ambiente",
           "Chama subindo do fundo do gabinete, com bruxuleio irregular.",
           ["#0b0000", "#9d0208", "#e85d04", "#ffba08", "#fff0a0"],
           [L("fire", {"scale": 3.5, "speed": 1.0, "height": 0.75}, name="Fogo")]),

    Preset("aurora", "Aurora Boreal", "Ambiente",
           "Cortinas verdes e roxas ondulando devagar.",
           ["#01030a", "#0a8a5f", "#4ce08a", "#9df5c0", "#b98cff"],
           [L("aurora", {"speed": 0.18, "curl": 0.4}, name="Aurora"),
            L("twinkle", {"palette": "ice", "rate": 3.0, "density": 0.12},
              blend="add", opacity=0.45, name="Estrelas")]),

    Preset("plasma", "Plasma", "Ambiente",
           "Senoides cruzadas em movimento, o classico de demoscene.",
           ["#0d0887", "#b12a90", "#e16462", "#fca636", "#f0f921"],
           [L("plasma", {"speed": 0.35, "scale": 3.0}, name="Plasma")]),

    Preset("nebulosa", "Nebulosa", "Ambiente",
           "Nuvens de gas em duas escalas com estrelas piscando.",
           ["#0d0221", "#7b2cbf", "#e0218a", "#00f5d4"],
           [L("nebula", {"speed": 0.06, "stars": 0.4}, name="Nebulosa")]),

    Preset("oceano", "Oceano", "Ambiente",
           "Causticas de piscina escorregando sobre azul profundo.",
           ["#03045e", "#0077b6", "#00b4d8", "#90e0ef", "#caf0f8"],
           [L("gradient", {"palette": "ocean", "axis": "y"}, opacity=0.6, name="Fundo"),
            L("water", {"speed": 0.3, "scale": 4.0}, blend="screen", name="Causticas")]),

    Preset("lava", "Lava Lamp", "Ambiente",
           "Bolhas subindo e descendo, fundindo quando se aproximam.",
           ["#0b0000", "#9d0208", "#e85d04", "#ffba08"],
           [L("lavalamp", {"speed": 0.22, "blobs": 5}, name="Lava")]),

    Preset("marmore", "Marmore Dourado", "Ambiente",
           "Veios de pedra dourada se movendo muito devagar.",
           ["#1a1000", "#b8860b", "#ffd700", "#fff4c2"],
           [L("marble", {"speed": 0.08, "veins": 4.0}, name="Marmore")]),

    Preset("vela", "Luz de Vela", "Ambiente",
           "Tremulacao quente, cada LED com seu proprio ritmo.",
           ["#3d1a00", "#ff8a1e", "#ffb347", "#ff8a1e"],
           [L("candle", {"speed": 1.0, "depth": 0.55}, name="Vela")]),

    Preset("fumaca", "Fumaca", "Ambiente",
           "Densidade cinzenta subindo e se dissipando.",
           ["#05070a", "#3a4654", "#9fb3c8", "#3a4654"],
           [L("smoke", {"speed": 0.35}, name="Fumaca")]),

    Preset("tempestade", "Tempestade", "Cenario",
           "Chuva caindo no escuro, cortada por relampagos.",
           ["#050912", "#1b3a5c", "#4fc3f7", "#dbeaff"],
           [L("lightning", {"rate": 0.7, "decay": 9.0}, name="Raios"),
            L("rain", {"drops": 18, "speed": 1.2, "color": "#4fc3f7"},
              blend="add", opacity=0.85, name="Chuva")]),

    Preset("chuva_neon", "Chuva Neon", "Cenario",
           "Gotas ciano descendo sobre um fundo roxo profundo.",
           ["#0d0221", "#2d00f7", "#00f5d4", "#f20089"],
           [L("gradient", {"palette": "cyberpunk", "axis": "y"}, opacity=0.5, name="Fundo"),
            L("rain", {"drops": 22, "speed": 1.5, "color": "#00f5d4", "length": 0.22},
              blend="add", name="Chuva")]),

    Preset("neve", "Neve", "Cenario",
           "Flocos caindo devagar com deriva lateral.",
           ["#04121e", "#1b3a5c", "#a8d8ff", "#e8f4ff"],
           [L("gradient", {"palette": "ice", "axis": "y", "repeat": 0.5},
              opacity=0.35, name="Fundo"),
            L("snow", {"flakes": 26, "speed": 0.3}, blend="add", name="Neve")]),

    Preset("vagalumes", "Vaga-lumes", "Cenario",
           "Pontos vagando no escuro, pulsando fora de fase.",
           ["#04160a", "#0b3d20", "#a8e10c", "#e4ff1a"],
           [L("fireflies", {"count": 12, "speed": 0.22}, name="Vaga-lumes")]),

    Preset("meteoros", "Meteoros", "Cenario",
           "Riscos diagonais com cauda que apaga.",
           ["#03040a", "#5b1179", "#ff6b35", "#fff3b0"],
           [L("meteor", {"count": 5, "speed": 0.8, "angle": 35.0}, name="Meteoros")]),

    Preset("fogos", "Fogos de Artificio", "Cenario",
           "Foguetes explodindo sobre um ceu de nebulosa.",
           ["#0d0221", "#7b2cbf", "#ff006e", "#ffbe0b"],
           [L("nebula", {"speed": 0.04, "density": 0.5, "stars": 0.5},
              opacity=0.5, name="Ceu"),
            L("fireworks", {"rate": 1.0, "sparks": 28}, blend="add", name="Fogos")]),

    Preset("cometa", "Cometa", "Cenario",
           "Um corpo em orbita deixando rastro.",
           ["#000814", "#0055a4", "#00a6fb", "#ffffff"],
           [L("comet", {"speed": 0.5, "trail": 20}, name="Cometa")]),

    Preset("tunel", "Tunel", "Cenario",
           "Aneis vindo em direcao a voce, com perspectiva.",
           ["#000004", "#8c2981", "#de4968", "#fe9f6d"],
           [L("tunnel", {"speed": 0.7, "depth": 0.25}, name="Tunel")]),

    Preset("scanner", "Scanner", "Movimento",
           "Feixe vermelho com rastro varrendo o gabinete.",
           ["#000000", "#440000", "#ff1744", "#ff8888"],
           [L("scan", {"color": "#ff1744", "speed": 0.7}, name="Scanner")]),

    Preset("viatura", "Viatura", "Movimento",
           "Vermelho e azul alternando nas duas metades.",
           ["#ff0000", "#000000", "#0026ff", "#000000"],
           [L("police", {"hz": 2.5, "style": "split"}, name="Viatura")]),

    Preset("espiral", "Espiral", "Movimento",
           "Bracos de cor girando a partir do centro.",
           ["#0d0221", "#7b2cbf", "#e0218a", "#00f5d4"],
           [L("spiral", {"speed": 0.3, "arms": 3, "twist": 2.0}, name="Espiral")]),

    Preset("ondulacao", "Ondulacao", "Movimento",
           "Aneis concentricos saindo do centro.",
           ["#03045e", "#0077b6", "#48cae4", "#caf0f8"],
           [L("ripple", {"speed": 0.5, "freq": 3.0}, name="Ondulacao")]),

    Preset("chase", "Chase", "Movimento",
           "Blocos de cor correndo ao longo das fitas.",
           ["#ff0040", "#000000", "#00d4ff", "#000000"],
           [L("chase", {"speed": 1.0, "width": 3}, name="Chase")]),

    Preset("interferencia", "Interferencia", "Movimento",
           "Duas fontes de onda somadas, orbitando uma a outra.",
           ["#03045e", "#0077b6", "#00b4d8", "#90e0ef"],
           [L("interference", {"speed": 0.5, "freq": 6.0, "orbit": True},
              name="Interferencia")]),

    Preset("matrix", "Matrix", "Simulacao",
           "Automato de Wolfram gerando linhas que rolam pelo gabinete.",
           ["#000000", "#0b3d20", "#5cb85c", "#a7e05c"],
           [L("automaton", {"rule": 30, "hz": 14.0, "palette": "toxic"},
              name="Automato")]),

    Preset("vida", "Game of Life", "Simulacao",
           "O automato de Conway, com rastro esfriando atras.",
           ["#0a1a00", "#5ca904", "#a8e10c", "#e4ff1a"],
           [L("life", {"hz": 7.0, "fade": 0.85}, name="Vida")]),

    Preset("turing", "Padroes de Turing", "Simulacao",
           "Reacao-difusao: manchas e labirintos que crescem sozinhos.",
           ["#000004", "#3b0f70", "#8c2981", "#fe9f6d"],
           [L("gray_scott", {"steps": 8}, name="Reacao-difusao")]),

    Preset("agua_fisica", "Fisica de Ondas", "Simulacao",
           "Equacao da onda 2D de verdade: pancadas geram ondas que refletem.",
           ["#03045e", "#0077b6", "#48cae4", "#caf0f8"],
           [L("wave_eq", {"rate": 1.8, "damping": 0.996}, name="Ondas")]),

    Preset("cardume", "Cardume", "Simulacao",
           "Bando com separacao, alinhamento e coesao.",
           ["#0d0221", "#3a86ff", "#00f5d4", "#ffbe0b"],
           [L("boids", {"count": 26, "speed": 0.35}, name="Cardume")]),

    Preset("espectro", "Espectro de Audio", "Audio",
           "Cada regiao do gabinete responde a uma faixa de frequencia.",
           ["#30123b", "#4145ab", "#1ddfa3", "#a4fc3b", "#fb8022"],
           [L("audio_spectrum", {"gain": 1.4, "mirror": True}, name="Espectro")],
           needs=("audio",)),

    Preset("batida", "Batida", "Audio",
           "Pulso no grave expandindo do centro, com faiscas no ataque.",
           ["#050014", "#ff0055", "#ff9ff3", "#ffffff"],
           [L("audio_bass_pulse", {"gain": 1.6, "from_center": True}, name="Pulso"),
            L("audio_sparkle", {"density": 0.3}, blend="add", opacity=0.8,
              name="Faiscas")],
           needs=("audio",)),

    Preset("fogo_sonoro", "Fogo Sonoro", "Audio",
           "A altura da chama e comandada pelo grave da musica.",
           ["#0b0000", "#9d0208", "#e85d04", "#ffba08"],
           [L("audio_fire", {"gain": 1.8}, name="Fogo sonoro")],
           needs=("audio",)),

    Preset("vu", "VU Meter", "Audio",
           "O volume preenche o gabinete como uma barra.",
           ["#0000ff", "#00ff00", "#ffff00", "#ff0000"],
           [L("audio_vu", {"gain": 1.2, "axis": "y", "mirror": False},
              name="VU meter")],
           needs=("audio",)),

    Preset("timbre", "Cor pelo Timbre", "Audio",
           "Som grave puxa para um lado da paleta, agudo para o outro.",
           ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff"],
           [L("audio_hue", {"gain": 1.2, "spread": 0.3}, name="Timbre")],
           needs=("audio",)),

    Preset("ondas_batida", "Ondas na Batida", "Audio",
           "Cada batida solta um anel que se expande.",
           ["#0d0221", "#7b2cbf", "#e0218a", "#00f5d4"],
           [L("audio_ripple", {"threshold": 0.5, "speed": 0.8}, name="Aneis")],
           needs=("audio",)),

    Preset("ambilight", "Ambilight", "Tela",
           "Cada LED pega a cor da regiao da tela que corresponde a posicao "
           "fisica dele no gabinete.",
           ["#ff4d4d", "#4dff88", "#4d88ff", "#ffdb4d"],
           [L("ambilight", {"saturation": 1.4, "smooth": 0.35}, name="Ambilight")],
           needs=("screen",)),

    Preset("ambilight_bordas", "Ambilight (bordas)", "Tela",
           "Igual ao Ambilight, mas amostrando so a moldura da tela -- costuma "
           "ficar mais vivo em jogo.",
           ["#ff2d55", "#a855f7", "#00d9ff", "#7cff00"],
           [L("ambilight", {"edges": True, "saturation": 1.6, "smooth": 0.25},
              name="Ambilight bordas")],
           needs=("screen",)),

    Preset("clima_tela", "Clima da Tela", "Tela",
           "Extrai o tom dominante da tela e espalha num gradiente, em vez de "
           "copiar a imagem. Menos agitado que o Ambilight.",
           ["#5b1179", "#c22e63", "#ff6b35", "#ffc15e"],
           [L("screen_mood", {"saturation": 1.6, "spread": 0.3}, name="Clima")],
           needs=("screen",)),

    Preset("termometro", "Termometro", "Sensores",
           "Cor pela temperatura da CPU: azul frio, vermelho quente.",
           ["#0000ff", "#00ffff", "#00ff00", "#ffff00", "#ff0000"],
           [L("temp_gradient", {"sensor": "cpu_temp", "lo": 35, "hi": 85},
              name="Temperatura")],
           needs=("sensors",)),

    Preset("cpu_gpu", "CPU vs GPU", "Sensores",
           "Um lado do gabinete mostra a CPU, o outro a GPU.",
           ["#0000ff", "#00ff00", "#ffff00", "#ff0000"],
           [L("dual_sensor", {"lo": 35, "hi": 85, "split": "x"}, name="CPU/GPU")],
           needs=("sensors",)),

    Preset("carga", "Barra de Carga", "Sensores",
           "Enche de baixo para cima conforme o uso da CPU.",
           ["#001b26", "#00ff88", "#ffff00", "#ff0000"],
           [L("load_bar", {"sensor": "cpu_load", "axis": "y"}, name="Carga")],
           needs=("sensors",)),

    Preset("alarme", "Alarme Termico", "Sensores",
           "Calmo abaixo do limite, pulsa vermelho forte quando passa.",
           ["#00c2ff", "#00c2ff", "#ff1100", "#ff1100"],
           [L("thermal_alarm", {"sensor": "cpu_temp", "threshold": 80},
              name="Alarme")],
           needs=("sensors",)),
]

AGRESSIVOS = {
    "viatura",
    "tempestade",
    "fogos",
    "fita_faisca",
    "fita_codigo",
    "cabo_twinkle",
    "cabo_lamina",
    "vida",
    "matrix",
    "alarme",
    "cabo_disputa",
}

for _p in PRESETS:
    _p.refined = _p.id not in AGRESSIVOS


# Do que serve para qualquer gabinete ao que pede peca especifica: Cabo e
# Fitas Finas sao para fita de cabo e fita fina, e na frente abriam a
# vitrine com onze efeitos que quase ninguem tem onde ver.
CATEGORY_ORDER = ["Essenciais", "Ambiente", "Movimento", "Fluxo", "Cenario",
                  "Simulacao", "Audio", "Tela", "Sensores", "Fitas Finas",
                  "Cabo"]


def by_id(pid: str):
    """Busca um preset pelo id, devolvendo None se nao existir."""
    return next((p for p in PRESETS if p.id == pid), None)


def catalog():
    """Agrupa os presets por categoria, na ordem em que a interface mostra.

    Categoria fora da ordem conhecida cai num grupo Outros, para que nenhum
    preset suma da tela sem aviso.
    """
    out = []
    for cat in CATEGORY_ORDER:
        items = [p.to_json() for p in PRESETS if p.category == cat]
        if items:
            out.append({"category": cat, "presets": items,
                        "refined": sum(1 for i in items if i["refined"])})
    resto = [p.to_json() for p in PRESETS if p.category not in CATEGORY_ORDER]
    if resto:
        out.append({"category": "Outros", "presets": resto,
                    "refined": sum(1 for i in resto if i["refined"])})
    return out
