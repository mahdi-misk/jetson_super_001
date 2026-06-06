#!/usr/bin/env python3
"""
Test script for Intel RealSense Depth Camera.

Opens the RealSense camera and displays:
  - RGB color stream
  - Depth colormap visualization
  - Min / Average / Median depth statistics

Press 'q' to quit.
"""

import os
import sys
import time

    # Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from app import config

def main():
    print("=" * 50)
    print(f"  Depth Camera Test ({config.DEPTH_CAMERA_TYPE.upper()})")
    print("=" * 50)

    # Try importing depth camera module
    try:
        if config.DEPTH_CAMERA_TYPE == "stereo":
            from app.stereo_depth_camera import StereoDepthCamera as DepthCamera
        else:
            from app.depth_camera import RealSenseDepthCamera as DepthCamera
    except ImportError as e:
        print(f"Error importing depth_camera module: {e}")
        return

    # Create camera
    print("\nInitializing camera...")
    cam = DepthCamera(width=config.DEPTH_WIDTH, height=config.DEPTH_HEIGHT, fps=30)

    if not cam.isOpened():
        print("\n❌ Could not open camera.")
        print("   - Check connections")
        print("   - Check USE_DEPTH_CAMERA in config.py")
        return

    print("\n✅ Camera opened successfully!")
    print("Press 'q' to quit.\n")

    frame_count = 0
    fps_start = time.time()

    try:
        while True:
            ret, color_bgr, depth_meters, intrinsics = cam.read()

            if not ret or color_bgr is None:
                time.sleep(0.01)
                continue

            frame_count += 1

            # Display RGB frame
            cv2.imshow("RealSense RGB", color_bgr)

            # Create depth colormap
            if depth_meters is not None:
                # Replace NaN with 0 for visualization
                depth_vis = depth_meters.copy()
                depth_vis[np.isnan(depth_vis)] = 0

                # Normalize to 0-255 for colormap (0-6 meters range)
                depth_norm = np.clip(depth_vis / 6.0, 0, 1)
                depth_uint8 = (depth_norm * 255).astype(np.uint8)
                depth_colormap = cv2.applyColorMap(depth_uint8, cv2.COLORMAP_JET)

                # Compute depth statistics (valid pixels only)
                valid_depth = depth_meters[np.isfinite(depth_meters) & (depth_meters > 0.1)]
                if len(valid_depth) > 0:
                    d_min = np.min(valid_depth)
                    d_avg = np.mean(valid_depth)
                    d_med = np.median(valid_depth)

                    stats_text = f"Min: {d_min:.2f}m  Avg: {d_avg:.2f}m  Med: {d_med:.2f}m"
                    cv2.putText(depth_colormap, stats_text, (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                    # Print every 30 frames
                    if frame_count % 30 == 0:
                        elapsed = time.time() - fps_start
                        fps = frame_count / elapsed if elapsed > 0 else 0
                        print(f"[Frame {frame_count}] FPS: {fps:.1f} | "
                              f"Depth Min: {d_min:.2f}m, Avg: {d_avg:.2f}m, "
                              f"Median: {d_med:.2f}m")

                cv2.imshow("RealSense Depth", depth_colormap)

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
        elapsed = time.time() - fps_start
        fps = frame_count / elapsed if elapsed > 0 else 0
        print(f"\nTotal frames: {frame_count}, Average FPS: {fps:.1f}")
        print("Done.")


if __name__ == "__main__":
    main()
