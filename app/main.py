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
                print("Could not connect to last Wi-Fi. Starting Hotspot mode...")
                nm.start_hotspot()
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
        telegram.broadcast("🟢 *النظام يعمل الآن!*\nأرسل /help لعرض الأوامر.")
    
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
    
    try:
        while True:
            for idx, cap in enumerate(cameras):
                ret, frame = read_frame(cap)
                if not ret:
                    continue
                
                if idx == 0:
                    # Run RoadVision Unified Detection
                    detections = detector.detect(frame)
                    
                    detected_labels = set()
                    hazard_detected = False
                    
                    for det in detections:
                        label_eng = det["label"]
                        label_ar = translate_label(label_eng)
                        conf = det["confidence"]
                        bbox = det["bbox"]
                        distance = det["distance"]
                        state = det["state"]
                        color = det["color"]
                        is_hazard = det["is_hazard"]
                        
                        x1, y1, x2, y2 = bbox
                        
                        direction = get_direction(bbox, frame.shape[1])
                        
                        # Add label and direction for speech
                        detected_labels.add(f"{label_ar} {direction}")
                        
                        # Trigger alerts for hazards in DANGER or WARNING
                        if is_hazard and (state == "DANGER" or state == "WARNING"):
                            hazard_detected = True
                            if arduino:
                                arduino.pothole_alert() # triggers buzzer/vibration
                            if telegram:
                                telegram.broadcast(
                                    f"⚠️ *تنبيه خطر!*\n"
                                    f"النوع: *{label_ar}*\n"
                                    f"المسافة: *{distance:.1f} متر* ({state})\n"
                                    f"⏰ {time.strftime('%H:%M:%S')}"
                                )
                        
                        # Draw bounding box and label
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        
                        text = f"{label_eng} | {state} | {distance:.1f}m"
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        (tw, th), _ = cv2.getTextSize(text, font, 0.5, 2)
                        # Draw text background INSIDE the box (top-inside)
                        cv2.rectangle(frame, (x1, y1), (x1 + tw + 4, y1 + th + 8), color, -1)
                        
                        # Text color black for better contrast on colored backgrounds
                        cv2.putText(frame, text, (x1 + 2, y1 + th + 4), font, 0.5, (0, 0, 0), 2)
                    
                    # Generate speech message for hazards
                    if hazard_detected:
                        speech_engine.speak("تحذير! انتبه أمامك!")
                    elif detected_labels:
                        objects_str = " و ".join(list(detected_labels)[:3]) # Limit to 3 items
                        speech_text = f"أرى {objects_str}."
                        speech_engine.speak(speech_text)
                    
                    # Update Web Dashboard frame
                    web_dashboard.latest_frame = frame.copy()
                
                # Display the frame if requested
                if config.DISPLAY_ON_JETSON:
                    try:
                        cv2.imshow("RoadVision-AI", frame)
                    except cv2.error:
                        config.DISPLAY_ON_JETSON = False
                        print("Display not available (headless mode). Running without GUI.")
            
            if config.DISPLAY_ON_JETSON:
                key = cv2.waitKey(1) & 0xFF
                if key == 27: # ESC key
                    print("ESC pressed. Exiting...")
                    break
            else:
                time.sleep(0.01)
                
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
            telegram.broadcast("🔴 *النظام توقف.*")
            time.sleep(1)
            telegram.stop()

if __name__ == "__main__":
    main()
