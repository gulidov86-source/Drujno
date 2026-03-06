"""
Модуль: rate_limiter.py
Описание: Настройка Rate Limiting для защиты от перегрузки
Проект: GroupBuy Mini App

Аналогия: турникет на входе в метро — пропускает определённое
количество людей в минуту. Если слишком много — «подождите».

Лимиты:
    - Обычные эндпоинты: 60 запросов/минуту
    - Авторизация (/auth): 5 запросов/минуту (защита от брутфорса)
    - Создание сборов/заказов: 3 запроса/минуту (антиспам)

Использование в роутерах:
    from rate_limiter import limiter, auth_limit, create_limit
    
    @router.post("/auth/telegram")
    @limiter.limit(auth_limit)
    async def auth_telegram(request: Request, ...):
        ...
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse


# ============================================================
# ОПРЕДЕЛЕНИЕ КЛЮЧА ЛИМИТИРОВАНИЯ
# ============================================================

def _get_user_or_ip(request: Request) -> str:
    """
    Определяем кто шлёт запрос: по токену или по IP.
    
    Аналогия: в метро считают по проездному (user_id),
    а если без проездного — по лицу (IP-адрес).
    
    Приоритет:
        1. Bearer токен (хэш) — если пользователь авторизован
        2. X-Forwarded-For — реальный IP за прокси (Railway)
        3. request.client.host — прямой IP
    """
    # Попробуем использовать токен как ключ
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Берём хэш токена (не декодируем — это дорого для rate limiter)
        return f"token:{hash(auth_header)}"
    
    # Fallback на IP (через proxy headers)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    return request.client.host if request.client else "unknown"


# ============================================================
# СОЗДАНИЕ ЛИМИТЕРА
# ============================================================

limiter = Limiter(
    key_func=_get_user_or_ip,
    default_limits=["60/minute"],  # По умолчанию: 60 запросов/минуту
    storage_uri="memory://",       # In-memory (для одного сервера достаточно)
)


# ============================================================
# СТРОКИ ЛИМИТОВ (для удобства импорта в роутеры)
# ============================================================

auth_limit = "5/minute"       # Авторизация: 5 запросов/минуту
create_limit = "3/minute"     # Создание сборов/заказов: 3 запроса/минуту
default_limit = "60/minute"   # Обычные эндпоинты


# ============================================================
# ОБРАБОТЧИК ПРЕВЫШЕНИЯ ЛИМИТА
# ============================================================

async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Обработчик при превышении лимита.
    
    Вместо непонятной ошибки 429 — человекочитаемое JSON-сообщение.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": True,
            "message": "Слишком много запросов. Подождите немного.",
            "detail": str(exc.detail)
        }
    )
