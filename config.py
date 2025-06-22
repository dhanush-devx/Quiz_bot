import os
from dotenv import load_dotenv

# Load .env file explicitly from the root directory
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

class Config:
    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_PROD_TOKEN")
    
    # Database
    DB_USER = os.getenv("DB_USER", "quizbot")
    DB_PASS = os.getenv("DB_PASS", "secure_password")
    DB_HOST = os.getenv("DB_HOST", "postgres")
    DB_NAME = os.getenv("DB_NAME", "quizbot_prod")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
    
    # Redis
    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = os.getenv("REDIS_PORT", 6379)
    REDIS_DB = os.getenv("REDIS_DB", 0)
    
    # Admin IDs (comma separated)
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]