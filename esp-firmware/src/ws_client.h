/*
 * ws_client.h — WebSocket client for OFS-PyQt axis stream
 *
 * Connects to the WSOutputBackend server, parses JSON or TCode
 * messages, and pushes axis values to AxisInterpolator instances.
 */
#pragma once

#include <Arduino.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "interpolator.h"

/// Callback: (axisIndex, value 0-100)
using AxisCallback = void (*)(int idx, float value);

class WSClient {
public:
    void begin(const char* host, uint16_t port, const char* path = "/") {
        _host = host;
        _port = port;
        _path = path;
        _ws.begin(host, port, path);
        _ws.onEvent([this](WStype_t t, uint8_t* p, size_t l) {
            _onEvent(t, p, l);
        });
        _ws.setReconnectInterval(WS_RECONNECT_INTERVAL);
        _ws.enableHeartbeat(15000, 3000, 2);  // ping every 15 s
    }

    void loop() {
        _ws.loop();
    }

    bool isConnected() const { return _connected; }

    /// Register axis callback
    void onAxis(AxisCallback cb) { _axisCb = cb; }

    /// Map an axis name string to an interpolator index.
    /// Returns -1 if unknown.  The mapping matches OFS-PyQt device models:
    ///   esp_gpio:  servo_1, servo_2, pwm_1, pwm_2, relay_1, relay_2
    ///   TCode:     L0=stroke, V0=vib, etc.
    static int axisIndex(const char* name) {
        // ESP GPIO axes
        if (strcmp(name, "servo_1") == 0 || strcmp(name, "stroke") == 0)  return IDX_SERVO_1;
        if (strcmp(name, "servo_2") == 0)                                 return IDX_SERVO_2;
        if (strcmp(name, "pwm_1") == 0   || strcmp(name, "vib") == 0)     return IDX_PWM_1;
        if (strcmp(name, "pwm_2") == 0)                                   return IDX_PWM_2;
        if (strcmp(name, "relay_1") == 0)                                 return IDX_RELAY_1;
        if (strcmp(name, "relay_2") == 0)                                 return IDX_RELAY_2;
        // TCode aliases
        if (strcmp(name, "L0") == 0)  return IDX_SERVO_1;
        if (strcmp(name, "L1") == 0)  return IDX_SERVO_2;
        if (strcmp(name, "V0") == 0)  return IDX_PWM_1;
        if (strcmp(name, "V1") == 0)  return IDX_PWM_2;
        return -1;
    }

private:
    WebSocketsClient _ws;
    AxisCallback     _axisCb    = nullptr;
    bool             _connected = false;
    const char*      _host      = "";
    uint16_t         _port      = 8082;
    const char*      _path      = "/";

    void _onEvent(WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {
        case WStype_CONNECTED:
            _connected = true;
            Serial.printf("[WS] Connected to %s:%d%s\n", _host, _port, _path);
            break;

        case WStype_DISCONNECTED:
            _connected = false;
            Serial.println("[WS] Disconnected");
            break;

        case WStype_TEXT:
            _parseMessage((const char*)payload, length);
            break;

        default:
            break;
        }
    }

    void _parseMessage(const char* msg, size_t len) {
        if (len == 0) return;

        // Quick heuristic: JSON starts with '{', TCode starts with a letter
        if (msg[0] == '{') {
            _parseJson(msg, len);
        } else if (isAlpha(msg[0])) {
            _parseTCode(msg, len);
        }
    }

    // ── JSON mode ───────────────────────────────────────────────
    // {"type":"axis","axes":{"servo_1":50.0,"pwm_1":75.0}}
    void _parseJson(const char* msg, size_t len) {
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, msg, len);
        if (err) {
            Serial.printf("[WS] JSON parse error: %s\n", err.c_str());
            return;
        }

        const char* type = doc["type"];
        if (!type || strcmp(type, "axis") != 0) return;

        JsonObject axes = doc["axes"];
        for (JsonPair kv : axes) {
            int idx = axisIndex(kv.key().c_str());
            if (idx >= 0) {
                float val = kv.value().as<float>();
                if (_axisCb) _axisCb(idx, val);
            }
        }
    }

    // ── TCode mode ──────────────────────────────────────────────
    // "L05000I16 V07500I16\n"
    void _parseTCode(const char* msg, size_t len) {
        String line(msg);
        line.trim();
        int start = 0;

        while (start < (int)line.length()) {
            int space = line.indexOf(' ', start);
            if (space < 0) space = line.length();

            // token = "L05000" or "L05000I16"
            if (space - start >= 6) {
                char axCode[3] = { line[start], line[start + 1], '\0' };

                // Extract value (4 digits after axis code)
                int iPos = line.indexOf('I', start + 2);
                int valEnd = (iPos > start && iPos < space) ? iPos : space;
                String valStr = line.substring(start + 2, valEnd);
                int rawVal = valStr.toInt();           // 0-9999
                float pct = (float)rawVal / 99.99f;    // → 0-100

                int idx = axisIndex(axCode);
                if (idx >= 0 && _axisCb) {
                    _axisCb(idx, pct);
                }
            }

            start = space + 1;
        }
    }
};
