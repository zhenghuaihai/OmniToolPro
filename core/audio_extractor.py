import os
import sys
import imageio_ffmpeg
import subprocess

def get_ffmpeg_path():
    """
    Get the path to the ffmpeg executable.
    """
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print(f"Error getting imageio-ffmpeg exe: {e}")
        return 'ffmpeg'

def extract_audio(video_path, output_audio_path):
    """
    Extracts audio from video using ffmpeg via subprocess.
    Returns (success, error_message).
    """
    try:
        # Check if file exists
        if not os.path.exists(video_path):
            return False, f"File not found: {video_path}"

        ffmpeg_cmd = get_ffmpeg_path()
        
        # Construct command
        # ffmpeg -y -i input.mp4 -acodec pcm_s16le -ac 1 -ar 16000 output.wav
        cmd = [
            ffmpeg_cmd,
            '-y', # Overwrite output files without asking
            '-i', video_path,
            '-vn', # Disable video recording
            '-acodec', 'pcm_s16le',
            '-ac', '1', # Mono
            '-ar', '16000', # 16kHz
            output_audio_path
        ]
        
        # Run subprocess
        # Capture output for error reporting
        process = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return True, None
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        return False, f"FFmpeg Error: {error_msg}"
    except Exception as e:
        return False, f"Extraction Error: {str(e)}"
