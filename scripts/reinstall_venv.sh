#!/bin/bash
set -e

echo "========================================="
echo "🗑️ Removing old virtual environment..."
echo "========================================="
rm -rf .venv

echo "========================================="
echo "🌱 Creating new virtual environment..."
echo "========================================="
python3 -m venv .venv
source .venv/bin/activate

echo "========================================="
echo "📦 Installing base dependencies..."
echo "========================================="
pip install --upgrade pip
pip install -r requirements-base.txt

echo "========================================="
echo "🚀 Installing ONNX Runtime GPU and Ultralytics..."
echo "========================================="
# Install Ultralytics (pulls torch from PyPI, but we use ONNX/TensorRT for inference so CPU torch is fine)
pip install ultralytics
pip install onnxruntime-gpu timm tqdm psutil py-cpuinfo pandas requests seaborn

echo "========================================="
echo "✅ Environment setup complete!"
echo "========================================="
