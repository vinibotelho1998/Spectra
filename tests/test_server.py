"""Entradas HTTP invalidas nunca acionam o app nem usam hardware real."""

from __future__ import annotations

import http.client
import io
import json
import os
import threading
import types
from email.message import Message

import pytest

from spectra import server


def _http_pipes(app, raw_request):
    """Exercita o parser e a resposta HTTP usando pipes locais."""
    incoming, sender = os.pipe()
    receiver, outgoing = os.pipe()

    class Endpoint:
        def __init__(self, read_fd, write_fd):
            self.read_fd, self.write_fd = read_fd, write_fd

        def makefile(self, mode, buffering=-1):
            fd = self.read_fd if "r" in mode else self.write_fd
            return os.fdopen(os.dup(fd), mode, buffering=buffering)

        def settimeout(self, _timeout):
            pass

        def sendall(self, data):
            remaining = memoryview(data)
            while remaining:
                remaining = remaining[os.write(self.write_fd, remaining):]

        def close(self):
            os.close(self.read_fd)
            os.close(self.write_fd)

    client, peer = Endpoint(receiver, sender), Endpoint(incoming, outgoing)
    handler = type("HandlerDeTeste", (server.Handler,), {"app": app})
    errors = []

    def atender():
        try:
            handler(peer, ("127.0.0.1", 12345), types.SimpleNamespace())
        except Exception as exc:
            errors.append(exc)
        finally:
            peer.close()

    thread = threading.Thread(target=atender, daemon=True)
    thread.start()
    try:
        os.write(client.write_fd, raw_request)
        response = http.client.HTTPResponse(client)
        response.begin()
        return response.status, response.getheaders(), response.read()
    finally:
        client.close()
        thread.join(2)
        assert not thread.is_alive()
        if errors:
            raise errors[0]


def test_http_real_serve_pagina_estado_e_valida_post():
    chamadas = []
    app = types.SimpleNamespace(state=lambda: {"id": 7}, renderer=object(),
                                reset_layout=lambda: chamadas.append("reset"))
    base = b"Host: 127.0.0.1:7311\r\nConnection: close\r\n"

    status, headers, body = _http_pipes(app, b"GET / HTTP/1.1\r\n" + base + b"\r\n")
    assert status == 200
    assert b"<html" in body.lower()
    assert dict(headers)["X-Content-Type-Options"] == "nosniff"

    status, _, body = _http_pipes(app, b"GET /api/state HTTP/1.1\r\n" + base + b"\r\n")
    assert status == 200
    assert json.loads(body) == {"id": 7}

    post = b"POST /api/layout/reset HTTP/1.1\r\n" + base
    status, _, _ = _http_pipes(app, post + b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
    assert status == 200
    assert chamadas == ["reset"]

    status, _, _ = _http_pipes(app, post + b"Origin: https://example.org\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
    assert status == 403
    assert chamadas == ["reset"]


def pedido(corpo=b"{}", caminho="/api/layout/reset", headers=None, motor=True):
    chamadas = []
    h = server.Handler.__new__(server.Handler)
    h.path = caminho
    h.headers = {"Host": "127.0.0.1:7311", "Content-Type": "application/json",
                 "Content-Length": str(len(corpo))}
    h.headers.update(headers or {})
    h.rfile = io.BytesIO(corpo)
    h.app = types.SimpleNamespace(renderer=object() if motor else None,
                                  reset_layout=lambda: chamadas.append("reset"),
                                  resize_zone=lambda *args: chamadas.append("resize"))
    respostas = []
    h._send = lambda code, body, ctype="": respostas.append((code, json.loads(body)))
    server.Handler.do_POST(h)
    return h, chamadas, respostas


@pytest.mark.parametrize("corpo", [b"{oops", b"null", b"[]", b"true", b"42",
                                    b'"texto"', b'{"x": NaN}',
                                    b'{"x": Infinity}', b'{"x": 1e999}',
                                    b'{"x": "\xff"}'])
def test_json_invalido_nao_restaura_o_mapa(corpo):
    h, chamadas, respostas = pedido(corpo)
    assert respostas[0][0] == 400
    assert chamadas == []
    assert h.close_connection is True


@pytest.mark.parametrize("tamanho, codigo", [("-1", 400), ("abc", 400), ("", 400),
                                              ("+2", 400), ("2, 2", 400),
                                              ("9" * 5000, 413),
                                              (str(server.MAX_BODY_BYTES + 1), 413)])
def test_tamanho_invalido_e_recusado_antes_da_leitura(tamanho, codigo):
    h, chamadas, respostas = pedido(headers={"Content-Length": tamanho})
    assert respostas[0][0] == codigo
    assert h.rfile.tell() == 0
    assert chamadas == []


def test_corpo_truncado_nao_executa_a_rota():
    _, chamadas, respostas = pedido(headers={"Content-Length": "4"})
    assert respostas[0][0] == 400
    assert chamadas == []


def test_chunked_nao_e_interpretado_como_corpo_vazio():
    _, chamadas, respostas = pedido(headers={"Transfer-Encoding": "chunked"})
    assert respostas[0][0] == 400
    assert chamadas == []


def test_content_length_duplicado_nao_e_ambiguo():
    h = server.Handler.__new__(server.Handler)
    h.headers = Message()
    h.headers.add_header("Content-Length", "2")
    h.headers.add_header("Content-Length", "20")
    h.rfile = io.BytesIO(b"{}")
    with pytest.raises(server.PedidoInvalido, match="ambiguo"):
        h._body()
    assert h.rfile.tell() == 0


@pytest.mark.parametrize("ctype", ["text/plain; application/json", "application/jsonp"])
def test_tipo_parecido_com_json_nao_passa(ctype):
    h, chamadas, respostas = pedido(headers={"Content-Type": ctype})
    assert respostas[0][0] == 403
    assert chamadas == []
    assert h.close_connection is True


def test_json_com_charset_continua_aceito():
    _, chamadas, respostas = pedido(headers={"Content-Type": "application/json; charset=utf-8"})
    assert respostas[0][0] == 200
    assert chamadas == ["reset"]


def test_rota_sem_motor_fecha_conexao_com_corpo_nao_consumido():
    h, chamadas, respostas = pedido(motor=False)
    assert respostas[0][0] == 503
    assert chamadas == []
    assert h.close_connection is True


def test_parametro_numerico_invalido_e_erro_de_entrada():
    _, _, respostas = pedido(b'{"device": "Mobo", "zone": "x"}',
                             "/api/zone/resize")
    assert respostas[0][0] == 400
    assert "parametro invalido" in respostas[0][1]["error"]


def test_timeout_do_corpo_tem_resposta_http():
    h = server.Handler.__new__(server.Handler)
    h.headers = {"Content-Length": "2"}

    def timeout(_n):
        raise TimeoutError("cliente parou de enviar")

    h.rfile = types.SimpleNamespace(read=timeout)
    with pytest.raises(server.PedidoInvalido) as erro:
        h._body()
    assert erro.value.code == 408


def test_servidores_independentes_mantem_seu_proprio_app():
    servidores = [server.serve(types.SimpleNamespace(state=lambda i=i: {"id": i}),
                              port=0) for i in range(2)]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servidores]
    for t in threads:
        t.start()
    try:
        for i, s in enumerate(servidores):
            conn = http.client.HTTPConnection("127.0.0.1", s.server_port, timeout=2)
            try:
                conn.request("GET", "/api/state")
                resposta = conn.getresponse()
                assert resposta.status == 200
                assert resposta.getheader("X-Content-Type-Options") == "nosniff"
                assert json.loads(resposta.read()) == {"id": i}
            finally:
                conn.close()
    finally:
        for s in servidores:
            s.shutdown()
            s.server_close()
        for t in threads:
            t.join(2)
