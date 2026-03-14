"""
Модуль: utils/async_db.py
Описание: Асинхронная обёртка для синхронного supabase-py клиента
Проект: GroupBuy Mini App

ПРОБЛЕМА:
    supabase-py использует httpx СИНХРОННО. Каждый вызов .execute()
    блокирует event loop FastAPI — все остальные запросы ждут.

    Аналогия: Представь кассу в магазине. Когда кассиру надо уточнить
    цену товара, он БРОСАЕТ кассу и идёт на склад. Очередь стоит.
    
    Правильно: кассир звонит на склад (async) и пока ждёт ответ —
    обслуживает следующего в очереди.

РЕШЕНИЕ:
    asyncio.to_thread() запускает синхронный вызов в отдельном потоке,
    а event loop продолжает обрабатывать другие запросы.

ИСПОЛЬЗОВАНИЕ:
    from utils.async_db import async_query, async_execute

    # Было (блокирует):
    result = db.table("users").select("*").eq("id", 1).execute()

    # Стало (не блокирует):
    result = await async_execute(
        db.table("users").select("*").eq("id", 1)
    )

    # Или одной строкой через хелпер:
    result = await async_query("users", lambda q: q.select("*").eq("id", 1))
"""

import asyncio
from typing import Callable, Any, Optional
from database.connection import get_db


async def async_execute(query_builder) -> Any:
    """
    Выполнить готовый запрос Supabase асинхронно.
    
    Параметры:
        query_builder: Объект запроса Supabase (до вызова .execute())
    
    Возвращает:
        Результат .execute()
    
    Пример:
        db = get_db()
        query = db.table("products").select("*").eq("is_active", True)
        result = await async_execute(query)
        products = result.data
        
    Наглядно:
        Обычный .execute() — как заблокировать дорогу шлагбаумом на 200мс.
        async_execute() — как открыть параллельную полосу: основная дорога свободна.
    """
    return await asyncio.to_thread(query_builder.execute)


async def async_query(table: str, builder_fn: Callable, count: str = None) -> Any:
    """
    Построить и выполнить запрос одной строкой.
    
    Параметры:
        table: Имя таблицы
        builder_fn: Функция, которая принимает query и возвращает построенный запрос
        count: Режим подсчёта ("exact", "planned", "estimated") или None
    
    Возвращает:
        Результат запроса
    
    Пример:
        # Получить активные товары с подсчётом
        result = await async_query(
            "products",
            lambda q: q.select("*").eq("is_active", True).order("total_sold", desc=True).limit(10),
            count="exact"
        )
        
        # Вставить запись
        result = await async_query(
            "users",
            lambda q: q.insert({"telegram_id": 123, "first_name": "Иван"})
        )
    
    Наглядно:
        async_query("users", lambda q: q.select("*").eq("id", 5))
        
        Это как сказать официанту: «Принеси из кухни (table=users) 
        блюдо номер 5 (eq id=5), а я пока посижу и не буду мешать 
        другим посетителям (async)».
    """
    db = get_db()
    
    if count:
        base = db.table(table).select("*", count=count)
    else:
        base = db.table(table)
    
    query = builder_fn(base)
    return await asyncio.to_thread(query.execute)


async def async_insert(table: str, data: dict) -> Any:
    """
    Вставить запись асинхронно.
    
    Пример:
        result = await async_insert("users", {
            "telegram_id": 123,
            "first_name": "Иван"
        })
        new_user = result.data[0]
    """
    db = get_db()
    return await asyncio.to_thread(
        db.table(table).insert(data).execute
    )


async def async_update(table: str, data: dict, match: dict) -> Any:
    """
    Обновить записи асинхронно.
    
    Параметры:
        table: Имя таблицы
        data: Данные для обновления
        match: Условия поиска {поле: значение}
    
    Пример:
        # Обновить имя пользователя с id=42
        result = await async_update(
            "users",
            {"first_name": "Пётр"},
            {"id": 42}
        )
    """
    db = get_db()
    query = db.table(table).update(data)
    for field, value in match.items():
        query = query.eq(field, value)
    return await asyncio.to_thread(query.execute)


async def async_select(
    table: str,
    columns: str = "*",
    match: dict = None,
    order_by: str = None,
    desc: bool = True,
    limit: int = None,
    offset: int = None,
    count: str = None,
) -> Any:
    """
    Универсальный SELECT-запрос.
    
    Параметры:
        table: Имя таблицы
        columns: Колонки ("*", "id, name", "*, products(id, name)")
        match: Фильтры {поле: значение}
        order_by: Поле для сортировки
        desc: True = убывание, False = возрастание
        limit: Лимит записей
        offset: Смещение (для пагинации)
        count: Режим подсчёта ("exact" и т.д.)
    
    Пример:
        # Получить 10 популярных активных товаров
        result = await async_select(
            "products",
            columns="id, name, base_price, image_url",
            match={"is_active": True},
            order_by="total_sold",
            desc=True,
            limit=10
        )
        products = result.data
    
    Наглядно:
        Это как заказ в ресторане:
        table = "меню"        → какой раздел
        columns = "название, цена" → что хочу видеть
        match = {"тип": "десерт"} → только десерты
        order_by = "рейтинг"      → от лучшего к худшему
        limit = 5                  → только топ-5
    """
    db = get_db()
    
    if count:
        query = db.table(table).select(columns, count=count)
    else:
        query = db.table(table).select(columns)
    
    if match:
        for field, value in match.items():
            query = query.eq(field, value)
    
    if order_by:
        query = query.order(order_by, desc=desc)
    
    if limit is not None and offset is not None:
        query = query.range(offset, offset + limit - 1)
    elif limit is not None:
        query = query.limit(limit)
    
    return await asyncio.to_thread(query.execute)
