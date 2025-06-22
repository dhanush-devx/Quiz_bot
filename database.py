from sqlalchemy import create_engine, Column, Integer, String, JSON, Boolean
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from config import Config

Base = declarative_base()
engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
Session = scoped_session(sessionmaker(bind=engine))

class Quiz(Base):
    __tablename__ = 'quizzes'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    group_id = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    questions = Column(JSON, nullable=False)  # Format: [{"q": "text", "o": ["A","B"], "a": 0}]
    time_limit = Column(Integer, default=10)
    shuffle = Column(Boolean, default=False)

class Leaderboard(Base):
    __tablename__ = 'leaderboards'
    quiz_id = Column(Integer, primary_key=True)
    user_scores = Column(JSON, default={})  # Format: {"user_id": score}

def init_db():
    Base.metadata.create_all(engine)
