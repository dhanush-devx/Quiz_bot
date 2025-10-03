import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

class Config:
    # Telegram
    BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
    
    # PostgreSQL
    DB_HOST: str = os.getenv("DB_HOST", "postgres")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_USER: str = os.getenv("DB_USER", "quizbot")
    DB_PASS: Optional[str] = os.getenv("DB_PASS")
    DB_NAME: str = os.getenv("DB_NAME", "quizbot_prod")
    
    # Build database URL with proper validation
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    if not DATABASE_URL and DB_PASS:
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    elif not DATABASE_URL:
        DATABASE_URL = None
    
    # Validate database configuration
    SQLALCHEMY_DATABASE_URI: Optional[str] = DATABASE_URL
    
    # Redis
    _raw_redis_host: str = os.getenv("REDIS_HOST", "redis")
    _raw_redis_port: str = os.getenv("REDIS_PORT", "6379")

    # Parse Redis host and port safely
    if ':' in _raw_redis_host and not _raw_redis_host.startswith('redis://'):
        try:
            _split_host = _raw_redis_host.split(':')
            REDIS_HOST: str = _split_host[0]
            REDIS_PORT: int = int(_split_host[1])
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid Redis host format: {_raw_redis_host}, using defaults")
            REDIS_HOST = "redis"
            REDIS_PORT = 6379
    else:
        REDIS_HOST = _raw_redis_host
        try:
            REDIS_PORT = int(_raw_redis_port)
        except ValueError:
            logger.warning(f"Invalid Redis port: {_raw_redis_port}, using default 6379")
            REDIS_PORT = 6379

    try:
        REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    except ValueError:
        logger.warning("Invalid REDIS_DB value, using default 0")
        REDIS_DB = 0
        
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    
    # Admin IDs with better error handling
    _admin_ids_str: str = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS: List[int] = []
    if _admin_ids_str:
        for id_str in _admin_ids_str.split(","):
            id_str = id_str.strip()
            if id_str:
                try:
                    ADMIN_IDS.append(int(id_str))
                except ValueError:
                    logger.warning(f"Invalid admin ID: {id_str}, skipping")
    
    # App configuration with environment-aware defaults
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
    QUESTION_DURATION_SECONDS: int = int(os.getenv("QUESTION_DURATION_SECONDS", "30"))
    MAX_QUESTIONS_PER_QUIZ: int = int(os.getenv("MAX_QUESTIONS_PER_QUIZ", "50"))
    MAX_QUIZ_TITLE_LENGTH: int = int(os.getenv("MAX_QUIZ_TITLE_LENGTH", "255"))
    LEADERBOARD_CACHE_TTL: int = int(os.getenv("LEADERBOARD_CACHE_TTL", "300"))  # 5 minutes
    MAX_LEADERBOARD_ENTRIES: int = int(os.getenv("MAX_LEADERBOARD_ENTRIES", "10"))
    REDIS_HEALTH_CHECK_INTERVAL: int = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))
    
    # Production vs Development settings
    DEBUG = ENVIRONMENT == "development"
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration and return True if valid."""
        errors = []
        warnings = []
        
        # Critical validations
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN environment variable is required")
            
        if not cls.SQLALCHEMY_DATABASE_URI:
            errors.append("Database configuration is incomplete")
            
        # Validate numeric configurations
        try:
            if cls.QUESTION_DURATION_SECONDS < 10 or cls.QUESTION_DURATION_SECONDS > 300:
                warnings.append(f"QUESTION_DURATION_SECONDS ({cls.QUESTION_DURATION_SECONDS}) should be between 10-300 seconds")
                
            if cls.MAX_QUESTIONS_PER_QUIZ < 1 or cls.MAX_QUESTIONS_PER_QUIZ > 100:
                warnings.append(f"MAX_QUESTIONS_PER_QUIZ ({cls.MAX_QUESTIONS_PER_QUIZ}) should be between 1-100")
                
        except (ValueError, TypeError) as e:
            errors.append(f"Invalid numeric configuration: {e}")
            
        # Environment-specific validations
        if cls.ENVIRONMENT == "production":
            if not cls.ADMIN_IDS:
                warnings.append("No admin IDs configured for production environment")
                
            if cls.DEBUG:
                warnings.append("Debug mode enabled in production - consider disabling")
                
            if not cls.RATE_LIMIT_ENABLED:
                warnings.append("Rate limiting disabled in production - not recommended")
        
        # Redis configuration warnings
        if not cls.REDIS_HOST:
            warnings.append("Redis not configured - bot will run without caching")
            
        # Log results
        for warning in warnings:
            logger.warning(warning)
            
        if errors:
            for error in errors:
                logger.error(error)
            return False
            
        logger.info(f"Configuration validation passed for {cls.ENVIRONMENT} environment")
        return True
