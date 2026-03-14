"""

Модуль: main.py
Описание: Точка входа приложения FastAPI
Проект: GroupBuy Mini App

Запуск:
    # Режим разработки (с автоперезагрузкой)
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    
    # Production
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

Документация API после запуска:
    - Swagger UI: http://localhost:8000/docs
    - ReDoc: http://localhost:8000/redoc
"""



from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.gzip import GZipMiddleware

# Импортируем наши модули
from config import settings, validate_config, is_development
from database.connection import check_connection

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from rate_limiter import limiter, rate_limit_exceeded_handler


# ============================================================
# SENTRY — мониторинг ошибок
# ============================================================
# 
# Аналогия: Sentry — это чёрный ящик самолёта.
# Когда на проде что-то падает — Sentry записывает:
# кто, где, когда, что случилось, stack trace.
# Ты получаешь уведомление и видишь ошибку с контекстом,
# а не просто «что-то сломалось».

if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            # traces_sample_rate=0.1 — записываем 10% запросов для performance
            traces_sample_rate=0.1 if not is_development() else 0.0,
            # Не отправляем в dev
            send_default_pii=False,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                StarletteIntegration(transaction_style="endpoint"),
            ],
        )
        print("✅ Sentry подключён")
    except ImportError:
        print("⚠️  sentry-sdk не установлен, мониторинг ошибок отключён")



# ============================================================
# СОБЫТИЯ ЖИЗНЕННОГО ЦИКЛА
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.
    
    Этот контекстный менеджер выполняется:
    - При старте: код до yield
    - При остановке: код после yield
    
    Используем для:
    - Проверки конфигурации при старте
    - Проверки подключения к БД
    - Освобождения ресурсов при остановке
    """
    from logger import get_logger

    logger = get_logger("main")
    # ===== STARTUP =====
    logger.info("Запуск GroupBuy Mini App")
    
    # Проверяем конфигурацию
    config_check = validate_config()
    if not config_check["valid"]:
        print("❌ Ошибка конфигурации!")
        print(f"   Не заполнены: {', '.join(config_check['missing'])}")
        print("   Проверь .env файл")
        # В production можно выбросить исключение
        # raise RuntimeError("Invalid configuration")
    else:
        print("✅ Конфигурация OK")
    
    # Проверяем подключение к БД
    db_check = await check_connection()
    if db_check["connected"]:
        print("✅ База данных OK")
    else:
        print(f"⚠️  База данных: {db_check['error']}")

    
    # Выводим информацию о режиме
    print(f"📍 Режим: {settings.APP_ENV}")
    print(f"🌐 URL: http://{settings.HOST}:{settings.PORT}")
    print(f"📚 Документация: http://{settings.HOST}:{settings.PORT}/docs")

    from scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    print("─" * 50)
    
    yield  # Приложение работает

    stop_scheduler()
    # ===== SHUTDOWN =====
    print("👋 Остановка приложения...")
    # Здесь можно закрыть соединения, сохранить состояние и т.д.


# ============================================================
# СОЗДАНИЕ ПРИЛОЖЕНИЯ
# ============================================================

app = FastAPI(
    title="GroupBuy Mini App API",
    description="""
    API для Telegram Mini App групповых покупок.
    
    ## Основные возможности
    
    * 🛍 **Товары** — каталог с ценовыми порогами
    * 👥 **Сборы** — групповые закупки
    * 💳 **Оплата** — через ЮKassa
    * 📦 **Доставка** — интеграция с СДЭК
    * 🔄 **Возвраты** — система возвратов
    * 💬 **Поддержка** — чат с поддержкой
    
    ## Авторизация
    
    Используется JWT токен, полученный при авторизации через Telegram.
    Передавайте в заголовке: `Authorization: Bearer <token>`
    """,
    version="1.0.0",
    # В production отключаем документацию — чтобы не светить API наружу
    docs_url="/docs" if is_development() else None,
    redoc_url="/redoc" if is_development() else None,
    openapi_url="/openapi.json" if is_development() else None,
    lifespan=lifespan
)

# Rate Limiting — защита от перегрузки
# Аналогия: турникет в метро — пропускает 60 человек/минуту
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# GZip — сжимаем ответы для ускорения загрузки
# minimum_size=1000 — не сжимаем мелкие ответы (нет смысла)
# Аналогия: упаковщик, который сжимает посылки перед отправкой
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ============================================================
# MIDDLEWARE
# ============================================================

# CORS — разрешаем запросы с фронтенда
# 
# Наглядно: CORS — это как "список пропусков" на вход.
# В dev: пускаем всех ("*") — удобно для тестирования.
# В prod: только Telegram и наш домен — для безопасности.
#
# Telegram Mini App загружается через несколько доменов:
# - web.telegram.org — веб-версия
# - t.me — мобильная ссылка
# - наш домен — когда API и фронтенд на одном сервере
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if is_development() else [
        settings.TELEGRAM_WEBAPP_URL,
        "https://web.telegram.org",
        "https://webk.telegram.org",
        "https://webz.telegram.org",
        "https://t.me"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """
    Middleware для измерения времени обработки запроса.
    
    Добавляет заголовок X-Process-Time в ответ.
    Полезно для отладки и мониторинга.
    """
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time * 1000, 2)) + "ms"
    # === КЕШИРОВАНИЕ API-ответов ===
    # GET-запросы к API — кешируем на 30 сек (stale-while-revalidate даёт ещё 60 сек)
    # Это значит: браузер отдаст закешированный ответ мгновенно,
    # а в фоне проверит — не обновилось ли.
    # Аналогия: официант приносит вчерашнее меню, но идёт уточнять на кухню.
    path = request.url.path
    if request.method == "GET" and path.startswith("/api/"):
        # Не кешируем личные данные и платежи
        no_cache_paths = ["/api/users/me", "/api/orders", "/api/payments", 
                          "/api/notifications", "/api/support"]
        if not any(path.startswith(p) for p in no_cache_paths):
            response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
        else:
            response.headers["Cache-Control"] = "private, no-store"
    return response


# ============================================================
# ОБРАБОТКА ОШИБОК
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Глобальный обработчик исключений.
    
    Ловит все необработанные ошибки и возвращает красивый JSON.
    В production скрывает детали ошибки.
    Sentry автоматически перехватывает ошибки через интеграцию,
    но мы дополнительно логируем для надёжности.
    """
    from logger import get_logger
    logger = get_logger("main")
    logger.error("Необработанная ошибка", 
                 path=request.url.path, 
                 method=request.method,
                 error=str(exc),
                 error_type=type(exc).__name__,
                 exc_info=True)
    
    if is_development():
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "message": str(exc),
                "type": type(exc).__name__,
                "path": request.url.path
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "message": "Внутренняя ошибка сервера"
            }
        )


# ============================================================
# БАЗОВЫЕ ЭНДПОИНТЫ
# ============================================================

@app.get("/", tags=["Система"])
async def root():
    return FileResponse("../frontend/index.html")




@app.get("/health", tags=["Система"])
async def health_check():
    """
    Проверка здоровья приложения.
    
    Используется для мониторинга и load balancer'ов.
    Проверяет:
    - Доступность приложения
    - Подключение к БД
    """
    # Проверяем БД
    db_status = await check_connection()
    
    return {
        "status": "healthy" if db_status["connected"] else "degraded",
        "checks": {
            "database": {
                "status": "ok" if db_status["connected"] else "error",
                "message": db_status.get("error")
            }
        },
        "environment": settings.APP_ENV
    }


@app.get("/config", tags=["Система"])
async def get_config():
    """
    Получить публичную конфигурацию.
    
    Возвращает только безопасные настройки для фронтенда.
    НЕ возвращает секретные ключи!
    """
    return {
        "environment": settings.APP_ENV,
        "webapp_url": settings.TELEGRAM_WEBAPP_URL,
        "features": {
            "payments_enabled": bool(settings.YOOKASSA_SHOP_ID),
            "delivery_enabled": bool(settings.CDEK_CLIENT_ID),
        },
        "limits": {
            "min_participants": settings.DEFAULT_MIN_PARTICIPANTS,
            "max_participants": settings.DEFAULT_MAX_PARTICIPANTS,
            "group_deadline_days": settings.DEFAULT_GROUP_DEADLINE_DAYS,
        }
    }


# ============================================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ
# ============================================================

# TODO: Раскомментировать после создания роутеров в Фазе 2

#from routers import users, products, groups, orders, payments, delivery, returns, support, notifications
from routers import users, products, groups, orders, payments, delivery, returns, support, notifications
from routers import analytics
from routers import image_upload

app.include_router(image_upload.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(groups.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(delivery.router)
app.include_router(returns.router)
app.include_router(support.router)
app.include_router(notifications.router)
app.include_router(analytics.router)


# ============================================================
# ЗАПУСК
# ============================================================
# Статика с кеш-заголовками.
# ?v=6 в URL обеспечивает cache-busting при обновлении.
# max-age=86400 (1 день) — браузер не будет перекачивать файлы.
# Аналогия: как дата на молоке — «свежее до завтра, не надо
# каждый час нюхать».
from starlette.staticfiles import StaticFiles as _StaticFiles
from starlette.responses import Response

class CachedStaticFiles(_StaticFiles):
    """StaticFiles с заголовком Cache-Control."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Кешируем на 1 день (cache-busting через ?v=N)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

app.mount("/css", CachedStaticFiles(directory="../frontend/css"), name="css")
app.mount("/js", CachedStaticFiles(directory="../frontend/js"), name="js")
if __name__ == "__main__":
    """
    Запуск приложения напрямую через Python.
    
    Использование:
        python main.py
    
    Или через uvicorn (рекомендуется):
        uvicorn main:app --reload
    """
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=is_development(),  # Автоперезагрузка в разработке
        log_level="debug" if settings.DEBUG else "info"
    )
