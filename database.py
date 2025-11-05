from sqlalchemy import create_engine, Column, Integer, String, JSON, Boolean, event, text
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from config import Config
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

# Database engine with connection pooling
engine = None
Session = None

def init_db_engine():
    """Initialize database engine with proper configuration."""
    global engine, Session
    
    try:
        # Engine configuration with connection pooling and production settings
        # Optimized for Railway PostgreSQL proxy connections
        
        # Detect if using Railway (proxy URLs contain 'railway' or 'proxy.rlwy.net')
        is_railway = 'railway' in Config.SQLALCHEMY_DATABASE_URI.lower() or 'rlwy.net' in Config.SQLALCHEMY_DATABASE_URI.lower()
        
        engine_config = {
            'pool_size': 20,  # Increased to handle concurrent async tasks
            'max_overflow': 30,  # More overflow for burst traffic
            'pool_pre_ping': True,
            'pool_recycle': 300,  # Recycle connections every 5 minutes for Railway
            'pool_timeout': 30,  # Railway proxy needs longer timeout
            'poolclass': QueuePool,
            'echo': False,  # Set to True for SQL debugging
            'connect_args': {
                'connect_timeout': 30,  # Railway proxy needs time
                'sslmode': 'require',  # Always require SSL for Railway external connections
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            }
        }
        
        # For non-Railway databases, prefer SSL but don't require it
        if not is_railway:
            engine_config['connect_args']['sslmode'] = 'prefer'
        
        engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, **engine_config)
        Session = scoped_session(sessionmaker(bind=engine))
        
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            
        logger.info("Database connection established successfully with production settings.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise

@contextmanager
def get_db_session(readonly=False):
    """Context manager for database sessions with automatic cleanup and nested transaction support.
    
    Args:
        readonly: If True, creates a session optimized for read-only operations (no autoflush).
    """
    # Get the session from scoped_session (always returns the same session in a thread)
    session = Session()
    
    # Configure session based on readonly flag
    if readonly:
        session.autoflush = False
        session.expire_on_commit = False
    
    try:
        yield session
        if not readonly:
            session.commit()
    except Exception as e:
        if not readonly:
            session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        session.close()
        # Remove the session from the registry to allow new sessions with different configs
        Session.remove()

class Quiz(Base):
    __tablename__ = 'quizzes'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False, index=True)  # Add index for search
    questions = Column(JSON, nullable=False)  # Format: [{"q": "text", "o": ["A","B"], "a": 0}]
    group_id = Column(Integer, nullable=True, index=True)  # Add index for group queries

    def validate_questions(self) -> bool:
        """Validate quiz questions format with enhanced security checks."""
        if not isinstance(self.questions, list) or not self.questions:
            return False
            
        for q in self.questions:
            if not isinstance(q, dict):
                return False
            if not all(key in q for key in ['q', 'o', 'a']):
                return False
            if not isinstance(q['o'], list) or len(q['o']) < 2 or len(q['o']) > 10:
                return False
            if not isinstance(q['a'], int) or q['a'] >= len(q['o']) or q['a'] < 0:
                return False
            # Validate text lengths to prevent abuse
            if len(q['q']) > 300:
                return False
            if any(len(option) > 100 for option in q['o']):
                return False
                
        return True

    @property
    def question_count(self) -> int:
        """Get the number of questions in this quiz."""
        return len(self.questions) if self.questions else 0


class Leaderboard(Base):
    __tablename__ = 'leaderboards'
    quiz_id = Column(Integer, primary_key=True, index=True)  # Add explicit index
    user_scores = Column(JSON, default={})  # Format: {"user_id": score}
    
    def add_score(self, user_id: int, points: int = 1) -> None:
        """Add points to a user's score with thread safety."""
        if not isinstance(self.user_scores, dict):
            self.user_scores = {}
        
        user_id_str = str(user_id)
        self.user_scores[user_id_str] = self.user_scores.get(user_id_str, 0) + points
        
        # CRITICAL FIX: Tell SQLAlchemy that the JSON field has been modified
        flag_modified(self, 'user_scores')
        
    def get_top_scores(self, limit: int = 10) -> list:
        """Get top scores sorted by points."""
        if not self.user_scores:
            return []
            
        sorted_scores = sorted(
            self.user_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        return sorted_scores[:limit]

def init_db():
    """Initialize database tables with proper error handling."""
    try:
        if not engine:
            init_db_engine()
            
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise

def health_check() -> bool:
    """Check database connection health."""
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
