# Quiz Bot

A production-ready Telegram bot for creating and running interactive quizzes in groups with real-time scoring, comprehensive monitoring, and enterprise-grade reliability.

## 🚀 Features

- 🎯 **Quiz Creation**: Admins can create quizzes with multiple-choice questions
- ⏱️ **Timed Questions**: Configurable time limit per question (default: 30 seconds)
- 🏆 **Real-time Leaderboards**: Live scoring with top 10 display and caching
- 👥 **Group Support**: Run quizzes in Telegram groups with admin controls
- 🔐 **Admin Controls**: Multi-level admin authentication and role-based access
- 💾 **Persistent Storage**: PostgreSQL with connection pooling and Redis caching
- 📊 **Monitoring**: Comprehensive metrics, health checks, and observability
- 🛡️ **Production Ready**: Graceful shutdown, error handling, and Docker support

## 📋 Commands

### Admin Commands
- `/create_quiz` - Start creating a new quiz (private chat only)
- `/start_quiz <id>` - Begin a quiz in a group
- `/stop_quiz` - Forcefully stop the active quiz
- `/reset_leaderboard <id>` - Clear scores for a quiz
- `/health` - Check bot system status and metrics

### User Commands
- `/start` - Show welcome message and commands
- `/leaderboard` - Display current quiz scores

## � Quick Start Guide

### Prerequisites
- Docker and Docker Compose (recommended)
- Python 3.11+ (for local development)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- PostgreSQL database (or use Docker Compose)

### 1-Minute Deployment
```bash
# 1. Clone and setup
git clone <repository_url>
cd Quiz_bot

# 2. Configure environment
cp .env.example .env
# Edit .env with your BOT_TOKEN and other settings

# 3. Deploy with Docker
docker-compose up -d

# 4. Check status
docker-compose ps
docker-compose logs bot
```

### Verification
```bash
# Test bot health
curl http://localhost:8080/health  # If health endpoint enabled

# Check services
docker-compose exec bot python -c "from config import Config; print('✅ Config valid:', Config.validate())"
docker-compose exec bot python -c "from database import health_check; print('✅ DB connected:', health_check())"
```

## �🔧 Setup

### Environment Variables
```env
# Required
BOT_TOKEN=your_telegram_bot_token
DB_PASS=your_postgresql_password

# Optional (with defaults)
DB_HOST=postgres
DB_PORT=5432
DB_USER=quizbot
DB_NAME=quizbot_prod
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
ADMIN_IDS=comma,separated,user,ids

# Optional: Full database URL (overrides individual settings)
DATABASE_URL=postgresql://user:pass@host:port/dbname
```

### 🐳 Docker Compose (Recommended)
```bash
# 1. Clone the repository
git clone <repository_url>
cd Quiz_bot

# 2. Create .env file with your configuration
cp .env.example .env
# Edit .env with your values

# 3. Start all services with health checks
docker-compose up -d

# 4. Check service health
docker-compose ps
```

### ☁️ Heroku Deployment
```bash
# 1. Create Heroku app
heroku create your-quiz-bot

# 2. Add PostgreSQL and Redis add-ons
heroku addons:create heroku-postgresql:hobby-dev
heroku addons:create heroku-redis:hobby-dev

# 3. Set environment variables
heroku config:set BOT_TOKEN=your_bot_token
heroku config:set ADMIN_IDS=your_telegram_id

# 4. Deploy
git push heroku main
```

## 🏗️ Architecture

### Core Components
- **bot.py**: Main application with graceful shutdown handling
- **handlers.py**: Business logic and enhanced command handlers
- **database.py**: SQLAlchemy models with connection pooling
- **config.py**: Robust configuration management with validation
- **redis_client.py**: Redis wrapper with error handling and fallback
- **monitoring.py**: Comprehensive metrics and analytics

### Infrastructure
- **PostgreSQL**: Primary database with connection pooling
- **Redis**: Caching layer with health checks and graceful degradation
- **Docker**: Multi-stage builds with security best practices
- **Health Checks**: Database, Redis, and bot status monitoring

## 📊 Monitoring & Observability

### Health Checks
- Database connectivity and performance
- Redis availability and response time
- Active quiz monitoring
- Bot uptime and metrics

### Metrics Tracked
- Total quizzes created and started
- Questions answered and user engagement
- Command usage analytics
- System performance indicators
- Error rates and recovery

## 🔒 Security Features

- **Input Validation**: Comprehensive sanitization and limits
- **Admin Authentication**: Multi-level access control
- **Private Quiz Creation**: Prevents group spam
- **Rate Limiting**: Built-in Telegram limits respected
- **Non-root Container**: Security-hardened Docker setup
- **Environment Isolation**: Secure configuration management

## 🚀 Recent Major Improvements

### ✅ **Enterprise Architecture**
- Database connection pooling for scalability
- Redis client with automatic reconnection
- Graceful shutdown handling with signal management
- Health checks and comprehensive monitoring

### ✅ **Enhanced Reliability**
- Robust error handling throughout the application
- Fallback mechanisms for external service failures
- Input validation and security improvements
- Configuration validation with detailed error reporting

### ✅ **Production Readiness**
- Docker health checks and multi-stage builds
- Comprehensive logging and metrics collection
- Performance monitoring and analytics
- Security hardening and best practices

### ✅ **Developer Experience**
- Type hints and improved documentation
- Structured configuration management
- Modular architecture with clear separation
- Easy deployment with Docker Compose

## 📈 Performance Optimizations

- **Connection Pooling**: Efficient database connection management
- **Redis Caching**: Leaderboard and session data caching
- **Session Management**: Context managers for automatic cleanup
- **Error Recovery**: Automatic reconnection and fallback logic
- **Batch Operations**: Optimized database queries

## 🛠️ Development

### Local Development
```bash
# 1. Clone and setup
git clone <repository_url>
cd Quiz_bot
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 2. Setup environment
cp .env.example .env
# Edit .env with your configuration

# 3. Run with Docker Compose
docker-compose up -d postgres redis
python bot.py
```

### Testing
```bash
# Run health checks
python -c "from database import health_check; print('DB:', health_check())"
python -c "from redis_client import redis_client; print('Redis:', redis_client.health_check())"

# Check configuration
python -c "from config import Config; print('Valid:', Config.validate())"
```

## 📚 API Reference

### Configuration Options
- `QUESTION_DURATION_SECONDS`: Time per question (default: 30)
- `MAX_QUESTIONS_PER_QUIZ`: Maximum questions allowed (default: 50)
- `MAX_QUIZ_TITLE_LENGTH`: Title character limit (default: 255)
- `LEADERBOARD_CACHE_TTL`: Cache duration (default: 300s)

### Database Models
- **Quiz**: Stores quiz data with question validation
- **Leaderboard**: Manages user scores with helper methods

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with proper tests
4. Ensure all health checks pass
5. Submit a pull request with detailed description

## 📋 System Requirements

- **Python**: 3.11+ (3.10+ supported)
- **PostgreSQL**: 12+ (15+ recommended)
- **Redis**: 6+ (7+ recommended)
- **Memory**: 512MB minimum (1GB+ recommended)
- **Storage**: 100MB + data storage

## 📄 License

This project is open source and available under the MIT License.

## 🆘 Support

For issues, feature requests, or questions:
1. Check the health status with `/health` command
2. Review logs for error details
3. Verify configuration with `Config.validate()`
4. Create an issue with system information

---

**Built with ❤️ for the Telegram community**