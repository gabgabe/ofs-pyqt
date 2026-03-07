/*
 * relay_output.h — Digital relay driver with debounce
 *
 * Drives an optocoupler relay module or bare relay via MOSFET.
 * Axis value > threshold = ON, below = OFF.
 * Debounce: prevents toggling faster than RELAY_DEBOUNCE_MS.
 */
#pragma once

#include <Arduino.h>
#include "config.h"

class RelayOutput {
public:
    explicit RelayOutput(uint8_t pin, float threshold = RELAY_THRESHOLD,
                         bool activeLow = false)
        : _pin(pin), _threshold(threshold), _activeLow(activeLow) {}

    void begin() {
        pinMode(_pin, OUTPUT);
        _write(false);
    }

    /// Set from axis value 0-100
    void writePct(float pct) {
        bool want = (pct >= _threshold);
        if (want == _state) return;

        // Debounce: don't toggle faster than interval
        uint32_t now = millis();
        if (now - _lastToggle < RELAY_DEBOUNCE_MS) return;

        _state = want;
        _lastToggle = now;
        _write(want);
    }

    /// Safe state: off
    void stop() {
        _state = false;
        _write(false);
    }

    bool isOn() const { return _state; }

private:
    uint8_t  _pin;
    float    _threshold;
    bool     _activeLow;
    bool     _state       = false;
    uint32_t _lastToggle  = 0;

    void _write(bool on) {
        bool level = _activeLow ? !on : on;
        digitalWrite(_pin, level ? HIGH : LOW);
    }
};
