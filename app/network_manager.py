import subprocess
import time
import json
import re

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

def start_hotspot():
    """Start an open Wi-Fi hotspot named Jetson-Setup."""
    try:
        # Check if Hotspot connection already exists
        output = subprocess.check_output(["nmcli", "-t", "-f", "NAME", "con", "show"]).decode()
        if "Jetson-Setup" in output:
            print("Bringing up existing Jetson-Setup hotspot...")
            subprocess.run(["nmcli", "con", "up", "Jetson-Setup"], check=True)
            return True
        
        print("Creating new open Hotspot Jetson-Setup...")
        # Create new open AP connection
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
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to start hotspot: {e}")
        return False

def stop_hotspot():
    """Stop the Hotspot connection if running."""
    try:
        subprocess.run(["nmcli", "con", "down", "Jetson-Setup"], check=True)
    except Exception:
        pass

def scan_wifi():
    """Scan for available Wi-Fi networks and return a list of dicts."""
    try:
        # Force a rescan first (might require root, but we'll try without it)
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], stderr=subprocess.DEVNULL)
        time.sleep(2) # Give it time to scan
        
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
                # Filter out empty SSIDs and our own hotspot
                if not ssid or ssid == "--" or ssid == "Jetson-Setup":
                    continue
                
                if ssid not in seen_ssids:
                    seen_ssids.add(ssid)
                    networks.append({
                        "ssid": ssid,
                        "signal": parts[1],
                        "security": parts[2] if parts[2] != "--" else "Open"
                    })
        
        # Sort by signal strength
        networks.sort(key=lambda x: int(x["signal"]) if x["signal"].isdigit() else 0, reverse=True)
        return networks
    except Exception as e:
        print(f"Error scanning Wi-Fi: {e}")
        return []

def connect_wifi(ssid, password=None):
    """Connect to a Wi-Fi network."""
    try:
        # Stop hotspot first if it's running so wlan0 is free
        stop_hotspot()
        time.sleep(1)
        
        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])
            
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return {"success": True, "message": f"تم الاتصال بنجاح بشبكة {ssid}"}
        else:
            return {"success": False, "message": f"فشل الاتصال: {result.stderr or result.stdout}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

if __name__ == "__main__":
    # Test script functionality
    print("Internet:", check_internet())
    print("Networks:", scan_wifi())
