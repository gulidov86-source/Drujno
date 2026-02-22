"""
Модуль: config.py
Описание: Конфигурация приложения и переменные окружения
Проект: GroupBuy Mini App

Этот файл загружает все настройки из .env файла и предоставляет
их остальным модулям приложения через класс Settings.

Использование:
    from config import settings
    print(settings.TELEGRAM_BOT_TOKEN)
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """
    Класс настроек приложения.
    
    Все значения загружаются из переменных окружения или .env файла.
    Pydantic автоматически валидирует типы данных.
    
    Пример:
        settings = Settings()
        token = settings.TELEGRAM_BOT_TOKEN
    """
    
    # ==================== TELEGRAM ====================
    # Токен бота, полученный от @BotFather
    TELEGRAM_BOT_TOKEN: str
    
    # URL твоего Mini App (будет после деплоя на Railway/Render)
    # Пример: https://groupbuy-app.up.railway.app
    TELEGRAM_WEBAPP_URL: str = "http://localhost:8000"
    
    # ==================== БАЗА ДАННЫХ (SUPABASE) ====================
    # URL проекта Supabase
    # Найти: Supabase Dashboard → Settings → API → Project URL
    SUPABASE_URL: str
    
    # Анонимный ключ (public)
    # Найти: Supabase Dashboard → Settings → API → anon/public key
    SUPABASE_ANON_KEY: str
    
    # Сервисный ключ (secret) — для операций от имени сервера
    # Найти: Supabase Dashboard → Settings → API → service_role key
    # ВАЖНО: Никогда не передавай на фронтенд!
    SUPABASE_SERVICE_KEY: str
    
    # ==================== ПЛАТЕЖИ (ЮKASSA) ====================
    # ID магазина в ЮKassa
    # Найти: Личный кабинет ЮKassa → Интеграция → shopId
    YOOKASSA_SHOP_ID: str = ""
    
    # Секретный ключ магазина
    # Найти: Личный кабинет ЮKassa → Интеграция → Секретный ключ
    YOOKASSA_SECRET_KEY: str = ""
    
    # Секрет для проверки webhook'ов (настраивается в ЮKassa)
    YOOKASSA_WEBHOOK_SECRET: str = ""
    
    # ==================== ДОСТАВКА (СДЭК) ====================
    # Учётные данные API СДЭК
    # Получить: https://www.cdek.ru/ru/integration/api
    CDEK_CLIENT_ID: str = ""
    CDEK_CLIENT_SECRET: str = ""
    
    # Режим СДЭК: "test" для тестирования, "prod" для боевого
    CDEK_MODE: str = "test"
    
    # ==================== БЕЗОПАСНОСТЬ (JWT) ====================
    # Секретный ключ для подписи JWT токенов
    # Сгенерировать: python -c "import secrets; print(secrets.token_hex(32))"
    JWT_SECRET: str
    
    # Алгоритм подписи (не менять без необходимости)
    JWT_ALGORITHM: str = "HS256"
    
    # Время жизни токена в часах
    JWT_EXPIRE_HOURS: int = 24 * 7  # 7 дней
    
    # ==================== ПРИЛОЖЕНИЕ ====================
    # Окружение: development, staging, production
    APP_ENV: str = "development"
    
    # Режим отладки (логи, трейсбеки)
    DEBUG: bool = True
    
    # Хост и порт для запуска сервера
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # ==================== БИЗНЕС-ЛОГИКА ====================
    # Дефолтный дедлайн сбора в днях
    DEFAULT_GROUP_DEADLINE_DAYS: int = 7
    
    # Минимальное количество участников для сбора
    DEFAULT_MIN_PARTICIPANTS: int = 3
    
    # Максимальное количество участников
    DEFAULT_MAX_PARTICIPANTS: int = 100
    
    # Комиссия платформы (процент от суммы заказа)
    PLATFORM_FEE_PERCENT: float = 5.0
    
    # Бонус организатора по умолчанию (процент)
    ORGANIZER_BONUS_PERCENT: float = 2.0
    
    ADMIN_BOT_TOKEN: str = "8549743015:AAG71eqE7ZKb_vTZ94VcK0zfZ38Q5KMPyuQ"  # Токен админ-бота (отдельный от основного)

    class Config:
        """
        Конфигурация Pydantic для загрузки из .env файла.
        """
        # Путь к .env файлу (относительно корня проекта)
        env_file = ".env"
        
        # Кодировка файла
        env_file_encoding = "utf-8"
        
        # Чувствительность к регистру переменных
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """
    Получить объект настроек (с кэшированием).
    
    Используем lru_cache чтобы не перечитывать .env при каждом обращении.
    
    Возвращает:
        Settings: Объект с настройками приложения
    
    Пример:
        settings = get_settings()
        print(settings.APP_ENV)  # "development"
    """
    return Settings()


# Создаём глобальный объект настроек для удобного импорта
# Использование: from config import settings
settings = get_settings()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def is_production() -> bool:
    """
    Проверить, запущено ли приложение в production.
    
    Возвращает:
        bool: True если production, иначе False
    
    Пример:
        if is_production():
            # Не показывать отладочную информацию
            pass
    """
    return settings.APP_ENV == "production"


def is_development() -> bool:
    """
    Проверить, запущено ли приложение в режиме разработки.
    
    Возвращает:
        bool: True если development, иначе False
    """
    return settings.APP_ENV == "development"


def get_database_url() -> str:
    """
    Получить URL базы данных Supabase.
    
    Возвращает:
        str: URL для подключения к Supabase
    """
    return settings.SUPABASE_URL


# ==================== ПРОВЕРКА КОНФИГУРАЦИИ ====================

def validate_config() -> dict:
    """
    Проверить, что все обязательные настройки заполнены.
    
    Возвращает:
        dict: Статус проверки
            {
                "valid": True/False,
                "missing": ["список", "пропущенных", "настроек"],
                "warnings": ["предупреждения"]
            }
    
    Пример:
        result = validate_config()
        if not result["valid"]:
            print(f"Ошибка: не заполнены {result['missing']}")
    """
    missing = []
    warnings = []
    
    # Обязательные настройки
    required = [
        ("TELEGRAM_BOT_TOKEN", settings.TELEGRAM_BOT_TOKEN),
        ("SUPABASE_URL", settings.SUPABASE_URL),
        ("SUPABASE_ANON_KEY", settings.SUPABASE_ANON_KEY),
        ("SUPABASE_SERVICE_KEY", settings.SUPABASE_SERVICE_KEY),
        ("JWT_SECRET", settings.JWT_SECRET),
    ]
    
    for name, value in required:
        if not value:
            missing.append(name)
    
    # Предупреждения для опциональных, но важных настроек
    if not settings.YOOKASSA_SHOP_ID:
        warnings.append("YOOKASSA_SHOP_ID не заполнен — оплата не будет работать")
    
    if not settings.CDEK_CLIENT_ID:
        warnings.append("CDEK_CLIENT_ID не заполнен — расчёт доставки не будет работать")
    
    if settings.APP_ENV == "production" and settings.DEBUG:
        warnings.append("DEBUG=True в production — рекомендуется отключить")
    
    return {
        "valid": len(missing) == 0,
        "missing": missing,
        "warnings": warnings
    }


# При импорте модуля выводим предупреждения в режиме разработки
if is_development():
    _config_check = validate_config()
    if _config_check["warnings"]:
        for warning in _config_check["warnings"]:
            print(f"⚠️  Конфигурация: {warning}")
