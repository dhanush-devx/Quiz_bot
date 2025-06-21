import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackContext
from database import Session, Quiz, Leaderboard
from config import Config
import redis

# Redis connection
redis_client = redis.Redis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=Config.REDIS_DB
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 **QuizBot Activated!** 🌟\n\n"
        "Admin commands:\n"
        "→ /quizz_set - Create new quizzes\n"
        "→ /leaderboard_reset - Reset scores\n\n"
        "User commands:\n"
        "→ /quizz_start - Begin a quiz\n"
        "→ /leaderboard - View rankings"
    )

async def quizz_set(update: Update, context: CallbackContext):
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ **Admin access required!**")
        return
    
    await update.message.reply_text(
        "📝 Enter quiz title:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_quiz")]])
    )
    context.user_data['state'] = 'AWAITING_TITLE'

async def quizz_start(update: Update, context: CallbackContext):
    session = Session()
    try:
        quizzes = session.query(Quiz).filter_by(group_id=str(update.effective_chat.id)).all()
        if not quizzes:
            await update.message.reply_text("ℹ️ No quizzes available. Create one with /quizz_set")
            return
        
        keyboard = [
            [InlineKeyboardButton(q.title, callback_data=f"start_quiz_{q.id}")]
            for q in quizzes
        ]
        await update.message.reply_text(
            "📚 **Available Quizzes:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    finally:
        Session.remove()

async def leaderboard(update: Update, context: CallbackContext):
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
            [f"{idx+1}. User {uid}: {score}" for idx, (uid, score) in enumerate(sorted_scores)]
        )
        
        # Cache for 10 minutes
        redis_client.setex(cache_key, 600, leaderboard_text)
        await update.message.reply_text(leaderboard_text)
    finally:
        Session.remove()

async def leaderboard_reset(update: Update, context: CallbackContext):
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
        Session.remove()

# Helper functions
async def _is_admin(update: Update) -> bool:
    if update.effective_user.id in Config.ADMIN_IDS:
        return True
    try:
        admins = await update.effective_chat.get_administrators()
        return update.effective_user.id in [admin.user.id for admin in admins]
    except Exception as e:
        logging.error(f"Admin check failed: {e}")
        return False
