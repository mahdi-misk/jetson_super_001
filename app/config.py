# Central configuration for the Vision + Voice AI Assistant

CAMERA_0_INDEX = 1
CAMERA_1_INDEX = 0
FRAME_WIDTH = 480
FRAME_HEIGHT = 360
FPS = 30

DISPLAY_ON_JETSON = True
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
