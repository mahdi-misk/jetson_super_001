import cv2
import torch
import numpy as np
import os
from ultralytics import YOLO

class RoadVisionEngine:
    def __init__(self, pothole_model_path="models/pothole/pothole_yolov8_final.pt",
                       stairs_model_path="models/stairs/stairs_handrail.pt",
                       obstacle_model_path="yolov8n.pt"):
        print("Initializing RoadVision Engine (YOLO + MiDaS)...")
        
        def get_best_model_path(base_path):
            if base_path.endswith('.pt'):
                engine_path = base_path.replace('.pt', '.engine')
                if os.path.exists(engine_path):
                    print(f"🚀 Found optimized TensorRT engine: {engine_path}")
                    return engine_path
            return base_path

        pothole_model_path = get_best_model_path(pothole_model_path)
        stairs_model_path = get_best_model_path(stairs_model_path)
        obstacle_model_path = get_best_model_path(obstacle_model_path)
        
        # Load YOLO models
        try:
            print(f"Loading Pothole model: {pothole_model_path}")
            self.pothole_model = YOLO(pothole_model_path)
            
            print(f"Loading Stairs model: {stairs_model_path}")
            self.stairs_model = YOLO(stairs_model_path)
            
            print(f"Loading General Obstacle model: {obstacle_model_path}")
            self.obstacle_model = YOLO(obstacle_model_path)
        except Exception as e:
            print(f"Error loading YOLO models: {e}")
            self.pothole_model = None

        if self.pothole_model:
            # Load MiDaS
            print("Loading MiDaS Depth Estimation model...")
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            
            # Use local cache for offline execution
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_dir = os.path.join(base_dir, "models", "torch_hub_cache")
            if os.path.exists(cache_dir):
                torch.hub.set_dir(cache_dir)
                
            self.midas = torch.hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
            self.midas.to(self.device)
            self.midas.eval()
            
            midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
            self.transform = midas_transforms.small_transform
            
            print("✅ RoadVision Engine is Ready!")

    def detect(self, frame):
        """
        Runs object detection and depth estimation.
        Returns a list of dictionaries with 'label', 'confidence', 'bbox', 'distance', 'state', 'color'.
        """
        if not self.pothole_model:
            return []

        # 1. Depth Map Generation
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        input_batch = self.transform(img_rgb).to(self.device)

        with torch.no_grad():
            prediction = self.midas(input_batch)
            prediction = torch.nn.functional.interpolate(
                prediction.unsqueeze(1),
                size=img_rgb.shape[:2],
                mode="bicubic",
                align_corners=False,
            ).squeeze()
        
        depth_map = prediction.cpu().numpy()
        
        all_detections = []

        # Helper to process YOLO results
        def process_results(results, is_hazard=False):
            for box in results[0].boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = results[0].names[cls_id]

                # Bounding box depth
                bx1, by1 = max(0, x1), max(0, y1)
                bx2, by2 = min(depth_map.shape[1], x2), min(depth_map.shape[0], y2)
                box_depth_values = depth_map[by1:by2, bx1:bx2]
                
                if box_depth_values.size == 0:
                    continue
                
                median_inverse_depth = np.median(box_depth_values)
                simulated_distance = 5000.0 / median_inverse_depth if median_inverse_depth > 0 else 99.9

                # Determine Safety State
                if simulated_distance > 5.0:
                    state = "SAFE"
                    color = (0, 255, 0) # Green
                elif 2.0 <= simulated_distance <= 5.0:
                    state = "WARNING"
                    color = (0, 255, 255) # Yellow
                else:
                    state = "DANGER"
                    color = (0, 0, 255) # Red

                all_detections.append({
                    "label": label,
                    "confidence": conf,
                    "bbox": [x1, y1, x2, y2],
                    "distance": simulated_distance,
                    "state": state,
                    "color": color,
                    "is_hazard": is_hazard # Flag for critical objects like potholes/stairs
                })

        # 2. Run YOLO Inferences
        pothole_results = self.pothole_model.predict(source=frame, conf=0.5, verbose=False)
        stairs_results = self.stairs_model.predict(source=frame, conf=0.5, verbose=False)
        obstacle_results = self.obstacle_model.predict(source=frame, conf=0.6, verbose=False)

        process_results(pothole_results, is_hazard=True)
        process_results(stairs_results, is_hazard=True)
        process_results(obstacle_results, is_hazard=False)

        return all_detections
