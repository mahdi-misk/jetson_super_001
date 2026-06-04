# Central configuration for the Vision + Voice AI Assistant

CAMERA_0_INDEX = 0
CAMERA_1_INDEX = 1
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FPS = 30

# Depth Calibration Factor (Increase to make objects appear further, decrease to make them closer)
DEPTH_SCALE_FACTOR = 1000.0

DISPLAY_ON_JETSON = False
WEB_PORT = 8000
SPEECH_COOLDOWN_SECONDS = 5

USE_AI_DETECTION = True  # AI is now integrated
USE_TWO_CAMERAS = True

# --- Arduino Settings ---
USE_ARDUINO = True
ARDUINO_PORT = None         # None = auto-detect, or set e.g. "/dev/ttyUSB0"
ARDUINO_BAUD_RATE = 115200

# --- Telegram Bot Settings ---
USE_TELEGRAM = True
TELEGRAM_BOT_TOKEN = "8977103710:AAFKAJWXzUqTbLMo8nEWXuPdDESkb861bMc"
TELEGRAM_SEND_INTERVAL = 0  # 0 to disable auto sensor updates (only send on collision)

# --- Pothole Detection Settings ---
USE_POTHOLE_DETECTION = True
POTHOLE_ROBOFLOW_API_KEY = "4lrHjIQ17hJryjEYNrfk"
POTHOLE_ROBOFLOW_MODEL_ID = "pothole-vhmow/2" # Roboflow model ID
POTHOLE_CONFIDENCE = 0.5                # Minimum confidence threshold (0.0 - 1.0)
POTHOLE_SNAPSHOT_COOLDOWN = 5           # Seconds between saving snapshots
