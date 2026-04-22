"""
Whisper model loader - Singleton pattern
"""
from faster_whisper import WhisperModel
from config import USE_CELERY

model = None

def get_model():
    """Get or create Whisper model instance"""
    global model
    if model is None and not USE_CELERY:
        print("Loading Faster-Whisper Model (tiny, int8)...")
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return model
