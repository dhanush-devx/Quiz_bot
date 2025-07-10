import os

class Config:
    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # PostgreSQL
    DB_HOST = os.getenv("DB_HOST", "postgres")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_USER = os.getenv("DB_USER", "quizbot")
    DB_PASS = os.getenv("DB_PASS")
    DB_NAME = os.getenv("DB_NAME", "quizbot_prod")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    
    # Redis
    _raw_redis_host = os.getenv("REDIS_HOST", "redis")
    _raw_redis_port = os.getenv("REDIS_PORT", "6379")

    # If _raw_redis_host contains the port, split it
    if ':' in _raw_redis_host and not _raw_redis_host.startswith('redis://'):  # Avoid splitting if it's a Redis URL
        _split_host = _raw_redis_host.split(':')
        REDIS_HOST = _split_host[0]
        REDIS_PORT = int(_split_host[1])
    else:
        REDIS_HOST = _raw_redis_host
        REDIS_PORT = int(_raw_redis_port)

    REDIS_DB = int(os.getenv("REDIS_DB", 0))
    
    # Admin IDs (comma-separated)
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
