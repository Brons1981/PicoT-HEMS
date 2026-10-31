(function () {
    'use strict';
    var snapshot = null, busy = false, inFlight = '', queued = null;
    var desired = null, desiredUntil = 0, debounceAt = 0, debounceTimer, displayTimer;
    var commandError = '', connectionError = '';
    var weather = {
        sunny: ['sun', 'Zonnig'], 'clear-night': ['moon', 'Heldere nacht'],
        partlycloudy: ['partlycloudy', 'Half bewolkt'], cloudy: ['cloud', 'Bewolkt'],
        rainy: ['rain', 'Regen'], pouring: ['pouring', 'Stortregen'],
        snowy: ['snow', 'Sneeuw'], 'snowy-rainy': ['sleet', 'Natte sneeuw'],
        hail: ['hail', 'Hagel'], lightning: ['lightning', 'Onweer'],
        'lightning-rainy': ['storm', 'Onweer met regen'], fog: ['fog', 'Mist'],
        windy: ['wind', 'Wind'], 'windy-variant': ['wind-cloud', 'Bewolkt en winderig'],
        exceptional: ['exceptional', 'Uitzonderlijk weer']
    };
    function el(id) { return document.getElementById(id); }
    function text(id, value) { el(id).textContent = value; }
    function number(value) { return typeof value === 'number' && isFinite(value); }
    function now() { return new Date().getTime(); }
    function temp(value) { return number(value) ? value.toFixed(1).replace('.', ',') + '\u00b0' : '\u2014'; }
    function watts(value) {
        return number(value) ? String(Math.round(Math.abs(value))).replace(/\B(?=(\d{3})+(?!\d))/g, '.') : '\u2014';
    }
    function icon(id, name) {
        el(id).setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', '#' + name);
    }
    function usable() {
        return snapshot && !snapshot.stale && snapshot.controllable && !snapshot.error &&
            typeof snapshot.csrf_token === 'string' && snapshot.csrf_token.length > 0 &&
            snapshot.revision !== null && typeof snapshot.revision !== 'undefined';
    }
    function source(value) {
        return value === 'pv' ? 'PV' : value === 'battery' ? 'batterij' :
            value === 'grid' ? 'net' : value === 'mixed' ? 'gemengd' : '';
    }
    function flow(prefix, value, origin, battery) {
        var color = 'muted', arrow = '', detail = '', from = source(origin);
        if (number(value)) {
            if (value === 0) { arrow = '\u2013'; detail = 'Geen stroom'; }
            else if (battery) {
                arrow = value > 0 ? '\u2191' : '\u2193';
                color = value > 0 ? 'green' : origin === 'pv' ? 'yellow' :
                    origin === 'grid' || origin === 'mixed' ? 'red' : 'muted';
                detail = value > 0 ? 'Ontladen' : 'Laden' + (from ? ' \u00b7 ' + from : '');
            } else {
                arrow = value > 0 ? '\u2193' : '\u2191';
                color = value > 0 ? 'red' : origin === 'pv' ? 'yellow' : origin === 'battery' ? 'green' : 'muted';
                detail = value > 0 ? 'Afname' : 'Teruglevering' + (from ? ' \u00b7 ' + from : '');
            }
        }
        text(prefix + 'Value', watts(value));
        el(prefix + 'Value').parentNode.className = 'reading' + (number(value) && Math.abs(value) >= 10000 ? ' long' : '');
        text(prefix + 'Arrow', arrow);
        el(prefix + 'Arrow').className = 'arrow ' + color;
        text(prefix + 'Detail', detail);
    }
    function render() {
        var s = snapshot || {}, fresh = snapshot && !s.stale;
        // Energy freshness is independent of HC; the API nulls unavailable values individually.
        var e = s.energy || {};
        var showing = fresh && number(desired) && now() < desiredUntil;
        var editable = usable() && number(s.target) && queued !== 'resume' && inFlight !== 'resume';
        var base = number(desired) ? desired : s.target;
        var w = fresh && Object.prototype.hasOwnProperty.call(weather, s.weather) ? weather[s.weather] : null;
        var status = commandError || connectionError || s.error ||
            (s.stale ? 'Metingen verouderd' : s.energy && s.energy.stale ? 'Energiemetingen verouderd' :
                queued || (busy && inFlight) ? 'Instelling verzenden\u2026' : !snapshot ? 'Verbinding maken\u2026' :
                    !s.controllable ? 'Bediening niet beschikbaar' : '');
        text('temperature', temp(showing ? desired : fresh ? s.inside : null));
        el('temperature').className = 'temp' + (showing ? ' desired' : '');
        text('tempLabel', showing ? 'Instellen' : 'Binnen');
        text('targetHint', showing ? (queued || inFlight ? 'Gewenst \u00b7 wordt verzonden' : 'Gewenste temperatuur') : '');
        text('outsideValue', temp(fresh ? s.outside : null));
        el('heat').setAttribute('class', 'icon heat' + (fresh && s.heat ? '' : ' hidden'));
        el('modeIcon').className = fresh && (s.manual || s.scheduled) ? '' : 'hidden';
        icon('modeUse', s.manual ? 'hand' : 'clock');
        el('modeIcon').disabled = !usable() || !s.manual || !s.scheduled || !!queued || !!inFlight;
        el('modeIcon').setAttribute('aria-label', s.manual ?
            (s.scheduled ? 'Handmatig. Kamerschema hervatten' : 'Handmatig. Geen kamerschema') : 'Volgens kamerschema');
        el('up').disabled = !editable || base >= 35;
        el('down').disabled = !editable || base <= 5;
        el('weather').setAttribute('class', 'weather-icon' + (w ? '' : ' hidden'));
        el('weather').setAttribute('aria-label', w ? w[1] : '');
        if (w) { icon('weatherUse', w[0]); }
        flow('net', e.grid_w, e.grid_source, false);
        flow('bat', e.battery_w, e.battery_source, true);
        text('pvValue', watts(number(e.pv_w) && e.pv_w >= 0 ? e.pv_w : null));
        text('homeValue', watts(number(e.home_w) && e.home_w >= 0 ? e.home_w : null));
        text('socValue', number(e.soc) && e.soc >= 0 && e.soc <= 100 ? Math.round(e.soc) + '%' : '\u2014');
        el('socFill').style.width = number(e.soc) && e.soc >= 0 && e.soc <= 100 ? e.soc + '%' : '0%';
        text('zendureMode', typeof e.mode === 'string' && e.mode ? e.mode : '\u2014');
        text('status', status);
        el('status').className = 'status' + (commandError || connectionError || s.error ? ' error' : '');
    }
    function clearDesired() {
        desired = null; desiredUntil = 0; queued = null;
        clearTimeout(debounceTimer); clearTimeout(displayTimer);
    }
    // All GETs and POSTs share this single flight, including timeout/abort paths.
    function request(command, payload) {
        var xhr = new XMLHttpRequest(), done = false, watchdog;
        busy = true; inFlight = command;
        function finish(failure) {
            var s, backendError = '', refetch = false;
            if (done) { return; }
            done = true; clearTimeout(watchdog);
            if (failure && xhr.status >= 400) {
                try {
                    s = JSON.parse(xhr.responseText);
                    if (s && typeof s.error === 'string' && s.error) { backendError = s.error; }
                } catch (ignoreErrorBody) { /* Keep the fallback for non-JSON HTTP errors. */ }
            }
            if (!failure) {
                try {
                    s = JSON.parse(xhr.responseText);
                    if (!s || typeof s !== 'object' || typeof s.stale !== 'boolean' ||
                            typeof s.controllable !== 'boolean' || !s.energy || typeof s.energy !== 'object') {
                        failure = 'Ongeldig antwoord';
                    }
                } catch (ignore) { failure = 'Ongeldig antwoord'; }
            }
            if (failure) {
                snapshot = null; clearDesired();
                if (command) {
                    commandError = backendError || (xhr.status === 409 ? 'Instelling gewijzigd elders. Opnieuw ophalen\u2026' :
                        'Instelling niet bevestigd. ' + failure);
                    refetch = true;
                } else { connectionError = backendError || failure; }
            } else {
                snapshot = s; connectionError = '';
                if (s.error || s.stale || !s.controllable) { clearDesired(); }
                if (command && s.error) { commandError = 'Instelling niet bevestigd: ' + s.error; }
                // Never keep an optimistic value that differs from the server's accepted target.
                if (command === 'temperature' && !queued && desired !== s.target) { desired = null; }
                if (!queued && now() >= desiredUntil) { desired = null; }
            }
            busy = false; inFlight = ''; render();
            if (refetch) { request('', null); } else { dispatch(); }
        }
        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) { finish(xhr.status >= 200 && xhr.status < 300 ? '' :
                xhr.status === 401 ? 'Authenticatie vereist' : 'Verbinding niet beschikbaar'); }
        };
        xhr.onerror = function () { finish('Verbinding niet beschikbaar'); };
        xhr.ontimeout = function () { finish('Verbinding verlopen'); };
        try {
            xhr.open(command ? 'POST' : 'GET', command ? 'api/tablet/' + command : 'api/tablet', true);
            xhr.timeout = 8000;
            xhr.setRequestHeader('Accept', 'application/json');
            if (!command) { xhr.setRequestHeader('Cache-Control', 'no-cache'); }
            if (command) {
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.setRequestHeader('X-HC-CSRF', snapshot.csrf_token);
            }
            watchdog = setTimeout(function () {
                if (done) { return; }
                // Detach callbacks before abort; some old WebKit versions fire synchronously.
                xhr.onreadystatechange = xhr.onerror = xhr.ontimeout = null;
                xhr.abort(); finish('Verbinding verlopen');
            }, 8500);
            xhr.send(command ? JSON.stringify(payload) : null);
        } catch (ignoreSend) { finish('Verbinding niet beschikbaar'); }
        render();
    }
    function dispatch() {
        var command, payload;
        if (busy || !queued) { return; }
        if (!usable()) { clearDesired(); render(); return; }
        if (queued === 'resume' && (!snapshot.manual || !snapshot.scheduled)) {
            clearDesired(); render(); return;
        }
        if (queued === 'temperature' && now() < debounceAt) { return; }
        command = queued; queued = null;
        payload = command === 'temperature' ? { revision: snapshot.revision, temperature: desired } : {};
        request(command, payload);
    }
    function change(delta) {
        var base;
        if (!usable() || !number(snapshot.target) || queued === 'resume' || inFlight === 'resume') { return; }
        base = number(desired) ? desired : snapshot.target;
        desired = Math.max(5, Math.min(35, Math.round((base + delta) * 2) / 2));
        desiredUntil = now() + 5000; debounceAt = now() + 300;
        queued = 'temperature'; commandError = '';
        clearTimeout(debounceTimer); debounceTimer = setTimeout(dispatch, 300);
        clearTimeout(displayTimer); displayTimer = setTimeout(function () {
            // Keep an unsent value internally, but never display it beyond five seconds.
            if (!queued && !inFlight) { desired = null; }
            render();
        }, 5000);
        render();
    }
    el('up').onclick = function () { change(0.5); };
    el('down').onclick = function () { change(-0.5); };
    el('modeIcon').onclick = function () {
        if (!usable() || !snapshot.manual || !snapshot.scheduled || inFlight || queued) { return; }
        clearDesired(); commandError = ''; queued = 'resume'; dispatch();
    };
    render(); request('', null);
    setInterval(function () { if (!busy && !queued) { request('', null); } }, 5000);
}());
