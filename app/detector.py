import cv2
import numpy as np
import os
import torch
from collections import deque
from ultralytics import YOLO
import onnxruntime as ort

from app import config

IGNORED_LABELS = {
    "boat", "airplane", "traffic light", "fire hydrant", "parking meter", 
    "bench", "toilet", "sink", "potted plant", "vase", "bed", "microwave", 
    "oven", "toaster", "suitcase", "umbrella", "tie", "hair drier", "scissors", 
    "toothbrush", "teddy bear", "horse", "sheep", "cow", "elephant", "bear", 
    "giraffe", "zebra", "sports ball", "tennis racket", "baseball bat", 
    "baseball glove", "skateboard", "snowboard", "skis", "surfboard", "kite", 
    "frisbee", "wine glass", "fork", "knife", "spoon", "bowl", "banana", 
    "apple", "orange", "carrot", "broccoli", "sandwich", "pizza", "hot dog", 
    "cake", "donut", "train", "clock"
}

class RoadVisionEngine:
    def __init__(self, pothole_model_path="best.pt",
                       stairs_model_path="models/stairs/stairs_yolov8.pt",
                       obstacle_model_path="yolov8n.pt"):
        print("Initializing RoadVision Engine (YOLO + MiDaS)...")
        print(f"  🔍 CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"  🔍 CUDA device: {torch.cuda.get_device_name(0)}")
        
        def get_best_model_path(base_path):
            # Priority: .engine (TensorRT, fastest) > .pt (PyTorch CUDA) > .onnx (fallback)
            # IMPORTANT: .pt is preferred over .onnx because YOLO's internal ONNX loader
            # does NOT use explicit CUDA providers, causing inference to run on CPU.
            # PyTorch .pt models with device=0 use CUDA directly.
            engine_path = base_path.replace('.pt', '.engine').replace('.onnx', '.engine')
            if os.path.exists(engine_path):
                print(f"🚀 Found optimized TensorRT engine: {engine_path}")
                return engine_path
            
            # Prefer .pt for proper PyTorch CUDA support
            if os.path.exists(base_path) and base_path.endswith('.pt'):
                print(f"✅ Using PyTorch model (CUDA-native): {base_path}")
                return base_path
            
            # ONNX as last resort (will run on CPU inside YOLO's internal runner)
            onnx_path = base_path.replace('.pt', '.onnx')
            if os.path.exists(onnx_path):
                print(f"⚠️ Using ONNX model (may not use GPU): {onnx_path}")
                return onnx_path
                
            return base_path

        pothole_model_path = get_best_model_path(pothole_model_path)
        stairs_model_path = get_best_model_path(stairs_model_path)
        obstacle_model_path = get_best_model_path(obstacle_model_path)
        
        self.pothole_model = None
        self.stairs_model = None
        self.obstacle_model = None
        self.midas_session = None
        self.midas_input_name = None
        self.models_loaded = False
        self._use_half = True  # Will fallback to False if FP16 causes errors
        
        def load_models_async():
            try:
                # --- Initialize CUDA context FIRST ---
                # cuBLAS needs a properly initialized context before fuse() works
                print("  🔧 Initializing CUDA context...")
                torch.cuda.init()
                torch.cuda.empty_cache()
                _warmup_tensor = torch.zeros(1, device='cuda')
                _ = _warmup_tensor + 1  # Force CUDA kernel compilation
                del _warmup_tensor
                torch.cuda.empty_cache()
                print(f"  ✅ CUDA context ready. Free memory: {torch.cuda.mem_get_info()[0] / 1024**2:.0f} MB")

                # --- Load YOLO models one at a time, move to GPU, clear cache ---
                def load_yolo_to_gpu(name, path):
                    print(f"Loading {name} model: {path}")
                    model = YOLO(path, task='detect')
                    model.to("cuda")
                    torch.cuda.empty_cache()
                    dev = next(model.model.parameters()).device
                    print(f"  ✅ {name} model device: {dev}")
                    return model

                self.pothole_model = load_yolo_to_gpu("Pothole", pothole_model_path)
                self.stairs_model = load_yolo_to_gpu("Stairs", stairs_model_path)
                self.obstacle_model = load_yolo_to_gpu("Obstacle", obstacle_model_path)

                print(f"  📊 GPU memory after loading: {torch.cuda.mem_get_info()[0] / 1024**2:.0f} MB free")

                # --- Warmup: trigger model fuse + first inference ---
                # Start with FP32 (safer), then test FP16
                print("  🔥 Warming up YOLO models on GPU...")
                dummy = np.zeros((480, 640, 3), dtype=np.uint8)

                # Warmup each model with FP32 first (triggers fuse safely)
                for name, model in [("Pothole", self.pothole_model),
                                     ("Stairs", self.stairs_model),
                                     ("Obstacle", self.obstacle_model)]:
                    try:
                        torch.cuda.empty_cache()
                        model.predict(source=dummy, device=0, half=False, verbose=False)
                        print(f"  ✅ {name} FP32 warmup OK")
                    except RuntimeError as e:
                        print(f"  ⚠️ {name} FP32 warmup failed: {e}")
                        torch.cuda.empty_cache()

                # Now test FP16 (half precision — faster on Jetson if supported)
                try:
                    torch.cuda.empty_cache()
                    self.pothole_model.predict(source=dummy, device=0, half=True, verbose=False)
                    self._use_half = True
                    print("  ✅ FP16 (half) test passed — will use half precision")
                except Exception as e:
                    self._use_half = False
                    print(f"  ⚠️ FP16 not supported: {e}")
                    print("  ↪ Using FP32 (half=False)")

            except Exception as e:
                print(f"Error loading YOLO models: {e}")
                import traceback
                traceback.print_exc()
                self.pothole_model = None

            if self.pothole_model:
                try:
                    print("Loading MiDaS Depth Estimation model (ONNX Runtime)...")
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    midas_onnx_path = os.path.join(base_dir, "models", "midas", "midas_small.onnx")
                    
                    # Build providers in priority order: TensorRT > CUDA > CPU
                    available = ort.get_available_providers()
                    print(f"  🔍 ONNX available providers: {available}")
                    providers = []
                    if "TensorrtExecutionProvider" in available:
                        providers.append("TensorrtExecutionProvider")
                        print("  🚀 Using TensorRT for MiDaS")
                    if "CUDAExecutionProvider" in available:
                        providers.append("CUDAExecutionProvider")
                        print("  ⚡ Using CUDA GPU for MiDaS")
                    providers.append("CPUExecutionProvider")
                    
                    print(f"  Requested providers (priority order): {providers}")
                    self.midas_session = ort.InferenceSession(midas_onnx_path, providers=providers)
                    self.midas_input_name = self.midas_session.get_inputs()[0].name
                    active_providers = self.midas_session.get_providers()
                    print(f"  MiDaS ONNX active providers: {active_providers}")
                    print(f"  MiDaS primary provider: {active_providers[0]}")
                    
                    print("=" * 60)
                    print("✅ RoadVision Engine AI Models are Ready!")
                    print(f"   YOLO device: cuda:0 | half={self._use_half}")
                    print(f"   MiDaS provider: {active_providers[0]}")
                    print("=" * 60)
                    self.models_loaded = True
                except Exception as e:
                    print(f"Error loading MiDaS model: {e}")
                    import traceback
                    traceback.print_exc()

        import threading
        threading.Thread(target=load_models_async, daemon=True).start()

        # --- Severity Stabilisation ---
        # Maps track_id -> deque of recent severity strings (last SEVERITY_WINDOW frames)
        self.SEVERITY_WINDOW = 7
        self._severity_history = {}   # {track_id: deque(["عميقة", "عميقة", ...])}
        self._active_track_ids = set()  # track IDs seen this frame (for cleanup)

    def _run_track(self, model, frame):
        """Run YOLO tracking with automatic half precision fallback."""
        try:
            return model.track(
                source=frame, conf=0.45, persist=True,
                verbose=False, device=0, half=self._use_half
            )
        except Exception as e:
            if self._use_half:
                print(f"⚠️ YOLO track failed with half=True: {e}")
                print("↪ Retrying with half=False...")
                self._use_half = False
                return model.track(
                    source=frame, conf=0.45, persist=True,
                    verbose=False, device=0, half=False
                )
            else:
                raise

    def detect(self, frame):
        """
        Runs object detection and depth estimation.
        Returns a list of dictionaries with 'label', 'confidence', 'bbox', 'distance', 'state', 'color'.
        """
        if not self.models_loaded:
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

                if label in IGNORED_LABELS and conf < 0.90:
                    continue

                # Extract track ID (assigned by YOLO tracker, None if not available)
                track_id = int(box.id[0]) if box.id is not None else None
                if track_id is not None:
                    self._active_track_ids.add(track_id)

                # Specific confidence threshold for handrail
                if label == "handrail" and conf < 0.80:
                    continue
                # Specific confidence threshold for potholes to reduce false positives
                if label == "pothole":
                    pothole_conf_thresh = getattr(config, 'POTHOLE_CONFIDENCE', 0.65)
                    if conf < pothole_conf_thresh:
                        continue

                # Specific confidence threshold for stairs to reduce false positives
                if label == "stairs":
                    stairs_conf_thresh = getattr(config, 'STAIRS_CONFIDENCE', 0.71)
                    if conf < stairs_conf_thresh:
                        continue

                # Bounding box depth
                bx1, by1 = max(0, x1), max(0, y1)
                bx2, by2 = min(depth_map.shape[1], x2), min(depth_map.shape[0], y2)
                box_depth_values = depth_map[by1:by2, bx1:bx2]
                
                if box_depth_values.size == 0:
                    continue
                
                # Use median for general distance estimation (75th percentile for potholes to get the deepest/closest part)
                if label == "pothole":
                    # For potholes, we care about the closest edge which has higher inverse depth
                    inverse_depth = np.percentile(box_depth_values, 80)
                else:
                    inverse_depth = np.median(box_depth_values)
                    
                simulated_distance = config.DEPTH_SCALE_FACTOR / inverse_depth if inverse_depth > 0 else 99.9

                # Determine Safety State
                if label == "pothole":
                    # Potholes are always a hazard if they are relatively close
                    if simulated_distance > 7.0:
                        state = "SAFE"
                        color = (0, 255, 0)
                    elif simulated_distance > 3.0:
                        state = "WARNING"
                        color = (0, 255, 255)
                    else:
                        state = "DANGER"
                        color = (0, 0, 255)
                else:
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

        # 2. Run YOLO Inferences (using tracking for stability, GPU with half fallback)
        pothole_results = self._run_track(self.pothole_model, frame)
        stairs_results = self._run_track(self.stairs_model, frame)
        obstacle_results = self._run_track(self.obstacle_model, frame)

        process_results(pothole_results, is_hazard=True)
        process_results(stairs_results, is_hazard=True)
        process_results(obstacle_results, is_hazard=False)

        # Prune severity history for tracks no longer visible
        stale_ids = set(self._severity_history.keys()) - self._active_track_ids
        for sid in stale_ids:
            del self._severity_history[sid]

        # 3. Wall Detection (Heuristic based on Depth Map)
        # Check central Region of Interest (ROI) avoiding the ground
        height, width = depth_map.shape
        roi_x1 = int(width * 0.20)
        roi_x2 = int(width * 0.80)
        roi_y1 = int(height * 0.15)
        roi_y2 = int(height * 0.50) # Avoid the bottom 50% where the ground is to reduce false ground detections
        
        wall_depth_values = depth_map[roi_y1:roi_y2, roi_x1:roi_x2]
        if wall_depth_values.size > 0:
            # Use 75th percentile to represent the closer dominant parts of the wall
            close_inverse_depth = np.percentile(wall_depth_values, 75)
            median_inverse_depth = np.median(wall_depth_values)
            std_depth = float(np.std(wall_depth_values))
            
            simulated_distance = config.DEPTH_SCALE_FACTOR / close_inverse_depth if close_inverse_depth > 0 else 99.9
            
            # Relative standard deviation to measure "flatness"
            relative_std = std_depth / (median_inverse_depth + 1e-6)
            
            # Check color uniformity (a wall usually has a uniform color/texture)
            color_roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
            color_std = 0.0
            if color_roi.size > 0:
                gray_roi = cv2.cvtColor(color_roi, cv2.COLOR_BGR2GRAY)
                color_std = float(np.std(gray_roi))

            # Tighten relative_std to ensure it's a flat surface, reducing false positives from objects
            # Also require color uniformity. Increased to 80.0 to handle noise in dark environments.
            if simulated_distance < 4.0 and relative_std < 0.25 and color_std < 80.0:
                # Calculate safe direction based on depth on the sides
                left_roi = depth_map[roi_y1:roi_y2, 0:roi_x1]
                right_roi = depth_map[roi_y1:roi_y2, roi_x2:width]
                
                left_median = np.median(left_roi) if left_roi.size > 0 else 0
                right_median = np.median(right_roi) if right_roi.size > 0 else 0
                
                # smaller inverse depth means further away
                safe_dir = "يساراً" if left_median < right_median else "يميناً"

                if simulated_distance > 2.5:
                    state = "WARNING"
                    color = (0, 255, 255) # Yellow
                else:
                    state = "DANGER"
                    color = (0, 0, 255) # Red
                    
                all_detections.append({
                    "label": "wall",
                    "confidence": max(0.5, 1.0 - relative_std),
                    "bbox": [roi_x1, roi_y1, roi_x2, roi_y2],
                    "distance": simulated_distance,
                    "state": state,
                    "color": color,
                    "severity_ar": "مسطح",
                    "safe_dir": safe_dir,
                    "is_hazard": True
                })

        return all_detections
