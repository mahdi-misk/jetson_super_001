import subprocess
import time
import re

def scan_devices(duration=5):
    """Scan for Bluetooth devices for a specified duration."""
    try:
        # Turn on bluetooth if it's off
        subprocess.run(["bluetoothctl", "power", "on"], check=True, stdout=subprocess.DEVNULL)
        
        # Start scanning
        scan_process = subprocess.Popen(["bluetoothctl", "scan", "on"], stdout=subprocess.DEVNULL)
        time.sleep(duration)
        
        # Stop scanning
        scan_process.terminate()
        subprocess.run(["bluetoothctl", "scan", "off"], stdout=subprocess.DEVNULL)
        
        # Get list of devices
        output = subprocess.check_output(["bluetoothctl", "devices"], universal_newlines=True)
        
        devices = []
        for line in output.strip().split('\n'):
            if not line:
                continue
            
            # Line format: Device MAC_ADDRESS Name
            parts = line.split(" ", 2)
            if len(parts) >= 3 and parts[0] == "Device":
                mac = parts[1]
                name = parts[2]
                # Try to get connected status
                info_output = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True).stdout
                connected = "Connected: yes" in info_output
                paired = "Paired: yes" in info_output
                
                devices.append({
                    "mac": mac,
                    "name": name.replace("-", " "), # Clean up names sometimes having dashes
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
        
        # Turn on bluetooth and agent
        subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "agent", "on"], stdout=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "default-agent"], stdout=subprocess.DEVNULL)
        
        # Remove if previously paired to ensure fresh connection (optional)
        # subprocess.run(["bluetoothctl", "remove", mac_address], stdout=subprocess.DEVNULL)
        
        # Pair
        pair_res = subprocess.run(["bluetoothctl", "pair", mac_address], capture_output=True, text=True)
        time.sleep(2) # Give it time
        
        # Trust
        subprocess.run(["bluetoothctl", "trust", mac_address], stdout=subprocess.DEVNULL)
        
        # Connect
        conn_res = subprocess.run(["bluetoothctl", "connect", mac_address], capture_output=True, text=True)
        
        if "Connection successful" in conn_res.stdout or "successful" in conn_res.stdout.lower():
            return {"success": True, "message": "تم الاقتران والاتصال بنجاح!"}
        elif "Failed" in conn_res.stdout:
            # Check if it was already connected
            info = subprocess.run(["bluetoothctl", "info", mac_address], capture_output=True, text=True).stdout
            if "Connected: yes" in info:
                return {"success": True, "message": "تم الاتصال مسبقاً بنجاح!"}
            return {"success": False, "message": f"فشل الاتصال: {conn_res.stdout.strip()}"}
        else:
            return {"success": True, "message": "تم إرسال أمر الاتصال."}
            
    except Exception as e:
        return {"success": False, "message": str(e)}

if __name__ == "__main__":
    # Test script functionality
    print("Scanning Bluetooth devices for 3 seconds...")
    devices = scan_devices(3)
    for d in devices:
        print(f"{d['name']} ({d['mac']}) - Connected: {d['connected']}")
