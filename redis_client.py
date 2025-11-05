import redis
import json
import logging
import time
from typing import Optional, Any, Dict
from config import Config

logger = logging.getLogger(__name__)

class RedisClient:
    """Redis client wrapper with connection pooling and enhanced error handling."""
    
    def __init__(self):
        self.pool: Optional[redis.ConnectionPool] = None
        self.client: Optional[redis.Redis] = None
        self.is_available = False
        self.last_connection_attempt = 0
        self.connection_retry_delay = 5  # Seconds between reconnection attempts
        self._connect()
    
    def _connect(self):
        """Establish Redis connection with connection pooling and error handling."""
        current_time = time.time()
        
        # Implement exponential backoff for reconnection attempts
        if (current_time - self.last_connection_attempt) < self.connection_retry_delay:
            return
            
        self.last_connection_attempt = current_time
        
        try:
            # Check if we have REDIS_URL (Heroku Redis, Railway Redis) or individual settings
            if hasattr(Config, 'REDIS_URL') and Config.REDIS_URL:
                # Detect if using Railway proxy
                is_railway = 'rlwy.net' in Config.REDIS_URL or 'railway' in Config.REDIS_URL.lower()
                
                # For redis-py v5+, SSL is automatically handled via rediss:// URL scheme
                # No need to pass ssl=True explicitly
                
                # Use Redis URL with Railway-optimized settings
                self.client = redis.from_url(
                    Config.REDIS_URL,
                    max_connections=20,
                    retry_on_timeout=True,
                    socket_connect_timeout=30 if is_railway else 5,  # Railway needs longer timeout
                    socket_timeout=30 if is_railway else 5,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        1: 1,  # TCP_KEEPIDLE
                        2: 30,  # TCP_KEEPINTVL  
                        3: 5,  # TCP_KEEPCNT
                    } if is_railway else None,
                    decode_responses=True,
                    health_check_interval=Config.REDIS_HEALTH_CHECK_INTERVAL if hasattr(Config, 'REDIS_HEALTH_CHECK_INTERVAL') else 30
                )
            else:
                # Use individual Redis settings (local development)
                self.pool = redis.ConnectionPool(
                    host=Config.REDIS_HOST,
                    port=Config.REDIS_PORT,
                    db=Config.REDIS_DB,
                    password=Config.REDIS_PASSWORD,
                    max_connections=20,
                    retry_on_timeout=True,
                    socket_connect_timeout=30,
                    socket_timeout=30,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        1: 1,
                        2: 10,
                        3: 5
                    },
                    decode_responses=True
                )
                
                self.client = redis.Redis(
                    connection_pool=self.pool,
                    health_check_interval=Config.REDIS_HEALTH_CHECK_INTERVAL if hasattr(Config, 'REDIS_HEALTH_CHECK_INTERVAL') else 30
                )
            
            # Test connection
            self.client.ping()
            self.is_available = True
            self.connection_retry_delay = 5  # Reset retry delay on successful connection
            logger.info("Successfully connected to Redis with connection pooling.")
            
        except redis.exceptions.ConnectionError as e:
            self.is_available = False
            self.connection_retry_delay = min(self.connection_retry_delay * 2, 60)  # Exponential backoff, max 60s
            logger.warning(f"Could not connect to Redis: {e}. Will retry in {self.connection_retry_delay}s. Operating without cache.")
        except Exception as e:
            self.is_available = False
            self.connection_retry_delay = min(self.connection_retry_delay * 2, 60)
            logger.error(f"Unexpected Redis error: {e}")
    
    def _execute_safely(self, operation, *args, **kwargs) -> Any:
        """Execute Redis operation with error handling and automatic reconnection."""
        if not self.is_available or not self.client:
            return None
            
        try:
            return operation(*args, **kwargs)
        except redis.exceptions.ConnectionError:
            logger.warning("Redis connection lost. Attempting to reconnect...")
            self._connect()
            if self.is_available:
                try:
                    return operation(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Redis operation failed after reconnect: {e}")
            return None
        except Exception as e:
            logger.error(f"Redis operation error: {e}")
            return None
    
    def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        return self._execute_safely(self.client.get, key)
    
    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set value in Redis with optional expiration."""
        result = self._execute_safely(self.client.set, key, value, ex=ex)
        return result is not None
    
    def setex(self, key: str, time: int, value: str) -> bool:
        """Set value with expiration time."""
        result = self._execute_safely(self.client.setex, key, time, value)
        return result is not None
    
    def delete(self, *keys: str) -> int:
        """Delete keys from Redis."""
        result = self._execute_safely(self.client.delete, *keys)
        return result if result is not None else 0
    
    def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        result = self._execute_safely(self.client.exists, key)
        return bool(result) if result is not None else False
    
    def set_json(self, key: str, value: Dict, ex: Optional[int] = None) -> bool:
        """Set JSON value in Redis with enhanced error handling."""
        try:
            json_str = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
            return self.set(key, json_str, ex=ex)
        except (TypeError, ValueError, OverflowError) as e:
            logger.error(f"Failed to serialize JSON for key {key}: {e}")
            return False
    
    def get_json(self, key: str) -> Optional[Dict]:
        """Get JSON value from Redis with enhanced error handling."""
        value = self.get(key)
        if value is None:
            return None
            
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error(f"Failed to deserialize JSON for key {key}: {e}")
            # Clean up corrupted data
            self.delete(key)
            return None
    
    def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            if not self.client:
                return False
            self.client.ping()
            return True
        except Exception:
            self.is_available = False
            return False

# Global Redis client instance
redis_client = RedisClient()

# Utility functions for Redis keys
def redis_key_active_quiz(chat_id: int) -> str:
    """Generate Redis key for active quiz."""
    return f"active_quiz:{chat_id}"

def redis_key_poll_data(poll_id: str) -> str:
    """Generate Redis key for poll data."""
    return f"poll_data:{poll_id}"

def redis_key_leaderboard(quiz_id: int) -> str:
    """Generate Redis key for leaderboard cache."""
    return f"leaderboard:{quiz_id}"

def redis_key_user_session(user_id: int) -> str:
    """Generate Redis key for user session data."""
    return f"user_session:{user_id}"