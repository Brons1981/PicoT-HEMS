const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../picot_hc/picot_hc/web');
const code = fs.readFileSync(path.join(web, 'tablet.js'), 'utf8');
const html = fs.readFileSync(path.join(web, 'tablet.html'), 'utf8');
function setup() {
    let time = 0, nextId = 1;
    const timers = new Map(), requests = [], elements = {};
    for (const match of html.matchAll(/id="([^"]+)"/g)) {
        elements[match[1]] = { textContent: '', className: '', style: {}, attributes: {}, parentNode: {},
            setAttribute(k,v) { this.attributes[k] = v; }, setAttributeNS(ns,k,v) { this.attributes[k] = v; } };
    }
    function timer(fn, delay, interval) { const id = nextId++; timers.set(id, { fn, at: time + delay, interval }); return id; }
    class XHR {
        constructor() { this.headers = {}; requests.push(this); }
        open(method, url) { this.method = method; this.url = url; }
        setRequestHeader(k,v) { this.headers[k] = v; }
        send(body) { this.body = body && JSON.parse(body); this.sent = true; }
        abort() { this.aborted = true; }
        respond(data, status = 200) { this.status = status; this.responseText = JSON.stringify(data); this.readyState = 4; if (this.onreadystatechange) this.onreadystatechange(); }
    }
    class Clock extends Date { constructor() { super(time); } }
    vm.runInNewContext(code, { document: { getElementById: id => { assert.ok(elements[id], id); return elements[id]; } },
        XMLHttpRequest: XHR, Date: Clock, setTimeout: (f,d) => timer(f,d,0), setInterval: (f,d) => timer(f,d,d),
        clearTimeout: id => timers.delete(id) });
    return { e: elements, requests, last: () => requests[requests.length - 1],
        tick(delta) { const end = time + delta; for (;;) {
            const due = [...timers.entries()].filter(([,t]) => t.at <= end).sort((a,b) => a[1].at-b[1].at || a[0]-b[0])[0];
            if (!due) break; const [id,t] = due; time = t.at;
            if (t.interval) t.at += t.interval; else timers.delete(id); t.fn();
        } time = end; }, click(id) { if (!elements[id].disabled) elements[id].onclick(); } };
}
function snapshot(extra = {}) {
    return Object.assign({ csrf_token: 'memory-only-token', revision: 1, inside: 19.4, outside: 8.4, target: 20,
        manual: false, scheduled: true, heat: true, weather: 'partlycloudy', stale: false, controllable: true,
        energy: { grid_w: -1000, pv_w: 3000, battery_w: -1200, home_w: 800, soc: 64, mode: 'NOM',
            grid_source: 'pv', battery_source: 'pv', stale: false }, error: null }, extra);
}
function ready(extra) { const h = setup(); h.last().respond(snapshot(extra)); return h; }
let count = 0;
function test(name, fn) { fn(); count++; console.log('ok - ' + name); }
test('energy remains independent of HC staleness and missing individual measurements', () => {
    for (const stale of [false, true]) {
        const s = snapshot({stale}); s.energy.pv_w = null; s.energy.stale = true;
        const h = ready(s);
        assert.equal(h.e.pvValue.textContent, '\u2014');
        assert.equal(h.e.netValue.textContent, '1.000');
        assert.equal(h.e.batValue.textContent, '1.200');
        assert.equal(h.e.homeValue.textContent, '800');
        assert.equal(h.e.socValue.textContent, '64%');
        assert.equal(h.e.socFill.style.width, '64%');
        assert.equal(h.e.zendureMode.textContent, 'NOM');
        assert.match(h.e.status.textContent, /verouderd/);
        if (stale) assert.equal(h.e.temperature.textContent, '\u2014');
        h.tick(5000); s.energy.grid_w = null; s.energy.battery_w = null; h.last().respond(s);
        assert.equal(h.e.netValue.textContent, '\u2014'); assert.equal(h.e.netArrow.textContent, '');
        assert.equal(h.e.batValue.textContent, '\u2014'); assert.equal(h.e.batArrow.textContent, '');
        assert.equal(h.e.socValue.textContent, '64%');
    }
});
test('fixed manual thermostat cannot resume; queued resume rechecks schedule', () => {
    const h = ready({manual:true, scheduled:false});
    assert.equal(h.e.modeIcon.disabled, true);
    assert.equal(h.e.modeUse.attributes['xlink:href'], '#hand');
    assert.ok(!h.e.modeIcon.attributes['aria-label'].includes('hervatten'));
    h.e.modeIcon.onclick(); assert.equal(h.requests.length, 1);
    assert.equal(h.e.up.disabled, false);
    const queued = ready({manual:true}); queued.tick(5000); queued.click('modeIcon');
    queued.last().respond(snapshot({manual:true,scheduled:false}));
    assert.equal(queued.requests.length, 2); assert.equal(queued.e.modeIcon.disabled, true);
});
test('HTTP JSON errors display exact backend reasons including 400 revision conflicts', () => {
    for (const status of [400, 403, 409, 500]) {
        const reason = 'Revision conflict: reload current state (' + status + ').';
        const h = ready(); h.click('up'); h.tick(300); h.click('up');
        h.last().respond({error:reason}, status);
        assert.equal(h.e.status.textContent, reason);
        assert.equal(h.e.temperature.textContent, '\u2014');
        assert.equal(h.last().method, 'GET');
        h.last().respond(snapshot({revision:9}));
        assert.equal(h.e.status.textContent, reason);
        h.tick(300); assert.equal(h.requests.length, 3);
    }
    const h = setup(); h.last().respond({error:'HC niet bereikbaar'}, 503);
    assert.equal(h.e.status.textContent, 'HC niet bereikbaar');
});
test('external CSP assets and empty initial measurements', () => {
    assert.ok(!/<script(?![^>]*src=)|<style|\sstyle=|\sonclick=/i.test(html));
    assert.ok(!/voorbeeld|demo|19,4|3\.000/i.test(html));
    const h = setup(); assert.equal(h.e.temperature.textContent, '—'); assert.equal(h.e.up.disabled, true);
    assert.equal(h.last().url, 'api/tablet');
});
test('measurements, schedule/hand/flame and actual weather', () => {
    const h = ready(); assert.equal(h.e.temperature.textContent, '19,4°'); assert.equal(h.e.outsideValue.textContent, '8,4°');
    assert.equal(h.e.modeUse.attributes['xlink:href'], '#clock'); assert.equal(h.e.netValue.textContent, '1.000');
    assert.equal(h.e.socValue.textContent, '64%'); assert.equal(h.e.weatherUse.attributes['xlink:href'], '#partlycloudy');
    h.tick(5000); h.last().respond(snapshot({manual:true, heat:false, weather:'unknown'}));
    assert.equal(h.e.modeUse.attributes['xlink:href'], '#hand'); assert.match(h.e.heat.attributes.class, /hidden/);
    assert.match(h.e.weather.attributes.class, /hidden/);
    h.tick(5000); h.last().respond(snapshot({manual:false, scheduled:false})); assert.equal(h.e.modeIcon.className, 'hidden');
});
test('debounces taps, uses latest revision and CSRF, shows desired only five seconds after last tap', () => {
    const h = ready(); h.click('up'); h.tick(200); h.click('up'); h.tick(299); assert.equal(h.requests.length, 1);
    h.tick(1); assert.deepEqual(h.last().body, {revision:1,temperature:21});
    assert.equal(h.last().headers['X-HC-CSRF'], 'memory-only-token');
    h.last().respond(snapshot({target:21,manual:true,revision:2}));
    h.tick(4699); assert.equal(h.e.temperature.textContent, '21,0°'); h.tick(1); assert.equal(h.e.temperature.textContent, '19,4°');
});
test('serializes poll and commands and coalesces taps during POST', () => {
    const h = ready(); h.tick(5000); h.click('up'); h.tick(300); assert.equal(h.requests.length, 2);
    h.last().respond(snapshot({revision:4})); assert.deepEqual(h.last().body, {revision:4,temperature:20.5});
    h.click('up'); h.click('up'); h.tick(1000); assert.equal(h.requests.length, 3);
    h.last().respond(snapshot({target:20.5,revision:5,manual:true}));
    assert.deepEqual(h.last().body, {revision:5,temperature:21.5});
    h.last().respond(snapshot({target:21.5,revision:6,manual:true})); assert.equal(h.e.temperature.textContent,'21,5°');
});
test('conflicts clear pending targets, refetch and retain visible conflict message', () => {
    const h = ready(); h.click('up'); h.tick(300); h.click('up'); h.last().respond({},409);
    assert.equal(h.e.temperature.textContent,'—'); assert.equal(h.last().method,'GET');
    h.last().respond(snapshot({target:18,revision:9})); assert.equal(h.e.temperature.textContent,'19,4°');
    assert.match(h.e.status.textContent,/gewijzigd elders/); h.tick(300); assert.equal(h.requests.length,3);
});
test('network failures clear all measurements; polling recovers', () => {
    const h = ready(); h.tick(5000); h.last().respond({},503);
    for (const id of ['temperature','outsideValue','netValue','pvValue','batValue','homeValue','socValue','zendureMode']) assert.equal(h.e[id].textContent,'—',id);
    assert.equal(h.e.up.disabled,true); h.tick(5000); h.last().respond(snapshot()); assert.equal(h.e.temperature.textContent,'19,4°');
});
test('timeout watchdog aborts and polling never overlaps', () => {
    const h = setup(); h.tick(5000); assert.equal(h.requests.length,1); h.tick(3500); assert.equal(h.requests[0].aborted,true);
    assert.match(h.e.status.textContent,/verlopen/); h.tick(1500); assert.equal(h.requests.length,2);
});
test('failed commands and server errors never show a successful target', () => {
    const h = ready(); h.click('up'); h.tick(300); h.last().respond({},500);
    assert.equal(h.e.temperature.textContent,'—'); h.last().respond(snapshot()); assert.equal(h.e.temperature.textContent,'19,4°');
    assert.match(h.e.status.textContent,/niet bevestigd/);
    h.click('up'); h.tick(300); h.last().respond(snapshot({error:'Niet beschikbaar'}));
    assert.equal(h.e.temperature.textContent,'19,4°'); assert.match(h.e.status.textContent,/Niet beschikbaar/);
});
test('temperature bounds and resume endpoint are exact', () => {
    const h = ready({target:34.5}); h.click('up'); assert.equal(h.e.up.disabled,true); h.tick(300);
    assert.equal(h.last().body.temperature,35); h.last().respond(snapshot({target:35,manual:true}));
    h.click('modeIcon'); assert.equal(h.last().url,'api/tablet/resume'); assert.deepEqual(h.last().body,{});
    h.last().respond(snapshot({target:5.5,manual:false})); h.click('down'); assert.equal(h.e.down.disabled,true);
    h.tick(300); assert.equal(h.last().body.temperature,5);
});
test('stale and missing data do not become zero readings', () => {
    const h = ready({inside:null,outside:null,target:null,energy:{stale:true}});
    assert.equal(h.e.temperature.textContent,'—'); assert.equal(h.e.netValue.textContent,'—'); assert.equal(h.e.up.disabled,true);
    h.tick(5000); h.last().respond(snapshot({stale:true})); assert.equal(h.e.temperature.textContent,'—'); assert.equal(h.e.socValue.textContent,'64%');
});
test('all source directions and colors', () => {
    for (const [grid,gs,battery,bs,gc,ga,bc,ba] of [
        [100,'pv',100,'grid','red','↓','green','↑'],[-100,'pv',-100,'pv','yellow','↑','yellow','↓'],
        [-100,'battery',-100,'grid','green','↑','red','↓'],[-100,'mixed',-100,'mixed','muted','↑','red','↓'],
        [-100,null,-100,null,'muted','↑','muted','↓'],[0,null,0,null,'muted','–','muted','–']]) {
        const s = snapshot(); Object.assign(s.energy,{grid_w:grid,grid_source:gs,battery_w:battery,battery_source:bs});
        const h = ready(s); assert.equal(h.e.netArrow.className,'arrow '+gc); assert.equal(h.e.netArrow.textContent,ga);
        assert.equal(h.e.batArrow.className,'arrow '+bc); assert.equal(h.e.batArrow.textContent,ba);
    }
});
test('weather symbols vary and unknown conditions stay hidden', () => {
    const symbols = new Set();
    for (const condition of ['sunny','clear-night','partlycloudy','cloudy','rainy','pouring','snowy','snowy-rainy','hail','lightning','lightning-rainy','fog','windy','windy-variant','exceptional']) {
        const h = ready({weather:condition}); const ref=h.e.weatherUse.attributes['xlink:href'];
        assert.ok(html.includes('id="'+ref.slice(1)+'"')); symbols.add(ref); assert.ok(!h.e.weather.attributes.class.includes('hidden'));
    } assert.equal(symbols.size,15);
});
test('late POST completion expires internal desired target before a later poll changes target', () => {
    const h = ready(); h.click('up'); h.tick(300); h.tick(5000);
    assert.equal(h.e.temperature.textContent,'19,4°');
    h.last().respond(snapshot({target:20.5,revision:2}));
    h.tick(4700); h.last().respond(snapshot({target:18,revision:3}));
    h.click('up'); h.tick(300); assert.equal(h.last().body.temperature,18.5);
});
test('resume queues behind poll with fresh CSRF and no extra POST', () => {
    const h = ready({manual:true}); h.tick(5000); h.click('modeIcon');
    assert.equal(h.requests.length,2); h.last().respond(snapshot({manual:true,csrf_token:'new-token'}));
    assert.equal(h.last().url,'api/tablet/resume'); assert.equal(h.last().headers['X-HC-CSRF'],'new-token');
    h.last().respond(snapshot()); assert.equal(h.requests.length,3);
});
console.log(count + ' tablet UI behavior tests passed');
