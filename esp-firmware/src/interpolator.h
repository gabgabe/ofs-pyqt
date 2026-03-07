/*
 * interpolator.h — Ring-buffer axis smoother with deadman detection
 *
 * Receives axis values (0-100 float) from WebSocket at ~60 Hz,
 * provides smooth interpolated output at 100 Hz for actuators.
 */
#pragma once

#include <Arduino.h>

class AxisInterpolator {
public:
    void push(float value) {
        _buf[_head].value = value;
        _buf[_head].timestamp = millis();
        _head = (_head + 1) & 3;  // % 4
        if (_count < 4) _count++;
    }

    /// Get interpolated value (call at actuator rate, e.g. 100 Hz)
    float get() const {
        if (_count == 0) return _default;
        if (_count == 1) return _buf[prev(1)].value;

        // Linear interpolation / extrapolation between last two samples
        const auto& a = _buf[prev(2)];
        const auto& b = _buf[prev(1)];

        uint32_t dt = b.timestamp - a.timestamp;
        if (dt == 0) return b.value;

        uint32_t elapsed = millis() - b.timestamp;
        float t = constrain((float)elapsed / (float)dt, 0.0f, 1.5f);

        float v = b.value + t * (b.value - a.value);
        return constrain(v, 0.0f, 100.0f);
    }

    /// Raw last-pushed value (no interpolation)
    float last() const {
        if (_count == 0) return _default;
        return _buf[prev(1)].value;
    }

    /// True if no data received for > timeoutMs
    bool isStale(uint32_t timeoutMs = 2000) const {
        if (_count == 0) return true;
        return (millis() - _buf[prev(1)].timestamp) > timeoutMs;
    }

    /// Milliseconds since last push
    uint32_t ageMsec() const {
        if (_count == 0) return UINT32_MAX;
        return millis() - _buf[prev(1)].timestamp;
    }

    void reset() {
        _head = 0;
        _count = 0;
    }

    void setDefault(float d) { _default = d; }

private:
    struct Frame {
        float    value     = 0.0f;
        uint32_t timestamp = 0;
    };

    Frame    _buf[4]  = {};
    uint8_t  _head    = 0;
    uint8_t  _count   = 0;
    float    _default = 0.0f;

    /// Index of the n-th most recent entry (1 = newest)
    uint8_t prev(uint8_t n) const {
        return (_head - n + 4) & 3;
    }
};
