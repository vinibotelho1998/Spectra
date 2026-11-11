"""Orquestracao do aplicativo: conexao, cena, perfis e descoberta de LED.

`SpectraApp` costura tudo: garante que o servidor OpenRGB esteja de pe,
conecta, monta o renderizador, liga as fontes externas conforme a cena
pede e persiste configuracao e perfis.

Duas coisas moram aqui por serem do aplicativo, e nao do motor. A
primeira e o vigia de conexao, que percebe queda e reconecta sozinho,
porque o servidor OpenRGB e um processo separado que pode cair ou ser
reiniciado. A segunda e a sessao de descoberta de LED: header ARGB de 3
pinos nao tem retorno, entao a unica forma de saber quantos LEDs foram
plugados e acender faixas e perguntar a quem esta olhando o gabinete.
"""

from __future__ import annotations

import json
import os
import socket
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from . import __version__
from . import effects as fx
from .core.protocol import OpenRGBClient, OpenRGBError
from .engine import blend
from .engine.canvas import device_key
from .engine.palette import (PALETTE_LABELS, PALETTE_NAMES, hex_to_rgb,
                             palette_preview)
from .engine.renderer import Layer, Renderer
from . import presets as ps
from .sources.audio import AudioSource
from .sources.screen import ScreenSource
from .sources.sensors import VENDOR_DLL, SensorSource


def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_root() -> str:
    if sys.platform.startswith("linux"):
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "spectra")
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Spectra")
    return os.path.join(ROOT, "config")


ROOT = _app_root()
CONFIG_DIR = _config_root()
PROFILES_DIR = os.path.join(CONFIG_DIR, "profiles")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

OPENRGB_CANDIDATES = [
    r"C:\Program Files\OpenRGB\OpenRGB.exe",
    r"C:\Program Files (x86)\OpenRGB\OpenRGB.exe",
]
OPENRGB_TASK = "Spectra - OpenRGB SDK Server"
OPENRGB_ARGS = ["--server", "--startminimized"]
# A porta SDK pode abrir antes de a varredura de hardware terminar.
ESTABILIZACAO_DISPOSITIVOS = 3.0
# Ate onde a conexao apaga o fim de cada conector ARGB. E o mesmo teto do
# campo de contagem; o conector que aceita menos para no proprio maximo.
TETO_LIMPEZA_CAUDA = 512
# Tempo para o OpenRGB entregar o preto ao controlador antes de a zona
# voltar a contagem salva.
ESPERA_LIMPEZA_CAUDA = 0.2

CASE_SPOTS = {
    "topo_esq":     (0.22, 0.10), "topo_centro": (0.50, 0.10),
    "topo_dir":     (0.78, 0.10),
    "frente_cima":  (0.12, 0.28), "frente_meio": (0.12, 0.50),
    "frente_baixo": (0.12, 0.74),
    "traseira":     (0.88, 0.30),
    "ram":          (0.50, 0.20),
    "placa_mae":    (0.50, 0.42),
    "meio":         (0.50, 0.50),
    "gpu":          (0.50, 0.64),
    "lateral":      (0.50, 0.80),
    "base_esq":     (0.28, 0.90), "base_centro": (0.50, 0.90),
    "base_dir":     (0.72, 0.90),
}

CASE_SPOT_LABELS = [
    ("topo_esq", "Topo esquerda"), ("topo_centro", "Topo centro"),
    ("topo_dir", "Topo direita"),
    ("frente_cima", "Frente cima"), ("frente_meio", "Frente meio"),
    ("frente_baixo", "Frente baixo"),
    ("traseira", "Traseira"), ("ram", "Perto da RAM"),
    ("placa_mae", "Placa-mae"), ("meio", "Meio"),
    ("gpu", "GPU / cabo da GPU"), ("lateral", "Lateral"),
    ("base_esq", "Base esquerda"), ("base_centro", "Base centro"),
    ("base_dir", "Base direita"),
]

DEFAULT_SCENE = {
    "layers": [{"effect": "rainbow_wave", "params": {"speed": 0.35},
                "blend": "normal", "opacity": 1.0, "enabled": True,
                "name": "Onda base"}],
    "settings": {"brightness": 1.0, "gamma": 2.2, "fps": 60, "smoothing": 0.0},
}

# Cena da primeira abertura. Sendo um preset, a vitrine o marca como tocando
# e o painel Tocando agora diz o nome dele, em vez de "cena personalizada".
PRESET_INICIAL = "arco_iris"

# Leituras que so a LibreHardwareMonitorLib entrega. Uso de CPU e de RAM
# vem do psutil e funciona sem ela.
SENSORES_LHM = {"cpu_temp", "gpu_temp", "gpu_load", "fan_rpm"}

ROTULO_SENSOR = {
    "cpu_temp": "temperatura da CPU", "gpu_temp": "temperatura da GPU",
    "cpu_load": "uso da CPU", "gpu_load": "uso da GPU",
    "ram_load": "uso da RAM", "fan_rpm": "rotacao dos fans",
}

ROTULO_FONTE = {"audio": "audio", "screen": "captura de tela",
                "sensors": "sensores"}


def sensores_da_camada(effect_id: str, params=None) -> set:
    """Leituras de sensor que uma camada consome.

    E o que separa um efeito de uso da CPU, que roda so com o psutil, de um
    de temperatura, que sem a DLL fica parado no frio sem aviso nenhum.
    """
    d = fx.get(effect_id)
    if d is None or "sensors" not in d.needs:
        return set()
    if effect_id == "dual_sensor":
        return {"cpu_temp", "gpu_temp"}
    p = d.defaults()
    p.update({k: v for k, v in (params or {}).items() if v is not None})
    s = p.get("sensor")
    return {s} if isinstance(s, str) else set()


def _dll_sensores() -> str:
    """Onde a LibreHardwareMonitorLib.dll e procurada.

    Primeiro na pasta de configuracao, que no app instalado e
    %LOCALAPPDATA%\\Spectra e aceita arquivo novo sem administrador; depois
    na vendor/ do proprio app, que no instalado fica escondida dentro de
    _internal. Sem ela em lugar nenhum vale o primeiro caminho, que e o que
    o aviso da interface manda usar.
    """
    opcoes = [os.path.join(CONFIG_DIR, "vendor", os.path.basename(VENDOR_DLL)),
              VENDOR_DLL]
    return next((p for p in opcoes if os.path.isfile(p)), opcoes[0])


def _port_open(host="127.0.0.1", port=6742, timeout=0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _openrgb_rodando() -> bool:
    if not sys.platform.startswith("linux"):
        from .core import admin
        return admin.openrgb_rodando()
    try:
        import psutil
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmd = proc.info.get("cmdline") or []
                executable = os.path.basename(cmd[0]).lower() if cmd else ""
                if name == "openrgb" or executable.startswith("openrgb") and (executable == "openrgb" or executable.endswith(".appimage")):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (ImportError, OSError):
        pass
    return False


def _grava_json(path: str, data) -> None:
    """Grava JSON num temporario ao lado e so entao troca pelo arquivo final.

    Se a serializacao falhar no meio, ou a maquina cair durante a escrita,
    o arquivo anterior continua inteiro em vez de ficar truncado.
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class SpectraApp:
    """Estado do aplicativo e as operacoes que a interface aciona.

    Quase todo metodo publico daqui corresponde a uma rota da API. Os que
    comecam com `probe_` formam o assistente de descoberta, que caminha por
    busca binaria em varias zonas ao mesmo tempo para reduzir quantas
    perguntas a pessoa precisa responder.
    """

    def __init__(self, host="127.0.0.1", port=6742):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        self.host, self.port = host, port
        self.client = OpenRGBClient(host, port, name="Spectra")
        self.renderer: Renderer | None = None
        self.config = self._load_config()
        self.audio = None
        self.screen = None
        self.sensors = None
        self.status_msg = "iniciando"
        self.connected = False
        self._lock = threading.RLock()
        self._conexao = threading.Lock()
        self._watchdog = None
        self._watchdog_stop = threading.Event()
        self._encerrando = False
        self._primeira_conexao_pendente = False
        self._recuperacao_inicial_tentada = False
        self.reconnects = 0
        self.last_exclusive = None
        self.last_error_exclusive = None
        self.connecting = False
        self._identify_until = 0.0
        self._identify_was_paused = False
        self.elevacao = {}
        self._reparando = False
        self.teclado = None
        self._teclado_proxima = 0.0
        self._fonte_espera = {}
        self.cor_teclado = (0, 0, 0)
        self._ultima_gravacao = 0.0
        self._gravar_pendente = False
        self.motivo_conexao = None
        self.erro_conexao = None
        # quem mostra a janela quando o app e aberto de novo; a janela nativa
        # e da camada de cima, que registra aqui o proprio jeito de mostrar
        self.ao_mostrar_janela = None

    def _load_config(self) -> dict:
        base = {"layout": {}, "enabled_devices": {}, "zone_sizes": {},
                "settings": dict(DEFAULT_SCENE["settings"]),
                "sources": {"audio": {"device": None}, "screen": {"output": 0, "fps": 30}},
                "autostart_openrgb": True, "last_profile": None,
                "exclusive_mode": True, "akko_keyboard": True}
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    lido = json.load(f)
                if not isinstance(lido, dict):
                    raise ValueError("a configuracao nao e um objeto")
                base.update(lido)
            except ValueError:
                # Arquivo ilegivel fica guardado ao lado. Sem isso a primeira
                # gravacao o trocaria pelos padroes, e com ele iriam o mapa
                # do gabinete e a contagem de LEDs de cada conector.
                try:
                    os.replace(CONFIG_FILE, CONFIG_FILE + ".corrompido")
                except OSError:
                    pass
            except OSError:
                pass
        return base

    def save_config(self):
        """Grava a configuracao em disco, criando o diretorio se faltar.

        A cena no ar vai junto. E ela que volta na proxima abertura, e nao o
        ultimo perfil: quem aplicou um efeito e reiniciou o PC espera ver o
        mesmo efeito, tenha salvo perfil ou nao.
        """
        with self._lock:
            if self.renderer:
                self.config["settings"] = {
                    k: self.renderer.settings[k]
                    for k in ("brightness", "gamma", "fps", "smoothing")}
                self.config["enabled_devices"] = self.renderer.settings["enabled_devices"]
                with self.renderer._lock:
                    self.config["cena"] = {"layers": [
                        dict(l.to_json(), params=dict(l.params),
                             targets=list(l.targets))
                        for l in self.renderer.layers]}
            os.makedirs(CONFIG_DIR, exist_ok=True)
            # copia rasa: algumas rotas gravam chave nova sem a trava, e o
            # json.dump iterando o proprio dicionario estouraria no meio
            _grava_json(CONFIG_FILE, dict(self.config))
            self._ultima_gravacao = time.monotonic()
            self._gravar_pendente = False

    def _cena_mudou(self):
        """Grava a cena que acabou de mudar, no maximo uma vez por segundo.

        Arrastar um slider muda a camada vinte vezes por segundo, e cada
        gravacao vai ate o disco. O que ficar para depois o vigia grava na
        volta seguinte, e o encerramento grava de qualquer jeito.
        """
        if time.monotonic() - self._ultima_gravacao >= 1.0:
            self.save_config()
        else:
            self._gravar_pendente = True

    def _openrgb_exe(self):
        """Acha o executavel do OpenRGB, ou None.

        O caminho informado pela pessoa vem antes da lista, para quem usa a
        versao portatil ou instalou fora de Program Files.
        """
        escolhido = self.config.get("openrgb_exe")
        if isinstance(escolhido, str) and os.path.isfile(escolhido):
            return escolhido
        if sys.platform.startswith("linux"):
            return shutil.which("openrgb") or shutil.which("OpenRGB")
        return next((p for p in OPENRGB_CANDIDATES if os.path.isfile(p)), None)

    def set_openrgb_exe(self, caminho) -> dict:
        """Grava onde fica o OpenRGB.exe desta maquina.

        So aceita um arquivo que existe e se chama OpenRGB.exe: esse caminho
        vira a tarefa agendada que roda com privilegio maximo.
        """
        caminho = str(caminho or "").strip().strip('"')
        if sys.platform.startswith("linux"):
            caminho = os.path.expanduser(caminho)
            nome = os.path.basename(caminho).lower()
            valido = nome == "openrgb" or (nome.startswith("openrgb") and nome.endswith(".appimage"))
            if not valido or not os.path.isfile(caminho) or not os.access(caminho, os.X_OK):
                return {"ok": False, "error": "Escolha o executavel openrgb ou OpenRGB AppImage"}
            caminho = os.path.abspath(caminho)
        elif (os.path.basename(caminho).lower() != "openrgb.exe"
                or not os.path.isfile(caminho)):
            return {"ok": False,
                    "error": "Nao achei o OpenRGB.exe nesse caminho"}
        self.config["openrgb_exe"] = caminho
        self.save_config()
        return {"ok": True, "path": caminho}

    def _start_openrgb(self) -> bool:
        """Sobe o servidor, gastando o que puder para ele subir elevado.

        A ordem importa. A tarefa agendada roda elevada sem aviso nenhum,
        entao vem primeiro. Faltando a tarefa, ela e criada na hora, ao
        preco de um unico aviso do controle de conta na vida da maquina.
        So depois de tudo isso e que cai no executavel comum, que sobe sem
        privilegio e deixa a memoria RAM invisivel.
        """
        from .core import admin

        if sys.platform.startswith("linux"):
            exe = self._openrgb_exe()
            if not exe:
                self.status_msg = "OpenRGB nao encontrado"
                self.motivo_conexao = "nao_instalado"
                return False
            try:
                # --startminimized implies a GUI in OpenRGB, which is not
                # available in headless sessions. The SDK server runs alone.
                subprocess.Popen([exe, "--server", "--server-port", str(self.port)],
                                 close_fds=True, start_new_session=True)
            except OSError as exc:
                self.status_msg = f"falha ao iniciar OpenRGB: {exc}"
                self.motivo_conexao = "falha_partida"
                self.erro_conexao = str(exc)
                return False
            return True

        if admin.tarefa_existe(OPENRGB_TASK) and admin.rodar_tarefa(OPENRGB_TASK):
            return True

        exe = self._openrgb_exe()
        if not exe:
            self.status_msg = "OpenRGB nao encontrado"
            self.motivo_conexao = "nao_instalado"
            return False

        if self.config.get("elevar_openrgb", True):
            r = admin.criar_tarefa(OPENRGB_TASK, exe, OPENRGB_ARGS)
            if r == "ok" and admin.rodar_tarefa(OPENRGB_TASK):
                return True
            if r == "recusado":
                self.config["elevar_openrgb"] = False
                self.save_config()

        try:
            subprocess.Popen([exe] + OPENRGB_ARGS,
                             creationflags=0x00000008 | 0x00000200,
                             close_fds=True)
        except Exception as exc:
            self.status_msg = f"falha ao iniciar OpenRGB: {exc}"
            self.motivo_conexao = "falha_partida"
            self.erro_conexao = str(exc)
            return False
        return True

    def ensure_openrgb(self, wait: float = 25.0, pode_subir: bool = True) -> bool:
        """Garante que o servidor OpenRGB esteja no ar, subindo se preciso.

        Sem privilegio de administrador o OpenRGB nao abre o SMBus, e sem
        SMBus ele nao enxerga a memoria RAM nem parte dos controladores da
        placa-mae, entao `_start_openrgb` persegue o caminho elevado.

        Quando nao consegue, deixa em `motivo_conexao` o porque, para a
        interface dizer a acao certa em vez de uma instrucao generica.

        `pode_subir` falso e o vigia: ele reconecta num servidor que esta
        abrindo, mas nao abre outro. Fechar o OpenRGB e escolha de quem fechou,
        e o vigia reabria ele sem fim.
        """
        from .core import admin

        if _port_open(self.host, self.port):
            return True
        if self.host in ("127.0.0.1", "localhost", "::1") and _openrgb_rodando():
            # O OpenRGB leva uns cinco segundos varrendo o hardware antes de
            # abrir a porta. Quem subia outro nessa janela, como no logon com
            # a tarefa antiga do Prism, deixava dois disputando os mesmos LEDs.
            self.status_msg = "esperando o OpenRGB abrir a porta"
            return self._esperar_porta(wait)
        if not pode_subir or self.host not in ("127.0.0.1", "localhost", "::1"):
            self.motivo_conexao = "servidor_fechado"
            return False
        if not self.config.get("autostart_openrgb"):
            self.motivo_conexao = "partida_desligada"
            return False
        self.status_msg = "subindo o servidor OpenRGB"
        if not self._start_openrgb():
            return False
        return self._esperar_porta(wait)

    def _esperar_porta(self, wait: float) -> bool:
        deadline = time.monotonic() + wait
        while not self._encerrando and time.monotonic() < deadline:
            if _port_open(self.host, self.port):
                return True
            time.sleep(0.5)
        self.status_msg = "OpenRGB nao respondeu a tempo"
        self.motivo_conexao = "sem_resposta"
        return False

    def _recuperar_openrgb_inicial(self, pode_subir: bool) -> bool:
        """Troca uma instancia travada na abertura, uma unica vez por sessao.

        No logon outro atalho pode abrir o OpenRGB sem servidor SDK, ou antes
        de os controladores estarem prontos. Esperar a porta para sempre nao
        resolve isso. So encerramos o processo quando ha como abrir outro,
        e conferimos que ele saiu antes de iniciar a substituicao.
        """
        from .core import admin

        # Nao encerrar processos de terceiros no Linux durante a reconexao.
        if sys.platform.startswith("linux"):
            return False
        if (not pode_subir or self.renderer is not None or self._encerrando
                or self._recuperacao_inicial_tentada
                or not self.config.get("autostart_openrgb")
                or self.host not in ("127.0.0.1", "localhost", "::1")
                or self.port != 6742):
            return False
        if not admin.openrgb_rodando():
            return False
        if not self._openrgb_exe() and not admin.tarefa_existe(OPENRGB_TASK):
            return False
        self._recuperacao_inicial_tentada = True
        self.status_msg = "reiniciando o OpenRGB que nao respondeu na abertura"
        self.client.close()
        if not admin.encerrar_openrgb():
            if (not admin.tarefa_existe(OPENRGB_TASK)
                    or not admin.encerrar_tarefa(OPENRGB_TASK)):
                return False
        deadline = time.monotonic() + 10.0
        while admin.openrgb_rodando():
            if self._encerrando or time.monotonic() >= deadline:
                return False
            time.sleep(0.3)
        if self._encerrando or _port_open(self.host, self.port):
            # Outra instancia pode ter tomado a porta durante a troca.
            return not self._encerrando
        return self._start_openrgb() and self._esperar_porta(30.0)

    def _liga_teclado(self):
        """Liga o teclado Akko na cena, se houver um e a configuracao pedir.

        Ele nao entra no canvas: nao fala o protocolo do OpenRGB e aceita
        uma cor so de cada vez. Mas acompanha ao vivo, porque o firmware
        tem um modo feito para receber cor do computador em fluxo. Os
        outros dois caminhos, cor fixa e camada por tecla, reaplicam a
        iluminacao a cada pacote e piscam; esse nao.
        """
        if not self.config.get("akko_keyboard", True):
            if self.renderer:
                # com a trava: um quadro no meio ainda pintaria o teclado
                # depois do preto abaixo
                with self.renderer._lock:
                    self.renderer.ambiente = None
            t = self.teclado
            if t is not None and t.conectado:
                # Solto sem isso, o teclado ficava para sempre na ultima cor,
                # no modo de fluxo, e o cartao seguia dizendo que o Spectra
                # controlava ele.
                try:
                    t.apagar()
                    t.fechar()
                except Exception:
                    pass
            return
        if self.teclado is None:
            from .core.akko import AkkoKeyboard
            self.teclado = AkkoKeyboard()
        if not self.teclado.conectado and not self.teclado.abrir():
            if self.renderer:
                self.renderer.ambiente = None
            return

        from .core.akko import BRILHO_MAX

        escala = max(0.0, min(float(self.config.get("akko_brilho", 1.0)), 1.0))
        # Quase sem media temporal. Ela entrou aqui para combater um
        # piscar que, no fim, vinha de duas instancias do app disputando o
        # teclado, e nao do canal. Mantida alta, ela corta o vale e o pico
        # de qualquer efeito: a respiracao nao apaga nem satura.
        constante = max(0.0, float(self.config.get("akko_suavizacao", 0.04)))
        # Sem piso por padrao: o teclado acompanha a cena ate o preto, que
        # e o que faz a respiracao parecer a mesma nos dois lugares. Quem
        # quiser um minimo de luz sempre acesa levanta `akko_piso`.
        piso = max(0.0, min(float(self.config.get("akko_piso", 0.0)), 1.0))
        suave = {"cor": None, "quando": 0.0}
        # Ganho automatico. Cada efeito tem o seu proprio teto de
        # intensidade, e quase nenhum chega a saturar a media da faixa, so
        # que o teclado tem 255 disponiveis de qualquer jeito. Guardando o
        # pico recente, o momento mais claro da cena passa a valer brilho
        # cheio. O teto cede devagar para uma cena que escurece de vez nao
        # ficar presa num maximo antigo.
        ganho = {"teto": 0.0}
        CEDE = 0.2
        aux = self._renderizador_teclado()
        # Faixa estreita no meio da cena. A grade do teclado cobre o
        # gabinete inteiro para desenhar a imagem por tecla; para a cor ao
        # vivo isso e ruim, porque a onda atravessa a grade toda e a media
        # volta a ficar parada. Amostrando so uma coluna de LEDs, a onda
        # passa por ela e a cor realmente muda.
        largura = max(0.02, min(float(self.config.get("akko_amostra", 0.09)),
                                0.5))
        faixa = np.abs(aux.canvas.x - 0.5) <= largura
        if not faixa.any():
            faixa = np.ones(aux.canvas.n, dtype=bool)

        def pinta(frame):
            # O teclado e um lugar na cena, nao um resumo dela. Resumir nao
            # funciona: onda que viaja tem energia total constante, entao a
            # media do gabinete fica parada enquanto a luz anda. Avaliando o
            # efeito na propria area do teclado, a onda passa por ele e a
            # cor muda de verdade.
            #
            # Sem a trava do app de proposito: isto roda dentro do laco de
            # render, que ja segura a trava do renderizador, e as rotas da
            # interface pegam as duas na ordem contraria. Tomar a do app aqui
            # travava o render e a interface juntos. So ha leitura simples.
            r = self.renderer
            if r is None or not self.teclado.conectado:
                return
            aux.ctx.t = r.ctx.t
            aux.settings["brightness"] = r.settings["brightness"]
            # as fontes alimentam o contexto do gabinete; sem compartilhar,
            # efeito de musica, tela ou sensor ficaria parado no teclado
            aux.ctx.audio = r.ctx.audio
            aux.ctx.screen = r.ctx.screen
            aux.ctx.sensors = r.ctx.sensors
            quadro = aux.render_once(1.0 / 60.0)
            # Media simples da faixa, sem procurar tom dominante. Numa
            # faixa estreita a media ja e uma cor que existe na cena, e
            # varia de forma continua; o agrupamento por matiz, que serve
            # para resumir a cena inteira, aqui so faria a cor saltar de
            # grupo em grupo enquanto a onda passa.
            media = quadro[faixa].mean(axis=0)
            pico = float(media.max())
            if pico <= 1e-4:
                cru = (0.0, 0.0, 0.0)
            else:
                # O tom vai cheio e a intensidade entra com piso, senao a
                # cena escura apaga o teclado e a clara satura tudo.
                tom = media / pico
                # Resposta linear. Uma curva de expoente menor que um
                # levantaria o fundo e o teclado nunca apagaria, enquanto o
                # gabinete apaga: a respiracao ficaria diferente nos dois.
                ganho["teto"] = max(pico, ganho["teto"] * (1.0 - CEDE / 60.0))
                rel = pico / ganho["teto"] if ganho["teto"] > 1e-4 else 0.0
                # Mesma gama do gabinete. Sem isso a rampa tem formato
                # diferente nos dois lugares: o teclado passa tempo demais
                # na parte clara e a subida nao bate com a do gabinete.
                g = float(r.settings.get("gamma", 2.2))
                curva = bool(g) and abs(g - 1.0) > 1e-3
                forca = min(rel, 1.0) ** g if curva else min(rel, 1.0)
                # O brilho geral vale aqui tambem, pela mesma gama. O ganho
                # automatico acima normaliza a intensidade da cena, entao sem
                # isso o teclado ignorava o slider e seguia aceso depois do
                # botao de apagar os LEDs.
                b = max(0.0, min(float(r.settings.get("brightness", 1.0)), 1.0))
                k = ((piso + (1.0 - piso) * forca) * (b ** g if curva else b)
                     * escala * 255.0)
                cru = tuple(float(v) * k for v in tom)

            agora = time.monotonic()
            if suave["cor"] is None:
                suave["cor"] = list(cru)
            else:
                passo = (1.0 if constante <= 1e-6
                         else min((agora - suave["quando"]) / constante, 1.0))
                suave["cor"] = [c + (a - c) * passo
                                for c, a in zip(suave["cor"], cru)]
            suave["quando"] = agora
            cor = tuple(int(round(v)) for v in suave["cor"])
            self.cor_teclado = cor
            self.teclado.cor_em_fluxo(*cor)

        self.renderer.ambiente = pinta
        self._sincroniza_aux()

    def _sincroniza_aux(self):
        """Copia as camadas da cena para o motor auxiliar do teclado."""
        aux = getattr(self, "_render_teclado", None)
        if aux is None or self.renderer is None:
            return
        with self._lock:
            aux.set_layers([Layer.from_json(l.to_json())
                            for l in self.renderer.layers])

    def imagem_no_teclado(self, atraso: float = 0.8):
        """Desenha a cena nas teclas, como imagem parada.

        Alternativa ao acompanhamento ao vivo, para quem prefere ver o
        desenho do efeito espalhado pelo teclado em vez de uma cor so. Nao
        anima: a camada por tecla reaplica a iluminacao a cada escrita e
        isso pisca, entao ela e refeita apenas quando a cena muda.
        """
        if not self.teclado or not self.teclado.conectado:
            return
        antigo = getattr(self, "_timer_teclado", None)
        if antigo is not None:
            antigo.cancel()

        def aplicar():
            try:
                r = self._renderizador_teclado()
                with self._lock:
                    if self.renderer is None:
                        return
                    r.set_layers([Layer.from_json(l.to_json())
                                  for l in self.renderer.layers])
                    r.settings["brightness"] = self.renderer.settings["brightness"]
                    r.ctx.t = self.renderer.ctx.t
                    r.ctx.audio = self.renderer.ctx.audio
                    r.ctx.screen = self.renderer.ctx.screen
                    r.ctx.sensors = self.renderer.ctx.sensors
                quadro = r.render_once(1.0 / 60.0)
                rgba = r.to_wire(quadro)
                cores = {i: (int(rgba[i][0]), int(rgba[i][1]), int(rgba[i][2]))
                         for i in range(min(len(rgba), r.canvas.n))}
                self.teclado.set_camada(cores)
            except Exception as exc:
                self.status_msg = f"teclado: {exc}"

        t = threading.Timer(atraso, aplicar)
        t.daemon = True
        self._timer_teclado = t
        t.start()

    def _renderizador_teclado(self):
        """Motor auxiliar que avalia a cena na matriz do teclado."""
        from .core.akko import DispositivoTeclado, GEOMETRIA
        from .engine.canvas import device_key

        if getattr(self, "_render_teclado", None) is None:
            dev = DispositivoTeclado()
            layout = {device_key(dev): {"zones": {"0": dict(GEOMETRIA)}}}
            self._render_teclado = Renderer(None, [dev], layout,
                                            {"brightness": 1.0, "gamma": 1.0})
        return self._render_teclado

    def check_elevacao(self) -> dict:
        """Apura se o servidor tem o privilegio que a memoria RAM exige.

        Roda fora do laco de estado, porque consulta processo e agendador
        do Windows. O resultado fica em `self.elevacao` e e de la que a
        interface le.
        """
        from .core import admin
        if sys.platform.startswith("linux"):
            self.elevacao = {"plataforma": "linux", "servidor_elevado": None,
                             "openrgb": self._openrgb_exe()}
            return self.elevacao
        dram = [d for d in (self.renderer.all_devices if self.renderer else [])
                if d.type_name == "DRAM"]
        self.elevacao = {
            "app_admin": admin.sou_admin(),
            "servidor_elevado": admin.openrgb_elevado(),
            "tarefa": admin.tarefa_existe(OPENRGB_TASK),
            "pawnio": admin.pawnio_instalado(),
            "openrgb": self._openrgb_exe(),
            "dram": len(dram),
            "recusado": not self.config.get("elevar_openrgb", True),
        }
        return self.elevacao

    def reparar_elevacao(self) -> dict:
        """Refaz o caminho elevado e reinicia o servidor OpenRGB.

        E o que a interface aciona quando a memoria RAM nao aparece: cria a
        tarefa agendada, derruba o servidor sem privilegio que estava no ar
        e sobe outro no lugar, elevado, reconectando em seguida.

        `_reparando` segura o vigia durante tudo isso: a queda de conexao
        aqui e proposital, e sem a trava o vigia reconectaria no servidor
        velho no meio da troca.
        """
        self._reparando = True
        try:
            return self._reparar_elevacao()
        finally:
            self._reparando = False

    def _reparar_elevacao(self) -> dict:
        from .core import admin
        if sys.platform.startswith("linux"):
            return {"ok": False, "erro": "Configure as permissoes de dispositivos do OpenRGB no Linux"}
        exe = self._openrgb_exe()
        if not exe:
            return {"ok": False, "erro": "OpenRGB nao encontrado"}

        self.config["elevar_openrgb"] = True
        if not admin.tarefa_existe(OPENRGB_TASK):
            r = admin.criar_tarefa(OPENRGB_TASK, exe, OPENRGB_ARGS)
            if r != "ok":
                self.save_config()
                return {"ok": False, "erro": (
                    "o aviso de administrador foi recusado" if r == "recusado"
                    else "nao consegui criar a tarefa agendada"),
                    "elevacao": self.check_elevacao()}
        self.save_config()

        if self.renderer:
            self.renderer.stop()
        self.connected = False
        self.client.close()
        self.status_msg = "reiniciando o OpenRGB com privilegio"
        admin.encerrar_openrgb()

        deadline = time.time() + 10.0
        while _port_open(self.host, self.port) and time.time() < deadline:
            time.sleep(0.3)
        if not admin.rodar_tarefa(OPENRGB_TASK):
            return {"ok": False, "erro": "a tarefa agendada nao rodou",
                    "elevacao": self.check_elevacao()}

        deadline = time.time() + 30.0
        while not _port_open(self.host, self.port) and time.time() < deadline:
            time.sleep(0.5)

        ok = self.connect()
        elev = self.check_elevacao()
        if ok and not elev["dram"]:
            return {"ok": True, "aviso": (
                "o servidor subiu elevado, mas nenhum pente de memoria RGB "
                "apareceu" + ("" if elev["pawnio"] else
                              ": o driver PawnIO nao esta instalado")),
                "elevacao": elev}
        return {"ok": ok, "elevacao": elev}

    def enforce_exclusive(self, forcar: bool = False) -> dict:
        """Fecha os softwares de RGB concorrentes e relata o que caiu.

        A chave da configuracao vale para a abertura. `forcar` e o botao de
        fechar agora, que quem desligou o fechamento automatico usa quando
        quer, e que antes nao fazia nada justamente para essa pessoa.
        """
        from .core import exclusive
        if not forcar and not self.config.get("exclusive_mode", True):
            return {"ok": True, "skipped": True, "fechados": [], "falhou": []}
        r = exclusive.enforce()
        r["openrgb_minimizado"] = exclusive.minimize_openrgb()
        r["ok"] = True
        self.last_exclusive = r
        if r["fechados"]:
            nomes = sorted({c["rotulo"] for c in r["fechados"]})
            self.status_msg = "fechei: " + ", ".join(nomes)
        return r

    def connect(self, exclusive_pass: bool = False, pode_subir: bool = True) -> bool:
        """Conecta no servidor, carrega os dispositivos e monta o renderizador.

        Aplica as contagens de LED salvas antes de montar o canvas, senao o mapa
        sairia com o tamanho errado de cada header. `connecting` fica ligado
        durante a tentativa, para a interface distinguir "ainda tentando" de
        "falhou".

        Uma tentativa por vez: o vigia e o botao de reconectar chegam a
        disparar juntos, e duas conexoes no mesmo cliente trocariam as
        respostas uma da outra no meio do carregamento dos dispositivos.
        """
        with self._conexao:
            if self._encerrando:
                return False
            primeira = self.renderer is None
            if primeira:
                self._primeira_conexao_pendente = True
            self.connecting = True
            try:
                return self._connect(exclusive_pass, pode_subir)
            finally:
                self.connecting = False
                # A primeira falha tambem precisa de vigia: no logon o SDK
                # pode ficar pronto depois do prazo da tentativa inicial.
                if primeira and not self._encerrando:
                    self.start_watchdog()

    def _connect(self, exclusive_pass: bool, pode_subir: bool = True) -> bool:
        if exclusive_pass:
            try:
                r = self.enforce_exclusive()
                # so o aviso da abertura vai para a tela inicial; o botao de
                # fechar agora ja responde na hora
                r["ao_iniciar"] = True
            except Exception as exc:
                self.last_error_exclusive = str(exc)
        self.motivo_conexao = None
        self.erro_conexao = None
        if self.renderer:
            # Nenhum quadro deve sair enquanto o socket e a lista de
            # dispositivos estao sendo trocados pela reconexao.
            self.renderer.stop()
        self.connected = False
        aberto = self.ensure_openrgb(pode_subir=pode_subir)
        for tentativa in range(2):
            try:
                if self._encerrando:
                    return False
                self.client.close()
                self.client.connect()
                devices = self.client.load_devices()
                # O SDK pode aceitar conexoes enquanto ainda descobre a placa,
                # depois da RAM. Espera a lista ficar estavel, com limite para
                # nao prender a abertura caso ela continue mudando.
                def assinatura(lista):
                    return tuple((d.index, device_key(d),
                                  tuple((z.index, z.leds_count) for z in d.zones))
                                 for d in lista)

                prazo = time.monotonic() + 20.0
                anterior = assinatura(devices)
                estavel_desde = time.monotonic() if devices else None
                while not self._encerrando:
                    agora = time.monotonic()
                    if (devices and estavel_desde is not None
                            and agora - estavel_desde >= ESTABILIZACAO_DISPOSITIVOS):
                        break
                    restante = prazo - agora
                    if restante <= 0:
                        break
                    self.status_msg = "OpenRGB detectando hardware"
                    time.sleep(min(1.5, restante))
                    if self._encerrando:
                        break
                    devices = self.client.load_devices()
                    atual = assinatura(devices)
                    if not devices:
                        estavel_desde = None
                    elif atual != anterior or estavel_desde is None:
                        estavel_desde = time.monotonic()
                    anterior = atual
                if self._encerrando:
                    self.client.close()
                    return False
                if not devices:
                    raise OpenRGBError("OpenRGB ainda nao encontrou dispositivos; "
                                       "vou tentar novamente")
                break
            except (OpenRGBError, OSError) as exc:
                self.client.close()
                if tentativa == 0 and self._recuperar_openrgb_inicial(pode_subir):
                    aberto = True
                    continue
                if aberto or self.motivo_conexao is None:
                    self.motivo_conexao = "recusada"
                # O detalhe do Windows fica a parte. Na barra do topo ele
                # quebrava a linha; a tela inicial mostra o motivo completo.
                self.erro_conexao = str(exc)
                self.status_msg = "sem conexao com o OpenRGB"
                return False

        self.connected = True
        self._primeira_conexao_pendente = False
        self.status_msg = "conectado"
        self.motivo_conexao = None
        self.erro_conexao = None
        self._apply_zone_sizes(devices)

        settings = dict(self.config.get("settings") or {})
        settings["enabled_devices"] = self.config.get("enabled_devices") or {}
        if self.renderer is None:
            # Abrir o app e querer luz: o botao de apagar e para a noite, e o
            # PC ligando com o gabinete escuro parece defeito. Volta o ultimo
            # brilho aceso.
            try:
                apagado = float(settings.get("brightness", 1.0)) <= 0.0
            except (TypeError, ValueError):
                apagado = True
            if apagado:
                settings["brightness"] = self._brilho_aceso()
            self.renderer = Renderer(self.client, devices,
                                     self.config.get("layout"), settings)
            self._load_startup_scene()
        else:
            self.renderer.client = self.client
            self.renderer.layout_config = self.config.get("layout") or {}
            self.renderer.settings.update(settings)
            self.renderer.set_devices(devices)
        self.check_elevacao()
        self.renderer.connection_lost = False
        # O estado informado pelo SDK pode nao refletir o hardware apos
        # abrir o OpenRGB. Reaplica o modo direto em cada conexao.
        self.renderer.arm_direct(force=True)
        self._apaga_alem_da_contagem()
        self._liga_teclado()
        self.renderer.start()
        self._sync_sources()
        self._sincroniza_aux()
        self.start_watchdog()
        return True

    def start_watchdog(self):
        """Sobe o vigia que reconecta quando a conexao cai."""
        if self._encerrando:
            return
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog = threading.Thread(target=self._watchdog_loop,
                                          name="spectra-watchdog", daemon=True)
        self._watchdog.start()

    def _vigia_teclado(self):
        """Reabre o teclado Akko que caiu, assim que ele volta a aparecer.

        Vale so para um teclado que ja esteve aberto nesta sessao, e no
        maximo a cada cinco segundos: quem nao tem um nao paga a varredura
        de HID a cada volta do vigia.
        """
        t = self.teclado
        if (t is None or t.conectado or not t.caminho or self.renderer is None
                or not self.config.get("akko_keyboard", True)):
            return
        agora = time.monotonic()
        if agora < self._teclado_proxima:
            return
        self._teclado_proxima = agora + 5.0
        try:
            self._liga_teclado()
        except Exception as exc:
            self.status_msg = f"teclado: {exc}"

    def _watchdog_loop(self):
        delay = 2.0
        while not self._watchdog_stop.wait(delay):
            if self._gravar_pendente:
                try:
                    self.save_config()
                except Exception:
                    pass
            self._vigia_teclado()
            r = self.renderer
            if r is None and not self._primeira_conexao_pendente:
                continue
            # o assistente de descoberta e o reparo de privilegio mexem na
            # conexao de proposito; o vigia nao pode disputar com eles, nem
            # com uma conexao que ja esta em andamento
            if (getattr(self, "_probe_session", None) is not None
                    or self._reparando or self.connecting):
                delay = 2.0
                continue
            alive = bool(r and r._thread and r._thread.is_alive())
            if self.connected and alive and not r.connection_lost:
                delay = 2.0
                continue

            self.connected = False
            self.status_msg = ("tentando a primeira conexao com o OpenRGB"
                               if self._primeira_conexao_pendente else
                               "conexao com o OpenRGB caiu; reconectando")
            try:
                ok = self.connect(pode_subir=self._primeira_conexao_pendente)
            except Exception as exc:
                # Erro fora do previsto nao pode matar o vigia: sem ele, a
                # proxima queda do OpenRGB nunca mais seria reconectada.
                self.status_msg = f"falha ao reconectar: {exc}"
                ok = False
            if ok:
                self.reconnects += 1
                self.status_msg = f"reconectado ({self.reconnects}x)"
                delay = 2.0
            else:
                delay = min(delay * 1.7, 20.0)

    def _apply_zone_sizes(self, devices):
        sizes = self.config.get("zone_sizes") or {}
        changed = False
        for dev in devices:
            key = device_key(dev)
            for zone in dev.zones:
                want = sizes.get(f"{key}:{zone.index}")
                if want is None or int(want) == zone.leds_count:
                    continue
                if zone.leds_min == zone.leds_max:
                    continue
                try:
                    self.client.resize_zone(dev.index, zone.index, int(want))
                    changed = True
                except OpenRGBError:
                    pass
        if changed:
            time.sleep(0.6)
            try:
                devices[:] = self.client.load_devices()
            except OpenRGBError:
                pass

    def _apaga_alem_da_contagem(self):
        """Apaga os LEDs que ficam depois da contagem de cada conector ARGB.

        Conector de 3 pinos e via unica: o controlador so manda dado ate a
        contagem configurada, e o LED que vem depois guarda a ultima cor que
        recebeu, em geral o efeito da placa-mae no boot. Era a luz da placa de
        video presa numa cor com todo o resto apagado. Estica cada zona ate o
        teto, manda preto e volta a contagem de antes.
        """
        r = self.renderer
        esticadas = []
        for dev in r.all_devices:
            if not r.direct_ok.get(dev.index):
                continue
            for zone in dev.zones:
                if zone.leds_min == zone.leds_max:
                    continue
                teto = min(zone.leds_max, TETO_LIMPEZA_CAUDA)
                antes = zone.leds_count
                if teto <= antes:
                    continue
                try:
                    self.client.resize_zone(dev.index, zone.index, teto)
                except OpenRGBError:
                    continue
                esticadas.append((dev.index, zone.index, antes))
                try:
                    self.client.update_zone_leds(
                        dev.index, zone.index, b"\x00\x00\x00\x00" * teto, teto)
                except OpenRGBError:
                    pass
        if not esticadas:
            return
        time.sleep(ESPERA_LIMPEZA_CAUDA)
        voltou = True
        for di, zi, antes in esticadas:
            try:
                self.client.resize_zone(di, zi, antes)
            except OpenRGBError:
                voltou = False
        if not voltou:
            # Zona que ficou esticada no servidor desalinha o mapa inteiro
            # do dispositivo; o renderizador passa a usar a lista real.
            try:
                r.set_devices(self.client.load_devices())
            except OpenRGBError:
                pass

    def _load_startup_scene(self):
        """Poe no ar a cena da sessao anterior.

        So as camadas. Brilho, gama e taxa de quadros sao ajustes globais e
        ja vieram da configuracao; carregar os de um perfil aqui desfazia
        todo ajuste feito depois de salvar esse perfil. Faltando a cena
        gravada, como na primeira abertura depois de atualizar, vale o
        ultimo perfil e, sem ele, o preset de partida.
        """
        cena = self.config.get("cena")
        camadas = cena.get("layers") if isinstance(cena, dict) else None
        if isinstance(camadas, list) and camadas:
            try:
                self.renderer.set_layers([Layer.from_json(d) for d in camadas])
                return
            except Exception:
                # cena gravada com formato estranho nao pode impedir a abertura
                pass
        name = self.config.get("last_profile")
        if name and self.load_profile(name, apply_only=True):
            return
        p = ps.by_id(PRESET_INICIAL)
        camadas = p.scene()["layers"] if p else DEFAULT_SCENE["layers"]
        self.renderer.set_layers([Layer.from_json(d) for d in camadas])
        self.config["last_preset"] = p.id if p else None
        self.config["perfil_atual"] = None

    def shutdown(self, blank=True):
        """Encerra tudo em ordem, apagando os LEDs por padrao."""
        self._encerrando = True
        self._watchdog_stop.set()
        try:
            self.save_config()
        except Exception:
            pass
        for src in (self.audio, self.screen, self.sensors):
            if src:
                try:
                    src.stop()
                except Exception:
                    pass
        if self.renderer:
            self.renderer.stop()
            if blank:
                self.renderer.blank()
        if self.teclado:
            try:
                if blank:
                    self.teclado.apagar()
                self.teclado.fechar()
            except Exception:
                pass
        self.client.close()

    def _needed_sources(self) -> set:
        need = set()
        if not self.renderer:
            return need
        for layer in self.renderer.layers:
            if not layer.enabled:
                continue
            d = fx.get(layer.effect_id)
            if d:
                need.update(d.needs)
        return need

    def _liga_fonte(self, kind: str, src):
        """Liga uma fonte parada, sem insistir a cada mudanca de camada.

        Abrir captura que vai falhar custa caro: o PortAudio sozinho leva
        centenas de milissegundos enumerando dispositivos, e isto roda com a
        trava do app a cada passo de slider. Depois de uma falha, a proxima
        tentativa espera alguns segundos.
        """
        if src.running or time.monotonic() < self._fonte_espera.get(kind, 0.0):
            return
        if not src.start():
            self._fonte_espera[kind] = time.monotonic() + 5.0

    def _sync_sources(self):
        # A trava vem aqui dentro porque a conexao e a carga de perfil chamam
        # isto sem ela. Duas chamadas juntas viam a fonte ainda vazia e
        # criavam uma cada: a que sobrava seguia capturando para sempre, sem
        # ninguem que a parasse.
        with self._lock:
            self._sync_sources_travado()

    def _sync_sources_travado(self):
        if self.renderer is None:
            # configurar a fonte antes da primeira conexao so grava a escolha
            return
        need = self._needed_sources()
        ctx = self.renderer.ctx

        if "audio" in need:
            if self.audio is None:
                cfg = self.config.get("sources", {}).get("audio") or {}
                self.audio = AudioSource(ctx.audio, device_index=cfg.get("device"),
                                         device_name=cfg.get("nome"))
            self._liga_fonte("audio", self.audio)
        elif self.audio and self.audio.running:
            self.audio.stop()

        if "screen" in need:
            cfg = (self.config.get("sources", {}).get("screen") or {})
            if self.screen is None:
                self.screen = ScreenSource(ctx.screen,
                                           output_idx=cfg.get("output", 0),
                                           fps=cfg.get("fps", 30))
            self._liga_fonte("screen", self.screen)
        elif self.screen and self.screen.running:
            self.screen.stop()

        if "sensors" in need:
            if self.sensors is None:
                self.sensors = SensorSource(ctx.sensors, dll_path=_dll_sensores())
            self._liga_fonte("sensors", self.sensors)
        elif self.sensors and self.sensors.running:
            self.sensors.stop()

    def _sensores_possiveis(self) -> set:
        """Leituras que a fonte de sensores consegue entregar agora."""
        s = self.sensors
        if s is None or not s.running:
            return set()
        if s.available:
            return set(s.available)
        # logo depois de ligar, antes da primeira volta de leitura, vale o
        # que cada biblioteca sabe ler
        out = set()
        if s.psutil_ok:
            out |= {"cpu_load", "ram_load"}
        if s.lhm_ok:
            out |= SENSORES_LHM | {"cpu_load", "ram_load"}
        return out

    def _erro_sensores(self, faltam) -> str:
        s = self.sensors
        oque = " e ".join(ROTULO_SENSOR.get(k, k) for k in sorted(faltam))
        if sys.platform.startswith("linux"):
            return f"esta maquina nao informa {oque} pelos sensores disponiveis"
        if s is not None and not s.lhm_ok and set(faltam) & SENSORES_LHM:
            dll = s.lhm.dll_path
            if not os.path.isfile(dll):
                return (f"sem {oque}: falta a LibreHardwareMonitorLib.dll em "
                        + os.path.dirname(dll))
            return f"sem {oque}: a biblioteca de sensores nao abriu ({s.lhm.error})"
        return f"esta maquina nao informa {oque}"

    def _problema_da_camada(self, layer) -> str | None:
        """Diz por que uma camada ligada esta sem o dado de que precisa.

        Sem isso, aplicar o Ambilight numa maquina em que a captura de tela
        falha dizia "ligando tela" e deixava o gabinete parado sem
        explicacao. Nos sensores conta tambem qual leitura a camada usa: sem
        a DLL so ha uso de CPU e RAM, e um efeito de temperatura ficava azul
        para sempre com a fonte marcada como ativa.
        """
        if not layer.enabled:
            return None
        d = fx.get(layer.effect_id)
        if d is None:
            return None
        for kind in d.needs:
            src = {"audio": self.audio, "screen": self.screen,
                   "sensors": self.sensors}.get(kind)
            if src is None or not src.running:
                erro = getattr(src, "error", None) or "nao ligou"
                return f"{ROTULO_FONTE.get(kind, kind)} indisponivel: {erro}"
            if kind == "sensors":
                faltam = (sensores_da_camada(layer.effect_id, layer.params)
                          - self._sensores_possiveis())
                if faltam:
                    return self._erro_sensores(faltam)
        return None

    def _avisos_das_camadas(self) -> dict:
        if not self.renderer:
            return {}
        out = {}
        for layer in list(self.renderer.layers):
            msg = self._problema_da_camada(layer)
            if msg:
                out[layer.id] = msg
        return out

    def set_layers(self, layers_json, preset="keep", perfil=None):
        """Troca a pilha de camadas inteira, a partir do que veio da interface.

        `preset` diz qual cena pronta essa pilha representa: None marca cena
        personalizada, um id marca o preset, e "keep" deixa como estava. E o
        que permite desfazer a aplicacao de um preset sem a vitrine continuar
        apontando para ele. `perfil` faz o mesmo para o desfazer de carregar
        um perfil, e vale junto com `preset`.
        """
        with self._lock:
            self.renderer.set_layers([Layer.from_json(d) for d in layers_json])
            if preset != "keep":
                self.config["last_preset"] = preset
                self.config["perfil_atual"] = perfil if isinstance(perfil, str) else None
                self.save_config()
            else:
                self._cena_mudou()
            self._sync_sources()
            self._sincroniza_aux()

    def add_layer(self, effect_id: str, **kw):
        """Acrescenta uma camada com o efeito pedido.

        `acima_de` poe a camada logo acima de outra, pelo id. E o que o
        duplicar usa: no topo da pilha, a copia de uma camada de fundo
        cobria todas as outras e a cena mudava inteira.
        """
        with self._lock:
            d = fx.get(effect_id)
            layer = Layer(effect_id, kw.get("params"), kw.get("blend", "normal"),
                          kw.get("opacity", 1.0), True, kw.get("targets"),
                          kw.get("name") or (d.label if d else effect_id))
            indice = None
            ref = kw.get("acima_de")
            if ref:
                pos = next((i for i, l in enumerate(self.renderer.layers)
                            if l.id == ref), None)
                if pos is not None:
                    indice = pos + 1
            self.renderer.add_layer(layer, indice)
            self._cena_mudou()
            self._sync_sources()
            self._sincroniza_aux()
            return layer.to_json()

    def update_layer(self, layer_id: str, patch: dict):
        """Aplica mudancas numa camada existente.

        A camada e o mesmo objeto que o laco de render esta desenhando, entao
        a mudanca entra com a trava do renderizador. Sem ela, trocar o efeito
        limpava o estado no meio de um quadro, e parametro novo mudava o
        dicionario enquanto o render o percorria: o erro caia no tratamento
        de efeito defeituoso e a camada era desligada sozinha.
        """
        with self._lock:
            with self.renderer._lock:
                layer = self.renderer.get_layer(layer_id)
                if not layer:
                    return None
                if "effect" in patch and patch["effect"] != layer.effect_id:
                    antigo, novo = fx.get(layer.effect_id), fx.get(patch["effect"])
                    # O nome que so repetia o efeito acompanha a troca; sem
                    # isso a camada que virou Fogo seguia listada como a onda
                    # de antes. Nome dado pela pessoa fica como esta. Sem
                    # diferenca de maiuscula: a barra de cor unica nomeia a
                    # camada "Cor unica", e o efeito se chama "Cor Unica".
                    if (novo is not None and "name" not in patch
                            and (not layer.name
                                 or (antigo is not None and str(layer.name).casefold()
                                     == antigo.label.casefold()))):
                        layer.name = novo.label
                    layer.effect_id = patch["effect"]
                    layer.params = {}
                    layer.state.clear()
                if "params" in patch:
                    layer.params.update(patch["params"])
                for k, attr in (("blend", "blend"), ("name", "name")):
                    if k in patch:
                        setattr(layer, attr, patch[k])
                # mesmos tipos que o construtor da camada garante: opacidade
                # em texto quebrava a comparacao no laco de render, que morria
                # a cada quadro e deixava o vigia reconectando sem fim
                if "opacity" in patch:
                    layer.opacity = float(patch["opacity"])
                if "enabled" in patch:
                    layer.enabled = bool(patch["enabled"])
                if "targets" in patch:
                    layer.targets = list(patch["targets"] or [])
                    layer._mask_key = None
            # fora da trava do renderizador: abrir captura de audio leva
            # centenas de milissegundos, e o gabinete congelaria esse tempo
            self._cena_mudou()
            self._sync_sources()
            self._sincroniza_aux()
            return layer.to_json()

    def remove_layer(self, layer_id: str):
        """Tira uma camada pelo id."""
        with self._lock:
            self.renderer.remove_layer(layer_id)
            self._cena_mudou()
            self._sync_sources()
            self._sincroniza_aux()

    def reorder_layers(self, order):
        """Reordena as camadas conforme a lista de ids.

        Camada que a lista nao cita, como uma adicionada enquanto o pedido
        viajava, vai para o topo em vez de sumir, e id repetido conta uma
        vez so: a mesma camada duas vezes na pilha dividiria o estado.
        """
        with self._lock:
            by_id = {l.id: l for l in self.renderer.layers}
            nova, vistos = [], set()
            for i in order:
                if i in by_id and i not in vistos:
                    vistos.add(i)
                    nova.append(by_id[i])
            nova += [l for l in self.renderer.layers if l.id not in vistos]
            self.renderer.set_layers(nova)
            self._cena_mudou()
            self._sincroniza_aux()

    def _brilho_aceso(self) -> float:
        """O ultimo brilho diferente de zero, para acender depois de apagar."""
        try:
            b = float(self.config.get("brilho_aceso") or 1.0)
        except (TypeError, ValueError):
            b = 1.0
        return min(1.0, b) if b > 0 else 1.0

    def update_settings(self, patch: dict):
        """Altera brilho, gama, taxa de quadros e afins."""
        with self._lock:
            for k in ("brightness", "gamma", "fps", "smoothing", "paused"):
                if k in patch and self.renderer:
                    self.renderer.settings[k] = patch[k]
            if "brightness" in patch:
                try:
                    b = float(patch["brightness"])
                except (TypeError, ValueError):
                    b = 0.0
                if b > 0:
                    self.config["brilho_aceso"] = b
            for k in ("exclusive_mode", "autostart_openrgb"):
                if k in patch:
                    self.config[k] = bool(patch[k])
            if "enabled_devices" in patch and self.renderer:
                antes = self.renderer.settings.get("enabled_devices") or {}
                novo = patch["enabled_devices"] or {}
                self.renderer.settings["enabled_devices"] = novo
                self.config["enabled_devices"] = novo
                with self.renderer._lock:
                    self.renderer.rebuild()
                    self._apaga_desligados(antes, novo)
                self.renderer.arm_direct()
            # com o render pausado o laco nao envia nada, entao mudar o brilho
            # nao apareceria no gabinete ate despausar; um empurrao resolve
            if ("brightness" in patch and self.renderer
                    and self.renderer.settings.get("paused")
                    and self.renderer.frame is not None):
                try:
                    self.renderer.push(self.renderer.frame)
                except OpenRGBError:
                    pass
                # o teclado so recebe cor do laco, que esta parado: sem o
                # empurrao dele o apagar deixava o teclado aceso
                amb = self.renderer.ambiente
                if amb is not None:
                    try:
                        amb(self.renderer.frame)
                    except Exception:
                        pass
            self.save_config()

    def _apaga_desligados(self, antes: dict, novo: dict):
        """Manda preto para o dispositivo que acabou de sair do controle.

        Fora do canvas ele nao recebe mais nada, e ficava congelado no ultimo
        quadro para sempre. Roda com a trava do renderizador, depois de
        remontar: um quadro em andamento terminaria por cima do preto.
        """
        for dev in self.renderer.all_devices:
            key = device_key(dev)
            if antes.get(key) is False or novo.get(key) is not False:
                continue
            n = dev.led_count
            if not n:
                continue
            try:
                self.client.update_leds(dev.index, b"\x00\x00\x00\x00" * n, n)
            except OpenRGBError:
                pass

    def set_zone_geometry(self, device_key_: str, zone_index: int, geometry):
        """Salva onde uma zona fica no mapa do gabinete.

        Geometria nula apaga a da zona, que volta ao posicionamento
        automatico.
        """
        with self._lock:
            layout = self.config.setdefault("layout", {})
            dev = layout.setdefault(device_key_, {}).setdefault("zones", {})
            if geometry is None:
                dev.pop(str(zone_index), None)
            else:
                dev[str(zone_index)] = geometry
            self.renderer.layout_config = layout
            self.renderer.rebuild()
            self.save_config()

    def reset_layout(self) -> dict:
        """Descarta o mapa salvo e volta ao posicionamento automatico.

        Devolve o mapa que existia, para a interface oferecer desfazer: um
        clique ali apagava de uma vez o que o assistente montou.
        """
        with self._lock:
            anterior = self.config.get("layout") or {}
            self.config["layout"] = {}
            self.renderer.layout_config = {}
            self.renderer.rebuild()
            self.save_config()
            return anterior

    def set_layout(self, layout) -> dict:
        """Troca o mapa inteiro, como no desfazer do restaurar automatico."""
        ok = isinstance(layout, dict) and all(
            isinstance(d, dict) and isinstance(d.get("zones", {}), dict)
            for d in layout.values())
        if not ok:
            # o canvas le cada dispositivo como dicionario; outra coisa ali
            # derrubaria a montagem dele
            return {"ok": False, "error": "mapa ilegivel"}
        with self._lock:
            self.config["layout"] = layout
            self.renderer.layout_config = layout
            self.renderer.rebuild()
            self.save_config()
        return {"ok": True}

    def resize_zones(self, changes, persist: bool = True):
        """Aplica varias contagens de LED de uma vez e recarrega uma unica vez.

        Fazer isso em lote importa: cada recarga de dispositivo faz o
        controlador reaplicar o modo, e uma sequencia delas aparece como piscada
        no gabinete inteiro.
        """
        with self._lock:
            touched = False
            for device_key_, zone_index, size in changes:
                dev = next((d for d in self.renderer.all_devices
                            if device_key(d) == device_key_), None)
                if dev is None:
                    continue
                zone = next((z for z in dev.zones if z.index == zone_index), None)
                if zone is None or zone.leds_count == int(size):
                    continue

                if zone.leds_count > int(size):
                    try:
                        self.client.update_zone_leds(
                            dev.index, zone_index,
                            b"\x00\x00\x00\x00" * zone.leds_count,
                            zone.leds_count)
                    except OpenRGBError:
                        pass
                try:
                    self.client.resize_zone(dev.index, zone_index, int(size))
                    touched = True
                except OpenRGBError as exc:
                    return {"ok": False, "error": str(exc)}
                if persist:
                    self.config.setdefault("zone_sizes", {})[
                        f"{device_key_}:{zone_index}"] = int(size)

            if persist:
                self.save_config()
            if not touched:
                return {"ok": True, "changed": False}

            time.sleep(0.6)
            try:
                devices = self.client.load_devices()
            except OpenRGBError as exc:
                return {"ok": False, "error": str(exc)}
            self.renderer.set_devices(devices)
            self.renderer.arm_direct()
            return {"ok": True, "changed": True}

    def resize_zone(self, device_key_: str, zone_index: int, size,
                    persist: bool = True):
        """Aplica a contagem de LEDs de uma zona so.

        E a porta da contagem digitada, e por isso confere antes de escrever:
        campo vazio chegava como nulo e voltava erro de Python, e "900" num
        conector de ate 512 passava sem conferencia e ficava gravado. O teto
        de 512 e o mesmo do campo da interface.
        """
        try:
            size = int(size)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Digite quantos LEDs esse conector tem"}
        with self._lock:
            _dev, zone = self._find_zone(device_key_, zone_index)
        if zone is not None:
            # zero passa quando o conector aceita: e o "nada plugado aqui"
            teto = min(zone.leds_max, 512)
            if not zone.leds_min <= size <= teto:
                return {"ok": False, "error": (
                    f"{zone.name}: digite de {max(zone.leds_min, 1)} a {teto}")}
        return self.resize_zones([(device_key_, zone_index, size)], persist)

    def _probe_open_session(self, probe_max: int):
        # zona piscando agora pausou o render so por uns segundos; o estado
        # que vale e o de antes dela, senao o render ficaria parado de vez
        # quando o assistente terminasse
        if self._identify_until > time.time():
            antes = self._identify_was_paused
        else:
            antes = bool(self.renderer.settings.get("paused"))
        sess = {"sizes": {}, "commits": {}, "was_paused": antes}
        self.renderer.settings["paused"] = True
        time.sleep(0.08)

        changes = []
        for z in self.resizable_zones():
            sess["sizes"][f"{z['device']}:{z['zone']}"] = z["count"]
            changes.append((z["device"], z["zone"],
                            int(min(z["max"], max(probe_max, 1)))))
        self.resize_zones(changes, persist=False)

        self.renderer.blank()
        self._probe_session = sess
        return sess

    def probe_start(self, device_key_: str, zone_index: int,
                    probe_max: int = 256):
        """Abre uma sessao de descoberta numa zona, com o maximo a testar."""
        with self._lock:
            dev = next((d for d in self.renderer.all_devices
                        if device_key(d) == device_key_), None)
            if dev is None:
                return {"ok": False, "error": "device nao encontrado"}
            zone = next((z for z in dev.zones if z.index == zone_index), None)
            if zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            if zone.leds_min == zone.leds_max:
                return {"ok": False, "error": "esta zona tem tamanho fixo"}

            if getattr(self, "_probe_session", None) is None:
                self._probe_open_session(probe_max)
            else:
                self.renderer.blank()

            zone = next(z for z in next(
                d for d in self.renderer.all_devices
                if device_key(d) == device_key_).zones if z.index == zone_index)
            n = zone.leds_count
            if n == 0:
                return {"ok": False, "error": "nao consegui expandir esta zona"}

            self._probe = {"device": device_key_, "zone": zone_index, "n": n}
            self.probe_paint(1, "fill")
            return {"ok": True, "probe_max": n}

    def probe_paint(self, count: int, mode: str = "fill"):
        """Acende uma quantidade de LEDs, para a pessoa conferir no gabinete."""
        pr = getattr(self, "_probe", None)
        if not pr:
            return {"ok": False, "error": "nenhuma descoberta em andamento"}
        dev = next((d for d in self.renderer.all_devices
                    if device_key(d) == pr["device"]), None)
        if dev is None:
            return {"ok": False, "error": "device sumiu"}
        zone = next((z for z in dev.zones if z.index == pr["zone"]), None)
        if zone is None or zone.leds_count == 0:
            return {"ok": False, "error": "zona sem leds"}

        n = zone.leds_count
        k = int(max(0, min(count, n)))
        buf = np.zeros((n, 4), dtype=np.uint8)
        if mode == "dot":
            if k > 0:
                buf[k - 1, :3] = (255, 255, 255)
        elif mode == "ruler":
            for i in range(n):
                if i % 10 == 9:
                    buf[i, :3] = (255, 255, 255)
                else:
                    buf[i, :3] = (0, 140, 255) if (i // 10) % 2 == 0 else (255, 60, 0)
        else:
            if k > 0:
                buf[:k, :3] = (0, 110, 255)
                buf[k - 1, :3] = (255, 255, 255)
        try:
            self.client.update_zone_leds(dev.index, zone.index, buf.tobytes(), n)
        except OpenRGBError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "count": k, "of": n}

    def probe_stop(self, commit=None):
        """Fecha a sessao de descoberta, gravando a contagem se houver."""
        with self._lock:
            pr = getattr(self, "_probe", None)
            if not pr:
                return {"ok": False, "error": "nenhuma descoberta em andamento"}
            sess = getattr(self, "_probe_session", None)
            if sess is not None and commit:
                sess["commits"][f"{pr['device']}:{pr['zone']}"] = int(commit)
            self._probe = None
            if sess is not None:
                self.renderer.blank()
            return {"ok": True, "committed": int(commit) if commit else None}

    def probe_commit(self, device_key_: str, zone_index: int, count: int):
        """Grava a contagem descoberta para uma zona."""
        with self._lock:
            sess = getattr(self, "_probe_session", None)
            if sess is None:
                return {"ok": False, "error": "nenhuma sondagem em andamento"}
            sess["commits"][f"{device_key_}:{zone_index}"] = int(count)
            return {"ok": True}

    def probe_finish(self):
        """Encerra o assistente, aplicando tudo que foi descoberto.

        Grava contagens, planos de peca e o inventario respondido, e remonta o
        canvas com o resultado.
        """
        with self._lock:
            sess = getattr(self, "_probe_session", None)
            self._probe = None
            if sess is None:
                return {"ok": True, "applied": {}}
            self._probe_session = None

            applied = {}
            keep, restore = [], []
            for key, before in sess["sizes"].items():
                dev_key, _, zi = key.rpartition(":")
                new = sess["commits"].get(key)
                if new is not None:
                    keep.append((dev_key, int(zi), int(new)))
                    applied[key] = int(new)
                else:
                    restore.append((dev_key, int(zi), int(before)))
            if keep:
                self.resize_zones(keep, persist=True)
            if restore:
                self.resize_zones(restore, persist=False)

            self.renderer.blank()
            self.renderer.settings["paused"] = sess["was_paused"]
            return {"ok": True, "applied": applied}

    def set_source_config(self, kind: str, cfg: dict) -> dict:
        """Reconfigura uma fonte externa, como o dispositivo de audio.

        Devolve se a captura abriu. Antes a interface dizia "atualizada" em
        todo caso, e o dispositivo que falhava so aparecia trocando de aba.
        """
        with self._lock:
            self.config.setdefault("sources", {})[kind] = cfg
            self.save_config()
            # configuracao nova merece tentativa na hora, sem a espera da falha
            self._fonte_espera.pop(kind, None)
            src = {"audio": self.audio, "screen": self.screen}.get(kind)
            if src:
                src.stop()
            if kind == "audio":
                self.audio = None
            elif kind == "screen":
                self.screen = None
            self._sync_sources()
            self._sincroniza_aux()
            src = {"audio": self.audio, "screen": self.screen}.get(kind)
            if src is None:
                # nenhuma camada usa a fonte agora: a escolha vale quando usar
                return {"ok": True, "running": False, "em_uso": False}
            if not src.running:
                erro = getattr(src, "error", None) or "motivo desconhecido"
                return {"ok": False, "running": False, "em_uso": True,
                        "error": f"a captura nao abriu: {erro}"}
            return {"ok": True, "running": True, "em_uso": True}

    def apply_preset(self, preset_id: str):
        """Carrega uma cena pronta pelo id.

        Devolve em `falhou` o que a cena pede e nao esta chegando, para a
        interface avisar na hora em vez de dizer que ligou a fonte.
        """
        p = ps.by_id(preset_id)
        if p is None:
            return {"ok": False, "error": "preset desconhecido"}
        with self._lock:
            self.renderer.load_scene(p.scene())
            self.config["last_preset"] = preset_id
            self.config["perfil_atual"] = None
            self._sync_sources()
            self._sincroniza_aux()
            self.save_config()
            falhou = sorted(set(self._avisos_das_camadas().values()))
        return {"ok": True, "name": p.name, "needs": list(p.needs),
                "falhou": falhou}

    def setup_todo(self) -> list:
        """Lista o que ainda falta configurar, para a interface avisar."""
        return [z for z in self.resizable_zones() if z["count"] == 0]

    def resizable_zones(self) -> list:
        """Lista as zonas cuja contagem de LEDs pode ser informada."""
        out = []
        if not self.renderer:
            return out
        for dev in self.renderer.all_devices:
            key = device_key(dev)
            for z in dev.zones:
                if z.leds_min != z.leds_max:
                    out.append({"device": key, "device_name": dev.name,
                                "zone": z.index, "zone_name": z.name,
                                "count": z.leds_count,
                                "max": min(z.leds_max, 512)})
        return out

    def _find_zone(self, device_key_: str, zone_index: int):
        dev = next((d for d in self.renderer.all_devices
                    if device_key(d) == device_key_), None)
        if dev is None:
            return None, None
        zone = next((z for z in dev.zones if z.index == zone_index), None)
        return dev, zone

    def _paint_zone(self, dev, zone, buf) -> bool:
        try:
            self.client.update_zone_leds(dev.index, zone.index, buf.tobytes(),
                                         zone.leds_count)
            return True
        except OpenRGBError:
            return False

    def probe_multi_start(self, probe_max: int = 256):
        """Abre uma sessao de descoberta cobrindo varias zonas ao mesmo tempo."""
        with self._lock:
            if getattr(self, "_probe_session", None) is None:
                self._probe_open_session(probe_max)
            else:
                self.renderer.blank()
            antes = self._probe_session["sizes"]
            zones = []
            for z in self.resizable_zones():
                chave = f"{z['device']}:{z['zone']}"
                # `antes` e a contagem de antes da sondagem, que o conferir
                # usa para abrir direto na conferencia sem contar de novo
                zones.append({"device": z["device"], "zone": z["zone"],
                              "zone_name": z["zone_name"],
                              "device_name": z["device_name"],
                              "max": z["count"],
                              "antes": antes.get(chave, z["count"])})
            if not zones:
                return {"ok": False, "error": "nenhum conector ajustavel"}
            return {"ok": True, "zones": zones}

    def probe_multi_paint(self, items):
        """Acende faixas em varias zonas de uma vez, um passo da busca."""
        with self._lock:
            if getattr(self, "_probe_session", None) is None:
                return {"ok": False, "error": "nenhuma sondagem em andamento"}
            self.renderer.blank()
            painted = []
            for it in items or []:
                dev, zone = self._find_zone(it["device"], int(it["zone"]))
                if dev is None or zone is None or zone.leds_count == 0:
                    continue
                idx = int(it["index"]) - 1
                if not (0 <= idx < zone.leds_count):
                    continue
                r, g, b = (int(v * 255) for v in hex_to_rgb(it.get("color", "#ffffff")))
                buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
                if it.get("tail", True):
                    buf[idx:, :3] = (r, g, b)
                else:
                    buf[idx, :3] = (r, g, b)
                if self._paint_zone(dev, zone, buf):
                    painted.append({"zone": zone.name, "index": idx + 1})
            return {"ok": True, "painted": painted}

    def probe_split_preview(self, device_key_: str, zone_index: int,
                            seg_size: int, total: int):
        """Mostra como uma zona ficaria dividida entre varias pecas."""
        with self._lock:
            dev, zone = self._find_zone(device_key_, zone_index)
            if dev is None or zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            self.renderer.blank()
            palette = [(255, 40, 90), (0, 190, 255), (140, 255, 40),
                       (255, 190, 0), (170, 90, 255), (0, 255, 190)]
            buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
            seg_size = max(1, int(seg_size))
            n = min(int(total), zone.leds_count)
            for i in range(n):
                buf[i, :3] = palette[(i // seg_size) % len(palette)]
            self._paint_zone(dev, zone, buf)
            return {"ok": True, "segments": (n + seg_size - 1) // seg_size}

    def probe_isolate(self, device_key_: str, zone_index: int, start: int,
                      count: int, color: str = "#ffffff"):
        """Acende so um trecho de uma zona, para identificar a peca."""
        with self._lock:
            dev, zone = self._find_zone(device_key_, zone_index)
            if dev is None or zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            self.renderer.blank()
            r, g, b = (int(v * 255) for v in hex_to_rgb(color))
            buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
            a = max(0, int(start))
            z = min(zone.leds_count, a + max(1, int(count)))
            buf[a:z, :3] = (r, g, b)
            self._paint_zone(dev, zone, buf)
            return {"ok": True, "lit": z - a}

    def identify_zone(self, device_key_: str, zone_index: int,
                      seconds: float = 1.6, color: str = "#ffffff"):
        """Acende uma zona sozinha por alguns segundos, para achar a peca.

        Pausa o render, pinta so aquela zona e agenda a retomada. Chamadas em
        sequencia estendem o prazo em vez de retomar cedo, entao clicar em
        varias zonas seguidas nao deixa o gabinete piscando entre elas.
        """
        with self._lock:
            if not self.renderer:
                return {"ok": False, "error": "sem renderizador"}
            dev, zone = self._find_zone(device_key_, zone_index)
            if dev is None or zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            if getattr(self, "_probe_session", None) is not None:
                return {"ok": False, "error": "assistente em andamento"}
            r = self.renderer
            if self._identify_until <= time.time():
                self._identify_was_paused = bool(r.settings.get("paused"))
            self._identify_until = time.time() + max(0.3, float(seconds))
            r.settings["paused"] = True
        time.sleep(0.07)
        with self._lock:
            r.blank()
            cr, cg, cb = (int(v * 255) for v in hex_to_rgb(color))
            buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
            buf[:, :3] = (cr, cg, cb)
            self._paint_zone(dev, zone, buf)

        def restore():
            while True:
                left = self._identify_until - time.time()
                if left <= 0:
                    break
                time.sleep(min(left, 0.2))
            with self._lock:
                if self._identify_until > time.time():
                    return
                if getattr(self, "_probe_session", None) is None:
                    self.renderer.settings["paused"] = self._identify_was_paused
                self._identify_until = 0.0

        threading.Thread(target=restore, daemon=True,
                         name="spectra-identify").start()
        return {"ok": True, "lit": zone.leds_count, "seconds": seconds}

    def set_zone_plan(self, device_key_: str, zone_index: int, parts):
        """Grava em quantas pecas uma zona se divide e o que cada uma e.

        E o que separa seis fans pendurados num header so em seis unidades
        independentes para os efeitos.
        """
        with self._lock:
            geo_parts = []
            spots_used = {}
            for p in parts or []:
                cnt = int(p.get("count", 0))
                if cnt <= 0:
                    continue
                spot = p.get("spot", "meio")
                x, y = CASE_SPOTS.get(spot, CASE_SPOTS["meio"])
                k = spots_used.get(spot, 0)
                spots_used[spot] = k + 1
                if k:
                    x = min(0.96, max(0.04, x + 0.16 * (1 if k % 2 else -1) * ((k + 1) // 2)))

                if p.get("kind") == "cable":
                    vertical = spot.startswith("frente") or spot == "traseira"
                    comp = 0.30
                    if vertical:
                        geo_parts.append({
                            "shape": "cable", "kind": "strip", "count": cnt,
                            "lanes": int(p.get("lanes", 12)),
                            "x1": x, "y1": max(0.03, y - comp),
                            "x2": x, "y2": min(0.97, y + comp),
                            "width": 0.14, "order": p.get("order", "lane")})
                    else:
                        geo_parts.append({
                            "shape": "cable", "kind": "strip", "count": cnt,
                            "lanes": int(p.get("lanes", 12)),
                            "x1": max(0.03, x - comp), "y1": y,
                            "x2": min(0.97, x + comp), "y2": y,
                            "width": 0.14, "order": p.get("order", "lane")})
                elif p.get("kind") == "strip":
                    vertical = spot.startswith("frente") or spot == "traseira"
                    if vertical:
                        geo_parts.append({"shape": "line", "kind": "strip",
                                          "count": cnt,
                                          "x1": x, "y1": max(0.03, y - 0.26),
                                          "x2": x, "y2": min(0.97, y + 0.26),
                                          "reverse": bool(p.get("reverse"))})
                    else:
                        geo_parts.append({"shape": "line", "kind": "strip",
                                          "count": cnt,
                                          "x1": max(0.03, x - 0.3), "y1": y,
                                          "x2": min(0.97, x + 0.3), "y2": y,
                                          "reverse": bool(p.get("reverse"))})
                else:
                    geo_parts.append({"shape": "ring", "kind": "fan",
                                      "count": cnt,
                                      "cx": x, "cy": y, "radius": 0.1,
                                      "start_deg": -90.0, "end_deg": 270.0,
                                      "reverse": bool(p.get("reverse"))})

            geo = ({"shape": "multi", "parts": geo_parts} if len(geo_parts) > 1
                   else (dict(geo_parts[0]) if geo_parts else None))
            if geo is None:
                return {"ok": False, "error": "plano vazio"}
            geo.pop("count", None)
            self.set_zone_geometry(device_key_, zone_index, geo)
            return {"ok": True, "geometry": geo}

    def list_profiles(self):
        """Lista os perfis salvos."""
        out = []
        try:
            nomes = os.listdir(PROFILES_DIR)
        except OSError:
            # sem a pasta nao ha perfil; estourar aqui derrubaria /api/state
            return out
        for fn in sorted(nomes):
            if fn.endswith(".json"):
                out.append(fn[:-5])
        return out

    def save_profile(self, name: str, sobrescrever: bool = False):
        """Salva a cena atual como perfil.

        Perfil que ja existe so e trocado com `sobrescrever`; sem isso volta
        `existe`, e a interface pergunta antes. A conferencia e pelo nome ja
        limpo, que e o que vai para o disco: "Jogo!" vira "Jogo" e passava
        por cima do perfil Jogo com o aviso dizendo que era um perfil novo.
        """
        safe = "".join(c for c in str(name) if c.isalnum() or c in " _-").strip()
        if not safe:
            return {"ok": False, "error": "nome invalido"}
        path = os.path.join(PROFILES_DIR, safe + ".json")
        # com a trava: dois pedidos de salvar o mesmo nome, como num clique
        # duplo, escreviam no mesmo temporario ao mesmo tempo e o perfil
        # podia sair com os dois conteudos embaralhados
        with self._lock:
            if os.path.isfile(path) and not sobrescrever:
                return {"ok": False, "existe": True, "name": safe}
            os.makedirs(PROFILES_DIR, exist_ok=True)
            _grava_json(path, self.renderer.scene_json())
            self.config["last_profile"] = safe
            self.config["perfil_atual"] = safe
            self.save_config()
        return {"ok": True, "name": safe}

    @staticmethod
    def _caminho_perfil(name) -> str | None:
        """Arquivo de um perfil pelo nome, ou None se o nome sair da pasta.

        O nome vem da interface. Sem essa conferencia, "../config" carregaria
        ou apagaria a propria configuracao, e com mais niveis qualquer .json
        do disco ficaria ao alcance.
        """
        if not isinstance(name, str) or not name.strip():
            return None
        base = os.path.realpath(PROFILES_DIR)
        path = os.path.realpath(os.path.join(base, name + ".json"))
        if os.path.dirname(path) != base:
            return None
        return path

    def load_profile(self, name: str, apply_only=False):
        """Carrega um perfil salvo.

        Carregado pela pessoa, o perfil traz o brilho, a gama e a taxa de
        quadros que guardou. Na abertura, `apply_only`, vem so a cena: os
        ajustes globais ja sairam da configuracao, e o brilho baixado depois
        de salvar o perfil nao pode subir sozinho a cada reinicio.

        O preset que tocava antes deixa de ser o atual, senao a vitrine
        seguia marcando como tocando uma cena que ja nao estava no ar.
        """
        path = self._caminho_perfil(name)
        if path is None or not os.path.isfile(path):
            return False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            # perfil com formato estranho vira recusa, e nao excecao: na
            # abertura isso derrubaria a conexao inteira com o render parado
            if apply_only:
                self.renderer.set_layers(
                    [Layer.from_json(d) for d in data.get("layers", [])])
            else:
                self.renderer.load_scene(data)
        except Exception:
            return False
        self.config["last_preset"] = None
        self.config["perfil_atual"] = name
        if not apply_only:
            self.config["last_profile"] = name
            self.save_config()
        self._sync_sources()
        self._sincroniza_aux()
        return True

    def delete_profile(self, name: str):
        """Apaga um perfil salvo.

        Apagado o perfil que valia, ele deixa de ser o atual e o da abertura:
        o nome apontaria para um arquivo que nao existe mais.
        """
        path = self._caminho_perfil(name)
        if path is not None and os.path.isfile(path):
            os.remove(path)
            mudou = False
            for k in ("last_profile", "perfil_atual"):
                if self.config.get(k) == name:
                    self.config[k] = None
                    mudou = True
            if mudou:
                self.save_config()
            return True
        return False

    def set_favoritos(self, ids) -> dict:
        """Grava os presets marcados com estrela.

        Moram na configuracao, e nao no navegador: a janela do app roda em
        modo privado, que apaga o armazenamento do navegador ao fechar, e as
        estrelas sumiam a cada reinicio.
        """
        if not isinstance(ids, list):
            return {"ok": False, "error": "lista de favoritos invalida"}
        validos = [i for i in dict.fromkeys(x for x in ids if isinstance(x, str))
                   if ps.by_id(i) is not None]
        self.config["favoritos"] = validos
        self.save_config()
        return {"ok": True, "favoritos": validos}

    def set_inventario(self, itens) -> dict:
        """Grava o que a pessoa descreveu do gabinete no assistente."""
        if not isinstance(itens, list):
            return {"ok": False, "error": "inventario invalido"}
        self.config["inventario"] = [i for i in itens if isinstance(i, dict)][:64]
        self.save_config()
        return {"ok": True}

    def mostrar_janela(self) -> dict:
        """Mostra a janela do app, a pedido de uma segunda abertura."""
        cb = self.ao_mostrar_janela
        if cb is None:
            return {"ok": False}
        try:
            cb()
        except Exception:
            return {"ok": False}
        return {"ok": True}

    def catalog(self):
        """Reune efeitos, presets, paletas e blends para a interface.

        Cada preset leva as leituras de sensor que usa, para a vitrine marcar
        os de temperatura quando a maquina nao tem como medi-la.
        """
        presets = ps.catalog()
        for g in presets:
            for pj in g["presets"]:
                p = ps.by_id(pj["id"])
                usados = set()
                for layer in (p.layers if p else []):
                    usados |= sensores_da_camada(layer.get("effect"),
                                                 layer.get("params"))
                pj["sensores"] = sorted(usados)
        return {
            "effects": fx.catalog(),
            "blends": [{"value": v, "label": l} for v, l in blend.LABELS],
            "palettes": [{"name": n, "label": PALETTE_LABELS.get(n, n),
                          "colors": palette_preview(n)}
                         for n in PALETTE_NAMES],
            "presets": presets,
            "spots": [{"value": v, "label": l} for v, l in CASE_SPOT_LABELS],
        }

    def state(self) -> dict:
        """Fotografia do estado atual, que a interface consulta em laco."""
        r = self.renderer
        out = {
            "connected": self.connected,
            "connecting": self.connecting,
            "status": self.status_msg,
            "protocol": self.client.protocol,
            "version": __version__,
            "platform": sys.platform,
            "config_dir": CONFIG_DIR,
            "profiles": self.list_profiles(),
            "last_profile": self.config.get("last_profile"),
            "perfil_atual": self.config.get("perfil_atual"),
            "elevacao": self.elevacao,
            "teclado": (self.teclado.to_json() if self.teclado else None),
            "akko_keyboard": self.config.get("akko_keyboard", True),
            "motivo_conexao": self.motivo_conexao,
            "erro_conexao": self.erro_conexao,
            "autostart_openrgb": self.config.get("autostart_openrgb", True),
            "favoritos": list(self.config.get("favoritos") or []),
            "inventario": self.config.get("inventario"),
            "assistente_ativo": getattr(self, "_probe_session", None) is not None,
        }
        if not r:
            out["devices"] = []
            out["layers"] = []
            return out
        out.update({
            "layers": [l.to_json() for l in r.layers],
            "settings": {k: v for k, v in r.settings.items() if k != "enabled_devices"},
            "enabled_devices": r.settings.get("enabled_devices", {}),
            "fps": round(r.fps_actual, 1),
            "last_error": r.last_error,
            "reconnects": self.reconnects,
            "exclusive": self.last_exclusive,
            "exclusive_mode": self.config.get("exclusive_mode", True),
            "autostart_openrgb": self.config.get("autostart_openrgb", True),
            "connection_lost": r.connection_lost,
            "canvas": r.canvas.to_json(),
            "devices": [
                dict(d.to_json(), key=device_key(d),
                     direct_ok=r.direct_ok.get(d.index),
                     active=any(dd.index == d.index for dd in r.canvas.devices))
                for d in r.all_devices
            ],
            "sources": {
                "audio": self._src_status(self.audio, "audio"),
                "screen": self._src_status(self.screen, "screen"),
                "sensors": self._sensores_status(),
            },
            "needed": sorted(self._needed_sources()),
            "avisos": self._avisos_das_camadas(),
            "setup_todo": self.setup_todo(),
            "zones_resizable": self.resizable_zones(),
            "last_preset": self.config.get("last_preset"),
            "sensor_values": {
                k: round(getattr(r.ctx.sensors, k), 1)
                for k in ("cpu_temp", "gpu_temp", "cpu_load", "gpu_load",
                          "ram_load", "fan_rpm")
            },
        })
        return out

    def _sensores_status(self) -> dict:
        """Situacao dos sensores, com a pasta onde a DLL deve ficar.

        Vem mesmo antes da fonte ligar, para a vitrine ja saber se ha como
        medir temperatura e o aviso mostrar o caminho inteiro.
        """
        if self.sensors:
            d = self.sensors.status()
        else:
            dll = _dll_sensores()
            d = {"running": False, "dll_path": dll,
                 "dll_present": os.path.isfile(dll)}
        d["dll_dir"] = os.path.dirname(d.get("dll_path") or _dll_sensores())
        return d

    def _src_status(self, src, kind) -> dict:
        cfg = (self.config.get("sources") or {}).get(kind) or {}
        if src is None:
            return {"running": False, "config": cfg}
        d = {"running": src.running, "error": src.error, "config": cfg}
        if kind == "audio":
            d["device_name"] = src.device_name
        else:
            d["fps"] = round(getattr(src, "actual_fps", 0.0), 1)
        return d

    def preview(self):
        """Cores do quadro atual, para a interface desenhar o mapa ao vivo."""
        r = self.renderer
        if not r or r.frame is None:
            return []
        rgba = r.to_wire(r.frame)[:, :3]
        return ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in rgba]

    def preview_hex(self) -> str:
        """O quadro atual como uma unica string hex, seis digitos por LED.

        E o formato que vai pelo stream: uma string so custa uma fracao do
        que custaria uma lista com uma cor por LED, em serializacao e em bytes.
        """
        r = self.renderer
        if not r or r.frame is None:
            return ""
        return np.ascontiguousarray(r.to_wire(r.frame)[:, :3]).tobytes().hex()

    def live_sources(self) -> dict:
        """Leitura instantanea das fontes ligadas, para os medidores da interface."""
        out = {}
        r = self.renderer
        if not r:
            return out
        if self.audio and self.audio.running:
            a = r.ctx.audio
            out["audio"] = {
                "level": round(float(a.level), 3), "bass": round(float(a.bass), 3),
                "mid": round(float(a.mid), 3), "treble": round(float(a.treble), 3),
                "beat": round(float(a.beat), 3),
                "bands": [round(float(v), 3) for v in a.bands],
            }
        if self.screen and self.screen.running:
            avg = getattr(r.ctx.screen, "average", None)
            if avg is not None:
                out["screen"] = [round(float(v), 3) for v in list(avg)[:3]]
        return out
