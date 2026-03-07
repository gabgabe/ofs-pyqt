/*
 * web_ui.h — Embedded web control panel
 *
 * Professional single-page dashboard served on port 80:
 *   - OFS connection settings (host/port, auto-save)
 *   - mDNS auto-discovery of OFS instances on LAN
 *   - GPIO pin assignment editor per output channel
 *   - Live axis monitor with bar graphs
 *   - System status (WiFi, WS, uptime, free heap)
 *   - Reboot / Factory Reset buttons
 *   - WiFi reconfigure (re-enter captive portal)
 *
 * All settings changes take effect via /api/config POST and auto-reconnect WS.
 */
#pragma once

#include <Arduino.h>

#ifdef TARGET_ESP8266
  #include <ESP8266WebServer.h>
  #include <ESP8266mDNS.h>
  using WebServer_t = ESP8266WebServer;
#endif
#ifdef TARGET_ESP32
  #include <WebServer.h>
  #include <ESPmDNS.h>
  using WebServer_t = WebServer;
#endif

#include <ArduinoJson.h>
#include "config.h"

// ── Forward declarations (implemented in main.cpp) ───────────────
// web_ui.h is #included from main.cpp after all globals are defined,
// so we just need the function forward declarations.
void saveConfig();
void loadConfig();
void emergencyStop();

// ── HTML / CSS / JS (compressed in PROGMEM) ──────────────────────

static const char PAGE_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OFS Bridge</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#1a1a2e;--card:#16213e;--accent:#0f3460;--hi:#e94560;
      --txt:#eee;--dim:#888;--ok:#4ecca3;--warn:#f39c12;--err:#e74c3c;
      --input-bg:#0a0e1a;--radius:8px}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
     background:var(--bg);color:var(--txt);min-height:100vh;padding:12px}
h1{font-size:1.3em;color:var(--hi);margin-bottom:4px}
h2{font-size:.95em;color:var(--dim);font-weight:400;margin-bottom:12px}
.top-bar{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.top-bar .dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.top-bar .info{font-size:.8em;color:var(--dim)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.card{background:var(--card);border-radius:var(--radius);padding:16px;
      border:1px solid rgba(255,255,255,.05)}
.card h3{font-size:.85em;text-transform:uppercase;letter-spacing:.05em;
         color:var(--hi);margin-bottom:10px;display:flex;align-items:center;gap:6px}
.card h3 .icon{font-size:1.1em}
label{display:block;font-size:.78em;color:var(--dim);margin:6px 0 2px}
input,select{width:100%;padding:7px 10px;background:var(--input-bg);
       border:1px solid rgba(255,255,255,.1);border-radius:4px;color:var(--txt);
       font-size:.85em;outline:none}
input:focus,select:focus{border-color:var(--hi)}
.row{display:flex;gap:8px;align-items:end}
.row>*{flex:1}
.btn{padding:8px 16px;border:none;border-radius:4px;cursor:pointer;
     font-size:.8em;font-weight:600;transition:opacity .2s}
.btn:hover{opacity:.85}
.btn-pri{background:var(--hi);color:#fff}
.btn-sec{background:var(--accent);color:#ccc}
.btn-warn{background:var(--warn);color:#111}
.btn-err{background:var(--err);color:#fff}
.btn-ok{background:var(--ok);color:#111}
.btn-sm{padding:5px 10px;font-size:.75em}
.btns{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.axis-bar{margin:4px 0}
.axis-bar .name{font-size:.72em;color:var(--dim);display:flex;justify-content:space-between}
.axis-bar .track{height:6px;background:var(--input-bg);border-radius:3px;overflow:hidden}
.axis-bar .fill{height:100%;border-radius:3px;background:var(--ok);transition:width .1s}
.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;font-size:.82em}
.status-grid .k{color:var(--dim)}
.status-grid .v{text-align:right;font-family:monospace}
.scan-list{max-height:120px;overflow-y:auto;margin-top:6px}
.scan-item{display:flex;justify-content:space-between;align-items:center;
           padding:4px 8px;background:var(--input-bg);border-radius:4px;
           margin:3px 0;font-size:.82em;cursor:pointer}
.scan-item:hover{border:1px solid var(--hi)}
.scan-item .ip{font-family:monospace;color:var(--ok)}
.gpio-row{display:grid;grid-template-columns:auto 1fr auto;gap:6px;
          align-items:center;margin:4px 0;font-size:.82em}
.gpio-row .ch{color:var(--dim);min-width:55px}
.gpio-row select{padding:4px 6px;font-size:.82em}
.gpio-row .type{font-size:.7em;color:var(--dim);text-align:right}
.toast{position:fixed;bottom:20px;right:20px;background:#333;color:#fff;
       padding:10px 18px;border-radius:6px;font-size:.82em;opacity:0;
       transition:opacity .3s;z-index:999;pointer-events:none}
.toast.show{opacity:1}
.hidden{display:none}
</style>
</head>
<body>

<div class="top-bar">
  <div>
    <h1>⚡ OFS Bridge</h1>
    <h2>ESP WiFi → Actuator Bridge</h2>
  </div>
  <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
    <div class="dot" id="dot-ws"></div>
    <span class="info" id="lbl-ws">--</span>
  </div>
</div>

<div class="cards">

  <!-- OFS Connection -->
  <div class="card">
    <h3><span class="icon">🔌</span> OFS Connection</h3>
    <div class="row">
      <div style="flex:2"><label>Host IP</label>
        <input id="ws_host" placeholder="192.168.1.100"></div>
      <div><label>Port</label>
        <input id="ws_port" type="number" placeholder="8082"></div>
    </div>
    <label style="margin-top:8px">Format</label>
    <select id="ws_format">
      <option value="json">JSON</option>
      <option value="tcode">TCode</option>
      <option value="tcode_mfp">TCode MFP</option>
    </select>
    <div class="btns">
      <button class="btn btn-pri" onclick="saveOfs()">💾 Save & Reconnect</button>
      <button class="btn btn-sec btn-sm" onclick="scanOfs()">🔍 Scan LAN</button>
    </div>
    <div id="scan-results" class="scan-list hidden"></div>
  </div>

  <!-- GPIO Mapping -->
  <div class="card">
    <h3><span class="icon">🔧</span> GPIO Pin Mapping</h3>
    <div id="gpio-map"></div>
    <div class="btns">
      <button class="btn btn-pri btn-sm" onclick="saveGpio()">💾 Save GPIO</button>
      <button class="btn btn-sec btn-sm" onclick="loadGpio()">↩ Reset</button>
    </div>
  </div>

  <!-- Output Enables -->
  <div class="card">
    <h3><span class="icon">⚙️</span> Output Channels</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
      <label><input type="checkbox" id="en_servo"> Servos</label>
      <label><input type="checkbox" id="en_mosfet"> MOSFET PWM</label>
      <label><input type="checkbox" id="en_relay"> Relay</label>
    </div>
    <label>Actuator Rate (Hz)</label>
    <input id="act_hz" type="number" min="10" max="200" value="100">
    <label>Deadman Timeout (ms)</label>
    <input id="deadman_ms" type="number" min="500" max="10000" value="2000">
    <div class="btns">
      <button class="btn btn-pri btn-sm" onclick="saveOutputs()">💾 Save</button>
    </div>
  </div>

  <!-- Live Axes -->
  <div class="card">
    <h3><span class="icon">📊</span> Live Axes</h3>
    <div id="axes-live"></div>
  </div>

  <!-- System Status -->
  <div class="card">
    <h3><span class="icon">📡</span> System Status</h3>
    <div class="status-grid" id="status-grid">
      <span class="k">WiFi</span><span class="v" id="s-wifi">--</span>
      <span class="k">IP</span><span class="v" id="s-ip">--</span>
      <span class="k">RSSI</span><span class="v" id="s-rssi">--</span>
      <span class="k">WebSocket</span><span class="v" id="s-ws">--</span>
      <span class="k">Uptime</span><span class="v" id="s-up">--</span>
      <span class="k">Free Heap</span><span class="v" id="s-heap">--</span>
      <span class="k">Safety</span><span class="v" id="s-safety">--</span>
      <span class="k">Firmware</span><span class="v" id="s-fw">--</span>
    </div>
  </div>

  <!-- Danger Zone -->
  <div class="card">
    <h3><span class="icon">🛑</span> System</h3>
    <div class="btns">
      <button class="btn btn-err" onclick="doStop()">🛑 Emergency Stop</button>
      <button class="btn btn-warn" onclick="doReboot()">🔄 Reboot</button>
      <button class="btn btn-sec" onclick="doWifiReset()">📶 Re-configure WiFi</button>
      <button class="btn btn-err btn-sm" onclick="doFactoryReset()">🗑 Factory Reset</button>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

/* ── Toast ─────────────────────────────────── */
let toastTimer;
function toast(msg, ms=2000) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), ms);
}

/* ── API helpers ───────────────────────────── */
async function api(path, body) {
  try {
    const opts = body !== undefined
      ? { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }
      : { method:'GET' };
    const r = await fetch('/api/' + path, opts);
    return await r.json();
  } catch(e) { toast('⚠ Request failed'); return null; }
}

/* ── Load config into UI ──────────────────── */
async function loadAll() {
  const d = await api('config');
  if (!d) return;
  $('#ws_host').value = d.ws_host || '';
  $('#ws_port').value = d.ws_port || 8082;
  $('#ws_format').value = d.ws_format || 'json';
  $('#en_servo').checked = d.enable_servos !== false;
  $('#en_mosfet').checked = d.enable_mosfet !== false;
  $('#en_relay').checked = d.enable_relay !== false;
  $('#act_hz').value = d.actuator_hz || 100;
  $('#deadman_ms').value = d.deadman_ms || 2000;
  buildGpioMap(d.gpio || {});
}

/* ── Save OFS connection ──────────────────── */
async function saveOfs() {
  const r = await api('config', {
    ws_host: $('#ws_host').value.trim(),
    ws_port: parseInt($('#ws_port').value) || 8082,
    ws_format: $('#ws_format').value
  });
  if (r && r.ok) toast('✅ Saved — reconnecting...');
}

/* ── Save output enables ──────────────────── */
async function saveOutputs() {
  const r = await api('config', {
    enable_servos: $('#en_servo').checked,
    enable_mosfet: $('#en_mosfet').checked,
    enable_relay: $('#en_relay').checked,
    actuator_hz: parseInt($('#act_hz').value) || 100,
    deadman_ms: parseInt($('#deadman_ms').value) || 2000
  });
  if (r && r.ok) toast('✅ Output settings saved');
}

/* ── GPIO mapping ─────────────────────────── */
const CHANNELS = [
  { key:'servo_1',  label:'Servo 1',  type:'PWM',     default_8266:12, default_32:25 },
  { key:'servo_2',  label:'Servo 2',  type:'PWM',     default_8266:14, default_32:27 },
  { key:'pwm_1',    label:'MOSFET 1', type:'PWM',     default_8266:13, default_32:26 },
  { key:'relay_1',  label:'Relay 1',  type:'Digital',  default_8266:5,  default_32:32 },
  { key:'status_led', label:'Status LED', type:'LED', default_8266:2,  default_32:2  }
];

// ESP8266 safe GPIOs for user assignment
// Excluded: 0 (boot), 1 (TX), 2 (boot/LED only), 3 (RX), 15 (boot)
const GPIO_8266 = [4,5,12,13,14,16];
const GPIO_32   = [2,4,5,12,13,14,15,16,17,18,19,21,22,23,25,26,27,32,33];

function buildGpioMap(saved) {
  const el = $('#gpio-map');
  el.innerHTML = '';
  CHANNELS.forEach(ch => {
    const pin = saved[ch.key] !== undefined ? saved[ch.key] : ch.default_8266;
    const row = document.createElement('div');
    row.className = 'gpio-row';
    row.innerHTML = `
      <span class="ch">${ch.label}</span>
      <select data-key="${ch.key}">
        ${GPIO_8266.map(g => `<option value="${g}" ${g===pin?'selected':''}>${g} (D${gpioToD(g)})</option>`).join('')}
      </select>
      <span class="type">${ch.type}</span>`;
    el.appendChild(row);
  });
}

function gpioToD(g) {
  const m = {0:'3',1:'10',2:'4',3:'9',4:'2',5:'1',12:'6',13:'7',14:'5',15:'8',16:'0'};
  return m[g] || '?';
}

async function saveGpio() {
  const gpio = {};
  $$('#gpio-map select').forEach(sel => { gpio[sel.dataset.key] = parseInt(sel.value); });
  const r = await api('config', { gpio });
  if (r && r.ok) toast('✅ GPIO saved — reboot to apply');
}

function loadGpio() { loadAll(); toast('↩ Reset to saved'); }

/* ── OFS LAN Scan (mDNS + port probe) ─────── */
async function scanOfs() {
  const el = $('#scan-results');
  el.classList.remove('hidden');
  el.innerHTML = '<span style="font-size:.8em;color:var(--dim)">Scanning...</span>';
  const r = await api('scan');
  if (!r || !r.hosts || r.hosts.length === 0) {
    el.innerHTML = '<span style="font-size:.8em;color:var(--dim)">No OFS instances found. Enter IP manually.</span>';
    return;
  }
  el.innerHTML = '';
  r.hosts.forEach(h => {
    const item = document.createElement('div');
    item.className = 'scan-item';
    item.innerHTML = `<span>${h.name || 'OFS'}</span><span class="ip">${h.ip}:${h.port}</span>`;
    item.onclick = () => {
      $('#ws_host').value = h.ip;
      $('#ws_port').value = h.port;
      el.classList.add('hidden');
      toast('Selected ' + h.ip);
    };
    el.appendChild(item);
  });
}

/* ── Live axis polling ────────────────────── */
const AXIS_NAMES = ['servo_1','servo_2','pwm_1','pwm_2','relay_1','relay_2'];
const AXIS_COLORS = ['#e94560','#f39c12','#4ecca3','#3498db','#9b59b6','#1abc9c'];

function buildAxes() {
  const el = $('#axes-live');
  el.innerHTML = '';
  AXIS_NAMES.forEach((name, i) => {
    el.innerHTML += `<div class="axis-bar">
      <div class="name"><span>${name}</span><span id="av-${i}">0.0</span></div>
      <div class="track"><div class="fill" id="af-${i}" style="width:0%;background:${AXIS_COLORS[i]}"></div></div>
    </div>`;
  });
}

async function pollStatus() {
  const d = await api('status');
  if (!d) return;

  // WS indicator
  const dot = $('#dot-ws');
  const lbl = $('#lbl-ws');
  if (d.ws_connected) {
    dot.style.background = 'var(--ok)';
    lbl.textContent = 'Connected to ' + (d.ws_host || '?');
  } else {
    dot.style.background = 'var(--err)';
    lbl.textContent = 'Disconnected';
  }

  // Status grid
  $('#s-wifi').textContent = d.wifi_connected ? '✅ Connected' : '❌ Down';
  $('#s-ip').textContent = d.ip || '--';
  $('#s-rssi').textContent = (d.rssi || '--') + ' dBm';
  $('#s-ws').textContent = d.ws_connected ? '✅ ' + d.ws_host + ':' + d.ws_port : '❌ Disconnected';
  $('#s-up').textContent = fmtUptime(d.uptime_s || 0);
  $('#s-heap').textContent = (d.free_heap || 0).toLocaleString() + ' B';
  $('#s-safety').textContent = d.safety_stopped ? '🛑 STOPPED' : '✅ LIVE';
  $('#s-safety').style.color = d.safety_stopped ? 'var(--err)' : 'var(--ok)';
  $('#s-fw').textContent = d.firmware || '--';

  // Live axes
  if (d.axes) {
    d.axes.forEach((v, i) => {
      const pct = Math.max(0, Math.min(100, v));
      const fill = document.getElementById('af-' + i);
      const val  = document.getElementById('av-' + i);
      if (fill) fill.style.width = pct + '%';
      if (val)  val.textContent = v.toFixed(1);
    });
  }
}

function fmtUptime(s) {
  const d = Math.floor(s/86400), h = Math.floor(s%86400/3600),
        m = Math.floor(s%3600/60), sec = Math.floor(s%60);
  if (d > 0) return d + 'd ' + h + 'h';
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm ' + sec + 's';
}

/* ── Actions ──────────────────────────────── */
async function doStop()  { await api('stop');  toast('🛑 Emergency stop sent'); }
async function doReboot(){ if(confirm('Reboot ESP?')){ await api('reboot'); toast('🔄 Rebooting...'); }}
async function doWifiReset(){ if(confirm('Reset WiFi? Device will create AP for reconfiguration.')){
  await api('wifi_reset'); toast('📶 Rebooting into AP mode...'); }}
async function doFactoryReset(){ if(confirm('⚠ Delete ALL settings and reboot?')){
  await api('factory_reset'); toast('🗑 Factory reset...'); }}

/* ── Init ─────────────────────────────────── */
buildAxes();
loadAll();
setInterval(pollStatus, 500);
pollStatus();
</script>
</body>
</html>
)rawliteral";


// ══════════════════════════════════════════════════════════════════
// WebUI class — HTTP server + REST API + mDNS
// ══════════════════════════════════════════════════════════════════

class WebUI {
public:
    void begin() {
        _server.on("/",         HTTP_GET,  [this]() { handleRoot(); });
        _server.on("/api/config",  HTTP_GET,  [this]() { handleGetConfig(); });
        _server.on("/api/config",  HTTP_POST, [this]() { handleSetConfig(); });
        _server.on("/api/status",  HTTP_GET,  [this]() { handleStatus(); });
        _server.on("/api/scan",    HTTP_GET,  [this]() { handleScan(); });
        _server.on("/api/stop",    HTTP_POST, [this]() { handleStop(); });
        _server.on("/api/reboot",  HTTP_POST, [this]() { handleReboot(); });
        _server.on("/api/wifi_reset",    HTTP_POST, [this]() { handleWifiReset(); });
        _server.on("/api/factory_reset", HTTP_POST, [this]() { handleFactoryReset(); });
        _server.onNotFound([this]() {
            _server.send(404, "application/json", "{\"error\":\"not found\"}");
        });
        _server.begin(WEB_UI_PORT);

        // Start mDNS responder
        if (MDNS.begin(MDNS_HOSTNAME)) {
            MDNS.addService("http", "tcp", WEB_UI_PORT);
            Serial.printf("[WEB] mDNS: http://%s.local:%d/\n",
                          MDNS_HOSTNAME, WEB_UI_PORT);
        }

        Serial.printf("[WEB] Control panel on http://%s:%d/\n",
                       WiFi.localIP().toString().c_str(), WEB_UI_PORT);
    }

    void loop() {
        _server.handleClient();
#ifdef TARGET_ESP8266
        MDNS.update();
#endif
    }

    // Called by main.cpp to provide current axis values for status API
    void setAxes(float* values, int count) {
        for (int i = 0; i < count && i < MAX_AXES; i++) {
            _axisValues[i] = values[i];
        }
    }

    // Callback: main.cpp sets this so we can trigger WS reconnect after config change
    using ReconnectCb = void (*)();
    void onReconnect(ReconnectCb cb) { _reconnectCb = cb; }

private:
    WebServer_t _server{WEB_UI_PORT};
    float       _axisValues[MAX_AXES] = {};
    ReconnectCb _reconnectCb = nullptr;

    // ── Page ─────────────────────────────────────────────────────

    void handleRoot() {
        _server.send_P(200, "text/html", PAGE_HTML);
    }

    // ── GET /api/config ──────────────────────────────────────────

    void handleGetConfig() {
        JsonDocument doc;
        doc["ws_host"]        = cfg.wsHost;
        doc["ws_port"]        = cfg.wsPort;
        doc["ws_format"]      = cfg.wsFormat;
        doc["enable_servos"]  = cfg.enableServos;
        doc["enable_mosfet"]  = cfg.enableMosfet;
        doc["enable_relay"]   = cfg.enableRelay;
        doc["actuator_hz"]    = cfg.actuatorHz;
        doc["deadman_ms"]     = cfg.deadmanMs;

        JsonObject gpio = doc["gpio"].to<JsonObject>();
        gpio["servo_1"]    = cfg.pinServo1;
        gpio["servo_2"]    = cfg.pinServo2;
        gpio["pwm_1"]      = cfg.pinMosfet1;
        gpio["relay_1"]    = cfg.pinRelay1;
        gpio["status_led"] = cfg.pinStatusLed;

        String out;
        serializeJson(doc, out);
        _server.send(200, "application/json", out);
    }

    // ── POST /api/config ─────────────────────────────────────────

    void handleSetConfig() {
        if (!_server.hasArg("plain")) {
            _server.send(400, "application/json", "{\"error\":\"no body\"}");
            return;
        }

        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, _server.arg("plain"));
        if (err) {
            _server.send(400, "application/json", "{\"error\":\"bad json\"}");
            return;
        }

        bool needReconnect = false;

        // OFS connection
        if (doc["ws_host"].is<const char*>()) {
            strlcpy(cfg.wsHost, doc["ws_host"] | "", sizeof(cfg.wsHost));
            needReconnect = true;
        }
        if (doc["ws_port"].is<int>()) {
            cfg.wsPort = doc["ws_port"] | 8082;
            needReconnect = true;
        }
        if (doc["ws_format"].is<const char*>()) {
            strlcpy(cfg.wsFormat, doc["ws_format"] | "json", sizeof(cfg.wsFormat));
        }

        // Output enables
        if (doc["enable_servos"].is<bool>())  cfg.enableServos  = doc["enable_servos"];
        if (doc["enable_mosfet"].is<bool>())  cfg.enableMosfet  = doc["enable_mosfet"];
        if (doc["enable_relay"].is<bool>())   cfg.enableRelay   = doc["enable_relay"];
        if (doc["actuator_hz"].is<int>())     cfg.actuatorHz    = constrain((int)doc["actuator_hz"], 10, 200);
        if (doc["deadman_ms"].is<int>())      cfg.deadmanMs     = constrain((int)doc["deadman_ms"], 500, 10000);

        // GPIO mapping
        if (doc["gpio"].is<JsonObject>()) {
            JsonObject gpio = doc["gpio"];
            if (gpio["servo_1"].is<int>())    cfg.pinServo1    = gpio["servo_1"];
            if (gpio["servo_2"].is<int>())    cfg.pinServo2    = gpio["servo_2"];
            if (gpio["pwm_1"].is<int>())      cfg.pinMosfet1   = gpio["pwm_1"];
            if (gpio["relay_1"].is<int>())    cfg.pinRelay1    = gpio["relay_1"];
            if (gpio["status_led"].is<int>()) cfg.pinStatusLed = gpio["status_led"];
        }

        saveConfig();

        if (needReconnect && _reconnectCb) {
            _reconnectCb();
        }

        _server.send(200, "application/json", "{\"ok\":true}");
    }

    // ── GET /api/status ──────────────────────────────────────────

    void handleStatus() {
        JsonDocument doc;
        doc["wifi_connected"] = WiFi.isConnected();
        doc["ip"]             = WiFi.localIP().toString();
        doc["rssi"]           = WiFi.RSSI();
        doc["ws_connected"]   = wsClient.isConnected();
        doc["ws_host"]        = cfg.wsHost;
        doc["ws_port"]        = cfg.wsPort;
        doc["uptime_s"]       = millis() / 1000;
        doc["free_heap"]      = ESP.getFreeHeap();
        doc["safety_stopped"] = safety.isStopped();
        doc["firmware"]       = FIRMWARE_VERSION;

        JsonArray axArr = doc["axes"].to<JsonArray>();
        for (int i = 0; i < MAX_AXES; i++) {
            axArr.add(round(_axisValues[i] * 10.0f) / 10.0f);
        }

        String out;
        serializeJson(doc, out);
        _server.send(200, "application/json", out);
    }

    // ── GET /api/scan — probe common ports for OFS WS server ─────

    void handleScan() {
        JsonDocument doc;
        JsonArray hosts = doc["hosts"].to<JsonArray>();

        // Strategy: probe the gateway and nearby IPs on common OFS ports
        IPAddress gw = WiFi.gatewayIP();
        IPAddress local = WiFi.localIP();
        uint16_t ports[] = { 8082, 8080, 8081, 12345 };

        // Build candidate IPs: gateway, .1, and a sweep of .2-.254
        // (limited to ~20 IPs to keep scan fast)
        IPAddress candidates[24];
        int nCandidates = 0;

        // Always try gateway first
        candidates[nCandidates++] = gw;

        // Then the subnet: prioritise common desktop IPs
        for (uint8_t last = 1; last < 255 && nCandidates < 24; last++) {
            IPAddress cand(local[0], local[1], local[2], last);
            if (cand == local || cand == gw) continue;
            candidates[nCandidates++] = cand;
        }

        WiFiClient tcp;
        tcp.setTimeout(150);  // 150ms connect timeout per probe

        for (int i = 0; i < nCandidates; i++) {
            for (int p = 0; p < 4; p++) {
                if (tcp.connect(candidates[i], ports[p])) {
                    tcp.stop();
                    JsonObject h = hosts.add<JsonObject>();
                    h["ip"]   = candidates[i].toString();
                    h["port"] = ports[p];
                    h["name"] = "OFS @ " + candidates[i].toString();
                    // Found one on this IP, skip other ports
                    break;
                }
            }
            // Yield to avoid WDT during long scans
            yield();

            // Stop after finding 5 hosts (fast enough)
            if (hosts.size() >= 5) break;
        }

        String out;
        serializeJson(doc, out);
        _server.send(200, "application/json", out);
    }

    // ── POST /api/stop ───────────────────────────────────────────

    void handleStop() {
        emergencyStop();
        _server.send(200, "application/json", "{\"ok\":true}");
    }

    // ── POST /api/reboot ─────────────────────────────────────────

    void handleReboot() {
        _server.send(200, "application/json", "{\"ok\":true,\"msg\":\"rebooting\"}");
        delay(500);
        ESP.restart();
    }

    // ── POST /api/wifi_reset ─────────────────────────────────────

    void handleWifiReset() {
        _server.send(200, "application/json",
                     "{\"ok\":true,\"msg\":\"wifi reset, rebooting into AP\"}");
        delay(500);
        WiFiManager wm;
        wm.resetSettings();
        ESP.restart();
    }

    // ── POST /api/factory_reset ──────────────────────────────────

    void handleFactoryReset() {
        _server.send(200, "application/json",
                     "{\"ok\":true,\"msg\":\"factory reset\"}");
        delay(500);
        // Delete config file
        LittleFS.remove(CONFIG_FILE);
        // Reset WiFi
        WiFiManager wm;
        wm.resetSettings();
        ESP.restart();
    }
};
