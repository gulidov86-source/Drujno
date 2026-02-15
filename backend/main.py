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

# Импортируем наши модули
from config import settings, validate_config, is_development
from database.connection import check_connection


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
    # ===== STARTUP =====
    print("🚀 Запуск GroupBuy Mini App...")
    
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
    print("─" * 50)
    
    yield  # Приложение работает
    
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
    docs_url="/docs",           # Swagger UI
    redoc_url="/redoc",         # ReDoc
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# ============================================================
# MIDDLEWARE
# ============================================================

# CORS — разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    # В production укажи конкретные домены:
    # allow_origins=["https://твой-домен.com", "https://t.me"]
    allow_origins=["*"] if is_development() else [
        settings.TELEGRAM_WEBAPP_URL,
        "https://web.telegram.org",
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
    """
    if is_development():
        # В разработке показываем детали
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
        # В production скрываем детали
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
    return FileResponse("frontend/index.html")




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
from routers import users, products, groups, orders, payments

app.include_router(users.router)
app.include_router(products.router)
app.include_router(groups.router)
app.include_router(orders.router)
app.include_router(payments.router)
#app.include_router(delivery.router)
#app.include_router(returns.router)
#app.include_router(support.router)
#app.include_router(notifications.router)


# ============================================================
# ЗАПУСК
# ============================================================
app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
app.mount("/js", StaticFiles(directory="frontend/js"), name="js")
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
