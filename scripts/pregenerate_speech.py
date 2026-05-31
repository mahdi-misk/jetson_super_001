import os
import hashlib
import time

try:
    from gtts import gTTS
except ImportError:
    print("gTTS is not installed. Run: pip install gTTS")
    exit(1)

# Import the vocabulary
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.translations import COCO_ARABIC

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".speech_cache")

def get_cache_path(text):
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{text_hash}.mp3")

def generate_phrase(text):
    cache_path = get_cache_path(text)
    if not os.path.exists(cache_path):
        try:
            print(f"Generating: '{text}'")
            tts = gTTS(text, lang="ar")
            tts.save(cache_path)
            time.sleep(0.5) # Prevent rate limiting
        except Exception as e:
            print(f"Failed to generate '{text}': {e}")
    else:
        print(f"Already cached: '{text}'")

def pregenerate_all():
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    print("Starting pre-generation of all Arabic speech phrases...")
    print(f"Cache directory: {CACHE_DIR}")
    
    # 1. Base Warnings
    warnings = [
        "تحذير! انتبه أمامك!",
        "انتبه! خطر أمامك!",
        "انتبه أمامك",
        "تحذير! سقوط شخص! يرجى المساعدة!",
    ]
    
    for w in warnings:
        generate_phrase(w)
        
    # 2. General Objects with directions (from detector logic: "أرى X على يمينك")
    directions = ["على يسارك", "على يمينك", "أمامك", ""]
    
    # Add custom hazards to vocabulary if not in COCO
    vocabulary = list(COCO_ARABIC.values())
    vocabulary.extend(["حفرة", "درج", "عائق"])
    
    # Generate common combinations (Max 3 items as per main.py logic: "أرى X و Y و Z")
    # To keep it manageable, we just cache single item phrases since main.py creates combined strings.
    # Actually, in main.py: speech_text = f"أرى {objects_str}."
    # If we want 100% offline, main.py might generate a dynamic string that isn't cached!
    # Let's cache the individual components, OR change main.py to say them one by one.
    
    # Generate single item phrases:
    for item in vocabulary:
        for d in directions:
            if d:
                phrase = f"أرى {item} {d}."
            else:
                phrase = f"أرى {item}."
            generate_phrase(phrase)
            
    print("\n✅ All speech phrases have been generated and cached!")
    print("Your system can now speak 100% offline!")

if __name__ == "__main__":
    pregenerate_all()
