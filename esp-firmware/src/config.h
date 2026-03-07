/*
 * config.h — Compile-time defaults & pin assignments
 *
 * Runtime values come from WiFiManager portal (stored in EEPROM/LittleFS).
 * These are only used as initial defaults on first boot.
 */
#pragma once

// ── WiFi (overridden by WiFiManager) ─────────────────────────────
#define DEFAULT_WIFI_SSID       ""
#define DEFAULT_WIFI_PASS       ""

// ── OFS-PyQt WebSocket output endpoint ───────────────────────────
#define DEFAULT_WS_HOST         "192.168.1.100"
#define DEFAULT_WS_PORT         8082
#define DEFAULT_WS_PATH         "/"

// ── WiFiManager captive portal ───────────────────────────────────
#define AP_NAME                 "OFS-Bridge-Setup"
#define AP_TIMEOUT_SEC          120     // portal auto-closes after 2 min

// ── Embedded web control panel ───────────────────────────────────
#define WEB_UI_PORT             80
#define MDNS_HOSTNAME           "ofs-bridge"
#define FIRMWARE_VERSION        "1.1.0"

// ── Actuator update rate ─────────────────────────────────────────
#define ACTUATOR_INTERVAL_MS    10      // 100 Hz output refresh

// ── Safety ───────────────────────────────────────────────────────
#define DEADMAN_TIMEOUT_MS      2000    // emergency stop after 2 s silence
#define WS_RECONNECT_INTERVAL   3000    // retry WS every 3 s

// ── Pin assignments (ESP8266 NodeMCU v2) ─────────────────────────
//
//  GPIO12 (D6) → Servo signal
//  GPIO13 (D7) → MOSFET gate (PWM)
//  GPIO14 (D5) → Servo 2 / extra PWM
//  GPIO5  (D1) → Relay control
//  GPIO2  (D4) → Status LED (built-in, active LOW)
//
// ⚠ CRITICAL / RESERVED — DO NOT assign to outputs:
//  GPIO0  (D3) — Boot mode select (pull LOW = flash mode)
//  GPIO1  (TX) — Serial TX (used by Serial Monitor)
//  GPIO2  (D4) — Boot (must be HIGH at boot); OK for LED only
//  GPIO3  (RX) — Serial RX (used by Serial Monitor)
//  GPIO15 (D8) — Boot mode select (must be LOW at boot)
//
#ifdef TARGET_ESP8266
  #define DEFAULT_PIN_SERVO_1    12    // D6
  #define DEFAULT_PIN_MOSFET_1   13    // D7
  #define DEFAULT_PIN_SERVO_2    14    // D5
  #define DEFAULT_PIN_RELAY_1     5    // D1
  #define DEFAULT_PIN_STATUS_LED  2    // D4  (built-in, active LOW)
#endif

#ifdef TARGET_ESP32
  #define DEFAULT_PIN_SERVO_1    25
  #define DEFAULT_PIN_MOSFET_1   26
  #define DEFAULT_PIN_SERVO_2    27
  #define DEFAULT_PIN_RELAY_1    32
  #define DEFAULT_PIN_STATUS_LED  2    // built-in
#endif

// ── Servo ────────────────────────────────────────────────────────
#define SERVO_MIN_US            500     // 0%  → 500 µs
#define SERVO_MAX_US            2500    // 100% → 2500 µs
#define SERVO_SMOOTHING         0.3f    // EMA alpha (0=frozen, 1=instant)

// ── MOSFET PWM ───────────────────────────────────────────────────
#define MOSFET_PWM_FREQ         1000    // 1 kHz
#ifdef TARGET_ESP8266
  #define MOSFET_PWM_RANGE      1023    // 10-bit
#else
  #define MOSFET_PWM_RANGE      255     // 8-bit (ESP32 LEDC default)
#endif

// ── Relay ────────────────────────────────────────────────────────
#define RELAY_THRESHOLD         50.0f   // axis > 50% = ON
#define RELAY_DEBOUNCE_MS       100     // min time between toggles

// ── Axis name → index mapping ────────────────────────────────────
// These must match the OFS-PyQt device model axis names
#define MAX_AXES                6

#define IDX_SERVO_1             0   // "servo_1"  or "stroke"
#define IDX_SERVO_2             1   // "servo_2"
#define IDX_PWM_1               2   // "pwm_1"    or "vib"
#define IDX_PWM_2               3   // "pwm_2"
#define IDX_RELAY_1             4   // "relay_1"
#define IDX_RELAY_2             5   // "relay_2"
