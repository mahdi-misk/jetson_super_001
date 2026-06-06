import cv2
import numpy as np
import os
from collections import deque
from ultralytics import YOLO
import onnxruntime as ort

class RoadVisionEngine:
    def __init__(self, pothole_model_path="best.pt",
                       stairs_model_path="models/stairs/stairs_yolov8.pt",
                       obstacle_model_path="yolov8n.pt"):
        print("Initializing RoadVision Engine (YOLO + MiDaS)...")
        
        def get_best_model_path(base_path):
            engine_path = base_path.replace('.pt', '.engine').replace('.onnx', '.engine')
            if os.path.exists(engine_path):
                print(f"🚀 Found optimized TensorRT engine: {engine_path}")
                return engine_path
            
            onnx_path = base_path.replace('.pt', '.onnx')
            if os.path.exists(onnx_path):
                print(f"✅ Found ONNX model: {onnx_path}")
                return onnx_path
                
            return base_path

        pothole_model_path = get_best_model_path(pothole_model_path)
        stairs_model_path = get_best_model_path(stairs_model_path)
        obstacle_model_path = get_best_model_path(obstacle_model_path)
        
        # Load YOLO models
        try:
            print(f"Loading Pothole model: {pothole_model_path}")
            self.pothole_model = YOLO(pothole_model_path, task='detect')
            
            print(f"Loading Stairs model: {stairs_model_path}")
            self.stairs_model = YOLO(stairs_model_path, task='detect')
            
            print(f"Loading General Obstacle model: {obstacle_model_path}")
            self.obstacle_model = YOLO(obstacle_model_path, task='detect')
        except Exception as e:
            print(f"Error loading YOLO models: {e}")
            self.pothole_model = None

        if self.pothole_model:
            # Load MiDaS via ONNX Runtime (10x faster than PyTorch CPU)
            print("Loading MiDaS Depth Estimation model (ONNX Runtime)...")
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            midas_onnx_path = os.path.join(base_dir, "models", "midas", "midas_small.onnx")
            
            # Pick the best available provider (GPU > CPU)
            available = ort.get_available_providers()
            providers = []
            if "CUDAExecutionProvider" in available:
                providers.append("CUDAExecutionProvider")
                print("  ⚡ Using CUDA GPU for MiDaS")
            if "TensorrtExecutionProvider" in available:
                providers.insert(0, "TensorrtExecutionProvider")
                print("  🚀 Using TensorRT for MiDaS")
            providers.append("CPUExecutionProvider")
            
            self.midas_session = ort.InferenceSession(midas_onnx_path, providers=providers)
            self.midas_input_name = self.midas_session.get_inputs()[0].name
            active_provider = self.midas_session.get_providers()[0]
            print(f"  MiDaS running on: {active_provider}")
            
            print("✅ RoadVision Engine is Ready!")

        # --- Severity Stabilisation ---
        # Maps track_id -> deque of recent severity strings (last SEVERITY_WINDOW frames)
        self.SEVERITY_WINDOW = 7
        self._severity_history = {}   # {track_id: deque(["عميقة", "عميقة", ...])}
        self._active_track_ids = set()  # track IDs seen this frame (for cleanup)

    def detect(self, frame):
        """
        Runs object detection and depth estimation.
        Returns a list of dictionaries with 'label', 'confidence', 'bbox', 'distance', 'state', 'color'.
        """
        if not self.pothole_model:
            return []

        # 1. Depth Map Generation (ONNX Runtime — no PyTorch needed)
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # MiDaS small expects 384x384 input, normalized with ImageNet stats
        resized = cv2.resize(img_rgb, (384, 384), interpolation=cv2.INTER_CUBIC)
        input_arr = resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        input_arr = (input_arr - mean) / std
        input_arr = input_arr.transpose(2, 0, 1)[np.newaxis]  # NCHW

        depth_out = self.midas_session.run(None, {self.midas_input_name: input_arr})[0]
        # depth_out shape: (1, 384, 384) — resize back to original frame size
        depth_map = cv2.resize(depth_out.squeeze(), (img_rgb.shape[1], img_rgb.shape[0]), interpolation=cv2.INTER_CUBIC)
        
        all_detections = []

        # Helper to process YOLO results
        self._active_track_ids.clear()
        def process_results(results, is_hazard=False):
            for box in results[0].boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = results[0].names[cls_id]

                # Extract track ID (assigned by YOLO tracker, None if not available)
                track_id = int(box.id[0]) if box.id is not None else None
                if track_id is not None:
                    self._active_track_ids.add(track_id)

                # Specific confidence threshold for handrail
                if label == "handrail" and conf < 0.80:
                    continue

                # Bounding box depth
                bx1, by1 = max(0, x1), max(0, y1)
                bx2, by2 = min(depth_map.shape[1], x2), min(depth_map.shape[0], y2)
                box_depth_values = depth_map[by1:by2, bx1:bx2]
                
                if box_depth_values.size == 0:
                    continue
                
                from app import config
                
                # Use median for general distance estimation
                median_inverse_depth = np.median(box_depth_values)
                simulated_distance = config.DEPTH_SCALE_FACTOR / median_inverse_depth if median_inverse_depth > 0 else 99.9

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

                severity_ar = ""

                all_detections.append({
                    "label": label,
                    "confidence": conf,
                    "bbox": [x1, y1, x2, y2],
                    "distance": simulated_distance,
                    "state": state,
                    "color": color,
                    "severity_ar": severity_ar,
                    "is_hazard": is_hazard # Flag for critical objects like potholes/stairs
                })

        # 2. Run YOLO Inferences (using tracking for stability)
        pothole_results = self.pothole_model.track(source=frame, conf=0.45, persist=True, verbose=False, device='cpu')
        stairs_results = self.stairs_model.track(source=frame, conf=0.45, persist=True, verbose=False, device='cpu')
        obstacle_results = self.obstacle_model.track(source=frame, conf=0.45, persist=True, verbose=False, device='cpu')

        process_results(pothole_results, is_hazard=True)
        process_results(stairs_results, is_hazard=True)
        process_results(obstacle_results, is_hazard=False)

        # Prune severity history for tracks no longer visible
        stale_ids = set(self._severity_history.keys()) - self._active_track_ids
        for sid in stale_ids:
            del self._severity_history[sid]

        # 3. Wall Detection (Heuristic based on Depth Map)
        # Only warn about a wall when it is truly close and dangerous (< 2 metres).
        # Check a central ROI in the middle-lower half (avoids sky false positives)
        height, width = depth_map.shape
        roi_x1 = int(width * 0.25)
        roi_x2 = int(width * 0.75)
        roi_y1 = int(height * 0.30)
        roi_y2 = int(height * 0.75)
        
        wall_depth_values = depth_map[roi_y1:roi_y2, roi_x1:roi_x2]
        if wall_depth_values.size > 0:
            median_inverse_depth = np.median(wall_depth_values)
            std_depth = float(np.std(wall_depth_values))
            
            from app import config
            simulated_distance = config.DEPTH_SCALE_FACTOR / median_inverse_depth if median_inverse_depth > 0 else 99.9
            
            # Relative standard deviation to measure "flatness"
            relative_std = std_depth / (median_inverse_depth + 1e-6)
            
            # Only trigger wall alert when VERY close (< 2 m) AND flat surface detected
            if simulated_distance < 2.0 and relative_std < 0.15:
                # Calculate safe direction based on depth on the sides
                left_roi = depth_map[roi_y1:roi_y2, 0:roi_x1]
                right_roi = depth_map[roi_y1:roi_y2, roi_x2:width]
                
                left_median = np.median(left_roi) if left_roi.size > 0 else 99.9
                right_median = np.median(right_roi) if right_roi.size > 0 else 99.9
                
                # smaller inverse depth means further away
                safe_dir = "يساراً" if left_median < right_median else "يميناً"

                # At this threshold the wall is always DANGER
                state = "DANGER"
                color = (0, 0, 255) # Red
                    
                all_detections.append({
                    "label": "wall",
                    "confidence": max(0.4, 1.0 - (relative_std * 5)), # Pseudo-confidence
                    "bbox": [roi_x1, roi_y1, roi_x2, roi_y2],
                    "distance": simulated_distance,
                    "state": state,
                    "color": color,
                    "severity_ar": "جدار مسطح",
                    "safe_dir": safe_dir,
                    "is_hazard": False
                })

        return all_detections
