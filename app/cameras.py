import cv2
import threading
import time

def gstreamer_pipeline(
    sensor_id=0,
    capture_width=1280,
    capture_height=720,
    display_width=640,
    display_height=480,
    framerate=60,
    flip_method=2,
):
    return (
        "nvarguscamerasrc sensor-id=%d ! "
        "video/x-raw(memory:NVMM), width=(int)%d, height=(int)%d, framerate=(fraction)%d/1 ! "
        "nvvidconv flip-method=%d ! "
        "video/x-raw, width=(int)%d, height=(int)%d, format=(string)BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=(string)BGR ! appsink drop=true max-buffers=1"
        % (
            sensor_id,
            capture_width,
            capture_height,
            framerate,
            flip_method,
            display_width,
            display_height,
        )
    )

class ThreadedCamera:
    """
    A threaded camera reader that continuously polls the camera in the background.
    This prevents the main loop from experiencing frame buffer lag.
    """
    def __init__(self, cap):
        self.cap = cap
        self.ret = False
        self.frame = None
        self.stopped = False
        self.thread = None
        
        if self.cap.isOpened():
            self.ret, self.frame = self.cap.read()
            self.thread = threading.Thread(target=self._update, args=(), daemon=True)
            self.thread.start()

    def _update(self):
        while not self.stopped:
            if not self.cap.isOpened():
                self.stop()
                break
            ret, frame = self.cap.read()
            if ret:
                self.ret = ret
                self.frame = frame
            else:
                time.sleep(0.01) # Avoid tight loop if reading fails temporarily

    def read(self):
        return self.ret, self.frame

    def isOpened(self):
        return self.cap.isOpened()

    def release(self):
        self.stop()

    def stop(self):
        self.stopped = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.cap.release()


def open_camera(index, width, height, fps):
    """
    Attempts to open a Jetson CSI camera using GStreamer via a ThreadedCamera.
    If it fails (e.g. standard USB webcam is connected), falls back to standard V4L2.
    """
    print(f"Trying to open camera {index} with GStreamer (CSI)...")
    pipeline = gstreamer_pipeline(
        sensor_id=index,
        capture_width=1280,
        capture_height=720,
        display_width=width,
        display_height=height,
        framerate=60
    )
    
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    
    if not cap.isOpened():
        print(f"Failed to open CSI camera {index}. Falling back to standard USB WebCam...")
        cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        
        if not cap.isOpened():
            print(f"Error: Could not open camera {index} via USB or GStreamer.")
            return None
            
    print(f"Camera {index} successfully opened!")
    cam = ThreadedCamera(cap)
    return cam

def read_frame(cap):
    """
    Reads the most recent frame from the threaded camera.
    Returns (success, frame).
    """
    if cap is None or not cap.isOpened():
        return False, None
    return cap.read()

def release_all(cameras):
    """
    Releases all camera objects provided in the list.
    """
    for cap in cameras:
        if cap is not None and cap.isOpened():
            cap.release()
