import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, PollAnswerHandler
from handlers import (
    start, quizz_set, quizz_start, leaderboard, leaderboard_reset,
    done, close, handle_message, handle_poll_answer
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
    # Create application
    application = ApplicationBuilder().token(Config.BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("quizz_set", quizz_set))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("close", close))
    application.add_handler(CommandHandler("quizz_start", quizz_start))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("leaderboard_reset", leaderboard_reset))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Poll handlers
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
