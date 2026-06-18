import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
DB_PATH = os.getenv("DB_PATH", "qfxm.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SEND_DELAY_MIN = float(os.getenv("SEND_DELAY_MIN", "3"))
SEND_DELAY_MAX = float(os.getenv("SEND_DELAY_MAX", "15"))
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)
