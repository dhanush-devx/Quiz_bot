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
    questions = Column(JSON, nullable=False)  # Format: [{"q": "text", "o": ["A","B"], "a": 0}]
    group_id = Column(Integer, nullable=True)  # Added nullable group_id column


class Leaderboard(Base):
    __tablename__ = 'leaderboards'
    quiz_id = Column(Integer, primary_key=True)
    user_scores = Column(JSON, default={})  # Format: {"user_id": score}

def init_db():
    Base.metadata.create_all(engine)
