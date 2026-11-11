"use strict";

// Regressions for the browser's network and editing logic. Run with
// `node --test tests/test_frontend.js`; Node's built-in modules are sufficient.
// The VM executes the actual app helpers with fake DOM, timers and HTTP.
// It never starts Spectra, OpenRGB or any hardware access.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appSource = fs.readFileSync(path.join(__dirname, "../ui/js/app.js"), "utf8");

function section(start, end) {
  const a = appSource.indexOf(start);
  const b = appSource.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `Missing frontend test boundary: ${start}`);
  return appSource.slice(a, b);
}

const testedSource = [
  section('"use strict";', "function showTab("),
  section("let stateRequest =", "function digitandoEm("),
  section("function currentLayer()", "function renderParams("),
  section('$("#btnResetParams").addEventListener', "function openEffectPicker("),
  section("async function pickEffect(", '$("#presetSearch").addEventListener'),
  `toast = (...args) => __toasts.push(args);
   globalThis.frontend = { API, orderedPost, S, throttle, patchLayer,
     patchLayerSoon, flushLayerPatch, refreshState, pickEffect, writeQueues,
     pendingLayerPatches };`,
].join("\n");

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function response(data = {}, status = 200, invalid = false) {
  return {
    status, ok: status >= 200 && status < 300,
    json: () => invalid ? Promise.reject(new SyntaxError("HTML response")) : Promise.resolve(data),
  };
}

const drain = () => new Promise((resolve) => setImmediate(resolve));
const plain = (value) => JSON.parse(JSON.stringify(value));

function harness() {
  const timers = new Map(), elements = new Map(), calls = [], statuses = [], toasts = [];
  let timerId = 0, transport = async () => response();
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      hidden: true, value: "", textContent: "", listeners: {},
      classList: { toggle() {}, add() {}, remove() {} },
      setAttribute() {},
      addEventListener(name, handler) { this.listeners[name] = handler; },
    });
    return elements.get(selector);
  }
  const noop = () => {};
  const context = vm.createContext({
    Error, TypeError, SyntaxError,
    console: { warn: noop },
    window: { addEventListener: noop },
    document: { activeElement: null, querySelector: element,
      querySelectorAll: () => [], body: element("body") },
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url, options) { calls.push({ url, options }); return transport(url, options); },
    __toasts: toasts,
    setStatus: (...args) => statuses.push(args),
    activeTab: () => "scene",
    renderLayers: noop, renderCanvasVazio: noop, renderParams: noop,
    closeModal: noop,
    effectDef: () => ({ label: "Efeito", params: [{ name: "speed", default: 1 }] }),
  });
  vm.runInContext(testedSource, context, { filename: "ui/js/app.js" });
  return {
    ...context.frontend, calls, statuses, toasts, timers, element,
    transport(fn) { transport = fn; },
    run(code) { return vm.runInContext(code, context); },
    flushTimers() {
      const due = [...timers.values()];
      timers.clear();
      for (const fn of due) fn();
    },
  };
}

test("API reports HTTP, malformed response and application errors", async (t) => {
  const cases = [
    ["HTTP reason", response({ error: "Camada nao existe" }, 404), /Camada nao existe/],
    ["HTTP without JSON", response(null, 503, true), /HTTP 503/],
    ["invalid success", response(null, 200, true), /resposta invalida/],
    ["application failure", response({ error: "Servidor ocupado" }), /Servidor ocupado/],
  ];
  for (const [name, result, message] of cases) await t.test(name, async () => {
    const h = harness();
    h.transport(async () => result);
    await assert.rejects(h.API.post("/api/settings", { fps: 60 }), (error) => {
      assert.match(error.message, message);
      assert.equal(error.isApiError, true);
      return true;
    });
  });
});

test("API handles empty success and network failure, and sends JSON without caching", async () => {
  const h = harness();
  h.transport(async () => response(undefined, 204));
  assert.deepEqual(plain(await h.API.post("/api/settings", { fps: 60 })), {});
  assert.equal(h.calls[0].options.cache, "no-store");
  assert.equal(h.calls[0].options.method, "POST");
  assert.equal(h.calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(h.calls[0].options.body, '{"fps":60}');
  h.transport(async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(h.API.get("/api/state"), /Sem resposta do servidor local/);
});

test("ordered writes serialize one family, copy payloads and allow another family through", async () => {
  const h = harness(), first = deferred();
  h.transport((url) => url === "/first" ? first.promise : Promise.resolve(response()));
  const body = { params: { speed: 1 } };
  const a = h.orderedPost("layer:A", "/first", body);
  const b = h.orderedPost("layer:A", "/second", { speed: 2 });
  const independent = h.orderedPost("settings", "/independent", {});
  body.params.speed = 99;
  await drain();
  assert.deepEqual(h.calls.map((call) => call.url), ["/first", "/independent"]);
  assert.equal(JSON.parse(h.calls[0].options.body).params.speed, 1);
  first.resolve(response());
  await Promise.all([a, b, independent]);
  assert.deepEqual(h.calls.map((call) => call.url), ["/first", "/independent", "/second"]);
  assert.equal(h.writeQueues.size, 0);
});

test("a failed write does not block later writes or leak its queue", async () => {
  const h = harness();
  h.transport(async (url) => url === "/bad" ? response({ error: "Falhou" }, 500) : response());
  const failed = h.orderedPost("settings", "/bad", {});
  const succeeds = h.orderedPost("settings", "/good", {});
  await assert.rejects(failed, /Falhou/);
  await succeeds;
  assert.deepEqual(h.calls.map((call) => call.url), ["/bad", "/good"]);
  assert.equal(h.writeQueues.size, 0);
});

test("slider edits merge parameters and stay with the layer selected at the gesture", async () => {
  const h = harness();
  h.S.state = { layers: [
    { id: "A", params: { speed: 1, size: 3, color: "red" }, opacity: 1 },
    { id: "B", params: { speed: 2 }, opacity: 1 },
  ] };
  h.S.selected = "A";
  h.patchLayerSoon({ params: { speed: 5 } });
  h.patchLayerSoon({ params: { size: 9 } });
  h.patchLayerSoon({ opacity: 0.4 });
  h.S.selected = "B";
  h.patchLayerSoon({ params: { speed: 8 } });
  h.flushTimers();
  await drain();
  const edits = h.calls.map((call) => JSON.parse(call.options.body));
  assert.deepEqual(edits, [
    { id: "A", patch: { params: { speed: 5, size: 9 }, opacity: 0.4 } },
    { id: "B", patch: { params: { speed: 8 } } },
  ]);
  assert.deepEqual(plain(h.S.state.layers[0].params), { speed: 5, size: 9, color: "red" });
  assert.equal(h.S.state.layers[0].opacity, 0.4);
  assert.equal(h.pendingLayerPatches.size, 0);
});

test("editing a deleted layer produces no write", async () => {
  const h = harness();
  h.S.selected = "deleted";
  h.S.state = { layers: [] };
  h.patchLayerSoon({ params: { speed: 10 } });
  h.flushTimers();
  await drain();
  assert.equal(h.calls.length, 0);
});

test("throttle keeps the latest input and supports flush and cancellation", () => {
  const h = harness(), values = [];
  const change = h.throttle((value) => { values.push(value); return value; }, 40);
  change(1); change(2);
  assert.equal(change.flush(), 2);
  h.flushTimers();
  assert.deepEqual(values, [2]);
  change(3); change.cancel();
  h.flushTimers();
  assert.deepEqual(values, [2]);
  change(4); change(5); h.flushTimers();
  assert.deepEqual(values, [2, 5]);
});

test("older state responses cannot replace a newer success", async () => {
  const h = harness(), old = deferred(), latest = deferred();
  const responses = [old, latest];
  h.transport(() => responses.shift().promise);
  const a = h.refreshState(), b = h.refreshState();
  latest.resolve(response({ connected: true, version: "new" }));
  await b;
  old.resolve(response({ connected: false, version: "old" }));
  await a;
  assert.equal(h.S.state.version, "new");
  assert.equal(h.statuses.length, 1);
  assert.equal(h.statuses[0][0], "ok");
});

test("older failure cannot replace the status of a newer success", async () => {
  const h = harness(), old = deferred(), latest = deferred();
  const responses = [old, latest];
  h.transport(() => responses.shift().promise);
  const a = h.refreshState(), b = h.refreshState();
  latest.resolve(response({ connected: true }));
  await b;
  old.reject(new TypeError("Server stopped"));
  await a;
  assert.equal(h.statuses.length, 1);
  assert.equal(h.statuses[0][0], "ok");
});

test("older success cannot undo a newer connection failure", async () => {
  const h = harness(), old = deferred(), latest = deferred();
  const responses = [old, latest];
  h.transport(() => responses.shift().promise);
  const a = h.refreshState(), b = h.refreshState();
  latest.reject(new TypeError("Server stopped"));
  await b;
  old.resolve(response({ connected: true, version: "stale" }));
  await a;
  assert.equal(h.S.state, null);
  assert.equal(h.statuses.length, 1);
  assert.equal(h.statuses[0][0], "err");
});

test("reset waits for pending slider edits and its undo restores that last value", async () => {
  const h = harness();
  h.S.state = { layers: [{ id: "A", effect: "wave", params: { speed: 2 } }] };
  h.S.selected = "A";
  h.run("refreshState = async () => {};");
  h.patchLayerSoon({ params: { speed: 8 } });
  await h.element("#btnResetParams").listeners.click();
  h.flushTimers();
  await drain();
  let edits = h.calls.map((call) => JSON.parse(call.options.body));
  assert.deepEqual(edits.map((edit) => edit.patch.params.speed), [8, 1]);
  const undo = h.toasts.find((toast) => toast[2]?.label === "Desfazer")[2];
  h.patchLayerSoon({ params: { speed: 5 } });
  await undo.run();
  edits = h.calls.map((call) => JSON.parse(call.options.body));
  assert.deepEqual(edits.map((edit) => edit.patch.params.speed), [8, 1, 5, 8]);
  assert.equal(h.pendingLayerPatches.size, 0);
});

test("changing the effect drains old slider edits before replacing its parameters", async () => {
  const h = harness();
  h.S.state = { layers: [{ id: "A", effect: "wave", params: { speed: 2 }, name: "Wave" }] };
  h.S.selected = "A";
  h.S.effectPickTarget = "A";
  h.run("refreshState = async () => {};");
  h.patchLayerSoon({ params: { speed: 8 } });
  await h.pickEffect("static");
  h.flushTimers();
  await drain();
  const edits = h.calls.map((call) => JSON.parse(call.options.body));
  assert.deepEqual(edits, [
    { id: "A", patch: { params: { speed: 8 } } },
    { id: "A", patch: { effect: "static" } },
  ]);
  const undo = h.toasts.find((toast) => toast[2]?.label === "Desfazer")[2];
  await undo.run();
  assert.deepEqual(JSON.parse(h.calls[2].options.body), {
    id: "A", patch: { effect: "wave", params: { speed: 8 }, name: "Wave" },
  });
});

// A regua de Configurar LEDs: o que acende no gabinete e como as pecas se
// dividem. So as funcoes puras de ui/js/probe.js, sem DOM nem servidor.
function regua() {
  const fonte = fs.readFileSync(path.join(__dirname, "../ui/js/probe.js"), "utf8");
  const ini = fonte.indexOf("// ---- regua: funcoes puras");
  const fim = fonte.indexOf("// ---- regua: fim das funcoes puras");
  assert.ok(ini >= 0 && fim > ini, "Missing ruler test boundary in probe.js");
  const context = vm.createContext({});
  vm.runInContext(fonte.slice(ini, fim) + `
    globalThis.r = { coresDaRegua, contagemDoCursor, marcarFim, tirarFim, cortarPecas, pecasSalvas,
      pecaDoLed, CAL_VERDE, CAL_VERMELHO, CAL_BRANCO, CAL_SOBRA, CAL_APAGADO,
      CAL_CORES_PECAS };`, context, { filename: "ui/js/probe.js" });
  return context.r;
}

const leds = (hex) => hex.match(/.{6}/g);
// array criado no contexto do VM nao e igual por referencia ao daqui
const contas = (pecas) => Array.from(pecas, (p) => p.count);

test("ruler lights green up to the cursor, white on it and red after it", () => {
  const r = regua();
  assert.deepEqual(leds(r.coresDaRegua("ate", 3, 5, 0, [])),
    [r.CAL_VERDE, r.CAL_VERDE, r.CAL_BRANCO, r.CAL_VERMELHO, r.CAL_VERMELHO]);
  assert.deepEqual(leds(r.coresDaRegua("ate", 0, 3, 0, [])),
    [r.CAL_VERMELHO, r.CAL_VERMELHO, r.CAL_VERMELHO]);
});

test("ruler single mode lights only the cursor LED", () => {
  const r = regua();
  assert.deepEqual(leds(r.coresDaRegua("so", 2, 4, 4, [])),
    [r.CAL_APAGADO, r.CAL_BRANCO, r.CAL_APAGADO, r.CAL_APAGADO]);
});

test("ruler piece mode colors each piece and flags LEDs past the count", () => {
  const r = regua();
  const [a, b] = r.CAL_CORES_PECAS;
  assert.deepEqual(leds(r.coresDaRegua("pecas", 1, 6, 4, [{ count: 2 }, { count: 1 }])),
    [a, a, b, r.CAL_SOBRA, r.CAL_VERMELHO, r.CAL_VERMELHO]);
});

test("marking a piece end appends after the last piece or splits the one under the cursor", () => {
  const r = regua();
  let p = r.marcarFim([], 8);
  assert.deepEqual(contas(p), [8]);
  p = r.marcarFim(p, 16);
  assert.deepEqual(contas(p), [8, 8]);
  p = r.marcarFim(p, 4);
  assert.deepEqual(contas(p), [4, 4, 8]);
  assert.deepEqual(contas(r.marcarFim(p, 8)), [4, 4, 8]);
  assert.deepEqual(contas(r.marcarFim(p, 0)), [4, 4, 8]);
  assert.equal(r.pecaDoLed(p, 5), 1);
  assert.equal(r.pecaDoLed(p, 17), -1);
});

test("removing a piece end merges it with the next one and drops the last", () => {
  const r = regua();
  const p = [{ count: 4 }, { count: 4 }, { count: 8 }];
  assert.deepEqual(contas(r.tirarFim(p, 0)), [8, 8]);
  assert.deepEqual(contas(r.tirarFim(p, 2)), [4, 4]);
  assert.deepEqual(contas(r.tirarFim(p, 5)), [4, 4, 8]);
});

test("pieces are cut at the connector count, saved or not", () => {
  const r = regua();
  assert.deepEqual(contas(r.cortarPecas([{ count: 8 }, { count: 8 }, { count: 8 }], 20)), [8, 8, 4]);
  assert.deepEqual(contas(r.pecasSalvas([8, "x", 8], 10)), [8, 2]);
  assert.deepEqual(contas(r.pecasSalvas(null, 10)), []);
  assert.deepEqual(contas(r.pecasSalvas([8, 8], 0)), []);
});

test("in the up-to mode the green LEDs are what gets saved", () => {
  const r = regua();
  assert.equal(r.contagemDoCursor("ate", 30, 22), 30);
  assert.equal(r.contagemDoCursor("ate", 0, 22), 0);
  assert.equal(r.contagemDoCursor("so", 30, 22), 22);
  assert.equal(r.contagemDoCursor("pecas", 30, 22), 22);
});
