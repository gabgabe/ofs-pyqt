/*
 * pishock.h — PiShock / OpenShock serial driver
 *
 * Sends rftransmit JSON commands to an OpenShock hub via UART.
 * Implements all required safety features:
 *   - Rate limiting (max 4 Hz / 250 ms between commands)
 *   - Deadman switch (Stop if no data for 2 s)
 *   - Hard intensity cap (100)
 *   - Minimum duration (300 ms)
 */
#pragma once

#include <Arduino.h>
#ifdef TARGET_ESP8266
  #include <SoftwareSerial.h>
#endif
#include <ArduinoJson.h>
#include "config.h"

// OpenShock command types
enum PiShockCmd : uint8_t {
    PS_STOP    = 0,
    PS_SHOCK   = 1,
    PS_VIBRATE = 2,
    PS_BEEP    = 3,
};

class PiShockDriver {
public:
    PiShockDriver(uint8_t txPin, uint8_t rxPin)
#ifdef TARGET_ESP8266
        : _serial(rxPin, txPin)
#else
        : _serial(1)  // ESP32 UART1
#endif
    {}

    void begin(uint32_t baud = PISHOCK_BAUD) {
#ifdef TARGET_ESP32
        _serial.begin(baud, SERIAL_8N1, PIN_PISHOCK_RX, PIN_PISHOCK_TX);
#else
        _serial.begin(baud);
#endif
        _lastCmdTime = millis();
        _lastDataTime = millis();
        _lastCmd = PS_STOP;
        Serial.printf("[PiShock] UART on TX=%d RX=%d @ %lu baud\n",
                      PIN_PISHOCK_TX, PIN_PISHOCK_RX, baud);
    }

    /// Set shocker config (from WiFiManager portal)
    void configure(uint32_t shockerId, uint8_t model = PISHOCK_MODEL_DEFAULT,
                   uint16_t durationMs = PISHOCK_DURATION_MS) {
        _shockerId  = shockerId;
        _model      = constrain(model, 1, 3);
        _durationMs = constrain(durationMs,
                                (uint16_t)PISHOCK_MIN_DURATION_MS,
                                (uint16_t)65535);
        Serial.printf("[PiShock] id=%lu model=%d dur=%dms\n",
                      (unsigned long)_shockerId, _model, _durationMs);
    }

    /// Call from actuator loop with axis values (0-100)
    void update(float shockIntensity, float vibrateIntensity, float beep) {
        uint32_t now = millis();
        _lastDataTime = now;

        // Rate limiting: enforce minimum interval
        if (now - _lastCmdTime < PISHOCK_MIN_CMD_INTERVAL_MS) return;
        if (_shockerId == 0) return;  // not configured

        // Priority: shock > vibrate > beep > stop
        if (shockIntensity > 1.0f) {
            _send(PS_SHOCK, (uint8_t)min(shockIntensity, (float)PISHOCK_MAX_INTENSITY));
        } else if (vibrateIntensity > 1.0f) {
            _send(PS_VIBRATE, (uint8_t)min(vibrateIntensity, (float)PISHOCK_MAX_INTENSITY));
        } else if (beep > 50.0f) {
            _send(PS_BEEP, 50);
        } else {
            // All zero → send Stop once
            if (_lastCmd != PS_STOP) {
                _send(PS_STOP, 0);
            }
        }
    }

    /// Call from main loop to check deadman timeout
    void checkDeadman() {
        if (_shockerId == 0) return;
        uint32_t elapsed = millis() - _lastDataTime;
        if (elapsed > PISHOCK_DEADMAN_MS && _lastCmd != PS_STOP) {
            Serial.println("[PiShock] DEADMAN — sending STOP");
            _send(PS_STOP, 0);
        }
    }

    /// Force stop immediately
    void emergencyStop() {
        if (_shockerId == 0) return;
        _send(PS_STOP, 0);
    }

    bool isConfigured() const { return _shockerId != 0; }
    PiShockCmd lastCommand() const { return _lastCmd; }

private:
#ifdef TARGET_ESP8266
    SoftwareSerial _serial;
#else
    HardwareSerial _serial;
#endif
    uint32_t  _shockerId   = 0;
    uint8_t   _model       = PISHOCK_MODEL_DEFAULT;
    uint16_t  _durationMs  = PISHOCK_DURATION_MS;
    uint32_t  _lastCmdTime = 0;
    uint32_t  _lastDataTime = 0;
    PiShockCmd _lastCmd    = PS_STOP;

    void _send(PiShockCmd type, uint8_t intensity) {
        // Build JSON payload
        JsonDocument doc;
        doc["model"]       = _model;
        doc["id"]          = _shockerId;
        doc["type"]        = (uint8_t)type;
        doc["intensity"]   = min(intensity, (uint8_t)PISHOCK_MAX_INTENSITY);
        doc["durationMs"]  = _durationMs;

        // Send: "rftransmit <json>\n"
        _serial.print("rftransmit ");
        serializeJson(doc, _serial);
        _serial.print('\n');

        _lastCmd = type;
        _lastCmdTime = millis();

#ifdef DEBUG_PISHOCK
        Serial.print("[PiShock] TX: rftransmit ");
        serializeJson(doc, Serial);
        Serial.println();
#endif
    }
};
