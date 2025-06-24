import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Poll
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, PollAnswerHandler
from database import Session, Quiz, Leaderboard
from config import Config
import redis

# Redis connection
redis_client = redis.Redis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=Config.REDIS_DB
)

# Quiz creation states
AWAITING_TITLE = 1
AWAITING_DESCRIPTION = 2
AWAITING_QUESTION = 3

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

async def create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate quiz creation in private chat"""
    if update.effective_chat.type != "private":
        await update.message.reply_text("⚠️ Quiz creation only available in private chat with bot")
        return
    
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ Admin access required!")
        return
    
    context.user_data['quiz_creation'] = {'questions': []}
    context.user_data['state'] = AWAITING_TITLE
    await update.message.reply_text("📝 Enter quiz title:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz creation states"""
    state = context.user_data.get('state')
    quiz_data = context.user_data.get('quiz_creation', {})
    
    if state == AWAITING_TITLE:
        quiz_data['title'] = update.message.text
        context.user_data['state'] = AWAITING_DESCRIPTION
        await update.message.reply_text("📝 Enter quiz description:")
    
    elif state == AWAITING_DESCRIPTION:
        # Remove description handling, skip to next state
        context.user_data['state'] = AWAITING_QUESTION
        await update.message.reply_text(
            "📝 Create a poll with options and mark the correct answer.\n"
            "After creating the poll, forward it to me."
        )
    
    
    elif state == AWAITING_QUESTION:
        if update.message.poll:
            poll = update.message.poll
            if poll.type != "regular" or not poll.options:
                await update.message.reply_text("⚠️ Only regular polls with options supported")
                return
            
            # Store question
            quiz_data['questions'].append({
                "q": poll.question,
                "o": [option.text for option in poll.options],
                "a": poll.correct_option_id
            })
            await update.message.reply_text(
                f"✅ Question added! Total: {len(quiz_data['questions'])}\n"
                "Send /done to finish or create another poll."
            )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize quiz creation"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ Admin access required!")
        return
    
    quiz_data = context.user_data.get('quiz_creation')
    if not quiz_data or 'title' not in quiz_data:
        await update.message.reply_text("❌ No active quiz creation")
        return
    
    session = Session()
    try:
        new_quiz = Quiz(
            title=quiz_data['title'],
            questions=quiz_data['questions']
        )
        session.add(new_quiz)
        session.commit()
        await update.message.reply_text(
            f"🎉 Quiz created! ID: {new_quiz.id}\n"
            f"Use /start_quiz {new_quiz.id} in your group"
        )
    finally:
        session.close()
        context.user_data.pop('quiz_creation', None)
        context.user_data.pop('state', None)

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start quiz in group"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ Admin access required!")
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
        
        # Store active quiz in Redis
        redis_client.set(f"active_quiz:{update.effective_chat.id}", quiz_id)
        
        # Send first question
        await _send_question(update, context, quiz, 0)
    finally:
        session.close()

async def _send_question(update, context, quiz, q_index):
    """Send question as poll to group"""
    question = quiz.questions[q_index]
    message = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=question["q"],
        options=question["o"],
        type=Poll.QUIZ,
        correct_option_id=question["a"],
        is_anonymous=False
    )
    # Store current question index
    redis_client.set(f"quiz_progress:{quiz.id}:{update.effective_chat.id}", q_index)
    # Store poll id to chat id mapping for answer handling
    poll_id = message.poll.id
    redis_client.set(f"poll:{poll_id}", update.effective_chat.id)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process poll answers and update leaderboard"""
    answer = update.poll_answer
    user_id = str(answer.user.id)
    chat_id = redis_client.get(f"poll:{answer.poll_id}")
    
    if not chat_id:
        return
    
    quiz_id = redis_client.get(f"active_quiz:{chat_id}")
    if not quiz_id:
        return
    
    session = Session()
    try:
        # Get current question index
        q_index = int(redis_client.get(f"quiz_progress:{quiz_id}:{chat_id}") or 0)
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        
        if answer.option_ids[0] == quiz.questions[q_index]["a"]:
            # Update leaderboard
            lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
            if not lb:
                lb = Leaderboard(quiz_id=quiz_id, user_scores={})
                session.add(lb)
            
            lb.user_scores[user_id] = lb.user_scores.get(user_id, 0) + 1
            session.commit()
            redis_client.delete(f"leaderboard:{quiz_id}")
    finally:
        session.close()

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show leaderboard in group"""
    chat_id = update.effective_chat.id
    quiz_id = redis_client.get(f"active_quiz:{chat_id}")
    
    if not quiz_id:
        await update.message.reply_text("ℹ️ No active quiz in this group")
        return
    
    # Check cache
    cache_key = f"leaderboard:{quiz_id}"
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
        
        # Format leaderboard
        sorted_scores = sorted(lb.user_scores.items(), key=lambda x: x[1], reverse=True)
        leaderboard_text = "🏆 **Leaderboard** 🏆\n\n" + "\n".join(
            [f"{idx+1}. User {uid}: {score}" for idx, (uid, score) in enumerate(sorted_scores[:10])]
        )
        
        # Cache for 10 minutes
        redis_client.setex(cache_key, 600, leaderboard_text)
        await update.message.reply_text(leaderboard_text)
    finally:
        session.close()

async def reset_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset leaderboard (admin only)"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ Admin access required!")
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
        redis_client.delete(f"leaderboard:{quiz_id}")
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
