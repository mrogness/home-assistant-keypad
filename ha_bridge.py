#!/usr/bin/env python3
"""
Home Assistant Keybow Bridge

Bridges Keybow 2040 to Home Assistant via USB serial.
Receives key press events and toggles HA devices.

Setup:
  1. Edit bridge_config.json with your HA URL, token, and entity mappings
  2. Install dependencies: pip install pyserial requests
  3. Run: python3 ha_bridge.py
"""

import sys
import json
import time
from typing import Dict, Optional
from pathlib import Path
import platform
import serial
import requests

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent

# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

def detect_serial_port(config: dict) -> str:
    """Auto-detect serial port based on platform"""
    serial_config = config.get("serial", {})
    if platform.system() == "Darwin":  # macOS
        return serial_config.get("port_macos", "/dev/cu.usbmodem1101")
    else:  # Linux/HA Green
        return serial_config.get("port_linux", "/dev/ttyACM0")


def parse_entity_map(config: dict) -> Dict[int, str]:
    """Parse key-to-entity mappings from config"""
    keys_config = config.get("keys", {})
    entity_map = {
        int(k): v["entity_id"] 
        for k, v in keys_config.items() 
        if "entity_id" in v
    }
    return entity_map if entity_map else {3: "switch.living_room_string_lights"}


def load_config(config_path: str = "bridge_config.json") -> dict:
    """Load and validate configuration from JSON file"""
    # Look for config file in script directory
    config_file = SCRIPT_DIR / config_path
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        print(f"✓ Loaded configuration from {config_file}")
        return config
    except FileNotFoundError:
        print(f"⚠️  Config file not found: {config_file}")
        return {}
    except Exception as e:
        print(f"⚠️  Error loading config: {e}")
        return {}


# Load and parse configuration
config = load_config()
ha_config = config.get("home_assistant", {})
HA_URL = ha_config.get("url", "http://10.0.0.58:8123")
HA_TOKEN = ha_config.get("token", "YOUR_LONG_LIVED_ACCESS_TOKEN")
SERIAL_PORT = detect_serial_port(config)
BAUD_RATE = config.get("serial", {}).get("baud_rate", 115200)
ENTITY_MAP = parse_entity_map(config)

# Retry configuration
RETRY_DELAY = config.get("retry_delay", 5)  # seconds between restart attempts
MAX_RETRIES = config.get("max_retries", None)  # None = infinite retries

# Output configuration
QUIET_MODE = config.get("quiet_mode", False)  # Suppress heartbeat messages

# ============================================================================
# HOME ASSISTANT API CLIENT
# ============================================================================

class HomeAssistant:
    """Client for Home Assistant REST API"""
    
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.session = requests.Session()
    
    def get_state(self, entity_id: str) -> Optional[str]:
        """Get current state of an entity"""
        try:
            response = self.session.get(
                f"{self.url}/api/states/{entity_id}",
                headers=self.headers,
                timeout=5
            )
            if response.status_code == 200:
                return response.json().get("state")
        except Exception as e:
            print(f"Error getting state for {entity_id}: {e}", file=sys.stderr)
        return None
    
    def call_service(self, domain: str, service: str, entity_id: str) -> bool:
        """Call a Home Assistant service"""
        try:
            response = self.session.post(
                f"{self.url}/api/services/{domain}/{service}",
                headers=self.headers,
                json={"entity_id": entity_id},
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Error calling {domain}.{service}: {e}", file=sys.stderr)
            return False
    
    def toggle(self, entity_id: str) -> bool:
        """Toggle a device (or activate scene/script)"""
        domain = entity_id.split(".")[0]
        service = "turn_on" if domain in ["scene", "script"] else "toggle"
        return self.call_service(domain, service, entity_id)
    
    def is_on(self, entity_id: str) -> bool:
        """Check if entity is currently on"""
        state = self.get_state(entity_id)
        return state == "on"

# ============================================================================
# KEYBOW SERIAL BRIDGE
# ============================================================================

class RestartRequested(Exception):
    """Exception to signal bridge restart is needed"""
    pass


class KeybowBridge:
    """Serial bridge between Keybow 2040 and Home Assistant"""
    
    def __init__(self, serial_port: str, baud_rate: int, ha: HomeAssistant, entity_map: Dict[int, str]):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ha = ha
        self.entity_map = entity_map
        self.ser: Optional[serial.Serial] = None
        self.running = False
        self.ready_count = 0  # Track READY messages
    
    # ------------------------------------------------------------------------
    # Serial Communication
    # ------------------------------------------------------------------------
    
    def connect(self) -> bool:
        """Establish serial connection to Keybow"""
        try:
            print(f"Connecting to Keybow on {self.serial_port}...")
            self.ser = serial.Serial(
                self.serial_port,
                self.baud_rate,
                timeout=1,
                write_timeout=1
            )
            time.sleep(2)  # Allow device to initialize
            print("✓ Connected to Keybow")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}", file=sys.stderr)
            return False
    
    def send_state(self, key_num: int, state: str):
        """Send device state update to Keybow"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(f"STATE:{key_num}:{state}\n".encode())
                self.ser.flush()
            except Exception as e:
                print(f"Error sending state: {e}", file=sys.stderr)
    
    def read_serial(self):
        """Read and process incoming serial data"""
        if not self.ser or not self.ser.is_open:
            return
        
        try:
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore')
                if line:
                    self.handle_command(line.strip())
        except (OSError, serial.SerialException) as e:
            # Serial connection lost - let it bubble up to trigger restart
            print(f"Serial connection error: {e}", file=sys.stderr)
            raise ConnectionError(f"Serial disconnected: {e}")
    
    # ------------------------------------------------------------------------
    # Command Handlers
    # ------------------------------------------------------------------------
    
    def refresh_states(self):
        """Sync all device states from HA to Keybow"""
        for key_num, entity_id in self.entity_map.items():
            try:
                is_on = self.ha.is_on(entity_id)
                state = "on" if is_on else "off"
                self.send_state(key_num, state)
                print(f"  Key {key_num} ({entity_id}): {state}")
            except Exception as e:
                print(f"  Error refreshing key {key_num}: {e}", file=sys.stderr)
    
    def handle_toggle(self, key_num: int):
        """Handle toggle request from Keybow"""
        if key_num not in self.entity_map:
            print(f"⚠️  Key {key_num} not mapped to any entity")
            return
        
        entity_id = self.entity_map[key_num]
        print(f"Toggle: Key {key_num} → {entity_id}")
        
        if self.ha.toggle(entity_id):
            print(f"  ✓ Toggled {entity_id}")
            time.sleep(0.2)  # Brief wait for state update
            is_on = self.ha.is_on(entity_id)
            state = "on" if is_on else "off"
            self.send_state(key_num, state)
        else:
            print(f"  ✗ Failed to toggle {entity_id}")
    
    def handle_command(self, command: str):
        """Process command received from Keybow"""
        if command == "READY":
            self.ready_count += 1
            
            # If this is a second READY (Keybow was reset), restart bridge
            if self.ready_count > 1:
                print("\n🔄 Keybow reset detected, restarting bridge...")
                raise RestartRequested("Keybow reset button pressed")
            
            print("\n🔄 Keybow ready, syncing states...")
            self.refresh_states()
        
        elif command == "HEARTBEAT":
            if not QUIET_MODE:
                print("♥ Heartbeat")
        
        elif command.startswith("TOGGLE:"):
            key_num = int(command.split(":")[1])
            self.handle_toggle(key_num)
        
        elif command.startswith(("DEBUG:", "ERROR:")):
            print(f"[Keybow] {command}")
    
    # ------------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------------
    
    def run(self):
        """Main bridge event loop"""
        if not self.connect():
            raise ConnectionError(f"Failed to connect to {self.serial_port}")
        
        self.running = True
        
        print("\n" + "="*60)
        print("🏠 HOME ASSISTANT KEYBOW BRIDGE")
        print("="*60)
        print(f"Monitoring {len(self.entity_map)} entities")
        print("Press Ctrl+C to stop\n")
        
        try:
            while self.running:
                self.read_serial()
                time.sleep(0.01)
        
        except KeyboardInterrupt:
            print("\n\n⏹️  Shutting down...")
            raise  # Re-raise to signal clean exit
        
        except RestartRequested as e:
            print(f"Restart: {e}")
            raise  # Re-raise to trigger restart
        
        except Exception as e:
            print(f"\n⚠️  Error in main loop: {e}", file=sys.stderr)
            raise  # Re-raise to trigger restart
        
        finally:
            self.running = False
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                    time.sleep(0.5)  # Brief delay to ensure clean disconnect
                except:
                    pass
            print("✓ Bridge stopped")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def validate_config():
    """Validate required configuration values"""
    errors = []
    
    if not HA_TOKEN or HA_TOKEN == "YOUR_LONG_LIVED_ACCESS_TOKEN":
        errors.append("HA_TOKEN not set in bridge_config.json")
        errors.append("  Add token under: home_assistant.token")
        errors.append("  Get token: HA Profile → Long-Lived Access Tokens")
    
    if not ENTITY_MAP:
        errors.append("No entities mapped in bridge_config.json")
        errors.append("  Add entries to the 'keys' section")
    
    if not config:
        errors.append("Failed to load bridge_config.json")
        errors.append("  Ensure file exists in same directory as script")
    
    return errors


def main():
    """Initialize and run the bridge with automatic restart on errors"""
    print("\n" + "="*60)
    print("🔌 Home Assistant Keybow Bridge")
    print("="*60 + "\n")
    
    # Validate configuration
    errors = validate_config()
    if errors:
        print("⚠️  Configuration errors:\n")
        for error in errors:
            print(f"  {error}")
        print()
        sys.exit(1)
    
    # Display configuration
    print(f"Home Assistant: {HA_URL}")
    print(f"Serial Port:    {SERIAL_PORT} @ {BAUD_RATE} baud")
    print(f"Mapped Keys:    {len(ENTITY_MAP)}")
    if MAX_RETRIES:
        print(f"Max Retries:    {MAX_RETRIES}")
    else:
        print(f"Auto-restart:   Enabled (infinite retries)")
    print()
    
    # Initialize Home Assistant client
    ha = HomeAssistant(HA_URL, HA_TOKEN)
    
    # Retry loop
    retry_count = 0
    while True:
        try:
            # Create new bridge instance for each attempt
            bridge = KeybowBridge(SERIAL_PORT, BAUD_RATE, ha, ENTITY_MAP)
            bridge.run()
            
            # If run() exits normally (shouldn't happen), break
            break
        
        except KeyboardInterrupt:
            print("\n✓ Stopped by user")
            break
        
        except RestartRequested:
            # Keybow reset detected, restart immediately without delay
            retry_count = 0  # Reset counter
            print("🔄 Restarting now...\n")
            continue
        
        except Exception as e:
            retry_count += 1
            
            # Check if we've hit max retries
            if MAX_RETRIES and retry_count >= MAX_RETRIES:
                print(f"\n✗ Max retries ({MAX_RETRIES}) reached. Exiting.")
                sys.exit(1)
            
            # Display error and retry info
            print(f"\n⚠️  Error (attempt {retry_count}): {e}")
            print(f"🔄 Restarting in {RETRY_DELAY} seconds...")
            
            try:
                time.sleep(RETRY_DELAY)
            except KeyboardInterrupt:
                print("\n✓ Stopped by user during retry wait")
                break


if __name__ == "__main__":
    main()
