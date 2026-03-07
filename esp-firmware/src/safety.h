/*
 * safety.h — Deadman switch + emergency stop
 *
 * If no axis data arrives for DEADMAN_TIMEOUT_MS, all outputs are
 * forced to their safe state (servos centred, PWM off, relays off).
 */
#pragma once

#include <Arduino.h>
#include "config.h"
#include "interpolator.h"

class Safety {
public:
    /// Check all interpolators; returns true if system is live.
    /// Returns false (and calls emergencyStop callback) if stale.
    bool check(AxisInterpolator axes[], int count,
               uint32_t deadmanMs = DEADMAN_TIMEOUT_MS) {
        // Any single axis receiving data keeps the system alive
        bool anyFresh = false;
        for (int i = 0; i < count; i++) {
            if (!axes[i].isStale(deadmanMs)) {
                anyFresh = true;
                break;
            }
        }

        if (anyFresh) {
            if (_stopped) {
                _stopped = false;
                Serial.println("[SAFETY] System LIVE — data resumed");
            }
            return true;
        }

        // All stale — trigger emergency stop (once)
        if (!_stopped) {
            _stopped = true;
            Serial.println("[SAFETY] DEADMAN — no data, emergency stop!");
        }
        return false;
    }

    bool isStopped() const { return _stopped; }

    /// Force back into stopped state (e.g. on WS disconnect)
    void forceStop() { _stopped = true; }

    /// Reset (e.g. on first data after reconnect)
    void reset() { _stopped = false; }

private:
    bool _stopped = true;  // start stopped until first data
};
