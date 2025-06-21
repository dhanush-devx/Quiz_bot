from sqlalchemy import create_engine, Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from config import Config

Base = declarative_base()
engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, echo=True, future=True)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

class Quiz(Base):
    __tablename__ = 'quizzes'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    questions = Column(JSON, nullable=False)  # Format: [{"q": "Question?", "o": ["A","B"], "a": 0}]
    group_id = Column(String(50), nullable=False)

class Leaderboard(Base):
    __tablename__ = 'leaderboards'
    quiz_id = Column(Integer, ForeignKey('quizzes.id'), primary_key=True)
    user_scores = Column(JSON, default=dict)  # Format: {"user_id": score}

def init_db():
    Base.metadata.create_all(engine)
