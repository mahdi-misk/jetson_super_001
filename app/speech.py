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
        
        self._set_default_audio_sink()
        
        # Try to import gTTS
        try:
            from gtts import gTTS
            self._gtts_available = True
            print("SpeechEngine: Using Google TTS (high quality Arabic)")
        except ImportError:
            self._gtts_available = False
            print("SpeechEngine: gTTS not found, falling back to spd-say")

    def _set_default_audio_sink(self):
        """Set the default audio sink to Bluetooth (if available) or USB Audio."""
        try:
            output = subprocess.check_output(["pactl", "list", "short", "sinks"], universal_newlines=True)
            sinks = [line.split('\t')[1] for line in output.strip().split('\n') if line]
            
            target_sink = None
            # Priority 1: Bluetooth (bluez)
            for s in sinks:
                if 'bluez_sink' in s:
                    target_sink = s
                    break
            
            # Priority 2: USB Audio (often used for bluetooth dongles)
            if not target_sink:
                for s in sinks:
                    if 'usb' in s:
                        target_sink = s
                        break
                        
            if target_sink:
                subprocess.run(["pactl", "set-default-sink", target_sink], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"SpeechEngine: Auto-configured default audio output to {target_sink}")
            else:
                print("SpeechEngine: No Bluetooth/USB sink found. Using default audio output.")
        except Exception as e:
            print(f"SpeechEngine: Error setting default sink: {e}")

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
        """Use Google TTS for high-quality Arabic speech with dynamic caching."""
        from gtts import gTTS
        
        cache_path = self._get_cache_path(text)
        
        # Generate audio only if not cached
        if not os.path.exists(cache_path):
            print(f"SpeechEngine: Generating audio for '{text}'...")
            try:
                tts = gTTS(text, lang="ar")
                tts.save(cache_path)
            except Exception as e:
                print(f"gTTS generation failed: {e}, falling back to spd-say")
                self._speak_spd(text)
                return
        
        # Play using GStreamer (already available on Jetson)
        env = os.environ.copy()
        if "XDG_RUNTIME_DIR" not in env:
            env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        if "PULSE_SERVER" not in env:
            env["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"

        subprocess.run(
            ["gst-launch-1.0", "playbin", f"uri=file://{os.path.abspath(cache_path)}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )

    def _speak_spd(self, text):
        """Fallback: use spd-say with Arabic language."""
        os.system(f"XDG_RUNTIME_DIR=/run/user/1000 PULSE_SERVER=unix:/run/user/1000/pulse/native spd-say -l ar '{text}'")
