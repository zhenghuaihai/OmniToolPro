from PyQt6.QtCore import QThread, pyqtSignal
from core.audio_extractor import extract_audio
from core.transcriber import Transcriber
from core.summarizer import Summarizer
import os

class VideoWorker(QThread):
    # index, progress (0-100)
    progress_signal = pyqtSignal(int, int) 
    # index, status text
    status_signal = pyqtSignal(int, str) 
    # finished
    finished_signal = pyqtSignal()
    
    def __init__(self, tasks, output_dir, api_key, base_url):
        super().__init__()
        self.tasks = tasks # list of {'path': str, 'index': int}
        self.output_dir = output_dir
        self.api_key = api_key
        self.base_url = base_url
        self.is_running = True

    def run(self):
        try:
            # Initialize Transcriber (this might take time to load model)
            # Notify UI if possible? No easy way to notify global loading yet.
            transcriber = Transcriber() 
            summarizer = Summarizer(self.api_key, self.base_url) if self.api_key else None
            
            for task in self.tasks:
                if not self.is_running:
                    break
                    
                index = task['index']
                video_path = task['path']
                filename = os.path.basename(video_path)
                base_name = os.path.splitext(filename)[0]
                
                # 1. Extract Audio
                self.status_signal.emit(index, "提取音频中...")
                audio_path = os.path.join(self.output_dir, f"{base_name}_audio.wav")
                
                success, error = extract_audio(video_path, audio_path)
                if not success:
                    self.status_signal.emit(index, f"音频提取失败: {error}")
                    continue
                    
                # 2. Transcribe
                self.status_signal.emit(index, "语音转写中(耗时较长)...")
                try:
                    text = transcriber.transcribe(audio_path)
                    
                    # Save Transcript
                    with open(os.path.join(self.output_dir, f"{base_name}_逐字稿.txt"), "w", encoding="utf-8") as f:
                        f.write(text)
                except Exception as e:
                    self.status_signal.emit(index, f"转写失败: {str(e)}")
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    continue

                # Clean up audio to save space
                if os.path.exists(audio_path):
                    os.remove(audio_path)

                # 3. Summarize
                if summarizer:
                    self.status_signal.emit(index, "生成摘要中...")
                    summary = summarizer.summarize(text)
                    with open(os.path.join(self.output_dir, f"{base_name}_摘要.txt"), "w", encoding="utf-8") as f:
                        f.write(summary)
                
                self.status_signal.emit(index, "处理完成")
                self.progress_signal.emit(index, 100)
                
        except Exception as e:
            print(f"Worker Error: {e}")
        
        self.finished_signal.emit()

    def stop(self):
        self.is_running = False
