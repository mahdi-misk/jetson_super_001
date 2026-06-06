#!/bin/bash
# Captive Portal Setup Script
# Run this once with sudo to redirect port 80 to 5000 for automatic captive portal popups.

echo "Setting up Captive Portal iptables rules..."

# Redirect port 80 to 5000
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 5000

# Install iptables-persistent to save the rules across reboots (if not already installed)
echo "Installing iptables-persistent to save rules..."
export DEBIAN_FRONTEND=noninteractive
sudo apt-get install -y iptables-persistent netfilter-persistent

# Save rules
sudo netfilter-persistent save

echo "----------------------------------------"
echo "Done! Port 80 is now redirecting to 5000."
echo "When the Jetson hotspot starts, connecting to it should automatically pop up the setup page."
