/*
 * servo_output.h — Servo PWM driver
 *
 * Maps axis value (0-100) to servo pulse width (500-2500 µs).
 * Applies exponential moving average smoothing to avoid jitter.
 */
#pragma once

#include <Arduino.h>
#ifdef TARGET_ESP32
  #include <ESP32Servo.h>
#else
  #include <Servo.h>
#endif
#include "config.h"

class ServoOutput {
public:
    explicit ServoOutput(uint8_t pin) : _pin(pin) {}

    void begin() {
        _servo.attach(_pin, SERVO_MIN_US, SERVO_MAX_US);
        _smoothed = 50.0f;  // centre
        writePct(50.0f);
    }

    /// Set from axis value 0-100
    void writePct(float pct) {
        pct = constrain(pct, 0.0f, 100.0f);
        // EMA smoothing
        _smoothed = _smoothed * (1.0f - SERVO_SMOOTHING)
                  + pct       * SERVO_SMOOTHING;
        int us = (int)mapf(_smoothed, 0.0f, 100.0f,
                           (float)SERVO_MIN_US, (float)SERVO_MAX_US);
        _servo.writeMicroseconds(us);
    }

    /// Move to centre position (safe state)
    void stop() {
        _smoothed = 50.0f;
        _servo.writeMicroseconds((SERVO_MIN_US + SERVO_MAX_US) / 2);
    }

    void detach() { _servo.detach(); }

private:
    Servo   _servo;
    uint8_t _pin;
    float   _smoothed = 50.0f;

    static float mapf(float x, float in_min, float in_max,
                      float out_min, float out_max) {
        return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
    }
};
