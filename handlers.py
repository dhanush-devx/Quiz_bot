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
AWAITING_UNDO = 4
AWAITING_TIME_LIMIT = 5
AWAITING_SHUFFLE = 6

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
        # Removed description prompt as per user request
        # await update.message.reply_text("📝 Enter quiz description or /skip:")
    
    elif state == AWAITING_DESCRIPTION:
        # Removed description step fully as per user request
        context.user_data['state'] = AWAITING_QUESTION
        await update.message.reply_text(
            "📝 Create a question poll with options and mark the correct answer.\n"
            "After creating the poll, send it here."
        )
    
    elif state == AWAITING_QUESTION:
        await update.message.reply_text(
            "⚠️ Please send the poll directly, not as a forwarded message."
        )
    
    elif state == AWAITING_UNDO:
        await update.message.reply_text(
            "Send /undo to remove the last question or send the next poll."
        )
    
    elif state == AWAITING_TIME_LIMIT:
        try:
            time_limit = int(update.message.text.split()[0])
            quiz_data['time_limit'] = time_limit
            context.user_data['state'] = AWAITING_SHUFFLE
            await update.message.reply_text(
                "Shuffle questions and answer options? (yes/no)"
            )
        except Exception:
            await update.message.reply_text(
                "Please enter a valid number for time limit in seconds."
            )
    
    elif state == AWAITING_SHUFFLE:
        text = update.message.text.lower()
        if text in ["yes", "y"]:
            quiz_data['shuffle'] = True
        else:
            quiz_data['shuffle'] = False
        # Quiz creation finished
        await update.message.reply_text("👍 Quiz created.")
        context.user_data['state'] = None

async def handle_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming polls during quiz creation"""
    import logging
    logging.info("handle_poll called")
    state = context.user_data.get('state')
    logging.info(f"Current state: {state}")
    quiz_data = context.user_data.get('quiz_creation', {})
    
    if state != AWAITING_QUESTION and state != AWAITING_UNDO:
        logging.info("Not in AWAITING_QUESTION or AWAITING_UNDO state, ignoring poll")
        return
    
    poll = update.poll
    logging.info(f"Received poll: {poll.question}")
    if poll.type not in ["regular", "quiz"] or not poll.options:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Only regular or quiz polls with options are supported."
        )
        return
    
    if state == AWAITING_QUESTION:
        # Store question
        quiz_data.setdefault('questions', []).append({
            "q": poll.question,
            "o": [option.text for option in poll.options],
            "a": poll.correct_option_id
        })
        context.user_data['state'] = AWAITING_UNDO
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Question added! Total: {len(quiz_data['questions'])}\n"
                 "Send /undo to fix last question or send next poll."
        )
    elif state == AWAITING_UNDO:
        # Add more questions
        quiz_data.setdefault('questions', []).append({
            "q": poll.question,
            "o": [option.text for option in poll.options],
            "a": poll.correct_option_id
        })
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Question added! Total: {len(quiz_data['questions'])}\n"
                 "Send /undo to fix last question or send next poll."
        )

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Undo last question during quiz creation"""
    state = context.user_data.get('state')
    quiz_data = context.user_data.get('quiz_creation', {})
    if state not in [AWAITING_UNDO, AWAITING_QUESTION]:
        await update.message.reply_text("Nothing to undo.")
        return
    if 'questions' in quiz_data and quiz_data['questions']:
        removed = quiz_data['questions'].pop()
        await update.message.reply_text(f"Removed last question: {removed['q']}")
    else:
        await update.message.reply_text("No questions to remove.")
    context.user_data['state'] = AWAITING_UNDO

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize quiz creation"""
    if not await _is_admin(update):
        await update.message.reply_text("⛔️ **Admin access required!**")
        return
    
    quiz_data = context.user_data.get('quiz_creation')
    if not quiz_data or 'title' not in quiz_data:
        await update.message.reply_text("❌ No active quiz creation.")
        return
    
    # Ask for time limit if not set
    if 'time_limit' not in quiz_data:
        context.user_data['state'] = AWAITING_TIME_LIMIT
        await update.message.reply_text(
            "Please set a time limit for questions in seconds. In groups, the bot will send the next question as soon as this time is up."
        )
        return
    
    # Ask for shuffle if not set
    if 'shuffle' not in quiz_data:
        context.user_data['state'] = AWAITING_SHUFFLE
        await update.message.reply_text(
            "Shuffle questions and answer options? (yes/no)"
        )
        return
    
    # Save quiz to database
    session = Session()
    try:
        new_quiz = Quiz(
            title=quiz_data['title'],
            # Remove description field to avoid DB error
            group_id=str(update.effective_chat.id),
            questions=quiz_data['questions'],
            time_limit=quiz_data.get('time_limit', 10),
            shuffle=quiz_data.get('shuffle', False),
            is_active=True
        )
        session.add(new_quiz)
        session.commit()
        await update.message.reply_text(
            f"👍 Quiz created successfully! ID: {new_quiz.id}\n"
            f"Title: {quiz_data['title']}\n"
            f"Questions: {len(quiz_data['questions'])}\n"
            f"Time limit: {new_quiz.time_limit} seconds\n"
            f"Shuffle: {'Yes' if new_quiz.shuffle else 'No'}"
        )
    except Exception as e:
        import logging
        logging.error(f"Quiz creation failed: {e}")
        await update.message.reply_text("❌ Failed to save quiz.")
    finally:
        session.close()
        context.user_data.pop('quiz_creation', None)
        context.user_data.pop('state', None)

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
            group_id=str(update.effective_chat.id),
            questions=quiz_data['questions'],
            time_limit=quiz_data.get('time_limit', 10),
            shuffle=quiz_data.get('shuffle', False),
            is_active=True
        )
        session.add(new_quiz)
        session.commit()
        await update.message.reply_text(
            f"👍 Quiz created successfully! ID: {new_quiz.id}\n"
            f"Title: {quiz_data['title']}\n"
            f"Questions: {len(quiz_data['questions'])}\n"
            f"Time limit: {new_quiz.time_limit} seconds\n"
            f"Shuffle: {'Yes' if new_quiz.shuffle else 'No'}"
        )
    except Exception as e:
        import logging
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
