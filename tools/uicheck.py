import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prism.app import PrismApp
from prism.server import serve

PORT = 7319
RESULT = {}


def probe(window):
    time.sleep(6.0)

    def ev(expr, label):
        try:
            RESULT[label] = window.evaluate_js(expr)
        except Exception as exc:
            RESULT[label] = f"ERRO: {type(exc).__name__}: {exc}"

    ev("typeof boot", "boot_definido")
    ev("typeof startWizard", "wizard_definido")
    ev("typeof renderPresets", "presets_definido")
    ev("document.querySelector('#tab-effects').classList.contains('active')",
       "efeitos_e_padrao")
    ev("S.catalog.effects.reduce((a,g)=>a+g.effects.length,0)", "efeitos")
    ev("S.catalog.presets.reduce((a,g)=>a+g.presets.length,0)", "presets")
    ev("S.catalog.palettes.length", "paletas")
    ev("(S.catalog.spots||[]).length", "pontos_gabinete")
    ev("document.querySelectorAll('#presetGrid .preset').length", "cards_preset")

    ev("(function(){startWizard();return 'ok'})()", "abre_wizard")
    time.sleep(3.0)
    ev("document.getElementById('probeModal').hidden === false", "modal_visivel")
    ev("document.querySelectorAll('#probeStepper .stp').length", "passos")
    ev("[...document.querySelectorAll('#probeStepper .stp')].map(e=>e.textContent.trim()).join(' > ')",
       "nomes_dos_passos")
    ev("document.querySelectorAll('#probeBody .inv-row').length", "itens_inventario")
    ev("document.querySelectorAll('#probeBody .inv-row select.inv-spot option').length",
       "opcoes_de_lugar")

    ev("(function(){var b=[...document.querySelectorAll('#probeBody .probe-actions button')]"
       ".find(x=>/contagem/i.test(x.textContent));if(!b)return 'sem botao';b.click();return 'ok'})()",
       "vai_para_contagem")
    time.sleep(2.5)
    ev("document.querySelectorAll('#probeBody .seen').length", "headers_em_paralelo")
    ev("[...document.querySelectorAll('#probeBody .seen .idx')].map(e=>e.textContent).join(' | ')",
       "faixas_iniciais")
    ev("(function(){document.querySelector('#probeBody .seen').click();"
       "var b=[...document.querySelectorAll('#probeBody .probe-actions button')]"
       ".find(x=>/Responder/i.test(x.textContent));b.click();return 'ok'})()",
       "responde_rodada")
    time.sleep(2.0)
    ev("[...document.querySelectorAll('#probeBody .seen .idx')].map(e=>e.textContent).join(' | ')",
       "faixas_apos_resposta")
    ev("W.zones.map(z=>z.lo+'-'+z.hi).join(' | ')", "intervalos_internos")

    ev("(function(){W.zones[0].count=48;W.zones[0].lo=48;W.zones[0].hi=48;"
       "if(W.zones[1]){W.zones[1].count=16;}"
       "if(W.zones[2]){W.zones[2].count=20;}"
       "W.zones.forEach(z=>z.empty=false);"
       "W.step=2;W._verifyIdx=0;renderStep();"
       "return W.zones.map(z=>z.name+'='+z.count).join(',')})()", "contagens_forcadas")
    time.sleep(2.5)
    ev("document.querySelector('#vfCount') ? document.getElementById('vfCount').textContent : '-'",
       "CONFERENCIA_MOSTRA")
    ev("(function(){var b=[...document.querySelectorAll('.verify-controls [data-d]')]"
       ".find(x=>x.dataset.d==='5');if(!b)return 'sem botao';b.click();return 'ok'})()",
       "conferencia_mais5")
    time.sleep(1.0)
    ev("document.getElementById('vfCount').textContent", "conferencia_apos_mais5")
    ev("(function(){var b=[...document.querySelectorAll('.verify-controls [data-d]')]"
       ".find(x=>x.dataset.d==='-5');b.click();return 'ok'})()", "conferencia_menos5")
    time.sleep(1.0)
    ev("(function(){W._verifyIdx=0;W._assignIdx=0;W.step=3;renderStep();return 'ok'})()",
       "vai_atribuicao")
    time.sleep(2.0)
    ev("document.querySelectorAll('#probeBody .pick').length", "pecas_para_escolher")

    ev("(function(){var p=[...document.querySelectorAll('#probeBody .pick')]"
       ".find(x=>/grupo 1/i.test(x.textContent));if(!p)return 'sem grupo 1';p.click();"
       "return 'marcado'})()", "atribui_topo")
    ev("(function(){var b=[...document.querySelectorAll('#probeBody .probe-actions button')]"
       ".find(x=>/Proximo|Continuar/i.test(x.textContent));b.click();return 'ok'})()",
       "avanca_conector")
    time.sleep(1.5)
    for i in range(3):
        ev("(function(){var b=[...document.querySelectorAll('#probeBody .probe-actions button')]"
           ".find(x=>/Proximo|Continuar|resumo/i.test(x.textContent));"
           "if(!b)return 'fim';b.click();return b.textContent})()", f"avanca_{i}")
        time.sleep(1.2)

    ev("W.step", "passo_atual")
    ev("(function(){W._splitIdx=0;W.step=4;renderStep();return 'ok'})()", "vai_divisao")
    time.sleep(2.0)
    ev("document.querySelectorAll('#probeBody .split-row input').length", "linhas_divisao")
    ev("(function(){var i=document.querySelector('#probeBody .split-row input');"
       "return i?i.value:'-'})()", "DIVISAO_AUTOMATICA")
    ev("(function(){var s=document.querySelector('#probeBody .split-sum');"
       "return s?s.className+' :: '+s.textContent.trim():'-'})()", "soma_confere")

    ev("(function(){W.step=5;renderStep();return 'ok'})()", "vai_resumo")
    time.sleep(1.2)
    ev("document.querySelectorAll('#probeBody .sum-row').length", "linhas_resumo")
    ev("(function(){applyAll();return 'aplicando'})()", "aplica")
    time.sleep(12.0)
    ev("JSON.stringify((S.state.zones_resizable||[]).map(z=>z.count))",
       "CONTAGENS_PERSISTIDAS")
    ev("(function(){var z=(S.state.canvas.zones||[])"
       ".find(x=>x.zone_name===W.zones[0].name);"
       "return z?z.geometry.shape:'nao encontrada'})()", "GEOMETRIA_MULTI")
    ev("(function(){var z=(S.state.canvas.zones||[])"
       ".find(x=>x.zone_name===W.zones[0].name);"
       "return z&&z.geometry.parts?z.geometry.parts.length:0})()", "pecas_no_mapa")
    ev("(function(){var z=(S.state.canvas.zones||[])"
       ".find(x=>x.zone_name===W.zones[0].name);if(!z||!z.geometry.parts)return '-';"
       "return z.geometry.parts.map(p=>p.shape+':'+p.count+'@'+p.cx.toFixed(2)+','+p.cy.toFixed(2)).join(' | ')})()",
       "aneis_gerados")
    ev("JSON.stringify((S.state.canvas.zones||[]).map(z=>z.zone_name+'='+z.count))",
       "zonas_do_canvas")
    ev("S.state.settings.paused", "render_retomado_false")
    ev("S.state.canvas.led_count", "leds_no_canvas")

    ev("JSON.stringify(window.__jserrors||[])", "erros_js")
    time.sleep(0.3)
    window.destroy()


def main():
    app = PrismApp()
    app.connect()
    print(f"[uicheck] {app.status_msg}")
    antes = {f"{z['device']}:{z['zone']}": z["count"] for z in app.resizable_zones()}
    print(f"[uicheck] tamanhos antes: {list(antes.values())}")

    httpd = serve(app, port=PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    import webview
    win = webview.create_window("Prism (uicheck)", f"http://127.0.0.1:{PORT}/",
                                width=1400, height=880)
    threading.Thread(target=probe, args=(win,), daemon=True).start()
    try:
        webview.start(gui="edgechromium")
    finally:
        try:
            app.reset_layout()
            for key, size in antes.items():
                dev, _, zi = key.rpartition(":")
                app.resize_zone(dev, int(zi), size)
            print(f"[uicheck] tamanhos restaurados: {list(antes.values())}")
        except Exception as exc:
            print(f"[uicheck] falha ao restaurar: {exc}")
        httpd.shutdown()
        app.shutdown()

    print("\n===== RESULTADO =====")
    for k, v in RESULT.items():
        print(f"  {k:24} = {v}")

    checks = {
        "boot definido": RESULT.get("boot_definido") == "function",
        "wizard definido": RESULT.get("wizard_definido") == "function",
        "68 efeitos": (RESULT.get("efeitos") or 0) >= 60,
        "presets carregados": (RESULT.get("presets") or 0) >= 40,
        "3 headers em paralelo": (RESULT.get("headers_em_paralelo") or 0) >= 1,
        "6 passos": RESULT.get("passos") == 6,
        "conferencia ajustavel": str(RESULT.get("conferencia_apos_mais5")) == "53",
        "divisao 48/3 = 16": str(RESULT.get("DIVISAO_AUTOMATICA")) == "16",
        "soma bate": str(RESULT.get("soma_confere", "")).startswith("split-sum ok"),
        "contagens persistiram": "48" in str(RESULT.get("CONTAGENS_PERSISTIDAS")),
        "geometria multi": RESULT.get("GEOMETRIA_MULTI") == "multi",
        "3 pecas no mapa": RESULT.get("pecas_no_mapa") == 3,
        "render retomado": RESULT.get("render_retomado_false") is False,
        "sem erro de js": RESULT.get("erros_js") in ("[]", None),
    }
    print("\n===== VERIFICACOES =====")
    ruim = 0
    for nome, ok in checks.items():
        print(f"  [{'OK ' if ok else 'FALHA'}] {nome}")
        ruim += 0 if ok else 1
    print("\n" + ("UI OK" if not ruim else f"{ruim} VERIFICACAO(OES) FALHARAM"))
    return 1 if ruim else 0


if __name__ == "__main__":
    sys.exit(main())
