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
    context.user_data.clear()
    context.user_data['state'] = 'AWAITING_TITLE'

async def handle_message(update: Update, context: CallbackContext):
    state = context.user_data.get('state')

    if state == 'AWAITING_TITLE':
        title = update.message.text.strip()
        if not title:
            await update.message.reply_text("❌ Quiz title cannot be empty. Please enter a valid title.")
            return
        context.user_data['title'] = title
        context.user_data['questions'] = []
        context.user_data['state'] = 'AWAITING_QUESTION'
        await update.message.reply_text(
            "📝 Enter the first question:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_quiz")]])
        )
    elif state == 'AWAITING_QUESTION':
        question = update.message.text.strip()
        if not question:
            await update.message.reply_text("❌ Question cannot be empty. Please enter a valid question.")
            return
        context.user_data['current_question'] = {'question': question, 'options': []}
        context.user_data['state'] = 'AWAITING_OPTION'
        await update.message.reply_text(
            "📝 Enter option 1 for this question:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_quiz")]])
        )
    elif state == 'AWAITING_OPTION':
        option = update.message.text.strip()
        if not option:
            await update.message.reply_text("❌ Option cannot be empty. Please enter a valid option.")
            return
        context.user_data['current_question']['options'].append(option)
        option_count = len(context.user_data['current_question']['options'])
        if option_count < 2:
            await update.message.reply_text(
                f"📝 Enter option {option_count + 1} for this question:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_quiz")]])
            )
        else:
            context.user_data['state'] = 'AWAITING_ANSWER'
            keyboard = [
                [InlineKeyboardButton(opt, callback_data=f"answer_{idx}")]
                for idx, opt in enumerate(context.user_data['current_question']['options'])
            ]
            await update.message.reply_text(
                "✅ Select the correct answer:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        await update.message.reply_text("ℹ️ Use /quizz_set to start creating a quiz.")

async def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_quiz":
        context.user_data.clear()
        await query.edit_message_text("❌ Quiz creation cancelled.")
        return

    state = context.user_data.get('state')

    if state == 'AWAITING_ANSWER' and data.startswith("answer_"):
        answer_index = int(data.split("_")[1])
        context.user_data['current_question']['answer'] = answer_index
        context.user_data['questions'].append(context.user_data['current_question'])
        context.user_data.pop('current_question', None)

        await query.edit_message_text(f"✅ Question added. Total questions: {len(context.user_data['questions'])}")

        # Ask if user wants to add another question or finish
        keyboard = [
            [InlineKeyboardButton("Add another question", callback_data="add_question")],
            [InlineKeyboardButton("Finish quiz", callback_data="finish_quiz")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_quiz")]
        ]
        context.user_data['state'] = 'QUIZ_IN_PROGRESS'
        await query.message.reply_text("What would you like to do next?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif state == 'QUIZ_IN_PROGRESS':
        if data == "add_question":
            context.user_data['state'] = 'AWAITING_QUESTION'
            await query.message.reply_text(
                "📝 Enter the next question:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_quiz")]])
            )
        elif data == "finish_quiz":
            # Save quiz to DB
            session = Session()
            try:
                quiz = Quiz(
                    title=context.user_data['title'],
                    questions=context.user_data['questions'],
                    group_id=str(update.effective_chat.id)
                )
                session.add(quiz)
                session.commit()
                await query.message.reply_text(f"🎉 Quiz '{quiz.title}' created successfully with {len(quiz.questions)} questions!")
            except Exception as e:
                logging.error(f"Error saving quiz: {e}")
                await query.message.reply_text("❌ Failed to save quiz. Please try again.")
            finally:
                Session.remove()
            context.user_data.clear()
        else:
            await query.message.reply_text("❌ Unknown action.")
    else:
        await query.message.reply_text("ℹ️ Use /quizz_set to start creating a quiz.")

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
