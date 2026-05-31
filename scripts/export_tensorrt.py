import os
from ultralytics import YOLO

def export_to_tensorrt(model_path, half_precision=True):
    print(f"Loading {model_path}...")
    if not os.path.exists(model_path):
        # Fallback for default models like yolov8n.pt which might download
        print(f"Note: {model_path} might be downloaded automatically if not found locally.")
        
    model = YOLO(model_path)
    print(f"Exporting {model_path} to TensorRT...")
    # half=True for FP16 optimization which is much faster on Jetson
    # dynamic=False is often safer for TensorRT if input sizes are fixed
    model.export(format="engine", half=half_precision, device=0)
    print("Export complete!\n")

if __name__ == "__main__":
    print("--- Starting TensorRT Export process for NVIDIA Jetson ---")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    pothole_path = os.path.join(base_dir, "models", "pothole", "pothole_yolov8_final.pt")
    stairs_path = os.path.join(base_dir, "models", "stairs", "stairs_yolov8_final.pt")
    obstacle_path = "yolov8n.pt" 
    
    export_to_tensorrt(pothole_path, half_precision=True)
    export_to_tensorrt(stairs_path, half_precision=True)
    export_to_tensorrt(obstacle_path, half_precision=True)
    
    print("All models exported to TensorRT (.engine) format!")
