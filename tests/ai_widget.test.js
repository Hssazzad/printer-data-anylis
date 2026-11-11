const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function widget(fetch, clock = {setTimeout, clearTimeout}) {
  const elements = {};
  function element(id) {
    return elements[id] ||= {
      value: '', textContent: '', disabled: false, handlers: {},
      classList: { hidden: id === 'gai-panel', contains() { return this.hidden; }, add() { this.hidden = true; }, remove() { this.hidden = false; } },
      addEventListener(name, fn) { this.handlers[name] = fn; }, focus() {}
    };
  }
  const actions = [element('insights'), element('forecast')];
  actions[0].dataset = {gaiAction: 'insights'};
  actions[1].dataset = {gaiAction: 'forecast'};
  const document = {
    getElementById(id) { return id === 'ai-assistant-panel' ? null : element(id); },
    createElement() { return {}; }, body: {appendChild() {}}, addEventListener() {},
    querySelectorAll() { return actions; }
  };
  const context = {document, window: {}, fetch, TextDecoder, AbortController, ...clock};
  vm.runInNewContext(fs.readFileSync('static/ai_assistant.js', 'utf8'), context);
  return {element, actions};
}

function stream(events, gate) {
  let i = 0;
  return {ok: true, status: 200, body: {getReader() { return {async read() {
    if (i === 0 && gate) await gate;
    if (i === events.length) return {done: true};
    return {done: false, value: new TextEncoder().encode(events[i++])};
  }}; }}};
}

test('interrupted stream is reported as an error', async () => {
  const w = widget(async () => stream(['data: {"delta":"partial"}\n\n']));
  w.element('gai-input').value = 'question';
  await w.element('gai-form').handlers.submit({preventDefault() {}});
  assert.match(w.element('gai-status').textContent, /interrupted/);
  assert.equal(w.element('gai-input').value, 'question');
});

test('a running request is exclusive and preserves a newly typed draft', async () => {
  let release;
  let calls = 0;
  const gate = new Promise(resolve => { release = resolve; });
  const w = widget(async () => { calls++; return stream(['data: {"delta":"answer"}\n\ndata: {"done":true}\n\n'], gate); });
  w.element('gai-input').value = 'first question';
  const pending = w.element('gai-form').handlers.submit({preventDefault() {}});
  w.element('gai-input').value = 'new draft';
  w.actions[0].handlers.click();
  assert.equal(calls, 1);
  assert.ok(w.actions.every(button => button.disabled));
  release();
  await pending;
  assert.equal(w.element('gai-response').textContent, 'answer');
  assert.equal(w.element('gai-input').value, 'new draft');
  assert.ok(w.actions.every(button => !button.disabled));
});

test('management table escapes stored menu titles', async () => {
  const source = fs.readFileSync('templates/main_menus.html', 'utf8');
  const esc = source.match(/function esc\(s\) \{[^\n]+\}/)[0];
  const start = source.indexOf('async function loadMainMenusTable()');
  const end = source.indexOf('        function resetForm()', start);
  const nodes = {};
  const payload = '<img src=x onerror=alert(1)>';
  const context = {
    document: {getElementById(id) { return nodes[id] ||= {}; }},
    fetch: async () => ({json: async () => [{id: 1, title: payload, menu_order: 1, is_active: 1}]}),
    lucide: {createIcons() {}}, console, cachedMainMenus: []
  };
  vm.runInNewContext(esc + '\n' + source.slice(start, end), context);
  await context.loadMainMenusTable();
  assert.ok(nodes['main-menu-tbody'].innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(!nodes['main-menu-tbody'].innerHTML.includes(payload));
});

test('menu forms report rejected URLs without clearing input', async () => {
  for (const file of ['main_menus.html', 'sub_menus.html']) {
    const source = fs.readFileSync('templates/' + file, 'utf8');
    const start = source.indexOf('async function handleFormSubmit(');
    const end = source.indexOf('        async function delete', start);
    let message = '';
    let reset = false;
    const context = {
      document: {getElementById(id) { return {value: id === 'sub-parent-id' ? '1' : id === 'menu-url' ? 'javascript:alert(1)' : '', checked: true}; }},
      fetch: async () => ({ok: false, status: 400, json: async () => ({message: 'Invalid menu URL'})}),
      alert: text => { message = text; }, resetForm: () => { reset = true; }, console: {error() {}}
    };
    vm.runInNewContext(source.slice(start, end), context);
    await context.handleFormSubmit({preventDefault() {}});
    assert.equal(message, 'Invalid menu URL');
    assert.equal(reset, false);
  }
});


test('a stalled request times out and permits a retry', async () => {
  let trigger;
  let signal;
  let calls = 0;
  const clock = {setTimeout(fn) { trigger = fn; return 1; }, clearTimeout() {}};
  const w = widget((url, options) => {
    signal = options.signal;
    calls++;
    return calls === 1 ? new Promise(() => {}) : Promise.resolve(stream(['data: {"delta":"ok"}\n\ndata: {"done":true}\n\n']));
  }, clock);
  w.element('gai-input').value = 'question';
  const pending = w.element('gai-form').handlers.submit({preventDefault() {}});
  trigger();
  await pending;
  assert.equal(signal.aborted, true);
  assert.match(w.element('gai-status').textContent, /timed out/);
  assert.equal(w.element('gai-send').disabled, false);
  await w.element('gai-form').handlers.submit({preventDefault() {}});
  assert.equal(calls, 2);
  assert.equal(w.element('gai-response').textContent, 'ok');
});


test('a stalled error response also releases the request', async () => {
  let trigger;
  const clock = {setTimeout(fn) { trigger = fn; return 1; }, clearTimeout() {}};
  const w = widget(async () => ({ok: false, status: 503, json: () => new Promise(() => {})}), clock);
  w.element('gai-input').value = 'question';
  const pending = w.element('gai-form').handlers.submit({preventDefault() {}});
  await Promise.resolve();
  await Promise.resolve();
  trigger();
  await pending;
  assert.equal(w.element('gai-send').disabled, false);
  assert.match(w.element('gai-status').textContent, /Server returned 503/);
});
