import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Poll
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, PollAnswerHandler
from database import Session, Quiz, Leaderboard
from config import Config
import redis
from enum import IntEnum
from functools import wraps

# Redis connection
redis_client = redis.Redis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=Config.REDIS_DB
)

# --- Redis Key Utilities ---
def redis_key_active_quiz(chat_id): return f"active_quiz:{chat_id}"
def redis_key_poll_mapping(poll_id): return f"poll:{poll_id}"
def redis_key_progress(quiz_id, chat_id): return f"quiz_progress:{quiz_id}:{chat_id}"
def redis_key_leaderboard(quiz_id): return f"leaderboard:{quiz_id}"

# --- Quiz State Enum ---
class QuizState(IntEnum):
    AWAITING_TITLE = 1
    AWAITING_QUESTION = 2

# --- Admin Decorator ---
def admin_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not await _is_admin(update):
            await update.message.reply_text("⛔️ Admin access required!")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    await update.message.reply_text(
        "🌟 **QuizBot Activated!** 🌟\n\n"
        "Admin commands:\n"
        "→ /create_quiz - Create new quizzes\n"
        "→ /start_quiz - Start quizzes in groups\n"
        "→ /reset_leaderboard - Reset scores\n\n"
        "User commands:\n"
        "→ /leaderboard - View rankings"
    )

@admin_required
async def create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate quiz creation in private chat"""
    if not (update and hasattr(update, 'message') and update.message and hasattr(update, 'effective_chat') and update.effective_chat and update.effective_chat.type == "private"):
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text("⚠️ Quiz creation only available in private chat with bot")
        return
    if not hasattr(context, 'user_data') or not isinstance(context.user_data, dict):
        context.user_data = {}
    context.user_data['quiz_creation'] = {'questions': []}
    context.user_data['state'] = QuizState.AWAITING_TITLE
    await update.message.reply_text("📝 Enter quiz title:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz creation states"""
    if not (update and hasattr(update, 'message') and update.message and hasattr(update.message, 'text') and update.message.text is not None):
        return
    if not hasattr(context, 'user_data') or not isinstance(context.user_data, dict):
        context.user_data = {}
    state = context.user_data.get('state')
    quiz_data = context.user_data.get('quiz_creation')
    if not isinstance(quiz_data, dict):
        quiz_data = {'questions': []}
        context.user_data['quiz_creation'] = quiz_data
    if 'questions' not in quiz_data or not isinstance(quiz_data['questions'], list):
        quiz_data['questions'] = []
    if state == QuizState.AWAITING_TITLE:
        quiz_data['title'] = update.message.text
        context.user_data['state'] = QuizState.AWAITING_QUESTION
        await update.message.reply_text(
            "📝 Create a quiz-mode poll directly (not forward) with options and a correct answer.\n"
            "Send /done when finished."
        )    
    elif state == QuizState.AWAITING_QUESTION:
        if update.message.text and update.message.text.lower() in ["/done", "done"]:
            await done(update, context)
        else:
            await update.message.reply_text(
                "Please send a poll question in quiz mode or send /done to finish."
            )

async def handle_poll_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll input for quiz creation"""
    if not (update and hasattr(update, 'message') and update.message and hasattr(update, 'effective_chat') and update.effective_chat):
        return
    if not hasattr(context, 'user_data') or not isinstance(context.user_data, dict):
        context.user_data = {}
    state = context.user_data.get('state')
    quiz_data = context.user_data.get('quiz_creation')
    if not isinstance(quiz_data, dict):
        quiz_data = {'questions': []}
        context.user_data['quiz_creation'] = quiz_data
    if 'questions' not in quiz_data or not isinstance(quiz_data['questions'], list):
        quiz_data['questions'] = []
    if state != QuizState.AWAITING_QUESTION:
        return

    poll = update.message.poll
    if not poll:
        return

    if poll.type != Poll.QUIZ or poll.correct_option_id is None:
        await update.message.reply_text(
            "⚠️ That's not a quiz poll! Please create a poll in **Quiz Mode** and select a correct answer."
        )
        return

    quiz_data['questions'].append({
        "q": poll.question,
        "o": [option.text for option in poll.options],
        "a": poll.correct_option_id
    })

    await update.message.reply_text(
        "✅ Poll added.\nSend another or /done to finish."
    )

@admin_required
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize quiz creation"""
    if not (update and hasattr(update, 'message') and update.message):
        return
    if not hasattr(context, 'user_data') or not isinstance(context.user_data, dict):
        context.user_data = {}
    quiz_data = context.user_data.get('quiz_creation')
    if not isinstance(quiz_data, dict) or 'title' not in quiz_data:
        await update.message.reply_text("❌ No active quiz creation process found. Please start with /create_quiz.")
        return
    
    if 'questions' not in quiz_data or not isinstance(quiz_data['questions'], list) or not quiz_data['questions']:
        await update.message.reply_text("❌ Your quiz has no questions. Please add at least one poll question before sending /done.")
        return
    
    session = Session()
    try:
        new_quiz = Quiz(
            title=quiz_data['title'],
            questions=quiz_data['questions'],
            group_id=None  # Set group_id to None to avoid NOT NULL constraint error
        )
        session.add(new_quiz)
        session.commit()
        
        quiz_id = new_quiz.id
        bot_username = (await context.bot.get_me()).username
        quiz_link = f"https://t.me/{bot_username}?start={quiz_id}"
        
        # Fix Markdown parsing error by escaping backticks or using MarkdownV2
        safe_quiz_id = str(quiz_id).replace('_', '\\_')
        safe_quiz_link = quiz_link.replace('_', '\\_')
        await update.message.reply_text(
            f"🎉 Quiz created successfully!\n\n"
            f"*ID:* `{safe_quiz_id}`\n\n"
            f"To start it in a group, use the command:\n"
            f"`/start_quiz {safe_quiz_id}`\n\n"
            f"Alternatively, you can use this direct link:\n{safe_quiz_link}",
            parse_mode='MarkdownV2'
        )
    except Exception as e:
        logging.error(f"Error saving quiz to database: {e}")
        await update.message.reply_text("❌ An error occurred while saving your quiz. Please try again later.")
        session.rollback()
    finally:
        session.close()
        context.user_data.pop('quiz_creation', None)
        context.user_data.pop('state', None)

@admin_required
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start quiz in group"""
    if not (update and hasattr(update, 'effective_chat') and update.effective_chat and hasattr(update, 'message') and update.message):
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Usage: /start_quiz <quiz_id>")
        return
    
    quiz_id = context.args[0]
    session = Session()
    try:
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        if not quiz:
            await update.message.reply_text("❌ Quiz not found")
            return
        
        chat_id = update.effective_chat.id
        redis_client.set(redis_key_active_quiz(chat_id), quiz_id)
        
        await _send_question(update, context, quiz, 0)
    finally:
        session.close()

async def _send_question(update, context, quiz, q_index):
    """Send question as poll to group"""
    if not (update and hasattr(update, 'effective_chat') and update.effective_chat):
        return
    question = quiz.questions[q_index]
    message = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=question["q"],
        options=question["o"],
        type=Poll.QUIZ,
        correct_option_id=question["a"],
        is_anonymous=False
    )
    chat_id = update.effective_chat.id
    redis_client.set(redis_key_progress(quiz.id, chat_id), q_index)
    poll_id = message.poll.id
    redis_client.set(redis_key_poll_mapping(poll_id), chat_id)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process poll answers and update leaderboard"""
    answer = update.poll_answer
    user_id = str(answer.user.id)
    chat_id = redis_client.get(redis_key_poll_mapping(answer.poll_id))
    
    if not chat_id:
        return
    
    quiz_id = redis_client.get(redis_key_active_quiz(chat_id))
    if not quiz_id:
        return
    
    session = Session()
    try:
        q_index = int(redis_client.get(redis_key_progress(quiz_id, chat_id)) or 0)
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        
        if answer.option_ids[0] == quiz.questions[q_index]["a"]:
            lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
            if not lb:
                lb = Leaderboard(quiz_id=quiz_id, user_scores={})
                session.add(lb)
            
            lb.user_scores[user_id] = lb.user_scores.get(user_id, 0) + 1
            session.commit()
            redis_client.delete(redis_key_leaderboard(quiz_id))
        q_index += 1
        if q_index < len(quiz.questions):
            redis_client.set(redis_key_progress(quiz_id, chat_id), q_index)
            await _send_question(update, context, quiz, q_index)
        else:
            await context.bot.send_message(chat_id=int(chat_id), text="✅ Quiz completed!")
            redis_client.delete(redis_key_progress(quiz_id, chat_id))
            redis_client.delete(redis_key_active_quiz(chat_id))
    finally:
        session.close()

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show leaderboard in group"""
    if not (update and hasattr(update, 'effective_chat') and update.effective_chat and hasattr(update, 'message') and update.message):
        return
    chat_id = update.effective_chat.id
    quiz_id = redis_client.get(redis_key_active_quiz(chat_id))
    
    if not quiz_id:
        await update.message.reply_text("ℹ️ No active quiz in this group")
        return
    
    cache_key = redis_key_leaderboard(quiz_id)
    cached = redis_client.get(cache_key)
    if cached:
        await update.message.reply_text(cached.decode())
        return
    
    session = Session()
    try:
        lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
        if not lb or not lb.user_scores:
            await update.message.reply_text("📊 No scores yet!")
            return
        
        sorted_scores = sorted(lb.user_scores.items(), key=lambda x: x[1], reverse=True)
        leaderboard_lines = ["🏆 **Leaderboard** 🏆\n"]
        for idx, (uid, score) in enumerate(sorted_scores[:10]):
            try:
                member = await context.bot.get_chat_member(chat_id, int(uid))
                name = member.user.full_name or f"User {uid}"
            except Exception:
                name = f"User {uid}"
            leaderboard_lines.append(f"{idx+1}. {name}: {score}")
        leaderboard_text = "\n".join(leaderboard_lines)
        
        redis_client.setex(cache_key, 600, leaderboard_text)
        await update.message.reply_text(leaderboard_text)
    finally:
        session.close()

@admin_required
async def reset_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset leaderboard (admin only)"""
    if not (update and hasattr(update, 'message') and update.message):
        return
    quiz_id = context.args[0] if context.args else None
    if not quiz_id:
        await update.message.reply_text("ℹ️ Usage: /reset_leaderboard <quiz_id>")
        return
    
    session = Session()
    try:
        lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
        if lb:
            lb.user_scores = {}
            session.commit()
        redis_client.delete(redis_key_leaderboard(quiz_id))
        await update.message.reply_text(f"✅ Leaderboard for quiz {quiz_id} reset!")
    finally:
        session.close()

async def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    if user_id in Config.ADMIN_IDS:
        return True
    try:
        admins = await update.effective_chat.get_administrators()
        return any(admin.user.id == user_id for admin in admins)
    except Exception as e:
        logging.error(f"Admin check failed: {e}")
        return False
