/*
 * ossm_bridge.h — OSSM serial bridge (ESP8266 → OSSM ESP32)
 *
 * Bridges axis values received via WebSocket to serial text commands
 * that the OSSM firmware understands.  The OSSM ESP32 is connected
 * via UART (using its BLE command format over serial).
 *
 * Commands sent:
 *   stream:<position 0-100>:<time_ms>\n
 *   set:speed:<value>\n
 *   set:depth:<value>\n
 *   set:sensation:<value>\n
 *   go:streaming\n
 *   go:stop\n
 */
#pragma once

#include <Arduino.h>
#ifdef TARGET_ESP8266
  #include <SoftwareSerial.h>
#endif
#include "config.h"

class OSSMBridge {
public:
    OSSMBridge(uint8_t txPin, uint8_t rxPin)
#ifdef TARGET_ESP8266
        : _serial(rxPin, txPin)
#else
        : _serial(2)  // ESP32 UART2
#endif
    {}

    void begin(uint32_t baud = 115200) {
#ifdef TARGET_ESP32
        _serial.begin(baud, SERIAL_8N1, rxPin(), txPin());
#else
        _serial.begin(baud);
#endif
        _lastSendMs = millis();
        Serial.printf("[OSSM] Serial bridge on TX=%d RX=%d @ %lu\n",
                      txPin(), rxPin(), baud);
    }

    /// Enter streaming mode (call once after connect)
    void startStreaming() {
        _serial.println("go:streaming");
        _streaming = true;
        Serial.println("[OSSM] go:streaming");
    }

    /// Stop motor
    void stop() {
        _serial.println("go:stop");
        _streaming = false;
        Serial.println("[OSSM] go:stop");
    }

    /// Send position update (call from actuator loop)
    /// @param stroke  0-100 (position)
    /// @param intervalMs  time to reach position (typically 16 ms)
    void sendStream(float stroke, uint16_t intervalMs = 16) {
        if (!_streaming) startStreaming();

        uint32_t now = millis();
        // Don't send faster than the interval
        if (now - _lastSendMs < intervalMs) return;
        _lastSendMs = now;

        int pos = constrain((int)stroke, 0, 100);
        char buf[32];
        snprintf(buf, sizeof(buf), "stream:%d:%u", pos, intervalMs);
        _serial.println(buf);
    }

    /// Send set:parameter commands (less frequent, for mode changes)
    void setSpeed(float pct) {
        char buf[24];
        snprintf(buf, sizeof(buf), "set:speed:%d", constrain((int)pct, 0, 100));
        _serial.println(buf);
    }

    void setDepth(float pct) {
        char buf[24];
        snprintf(buf, sizeof(buf), "set:depth:%d", constrain((int)pct, 0, 100));
        _serial.println(buf);
    }

    void setSensation(float pct) {
        char buf[24];
        snprintf(buf, sizeof(buf), "set:sensation:%d", constrain((int)pct, 0, 100));
        _serial.println(buf);
    }

    bool isStreaming() const { return _streaming; }

private:
#ifdef TARGET_ESP8266
    SoftwareSerial _serial;
#else
    HardwareSerial _serial;
#endif
    bool     _streaming  = false;
    uint32_t _lastSendMs = 0;

    // Store pins for debug print (SoftwareSerial doesn't expose them)
    uint8_t txPin() const { return PIN_PISHOCK_TX; }  // reuses same pins
    uint8_t rxPin() const { return PIN_PISHOCK_RX; }
};
