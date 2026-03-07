/*
 * mosfet_output.h — MOSFET / PWM intensity driver
 *
 * Drives a logic-level MOSFET (IRLZ44N, IRLB8721) for DC motors,
 * vibrators, heating elements, etc.
 *
 * Maps axis value (0-100) → PWM duty cycle.
 * ESP8266: 10-bit (0-1023), 1 kHz.
 * ESP32:   8-bit (0-255), LEDC channel.
 */
#pragma once

#include <Arduino.h>
#include "config.h"

class MosfetOutput {
public:
    explicit MosfetOutput(uint8_t pin) : _pin(pin) {}

    void begin() {
        pinMode(_pin, OUTPUT);
        analogWrite(_pin, 0);
#ifdef TARGET_ESP8266
        analogWriteFreq(MOSFET_PWM_FREQ);
        analogWriteRange(MOSFET_PWM_RANGE);
#endif
#ifdef TARGET_ESP32
        // ESP32 uses LEDC
        _channel = _nextChannel++;
        ledcSetup(_channel, MOSFET_PWM_FREQ, 8);  // 8-bit
        ledcAttachPin(_pin, _channel);
#endif
    }

    /// Set from axis value 0-100
    void writePct(float pct) {
        pct = constrain(pct, 0.0f, 100.0f);
        int duty = (int)(pct / 100.0f * MOSFET_PWM_RANGE);
#ifdef TARGET_ESP8266
        analogWrite(_pin, duty);
#endif
#ifdef TARGET_ESP32
        ledcWrite(_channel, duty);
#endif
    }

    /// Safe state: off
    void stop() {
        writePct(0.0f);
    }

private:
    uint8_t _pin;
#ifdef TARGET_ESP32
    uint8_t _channel = 0;
    static uint8_t _nextChannel;
#endif
};

#ifdef TARGET_ESP32
uint8_t MosfetOutput::_nextChannel = 0;
#endif
