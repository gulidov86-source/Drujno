"""
Модуль: utils/telegram.py
Описание: Работа с Telegram WebApp API
Проект: GroupBuy Mini App

Этот модуль содержит функции для:
- Валидации initData от Telegram Mini App
- Парсинга данных пользователя
- Генерации deep links

Документация Telegram:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Как это работает:
    1. Mini App получает initData от Telegram
    2. Фронтенд отправляет initData на бэкенд
    3. Бэкенд проверяет подпись (HMAC-SHA256)
    4. Если подпись верна — данным можно доверять

Пример initData:
    "query_id=AAHdF...&user=%7B%22id%22%3A123...&auth_date=1234567890&hash=abc123..."
"""

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from pydantic import BaseModel

import sys
sys.path.append("..")
from config import settings


# ============================================================
# МОДЕЛИ ДАННЫХ
# ============================================================

class TelegramUser(BaseModel):
    """
    Данные пользователя из Telegram.
    
    Эти данные приходят в initData и гарантированы Telegram'ом.
    
    Атрибуты:
        id: Уникальный ID пользователя в Telegram
        first_name: Имя
        last_name: Фамилия (опционально)
        username: @username (опционально)
        language_code: Код языка (ru, en, ...)
        is_premium: Есть ли Premium подписка
        photo_url: URL аватарки (опционально)
    """
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = False
    photo_url: Optional[str] = None


class TelegramInitData(BaseModel):
    """
    Распарсенные данные initData.
    
    Атрибуты:
        user: Данные пользователя
        auth_date: Unix timestamp авторизации
        query_id: ID запроса (для inline режима)
        hash: Подпись для проверки
        start_param: Параметр из deep link (?startapp=xxx)
    """
    user: TelegramUser
    auth_date: int
    query_id: Optional[str] = None
    hash: str
    start_param: Optional[str] = None


# ============================================================
# ВАЛИДАЦИЯ INITDATA
# ============================================================

def validate_telegram_init_data(init_data: str, bot_token: str = None) -> bool:
    """
    Проверить подпись initData от Telegram.
    
    Telegram подписывает данные с помощью HMAC-SHA256.
    Мы проверяем, что данные не были подделаны.
    
    Параметры:
        init_data: Строка initData от Telegram WebApp
        bot_token: Токен бота (если None — берётся из настроек)
    
    Возвращает:
        bool: True если подпись верна, False если нет
    
    Алгоритм проверки (из документации Telegram):
        1. Парсим init_data как query string
        2. Извлекаем hash
        3. Сортируем остальные параметры по алфавиту
        4. Формируем строку "key=value\nkey=value\n..."
        5. Создаём secret_key = HMAC-SHA256("WebAppData", bot_token)
        6. Вычисляем hash = HMAC-SHA256(secret_key, data_check_string)
        7. Сравниваем с полученным hash
    
    Пример:
        init_data = request.headers.get("X-Telegram-Init-Data")
        if validate_telegram_init_data(init_data):
            # Данным можно доверять
            user = parse_telegram_user(init_data)
        else:
            # Данные подделаны!
            raise HTTPException(401, "Invalid Telegram data")
    """
    if not init_data:
        return False
    
    # Используем токен из настроек, если не передан
    if bot_token is None:
        bot_token = settings.TELEGRAM_BOT_TOKEN
    
    try:
        # Парсим query string
        parsed_data = parse_qs(init_data, keep_blank_values=True)
        
        # Извлекаем hash (он не участвует в проверке)
        received_hash = parsed_data.get("hash", [None])[0]
        if not received_hash:
            return False
        
        # Собираем остальные параметры
        data_check_parts = []
        for key, values in sorted(parsed_data.items()):
            if key == "hash":
                continue
            # Берём первое значение каждого параметра
            value = values[0] if values else ""
            data_check_parts.append(f"{key}={value}")
        
        # Формируем строку для проверки
        data_check_string = "\n".join(data_check_parts)
        
        # Создаём secret key
        # secret_key = HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        
        # Вычисляем hash
        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        # Сравниваем (безопасное сравнение для защиты от timing attack)
        return hmac.compare_digest(calculated_hash, received_hash)
        
    except Exception as e:
        # При любой ошибке парсинга — данные невалидны
        print(f"Ошибка валидации initData: {e}")
        return False


def is_init_data_expired(init_data: str, max_age_seconds: int = 86400) -> bool:
    """
    Проверить, не устарели ли данные initData.
    
    По умолчанию данные считаются устаревшими через 24 часа.
    Это защита от replay-атак.
    
    Параметры:
        init_data: Строка initData
        max_age_seconds: Максимальный возраст в секундах (по умолчанию 24 часа)
    
    Возвращает:
        bool: True если данные устарели
    
    Пример:
        if is_init_data_expired(init_data):
            raise HTTPException(401, "Session expired")
    """
    try:
        parsed_data = parse_qs(init_data)
        auth_date = int(parsed_data.get("auth_date", [0])[0])
        
        current_time = int(time.time())
        age = current_time - auth_date
        
        return age > max_age_seconds
        
    except Exception:
        return True  # При ошибке считаем устаревшими


# ============================================================
# ПАРСИНГ ДАННЫХ ПОЛЬЗОВАТЕЛЯ
# ============================================================

def parse_telegram_user(init_data: str) -> Optional[TelegramUser]:
    """
    Извлечь данные пользователя из initData.
    
    ВАЖНО: Вызывай эту функцию только ПОСЛЕ validate_telegram_init_data()!
    Эта функция не проверяет подпись.
    
    Параметры:
        init_data: Строка initData от Telegram
    
    Возвращает:
        TelegramUser | None: Данные пользователя или None при ошибке
    
    Пример:
        # Сначала проверяем подпись
        if validate_telegram_init_data(init_data):
            user = parse_telegram_user(init_data)
            print(f"Привет, {user.first_name}!")
    """
    try:
        # Парсим query string
        parsed_data = parse_qs(init_data, keep_blank_values=True)
        
        # Получаем JSON строку с данными пользователя
        user_json = parsed_data.get("user", [None])[0]
        if not user_json:
            return None
        
        # Декодируем URL-encoded JSON
        user_json = unquote(user_json)
        
        # Парсим JSON
        user_data = json.loads(user_json)
        
        # Создаём объект TelegramUser
        return TelegramUser(**user_data)
        
    except Exception as e:
        print(f"Ошибка парсинга user из initData: {e}")
        return None


def parse_telegram_init_data(init_data: str) -> Optional[TelegramInitData]:
    """
    Полный парсинг initData.
    
    Возвращает все данные: пользователя, auth_date, start_param и т.д.
    
    Параметры:
        init_data: Строка initData от Telegram
    
    Возвращает:
        TelegramInitData | None: Все данные или None при ошибке
    
    Пример:
        data = parse_telegram_init_data(init_data)
        if data:
            print(f"User ID: {data.user.id}")
            print(f"Auth date: {data.auth_date}")
            if data.start_param:
                print(f"Start param: {data.start_param}")
    """
    try:
        parsed_data = parse_qs(init_data, keep_blank_values=True)
        
        # Парсим пользователя
        user = parse_telegram_user(init_data)
        if not user:
            return None
        
        # Собираем остальные данные
        return TelegramInitData(
            user=user,
            auth_date=int(parsed_data.get("auth_date", [0])[0]),
            query_id=parsed_data.get("query_id", [None])[0],
            hash=parsed_data.get("hash", [""])[0],
            start_param=parsed_data.get("start_param", [None])[0]
        )
        
    except Exception as e:
        print(f"Ошибка парсинга initData: {e}")
        return None


# ============================================================
# DEEP LINKS
# ============================================================

def generate_start_link(bot_username: str, start_param: str) -> str:
    """
    Сгенерировать deep link для бота.
    
    Параметры:
        bot_username: Username бота (без @)
        start_param: Параметр для передачи
    
    Возвращает:
        str: Deep link
    
    Пример:
        link = generate_start_link("MyGroupBuyBot", "group_42")
        # https://t.me/MyGroupBuyBot?start=group_42
    """
    return f"https://t.me/{bot_username}?start={start_param}"


def generate_webapp_link(bot_username: str, start_param: str = None) -> str:
    """
    Сгенерировать deep link для Mini App.
    
    Параметры:
        bot_username: Username бота (без @)
        start_param: Параметр для передачи (опционально)
    
    Возвращает:
        str: Deep link для Mini App
    
    Пример:
        # Без параметра
        link = generate_webapp_link("MyGroupBuyBot")
        # https://t.me/MyGroupBuyBot/app
        
        # С параметром (для шеринга сбора)
        link = generate_webapp_link("MyGroupBuyBot", "g_42_r_123")
        # https://t.me/MyGroupBuyBot/app?startapp=g_42_r_123
    """
    base_url = f"https://t.me/{bot_username}/app"
    
    if start_param:
        return f"{base_url}?startapp={start_param}"
    
    return base_url


def parse_start_param(start_param: str) -> dict:
    """
    Распарсить параметр из deep link.
    
    Формат: "g_{group_id}_r_{referrer_id}"
    - g_ — ID группового сбора
    - r_ — ID пригласившего пользователя
    
    Параметры:
        start_param: Параметр из deep link
    
    Возвращает:
        dict: Распарсенные данные
    
    Пример:
        params = parse_start_param("g_42_r_123")
        # {"group_id": 42, "referrer_id": 123}
        
        params = parse_start_param("g_42")
        # {"group_id": 42, "referrer_id": None}
    """
    result = {
        "group_id": None,
        "referrer_id": None,
        "raw": start_param
    }
    
    if not start_param:
        return result
    
    parts = start_param.split("_")
    
    # Парсим по частям
    i = 0
    while i < len(parts):
        if parts[i] == "g" and i + 1 < len(parts):
            try:
                result["group_id"] = int(parts[i + 1])
            except ValueError:
                pass
            i += 2
        elif parts[i] == "r" and i + 1 < len(parts):
            try:
                result["referrer_id"] = int(parts[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1
    
    return result


def generate_share_link(group_id: int, referrer_id: int, bot_username: str) -> str:
    """
    Сгенерировать ссылку для шеринга сбора.
    
    Параметры:
        group_id: ID сбора
        referrer_id: ID пользователя, который делится
        bot_username: Username бота
    
    Возвращает:
        str: Ссылка для шеринга
    
    Пример:
        link = generate_share_link(42, 123, "MyGroupBuyBot")
        # https://t.me/MyGroupBuyBot/app?startapp=g_42_r_123
    """
    start_param = f"g_{group_id}_r_{referrer_id}"
    return generate_webapp_link(bot_username, start_param)


# ============================================================
# ТЕСТИРОВАНИЕ
# ============================================================

if __name__ == "__main__":
    """
    Тесты при запуске файла напрямую.
    
    Запуск:
        python utils/telegram.py
    """
    print("🧪 Тестирование модуля telegram.py\n")
    
    # Тест парсинга start_param
    print("1. Парсинг start_param:")
    test_cases = [
        "g_42_r_123",
        "g_42",
        "r_123",
        "invalid",
        ""
    ]
    for param in test_cases:
        result = parse_start_param(param)
        print(f"   '{param}' → {result}")
    
    # Тест генерации ссылок
    print("\n2. Генерация ссылок:")
    link = generate_share_link(42, 123, "TestBot")
    print(f"   Share link: {link}")
    
    link = generate_webapp_link("TestBot")
    print(f"   WebApp link: {link}")
    
    print("\n✅ Тесты завершены")
