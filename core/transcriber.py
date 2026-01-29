import whisper
import os

class Transcriber:
    _instance = None
    
    def __new__(cls, model_size="base"):
        if cls._instance is None:
            cls._instance = super(Transcriber, cls).__new__(cls)
            cls._instance.model_size = model_size
            cls._instance.model = None
        return cls._instance

    def load_model(self):
        if not self.model:
            print(f"Loading Whisper model ({self.model_size})... this may take a while.")
            self.model = whisper.load_model(self.model_size)
            print("Whisper model loaded.")

    def transcribe(self, audio_path):
        self.load_model()
        
        # Check if audio file exists
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        result = self.model.transcribe(audio_path)
        return result # Return full dict containing 'text' and 'segments'
