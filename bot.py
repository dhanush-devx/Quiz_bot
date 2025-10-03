import logging
import signal
import sys
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, PollAnswerHandler
from telegram.ext import AIORateLimiter
from handlers import (
    start, create_quiz, done, start_quiz, 
    leaderboard, reset_leaderboard, stop_quiz, health, handle_message, handle_poll_answer, handle_poll_message
)
from database import init_db, init_db_engine
from config import Config
from monitoring import metrics

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global application reference for graceful shutdown
application = None

def signal_handler(signum, frame):
    """Handle graceful shutdown signals."""
    logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
    
    if application:
        try:
            # Use asyncio to properly shutdown the application
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(graceful_shutdown())
            else:
                loop.run_until_complete(graceful_shutdown())
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
    
    logger.info("Shutdown complete.")
    sys.exit(0)

async def graceful_shutdown():
    """Perform graceful shutdown of the application."""
    try:
        # Stop the application properly
        await application.stop()
        await application.shutdown()
        logger.info("Application stopped successfully.")
        
        # Log final metrics
        final_metrics = metrics.get_metrics_summary()
        logger.info(f"Final metrics: {final_metrics}")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Validate configuration
if not Config.validate():
    logger.error("Configuration validation failed. Exiting.")
    exit(1)

# Initialize database and load metrics
try:
    init_db_engine()
    init_db()
    metrics.load_metrics()
    logger.info("Database and metrics initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
    exit(1)

def main():
    global application
    
    try:
        application = (
            ApplicationBuilder()
            .token(Config.BOT_TOKEN)
            .rate_limiter(AIORateLimiter(max_retries=5))
            .connect_timeout(30)
            .read_timeout(30)
            .pool_timeout(30)
            .build()
        )
        
        # Command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("create_quiz", create_quiz))
        application.add_handler(CommandHandler("done", done))
        application.add_handler(CommandHandler("start_quiz", start_quiz))
        application.add_handler(CommandHandler("stop_quiz", stop_quiz))
        application.add_handler(CommandHandler("leaderboard", leaderboard))
        application.add_handler(CommandHandler("reset_leaderboard", reset_leaderboard))
        application.add_handler(CommandHandler("health", health))
        
        # Message handlers
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.POLL, handle_poll_message))
        
        # Poll handlers
        application.add_handler(PollAnswerHandler(handle_poll_answer))
        
        logger.info("Starting bot with improved architecture...")
        logger.info(f"Bot uptime tracking started: {metrics.get_uptime()}")
        
        # Start polling with production settings
        application.run_polling(
            drop_pending_updates=True,  # Clean start
            timeout=30,  # Request timeout
            read_timeout=30,  # Read timeout
            connect_timeout=30,  # Connection timeout
            pool_timeout=30,  # Connection pool timeout
            close_loop=False  # Keep event loop open for graceful shutdown
        )
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        exit(1)

if __name__ == "__main__":
    main()
