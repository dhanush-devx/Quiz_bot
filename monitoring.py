import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass
from redis_client import redis_client

logger = logging.getLogger(__name__)

@dataclass
class BotMetrics:
    """Bot performance metrics."""
    total_quizzes_created: int = 0
    total_quizzes_started: int = 0
    total_questions_answered: int = 0
    active_quizzes: int = 0
    total_users: int = 0
    uptime_start: datetime = None
    
    def __post_init__(self):
        if self.uptime_start is None:
            self.uptime_start = datetime.now()

class MetricsCollector:
    """Collect and store bot metrics."""
    
    def __init__(self):
        self.metrics = BotMetrics()
        self.metrics_prefix = "bot_metrics:"
        
    def increment_quizzes_created(self):
        """Increment quiz creation counter."""
        self.metrics.total_quizzes_created += 1
        self._store_metric("quizzes_created", self.metrics.total_quizzes_created)
        
    def increment_quizzes_started(self):
        """Increment quiz start counter."""
        self.metrics.total_quizzes_started += 1
        self._store_metric("quizzes_started", self.metrics.total_quizzes_started)
        
    def increment_questions_answered(self):
        """Increment questions answered counter."""
        self.metrics.total_questions_answered += 1
        self._store_metric("questions_answered", self.metrics.total_questions_answered)
        
    def set_active_quizzes(self, count: int):
        """Set active quiz count."""
        self.metrics.active_quizzes = count
        self._store_metric("active_quizzes", count)
        
    def add_user(self, user_id: int):
        """Track unique user."""
        key = f"{self.metrics_prefix}users"
        if redis_client.is_available:
            # Use Redis set to track unique users
            redis_client._execute_safely(redis_client.client.sadd, key, str(user_id))
            count = redis_client._execute_safely(redis_client.client.scard, key)
            if count:
                self.metrics.total_users = count
    
    def _store_metric(self, metric_name: str, value: int):
        """Store metric in Redis."""
        if redis_client.is_available:
            key = f"{self.metrics_prefix}{metric_name}"
            redis_client.set(key, str(value))
    
    def _load_metric(self, metric_name: str, default: int = 0) -> int:
        """Load metric from Redis."""
        if redis_client.is_available:
            key = f"{self.metrics_prefix}{metric_name}"
            value = redis_client.get(key)
            if value:
                try:
                    return int(value)
                except ValueError:
                    pass
        return default
    
    def load_metrics(self):
        """Load metrics from storage."""
        self.metrics.total_quizzes_created = self._load_metric("quizzes_created")
        self.metrics.total_quizzes_started = self._load_metric("quizzes_started")
        self.metrics.total_questions_answered = self._load_metric("questions_answered")
        self.metrics.active_quizzes = self._load_metric("active_quizzes")
        
        # Load user count
        if redis_client.is_available:
            key = f"{self.metrics_prefix}users"
            count = redis_client._execute_safely(redis_client.client.scard, key)
            if count:
                self.metrics.total_users = count
    
    def get_uptime(self) -> str:
        """Get bot uptime as formatted string."""
        uptime = datetime.now() - self.metrics.uptime_start
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    def get_metrics_summary(self) -> Dict:
        """Get comprehensive metrics summary."""
        return {
            "total_quizzes_created": self.metrics.total_quizzes_created,
            "total_quizzes_started": self.metrics.total_quizzes_started,
            "total_questions_answered": self.metrics.total_questions_answered,
            "active_quizzes": self.metrics.active_quizzes,
            "total_users": self.metrics.total_users,
            "uptime": self.get_uptime(),
            "uptime_start": self.metrics.uptime_start.isoformat()
        }

# Global metrics collector
metrics = MetricsCollector()

def track_command_usage(command_name: str, user_id: int, chat_id: int):
    """Track command usage for analytics."""
    try:
        # Track user
        metrics.add_user(user_id)
        
        # Store command usage with timestamp
        if redis_client.is_available:
            timestamp = int(time.time())
            key = f"command_usage:{command_name}:{timestamp // 3600}"  # Hour buckets
            redis_client._execute_safely(redis_client.client.incr, key)
            redis_client._execute_safely(redis_client.client.expire, key, 86400 * 7)  # Keep for 7 days
            
    except Exception as e:
        logger.error(f"Error tracking command usage: {e}")

def get_command_stats(hours: int = 24) -> Dict:
    """Get command usage statistics for the last N hours."""
    stats = {}
    try:
        if not redis_client.is_available:
            return stats
            
        current_hour = int(time.time()) // 3600
        for i in range(hours):
            hour = current_hour - i
            pattern = f"command_usage:*:{hour}"
            keys = redis_client._execute_safely(redis_client.client.keys, pattern)
            
            if keys:
                for key in keys:
                    parts = key.split(':')
                    if len(parts) >= 3:
                        command = parts[1]
                        count = redis_client._execute_safely(redis_client.client.get, key)
                        if count:
                            stats[command] = stats.get(command, 0) + int(count)
                            
    except Exception as e:
        logger.error(f"Error getting command stats: {e}")
        
    return stats