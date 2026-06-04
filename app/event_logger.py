import json
import os
import time
import threading
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "event_log.json")
MAX_EVENTS = 500

_lock = threading.Lock()

def _load_events():
    """Load events from disk."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def _save_events(events):
    """Save events to disk (keep last MAX_EVENTS)."""
    events = events[-MAX_EVENTS:]
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Error saving event log: {e}")

def log_event(category, message, level="info"):
    """
    Log an event.
    
    Args:
        category: e.g. "network", "bluetooth", "detection", "system", "ota"
        message: Description of the event
        level: "info", "warning", "error", "success"
    """
    event = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "category": category,
        "message": message,
        "level": level
    }
    with _lock:
        events = _load_events()
        events.append(event)
        _save_events(events)
    return event

def get_events(limit=100, category=None):
    """Get recent events, optionally filtered by category."""
    with _lock:
        events = _load_events()
    
    if category:
        events = [e for e in events if e["category"] == category]
    
    return events[-limit:][::-1]  # Return newest first

def clear_events():
    """Clear all events."""
    with _lock:
        _save_events([])
