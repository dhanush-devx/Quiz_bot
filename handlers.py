from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from database import Session, Quiz
import logging

# Quiz creation states
AWAITING_TITLE = 1
AWAITING_QUESTION = 2

async def start_quiz_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate quiz creation process"""
    await update.message.reply_text(
        "📝 Let's create a new quiz!\n"
        "Please send me the TITLE for your quiz.\n\n"
        "Type /cancel at any time to abort."
    )
    context.user_data['quiz_creation'] = {'state': AWAITING_TITLE, 'questions': []}
    return AWAITING_TITLE

async def handle_quiz_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process quiz title and prompt for first question"""
    title = update.message.text
    context.user_data['quiz_creation']['title'] = title
    context.user_data['quiz_creation']['state'] = AWAITING_QUESTION
    
    await update.message.reply_text(
        f"✅ Title set: {title}\n\n"
        "Now send your first question in this format:\n"
        "<b>Question?|Option1|Option2|Option3|Option4|CorrectIndex</b>\n\n"
        "Example:\n"
        "<i>What is 2+2?|3|4|5|6|1</i>\n\n"
        "Type /done when finished adding questions.",
        parse_mode="HTML"
    )
    return AWAITING_QUESTION

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process quiz question input"""
    try:
        parts = update.message.text.split('|')
        if len(parts) < 6:
            raise ValueError("Insufficient parts")
            
        question_text = parts[0].strip()
        options = [opt.strip() for opt in parts[1:5]]
        correct_index = int(parts[5].strip())
        
        if correct_index < 0 or correct_index > 3:
            raise ValueError("Invalid option index (0-3)")
        
        # Store question
        context.user_data['quiz_creation']['questions'].append({
            'text': question_text,
            'options': options,
            'correct_index': correct_index
        })
        
        await update.message.reply_text(
            f"✅ Question added! Total questions: {len(context.user_data['quiz_creation']['questions']}\n"
            "Send next question or /done to finish."
        )
    except Exception as e:
        logging.error(f"Question format error: {e}")
        await update.message.reply_text(
            "⚠️ Invalid format. Please use:\n"
            "<b>Question?|Option1|Option2|Option3|Option4|CorrectIndex</b>\n\n"
            "Example: <i>Capital of France?|Berlin|London|Paris|Rome|2</i>",
            parse_mode="HTML"
        )
    return AWAITING_QUESTION

async def save_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save quiz to database and clean up"""
    quiz_data = context.user_data['quiz_creation']
    if not quiz_data.get('questions'):
        await update.message.reply_text("❌ Quiz not saved - no questions added!")
        return
    
    # Save to database
    session = Session()
    try:
        new_quiz = Quiz(
            title=quiz_data['title'],
            questions=quiz_data['questions'],
            group_id=str(update.effective_chat.id)
        )
        session.add(new_quiz)
        session.commit()
        quiz_id = new_quiz.id
        await update.message.reply_text(
            f"🎉 Quiz saved successfully! ID: {quiz_id}\n"
            f"Title: {quiz_data['title']}\n"
            f"Questions: {len(quiz_data['questions'])}\n\n"
            "Use /quizz_start to begin this quiz."
        )
    except Exception as e:
        logging.error(f"Database error: {e}")
        await update.message.reply_text("❌ Failed to save quiz. Please try again.")
    finally:
        session.close()
        # Clean up
        context.user_data.pop('quiz_creation', None)

async def cancel_quiz_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Abort quiz creation"""
    if 'quiz_creation' in context.user_data:
        context.user_data.pop('quiz_creation')
    await update.message.reply_text("❌ Quiz creation cancelled.")

# Handler registration in bot.py
def setup_quiz_handlers(application):
    application.add_handler(CommandHandler("quizz_set", start_quiz_creation))
    
    # Conversation handlers
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_title)],
        states={
            AWAITING_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_title)
            ],
            AWAITING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question),
                CommandHandler("done", save_quiz)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_quiz_creation),
            CommandHandler("stop", cancel_quiz_creation)
        ],
        allow_reentry=True
    )
    application.add_handler(conv_handler)
