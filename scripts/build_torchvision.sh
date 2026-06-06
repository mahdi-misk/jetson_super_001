#!/bin/bash
set -e

echo "========================================="
echo "🛠️ Building Torchvision from Source"
echo "========================================="

echo "[1/3] Installing dependencies..."
sudo apt-get update
sudo apt-get install -y libjpeg-dev zlib1g-dev libpython3-dev libopenblas-dev libavcodec-dev libavformat-dev libswscale-dev

echo "[2/3] Cloning Torchvision v0.20.0..."
cd /home/mahdi/jetson_super_001
if [ -d "torchvision_src" ]; then
    rm -rf torchvision_src
fi
git clone --branch v0.20.0 https://github.com/pytorch/vision torchvision_src
cd torchvision_src

echo "[3/3] Building Torchvision (This will take 10-20 minutes)..."
export BUILD_VERSION=0.20.0
export MAX_JOBS=1
export LD_LIBRARY_PATH=/home/mahdi/.local/lib/python3.10/site-packages/nvidia/cusparselt/lib:$LD_LIBRARY_PATH
export CUDACXX=/usr/local/cuda/bin/nvcc
python3 setup.py install --user

echo "========================================="
echo "✅ Torchvision built and installed successfully!"
echo "========================================="
