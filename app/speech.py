import time
import os
import hashlib
import threading
import subprocess

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".speech_cache")

class SpeechEngine:
    def __init__(self, cooldown_seconds=3):
        self.cooldown_seconds = cooldown_seconds
        self.last_spoken_time = 0.0
        self.last_message = ""
        self._is_speaking = False
        self._lock = threading.Lock()
        
        # Create cache directory
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        # Try to import gTTS
        try:
            from gtts import gTTS
            self._gtts_available = True
            print("SpeechEngine: Using Google TTS (high quality Arabic)")
        except ImportError:
            self._gtts_available = False
            print("SpeechEngine: gTTS not found, falling back to spd-say")

    def speak(self, text):
        current_time = time.time()
        
        # Skip if still in cooldown
        if (current_time - self.last_spoken_time) < self.cooldown_seconds:
            return
        
        # Skip if another speech is still playing
        with self._lock:
            if self._is_speaking:
                return
        
        self.last_spoken_time = current_time
        self.last_message = text
        print(f"Speaking: '{text}'")
        
        # Run speech in a background thread so it doesn't freeze the camera feed
        threading.Thread(target=self._speak_task, args=(text,), daemon=True).start()

    def _get_cache_path(self, text):
        """Generate a cache file path based on text hash."""
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        return os.path.join(CACHE_DIR, f"{text_hash}.mp3")

    def _speak_task(self, text):
        with self._lock:
            self._is_speaking = True
        
        try:
            if self._gtts_available:
                self._speak_gtts(text)
            else:
                self._speak_spd(text)
        except Exception as e:
            print(f"Speech error: {e}")
        finally:
            with self._lock:
                self._is_speaking = False

    def _speak_gtts(self, text):
        """Use Google TTS offline cache for high-quality Arabic speech."""
        cache_path = self._get_cache_path(text)
        
        # Check if the specific phrase was pre-generated
        if not os.path.exists(cache_path):
            print(f"SpeechEngine Warning: '{text}' not found in offline cache.")
            # Fallback to a generic warning that is guaranteed to be cached
            fallback_text = "انتبه أمامك"
            cache_path = self._get_cache_path(fallback_text)
            
            if not os.path.exists(cache_path):
                # If even fallback is missing (user forgot to run pregenerate_speech.py)
                print("SpeechEngine Critical: No offline cache found! Run scripts/pregenerate_speech.py")
                self._speak_spd(text)
                return
        
        # Play using GStreamer (already available on Jetson)
        subprocess.run(
            ["gst-launch-1.0", "playbin", f"uri=file://{os.path.abspath(cache_path)}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _speak_spd(self, text):
        """Fallback: use spd-say with Arabic language."""
        os.system(f"spd-say -l ar '{text}'")
