import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from handlers import start, quizz_set, quizz_start, leaderboard, leaderboard_reset, handle_message, handle_callback_query
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
    # Create application with webhook
    application = ApplicationBuilder().token(Config.BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("quizz_set", quizz_set))
    application.add_handler(CommandHandler("quizz_start", quizz_start))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("leaderboard_reset", leaderboard_reset))

    # Add message handler for quiz creation flow
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add callback query handler for quiz creation flow
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Start the bot with webhook
    WEBHOOK_URL = "https://your-domain.com/telegram-webhook"  # Replace with your public URL
    
    application.run_webhook(
        listen="0.0.0.0",
        port=8443,
        url_path=Config.BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{Config.BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
