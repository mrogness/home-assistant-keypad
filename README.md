# Home Assistant Keybow Controller

Controling your Home Assistant devices with a Keybow 2040 RGB mechanical keypad.

This repository stores the python files written for a Keybow 2040 RGB mechanical keypad for use in a Home Assistant Environment. One file is written for the Keybow 2040 and defines the behavior of switches as an HID device. The other is a "bridge" between the keypad a wifi-enabled computer on the same network as the Home Assistant server. It reads the USB input from the pad and makes a corresponding call to the Home Assistant server specified to control various devices, scripts, or scenes as defined by the server. This approach is necessary because the Keybow 2040 is not wifi-enabled, so we "borrow" the wifi capabilities of the connected computer.

This repository was devloped for a specific use case, where the keypad is connected to a Home Assistant Green that was purchased for a family member. That being said, the code should be fairly adaptable to other Linux or MacOS systems as well.

Note: Both of these files borrow heavily from code examples found on the product packaging in order to function properly.
## Setup

### 1. Keybow 2040 Configuration

Connect the Keybow 2040 to your device using a USB C cable.

**Copy files to CIRCUITPY drive:**
- `code.py` → `/Volumes/CIRCUITPY/code.py`
- `config.json` → `/Volumes/CIRCUITPY/config.json`

**Edit `config.json` on the Keybow:**
```json
{
  "keys": {
    "0": {
      "label": "Bedroom Lamp",
      "color": [255, 200, 100]
    },
    "3": {
      "label": "Living Room Lights",
      "color": [255, 100, 0]
    }
  },
  "settings": {
    "off_brightness": 20,
    "heartbeat_interval": 5.0
  }
}
```
**Configuration Options:**
 - `label`: optional value to track indended use of swutch
 -  `color`: RGB values 0-255, e.g., `[255, 0, 0]` = red

It is only necessary to encode values for keys that you indend to use.

### 2. Bridge Configuration

**Edit `bridge_config.json`:**
```json
{
  "home_assistant": {
    "url": "http://YOUR_HA_IP:8123",
    "token": "YOUR_LONG_LIVED_ACCESS_TOKEN"
  },
  "serial": {
    "port_macos": "/dev/cu.usbmodem1101",
    "port_linux": "/dev/ttyACM0",
    "baud_rate": 115200
  },
  "retry_delay": 5,
  "max_retries": null,
  "quiet_mode": false,
  "keys": {
    "0": {
      "entity_id": "light.bedroom_lamp"
    },
    "3": {
      "entity_id": "switch.living_room_string_lights"
    }
  }
}
```

**Configuration Options:**
- `home_assistant.url`: your Home Assistnat URL
- `home_assistant.token`: a generated Long Lived Access Token for your Home Assitant server
- `serial.port_macos`: The serial port to listen to if the host device runs MacOS (default: `"/dev/cu.usbmodem1101"`)
- - `serial.port_linux`: The serial port to listen to if the host device runs Linux (default: `"/dev/ttyACM0"`)
- `retry_delay` - Seconds to wait between restart attempts (default: 5)
- `max_retries` - Maximum restart attempts (default: `null` = infinite, or set a number)
- `quiet_mode` - Suppress heartbeat messages (default: `false`)

### How to get a HA Token:
1. Open Home Assistant
2. Click your profile (bottom left)
3. Scroll to "Long-Lived Access Tokens"
4. Click "Create Token"
5. Copy and paste into config

### 3. Run the Bridge

**macOS (development):**
```zsh
python3 ha_bridge.py
```

**Home Assistant Green (production):**
1. Copy `ha_bridge.py` and `bridge_config.json` to HA Green
2. Install dependencies: 
```bash
pip3 install pyserial requests
```
3. Run: 
```bash
python3 ha_bridge.py
```


## Usage

- **Press a key** → Toggles the mapped Home Assistant device
- **LED feedback** → Key flashes at full brightness in its configured color, then returns to "off" brightness
- **Press reset button** → Restarts both Keybow and bridge (useful for applying config changes)
- **Auto-restart** → Bridge automatically reconnects on errors

## Features

### Keybow Reset Integration
Pressing the reset button on the Keybow will:
1. Reset the Keybow device
2. Trigger a restart of the bridge
3. Reload configuration files
4. Re-sync all device states

This is helpful, as repeatedly pressing the buttons for macros can at times overload the bridge script, which then fails to register further inputs. If this happens, we simply press the reset button on the keypad to restart both the keypad and bridge script.

### Automatic Recovery
The bridge automatically restarts when errors occur:
- Serial disconnection → Waits and reconnects
- Home Assistant API errors → Retries connection
- Network issues → Automatic retry with backoff

Configure retry behavior in `bridge_config.json`:
```json
"retry_delay": 5,      // Wait 5 seconds between retries
"max_retries": null,   // null = infinite, or set limit (e.g., 10)
```

### Configuration-Based Setup
Both Keybow and bridge load settings from JSON files:
- **Keybow**: `/config.json` on CIRCUITPY drive
- **Bridge**: `bridge_config.json` in same directory as `ha_bridge.py`

This allows for a user to only edit json files, rather than the scripts themselves.

## Supported Entity Types

The bridge supports all Home Assistant entity types:

- **Switches** (`switch.*`) - Toggle on/off
- **Lights** (`light.*`) - Toggle on/off
- **Input Booleans** (`input_boolean.*`) - Toggle True/False
- **Scripts** (`script.*`) - Activates script (LED stays dim)
- **Scenes** (`scene.*`) - Activates scene (LED stays dim)

Just map the entity_id in `bridge_config.json` and assign a color in the Keybow `config.json`!

## Adding More Keys

Say we want to add a light switch toggle to the keypad. We need to set this on both config files with the following structure. Note that the `"5"` in this example denotes the key index on the keypad.

1. **On Keybow** - Edit `/Volumes/CIRCUITPY/config.json`:
   ```json
   "keys":{
        "5": {
            "label": "Kitchen Light",
            "color": [100, 100, 255]
        }
   }
   ```

2. **On Bridge** - Edit `bridge_config.json`:
   ```json
   "keys":{
        "5": {
        "entity_id": "light.kitchen"
        }
   }
   
   ```

3. Restart both the Keybow 2040 and bridge script.

## Troubleshooting

**Key press doesn't work:**
- Check bridge is running (look for heartbeat messages using `"quiet_mode" = false`)
- Verify entity_id exists in Home Assistant
- Check terminal for error messages
- Ensure key numbers match between configs

**LEDs wrong color:**
- Verify `color` values in Keybow `config.json`
- Ensure key number matches between Keybow and bridge configs
- Check `off_brightness` setting (default: 20)

**Serial connection failed:**
- macOS: Run `ls /dev/cu.usbmodem*` to find port
- Linux: Usually `/dev/ttyACM0`, (should be `/dev/ttyACM*`)
- Update `port_macos` or `port_linux` in `bridge_config.json`
- Check USB cable connection

**Bridge keeps restarting:**
- Check Home Assistant URL is correct
- Verify access token is valid
- Check network connectivity to HA
- Set `max_retries` to limit restart attempts
- Review error messages in terminal

**Too many messages in terminal:**
- Set `"quiet_mode": true` in `bridge_config.json`
- This suppresses heartbeat messages while keeping error/toggle messages

**Need to reload configuration:**
- Press the reset button on the Keybow
- Bridge will automatically restart and reload configs
- Or manually stop (Ctrl+C) and restart the bridge script

**Bridge won't auto-restart:**
- Check `retry_delay` in config (must be > 0)
- Verify `max_retries` isn't set too low
- Use Ctrl+C to manually stop if needed

## Architecture
(using Key index 3 as an example)
```
┌─────────────┐         USB Serial          ┌──────────────┐
│ Keybow 2040 │ ◄──────────────────────────► │  HA Bridge   │
│             │  TOGGLE:3                    │  (Python)    │
│  - Loads    │  HEARTBEAT                   │              │
│    config   │  ────────────────────►       │  - Loads     │
│  - Sends    │                              │    config    │
│    events   │  ◄────────────────────       │  - Auto      │
│  - Updates  │  STATE:3:on                  │    restart   │
│    LEDs     │                              │  - Calls API │
└─────────────┘                              └──────┬───────┘
                                                    │
                                                    │ REST API
                                                    ▼
                                             ┌──────────────┐
                                             │     Home     │
                                             │  Assistant   │
                                             └──────────────┘
```

## File Structure

```
home-assistant-keypad/
├── code.py              # Keybow device code (copy to CIRCUITPY)
├── ha_bridge.py         # Bridge script (runs on host)
├── keybow_config.json   # Keybow settings template
├── bridge_config.json   # Bridge configuration
└── README.md           # This file
```

## Protocol

**Keybow → Bridge:**
- `READY` - Device initialized
- `HEARTBEAT` - Periodic keep-alive (every 5s)
- `TOGGLE:N` - Key N pressed
- `DEBUG:msg` - Debug information

**Bridge → Keybow:**
- `STATE:N:on` - Entity on
- `STATE:N:off` - Entity off
