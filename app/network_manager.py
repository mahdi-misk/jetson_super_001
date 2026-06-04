import subprocess
import time
import json
import os
import threading

try:
    from app.event_logger import log_event
except ImportError:
    def log_event(cat, msg, level="info"):
        print(f"[{level}] {cat}: {msg}")

LAST_WIFI_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "last_wifi.json")

# Shared state for dashboard widgets
connection_state = {
    "internet": False,
    "hotspot_active": False,
    "current_ssid": "",
    "ip_address": "",
}

_monitor_thread = None
_monitor_running = False

def check_internet(host="8.8.8.8", timeout=3):
    """Check if there is an active internet connection by pinging."""
    try:
        subprocess.check_output(
            ["ping", "-c", "1", "-W", str(timeout), host],
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def get_current_ssid():
    """Get the currently connected Wi-Fi SSID."""
    try:
        output = subprocess.check_output(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            universal_newlines=True
        )
        for line in output.strip().split('\n'):
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except Exception:
        pass
    return ""

def get_ip_address():
    """Get the current IP address of wlan0."""
    try:
        output = subprocess.check_output(
            ["hostname", "-I"],
            universal_newlines=True
        ).strip()
        if output:
            return output.split()[0]
    except Exception:
        pass
    return "N/A"

def is_hotspot_active():
    """Check if Jetson-Setup hotspot is currently active."""
    try:
        output = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,STATE", "con", "show", "--active"],
            universal_newlines=True
        )
        for line in output.strip().split('\n'):
            if "Jetson-Setup" in line and "activated" in line.lower():
                return True
    except Exception:
        pass
    return False

def _update_state():
    """Update the shared connection state."""
    connection_state["internet"] = check_internet()
    connection_state["hotspot_active"] = is_hotspot_active()
    connection_state["current_ssid"] = get_current_ssid()
    connection_state["ip_address"] = get_ip_address()

def start_hotspot():
    """Start an open Wi-Fi hotspot named Jetson-Setup."""
    try:
        # Check if Hotspot connection already exists
        output = subprocess.check_output(["nmcli", "-t", "-f", "NAME", "con", "show"]).decode()
        if "Jetson-Setup" in output:
            print("Bringing up existing Jetson-Setup hotspot...")
            subprocess.run(["nmcli", "con", "up", "Jetson-Setup"], check=True)
        else:
            print("Creating new open Hotspot Jetson-Setup...")
            subprocess.run([
                "nmcli", "con", "add", "type", "wifi", "ifname", "wlan0",
                "con-name", "Jetson-Setup", "autoconnect", "no", "ssid", "Jetson-Setup"
            ], check=True)
            
            subprocess.run([
                "nmcli", "con", "modify", "Jetson-Setup",
                "802-11-wireless.mode", "ap",
                "802-11-wireless.band", "bg",
                "ipv4.method", "shared"
            ], check=True)
            
            subprocess.run(["nmcli", "con", "up", "Jetson-Setup"], check=True)
        
        connection_state["hotspot_active"] = True
        log_event("network", "تم تشغيل نقطة الاتصال Jetson-Setup", "success")
        return True
    except subprocess.CalledProcessError as e:
        log_event("network", f"فشل تشغيل نقطة الاتصال: {e}", "error")
        print(f"Failed to start hotspot: {e}")
        return False

def stop_hotspot():
    """Stop the Hotspot connection if running."""
    try:
        subprocess.run(["nmcli", "con", "down", "Jetson-Setup"], check=True)
        connection_state["hotspot_active"] = False
        log_event("network", "تم إيقاف نقطة الاتصال", "info")
    except Exception:
        pass

def save_last_wifi(ssid, password=None):
    """Save last successful Wi-Fi credentials."""
    try:
        data = {"ssid": ssid, "password": password or ""}
        with open(LAST_WIFI_FILE, "w") as f:
            json.dump(data, f)
    except IOError:
        pass

def load_last_wifi():
    """Load last successful Wi-Fi credentials."""
    if os.path.exists(LAST_WIFI_FILE):
        try:
            with open(LAST_WIFI_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None

def try_last_wifi():
    """Try to connect to the last known Wi-Fi network."""
    last = load_last_wifi()
    if last:
        ssid = last.get("ssid")
        password = last.get("password")
        if ssid:
            print(f"Trying last known Wi-Fi: {ssid}...")
            log_event("network", f"محاولة الاتصال بآخر شبكة: {ssid}", "info")
            result = connect_wifi(ssid, password if password else None, save=False)
            if result.get("success"):
                log_event("network", f"تم الاتصال بآخر شبكة محفوظة: {ssid}", "success")
                return True
            else:
                log_event("network", f"فشل الاتصال بآخر شبكة: {ssid}", "warning")
    return False

def scan_wifi():
    """Scan for available Wi-Fi networks and return a list of dicts."""
    try:
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], stderr=subprocess.DEVNULL)
        time.sleep(2)
        
        output = subprocess.check_output(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            universal_newlines=True
        )
        
        networks = []
        seen_ssids = set()
        
        for line in output.strip().split('\n'):
            parts = line.split(':')
            if len(parts) >= 3:
                ssid = parts[0]
                if not ssid or ssid == "--" or ssid == "Jetson-Setup":
                    continue
                
                if ssid not in seen_ssids:
                    seen_ssids.add(ssid)
                    networks.append({
                        "ssid": ssid,
                        "signal": parts[1],
                        "security": parts[2] if parts[2] != "--" else "Open"
                    })
        
        networks.sort(key=lambda x: int(x["signal"]) if x["signal"].isdigit() else 0, reverse=True)
        return networks
    except Exception as e:
        print(f"Error scanning Wi-Fi: {e}")
        return []

def connect_wifi(ssid, password=None, save=True):
    """Connect to a Wi-Fi network."""
    try:
        stop_hotspot()
        time.sleep(1)
        
        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])
            
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            if save:
                save_last_wifi(ssid, password)
            log_event("network", f"تم الاتصال بشبكة {ssid}", "success")
            _update_state()
            return {"success": True, "message": f"تم الاتصال بنجاح بشبكة {ssid}"}
        else:
            log_event("network", f"فشل الاتصال بشبكة {ssid}: {result.stderr or result.stdout}", "error")
            return {"success": False, "message": f"فشل الاتصال: {result.stderr or result.stdout}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def _monitor_loop(check_interval=30):
    """Background thread that periodically checks internet and auto-recovers."""
    global _monitor_running
    _monitor_running = True
    was_connected = check_internet()
    
    while _monitor_running:
        time.sleep(check_interval)
        if not _monitor_running:
            break
        
        currently_connected = check_internet()
        _update_state()
        
        # Lost internet
        if was_connected and not currently_connected:
            log_event("network", "انقطع الاتصال بالإنترنت!", "warning")
            print("[Auto-Recovery] Internet lost! Starting hotspot...")
            start_hotspot()
        
        # Regained internet
        elif not was_connected and currently_connected:
            log_event("network", "تم استعادة الاتصال بالإنترنت!", "success")
            print("[Auto-Recovery] Internet restored!")
            if is_hotspot_active():
                stop_hotspot()
        
        was_connected = currently_connected

def start_monitor(check_interval=30):
    """Start the background internet monitor thread."""
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _update_state()
    _monitor_thread = threading.Thread(target=_monitor_loop, args=(check_interval,), daemon=True)
    _monitor_thread.start()
    log_event("system", "تم تشغيل مراقب الاتصال التلقائي", "info")
    print("[Auto-Recovery] Monitor started.")

def stop_monitor():
    """Stop the background internet monitor."""
    global _monitor_running
    _monitor_running = False

if __name__ == "__main__":
    print("Internet:", check_internet())
    print("Current SSID:", get_current_ssid())
    print("IP:", get_ip_address())
    print("Networks:", scan_wifi())
