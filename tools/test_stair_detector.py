#!/usr/bin/env python3
"""
Test script for Depth-based Stair/Hole Detector.

Opens the RealSense camera and runs StairDepthDetector WITHOUT YOLO.
Displays the detection results on screen and prints:
  - label, distance, confidence, state

Press 'q' to quit.
"""

import os
import sys
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np


def main():
    print("=" * 50)
    print("  Stair/Hole Depth Detector Test (No YOLO)")
    print("=" * 50)

    # Import modules
    try:
        from app.depth_camera import RealSenseDepthCamera
        from app.stair_depth_detector import StairDepthDetector
    except ImportError as e:
        print(f"Error importing modules: {e}")
        return

    # Create camera
    print("\nInitializing RealSense camera...")
    cam = RealSenseDepthCamera(width=640, height=480, fps=30)

    if not cam.isOpened():
        print("\n❌ Could not open RealSense camera.")
        print("   - Check USB connection")
        print("   - Install librealsense: pip install pyrealsense2")
        return

    # Create stair detector
    detector = StairDepthDetector()
    print("✅ Camera and Stair Detector initialized!")
    print("Press 'q' to quit.\n")

    frame_count = 0
    process_every = 2  # Match config default

    # Color map for states
    state_colors = {
        "SAFE": (0, 200, 0),
        "WARNING": (0, 255, 255),
        "DANGER": (0, 0, 255),
    }

    try:
        while True:
            ret, color_bgr, depth_meters, intrinsics = cam.read()

            if not ret or color_bgr is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            display = color_bgr.copy()

            # Run stair detection every N frames
            result = None
            if frame_count % process_every == 0 and depth_meters is not None:
                result = detector.analyze(depth_meters, intrinsics)

                if result:
                    # Print results
                    if result["detected"]:
                        print(f"[{frame_count:5d}] ⚠️  label={result['label']:<15s} "
                              f"dist={result['distance']:.2f}m  "
                              f"conf={result['confidence']:.0%}  "
                              f"state={result['state']}")
                    elif frame_count % 30 == 0:
                        print(f"[{frame_count:5d}] ✅  clear")

            # Draw ROI and detection info
            fh, fw = display.shape[:2]
            roi = detector.get_roi_rect(fh, fw)
            rx1, ry1, rx2, ry2 = roi

            # Get latest result (or use last from detector)
            if result is None:
                result = detector._last_result

            state = result.get("state", "SAFE")
            color = state_colors.get(state, (0, 200, 0))

            # Draw ROI rectangle
            thickness = 3 if result.get("detected", False) else 1
            cv2.rectangle(display, (rx1, ry1), (rx2, ry2), color, thickness)

            # Draw info bar at top
            label_text = result.get("label", "clear")
            dist_text = f"{result.get('distance', 0):.1f}m"
            conf_text = f"{result.get('confidence', 0):.0%}"
            state_text = result.get("state", "SAFE")
            msg_text = result.get("message", "")

            info = f"{label_text} | {state_text} | {dist_text} | conf: {conf_text}"
            cv2.putText(display, info, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            if msg_text:
                cv2.putText(display, msg_text, (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # Show depth colormap alongside
            if depth_meters is not None:
                depth_vis = depth_meters.copy()
                depth_vis[np.isnan(depth_vis)] = 0
                depth_norm = np.clip(depth_vis / 6.0, 0, 1)
                depth_uint8 = (depth_norm * 255).astype(np.uint8)
                depth_colormap = cv2.applyColorMap(depth_uint8, cv2.COLORMAP_JET)

                # Draw ROI on depth too
                cv2.rectangle(depth_colormap, (rx1, ry1), (rx2, ry2), (255, 255, 255), 2)

                cv2.imshow("Depth Map", depth_colormap)

            cv2.imshow("Stair Detector", display)

            # Check for quit
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("\n'q' pressed. Exiting...")
                break

    except KeyboardInterrupt:
        print("\nKeyboard interrupt. Exiting...")
    finally:
        cam.release()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()
