import logging
import time
import asyncio
from telegram import Update, Poll
from telegram.ext import ContextTypes
from database import get_db_session, Quiz, Leaderboard
from redis_client import redis_client, redis_key_active_quiz, redis_key_poll_data, redis_key_leaderboard
from config import Config
from enum import IntEnum
from functools import wraps
import json

# --- Configuration & Constants ---
QUESTION_DURATION_SECONDS = Config.QUESTION_DURATION_SECONDS

# Set up logging
logger = logging.getLogger(__name__)

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

async def _find_quiz_by_title_or_id(query: str) -> tuple:
    """
    Find quiz by title or ID. Returns (quiz_data_dict, error_message).
    Supports both numeric IDs and string titles with flexible matching.
    Returns a dictionary with quiz data instead of SQLAlchemy object to avoid session issues.
    """
    try:
        with get_db_session() as session:
            # First, try to parse as numeric ID
            try:
                quiz_id = int(query)
                if quiz_id > 0:
                    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
                    if quiz:
                        # Extract data while in session
                        quiz_data = {
                            'id': quiz.id,
                            'title': quiz.title,
                            'questions': quiz.questions
                        }
                        return quiz_data, None
                    else:
                        return None, f"❌ Quiz with ID `{quiz_id}` not found."
            except ValueError:
                # Not a number, search by title
                pass
            
            # Search by exact title match (case-insensitive)
            quiz = session.query(Quiz).filter(Quiz.title.ilike(query)).first()
            if quiz:
                quiz_data = {
                    'id': quiz.id,
                    'title': quiz.title,
                    'questions': quiz.questions
                }
                return quiz_data, None
            
            # Search by partial title match
            quizzes = session.query(Quiz).filter(Quiz.title.ilike(f"%{query}%")).all()
            
            if not quizzes:
                return None, f"❌ No quiz found with title containing '{query}'."
            elif len(quizzes) == 1:
                quiz = quizzes[0]
                quiz_data = {
                    'id': quiz.id,
                    'title': quiz.title,
                    'questions': quiz.questions
                }
                return quiz_data, None
            else:
                # Multiple matches found
                quiz_list = "\n".join([f"• ID: {q.id} - \"{q.title}\"" for q in quizzes[:5]])
                if len(quizzes) > 5:
                    quiz_list += f"\n... and {len(quizzes) - 5} more"
                
                return None, f"🔍 Multiple quizzes found for '{query}':\n\n{quiz_list}\n\nPlease use a more specific title or quiz ID."
                
    except Exception as e:
        logger.error(f"Error finding quiz: {e}")
        return None, "❌ Database error occurred while searching for quiz."

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message with role-based instructions."""
    # Check if user is an admin
    is_admin = await _is_admin(update)
    
    if is_admin:
        # Admin welcome message with full command list
        welcome_text = (
            "Welcome to the StellarQuiz Bot! 🎯\n\n"
            "Admin Commands:\n"
            "/create_quiz - creating a new quiz.\n"
            "/start_quiz <id_or_title> - Begin a quiz in a group.\n"
            "/stop_quiz - Forcefully stop the active quiz in a group.\n"
            "/reset_leaderboard <id_or_title> - reset the scores for a quiz.\n"
            "/health - Check bot system status.\n\n"
            "User Commands:\n"
            "/leaderboard [quiz name] - To see leaderboard for the current or specified quiz."
        )
    else:
        # Regular user welcome message with limited commands
        welcome_text = (
            "Welcome to the StellarQuiz Bot! 🎯\n\n"
            "User Commands:\n"
            "/leaderboard [quiz name] - To see leaderboard for the current or specified quiz."
        )
    
    await update.message.reply_text(welcome_text)

@admin_required
async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check system health status."""
    try:
        from database import health_check as db_health
        
        # Check database
        db_status = "🟢 Connected" if db_health() else "🔴 Disconnected"
        
        # Check Redis
        redis_status = "🟢 Connected" if redis_client.health_check() else "🔴 Disconnected"
        
        # Bot info
        bot_info = await context.bot.get_me()
        
        health_message = (
            f"🏥 System Health Status\n\n"
            f"Bot: 🟢 @{bot_info.username}\n"
            f"Database: {db_status}\n"
            f"Redis Cache: {redis_status}\n"
            f"Active Chats: {len(context.job_queue.jobs())}\n\n"
            f"Configuration:\n"
            f"Question Duration: {QUESTION_DURATION_SECONDS}s\n"
            f"Max Questions: {Config.MAX_QUESTIONS_PER_QUIZ}\n"
            f"Admin Count: {len(Config.ADMIN_IDS)}"
        )
        
        await update.message.reply_text(health_message)
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        await update.message.reply_text("❌ Error performing health check.")

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
        try:
            title = update.message.text.strip()
            
            # Input validation
            if len(title) > Config.MAX_QUIZ_TITLE_LENGTH:
                await update.message.reply_text(
                    f"⚠️ Title is too long. Please keep it under {Config.MAX_QUIZ_TITLE_LENGTH} characters."
                )
                return
                
            if not title:
                await update.message.reply_text("⚠️ Title cannot be empty. Please provide a title.")
                return
                
            # Basic sanitization
            title = title.replace('\n', ' ').replace('\r', ' ')
            
            quiz_data['title'] = title
            context.user_data['state'] = QuizState.AWAITING_QUESTION
            await update.message.reply_text(
                "✅ Title set! Now, please send me your questions.\n\n"
                "Create a poll, select **'Quiz mode'**, and choose the correct answer. Send them one by one.\n\n"
                "When you've added all your questions, send `/done`."
            )
        except Exception as e:
            logger.error(f"Error handling creation message: {e}")
            await update.message.reply_text("❌ An error occurred. Please try again.")

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

    # Input validation
    if len(poll.options) < 2:
        await update.message.reply_text("⚠️ Poll must have at least 2 options!")
        return
        
    if len(poll.options) > 10:
        await update.message.reply_text("⚠️ Poll can have maximum 10 options!")
        return

    quiz_data = context.user_data.get('quiz_creation', {'questions': []})
    
    # Check question limit
    if len(quiz_data['questions']) >= Config.MAX_QUESTIONS_PER_QUIZ:
        await update.message.reply_text(f"⚠️ Maximum {Config.MAX_QUESTIONS_PER_QUIZ} questions allowed!")
        return
    
    # Validate question text length
    if len(poll.question) > 300:
        await update.message.reply_text("⚠️ Question text is too long. Please keep it under 300 characters.")
        return
    
    # Sanitize and add question
    question_data = {
        "q": poll.question.strip(),
        "o": [option.text.strip() for option in poll.options],
        "a": poll.correct_option_id
    }
    
    quiz_data['questions'].append(question_data)
    
    question_count = len(quiz_data['questions'])
    await update.message.reply_text(
        f"✅ Question {question_count} added! Send another poll or type `/done` to finish.\n"
        f"({Config.MAX_QUESTIONS_PER_QUIZ - question_count} questions remaining)"
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
        
    # Validate question count
    if len(quiz_data['questions']) > Config.MAX_QUESTIONS_PER_QUIZ:
        await update.message.reply_text(f"❌ Too many questions! Maximum allowed: {Config.MAX_QUESTIONS_PER_QUIZ}")
        return

    try:
        with get_db_session() as session:
            new_quiz = Quiz(title=quiz_data['title'], questions=quiz_data['questions'])
            
            # Validate quiz before saving
            if not new_quiz.validate_questions():
                await update.message.reply_text("❌ Invalid question format detected. Please try again.")
                return
                
            session.add(new_quiz)
            session.flush()  # Get the ID without committing
            quiz_id = new_quiz.id
            
            message = (
                f"🎉 *Quiz Created Successfully\\!* 🎉\n\n"
                f"*Title:* {escape_markdown(new_quiz.title)}\n"
                f"*ID:* `{quiz_id}`\n"
                f"*Questions:* {new_quiz.question_count}\n\n"
                f"To start this quiz in a group, go to the group and use the command:\n"
                f"`/start_quiz {quiz_id}`"
            )
            await update.message.reply_text(message)
            
    except Exception as e:
        logger.error(f"Error saving quiz to database: {e}")
        await update.message.reply_text("❌ An error occurred while saving your quiz. Please try again.")
    finally:
        # Clean up user_data
        context.user_data.pop('quiz_creation', None)
        context.user_data.pop('state', None)

@admin_required
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a quiz in a group by ID or title."""
    if not context.args:
        await update.message.reply_text("ℹ️ Please provide a Quiz ID or title. Usage: `/start_quiz <quiz_id_or_title>`")
        return
    
    chat_id = update.effective_chat.id
    
    # Check if a quiz is already running
    if redis_client.exists(redis_key_active_quiz(chat_id)):
        await update.message.reply_text("⚠️ A quiz is already running in this chat. Use `/stop_quiz` to end it first.")
        return
        
    # Join all arguments in case title has spaces
    query = " ".join(context.args)
    
    # Find quiz by ID or title
    quiz_data, error_message = await _find_quiz_by_title_or_id(query)
    if not quiz_data:
        await update.message.reply_text(error_message)
        return
    
    quiz_id = quiz_data['id']
    quiz_title = quiz_data['title']
    quiz_questions = quiz_data['questions']
    
    try:
        # Validate quiz has questions
        if not quiz_questions or len(quiz_questions) == 0:
            await update.message.reply_text("❌ This quiz has no questions and cannot be started.")
            return
        
        # Basic validation of question format
        for question in quiz_questions:
            if not isinstance(question, dict) or 'q' not in question or 'o' not in question or 'a' not in question:
                await update.message.reply_text("❌ This quiz has invalid question format and cannot be started.")
                return
        
        # Set the active quiz in Redis
        redis_client.set(redis_key_active_quiz(chat_id), str(quiz_id))
        
        await update.message.reply_text(
            f"🚀 The quiz '{escape_markdown(quiz_title)}' is about to begin!\n"
            f"📊 {len(quiz_questions)} questions\n"
            f"⏱️ {QUESTION_DURATION_SECONDS} seconds per question\n\n"
            f"First question in 3 seconds..."
        )
        
        # Schedule the first question
        try:
            context.job_queue.run_once(
                _send_question,
                when=3,
                data={'chat_id': chat_id, 'quiz_id': quiz_id, 'q_index': 0},
                name=f"quiz_{chat_id}"
            )
        except Exception as job_e:
            logger.error(f"Failed to schedule quiz: {job_e}")
            await update.message.reply_text("❌ Failed to start quiz. Please try again.")
            redis_client.delete(redis_key_active_quiz(chat_id))
                    
    except Exception as e:
        logger.error(f"Error starting quiz: {e}")
        await update.message.reply_text("❌ An error occurred while starting the quiz. Please try again.")

async def _send_question(context: ContextTypes.DEFAULT_TYPE):
    """Sends a question poll and schedules the next action."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    quiz_id = job_data['quiz_id']
    q_index = job_data['q_index']

    try:
        with get_db_session() as session:
            quiz = session.query(Quiz).filter_by(id=quiz_id).first()
            if not quiz or q_index >= len(quiz.questions):
                # This case handles if the quiz is deleted mid-run
                await _end_quiz(context, chat_id, quiz_id)
                return

            question_data = quiz.questions[q_index]
            try:
                # Implement retry logic for poll sending
                max_retries = 3
                retry_delay = 1
                
                for attempt in range(max_retries):
                    try:
                        message = await context.bot.send_poll(
                            chat_id=chat_id,
                            question=f"Question {q_index + 1}/{len(quiz.questions)}\n\n{question_data['q']}",
                            options=question_data['o'],
                            type=Poll.QUIZ,
                            correct_option_id=question_data['a'],
                            is_anonymous=False,
                            open_period=QUESTION_DURATION_SECONDS
                        )
                        break  # Success, exit retry loop
                        
                    except Exception as retry_e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Poll send attempt {attempt + 1} failed, retrying in {retry_delay}s: {retry_e}")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            raise retry_e  # Final attempt failed
                
                # Store poll data in Redis to link answers back to the quiz
                poll_info = {'quiz_id': quiz_id, 'chat_id': chat_id, 'correct_option': question_data['a']}
                redis_client.set_json(
                    redis_key_poll_data(message.poll.id), 
                    poll_info, 
                    ex=QUESTION_DURATION_SECONDS + 10
                )

                # Schedule the job to end this question and send the next one
                context.job_queue.run_once(
                    _end_question,
                    when=QUESTION_DURATION_SECONDS,
                    data={'chat_id': chat_id, 'quiz_id': quiz_id, 'q_index': q_index + 1, 'poll_id': message.poll.id, 'message_id': message.message_id},
                    name=f"quiz_{chat_id}"
                )
            except Exception as send_e:
                logger.error(f"Failed to send poll: {send_e}")
                await context.bot.send_message(chat_id, "❌ Failed to send question. Quiz stopped.")
                await _end_quiz(context, chat_id, quiz_id)
                
    except Exception as e:
        logger.error(f"Error in _send_question: {e}")
        try:
            await context.bot.send_message(chat_id, "❌ An error occurred. Quiz stopped.")
            await _end_quiz(context, chat_id, quiz_id)
        except Exception as cleanup_e:
            logger.error(f"Failed to send error message: {cleanup_e}")

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

    try:
        with get_db_session() as session:
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
    except Exception as e:
        logger.error(f"Error in _end_question: {e}")
        await _end_quiz(context, chat_id, quiz_id)

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
    """Process a user's answer to a quiz poll and update their score with atomic operations."""
    if not redis_client.is_available: 
        return

    answer = update.poll_answer
    poll_data = redis_client.get_json(redis_key_poll_data(answer.poll_id))
    
    if not poll_data:
        return # This poll is not part of an active quiz

    quiz_id = poll_data['quiz_id']
    correct_option = poll_data['correct_option']

    if answer.option_ids and answer.option_ids[0] == correct_option:
        user_id = str(answer.user.id)
        correlation_id = f"score_update_{quiz_id}_{user_id}_{int(time.time())}"
        
        # Run in background to avoid blocking the job queue
        async def update_score():
            try:
                with get_db_session() as session:
                    # Use row-level locking to prevent race conditions
                    lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).with_for_update(skip_locked=True).first()
                    if not lb:
                        lb = Leaderboard(quiz_id=quiz_id, user_scores={})
                        session.add(lb)
                    
                    # Add score using the model method
                    lb.add_score(int(user_id))
                    
                    # Invalidate leaderboard cache
                    redis_client.delete(redis_key_leaderboard(quiz_id))
                    
                    logger.info(f"Score updated successfully for user {user_id} in quiz {quiz_id} [{correlation_id}]")
                    
            except Exception as e:
                logger.error(f"Error updating leaderboard [{correlation_id}]: {e}")
        
        # Execute asynchronously without waiting
        asyncio.create_task(update_score())

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id_override=None):
    """Display the leaderboard for the active or specified quiz."""
    chat_id = update.effective_chat.id
    quiz_id = quiz_id_override
    quiz_title = None
    
    # If quiz_id is provided via arguments (e.g., /leaderboard <title>)
    if not quiz_id and context.args:
        query = " ".join(context.args)
        quiz_data, error_message = await _find_quiz_by_title_or_id(query)
        if not quiz_data:
            await context.bot.send_message(chat_id, error_message)
            return
        # Extract data from dictionary
        quiz_id = quiz_data['id']
        quiz_title = quiz_data['title']
    
    # If no quiz specified, check for active quiz
    if not quiz_id and redis_client.is_available:
        quiz_id = redis_client.get(redis_key_active_quiz(chat_id))
    
    if not quiz_id:
        await context.bot.send_message(
            chat_id, 
            "ℹ️ Please specify a quiz or start one first.\n"
            "Usage: `/leaderboard <quiz_id_or_title>` or start a quiz with `/start_quiz`"
        )
        return
    
    # Check cache first
    cache_key = redis_key_leaderboard(quiz_id)
    if redis_client.is_available:
        cached_leaderboard = redis_client.get(cache_key)
        if cached_leaderboard:
            await context.bot.send_message(chat_id, cached_leaderboard)
            return
    
    try:
        with get_db_session() as session:
            lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
            # Get quiz info if we don't have it already
            if not quiz_title:
                quiz = session.query(Quiz).filter_by(id=quiz_id).first()
                if quiz:
                    quiz_title = quiz.title

            if not quiz_title:
                await context.bot.send_message(chat_id, "❌ Quiz not found.")
                return

            if not lb or not lb.user_scores:
                await context.bot.send_message(chat_id, f"🏆 Leaderboard for \"{escape_markdown(quiz_title)}\" is empty!")
                return
            
            # Use the model's helper method
            top_scores = lb.get_top_scores(Config.MAX_LEADERBOARD_ENTRIES)
            
            leaderboard_lines = [f"🏆 Leaderboard for: {escape_markdown(quiz_title)} 🏆\n"]
            for idx, (user_id, score) in enumerate(top_scores):
                try:
                    member = await context.bot.get_chat_member(chat_id, int(user_id))
                    name = escape_markdown(member.user.full_name)
                except Exception as user_e:
                    logger.warning(f"Failed to get user info for {user_id}: {user_e}")
                    name = f"User {user_id}"
                leaderboard_lines.append(f"{idx + 1}. {name}: {score}")
                
            leaderboard_text = "\n".join(leaderboard_lines)
            
            # Cache the result
            if redis_client.is_available:
                redis_client.setex(cache_key, Config.LEADERBOARD_CACHE_TTL, leaderboard_text)
                
            await context.bot.send_message(chat_id, leaderboard_text)
            
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}")
        await context.bot.send_message(chat_id, "❌ An error occurred while getting the leaderboard.")

@admin_required
async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forcefully stops the current quiz in a chat."""
    chat_id = update.effective_chat.id
    
    # Check both job queue and Redis for active quiz
    jobs = context.job_queue.get_jobs_by_name(f"quiz_{chat_id}")
    redis_quiz_key = redis_key_active_quiz(chat_id)
    quiz_id = redis_client.get(redis_quiz_key) if redis_client else None
    
    # If neither jobs nor Redis has active quiz, nothing to stop
    if not jobs and not quiz_id:
        await update.message.reply_text("📭 No quiz is currently running in this chat.")
        return

    # Stop any active jobs
    if jobs:
        for job in jobs:
            job.schedule_removal()

    # Clean up Redis even if no jobs exist (handles stale data)
    if quiz_id:
        await _end_quiz(context, chat_id, quiz_id)
    
    await update.message.reply_text("🛑 The quiz has been manually stopped by an admin.")

@admin_required
async def reset_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the leaderboard for a specific quiz by ID or title."""
    if not context.args:
        await update.message.reply_text("ℹ️ Please provide a Quiz ID or title. Usage: `/reset_leaderboard <quiz_id_or_title>`")
        return
    
    # Join all arguments in case title has spaces
    query = " ".join(context.args)
    
    # Find quiz by ID or title
    quiz_data, error_message = await _find_quiz_by_title_or_id(query)
    if not quiz_data:
        await update.message.reply_text(error_message)
        return
    
    quiz_id = quiz_data['id']
    quiz_title = quiz_data['title']
    
    try:
        with get_db_session() as session:
            lb = session.query(Leaderboard).filter_by(quiz_id=quiz_id).first()
            if lb:
                lb.user_scores = {}
                # Invalidate cache
                redis_client.delete(redis_key_leaderboard(quiz_id))
                await update.message.reply_text(
                    f"✅ Leaderboard for quiz \"{escape_markdown(quiz_title)}\" (ID: `{quiz_id}`) has been reset."
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ No leaderboard found for quiz \"{escape_markdown(quiz_title)}\" (ID: `{quiz_id}`)."
                )
    except Exception as e:
        logger.error(f"Error resetting leaderboard: {e}")
        await update.message.reply_text("❌ An error occurred while resetting the leaderboard.")

# --- Missing Handler Functions ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages and route them appropriately."""
    # Route messages during quiz creation process
    if 'state' in context.user_data and context.user_data['state'] == QuizState.AWAITING_TITLE:
        await handle_creation_message(update, context)
    else:
        # For other messages, you can add general message handling here
        # Currently, just ignore non-creation messages
        pass

async def handle_poll_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll messages and route them appropriately."""
    # Route polls during quiz creation process
    if 'state' in context.user_data and context.user_data['state'] == QuizState.AWAITING_QUESTION:
        await handle_creation_poll(update, context)
    else:
        # For other polls, you can add general poll handling here
        # Currently, just ignore non-creation polls
        pass
