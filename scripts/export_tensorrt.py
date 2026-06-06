#!/usr/bin/env python3
import os
import sys

# Ensure YOLO can be loaded
from ultralytics import YOLO

def export_models():
    print("=========================================")
    print("🚀 TensorRT Export Script for RoadVision")
    print("=========================================")
    
    # 1. Obstacle Model
    try:
        print("\n[1/3] Exporting Obstacle Model (yolov8n.pt)...")
        if os.path.exists("yolov8n.pt"):
            model_obs = YOLO("yolov8n.pt")
            # Export to TensorRT with half-precision (FP16) for max speed
            model_obs.export(format="engine", device=0, half=True, workspace=1)
            print("✅ Obstacle Model exported successfully!")
        else:
            print("⚠️ yolov8n.pt not found. Skipping.")
    except Exception as e:
        print(f"❌ Failed to export yolov8n.pt: {e}")

    # 2. Pothole Model
    try:
        print("\n[2/3] Exporting Pothole Model (best.pt)...")
        if os.path.exists("best.pt"):
            model_pot = YOLO("best.pt")
            model_pot.export(format="engine", device=0, half=True, workspace=1)
            print("✅ Pothole Model exported successfully!")
        else:
            print("⚠️ best.pt not found. Skipping.")
    except Exception as e:
        print(f"❌ Failed to export best.pt: {e}")

    # 3. Stairs Model
    try:
        print("\n[3/3] Exporting Stairs Model (models/stairs/stairs_yolov8.pt)...")
        stairs_path = "models/stairs/stairs_yolov8.pt"
        if os.path.exists(stairs_path):
            model_stairs = YOLO(stairs_path)
            model_stairs.export(format="engine", device=0, half=True, workspace=1)
            print("✅ Stairs Model exported successfully!")
        else:
            print(f"⚠️ {stairs_path} not found. Skipping.")
    except Exception as e:
        print(f"❌ Failed to export stairs_yolov8.pt: {e}")

    print("\n=========================================")
    print("🎉 All exports completed!")
    print("The system will now automatically use the .engine models for maximum speed.")
    print("=========================================")

if __name__ == "__main__":
    export_models()
