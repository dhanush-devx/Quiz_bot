import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class Config:
    # Telegram
    BOT_TOKEN = os.getenv("8187052777:AAGUmozz_nvFrtItvpOWasMNfNzdOfo9gZc")
    
    # Database
    DB_USER = os.getenv("DB_USER", "quizbot")
    DB_PASS = os.getenv("DB_PASS", "secure_password")
    DB_HOST = os.getenv("DB_HOST", "postgres")
    DB_NAME = os.getenv("DB_NAME", "quizbot_prod")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
    
    # Redis - Disabled as per user request
    REDIS_HOST = None
    REDIS_PORT = None
    REDIS_DB = None
    
    # Admin IDs (comma separated)
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
