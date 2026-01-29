
import imageio_ffmpeg
import os
import sys

print(f"imageio_ffmpeg version: {imageio_ffmpeg.__version__}")
try:
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"ffmpeg exe path: {exe}")
    print(f"exists: {os.path.exists(exe)}")
except Exception as e:
    print(f"Error getting ffmpeg exe: {e}")

import ffmpeg
print(f"ffmpeg-python imported")
