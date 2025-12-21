# SPDX-FileCopyrightText: 2024
# SPDX-License-Identifier: MIT

"""
Home Assistant Keybow Controller - Device Side (Keybow 2040)

Communicates with wifi-enabled computer via USB serial.
Sends key press events and receives device state updates.

Deploy: Copy this to /Volumes/CIRCUITPY/code.py
"""

import time
import json
import usb_cdc
from pmk import PMK
from pmk.platform.keybow2040 import Keybow2040 as Hardware

# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

def get_default_config():
    """Return default configuration if config.json is missing"""
    return {
        3: {"label": "Living Room String Lights", "color": (255, 100, 0)},
    }, 20, 5.0


def parse_key_config(keys_config):
    """Parse keys section from config.json into entity map"""
    entity_map = {}
    for key_str, key_config in keys_config.items():
        key_num = int(key_str)
        entity_map[key_num] = {
            "label": key_config.get("label", f"Key {key_num}"),
            "color": tuple(key_config.get("color", [255, 255, 255]))
        }
    return entity_map


def load_config():
    """Load configuration from /config.json file"""
    try:
        with open('/config.json', 'r') as f:
            config = json.load(f)
        
        entity_map = parse_key_config(config.get('keys', {}))
        settings = config.get('settings', {})
        off_brightness = settings.get('off_brightness', 20)
        heartbeat_interval = settings.get('heartbeat_interval', 5.0)
        
        print(f"Config loaded: {len(entity_map)} keys configured")
        return entity_map, off_brightness, heartbeat_interval
        
    except Exception as e:
        print(f"⚠ Config error: {e}, using defaults")
        return get_default_config()


# Load configuration
ENTITY_MAP, OFF_BRIGHTNESS, HEARTBEAT_INTERVAL = load_config()

# ============================================================================
# SERIAL COMMUNICATION
# ============================================================================

serial = usb_cdc.console


def send_command(cmd):
    """Send command to bridge over USB serial"""
    if serial and serial.connected:
        serial.write((cmd + "\n").encode('utf-8'))


# ============================================================================
# KEYBOW HARDWARE SETUP
# ============================================================================

keybow = PMK(Hardware())
keys = keybow.keys


def set_key_led(key_num, is_on):
    """Update LED color based on device state"""
    if key_num not in ENTITY_MAP:
        keys[key_num].set_led(0, 0, 0)  # Off for unmapped keys
        return
    
    r, g, b = ENTITY_MAP[key_num]["color"]
    
    if is_on:
        keys[key_num].set_led(r, g, b)  # Full brightness
    else:
        # Dimmed when off
        keys[key_num].set_led(
            int(r * OFF_BRIGHTNESS / 255),
            int(g * OFF_BRIGHTNESS / 255),
            int(b * OFF_BRIGHTNESS / 255)
        )


def create_press_handler(key_number):
    """Factory function to create handler with proper closure"""
    def handler(key):
        # Flash key at full brightness with its configured color
        if key_number in ENTITY_MAP:
            r, g, b = ENTITY_MAP[key_number]["color"]
            key.set_led(r, g, b)
        
        send_command(f"TOGGLE:{key_number}")
        
        # Return to dim state after press
        # (will be updated to correct state when bridge sends STATE response)
        time.sleep(0.1)  # Brief flash
        set_key_led(key_number, False)
    return handler


# ============================================================================
# KEY HANDLERS
# ============================================================================

# Attach press handlers to all keys
for key in keys:
    keybow.on_press(key)(create_press_handler(key.number))

# Initialize LEDs to dim state for configured keys
for key_num in ENTITY_MAP.keys():
    set_key_led(key_num, False)

# ============================================================================
# STARTUP
# ============================================================================

send_command("READY")
send_command(f"DEBUG:Keybow initialized with {len(ENTITY_MAP)} keys")

# ============================================================================
# MAIN LOOP
# ============================================================================

last_heartbeat = time.monotonic()

while True:
    keybow.update()  # Check for key presses
    
    # Send periodic heartbeat to keep connection alive
    current_time = time.monotonic()
    if current_time - last_heartbeat > HEARTBEAT_INTERVAL:
        send_command("HEARTBEAT")
        last_heartbeat = current_time
    
    time.sleep(0.01)  # Small delay to prevent CPU spinning
