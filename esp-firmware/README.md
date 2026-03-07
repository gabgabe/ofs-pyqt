# OFS-PyQt ESP Bridge Firmware

WiFi WebSocket bridge for [OFS-PyQt](../README.md).  
Receives real-time axis values from the `WSOutputBackend` and drives local actuators.

## Supported Outputs

| Output | Type | Pin (ESP8266) | Axis Names |
|--------|------|---------------|------------|
| Servo 1 | PWM (500-2500µs) | GPIO12 (D6) | `servo_1`, `stroke` |
| Servo 2 | PWM (500-2500µs) | GPIO14 (D5) | `servo_2` |
| MOSFET 1 | PWM (1kHz) | GPIO13 (D7) | `pwm_1`, `vib` |
| Relay 1 | Digital | GPIO16 (D0) | `relay_1` |
| PiShock | Serial UART | GPIO4/5 (D2/D1) | `shock_intensity`, `vibrate_intensity` |

## Quick Start

### 1. Install PlatformIO

```bash
pip install platformio
# or use the VS Code PlatformIO extension
```

### 2. Build & Upload

```bash
cd esp-firmware

# ESP8266 (default)
pio run -t upload

# ESP32
pio run -e esp32dev -t upload

# Monitor serial output
pio device monitor
```

### 3. First-Boot Configuration

On first boot (or if WiFi credentials are lost), the ESP creates a hotspot:

1. Connect to WiFi network **`OFS-Bridge-Setup`**
2. A captive portal opens automatically
3. Configure:
   - **WiFi SSID/Password** — your local network
   - **OFS Host IP** — IP address of the PC running OFS-PyQt
   - **OFS WS Port** — WebSocket port (default: 8082)
   - **PiShock Shocker ID** — from PiShock hub (0 = disabled)
   - **PiShock Model** — 1=CaiXianlin, 2=Petrainer, 3=998DR
   - **PiShock Duration** — pulse duration in ms (default: 1000)
4. Click Save — ESP reboots and connects

### 4. OFS-PyQt Setup

In OFS-PyQt's Routing Panel:

1. Add a device: **ESP GPIO Bridge** (or **PiShock**, **OSSM**)
2. Add a **WS Output** instance  
3. Set WS Output host/port to match the ESP config
4. Route funscript tracks → device axes → WS Output
5. Click **Connect** on the WS Output

The ESP will auto-connect as a WebSocket client and start receiving axis values.

## Architecture

```
OFS-PyQt                         ESP8266
┌──────────────┐                ┌─────────────────┐
│ WSOutputBackend ──── WiFi ───→│ WSClient         │
│ (WS server)   │    ~60 Hz    │   ↓              │
└──────────────┘               │ AxisInterpolator │
                                │   ↓              │
                                │ Safety (deadman) │
                                │   ↓              │
                                │ ┌─────┬──────┬──┐│
                                │ │Servo│MOSFET│Rly││
                                │ └─────┘──────┘──┘│
                                │      │PiShock│    │
                                │      └───────┘    │
                                └─────────────────┘
```

## Safety Features

- **Deadman switch**: All outputs stop if no WebSocket data for 2 seconds
- **PiShock rate limiting**: Max 4 commands/second (250ms interval)
- **PiShock deadman**: Independent 2s timeout → sends Stop command
- **Auto-reconnect**: WebSocket reconnects every 3 seconds on disconnect
- **Servo smoothing**: EMA filter prevents jitter
- **Relay debounce**: Min 100ms between toggles

## File Structure

```
esp-firmware/
├── platformio.ini          # Build config (ESP8266 + ESP32 envs)
├── src/
│   ├── main.cpp            # Setup + main loop + WiFiManager portal
│   ├── config.h            # Pin assignments, defaults, axis indices
│   ├── ws_client.h         # WebSocket client (JSON + TCode parsing)
│   ├── interpolator.h      # Ring-buffer smoother + deadman detection
│   ├── safety.h            # Global deadman switch
│   └── outputs/
│       ├── servo_output.h  # Servo PWM driver (EMA smoothing)
│       ├── mosfet_output.h # MOSFET PWM driver (DC motor/vibrator)
│       ├── relay_output.h  # Digital relay with debounce
│       ├── pishock.h       # PiShock serial rftransmit driver
│       └── ossm_bridge.h   # OSSM serial bridge (future)
└── README.md
```

## Protocol Details

See [ESP Firmware Spec](../docs/ESP_FIRMWARE_SPEC.md) for the full protocol documentation.

## Hardware Notes

- **Servos**: Use external 5V supply, not the ESP's 3.3V regulator
- **MOSFETs**: Use logic-level types (IRLZ44N, IRLB8721) — 3.3V gate drive
- **Relays**: Use optocoupler modules that accept 3.3V logic input
- **PiShock**: Connect ESP TX (GPIO4) → Hub RX, ESP RX (GPIO5) → Hub TX
- **ESP8266 max GPIO current**: 12mA — always use a transistor/MOSFET for loads
