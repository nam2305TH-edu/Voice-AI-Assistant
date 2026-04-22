import os
from dotenv import load_dotenv

# Tắt cảnh báo TensorFlow/oneDNN
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Chỉ hiện ERROR, không hiện INFO/WARNING

load_dotenv()

USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"

#local main and streaming to server 
REDIS_BROKER = "redis://localhost:6379/0"
REDIS_BACKEND = "redis://localhost:6379/1"

# duration
_SAMPLE_ = 16000
_MIN_ = 0.3
_MAX_ = 1.5  # Giảm từ 2.0 xuống 1.5 để transcribe nhanh hơn
_SILENCE_THRESHOLD_ = 0.002  # Tăng threshold để phát hiện im lặng nhanh hơn  
_SILENCE_DURATION_ = 0.4     # Giảm từ 0.5 xuống 0.4
_MIN_VOICE_ = 0.002  # Tăng để lọc noise tốt hơn   

# API Keys
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Telegram Notification
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Data Cleanup
MAX_DATA_SIZE_MB = float(os.getenv("MAX_DATA_SIZE_MB", "1024"))  
CLEANUP_DAYS = int(os.getenv("CLEANUP_DAYS", "30"))  
DATA_DIR = os.getenv("DATA_DIR", "./data")