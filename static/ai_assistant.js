(function () {
    if (document.getElementById('ai-assistant-panel') || window.__printerAIWidget) return;
    window.__printerAIWidget = true;

    var botIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
    var closeIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';

    var root = document.createElement('div');
    root.innerHTML =
        '<button id="gai-toggle" type="button" aria-label="Toggle AI Assistant" title="AI Assistant" class="fixed bottom-6 right-6 z-[60] h-14 w-14 rounded-full bg-slate-900 text-cyan-300 border border-cyan-400/40 shadow-2xl flex items-center justify-center hover:bg-slate-800 hover:scale-105 transition">' + botIcon + '</button>' +
        '<section id="gai-panel" class="hidden fixed bottom-24 right-4 sm:right-6 z-[60] w-[calc(100vw-2rem)] max-w-sm rounded-2xl bg-gradient-to-b from-slate-900 to-slate-950 text-white border border-white/10 shadow-2xl">' +
            '<div class="flex items-start justify-between gap-3 p-4 pb-3">' +
                '<div>' +
                    '<h3 class="text-sm font-bold">AI Business Assistant</h3>' +
                    '<p class="text-[11px] text-slate-400">Read-only sales, stock and customer intelligence</p>' +
                '</div>' +
                '<button id="gai-close" type="button" aria-label="Close AI Assistant" class="text-slate-400 hover:text-white p-1 rounded-lg">' + closeIcon + '</button>' +
            '</div>' +
            '<div class="flex flex-wrap gap-2 px-4">' +
                '<button type="button" data-gai-action="insights" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-[11px] font-semibold transition">Insights</button>' +
                '<button type="button" data-gai-action="forecast" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-[11px] font-semibold transition">3-Month Forecast</button>' +
            '</div>' +
            '<div id="gai-response" class="hidden mx-4 mt-3 rounded-xl bg-black/30 border border-white/10 p-3 text-sm text-slate-100 whitespace-pre-wrap leading-6 max-h-60 overflow-y-auto"></div>' +
            '<form id="gai-form" class="p-4 flex gap-2">' +
                '<input id="gai-input" type="text" maxlength="2000" placeholder="Ask about revenue, stock..." autocomplete="off" class="flex-1 min-w-0 rounded-xl bg-white text-slate-900 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-cyan-300">' +
                '<button id="gai-send" type="submit" class="px-3.5 py-2.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 text-xs font-bold transition">Ask</button>' +
            '</form>' +
            '<p id="gai-status" class="px-4 pb-4 -mt-1 text-[11px] text-slate-400">AI responses use a read-only snapshot of dashboard data.</p>' +
        '</section>';
    document.body.appendChild(root);

    var toggle = document.getElementById('gai-toggle');
    var panel = document.getElementById('gai-panel');
    var closeBtn = document.getElementById('gai-close');
    var form = document.getElementById('gai-form');
    var input = document.getElementById('gai-input');
    var sendBtn = document.getElementById('gai-send');
    var responseBox = document.getElementById('gai-response');
    var status = document.getElementById('gai-status');
    var actionButtons = document.querySelectorAll('[data-gai-action]');
    var busy = false;

    function setStatus(text, isError) {
        status.textContent = text;
        status.className = isError
            ? 'px-4 pb-4 -mt-1 text-[11px] text-rose-300'
            : 'px-4 pb-4 -mt-1 text-[11px] text-slate-400';
    }

    function openPanel() {
        panel.classList.remove('hidden');
        input.focus();
    }

    function closePanel() {
        panel.classList.add('hidden');
    }

    toggle.addEventListener('click', function () {
        if (panel.classList.contains('hidden')) openPanel();
        else closePanel();
    });
    closeBtn.addEventListener('click', closePanel);
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') closePanel();
    });

    async function streamAI(url, body) {
        if (busy) return false;
        busy = true;
        sendBtn.disabled = true;
        actionButtons.forEach(function (button) { button.disabled = true; });
        responseBox.classList.remove('hidden');
        responseBox.textContent = 'AI is analyzing the latest business data...';
        setStatus('Preparing a read-only analytics snapshot...', false);
        var answer = '';
        var controller = new AbortController();
        var timer;
        var timeout = new Promise(function (_, reject) {
            timer = setTimeout(function () {
                controller.abort();
                reject(new Error('AI request timed out. Please try again.'));
            }, 120000);
        });
        try {
            var res = await Promise.race([fetch(url, {
                method: 'POST',
                headers: body ? { 'Content-Type': 'application/json' } : {},
                body: body ? JSON.stringify(body) : undefined,
                signal: controller.signal
            }), timeout]);
            if ((res.status === 404 || res.status === 405) && url.endsWith('/stream')) {
                var legacy = await Promise.race([fetch(url.slice(0, -7), {
                    method: 'POST',
                    headers: body ? { 'Content-Type': 'application/json' } : {},
                    body: body ? JSON.stringify(body) : undefined,
                    signal: controller.signal
                }), timeout]);
                var data = await Promise.race([legacy.json(), timeout]);
                if (!legacy.ok || !data.success) throw new Error(data.message || 'Server returned ' + legacy.status);
                responseBox.textContent = data.answer;
                setStatus('Generated from the latest available dashboard data.', false);
                return true;
            }
            if (!res.ok || !res.body) {
                var message = 'Server returned ' + res.status;
                try {
                    var errorData = await Promise.race([res.json(), timeout]);
                    message = errorData.message || message;
                } catch (e) {}
                throw new Error(message);
            }
            var reader = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var receivedDone = false;
            while (true) {
                var chunk = await Promise.race([reader.read(), timeout]);
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                var sep;
                while ((sep = buffer.indexOf('\n\n')) !== -1) {
                    var raw = buffer.slice(0, sep);
                    buffer = buffer.slice(sep + 2);
                    var line = raw.split('\n').find(function (l) { return l.startsWith('data:'); });
                    if (!line) continue;
                    var evt;
                    try {
                        evt = JSON.parse(line.slice(5).trim());
                    } catch (e) {
                        continue;
                    }
                    if (evt.error) throw new Error(evt.error);
                    if (evt.done) receivedDone = true;
                    if (evt.delta) {
                        answer += evt.delta;
                        responseBox.textContent = answer;
                        responseBox.scrollTop = responseBox.scrollHeight;
                    }
                }
            }
            if (!receivedDone) throw new Error('AI response was interrupted.');
            if (!answer.trim()) throw new Error('AI returned an empty response.');
            setStatus('Generated from the latest available dashboard data.', false);
            return true;
        } catch (err) {
            responseBox.textContent = answer || 'AI request failed.';
            setStatus(err.message || 'AI request failed.', true);
            return false;
        } finally {
            clearTimeout(timer);
            controller.abort();
            busy = false;
            sendBtn.disabled = false;
            actionButtons.forEach(function (button) { button.disabled = false; });
        }
    }

    document.querySelectorAll('[data-gai-action]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            openPanel();
            streamAI('/api/ai/' + btn.dataset.gaiAction + '/stream', null);
        });
    });

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        var submitted = input.value;
        var message = submitted.trim();
        if (!message) return;
        openPanel();
        var ok = await streamAI('/api/ai/chat/stream', { message: message });
        if (ok && input.value === submitted) input.value = '';
    });
})();
