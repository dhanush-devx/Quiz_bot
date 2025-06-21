import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from handlers import start, quizz_set, quizz_start, leaderboard, leaderboard_reset
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
    application.add_handler(CommandHandler("quizz_start", quizz_start))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("leaderboard_reset", leaderboard_reset))
    
    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
