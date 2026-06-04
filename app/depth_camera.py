"""
Intel RealSense Depth Camera Module.

Provides a unified RGB + Depth source using Intel RealSense D4xx cameras.
Falls back gracefully if pyrealsense2 is not installed or camera is not connected.

Interface is compatible with cameras.ThreadedCamera:
    read()      -> (ret, color_bgr, depth_meters, intrinsics)
    isOpened()  -> bool
    release()   -> None
"""

import threading
import time
import numpy as np

# Try importing pyrealsense2 with clear error message
try:
    import pyrealsense2 as rs
    _RS_AVAILABLE = True
except ImportError:
    _RS_AVAILABLE = False


class RealSenseDepthCamera:
    """
    Threaded Intel RealSense camera that provides aligned RGB + Depth frames.

    Usage:
        cam = RealSenseDepthCamera(width=640, height=480, fps=30)
        if cam.isOpened():
            ret, color_bgr, depth_meters, intrinsics = cam.read()
        cam.release()
    """

    def __init__(self, width=640, height=480, fps=30):
        self._width = width
        self._height = height
        self._fps = fps

        self._pipeline = None
        self._align = None
        self._intrinsics = None

        # Latest frame data (protected by lock)
        self._lock = threading.Lock()
        self._ret = False
        self._color_frame = None
        self._depth_meters = None

        self._opened = False
        self._stopped = False
        self._thread = None

        if not _RS_AVAILABLE:
            print("⚠️ pyrealsense2 not installed. "
                  "Disable USE_DEPTH_CAMERA in config.py or install librealsense:\n"
                  "   pip install pyrealsense2")
            return

        # Try to start the camera
        if not self._start_pipeline():
            return

        # Start background reading thread
        self._opened = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        print(f"✅ RealSense Depth Camera started ({width}x{height} @ {fps}fps)")

    def _start_pipeline(self):
        """Initialize RealSense pipeline with color + depth streams."""
        try:
            ctx = rs.context()
            devices = ctx.query_devices()
            if len(devices) == 0:
                print("⚠️ No Intel RealSense device detected. "
                      "Check USB connection or disable USE_DEPTH_CAMERA in config.py.")
                return False

            dev_name = devices[0].get_info(rs.camera_info.name)
            dev_serial = devices[0].get_info(rs.camera_info.serial_number)
            print(f"  🔍 Found RealSense: {dev_name} (S/N: {dev_serial})")

            self._pipeline = rs.pipeline()
            cfg = rs.config()
            cfg.enable_stream(rs.stream.color, self._width, self._height,
                              rs.format.bgr8, self._fps)
            cfg.enable_stream(rs.stream.depth, self._width, self._height,
                              rs.format.z16, self._fps)

            profile = self._pipeline.start(cfg)

            # Create alignment object (align depth to color)
            self._align = rs.align(rs.stream.color)

            # Extract camera intrinsics (needed for 3D point computation)
            depth_profile = profile.get_stream(rs.stream.depth)
            self._intrinsics = depth_profile.as_video_stream_profile().get_intrinsics()

            # Read one frame to confirm everything works
            frames = self._pipeline.wait_for_frames(timeout_ms=5000)
            if not frames:
                print("⚠️ RealSense: Could not read initial frame.")
                self._pipeline.stop()
                self._pipeline = None
                return False

            return True

        except Exception as e:
            print(f"⚠️ RealSense initialization failed: {e}")
            if self._pipeline:
                try:
                    self._pipeline.stop()
                except Exception:
                    pass
                self._pipeline = None
            return False

    def _update_loop(self):
        """Continuously read frames in background thread."""
        while not self._stopped:
            try:
                frames = self._pipeline.wait_for_frames(timeout_ms=1000)
                if not frames:
                    continue

                # Align depth to color frame
                aligned = self._align.process(frames)
                color_frame = aligned.get_color_frame()
                depth_frame = aligned.get_depth_frame()

                if not color_frame or not depth_frame:
                    continue

                # Convert to numpy arrays
                color_np = np.asanyarray(color_frame.get_data())  # BGR uint8

                # Convert depth from raw uint16 (millimeters) to float32 meters
                depth_raw = np.asanyarray(depth_frame.get_data())  # uint16
                depth_m = depth_raw.astype(np.float32) / 1000.0   # -> meters

                # Mark invalid depth (0 = no reading) as NaN for downstream
                depth_m[depth_raw == 0] = np.nan

                with self._lock:
                    self._ret = True
                    self._color_frame = color_np
                    self._depth_meters = depth_m

            except RuntimeError:
                # Camera disconnected or pipeline error
                if not self._stopped:
                    time.sleep(0.1)
            except Exception as e:
                if not self._stopped:
                    print(f"RealSense read error: {e}")
                    time.sleep(0.1)

    def read(self):
        """
        Read the latest aligned RGB + Depth frame.

        Returns:
            (ret, color_bgr, depth_meters, intrinsics)
            - ret: bool, True if frames are available
            - color_bgr: numpy array (H, W, 3) uint8 BGR
            - depth_meters: numpy array (H, W) float32 in meters (NaN = invalid)
            - intrinsics: pyrealsense2 intrinsics object (or None)
        """
        with self._lock:
            if not self._ret:
                return False, None, None, None
            return (True,
                    self._color_frame.copy() if self._color_frame is not None else None,
                    self._depth_meters.copy() if self._depth_meters is not None else None,
                    self._intrinsics)

    def isOpened(self):
        """Check if the camera is opened and running."""
        return self._opened and not self._stopped

    def release(self):
        """Stop the camera and release resources."""
        self._stopped = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._pipeline:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
        self._opened = False
        print("RealSense camera released.")


def create_depth_camera(width=640, height=480, fps=30):
    """
    Factory function to create a RealSense depth camera.
    Returns None if not available (no crash).
    """
    if not _RS_AVAILABLE:
        print("⚠️ pyrealsense2 not installed. "
              "Disable USE_DEPTH_CAMERA or install librealsense.")
        return None

    cam = RealSenseDepthCamera(width=width, height=height, fps=fps)
    if cam.isOpened():
        return cam

    print("⚠️ RealSense camera not available. Falling back to standard camera.")
    return None
