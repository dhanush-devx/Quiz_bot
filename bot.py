import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, PollAnswerHandler
from handlers import (
    start, create_quiz, done, start_quiz, 
    leaderboard, reset_leaderboard, handle_message, handle_poll_answer
)
from database import init_db
from config import Config

# Initialize database
init_db()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def main():
    application = ApplicationBuilder().token(Config.BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create_quiz", create_quiz))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("start_quiz", start_quiz))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("reset_leaderboard", reset_leaderboard))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.POLL, handle_poll_message))
    
    # Poll handlers
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    application.run_polling()

if __name__ == "__main__":
    main()
