"""
Модуль: utils/server_cache.py
Описание: Серверный кеш для часто запрашиваемых публичных данных
Проект: GroupBuy Mini App

ПРОБЛЕМА:
    Каждый пользователь, открывая главную, запрашивает одни и те же данные:
    горячие сборы, популярные товары, категории. Если 10 юзеров одновременно 
    зашли на главную — это 10 одинаковых запросов в Supabase.

    Аналогия: Представь школу. 30 учеников по очереди звонят в справочную,
    чтобы узнать расписание на завтра. Расписание у всех одинаковое!
    Проще один раз повесить на стенд (кеш) и все читают оттуда.

РЕШЕНИЕ:
    In-memory кеш с TTL (временем жизни). Первый запрос идёт в БД,
    результат сохраняется. Следующие N секунд — отдаём из памяти мгновенно.

ИСПОЛЬЗОВАНИЕ:
    from utils.server_cache import server_cache

    # В эндпоинте:
    cached = server_cache.get("hot_groups")
    if cached is not None:
        return cached
    
    # ... запрос в БД ...
    
    server_cache.set("hot_groups", result, ttl=15)
    return result

    # Или декоратор:
    @server_cache.cached("popular_products:{limit}", ttl=60)
    async def get_popular(limit: int):
        ...  # запрос в БД

    # Сбросить кеш после мутации:
    server_cache.invalidate("hot_groups")
    server_cache.invalidate_prefix("groups:")  # все ключи, начинающиеся с "groups:"
"""

import time
import asyncio
import functools
from typing import Any, Optional, Callable
from logger import get_logger

logger = get_logger("server_cache")


class ServerCache:
    """
    Простой in-memory кеш с TTL.
    
    Аналогия: блокнот официанта с пометкой «актуально до 14:05».
    Если сейчас 14:03 — читаем из блокнота (мгновенно).
    Если 14:06 — идём на кухню (запрос в БД) и обновляем блокнот.
    
    Пример:
        cache = ServerCache()
        
        # Сохранить на 30 секунд
        cache.set("hot_groups", groups_list, ttl=30)
        
        # Получить (None если протухло)
        result = cache.get("hot_groups")
        
        # Сбросить
        cache.invalidate("hot_groups")
    """
    
    def __init__(self):
        # Формат: {key: {"data": ..., "expires": timestamp}}
        self._store: dict = {}
        # Счётчики для мониторинга
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        Получить значение из кеша.
        
        Возвращает None если ключа нет или он протух.
        
        Наглядно:
            cache.get("menu") 
            → Есть и свежее? Вот, держи (мгновенно)
            → Нет или протухло? None (иди в БД)
        """
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        
        if time.time() > entry["expires"]:
            # Протухло — удаляем
            del self._store[key]
            self._misses += 1
            return None
        
        self._hits += 1
        return entry["data"]
    
    def set(self, key: str, data: Any, ttl: int = 30) -> None:
        """
        Сохранить значение в кеш.
        
        Параметры:
            key: Ключ
            data: Данные (любой тип)
            ttl: Время жизни в секундах
        
        Наглядно:
            cache.set("hot_groups", groups, ttl=15)
            → Записали в блокнот, пометили «актуально 15 секунд»
        """
        self._store[key] = {
            "data": data,
            "expires": time.time() + ttl,
        }
    
    def invalidate(self, key: str) -> None:
        """
        Удалить конкретный ключ из кеша.
        
        Вызывать после мутаций (создание сбора, вступление и т.д.)
        """
        self._store.pop(key, None)
    
    def invalidate_prefix(self, prefix: str) -> None:
        """
        Удалить все ключи, начинающиеся с prefix.
        
        Пример:
            cache.invalidate_prefix("groups:")
            → Удалит "groups:hot", "groups:list:1", "groups:detail:42" и т.д.
        
        Наглядно:
            Как вырвать из блокнота все страницы раздела «Сборы».
        """
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
    
    def invalidate_all(self) -> None:
        """Полностью очистить кеш."""
        self._store.clear()
    
    def stats(self) -> dict:
        """
        Статистика кеша для мониторинга.
        
        Возвращает:
            {
                "size": 12,       — сколько записей
                "hits": 150,      — сколько раз ответили из кеша
                "misses": 45,     — сколько раз пошли в БД
                "hit_rate": 0.77  — процент попаданий (чем выше — тем лучше)
            }
        """
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 2) if total > 0 else 0,
        }
    
    def cleanup(self) -> int:
        """
        Удалить все протухшие записи.
        
        Можно вызывать периодически (например, из scheduler).
        Возвращает количество удалённых записей.
        """
        now = time.time()
        expired_keys = [k for k, v in self._store.items() if now > v["expires"]]
        for k in expired_keys:
            del self._store[k]
        return len(expired_keys)

    def cached(self, key_template: str, ttl: int = 30):
        """
        Декоратор для автоматического кеширования результатов функции.
        
        Параметры:
            key_template: Шаблон ключа с подстановкой аргументов
                          Пример: "products:popular:{limit}"
            ttl: Время жизни в секундах
        
        Пример:
            @server_cache.cached("products:popular:{limit}", ttl=60)
            async def get_popular_products(limit: int = 10):
                db = get_db()
                result = db.table("products")...
                return result
            
            # Первый вызов → БД → сохранит в кеш
            # Второй вызов (< 60 сек) → мгновенно из кеша
            # Через 60 сек → снова в БД
        
        Наглядно:
            Как «умная заметка», которая:
            1. Первый раз — идёт узнавать и записывает
            2. Потом N секунд — отвечает по памяти
            3. Через N секунд — снова идёт узнавать
        """
        def decorator(func: Callable):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Формируем ключ, подставляя аргументы
                # Для "products:popular:{limit}" + limit=10 → "products:popular:10"
                try:
                    cache_key = key_template.format(**kwargs)
                except (KeyError, IndexError):
                    # Если шаблон не совпадает с kwargs — вызываем без кеша
                    return await func(*args, **kwargs)
                
                # Проверяем кеш
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # Вызываем функцию
                result = await func(*args, **kwargs)
                
                # Сохраняем в кеш
                self.set(cache_key, result, ttl=ttl)
                
                return result
            return wrapper
        return decorator


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
# Один на всё приложение, как глобальный блокнот официанта

server_cache = ServerCache()


# ============================================================
# TTL-КОНСТАНТЫ (удобно настраивать в одном месте)
# ============================================================
# Аналогия: «срок годности» для разных типов данных.
# Категории — как консервы, долго не портятся.
# Горячие сборы — как суши, быстро устаревают.

CACHE_TTL_CATEGORIES = 300     # 5 мин — категории меняются очень редко
CACHE_TTL_POPULAR = 60         # 1 мин — популярные товары обновляются нечасто
CACHE_TTL_HOT_GROUPS = 15      # 15 сек — горячие сборы меняются при вступлении
CACHE_TTL_PRODUCT_LIST = 60    # 1 мин — каталог
CACHE_TTL_PRODUCT_DETAIL = 30  # 30 сек — детали товара
