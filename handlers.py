import logging
from telegram import Update, Poll, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
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
        "→ /quizz_set - Create quizzes\n"
        "→ /quizz_start - Start quizzes\n"
        "→ /leaderboard_reset - Reset scores\n\n"
        "User commands:\n"
        "→ /leaderboard - View rankings"
    )

async def quizz_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate quiz creation"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ **Admin access required!**")
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
        quiz_data['description'] = update.message.text
        context.user_data['state'] = AWAITING_QUESTION
        await update.message.reply_text(
            "📝 Create a question poll with options and mark the correct answer.\n"
            "After creating the poll, forward it to me."
        )
    
    elif state == AWAITING_QUESTION:
        if update.message.poll:
            poll = update.message.poll
            if poll.type != "regular" or not poll.options:
                await update.message.reply_text("⚠️ Only regular polls with options are supported.")
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
        await update.message.reply_text("⛔️ **Admin access required!**")
        return
    
    quiz_data = context.user_data.get('quiz_creation')
    if not quiz_data or 'title' not in quiz_data:
        await update.message.reply_text("❌ No active quiz creation.")
        return
    
    session = Session()
    try:
        new_quiz = Quiz(
            title=quiz_data['title'],
            description=quiz_data.get('description', ''),
            group_id=str(update.effective_chat.id),
            questions=quiz_data['questions']
        )
        session.add(new_quiz)
        session.commit()
        await update.message.reply_text(
            f"🎉 Quiz created successfully! ID: {new_quiz.id}\n"
            f"Title: {quiz_data['title']}\n"
            f"Questions: {len(quiz_data['questions'])}"
        )
    except Exception as e:
        logging.error(f"Quiz creation failed: {e}")
        await update.message.reply_text("❌ Failed to save quiz.")
    finally:
        session.close()
        context.user_data.pop('quiz_creation', None)
        context.user_data.pop('state', None)

async def close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close active quiz"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ **Admin access required!**")
        return
    
    session = Session()
    try:
        quiz_id = context.args[0] if context.args else None
        if not quiz_id:
            await update.message.reply_text("Usage: /close <quiz_id>")
            return
        
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        if quiz:
            quiz.is_active = False
            session.commit()
            await update.message.reply_text(f"✅ Quiz {quiz_id} closed.")
        else:
            await update.message.reply_text("❌ Quiz not found.")
    finally:
        session.close()

async def quizz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a quiz in the group"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ **Admin access required!**")
        return
    
    session = Session()
    try:
        quizzes = session.query(Quiz).filter_by(
            group_id=str(update.effective_chat.id),
            is_active=True
        ).all()
        
        if not quizzes:
            await update.message.reply_text("ℹ️ No active quizzes available.")
            return
        
        keyboard = [
            [InlineKeyboardButton(q.title, callback_data=f"start_quiz_{q.id}")]
            for q in quizzes
        ]
        await update.message.reply_text(
            "📚 **Active Quizzes:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    finally:
        session.close()

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process poll answers and update leaderboard"""
    answer = update.poll_answer
    user_id = str(answer.user.id)
    
    # Get quiz ID from cached poll data
    poll_id = answer.poll_id
    quiz_id = redis_client.get(f"poll:{poll_id}")
    if not quiz_id:
        return
    
    session = Session()
    try:
        quiz = session.query(Quiz).filter_by(id=quiz_id).first()
        if not quiz or not quiz.is_active:
            return
        
        # Find question index
        question_idx = next(
            (i for i, q in enumerate(quiz.questions) 
             if q['q'] == context.bot_data.get(f"poll:{poll_id}:question")), 
            None
        )
        if question_idx is None:
            return
        
        # Check answer
        question = quiz.questions[question_idx]
        if answer.option_ids[0] == question['a']:
            # Update leaderboard
            lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
            if not lb:
                lb = Leaderboard(quiz_id=quiz_id, user_scores={})
                session.add(lb)
            
            lb.user_scores[user_id] = lb.user_scores.get(user_id, 0) + 1
            session.commit()
            
            # Invalidate leaderboard cache
            redis_client.delete(f"leaderboard:{quiz_id}")
    finally:
        session.close()

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show leaderboard"""
    quiz_id = context.args[0] if context.args else None
    if not quiz_id:
        await update.message.reply_text("ℹ️ Usage: /leaderboard <quiz_id>")
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
            await update.message.reply_text("📊 No scores recorded yet!")
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

async def leaderboard_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset leaderboard"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ **Admin access required!**")
        return
    
    quiz_id = context.args[0] if context.args else None
    if not quiz_id:
        await update.message.reply_text("ℹ️ Usage: /leaderboard_reset <quiz_id>")
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
