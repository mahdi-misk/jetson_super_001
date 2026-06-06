#!/bin/bash
# ============================================================
# RoadVision-AI Autostart Installer
# Run this script ONCE to enable auto-start on boot
# Usage: sudo bash scripts/install_autostart.sh
# ============================================================

set -e

SERVICE_FILE="/home/mahdi/jetson_super_001/roadvision.service"
SERVICE_NAME="roadvision.service"

echo "=========================================="
echo "  RoadVision-AI Autostart Installer"
echo "=========================================="

# 1. Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run with sudo: sudo bash scripts/install_autostart.sh"
    exit 1
fi

# 2. Enable lingering for user mahdi (keeps user services running without login)
echo "[1/6] Enabling user lingering for mahdi..."
loginctl enable-linger mahdi 2>/dev/null || true

# 3. Ensure PulseAudio starts for the user on boot
echo "[2/6] Ensuring PulseAudio auto-starts for user mahdi..."
sudo -u mahdi bash -c 'systemctl --user enable pulseaudio.service 2>/dev/null || true'
sudo -u mahdi bash -c 'systemctl --user enable pulseaudio.socket 2>/dev/null || true'

# 4. Copy service file to systemd
echo "[3/6] Installing systemd service..."
cp "$SERVICE_FILE" /etc/systemd/system/"$SERVICE_NAME"

# 5. Reload systemd and enable service
echo "[4/6] Enabling service for auto-start..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# 6. Create log file with correct permissions
echo "[5/6] Setting up log file..."
touch /var/log/roadvision.log
chown mahdi:mahdi /var/log/roadvision.log

# 7. Start the service now
echo "[6/6] Starting service..."
systemctl start "$SERVICE_NAME"

echo ""
echo "=========================================="
echo "  ✅ Installation Complete!"
echo "=========================================="
echo ""
echo "The app will now auto-start every time the Jetson boots."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status roadvision    # Check status"
echo "  sudo journalctl -u roadvision -f    # Live logs (systemd)"
echo "  tail -f /var/log/roadvision.log     # Live logs (app)"
echo "  sudo systemctl restart roadvision   # Restart"
echo "  sudo systemctl stop roadvision      # Stop"
echo "  sudo systemctl disable roadvision   # Disable auto-start"
echo ""
