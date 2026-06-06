"""
Arduino Nano Serial Reader with Fall Detection.

Reads JSON sensor data from Arduino, detects falls using MPU6050
accelerometer data, and sends serial commands to control buzzer/vibration.

Expected JSON from Arduino:
  {"d":150.5,"ax":200,"ay":-100,"az":16384,"gx":50,"gy":-30,"gz":10,
   "lat":31.95,"lon":35.91,"gps":true,"buz":0,"vib":0,"auto":1,"ad":50}

Serial commands to Arduino:
  b1/b0     - Buzzer on/off
  v1/v0     - Vibration on/off
  a1/a0     - Auto alarm on/off
  d50       - Set alarm distance
  alert     - Emergency: buzzer + vibration ON
  stop      - Stop all outputs
"""

import serial
import serial.tools.list_ports
import json
import threading
import time
import math


# MPU6050 sensitivity: 16384 LSB/g at ±2g range
LSB_PER_G = 16384.0

# Fall detection thresholds
FREEFALL_THRESHOLD = 0.4   # g - below this = free fall
IMPACT_THRESHOLD = 2.0     # g - above this = hard impact (more sensitive)
STILL_THRESHOLD = 0.3      # g variance - person lying still after fall
FALL_CONFIRM_SECONDS = 3   # seconds to wait before confirming fall
FALL_COOLDOWN_SECONDS = 60 # don't re-trigger fall for 60s

# Person info (placeholder - will be dynamic later)
PERSON_NAME = "Ahmed Mohamed"
PERSON_AGE = 72
PERSON_ID = "P001"


class ArduinoReader:
    def __init__(self, port=None, baud_rate=115200, timeout=2):
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.serial_conn = None
        self.latest_data = {}
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # Fall detection state
        self._accel_history = []
        self._fall_phase = None        # None, "freefall", "impact"
        self._fall_event_time = 0
        self._last_fall_alert = 0
        self._fall_detected = False

        # Callbacks
        self._on_fall_callback = None

        # Auto-detect port
        if port is None:
            port = self._auto_detect_port()
        self.port = port

    def _auto_detect_port(self):
        """Auto-detect Arduino serial port."""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = (p.description or "").lower()
            mfr = (p.manufacturer or "").lower()
            if any(kw in desc for kw in ["arduino", "ch340", "cp210", "ftdi", "usb serial", "usb2.0-serial"]):
                print(f"Arduino: Auto-detected on {p.device} ({p.description})")
                return p.device
            if any(kw in mfr for kw in ["arduino", "wch", "silicon labs", "ftdi", "qinheng"]):
                print(f"Arduino: Auto-detected on {p.device} (mfr: {p.manufacturer})")
                return p.device

        import os
        for candidate in ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyCH341USB0", "/dev/ttyUSB1", "/dev/ttyACM1", "/dev/ttyCH341USB1"]:
            if os.path.exists(candidate):
                print(f"Arduino: Found serial port {candidate}")
                return candidate

        print("Arduino: No serial port detected.")
        return None

    def set_on_fall(self, callback):
        """Set callback for fall detection: callback(data) where data has GPS + sensor info."""
        self._on_fall_callback = callback

    def connect(self):
        """Open serial connection."""
        if self.port is None:
            print("Arduino: No serial port available.")
            return False
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout
            )
            time.sleep(2)
            self.serial_conn.reset_input_buffer()
            print(f"Arduino: Connected on {self.port} at {self.baud_rate} baud")
            return True
        except serial.SerialException as e:
            print(f"Arduino: Connection failed - {e}")
            return False

    def start(self):
        """Start reading in background thread."""
        if not self.serial_conn or not self.serial_conn.is_open:
            if not self.connect():
                return False
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print("Arduino: Reader started.")
        return True

    def stop(self):
        """Stop reader and close serial."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("Arduino: Connection closed.")

    # =================== Serial Commands ===================

    def send_command(self, cmd):
        """Send a command to Arduino via Serial."""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write(f"{cmd}\n".encode())
                print(f"Arduino: Sent command '{cmd}'")
                return True
            except serial.SerialException as e:
                print(f"Arduino: Failed to send command - {e}")
        return False

    def buzzer_on(self):
        return self.send_command("b1")

    def buzzer_off(self):
        return self.send_command("b0")

    def vibration_on(self):
        return self.send_command("v1")

    def vibration_off(self):
        return self.send_command("v0")

    def alert_on(self):
        """Emergency: turn on buzzer + vibration."""
        return self.send_command("alert")

    def alert_off(self):
        """Stop buzzer + vibration."""
        return self.send_command("stop")

    def set_auto_alarm(self, on=True):
        return self.send_command("a1" if on else "a0")

    def set_alarm_distance(self, cm):
        return self.send_command(f"d{cm}")

    def pothole_alert(self):
        """Intermittent buzzer + vibration for pothole warning (handled by Arduino 'palert' command)."""
        self.send_command("palert")

    # =================== Data Reading ===================

    def _read_loop(self):
        """Continuously read and parse serial data."""
        while self._running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self._process_line(line)
                else:
                    time.sleep(0.05)
            except serial.SerialException as e:
                print(f"Arduino: Serial error - {e}")
                time.sleep(1)
            except Exception as e:
                print(f"Arduino: Error - {e}")
                time.sleep(0.5)

    def _process_line(self, line):
        """Parse a JSON line and check for falls."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return

        if not isinstance(data, dict):
            return

        # Command response
        if "cmd" in data:
            return

        # Status message
        if "status" in data:
            print(f"Arduino: {data}")
            return

        # Sensor data - update latest
        with self._lock:
            self.latest_data = data

        # Check for fall
        if "ax" in data and "ay" in data and "az" in data:
            self._check_fall(data)

    # =================== Fall Detection ===================

    def _check_fall(self, data):
        """
        Simplified Collision Detection algorithm.
        
        - Ignores movements during the first 10 seconds (calibration / setup).
        - Triggers immediately if acceleration magnitude exceeds an impact threshold.
        """
        if not hasattr(self, '_startup_time'):
            self._startup_time = time.time()

        now = time.time()
        
        # Calibration / Setup phase (ignore collisions for first 10 seconds)
        if (now - self._startup_time) < 10.0:
            return

        ax = data.get("ax", 0)
        ay = data.get("ay", 0)
        az = data.get("az", 0)

        # Calculate total acceleration in g units
        magnitude = math.sqrt(ax**2 + ay**2 + az**2) / LSB_PER_G

        # Debug print magnitude every 1 second
        if not hasattr(self, '_last_debug_print') or (now - self._last_debug_print) >= 1.0:
            print(f"[DEBUG] Current MPU Magnitude: {magnitude:.2f}g")
            self._last_debug_print = now

        # Cooldown check
        if (now - self._last_fall_alert) < FALL_COOLDOWN_SECONDS:
            return

        # Only trigger on hard impact (e.g. cane hitting the ground)
        if magnitude > IMPACT_THRESHOLD:
            print(f"⚠️ Hard Impact Detected! (magnitude={magnitude:.2f}g, threshold={IMPACT_THRESHOLD}g)")
            self._trigger_fall_alert(data)

    def _trigger_fall_alert(self, data):
        """Handle confirmed fall event."""
        self._last_fall_alert = time.time()
        self._fall_detected = True

        lat = data.get("lat", 0)
        lon = data.get("lon", 0)
        gps_fix = data.get("gps", False)

        print("=" * 50)
        print("🚨 FALL DETECTED! 🚨")
        print(f"   Person: {PERSON_NAME}")
        print(f"   GPS: {lat}, {lon} (fix: {gps_fix})")
        print("=" * 50)

        # Turn on buzzer and vibration
        self.alert_on()

        # Call the fall callback (sends Telegram alert)
        if self._on_fall_callback:
            fall_info = {
                "person_name": PERSON_NAME,
                "person_age": PERSON_AGE,
                "person_id": PERSON_ID,
                "lat": lat,
                "lon": lon,
                "gps_fix": gps_fix,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._on_fall_callback(fall_info)

    def is_fall_detected(self):
        """Check if a fall was recently detected."""
        return self._fall_detected

    def clear_fall(self):
        """Clear fall flag and stop alert."""
        self._fall_detected = False
        self.alert_off()
        print("Fall alert cleared.")

    # =================== Data Getters ===================

    def get_data(self):
        """Get latest sensor data."""
        with self._lock:
            return self.latest_data.copy()

    def get_gps(self):
        """Get latest GPS coordinates."""
        data = self.get_data()
        if data.get("gps", False):
            return data.get("lat", 0), data.get("lon", 0)
        return None, None

    def get_telegram_message(self):
        """Get formatted sensor data for Telegram."""
        data = self.get_data()
        if not data:
            return None

        lines = ["📊 *Sensor Data*", ""]
        
        # Distance
        dist = data.get("d", -1)
        if dist > 0:
            lines.append(f"📏 Distance: *{dist:.1f} cm*")
        else:
            lines.append("📏 Distance: *Out of range*")

        # Acceleration (in g)
        ax = data.get("ax", 0) / LSB_PER_G
        ay = data.get("ay", 0) / LSB_PER_G
        az = data.get("az", 0) / LSB_PER_G
        total_g = math.sqrt(ax**2 + ay**2 + az**2)
        lines.append(f"📐 Acceleration: *{total_g:.2f}g*")

        # GPS
        if data.get("gps", False):
            lat = data.get("lat", 0)
            lon = data.get("lon", 0)
            lines.append(f"📍 Location: *{lat:.6f}, {lon:.6f}*")
        else:
            lines.append("📍 GPS: *No Signal*")

        # Status
        buz = "🔔" if data.get("buz", 0) else "🔕"
        vib = "📳" if data.get("vib", 0) else "📴"
        lines.append(f"Buzzer: {buz} | Vibration: {vib}")

        lines.append("")
        lines.append(f"👤 {PERSON_NAME}")
        lines.append(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(lines)
