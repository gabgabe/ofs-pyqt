/*
 * OFS-PyQt ESP Bridge Firmware
 * ============================
 *
 * WiFi WebSocket bridge for OFS-PyQt.  Receives real-time axis values
 * from the WSOutputBackend and drives local actuators:
 *
 *   - Servo motors (PWM)
 *   - MOSFET / DC motor (PWM)
 *   - Relay (digital on/off)
 *
 * Configuration is done via:
 *   1. WiFiManager captive portal on first boot (WiFi credentials)
 *   2. Embedded web panel on port 80 (OFS IP, GPIO, outputs, etc.)
 *      → http://ofs-bridge.local/ or http://<ip>/
 *
 * Safety:
 *   - Deadman switch: emergency stop if no data for configurable timeout
 *   - Auto-reconnect on WiFi or WS drop
 *   - All outputs default to safe state on startup
 */

#include <Arduino.h>

#ifdef TARGET_ESP8266
  #include <ESP8266WiFi.h>
  #include <LittleFS.h>
#endif
#ifdef TARGET_ESP32
  #include <WiFi.h>
  #include <LittleFS.h>
#endif

#include <WiFiManager.h>
#include <ArduinoJson.h>

#include "config.h"
#include "interpolator.h"
#include "ws_client.h"
#include "safety.h"
#include "outputs/servo_output.h"
#include "outputs/mosfet_output.h"
#include "outputs/relay_output.h"

// ── Runtime config (persisted in LittleFS) ───────────────────────

struct RuntimeConfig {
    // OFS connection
    char     wsHost[64]       = DEFAULT_WS_HOST;
    uint16_t wsPort           = DEFAULT_WS_PORT;
    char     wsFormat[12]     = "json";

    // Output enables
    bool     enableServos     = true;
    bool     enableMosfet     = true;
    bool     enableRelay      = true;

    // Timing
    uint16_t actuatorHz       = 100;
    uint16_t deadmanMs        = DEADMAN_TIMEOUT_MS;

    // GPIO pin assignments (runtime-configurable via web panel)
    uint8_t  pinServo1        = DEFAULT_PIN_SERVO_1;
    uint8_t  pinServo2        = DEFAULT_PIN_SERVO_2;
    uint8_t  pinMosfet1       = DEFAULT_PIN_MOSFET_1;
    uint8_t  pinRelay1        = DEFAULT_PIN_RELAY_1;
    uint8_t  pinStatusLed     = DEFAULT_PIN_STATUS_LED;
} cfg;

// ── Global state ─────────────────────────────────────────────────

AxisInterpolator axes[MAX_AXES];

// Output drivers — use pointers so we can reinit with new pins
ServoOutput*   servo1  = nullptr;
ServoOutput*   servo2  = nullptr;
MosfetOutput*  mosfet1 = nullptr;
RelayOutput*   relay1  = nullptr;

// WebSocket + Safety
WSClient wsClient;
Safety   safety;

// Status LED blink state
uint32_t ledLastToggle = 0;
bool     ledState      = false;

// Config file path (needed by web_ui.h)
#define CONFIG_FILE "/ofs_config.json"

// ── Include web UI (needs cfg, axes, wsClient, safety externs) ───
#include "web_ui.h"

WebUI webUI;

// ── Config persistence (LittleFS) ────────────────────────────────


void loadConfig() {
    if (!LittleFS.begin()) {
        Serial.println("[CFG] LittleFS mount failed, using defaults");
        return;
    }
    File f = LittleFS.open(CONFIG_FILE, "r");
    if (!f) {
        Serial.println("[CFG] No config file, using defaults");
        return;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, f);
    f.close();
    if (err) {
        Serial.printf("[CFG] Parse error: %s\n", err.c_str());
        return;
    }

    strlcpy(cfg.wsHost,   doc["ws_host"]   | DEFAULT_WS_HOST,  sizeof(cfg.wsHost));
    cfg.wsPort           = doc["ws_port"]   | DEFAULT_WS_PORT;
    strlcpy(cfg.wsFormat, doc["ws_format"]  | "json",           sizeof(cfg.wsFormat));

    cfg.enableServos     = doc["enable_servos"]  | true;
    cfg.enableMosfet     = doc["enable_mosfet"]  | true;
    cfg.enableRelay      = doc["enable_relay"]   | true;
    cfg.actuatorHz       = doc["actuator_hz"]    | 100;
    cfg.deadmanMs        = doc["deadman_ms"]     | DEADMAN_TIMEOUT_MS;

    cfg.pinServo1        = doc["pin_servo1"]     | DEFAULT_PIN_SERVO_1;
    cfg.pinServo2        = doc["pin_servo2"]     | DEFAULT_PIN_SERVO_2;
    cfg.pinMosfet1       = doc["pin_mosfet1"]    | DEFAULT_PIN_MOSFET_1;
    cfg.pinRelay1        = doc["pin_relay1"]     | DEFAULT_PIN_RELAY_1;
    cfg.pinStatusLed     = doc["pin_led"]        | DEFAULT_PIN_STATUS_LED;

    Serial.printf("[CFG] Loaded: ws=%s:%d fmt=%s hz=%d pins=%d/%d/%d/%d led=%d\n",
                  cfg.wsHost, cfg.wsPort, cfg.wsFormat, cfg.actuatorHz,
                  cfg.pinServo1, cfg.pinServo2, cfg.pinMosfet1, cfg.pinRelay1,
                  cfg.pinStatusLed);
}

void saveConfig() {
    JsonDocument doc;
    doc["ws_host"]        = cfg.wsHost;
    doc["ws_port"]        = cfg.wsPort;
    doc["ws_format"]      = cfg.wsFormat;
    doc["enable_servos"]  = cfg.enableServos;
    doc["enable_mosfet"]  = cfg.enableMosfet;
    doc["enable_relay"]   = cfg.enableRelay;
    doc["actuator_hz"]    = cfg.actuatorHz;
    doc["deadman_ms"]     = cfg.deadmanMs;
    doc["pin_servo1"]     = cfg.pinServo1;
    doc["pin_servo2"]     = cfg.pinServo2;
    doc["pin_mosfet1"]    = cfg.pinMosfet1;
    doc["pin_relay1"]     = cfg.pinRelay1;
    doc["pin_led"]        = cfg.pinStatusLed;

    File f = LittleFS.open(CONFIG_FILE, "w");
    if (!f) {
        Serial.println("[CFG] Failed to open config for writing");
        return;
    }
    serializeJson(doc, f);
    f.close();
    Serial.println("[CFG] Saved");
}

// ── WiFiManager setup (only handles WiFi credentials) ────────────

void setupWiFi() {
    WiFiManager wm;
    wm.setConfigPortalTimeout(AP_TIMEOUT_SEC);

    if (!wm.autoConnect(AP_NAME)) {
        Serial.println("[WIFI] Portal timed out, restarting...");
        delay(1000);
        ESP.restart();
    }

    Serial.printf("[WIFI] Connected! IP: %s\n",
                  WiFi.localIP().toString().c_str());
}

// ── Output driver init / teardown ────────────────────────────────

void initOutputs() {
    // Clean up old instances if re-initialising
    if (servo1)  { servo1->detach();  delete servo1;  servo1  = nullptr; }
    if (servo2)  { servo2->detach();  delete servo2;  servo2  = nullptr; }
    if (mosfet1) { mosfet1->stop();   delete mosfet1; mosfet1 = nullptr; }
    if (relay1)  { relay1->stop();    delete relay1;  relay1  = nullptr; }

    if (cfg.enableServos) {
        servo1 = new ServoOutput(cfg.pinServo1);
        servo2 = new ServoOutput(cfg.pinServo2);
        servo1->begin();
        servo2->begin();
        Serial.printf("[OUT] Servos on GPIO %d, %d\n", cfg.pinServo1, cfg.pinServo2);
    }
    if (cfg.enableMosfet) {
        mosfet1 = new MosfetOutput(cfg.pinMosfet1);
        mosfet1->begin();
        Serial.printf("[OUT] MOSFET PWM on GPIO %d\n", cfg.pinMosfet1);
    }
    if (cfg.enableRelay) {
        relay1 = new RelayOutput(cfg.pinRelay1);
        relay1->begin();
        Serial.printf("[OUT] Relay on GPIO %d\n", cfg.pinRelay1);
    }
}

// ── Status LED ───────────────────────────────────────────────────

void updateStatusLed() {
    uint32_t interval;
    if (!WiFi.isConnected())          interval = 100;   // fast blink: no WiFi
    else if (!wsClient.isConnected()) interval = 500;   // slow blink: no WS
    else if (safety.isStopped())      interval = 1000;  // very slow: deadman
    else                              interval = 0;     // solid ON: all good

    if (interval == 0) {
        digitalWrite(cfg.pinStatusLed, LOW);  // active LOW = LED on
        return;
    }

    uint32_t now = millis();
    if (now - ledLastToggle >= interval) {
        ledLastToggle = now;
        ledState = !ledState;
        digitalWrite(cfg.pinStatusLed, ledState ? HIGH : LOW);
    }
}

// ── Emergency stop (all outputs to safe state) ───────────────────

void emergencyStop() {
    if (servo1)  servo1->stop();
    if (servo2)  servo2->stop();
    if (mosfet1) mosfet1->stop();
    if (relay1)  relay1->stop();
}

// ── WS reconnect (called from web UI after config change) ────────

void wsReconnect() {
    Serial.printf("[WS] Reconnecting to ws://%s:%d/ ...\n",
                  cfg.wsHost, cfg.wsPort);
    wsClient.begin(cfg.wsHost, cfg.wsPort, "/");
}

// ── Arduino setup() ──────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\n\n=== OFS-PyQt ESP Bridge v" FIRMWARE_VERSION " ===");

    // Load persistent config (before WiFi, so we have pin assignments)
    loadConfig();

    // Status LED
    pinMode(cfg.pinStatusLed, OUTPUT);
    digitalWrite(cfg.pinStatusLed, HIGH);  // off (active LOW)

    // WiFi (captive portal on first boot, auto-connect thereafter)
    setupWiFi();

    // Initialize output drivers with runtime pin config
    initOutputs();

    // Set default axis values
    axes[IDX_SERVO_1].setDefault(50.0f);  // centre
    axes[IDX_SERVO_2].setDefault(50.0f);
    axes[IDX_PWM_1].setDefault(0.0f);     // off
    axes[IDX_PWM_2].setDefault(0.0f);
    axes[IDX_RELAY_1].setDefault(0.0f);   // off
    axes[IDX_RELAY_2].setDefault(0.0f);

    // WebSocket client
    wsClient.onAxis([](int idx, float value) {
        if (idx >= 0 && idx < MAX_AXES) {
            axes[idx].push(value);
        }
    });
    wsClient.begin(cfg.wsHost, cfg.wsPort, "/");

    // Embedded web control panel + mDNS
    webUI.onReconnect(wsReconnect);
    webUI.begin();

    Serial.printf("[MAIN] Ready\n");
    Serial.printf("  WS:  ws://%s:%d/\n", cfg.wsHost, cfg.wsPort);
    Serial.printf("  Web: http://%s/  or  http://%s.local/\n",
                  WiFi.localIP().toString().c_str(), MDNS_HOSTNAME);
}

// ── Arduino loop() ───────────────────────────────────────────────

void loop() {
    // 1. Poll WebSocket (receive messages, handle reconnect)
    wsClient.loop();

    // 2. Serve web control panel + mDNS
    webUI.loop();

    // 3. Fixed-rate actuator update
    static uint32_t lastActuator = 0;
    uint32_t now = millis();
    uint32_t actInterval = 1000 / cfg.actuatorHz;

    if (now - lastActuator >= actInterval) {
        lastActuator = now;

        // 4. Safety check (deadman — uses runtime-configurable timeout)
        if (safety.check(axes, MAX_AXES, cfg.deadmanMs)) {
            // System is LIVE — drive outputs from interpolated values
            if (servo1)  servo1->writePct(axes[IDX_SERVO_1].get());
            if (servo2)  servo2->writePct(axes[IDX_SERVO_2].get());
            if (mosfet1) mosfet1->writePct(axes[IDX_PWM_1].get());
            if (relay1)  relay1->writePct(axes[IDX_RELAY_1].last());

            // Update web UI with current axis values
            float axVals[MAX_AXES];
            for (int i = 0; i < MAX_AXES; i++) axVals[i] = axes[i].last();
            webUI.setAxes(axVals, MAX_AXES);
        } else {
            // DEADMAN triggered — emergency stop
            emergencyStop();

            // Report zero to web UI
            float zeros[MAX_AXES] = {};
            webUI.setAxes(zeros, MAX_AXES);
        }
    }

    // 5. Status LED
    updateStatusLed();
}
