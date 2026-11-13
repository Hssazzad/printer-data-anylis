(function () {
    if (document.getElementById('ai-assistant-panel') || window.__printerAIWidget) return;
    window.__printerAIWidget = true;

    var botIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
    var closeIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';

    var root = document.createElement('div');
    root.innerHTML =
        '<button id="gai-toggle" type="button" aria-label="Open AI Assistant" aria-controls="gai-panel" aria-expanded="false" title="AI Assistant" class="fixed bottom-6 right-6 z-[60] h-14 w-14 rounded-full bg-slate-900 text-cyan-300 border border-cyan-400/40 shadow-2xl flex items-center justify-center hover:bg-slate-800 hover:scale-105 transition">' + botIcon + '</button>' +
        '<section id="gai-panel" role="dialog" aria-labelledby="gai-title" aria-describedby="gai-subtitle" class="hidden fixed bottom-24 right-4 sm:right-6 z-[60] w-[calc(100vw-2rem)] max-w-sm rounded-2xl bg-gradient-to-b from-slate-900 to-slate-950 text-white border border-white/10 shadow-2xl">' +
            '<div class="flex items-start justify-between gap-3 p-4 pb-3">' +
                '<div>' +
                    '<h3 id="gai-title" class="text-sm font-bold">AI Business Assistant</h3>' +
                    '<p id="gai-subtitle" class="text-[11px] text-slate-400">Read-only sales, stock and customer intelligence</p>' +
                '</div>' +
                '<button id="gai-close" type="button" aria-label="Close AI Assistant" class="text-slate-400 hover:text-white p-1 rounded-lg">' + closeIcon + '</button>' +
            '</div>' +
            '<div class="flex flex-wrap gap-2 px-4">' +
                '<button type="button" data-gai-action="insights" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-50 text-[11px] font-semibold transition">Insights</button>' +
                '<button type="button" data-gai-action="forecast" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-50 text-[11px] font-semibold transition">3-Month Forecast</button>' +
            '</div>' +
            '<div id="gai-response" class="hidden mx-4 mt-3 rounded-xl bg-black/30 border border-white/10 p-3 text-sm text-slate-100 whitespace-pre-wrap leading-6 max-h-60 overflow-y-auto" aria-live="polite" aria-atomic="false" aria-busy="false"></div>' +
            '<p id="gai-context" class="hidden mx-4 mt-2 text-[10px] text-cyan-200/80 leading-4"></p>' +
            '<form id="gai-form" class="p-4 flex gap-2">' +
                '<input id="gai-input" type="text" maxlength="2000" placeholder="Ask about revenue, stock..." autocomplete="off" aria-label="Ask the AI business assistant" class="flex-1 min-w-0 rounded-xl bg-white text-slate-900 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-cyan-300">' +
                '<button id="gai-send" type="submit" class="px-3.5 py-2.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 disabled:opacity-50 text-slate-950 text-xs font-bold transition">Ask</button>' +
            '</form>' +
            '<p id="gai-status" class="px-4 pb-4 -mt-1 text-[11px] text-slate-400" aria-live="polite">AI responses use a read-only snapshot of dashboard data.</p>' +
        '</section>';
    document.body.appendChild(root);

    var toggle = document.getElementById('gai-toggle');
    var panel = document.getElementById('gai-panel');
    var closeBtn = document.getElementById('gai-close');
    var form = document.getElementById('gai-form');
    var input = document.getElementById('gai-input');
    var sendBtn = document.getElementById('gai-send');
    var responseBox = document.getElementById('gai-response');
    var contextNote = document.getElementById('gai-context');
    var status = document.getElementById('gai-status');
    var actionButtons = Array.prototype.slice.call(document.querySelectorAll('[data-gai-action]'));
    var busy = false;

    function setStatus(text, isError) {
        status.textContent = text;
        status.className = isError
            ? 'px-4 pb-4 -mt-1 text-[11px] text-rose-300'
            : 'px-4 pb-4 -mt-1 text-[11px] text-slate-400';
    }

    function periodLabel(value) {
        if (!value || !/^\d{4}-\d{2}$/.test(value)) return value || 'unknown';
        var parts = value.split('-');
        var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return months[Number(parts[1]) - 1] + ' ' + parts[0];
    }

    function setContext(meta, isForecast) {
        if (!meta || !meta.sales_period || !meta.sales_period.to) {
            contextNote.classList.add('hidden');
            contextNote.textContent = '';
            return;
        }
        var text = 'Data through ' + periodLabel(meta.sales_period.to);
        if (meta.data_is_stale) text += ' (latest available; may lag the current month)';
        if (meta.missing_months && meta.missing_months.length) {
            text += '. Missing month' + (meta.missing_months.length === 1 ? '' : 's') + ': ' + meta.missing_months.map(periodLabel).join(', ');
        }
        text += '.';
        if (isForecast) {
            text += meta.forecast_sufficient === false
                ? ' Not enough recent months for a reliable forecast.'
                : ' Directional estimate, not a guarantee.';
        }
        contextNote.textContent = text;
        contextNote.classList.remove('hidden');
    }

    function openPanel() {
        panel.classList.remove('hidden');
        toggle.setAttribute('aria-expanded', 'true');
        toggle.setAttribute('aria-label', 'Close AI Assistant');
        input.focus();
    }

    function closePanel() {
        if (panel.classList.contains('hidden')) return;
        panel.classList.add('hidden');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', 'Open AI Assistant');
        toggle.focus();
    }

    toggle.addEventListener('click', function () {
        if (panel.classList.contains('hidden')) openPanel();
        else closePanel();
    });
    closeBtn.addEventListener('click', closePanel);
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') closePanel();
    });

    async function streamAI(url, body, isForecast) {
        if (busy) return false;
        busy = true;
        sendBtn.disabled = true;
        actionButtons.forEach(function (button) { button.disabled = true; });
        responseBox.classList.remove('hidden');
        responseBox.setAttribute('aria-busy', 'true');
        responseBox.textContent = 'AI is analyzing the latest business data...';
        contextNote.classList.add('hidden');
        contextNote.textContent = '';
        setStatus('Preparing a read-only analytics snapshot...', false);
        var answer = '';
        try {
            var res = await fetch(url, {
                method: 'POST',
                headers: body ? { 'Content-Type': 'application/json' } : {},
                body: body ? JSON.stringify(body) : undefined
            });
            if ((res.status === 404 || res.status === 405) && url.endsWith('/stream')) {
                var legacy = await fetch(url.slice(0, -7), {
                    method: 'POST',
                    headers: body ? { 'Content-Type': 'application/json' } : {},
                    body: body ? JSON.stringify(body) : undefined
                });
                var data = await legacy.json().catch(function () { return {}; });
                if (!legacy.ok || !data.success) throw new Error(data.message || 'Server returned ' + legacy.status);
                responseBox.textContent = data.answer;
                setContext(data.metadata, isForecast);
                setStatus('Generated from the latest available dashboard data.', false);
                return true;
            }
            if (!res.ok || !res.body) {
                var message = 'Server returned ' + res.status;
                try {
                    var errorData = await res.json();
                    message = errorData.message || message;
                } catch (e) {}
                throw new Error(message);
            }
            var reader = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            while (true) {
                var chunk = await reader.read();
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
                    if (evt.meta) {
                        setContext(evt.meta, isForecast);
                        continue;
                    }
                    if (evt.delta) {
                        answer += evt.delta;
                        responseBox.textContent = answer;
                        responseBox.scrollTop = responseBox.scrollHeight;
                    }
                }
            }
            if (!answer.trim()) throw new Error('AI returned an empty response.');
            setStatus('Generated from the latest available dashboard data.', false);
            return true;
        } catch (err) {
            var message = err && err.message ? err.message : 'The AI assistant is temporarily unavailable. Please try again.';
            responseBox.textContent = answer || message;
            setStatus(message, true);
            return false;
        } finally {
            busy = false;
            sendBtn.disabled = false;
            actionButtons.forEach(function (button) { button.disabled = false; });
            responseBox.setAttribute('aria-busy', 'false');
        }
    }

    actionButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            openPanel();
            streamAI('/api/ai/' + btn.dataset.gaiAction + '/stream', null, btn.dataset.gaiAction === 'forecast');
        });
    });

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        var message = input.value.trim();
        if (!message) return;
        openPanel();
        var ok = await streamAI('/api/ai/chat/stream', { message: message }, false);
        if (ok) input.value = '';
    });
})();
