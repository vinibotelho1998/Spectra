"""Teclado Akko por HID direto, fora do OpenRGB.

O Spectra fala com o hardware pelo OpenRGB, sempre. Este modulo e a unica
excecao, e existe por um motivo concreto: o OpenRGB nao tem driver para os
teclados da plataforma Rongyuan RY5088, que a Akko revende, entao esse
hardware seria invisivel para o aplicativo inteiro.

O protocolo foi obtido do driver web oficial da Akko, em
`https://web.akkogear.com`, observando o que ele manda ao teclado.

Formato do relatorio, enviado como feature report de 64 bytes mais o byte
de id na frente, na interface vendor:

    b0  0x07  comando de efeito de luz
    b1  efeito, 1 e a cor fixa
    b2  modo de cor, 4 e cor unica
    b3  brilho, 0 a 4
    b4  velocidade, irrelevante na cor fixa
    b5  R    b6  G    b7  B
    b8  checksum, 0xFF menos a soma dos bytes anteriores

Existe tambem a camada de cor por tecla, comando 0x0C, em sete pacotes
que somam 126 LEDs em RGB.

O que este teclado nao tem e fluxo. O controlador reaplica a iluminacao a
cada comando recebido, e isso aparece como um piscar em qualquer taxa,
testado de 8 a 207 quadros por segundo. O driver web do proprio fabricante
tambem nao transmite: arrastar o pincel pelas teclas nao manda um byte, e
so a confirmacao escreve. Entao cor por tecla aqui e imagem parada, refeita
quando a cena muda, e nao animacao.
"""

from __future__ import annotations

import sys
import os

_WINDOWS = sys.platform == "win32"

import ctypes
import threading
import time
from ctypes import wintypes

VID = 0x3151
PID = 0x502D
USAGE_PAGE = 0xFFFF
USAGE = 0x02

CMD_LUZ = 0x07
CMD_CAMADA = 0x0C
CMD_COR_TELA = 0x0E
EFEITO_COR_FIXA = 0x01
EFEITO_PERSONALIZADO = 0x0D
EFEITO_SINCRONIA_TELA = 21
MODO_COR_UNICA = 0x04
BRILHO_MAX = 4

# O firmware tem um modo feito para receber cor do computador em fluxo, o
# 21, alimentado pelo comando 0x0E. Ele nao reaplica a iluminacao a cada
# pacote, entao aceita atualizacao continua sem piscar, ao contrario do
# 0x07 e do 0x0C. O driver web da Akko nao expoe esse modo; o formato vem
# da documentacao do projeto monsgeek-akko-linux, que prevê 50 Hz.
FLUXO_HZ = 50

# A matriz de LED tem 21 colunas de 6 linhas, e o indice anda pela coluna:
# W e S sao 14 e 15, vizinhos verticais. Descoberto pintando tecla por
# tecla no driver oficial e lendo a camada que ele gravava.
LINHAS = 6
COLUNAS = 21
LEDS = LINHAS * COLUNAS
BYTES_POR_PACOTE = 56


def indice(coluna: int, linha: int) -> int:
    """Indice do LED a partir da posicao na matriz do teclado."""
    return coluna * LINHAS + linha


TECLAS = {
    "esc": 0,
    "a": 9, "w": 14, "s": 15, "d": 21,
    "seta_cima": 82, "seta_esquerda": 77,
    "seta_baixo": 83, "seta_direita": 89,
}

# O teclado grava configuracao, entao mesmo sem o modo de gravacao
# explicito nao se escreve nele a cada quadro.
INTERVALO_MIN = 1.0 / 8.0
# Baixo de proposito: quem acompanha uma cena manda cor ja suavizada, em
# passos pequenos, e um limiar alto engoliria a transicao inteira.
DELTA_MIN = 3
# Envios falhando em sequencia que contam como teclado fora. No fluxo de
# 50 Hz isso e meio segundo: rapido para quem tirou o cabo ou trocou o
# chaveador, e longe de um soluco isolado do controlador.
FALHAS_MAX = 25

if _WINDOWS:
    _setupapi = ctypes.WinDLL("setupapi")
    _hid = ctypes.WinDLL("hid")
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)


    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


    class _IFACE(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", _GUID),
                    ("Flags", wintypes.DWORD),
                    ("Reserved", ctypes.POINTER(wintypes.ULONG))]


    class _DETAIL(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", wintypes.WCHAR * 1)]


    class _ATTRS(ctypes.Structure):
        _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                    ("ProductID", wintypes.USHORT),
                    ("VersionNumber", wintypes.USHORT)]


    class _CAPS(ctypes.Structure):
        _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                    ("InputReportByteLength", wintypes.USHORT),
                    ("OutputReportByteLength", wintypes.USHORT),
                    ("FeatureReportByteLength", wintypes.USHORT),
                    ("Reserved", wintypes.USHORT * 17),
                    ("Numeros", wintypes.USHORT * 10)]


    _setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    _setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    _setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    _setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD,
        ctypes.POINTER(_IFACE)]
    _setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    _setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_IFACE), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    _hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    _hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
    _hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ATTRS)]
    _hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    _hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(ctypes.c_void_p)]
    _hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    _hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CAPS)]
    _hid.HidD_SetFeature.restype = wintypes.BOOLEAN
    _hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                     wintypes.ULONG]

    DIGCF_PRESENT = 0x02
    DIGCF_DEVICEINTERFACE = 0x10
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_RW = 0x03
    OPEN_EXISTING = 3
    INVALIDO = wintypes.HANDLE(-1).value

else:
    # hidapi seleciona a colecao vendor pelo usage e envia feature reports
    # com o mesmo byte de report ID usado pelo backend do Windows.
    _hid = None
    _k32 = None
    INVALIDO = -1
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_RW = 0x03
    OPEN_EXISTING = 3


def _procura() -> tuple:
    """Acha a interface vendor do teclado, devolvendo caminho e tamanho.

    Sao varias colecoes HID no mesmo teclado, e so a de usage page 0xFFFF
    com usage 2 aceita o relatorio de configuracao.
    """
    if not _WINDOWS:
        try:
            import hidraw
        except ImportError as exc:
            raise OSError("Biblioteca hidapi ausente; instale as dependencias do Spectra") from exc
        desconhecida = False
        for dev in hidraw.enumerate(VID, PID):
            usage = (dev.get("usage_page"), dev.get("usage"))
            if usage == (USAGE_PAGE, USAGE) and dev.get("path"):
                return dev["path"], 65
            # Alguns backends nao conseguem ler o descritor sem permissao.
            # Nunca tente escrever em outra colecao sem identificacao.
            if not usage[0] or not usage[1]:
                desconhecida = True
        if desconhecida:
            raise OSError("Akko detectado, mas nao foi possivel identificar a interface HID; verifique as permissoes hidraw e a regra udev")
        return None, 0
    guid = _GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    lista = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    i = 0
    try:
        while True:
            iface = _IFACE()
            iface.cbSize = ctypes.sizeof(_IFACE)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                    lista, None, ctypes.byref(guid), i, ctypes.byref(iface)):
                return None, 0
            i += 1
            precisa = wintypes.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                lista, ctypes.byref(iface), None, 0, ctypes.byref(precisa),
                None)
            if not precisa.value:
                continue
            buf = ctypes.create_string_buffer(precisa.value)
            det = ctypes.cast(buf, ctypes.POINTER(_DETAIL))
            det.contents.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not _setupapi.SetupDiGetDeviceInterfaceDetailW(
                    lista, ctypes.byref(iface), buf, precisa.value,
                    ctypes.byref(precisa), None):
                continue
            caminho = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            h = _k32.CreateFileW(caminho, 0, FILE_SHARE_RW, None,
                                 OPEN_EXISTING, 0, None)
            if h == INVALIDO:
                continue
            try:
                attrs = _ATTRS()
                attrs.Size = ctypes.sizeof(_ATTRS)
                if not _hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
                    continue
                if (attrs.VendorID, attrs.ProductID) != (VID, PID):
                    continue
                pp = ctypes.c_void_p()
                if not _hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
                    continue
                try:
                    caps = _CAPS()
                    _hid.HidP_GetCaps(pp, ctypes.byref(caps))
                finally:
                    _hid.HidD_FreePreparsedData(pp)
                if (caps.UsagePage, caps.Usage) == (USAGE_PAGE, USAGE):
                    return caminho, caps.FeatureReportByteLength
            finally:
                _k32.CloseHandle(h)
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(lista)


def monta(efeito: int, modo_cor: int, brilho: int, velocidade: int,
          r: int, g: int, b: int) -> bytes:
    """Monta o relatorio de 64 bytes, com o checksum logo apos a carga."""
    carga = [CMD_LUZ, efeito, modo_cor, brilho, velocidade,
             r & 0xFF, g & 0xFF, b & 0xFF]
    ck = (0xFF - (sum(carga) & 0xFF)) & 0xFF
    return bytes(carga + [ck] + [0] * (64 - len(carga) - 1))


def monta_cor_tela(r: int, g: int, b: int) -> bytes:
    """Monta o relatorio de cor em fluxo do modo de sincronia com a tela."""
    carga = [CMD_COR_TELA, int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF, 0, 0, 0]
    ck = (0xFF - (sum(carga) & 0xFF)) & 0xFF
    return bytes(carga + [ck] + [0] * (64 - len(carga) - 1))


def pacotes_camada(cores: dict) -> list:
    """Fatia a camada de cor por tecla nos relatorios que o teclado espera.

    `cores` mapeia indice de LED para uma tripla RGB, e o que faltar fica
    apagado. Os 378 bytes saem em sete relatorios, seis de 56 bytes e um
    de 42, cada um com cabecalho e checksum proprios.

        b0  0x0C  gravar camada
        b1  0x00
        b2  0xFF
        b3  indice do pacote
        b4  bytes de dados neste pacote
        b5  1 no ultimo pacote
        b6  0x00
        b7  checksum
        b8+ dados
    """
    dados = bytearray()
    for i in range(LEDS):
        r, g, b = cores.get(i, (0, 0, 0))
        dados += bytes([int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF])

    saida = []
    off = 0
    idx = 0
    while off < len(dados):
        n = min(BYTES_POR_PACOTE, len(dados) - off)
        cab = [CMD_CAMADA, 0x00, 0xFF, idx, n,
               1 if off + n >= len(dados) else 0, 0x00]
        ck = (0xFF - (sum(cab) & 0xFF)) & 0xFF
        corpo = cab + [ck] + list(dados[off:off + n])
        saida.append(bytes(corpo + [0] * (64 - len(corpo))))
        off += n
        idx += 1
    return saida


class _ZonaTeclado:
    """Zona unica do teclado, no formato que o canvas espera."""

    def __init__(self):
        self.index = 0
        self.name = "Teclas"
        self.leds_count = LEDS
        self.type = 2
        self.leds_min = self.leds_max = LEDS
        self.matrix_width = COLUNAS
        self.matrix_height = LINHAS


class DispositivoTeclado:
    """Faz o teclado parecer um dispositivo para o motor de efeitos.

    Ele nao fala o protocolo do OpenRGB e nunca entra na lista que o
    renderizador empurra por la. Existe para que os efeitos tenham onde
    pintar: uma matriz de 21 por 6 com coordenadas proprias, igual a
    qualquer outra peca do gabinete.
    """

    index = 0
    name = "Akko TAC75 HE"
    type_name = "Keyboard"
    serial = "akko-tac75he"
    location = ""

    def __init__(self):
        self.zones = [_ZonaTeclado()]
        self.led_count = LEDS


GEOMETRIA = {
    "shape": "grid", "x": 0.03, "y": 0.03, "w": 0.94, "h": 0.94,
    "cols": COLUNAS, "rows": LINHAS,
}


class AkkoKeyboard:
    """Teclado Akko como destino de cor unica.

    Nao entra no canvas: o teclado nao aceita cor por LED em fluxo, entao
    ele recebe uma cor so, tirada da media do quadro. O envio e limitado
    no tempo e por diferenca de cor, porque o controlador grava
    configuracao e escrever a cada quadro o desgastaria.
    """

    def __init__(self):
        self.caminho = None
        self.tamanho = 0
        self._h = None
        self._lock = threading.Lock()
        self._ultima = None
        self._quando = 0.0
        self._modo = None
        self._falhas = 0
        self.erro = None

    @property
    def conectado(self) -> bool:
        """Diz se existe handle aberto para o teclado."""
        return self._h is not None

    def abrir(self) -> bool:
        """Procura o teclado e abre a interface de configuracao dele."""
        with self._lock:
            if self._h is not None:
                return True
            try:
                caminho, tamanho = _procura()
            except OSError as exc:
                self.erro = str(exc)
                return False
            if not caminho:
                self.erro = "teclado Akko nao encontrado"
                return False
            if tamanho < 65:
                self.erro = "interface HID Akko com relatorio menor que 65 bytes"
                return False
            if _WINDOWS:
                h = _k32.CreateFileW(caminho, GENERIC_READ | GENERIC_WRITE,
                                     FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
                if h == INVALIDO:
                    self.erro = "sem acesso a interface do teclado (erro %d)" % (
                        ctypes.get_last_error(),)
                    return False
            else:
                h = None
                try:
                    import hidraw
                    h = hidraw.device()
                    h.open_path(caminho)
                except (OSError, ImportError) as exc:
                    if h is not None:
                        try:
                            h.close()
                        except OSError:
                            pass
                    self.erro = "sem acesso a interface do teclado; verifique as permissoes hidraw e a regra udev: %s" % exc
                    return False
            self.caminho, self.tamanho, self._h = os.fsdecode(caminho), tamanho, h
            self.erro = None
            return True

    def fechar(self):
        """Fecha o handle, se houver."""
        with self._lock:
            self._solta()

    def _solta(self):
        # O modo vai junto: o aparelho que volta a ser aberto pode ter sido
        # religado e estar no efeito salvo, e sem o modo de fluxo de novo a
        # cor mandada nao aparece.
        if self._h is not None:
            if _WINDOWS:
                _k32.CloseHandle(self._h)
            else:
                try:
                    self._h.close()
                except OSError:
                    pass
            self._h = None
        self._modo = None
        self._ultima = None
        self._falhas = 0

    def _envia(self, pacote: bytes) -> bool:
        buf = ctypes.create_string_buffer(self.tamanho)
        buf[0] = bytes([0])
        buf[1:1 + len(pacote)] = pacote
        if self._h is None:
            return False
        if _WINDOWS:
            ok = _hid.HidD_SetFeature(self._h, buf, self.tamanho)
        else:
            try:
                ok = self._h.send_feature_report(buf.raw) == self.tamanho
            except OSError:
                ok = False
        if ok:
            self._falhas = 0
            return True
        self._falhas += 1
        if self._falhas >= FALHAS_MAX:
            # Handle de um teclado que saiu nao volta a valer, nem com ele
            # plugado de novo. Fechando, o estado diz a verdade para a
            # interface e a proxima abertura acha o aparelho outra vez.
            self._solta()
            self.erro = "teclado Akko parou de responder"
        return False

    def set_cor(self, r: int, g: int, b: int, brilho: int = BRILHO_MAX,
                forcar: bool = False) -> bool:
        """Pinta o teclado inteiro de uma cor.

        Ignora a chamada quando a cor mal mudou ou quando veio cedo demais
        depois da anterior, a nao ser que `forcar` peca o contrario.
        """
        with self._lock:
            if self._h is None:
                return False
            agora = time.monotonic()
            nivel = max(0, min(int(brilho), BRILHO_MAX))
            # O brilho entra na comparacao porque o tom vai normalizado: a
            # variacao de uma cena que so escurece mora ali, e comparar so
            # o RGB faria o destino congelar.
            estado = (int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF, nivel)
            if not forcar and self._ultima is not None:
                if agora - self._quando < INTERVALO_MIN:
                    return False
                mudou_cor = max(abs(a - c) for a, c in
                                zip(self._ultima[:3], estado[:3])) >= DELTA_MIN
                if not mudou_cor and self._ultima[3] == nivel:
                    return False
            ok = self._envia(monta(EFEITO_COR_FIXA, MODO_COR_UNICA,
                                   nivel, 8, *estado[:3]))
            if ok:
                self._ultima, self._quando = estado, agora
                self._modo = EFEITO_COR_FIXA
            return ok

    def cor_em_fluxo(self, r: int, g: int, b: int) -> bool:
        """Manda uma cor pelo canal de fluxo, para acompanhar a cena ao vivo.

        Entra no modo de sincronia com a tela na primeira chamada. Esse e o
        unico caminho deste teclado que aceita atualizacao continua: tanto o
        efeito de cor fixa quanto a camada por tecla reaplicam a iluminacao
        a cada pacote e piscam de forma visivel, em qualquer taxa.

        Limitado a `FLUXO_HZ`, que e a taxa que o firmware espera. Mandar
        mais rapido que isso, tipo acompanhar um laco de 60 quadros por
        segundo, atropela o controlador e volta a aparecer como piscar.
        """
        with self._lock:
            if self._h is None:
                return False
            agora = time.monotonic()
            if agora - self._quando < 1.0 / FLUXO_HZ:
                return False
            self._quando = agora
            if self._modo != EFEITO_SINCRONIA_TELA:
                if not self._envia(monta(EFEITO_SINCRONIA_TELA, MODO_COR_UNICA,
                                         BRILHO_MAX, 0, 255, 255, 255)):
                    return False
                self._modo = EFEITO_SINCRONIA_TELA
                time.sleep(0.05)
            return self._envia(monta_cor_tela(r, g, b))

    def set_camada(self, cores: dict) -> bool:
        """Manda a camada de cor por tecla e a exibe.

        Antes dos dados vai o efeito personalizado: sem ele o controlador
        fica alternando entre o efeito anterior e a camada, o que aparece
        como piscar e como cor lavada.

        Serve para imagem parada, nunca para animacao. O controlador
        reaplica a camada a cada escrita e isso pisca de forma visivel em
        qualquer taxa, do mesmo jeito que acontece com a cor unica. O
        driver do proprio fabricante so escreve quando a pessoa manda.
        """
        with self._lock:
            if self._h is None:
                return False
            if self._modo != EFEITO_PERSONALIZADO:
                if not self._envia(monta(EFEITO_PERSONALIZADO, MODO_COR_UNICA,
                                         BRILHO_MAX, 0, 0, 0xC8, 0xC8)):
                    return False
                self._modo = EFEITO_PERSONALIZADO
                time.sleep(0.05)
            for pacote in pacotes_camada(cores):
                if not self._envia(pacote):
                    return False
            self._ultima = None
            return True

    def apagar(self) -> bool:
        """Deixa o teclado preto, para o encerramento do aplicativo."""
        return self.set_cor(0, 0, 0, forcar=True)

    def to_json(self) -> dict:
        """Descreve o teclado no formato que a interface consome."""
        return {"kind": "akko", "name": "Teclado Akko",
                "connected": self.conectado, "error": self.erro,
                "path": self.caminho, "per_led": False}
