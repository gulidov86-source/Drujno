"""
Модуль: utils/auth.py
Описание: Авторизация и работа с JWT токенами
Проект: GroupBuy Mini App

Этот модуль содержит:
- Создание JWT токенов
- Верификация токенов
- Dependency для получения текущего пользователя

Как работает авторизация:
    1. Пользователь открывает Mini App
    2. Фронтенд отправляет initData на /api/users/auth
    3. Бэкенд проверяет initData и создаёт JWT токен
    4. Фронтенд сохраняет токен и передаёт в заголовках
    5. Бэкенд проверяет токен и определяет пользователя

Использование:
    from utils.auth import get_current_user
    
    @router.get("/profile")
    async def get_profile(user_id: int = Depends(get_current_user)):
        # user_id гарантированно валидный
        return await get_user_by_id(user_id)
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

import sys
sys.path.append("..")
from config import settings


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Схема авторизации через Bearer токен
# Ожидает заголовок: Authorization: Bearer <token>
security = HTTPBearer(
    scheme_name="JWT",
    description="JWT токен, полученный при авторизации через Telegram",
    auto_error=False  # Не выбрасываем ошибку автоматически
)


# ============================================================
# МОДЕЛИ
# ============================================================

class TokenPayload(BaseModel):
    """
    Данные внутри JWT токена.
    
    Атрибуты:
        sub: Subject — ID пользователя (строка для совместимости)
        telegram_id: ID в Telegram
        exp: Expiration — время истечения
        iat: Issued At — время создания
        type: Тип токена (access, refresh)
    """
    sub: str  # user_id как строка
    telegram_id: int
    exp: datetime
    iat: datetime
    type: str = "access"


class TokenResponse(BaseModel):
    """
    Ответ с токеном при авторизации.
    
    Атрибуты:
        access_token: JWT токен
        token_type: Тип токена (всегда "bearer")
        expires_in: Время жизни в секундах
    """
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ============================================================
# СОЗДАНИЕ ТОКЕНА
# ============================================================

def create_access_token(
    user_id: int,
    telegram_id: int,
    expires_delta: timedelta = None
) -> str:
    """
    Создать JWT access токен.
    
    Параметры:
        user_id: ID пользователя в нашей БД
        telegram_id: ID пользователя в Telegram
        expires_delta: Время жизни токена (опционально)
    
    Возвращает:
        str: JWT токен
    
    Пример:
        token = create_access_token(user_id=42, telegram_id=123456789)
        # eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    """
    # Определяем время жизни
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    
    # Формируем payload
    payload = {
        "sub": str(user_id),  # Subject — ID пользователя
        "telegram_id": telegram_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    }
    
    # Создаём токен
    token = jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )
    
    return token


def create_token_response(user_id: int, telegram_id: int) -> TokenResponse:
    """
    Создать полный ответ с токеном.
    
    Параметры:
        user_id: ID пользователя в БД
        telegram_id: ID пользователя в Telegram
    
    Возвращает:
        TokenResponse: Объект с токеном и метаданными
    
    Пример:
        response = create_token_response(42, 123456789)
        # {
        #     "access_token": "eyJ...",
        #     "token_type": "bearer",
        #     "expires_in": 604800
        # }
    """
    token = create_access_token(user_id, telegram_id)
    expires_in = settings.JWT_EXPIRE_HOURS * 3600  # В секундах
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
    )


# ============================================================
# ВЕРИФИКАЦИЯ ТОКЕНА
# ============================================================

def verify_token(token: str) -> Optional[TokenPayload]:
    """
    Проверить и декодировать JWT токен.
    
    Параметры:
        token: JWT токен
    
    Возвращает:
        TokenPayload | None: Данные токена или None если невалиден
    
    Пример:
        payload = verify_token(token)
        if payload:
            print(f"User ID: {payload.sub}")
        else:
            print("Токен невалиден")
    """
    try:
        # Декодируем токен
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # Проверяем обязательные поля
        if "sub" not in payload:
            return None
        
        # Создаём объект TokenPayload
        return TokenPayload(
            sub=payload["sub"],
            telegram_id=payload.get("telegram_id", 0),
            exp=datetime.fromtimestamp(payload["exp"]),
            iat=datetime.fromtimestamp(payload["iat"]),
            type=payload.get("type", "access")
        )
        
    except JWTError as e:
        # Токен невалиден или истёк
        print(f"JWT Error: {e}")
        return None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None


def is_token_expired(payload: TokenPayload) -> bool:
    """
    Проверить, истёк ли токен.
    
    Параметры:
        payload: Данные токена
    
    Возвращает:
        bool: True если токен истёк
    """
    return datetime.utcnow() > payload.exp


# ============================================================
# DEPENDENCIES ДЛЯ FASTAPI
# ============================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> int:
    """
    FastAPI Dependency для получения текущего пользователя.
    
    Извлекает user_id из JWT токена в заголовке Authorization.
    Выбрасывает HTTPException если токен невалиден.
    
    Использование:
        @router.get("/me")
        async def get_my_profile(user_id: int = Depends(get_current_user)):
            # user_id гарантированно валидный
            return await get_user_by_id(user_id)
    
    Возвращает:
        int: ID пользователя в БД
    
    Исключения:
        HTTPException 401: Токен отсутствует, невалиден или истёк
    """
    # Проверяем наличие credentials
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Получаем токен
    token = credentials.credentials
    
    # Верифицируем токен
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Проверяем срок действия
    if is_token_expired(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен истёк",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Возвращаем ID пользователя
    return int(payload.sub)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[int]:
    """
    Опциональная версия get_current_user.
    
    Не выбрасывает ошибку если токен отсутствует.
    Полезно для эндпоинтов, которые работают и с авторизованными,
    и с анонимными пользователями.
    
    Использование:
        @router.get("/products")
        async def get_products(user_id: Optional[int] = Depends(get_current_user_optional)):
            if user_id:
                # Показываем персонализированный контент
                pass
            else:
                # Показываем общий контент
                pass
    
    Возвращает:
        int | None: ID пользователя или None
    """
    if credentials is None:
        return None
    
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None or is_token_expired(payload):
        return None
    
    return int(payload.sub)


async def get_telegram_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> int:
    """
    Получить Telegram ID текущего пользователя.
    
    Использование:
        @router.get("/telegram-info")
        async def get_tg_info(tg_id: int = Depends(get_telegram_id)):
            return {"telegram_id": tg_id}
    
    Возвращает:
        int: Telegram ID пользователя
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация"
        )
    
    payload = verify_token(credentials.credentials)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен"
        )
    
    return payload.telegram_id


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def extract_user_id_from_token(token: str) -> Optional[int]:
    """
    Извлечь user_id из токена без выбрасывания исключений.
    
    Полезно для логирования и аналитики.
    
    Параметры:
        token: JWT токен
    
    Возвращает:
        int | None: ID пользователя или None
    """
    payload = verify_token(token)
    if payload:
        return int(payload.sub)
    return None


def get_token_remaining_time(token: str) -> Optional[timedelta]:
    """
    Получить оставшееся время жизни токена.
    
    Параметры:
        token: JWT токен
    
    Возвращает:
        timedelta | None: Оставшееся время или None
    
    Пример:
        remaining = get_token_remaining_time(token)
        if remaining and remaining.total_seconds() < 3600:
            # Токен скоро истечёт, можно обновить
            pass
    """
    payload = verify_token(token)
    if payload is None:
        return None
    
    remaining = payload.exp - datetime.utcnow()
    
    if remaining.total_seconds() < 0:
        return None
    
    return remaining


# ============================================================
# ТЕСТИРОВАНИЕ
# ============================================================

if __name__ == "__main__":
    """
    Тесты при запуске файла напрямую.
    
    Запуск:
        python utils/auth.py
    """
    print("🧪 Тестирование модуля auth.py\n")
    
    # Тест создания токена
    print("1. Создание токена:")
    token = create_access_token(user_id=42, telegram_id=123456789)
    print(f"   Token: {token[:50]}...")
    
    # Тест верификации
    print("\n2. Верификация токена:")
    payload = verify_token(token)
    if payload:
        print(f"   User ID: {payload.sub}")
        print(f"   Telegram ID: {payload.telegram_id}")
        print(f"   Expires: {payload.exp}")
        print(f"   Is expired: {is_token_expired(payload)}")
    else:
        print("   ❌ Токен невалиден")
    
    # Тест оставшегося времени
    print("\n3. Оставшееся время:")
    remaining = get_token_remaining_time(token)
    if remaining:
        hours = remaining.total_seconds() / 3600
        print(f"   Осталось: {hours:.1f} часов")
    
    # Тест невалидного токена
    print("\n4. Невалидный токен:")
    bad_payload = verify_token("invalid.token.here")
    print(f"   Результат: {bad_payload}")
    
    print("\n✅ Тесты завершены")
