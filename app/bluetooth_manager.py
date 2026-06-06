import subprocess
import time

try:
    from app.event_logger import log_event
except ImportError:
    def log_event(cat, msg, level="info"):
        print(f"[{level}] {cat}: {msg}")

def scan_devices(duration=5):
    """Scan for Bluetooth devices for a specified duration."""
    try:
        subprocess.run(["bluetoothctl", "power", "on"], check=True, stdout=subprocess.DEVNULL)
        
        scan_process = subprocess.Popen(["bluetoothctl", "scan", "on"], stdout=subprocess.DEVNULL)
        time.sleep(duration)
        
        scan_process.terminate()
        subprocess.run(["bluetoothctl", "scan", "off"], stdout=subprocess.DEVNULL)
        
        output = subprocess.check_output(["bluetoothctl", "devices"], universal_newlines=True)
        
        devices = []
        for line in output.strip().split('\n'):
            if not line:
                continue
            
            parts = line.split(" ", 2)
            if len(parts) >= 3 and parts[0] == "Device":
                mac = parts[1]
                name = parts[2]
                info_output = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True).stdout
                connected = "Connected: yes" in info_output
                paired = "Paired: yes" in info_output
                
                devices.append({
                    "mac": mac,
                    "name": name,
                    "connected": connected,
                    "paired": paired
                })
        
        return devices
    except Exception as e:
        print(f"Error scanning bluetooth devices: {e}")
        return []

def pair_and_connect(mac_address):
    """Pair, trust, and connect to a Bluetooth device (Just Works)."""
    try:
        print(f"Attempting to pair and connect to {mac_address}...")
        
        subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "agent", "on"], stdout=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "default-agent"], stdout=subprocess.DEVNULL)
        
        subprocess.run(["bluetoothctl", "pair", mac_address], capture_output=True, text=True)
        time.sleep(2)
        
        subprocess.run(["bluetoothctl", "trust", mac_address], stdout=subprocess.DEVNULL)
        
        conn_res = subprocess.run(["bluetoothctl", "connect", mac_address], capture_output=True, text=True)
        
        if "Connection successful" in conn_res.stdout or "successful" in conn_res.stdout.lower():
            log_event("bluetooth", f"تم الاتصال بجهاز {mac_address}", "success")
            return {"success": True, "message": "تم الاقتران والاتصال بنجاح!"}
        elif "Failed" in conn_res.stdout:
            info = subprocess.run(["bluetoothctl", "info", mac_address], capture_output=True, text=True).stdout
            if "Connected: yes" in info:
                return {"success": True, "message": "تم الاتصال مسبقاً بنجاح!"}
            log_event("bluetooth", f"فشل الاتصال بجهاز {mac_address}", "error")
            return {"success": False, "message": f"فشل الاتصال: {conn_res.stdout.strip()}"}
        else:
            log_event("bluetooth", f"تم إرسال أمر الاتصال بجهاز {mac_address}", "info")
            return {"success": True, "message": "تم إرسال أمر الاتصال."}
            
    except Exception as e:
        return {"success": False, "message": str(e)}

def disconnect_device(mac_address):
    """Disconnect a Bluetooth device."""
    try:
        result = subprocess.run(["bluetoothctl", "disconnect", mac_address], capture_output=True, text=True)
        if "Successful" in result.stdout or "successful" in result.stdout.lower():
            log_event("bluetooth", f"تم فصل جهاز {mac_address}", "info")
            return {"success": True, "message": "تم فصل الجهاز بنجاح."}
        return {"success": False, "message": result.stdout.strip()}
    except Exception as e:
        return {"success": False, "message": str(e)}

if __name__ == "__main__":
    print("Scanning Bluetooth devices for 3 seconds...")
    devices = scan_devices(3)
    for d in devices:
        print(f"{d['name']} ({d['mac']}) - Connected: {d['connected']}")
