import cv2
import time
import os
import sys

# Add project root to sys.path to allow running 'python3 app/main.py' directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config
from app.cameras import open_camera, read_frame, release_all
from app.detector import RoadVisionEngine
from app.distance import get_direction
from app.speech import SpeechEngine
import threading
from app.translations import translate_label
from app import web_dashboard
try:
    from app import network_manager as nm
except ImportError:
    nm = None

def main():
    print("Starting RoadVision-AI Assistant (YOLO + MiDaS)...")
    
    if nm:
        print("Checking internet connection...")
        if not nm.check_internet():
            print("No internet. Trying last known Wi-Fi...")
            if not nm.try_last_wifi():
                print("Could not connect to last Wi-Fi. Will keep retrying in background...")
        else:
            print("Internet connection is active.")
        # Start auto-recovery monitor (checks every 30 seconds)
        nm.start_monitor(check_interval=30)
    
    speech_engine = SpeechEngine(cooldown_seconds=config.SPEECH_COOLDOWN_SECONDS)
    
    # --- Arduino Setup ---
    arduino = None
    if config.USE_ARDUINO:
        from app.arduino_reader import ArduinoReader
        arduino = ArduinoReader(
            port=config.ARDUINO_PORT,
            baud_rate=config.ARDUINO_BAUD_RATE
        )

    # --- Telegram Bot Setup ---
    telegram = None
    if config.USE_TELEGRAM:
        from app.telegram_bot import TelegramBot
        telegram = TelegramBot(
            token=config.TELEGRAM_BOT_TOKEN,
            send_interval=config.TELEGRAM_SEND_INTERVAL
        )
        if arduino:
            telegram.set_arduino_reader(arduino)

    # --- Fall Detection Callback ---
    def on_fall_detected(fall_info):
        """Called when Arduino detects a fall."""
        name = fall_info.get("person_name", "شخص")
        speech_engine.speak(f"تحذير! سقوط {name}! يرجى المساعدة!")
        if telegram:
            telegram.send_fall_alert(fall_info)

    if arduino:
        arduino.set_on_fall(on_fall_detected)
        arduino.start()

    if telegram:
        telegram.start()
        
        # Build startup message
        msg = "🟢 *System is now running!*\n"
        if nm:
            ip = nm.get_ip_address()
            msg += f"🌐 Dashboard (IP): http://{ip}:{config.WEB_PORT}\n"
            msg += f"🔗 Dashboard (Fixed): http://jetson.local:{config.WEB_PORT}\n"
        
        msg += "Send /help to view commands."

        telegram.broadcast(msg)
    
    cameras = []
    
    # Open Camera 0
    print(f"Opening Camera 0 (Index {config.CAMERA_0_INDEX})...")
    cap0 = open_camera(config.CAMERA_0_INDEX, config.FRAME_WIDTH, config.FRAME_HEIGHT, config.FPS)
    if cap0:
        cameras.append(cap0)
        
    if not cameras:
        print("Error: No cameras could be opened. Exiting.")
        return

    # Initialize New RoadVision Engine (3 YOLO Models + MiDaS)
    detector = RoadVisionEngine()
    
    # Start Web Dashboard
    print(f"Starting Web Dashboard on port {config.WEB_PORT}...")
    web_dashboard.system_state["status"] = "running"
    web_dashboard.system_state["cameras_active"] = len(cameras)
    web_dashboard.system_state["pothole_model_loaded"] = True
    threading.Thread(target=web_dashboard.run_server, daemon=True).start()
    
    # --- AI Background Thread ---
    latest_raw_frame = None
    latest_detections = []
    ai_processing = False
    
    def ai_worker():
        nonlocal latest_raw_frame, latest_detections, ai_processing
        last_vibration_state = None
        while True:
            if latest_raw_frame is not None and not ai_processing:
                ai_processing = True
                frame_to_process = latest_raw_frame.copy()
                
                # Run RoadVision Unified Detection (blocks)
                try:
                    detections = detector.detect(frame_to_process)
                except Exception as e:
                    print(f"AI Error: {e}")
                    detections = []
                
                hazard_detected = False
                vibration_triggered = False
                
                # To collect items for speech
                speech_objects = set()
                hazard_objects = set()
                
                for det in detections:
                    label_eng = det["label"]
                    label_ar = translate_label(label_eng)
                    distance = det["distance"]
                    state = det["state"]
                    is_hazard = det["is_hazard"]
                    bbox = det["bbox"]
                    direction = get_direction(bbox, frame_to_process.shape[1])
                    
                    severity_ar = det.get("severity_ar", "")
                    
                    # Add label and direction for speech (all objects)
                    obj_desc = f"{label_ar} {severity_ar} {direction}".strip()
                    # Clean up any double spaces
                    obj_desc = " ".join(obj_desc.split())
                    
                    # Only mention potholes if they are close (WARNING or DANGER)
                    if "pothole" in label_eng.lower() and state == "SAFE":
                        pass # Ignore far away potholes for speech
                    elif label_eng == "wall":
                        pass # Wall speech is handled explicitly below
                    else:
                        speech_objects.add(obj_desc)
                    
                    if is_hazard and state in ["DANGER", "WARNING"]:
                        hazard_detected = True
                        vibration_triggered = True
                        hazard_objects.add(obj_desc)
                        if telegram:
                            telegram.broadcast(f"⚠️ *تنبيه خطر!*\nالنوع: *{label_ar} {severity_ar}*\nالمسافة: *{distance:.1f} متر* ({state})\n⏰ {time.strftime('%H:%M:%S')}")
                    elif state == "DANGER":
                        hazard_detected = True # Treat any close object as a hazard for speech
                        vibration_triggered = True
                        if label_eng != "wall":
                            hazard_objects.add(obj_desc)
                        if telegram:
                            telegram.broadcast(f"⚠️ *تنبيه اقتراب!*\nالنوع: *{label_ar} {severity_ar}*\nالمسافة: *{distance:.1f} متر* ({state})\n⏰ {time.strftime('%H:%M:%S')}")
                
                # Update shared state
                latest_detections = detections
                
                # Control vibration
                if arduino:
                    if vibration_triggered != last_vibration_state:
                        if vibration_triggered:
                            arduino.vibration_on()
                        else:
                            arduino.vibration_off()
                        last_vibration_state = vibration_triggered
                
                # Speech Generation
                # Collect wall detections (only emitted when < 2m / DANGER)
                for det in latest_detections:
                    if det["label"] == "wall" and det["state"] == "DANGER":
                        safe_direction = det.get("safe_dir", "")
                        wall_msg = f"جدار قريب جداً، اتجه {safe_direction}".strip()
                        hazard_objects.add(wall_msg)
                        hazard_detected = True
                        vibration_triggered = True

                if hazard_objects:
                    hazards_str = " و ".join(list(hazard_objects)[:2])
                    speech_engine.speak(f"تحذير! {hazards_str}!")
                elif speech_objects:
                    objects_str = " و ".join(list(speech_objects)[:3])
                    speech_text = f"أرى {objects_str}."
                    speech_engine.speak(speech_text)
                
                ai_processing = False
            time.sleep(0.01)

    threading.Thread(target=ai_worker, daemon=True).start()

    try:
        print("Press CTRL+C to quit")
        while True:
            for idx, cap in enumerate(cameras):
                ret, frame = read_frame(cap)
                if not ret:
                    continue
                
                if idx == 0:
                    latest_raw_frame = frame.copy()
                    
                    # Draw latest_detections on the CURRENT frame (smooth 30fps)
                    for det in latest_detections:
                        color = det["color"]
                        x1, y1, x2, y2 = det["bbox"]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        
                        conf_percent = int(det['confidence'] * 100)
                        text = f"{det['label']} {conf_percent}% | {det['state']} | {det['distance']:.1f}m"
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        (tw, th), _ = cv2.getTextSize(text, font, 0.5, 2)
                        cv2.rectangle(frame, (x1, y1), (x1 + tw + 4, y1 + th + 8), color, -1)
                        cv2.putText(frame, text, (x1 + 2, y1 + th + 4), font, 0.5, (0, 0, 0), 2)
                    
                    # Update Web Dashboard frame smoothly
                    web_dashboard.latest_frame = frame
                
                if config.DISPLAY_ON_JETSON:
                    try:
                        cv2.imshow("RoadVision-AI", frame)
                    except cv2.error:
                        config.DISPLAY_ON_JETSON = False
                        
            if config.DISPLAY_ON_JETSON:
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    print("ESC pressed. Exiting...")
                    break
            else:
                time.sleep(0.03) # Cap loop to ~30 FPS
                
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")
    finally:
        print("Cleaning up resources...")
        release_all(cameras)
        if config.DISPLAY_ON_JETSON:
            cv2.destroyAllWindows()
        if arduino:
            arduino.stop()
        if telegram:
            telegram.broadcast("🔴 *System stopped.*")
            time.sleep(1)
            telegram.stop()

if __name__ == "__main__":
    main()
