import logging
from telegram import Update, Poll
from telegram.ext import ContextTypes
from database import Session, Quiz, Leaderboard
from config import Config
import redis
from enum import IntEnum
from functools import wraps
import json

# --- Configuration & Constants ---
QUESTION_DURATION_SECONDS = 30  # How long each question stays open

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Redis Connection ---
# It's good practice to handle potential connection errors
try:
    redis_client = redis.Redis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        db=Config.REDIS_DB,
        password=Config.REDIS_PASSWORD,
        decode_responses=True  # Decode responses to strings
    )
    redis_client.ping()
    logger.info("Successfully connected to Redis.")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis: {e}")
    # Depending on the use case, you might want to exit or handle this differently
    redis_client = None

# --- Redis Key Utilities ---
def redis_key_active_quiz(chat_id): return f"active_quiz:{chat_id}"
def redis_key_poll_data(poll_id): return f"poll_data:{poll_id}"
def redis_key_leaderboard(quiz_id): return f"leaderboard:{quiz_id}"

# --- Quiz State Enum for quiz creation ---
class QuizState(IntEnum):
    AWAITING_TITLE = 1
    AWAITING_QUESTION = 2

# --- Admin Decorator ---
def admin_required(func):
    """Decorator to restrict command to admins."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not await _is_admin(update):
            if update.message:
                await update.message.reply_text("⛔️ This command is for admins only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Helper Functions ---
async def _is_admin(update: Update) -> bool:
    """Check if the user is a bot admin or a chat administrator."""
    if not update.effective_user:
        return False
    user_id = update.effective_user.id
    # Check against the global admin list from config
    if user_id in Config.ADMIN_IDS:
        return True
    # Check if the user is an admin in the chat (for group commands)
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        try:
            admins = await update.effective_chat.get_administrators()
            return any(admin.user.id == user_id for admin in admins)
        except Exception as e:
            logger.error(f"Failed to check chat admin status: {e}")
    return False

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown characters."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in str(text))

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message with instructions."""
    await update.message.reply_text(
        "🌟 *Welcome to the Quiz Bot!* �\n\n"
        "This bot lets you create and run quizzes in your groups.\n\n"
        "*Admin Commands:*\n"
        "`/create_quiz` - Start creating a new quiz (in a private chat with me).\n"
        "`/start_quiz <id>` - Begin a quiz in a group.\n"
        "`/stop_quiz` - Forcefully stop the active quiz in a group.\n"
        "`/reset_leaderboard <id>` - Clear the scores for a quiz.\n\n"
        "*User Commands:*\n"
        "`/leaderboard` - Show the scores for the current quiz.",
        parse_mode='MarkdownV2'
    )

@admin_required
async def create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate the quiz creation process (admin only, private chat)."""
    if update.effective_chat.type != "private":
        await update.message.reply_text("⚠️ Quiz creation should be done in a private chat with me to avoid spamming groups.")
        return

    context.user_data['quiz_creation'] = {'questions': []}
    context.user_data['state'] = QuizState.AWAITING_TITLE
    await update.message.reply_text("📝 Let's create a new quiz! First, what is the title of your quiz?")

async def handle_creation_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages during the quiz creation process."""
    if 'state' not in context.user_data:
        return

    state = context.user_data['state']
    quiz_data = context.user_data.get('quiz_creation', {})

    if state == QuizState.AWAITING_TITLE:
        quiz_data['title'] = update.message.text
        context.user_data['state'] = QuizState.AWAITING_QUESTION
        await update.message.reply_text(
            "✅ Title set! Now, please send me your questions.\n\n"
            "Create a poll, select **'Quiz mode'**, and choose the correct answer. Send them one by one.\n\n"
            "When you've added all your questions, send `/done`."
        )

async def handle_creation_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle polls sent during the quiz creation process."""
    if 'state' not in context.user_data or context.user_data['state'] != QuizState.AWAITING_QUESTION:
        return

    poll = update.message.poll
    if poll.type != Poll.QUIZ or poll.correct_option_id is None:
        await update.message.reply_text(
            "⚠️ That's not a valid quiz poll! Please make sure you create a poll in **Quiz Mode** and select a correct answer."
        )
        return

    quiz_data = context.user_data.get('quiz_creation', {'questions': []})
    quiz_data['questions'].append({
        "q": poll.question,
        "o": [option.text for option in poll.options],
        "a": poll.correct_option_id
    })
    
    question_count = len(quiz_data['questions'])
    await update.message.reply_text(
        f"✅ Question {question_count} added! Send another poll or type `/done` to finish."
    )

@admin_required
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize the quiz creation process."""
    if 'quiz_creation' not in context.user_data:
        await update.message.reply_text("❌ No active quiz creation process found. Start with `/create_quiz`.")
        return

    quiz_data = context.user_data['quiz_creation']
    if not quiz_data.get('questions'):
        await update.message.reply_text("❌ Your quiz has no questions! Please add at least one poll before finishing.")
        return

    session = Session()
    try:
        new_quiz = Quiz(title=quiz_data['title'], questions=quiz_data['questions'])
        session.add(new_quiz)
        session.commit()
        quiz_id = new_quiz.id
        
        message = (
            f"🎉 *Quiz Created Successfully\\!* 🎉\n\n"
            f"*Title:* {escape_markdown(new_quiz.title)}\n"
            f"*ID:* `{quiz_id}`\n\n"
            f"To start this quiz in a group, go to the group and use the command:\n"
            f"`/start_quiz {quiz_id}`"
        )
        await update.message.reply_text(message, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error saving quiz to database: {e}")
        await update.message.reply_text("❌ An error occurred while saving your quiz. Please try again.")
        session.rollback()
    finally:
        session.close()
        # Clean up user_data
        context.user_data.pop('quiz_creation', None)
        context.user_data.pop('state', None)

@admin_required
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a quiz in a group."""
    if not context.args:
        await update.message.reply_text("ℹ️ Please provide a Quiz ID. Usage: `/start_quiz <quiz_id>`")
        return
    
    chat_id = update.effective_chat.id
    if redis_client and redis_client.get(redis_key_active_quiz(chat_id)):
        await update.message.reply_text("⚠️ A quiz is already running in this chat. Use `/stop_quiz` to end it first.")
        return
        
    quiz_id = context.args[0]
    session = Session()
    try:
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        if not quiz:
            await update.message.reply_text("❌ Quiz not found. Please check the ID.")
            return

        if not quiz.questions:
            await update.message.reply_text("❌ This quiz has no questions and cannot be started.")
            return
        
        # Set the active quiz in Redis
        if redis_client:
            redis_client.set(redis_key_active_quiz(chat_id), quiz.id)
        
        await update.message.reply_text(f"🚀 The quiz '{quiz.title}' is about to begin! First question in 3 seconds...")
        
        # Schedule the first question
        context.job_queue.run_once(
            _send_question,
            when=3,
            data={'chat_id': chat_id, 'quiz_id': quiz.id, 'q_index': 0},
            name=f"quiz_{chat_id}"
        )
    finally:
        session.close()

async def _send_question(context: ContextTypes.DEFAULT_TYPE):
    """Sends a question poll and schedules the next action."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    quiz_id = job_data['quiz_id']
    q_index = job_data['q_index']

    session = Session()
    try:
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        if not quiz or q_index >= len(quiz.questions):
            # This case handles if the quiz is deleted mid-run
            await _end_quiz(context, chat_id, quiz_id)
            return

        question_data = quiz.questions[q_index]
        message = await context.bot.send_poll(
            chat_id=chat_id,
            question=f"Question {q_index + 1}/{len(quiz.questions)}\n\n{question_data['q']}",
            options=question_data['o'],
            type=Poll.QUIZ,
            correct_option_id=question_data['a'],
            is_anonymous=False,
            open_period=QUESTION_DURATION_SECONDS
        )
        
        # Store poll data in Redis to link answers back to the quiz
        if redis_client:
            poll_info = {'quiz_id': quiz_id, 'chat_id': chat_id, 'correct_option': question_data['a']}
            redis_client.set(redis_key_poll_data(message.poll.id), json.dumps(poll_info), ex=QUESTION_DURATION_SECONDS + 10)

        # Schedule the job to end this question and send the next one
        context.job_queue.run_once(
            _end_question,
            when=QUESTION_DURATION_SECONDS,
            data={'chat_id': chat_id, 'quiz_id': quiz_id, 'q_index': q_index + 1, 'poll_id': message.poll.id, 'message_id': message.message_id},
            name=f"quiz_{chat_id}"
        )
    except Exception as e:
        logger.error(f"Error sending question: {e}")
    finally:
        session.close()

async def _end_question(context: ContextTypes.DEFAULT_TYPE):
    """Stops the poll, announces the answer, and triggers the next question or ends the quiz."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    quiz_id = job_data['quiz_id']
    next_q_index = job_data['q_index']
    poll_id = job_data['poll_id']
    message_id = job_data['message_id']

    # Stop the previous poll
    try:
        await context.bot.stop_poll(chat_id, message_id)
    except Exception as e:
        logger.warning(f"Could not stop poll (it might have been closed already): {e}")

    session = Session()
    try:
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        if not quiz:
            return

        # Check if there are more questions
        if next_q_index < len(quiz.questions):
            # Schedule the next question
            context.job_queue.run_once(
                _send_question,
                when=3, # 3-second delay between questions
                data={'chat_id': chat_id, 'quiz_id': quiz_id, 'q_index': next_q_index},
                name=f"quiz_{chat_id}"
            )
        else:
            # End of the quiz
            await context.bot.send_message(chat_id, "🏁 The quiz has finished! 🏁")
            await _end_quiz(context, chat_id, quiz_id)
    finally:
        session.close()

async def _end_quiz(context, chat_id, quiz_id):
    """Cleans up Redis and shows the final leaderboard."""
    if redis_client:
        redis_client.delete(redis_key_active_quiz(chat_id))
    
    # Use a new update object for the leaderboard command context
    class MockUpdate:
        class MockMessage:
            class MockChat:
                id = chat_id
            chat = MockChat()
        message = MockMessage()
        effective_chat = message.chat

    await leaderboard(MockUpdate(), context, quiz_id_override=quiz_id)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process a user's answer to a quiz poll and update their score."""
    if not redis_client: return

    answer = update.poll_answer
    poll_data_str = redis_client.get(redis_key_poll_data(answer.poll_id))
    
    if not poll_data_str:
        return # This poll is not part of an active quiz

    poll_data = json.loads(poll_data_str)
    quiz_id = poll_data['quiz_id']
    correct_option = poll_data['correct_option']

    if answer.option_ids and answer.option_ids[0] == correct_option:
        user_id = str(answer.user.id)
        session = Session()
        try:
            lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
            if not lb:
                lb = Leaderboard(quiz_id=quiz_id, user_scores={})
                session.add(lb)
            
            # Use SQLAlchemy's automatic JSON mutation tracking
            new_scores = dict(lb.user_scores)
            new_scores[user_id] = new_scores.get(user_id, 0) + 1
            lb.user_scores = new_scores
            
            session.commit()
            # Invalidate leaderboard cache
            redis_client.delete(redis_key_leaderboard(quiz_id))
        except Exception as e:
            logger.error(f"Error updating leaderboard: {e}")
            session.rollback()
        finally:
            session.close()

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id_override=None):
    """Display the leaderboard for the active or specified quiz."""
    chat_id = update.effective_chat.id
    quiz_id = quiz_id_override or (redis_client.get(redis_key_active_quiz(chat_id)) if redis_client else None)
    
    if not quiz_id:
        await context.bot.send_message(chat_id, "ℹ️ There is no active quiz in this chat.")
        return
    
    # Check cache first
    cache_key = redis_key_leaderboard(quiz_id)
    if redis_client and redis_client.exists(cache_key):
        cached_leaderboard = redis_client.get(cache_key)
        await context.bot.send_message(chat_id, cached_leaderboard, parse_mode='MarkdownV2')
        return
    
    session = Session()
    try:
        lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()

        if not lb or not lb.user_scores:
            await context.bot.send_message(chat_id, "📊 The leaderboard is empty!")
            return
        
        sorted_scores = sorted(lb.user_scores.items(), key=lambda item: item[1], reverse=True)
        
        leaderboard_lines = [f"🏆 *Leaderboard for: {escape_markdown(quiz.title)}* 🏆\n"]
        for idx, (user_id, score) in enumerate(sorted_scores[:10]): # Top 10
            try:
                member = await context.bot.get_chat_member(chat_id, int(user_id))
                name = escape_markdown(member.user.full_name)
            except Exception:
                name = f"User {user_id}"
            leaderboard_lines.append(f"*{idx + 1}\\.* {name}: *{score}*")
            
        leaderboard_text = "\n".join(leaderboard_lines)
        
        if redis_client:
            redis_client.setex(cache_key, 300, leaderboard_text) # Cache for 5 minutes
            
        await context.bot.send_message(chat_id, leaderboard_text, parse_mode='MarkdownV2')
    finally:
        session.close()

@admin_required
async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forcefully stops the current quiz in a chat."""
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(f"quiz_{chat_id}")
    if not jobs:
        await update.message.reply_text("ℹ️ No quiz is currently running in this chat.")
        return

    for job in jobs:
        job.schedule_removal()

    quiz_id = redis_client.get(redis_key_active_quiz(chat_id)) if redis_client else None
    await update.message.reply_text("🛑 The quiz has been manually stopped by an admin.")
    if quiz_id:
        await _end_quiz(context, chat_id, quiz_id)

@admin_required
async def reset_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the leaderboard for a specific quiz."""
    if not context.args:
        await update.message.reply_text("ℹ️ Please provide a Quiz ID. Usage: `/reset_leaderboard <quiz_id>`")
        return
    
    quiz_id = context.args[0]
    session = Session()
    try:
        lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
        if lb:
            lb.user_scores = {}
            session.commit()
            if redis_client:
                redis_client.delete(redis_key_leaderboard(quiz_id))
            await update.message.reply_text(f"✅ Leaderboard for quiz `{quiz_id}` has been reset.")
        else:
            await update.message.reply_text(f"ℹ️ No leaderboard found for quiz `{quiz_id}`.")
    except Exception as e:
        logger.error(f"Error resetting leaderboard: {e}")
        session.rollback()
        await update.message.reply_text("❌ An error occurred while resetting the leaderboard.")
    finally:
        session.close()
