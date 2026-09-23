"""Privilegio de administrador para o servidor OpenRGB, no Windows.

A parte do hardware que fala por SMBus, que e onde moram os pentes de
memoria RGB e parte das placas-mae, so responde a um processo elevado.
Sem isso o OpenRGB registra `Permission Denied, PawnIO initialization
aborted` e simplesmente nao lista a DRAM: nao ha erro de conexao nem
dispositivo torto, o pente some da lista e parece que o Spectra ignorou.

Pedir elevacao a cada abertura significaria um aviso do controle de
conta toda vez. Por isso o caminho preferido e uma tarefa agendada com
`HighestAvailable`, criada uma unica vez: dali em diante o Spectra, mesmo
sem privilegio, manda rodar a tarefa e o servidor sobe elevado calado.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
from ctypes import wintypes

NO_WINDOW = 0x08000000

# Codificacao da saida de tasklist e taskkill. Mandando para um pipe eles
# escrevem na pagina OEM, e nao na ANSI que o Python usaria por padrao: letra
# como o "u" com trema cai num byte que a ANSI nao tem, a leitura estourava
# dentro do subprocess e a saida chegava vazia.
SAIDA_CONSOLE = {"encoding": "oem", "errors": "replace"}

PAWNIO_DIRS = [
    r"C:\Program Files\PawnIO",
    r"C:\Program Files (x86)\PawnIO",
]

_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Sobe o servidor SDK do OpenRGB elevado, para o Spectra enxergar a memoria RAM e os controladores de SMBus.</Description>
  </RegistrationInfo>
  <Triggers />
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>6</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe}</Command>
      <Arguments>{args}</Arguments>
      <WorkingDirectory>{cwd}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def sou_admin() -> bool:
    """Diz se o proprio Spectra esta rodando elevado."""
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
ERROR_ACCESS_DENIED = 5


def processo_elevado(pid: int):
    """Diz se um processo roda elevado, ou None quando nao da para apurar.

    Acesso negado ao abrir o processo conta como elevado: processo comum
    nao consegue espiar o token de um processo de privilegio maior, entao
    a propria recusa ja e a resposta.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    # sem assinatura declarada o ctypes devolve o handle como int de 32 bits,
    # e num Python de 64 bits isso o corta pela metade
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                        ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED else None
    try:
        tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            val = wintypes.DWORD()
            size = wintypes.DWORD()
            ok = adv.GetTokenInformation(tok, TOKEN_ELEVATION, ctypes.byref(val),
                                         ctypes.sizeof(val), ctypes.byref(size))
            return bool(val.value) if ok else None
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def _pids_openrgb() -> list:
    try:
        r = subprocess.run(["tasklist", "/fi", "IMAGENAME eq OpenRGB.exe",
                            "/fo", "csv", "/nh"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=NO_WINDOW, **SAIDA_CONSOLE)
    except Exception:
        return []
    pids = []
    for linha in r.stdout.splitlines():
        partes = [p.strip('"') for p in linha.split('","')]
        if len(partes) < 2 or not partes[0].lower().startswith("openrgb"):
            continue
        try:
            pids.append(int(partes[1].strip('" ')))
        except ValueError:
            pass
    return pids


def openrgb_elevado():
    """Diz se o servidor OpenRGB em execucao esta elevado.

    Devolve None quando nao ha processo ou quando o token nao pode ser
    lido, para a interface separar "sei que esta sem privilegio" de "nao
    consegui apurar".
    """
    for pid in _pids_openrgb():
        v = processo_elevado(pid)
        if v is not None:
            return v
    return None


def encerrar_openrgb() -> bool:
    """Derruba o servidor OpenRGB, para poder subir outro no lugar."""
    try:
        r = subprocess.run(["taskkill", "/IM", "OpenRGB.exe", "/T", "/F"],
                           capture_output=True, text=True, timeout=20,
                           creationflags=NO_WINDOW, **SAIDA_CONSOLE)
        return r.returncode == 0
    except Exception:
        return False


def pawnio_instalado() -> bool:
    """Diz se o driver que abre o SMBus esta instalado.

    Sem ele nem elevado o OpenRGB alcanca os pentes de memoria, entao a
    interface precisa distinguir os dois motivos de a RAM nao aparecer.
    """
    return any(os.path.isdir(d) for d in PAWNIO_DIRS)


def tarefa_existe(nome: str) -> bool:
    """Diz se a tarefa agendada ja foi criada nesta maquina."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", nome],
                           capture_output=True, timeout=15,
                           creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def rodar_tarefa(nome: str) -> bool:
    """Manda a tarefa agendada rodar agora."""
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", nome],
                           capture_output=True, timeout=15,
                           creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
ERROR_CANCELLED = 1223
SW_HIDE = 0


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def executar_elevado(exe: str, args: list, espera: float = 60.0) -> str:
    """Roda um programa elevado e espera ele terminar.

    Devolve "ok", "recusado" quando a pessoa nega o controle de conta, ou
    "erro". O "recusado" e separado de proposito: negar o aviso e uma
    escolha, e quem chama nao deve insistir na proxima abertura.
    """
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = subprocess.list2cmdline(args)
    info.nShow = SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return "recusado" if ctypes.get_last_error() == ERROR_CANCELLED else "erro"
    if not info.hProcess:
        return "ok"
    try:
        k32.WaitForSingleObject(info.hProcess, int(espera * 1000))
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            return "ok" if code.value == 0 else "erro"
        return "ok"
    finally:
        k32.CloseHandle(info.hProcess)


def criar_tarefa(nome: str, exe: str, args: list) -> str:
    """Registra a tarefa agendada que sobe o servidor elevado.

    Custa um aviso do controle de conta, uma vez so na vida da maquina. O
    XML vai em UTF-16 porque e o formato que o `schtasks` aceita.
    """
    user = os.environ.get("USERNAME") or ""
    dominio = os.environ.get("USERDOMAIN") or ""
    conta = f"{dominio}\\{user}" if dominio and user else user
    if not conta:
        return "erro"
    xml = _TASK_XML.format(
        user=_xml_escape(conta), exe=_xml_escape(exe),
        args=_xml_escape(" ".join(args)),
        cwd=_xml_escape(os.path.dirname(exe)))
    caminho = os.path.join(tempfile.gettempdir(), "spectra-openrgb-task.xml")
    try:
        with open(caminho, "w", encoding="utf-16") as f:
            f.write(xml)
    except OSError:
        return "erro"
    try:
        r = executar_elevado(
            "schtasks.exe", ["/create", "/tn", nome, "/xml", caminho, "/f"])
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass
    if r != "ok":
        return r
    return "ok" if tarefa_existe(nome) else "erro"
