"""
Модуль: database/connection.py
Описание: Подключение к базе данных Supabase
Проект: GroupBuy Mini App

Supabase — это Backend-as-a-Service на базе PostgreSQL.
Мы используем официальный Python SDK для работы с ним.

Документация Supabase:
    https://supabase.com/docs/reference/python/introduction

Использование:
    from database.connection import get_db
    
    async def my_function():
        db = get_db()
        result = db.table("users").select("*").execute()
"""

from typing import Optional
from supabase import create_client, Client

import sys
sys.path.append("../../..")
from backend.config import settings


# ==================== КЛИЕНТ SUPABASE ====================

# Глобальная переменная для хранения клиента
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Получить клиент Supabase (singleton).
    
    Создаёт подключение при первом вызове, затем переиспользует.
    Использует service_role ключ для полного доступа к БД.
    
    Возвращает:
        Client: Клиент Supabase для работы с БД
    
    Исключения:
        ValueError: Если не заполнены SUPABASE_URL или SUPABASE_SERVICE_KEY
    
    Пример:
        client = get_supabase_client()
        
        # Получить всех пользователей
        result = client.table("users").select("*").execute()
        users = result.data
        
        # Создать нового пользователя
        new_user = {"telegram_id": 123, "username": "ivan"}
        result = client.table("users").insert(new_user).execute()
    """
    global _supabase_client
    
    # Если клиент уже создан — возвращаем его
    if _supabase_client is not None:
        return _supabase_client
    
    # Проверяем наличие настроек
    if not settings.SUPABASE_URL:
        raise ValueError(
            "SUPABASE_URL не заполнен! "
            "Укажи URL проекта в .env файле."
        )
    
    if not settings.SUPABASE_SERVICE_KEY:
        raise ValueError(
            "SUPABASE_SERVICE_KEY не заполнен! "
            "Укажи service_role ключ в .env файле."
        )
    
    # Создаём клиент с сервисным ключом
    # Сервисный ключ даёт полный доступ, минуя Row Level Security
    _supabase_client = create_client(
        supabase_url=settings.SUPABASE_URL,
        supabase_key=settings.SUPABASE_SERVICE_KEY
    )
    
    return _supabase_client


def get_db() -> Client:
    """
    Алиас для get_supabase_client().
    
    Короткое имя для удобства использования в коде.
    
    Пример:
        db = get_db()
        users = db.table("users").select("*").execute().data
    """
    return get_supabase_client()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_anon_client() -> Client:
    """
    Получить клиент с анонимным ключом (для фронтенда).
    
    Анонимный ключ имеет ограниченные права согласно Row Level Security.
    Используй его когда нужно ограничить доступ пользователя.
    
    Возвращает:
        Client: Клиент Supabase с ограниченными правами
    
    Пример:
        # На фронтенде (или для проверки RLS)
        anon_client = get_anon_client()
        # Этот запрос вернёт только разрешённые данные
        result = anon_client.table("products").select("*").execute()
    """
    return create_client(
        supabase_url=settings.SUPABASE_URL,
        supabase_key=settings.SUPABASE_ANON_KEY
    )


async def check_connection() -> dict:
    """
    Проверить подключение к Supabase.
    
    Выполняет простой запрос к БД для проверки связи.
    
    Возвращает:
        dict: Результат проверки
            {
                "connected": True/False,
                "message": "описание",
                "error": "ошибка если есть"
            }
    
    Пример:
        result = await check_connection()
        if result["connected"]:
            print("БД работает!")
        else:
            print(f"Ошибка: {result['error']}")
    """
    try:
        db = get_db()
        
        # Пробуем выполнить простой запрос
        # Запрашиваем системную таблицу (всегда существует)
        result = db.table("users").select("id").limit(1).execute()
        
        return {
            "connected": True,
            "message": "Успешное подключение к Supabase",
            "error": None
        }
        
    except Exception as e:
        return {
            "connected": False,
            "message": "Не удалось подключиться к Supabase",
            "error": str(e)
        }


# ==================== ХЕЛПЕРЫ ДЛЯ РАБОТЫ С ДАННЫМИ ====================

class DatabaseHelper:
    """
    Вспомогательный класс для типичных операций с БД.
    
    Упрощает частые паттерны работы с Supabase.
    
    Пример:
        helper = DatabaseHelper("users")
        
        # Получить по ID
        user = helper.get_by_id(42)
        
        # Получить по условию
        users = helper.get_where({"level": "expert"})
        
        # Создать запись
        new_user = helper.create({"telegram_id": 123})
    """
    
    def __init__(self, table_name: str):
        """
        Инициализация хелпера для конкретной таблицы.
        
        Параметры:
            table_name: Название таблицы в БД
        """
        self.table_name = table_name
        self.db = get_db()
    
    def get_by_id(self, record_id: int) -> Optional[dict]:
        """
        Получить запись по ID.
        
        Параметры:
            record_id: ID записи
        
        Возвращает:
            dict | None: Запись или None если не найдена
        
        Пример:
            user = helper.get_by_id(42)
            if user:
                print(user["username"])
        """
        result = (
            self.db
            .table(self.table_name)
            .select("*")
            .eq("id", record_id)
            .limit(1)
            .execute()
        )
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    
    def get_where(self, conditions: dict, limit: int = 100) -> list:
        """
        Получить записи по условиям.
        
        Параметры:
            conditions: Словарь условий {поле: значение}
            limit: Максимум записей (по умолчанию 100)
        
        Возвращает:
            list: Список записей
        
        Пример:
            # Найти всех экспертов
            experts = helper.get_where({"level": "expert"})
            
            # Найти активные сборы
            groups = helper.get_where({"status": "active"}, limit=50)
        """
        query = self.db.table(self.table_name).select("*")
        
        for field, value in conditions.items():
            query = query.eq(field, value)
        
        result = query.limit(limit).execute()
        return result.data or []
    
    def get_all(self, limit: int = 100, offset: int = 0) -> list:
        """
        Получить все записи с пагинацией.
        
        Параметры:
            limit: Количество записей
            offset: Смещение (для пагинации)
        
        Возвращает:
            list: Список записей
        
        Пример:
            # Первая страница (записи 0-99)
            page1 = helper.get_all(limit=100, offset=0)
            
            # Вторая страница (записи 100-199)
            page2 = helper.get_all(limit=100, offset=100)
        """
        result = (
            self.db
            .table(self.table_name)
            .select("*")
            .range(offset, offset + limit - 1)
            .execute()
        )
        return result.data or []
    
    def create(self, data: dict) -> dict:
        """
        Создать новую запись.
        
        Параметры:
            data: Данные для создания
        
        Возвращает:
            dict: Созданная запись с ID
        
        Исключения:
            Exception: При ошибке создания
        
        Пример:
            new_user = helper.create({
                "telegram_id": 123456,
                "username": "ivan",
                "first_name": "Иван"
            })
            print(f"Создан пользователь с ID: {new_user['id']}")
        """
        result = (
            self.db
            .table(self.table_name)
            .insert(data)
            .execute()
        )
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        
        raise Exception(f"Не удалось создать запись в {self.table_name}")
    
    def update(self, record_id: int, data: dict) -> dict:
        """
        Обновить запись по ID.
        
        Параметры:
            record_id: ID записи
            data: Данные для обновления
        
        Возвращает:
            dict: Обновлённая запись
        
        Пример:
            updated = helper.update(42, {"level": "expert"})
        """
        result = (
            self.db
            .table(self.table_name)
            .update(data)
            .eq("id", record_id)
            .execute()
        )
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        
        raise Exception(f"Не удалось обновить запись {record_id} в {self.table_name}")
    
    def delete(self, record_id: int) -> bool:
        """
        Удалить запись по ID.
        
        Параметры:
            record_id: ID записи
        
        Возвращает:
            bool: True если удалено успешно
        
        Пример:
            if helper.delete(42):
                print("Запись удалена")
        """
        result = (
            self.db
            .table(self.table_name)
            .delete()
            .eq("id", record_id)
            .execute()
        )
        return True
    
    def count(self, conditions: dict = None) -> int:
        """
        Посчитать количество записей.
        
        Параметры:
            conditions: Условия фильтрации (опционально)
        
        Возвращает:
            int: Количество записей
        
        Пример:
            total_users = helper.count()
            active_groups = helper.count({"status": "active"})
        """
        query = self.db.table(self.table_name).select("id", count="exact")
        
        if conditions:
            for field, value in conditions.items():
                query = query.eq(field, value)
        
        result = query.execute()
        return result.count or 0


# ==================== ФАБРИКИ ХЕЛПЕРОВ ====================
# Готовые хелперы для каждой таблицы

def users_db() -> DatabaseHelper:
    """Хелпер для таблицы users"""
    return DatabaseHelper("users")

def products_db() -> DatabaseHelper:
    """Хелпер для таблицы products"""
    return DatabaseHelper("products")

def groups_db() -> DatabaseHelper:
    """Хелпер для таблицы groups"""
    return DatabaseHelper("groups")

def orders_db() -> DatabaseHelper:
    """Хелпер для таблицы orders"""
    return DatabaseHelper("orders")

def payments_db() -> DatabaseHelper:
    """Хелпер для таблицы payments"""
    return DatabaseHelper("payments")


# ==================== ТЕСТИРОВАНИЕ ====================

if __name__ == "__main__":
    """
    Тест подключения при запуске файла напрямую.
    
    Запуск:
        python database/connection.py
    """
    import asyncio
    
    async def test():
        print("🔄 Проверка подключения к Supabase...")
        result = await check_connection()
        
        if result["connected"]:
            print("✅ " + result["message"])
        else:
            print("❌ " + result["message"])
            print("   Ошибка:", result["error"])
    
    asyncio.run(test())
