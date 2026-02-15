"""
Модуль: routers/products.py
Описание: API эндпоинты для работы с товарами и каталогом
Проект: GroupBuy Mini App

Эндпоинты:
    GET  /api/products             — Список товаров с фильтрами
    GET  /api/products/{id}        — Детали товара
    GET  /api/categories           — Список категорий

Особенности:
    - Товары возвращаются с информацией об активных сборах
    - Цены рассчитываются динамически
    - Поддерживается поиск и фильтрация

Использование:
    from routers.products import router
    app.include_router(router)
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

import sys
sys.path.append("..")
from database.connection import get_db
from database.models import (
    Product, ProductWithActiveGroup, PriceTier,
    Category, GroupBrief, GroupStatus
)
from services.price_calculator import (
    calculate_current_price,
    get_best_price,
    get_full_price_info,
    get_tiers_progress,
    TierProgress
)
from utils.auth import get_current_user_optional


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/products",
    tags=["Товары"]
)


# ============================================================
# МОДЕЛИ ОТВЕТОВ
# ============================================================

class ProductListItem(BaseModel):
    """
    Товар в списке (лента).
    
    Облегчённая версия для отображения в каталоге.
    """
    id: int
    name: str
    image_url: Optional[str] = None
    base_price: Decimal
    best_price: Decimal  # Минимально возможная цена
    category_id: Optional[int] = None
    
    # Информация об активном сборе (если есть)
    active_group: Optional[GroupBrief] = None
    
    # Статистика
    total_sold: int = 0


class ProductListResponse(BaseModel):
    """Ответ со списком товаров."""
    items: List[ProductListItem]
    total: int
    page: int
    per_page: int
    pages: int


class ProductDetailResponse(BaseModel):
    """
    Детальная информация о товаре.
    
    Включает все данные для страницы товара.
    """
    id: int
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    images: List[str] = []
    base_price: Decimal
    best_price: Decimal
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    stock: int
    total_sold: int
    is_active: bool
    
    # Ценовые пороги
    price_tiers: List[PriceTier]
    
    # Активные сборы на этот товар
    active_groups: List[GroupBrief] = []
    
    # Прогресс по порогам (для визуализации)
    tiers_progress: Optional[List[TierProgress]] = None


class CategoryResponse(BaseModel):
    """Категория товаров."""
    id: int
    name: str
    slug: str
    icon: Optional[str] = None
    products_count: int = 0


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def format_time_left(deadline) -> str:
    """
    Форматировать оставшееся время.
    
    Возвращает строку вида "2д 14ч" или "3ч 25м".
    """
    from datetime import datetime, timezone
    
    if isinstance(deadline, str):
        # Парсим ISO строку
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    
    now = datetime.now(timezone.utc)
    
    if deadline.tzinfo is None:
        # Если нет таймзоны, считаем UTC
        from datetime import timezone
        deadline = deadline.replace(tzinfo=timezone.utc)
    
    diff = deadline - now
    
    if diff.total_seconds() <= 0:
        return "Завершён"
    
    total_seconds = int(diff.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    
    if days > 0:
        return f"{days}д {hours}ч"
    elif hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"


def build_group_brief(group_data: dict, price_tiers: list) -> GroupBrief:
    """
    Создать краткую информацию о сборе.
    """
    current_count = group_data.get("current_count", 0)
    max_participants = group_data.get("max_participants", 100)
    
    # Рассчитываем текущую цену
    current_price = calculate_current_price(
        price_tiers=price_tiers,
        participants_count=current_count
    )
    
    # Прогресс
    progress = (current_count / max_participants * 100) if max_participants > 0 else 0
    
    return GroupBrief(
        id=group_data["id"],
        status=GroupStatus(group_data.get("status", "active")),
        current_count=current_count,
        current_price=current_price,
        progress_percent=round(progress, 1),
        deadline=group_data.get("deadline"),
        time_left=format_time_left(group_data.get("deadline"))
    )


# ============================================================
# ЭНДПОИНТЫ: ТОВАРЫ
# ============================================================

@router.get(
    "",
    response_model=ProductListResponse,
    summary="Список товаров",
    description="""
    Возвращает список товаров с фильтрацией и пагинацией.
    
    **Фильтры:**
    - `category_id` — ID категории
    - `search` — поиск по названию
    - `min_price`, `max_price` — диапазон цен
    - `has_active_group` — только товары с активными сборами
    
    **Сортировка:**
    - `popular` — по популярности
    - `price_asc` — по цене (возрастание)
    - `price_desc` — по цене (убывание)
    - `new` — по дате добавления
    """
)
async def get_products(
    # Фильтры
    category_id: Optional[int] = Query(None, description="ID категории"),
    search: Optional[str] = Query(None, min_length=2, max_length=100, description="Поиск по названию"),
    min_price: Optional[int] = Query(None, ge=0, description="Минимальная цена"),
    max_price: Optional[int] = Query(None, ge=0, description="Максимальная цена"),
    has_active_group: Optional[bool] = Query(None, description="Только с активными сборами"),
    
    # Сортировка
    sort_by: str = Query("popular", regex="^(popular|price_asc|price_desc|new)$"),
    
    # Пагинация
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Товаров на странице"),
    
    # Опциональная авторизация
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    """
    Получить список товаров.
    
    Возвращает товары с информацией об активных сборах.
    """
    db = get_db()
    
    # Базовый запрос
    query = db.table("products").select("*", count="exact")
    
    # Только активные товары
    query = query.eq("is_active", True)
    
    # Фильтр по категории
    if category_id:
        query = query.eq("category_id", category_id)
    
    # Поиск по названию
    if search:
        query = query.ilike("name", f"%{search}%")
    
    # Фильтр по цене
    if min_price is not None:
        query = query.gte("base_price", min_price)
    if max_price is not None:
        query = query.lte("base_price", max_price)
    
    # Сортировка
    if sort_by == "popular":
        query = query.order("total_sold", desc=True)
    elif sort_by == "price_asc":
        query = query.order("base_price", desc=False)
    elif sort_by == "price_desc":
        query = query.order("base_price", desc=True)
    elif sort_by == "new":
        query = query.order("created_at", desc=True)
    
    # Пагинация
    offset = (page - 1) * per_page
    query = query.range(offset, offset + per_page - 1)
    
    # Выполняем запрос
    result = query.execute()
    
    total = result.count or 0
    pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    
    # Получаем активные сборы для этих товаров
    product_ids = [p["id"] for p in (result.data or [])]
    
    active_groups = {}
    if product_ids:
        groups_result = (
            db.table("groups")
            .select("*")
            .in_("product_id", product_ids)
            .eq("status", "active")
            .execute()
        )
        
        for group in (groups_result.data or []):
            product_id = group["product_id"]
            if product_id not in active_groups:
                active_groups[product_id] = group
    
    # Формируем ответ
    items = []
    for product in (result.data or []):
        price_tiers = product.get("price_tiers", [])
        best_price = get_best_price(price_tiers) if price_tiers else Decimal(str(product["base_price"]))
        
        # Информация об активном сборе
        active_group = None
        if product["id"] in active_groups:
            group_data = active_groups[product["id"]]
            active_group = build_group_brief(group_data, price_tiers)
        
        items.append(ProductListItem(
            id=product["id"],
            name=product["name"],
            image_url=product.get("image_url"),
            base_price=Decimal(str(product["base_price"])),
            best_price=best_price,
            category_id=product.get("category_id"),
            active_group=active_group,
            total_sold=product.get("total_sold", 0)
        ))
    
    # Фильтруем по наличию активного сбора (после запроса, т.к. это join)
    if has_active_group is True:
        items = [item for item in items if item.active_group is not None]
    elif has_active_group is False:
        items = [item for item in items if item.active_group is None]
    
    return ProductListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages
    )


@router.get(
    "/{product_id}",
    response_model=ProductDetailResponse,
    summary="Детали товара",
    description="""
    Возвращает полную информацию о товаре.
    
    Включает:
    - Описание и изображения
    - Ценовые пороги
    - Активные сборы
    - Прогресс по порогам (если есть активный сбор)
    """
)
async def get_product_detail(
    product_id: int,
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    """
    Получить детальную информацию о товаре.
    """
    db = get_db()
    
    # Получаем товар
    result = (
        db.table("products")
        .select("*")
        .eq("id", product_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не найден"
        )
    
    product = result.data[0]
    price_tiers = product.get("price_tiers", [])
    
    # Получаем категорию
    category_name = None
    if product.get("category_id"):
        cat_result = (
            db.table("categories")
            .select("name")
            .eq("id", product["category_id"])
            .limit(1)
            .execute()
        )
        if cat_result.data:
            category_name = cat_result.data[0]["name"]
    
    # Получаем активные сборы
    groups_result = (
        db.table("groups")
        .select("*")
        .eq("product_id", product_id)
        .eq("status", "active")
        .order("current_count", desc=True)
        .execute()
    )
    
    active_groups = []
    tiers_progress = None
    
    for group_data in (groups_result.data or []):
        active_groups.append(build_group_brief(group_data, price_tiers))
        
        # Для первого (самого популярного) сбора считаем прогресс по порогам
        if tiers_progress is None and price_tiers:
            tiers_progress = get_tiers_progress(
                price_tiers, 
                group_data.get("current_count", 0)
            )
    
    # Лучшая цена
    best_price = get_best_price(price_tiers) if price_tiers else Decimal(str(product["base_price"]))
    
    # Формируем ценовые пороги как объекты
    price_tier_objects = [
        PriceTier(min_quantity=t["min_quantity"], price=Decimal(str(t["price"])))
        for t in price_tiers
    ]
    
    return ProductDetailResponse(
        id=product["id"],
        name=product["name"],
        description=product.get("description"),
        image_url=product.get("image_url"),
        images=product.get("images", []),
        base_price=Decimal(str(product["base_price"])),
        best_price=best_price,
        category_id=product.get("category_id"),
        category_name=category_name,
        stock=product.get("stock", 0),
        total_sold=product.get("total_sold", 0),
        is_active=product.get("is_active", True),
        price_tiers=price_tier_objects,
        active_groups=active_groups,
        tiers_progress=tiers_progress
    )


# ============================================================
# ЭНДПОИНТЫ: КАТЕГОРИИ
# ============================================================

@router.get(
    "/categories/",  # Слеш в конце чтобы не конфликтовало с /{product_id}
    response_model=List[CategoryResponse],
    summary="Список категорий",
    description="Возвращает все активные категории товаров."
)
async def get_categories():
    """
    Получить список категорий.
    
    Категории отсортированы по sort_order.
    Включает количество товаров в каждой категории.
    """
    db = get_db()
    
    # Получаем категории
    result = (
        db.table("categories")
        .select("*")
        .eq("is_active", True)
        .order("sort_order")
        .execute()
    )
    
    categories = []
    
    for cat in (result.data or []):
        # Считаем товары в категории
        count_result = (
            db.table("products")
            .select("id", count="exact")
            .eq("category_id", cat["id"])
            .eq("is_active", True)
            .execute()
        )
        
        categories.append(CategoryResponse(
            id=cat["id"],
            name=cat["name"],
            slug=cat["slug"],
            icon=cat.get("icon"),
            products_count=count_result.count or 0
        ))
    
    return categories


# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ ЭНДПОИНТЫ
# ============================================================

@router.get(
    "/{product_id}/price",
    summary="Рассчитать цену",
    description="""
    Рассчитать цену товара при заданном количестве участников.
    
    Полезно для предпросмотра цены без создания сбора.
    """
)
async def calculate_product_price(
    product_id: int,
    participants: int = Query(..., ge=1, description="Количество участников")
):
    """
    Рассчитать цену товара.
    
    Параметры:
        product_id: ID товара
        participants: Количество участников
    
    Возвращает полную информацию о цене.
    """
    db = get_db()
    
    # Получаем товар
    result = (
        db.table("products")
        .select("base_price, price_tiers")
        .eq("id", product_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не найден"
        )
    
    product = result.data[0]
    price_tiers = product.get("price_tiers", [])
    base_price = Decimal(str(product["base_price"]))
    
    # Получаем полную информацию о цене
    price_info = get_full_price_info(price_tiers, base_price, participants)
    
    return {
        "product_id": product_id,
        "participants": participants,
        "current_price": float(price_info.current_price),
        "base_price": float(price_info.base_price),
        "best_price": float(price_info.best_price),
        "savings_amount": float(price_info.savings_amount),
        "savings_percent": price_info.savings_percent,
        "next_tier": {
            "price": float(price_info.next_tier_price) if price_info.next_tier_price else None,
            "quantity": price_info.next_tier_quantity,
            "people_needed": price_info.people_to_next_tier
        } if price_info.next_tier_price else None
    }


@router.get(
    "/popular/",  # Слеш чтобы не конфликтовало
    response_model=List[ProductListItem],
    summary="Популярные товары",
    description="Возвращает топ популярных товаров."
)
async def get_popular_products(
    limit: int = Query(10, ge=1, le=50, description="Количество товаров")
):
    """
    Получить популярные товары.
    
    Сортировка по количеству продаж.
    """
    db = get_db()
    
    result = (
        db.table("products")
        .select("*")
        .eq("is_active", True)
        .order("total_sold", desc=True)
        .limit(limit)
        .execute()
    )
    
    # Получаем активные сборы
    product_ids = [p["id"] for p in (result.data or [])]
    
    active_groups = {}
    if product_ids:
        groups_result = (
            db.table("groups")
            .select("*")
            .in_("product_id", product_ids)
            .eq("status", "active")
            .execute()
        )
        
        for group in (groups_result.data or []):
            product_id = group["product_id"]
            if product_id not in active_groups:
                active_groups[product_id] = group
    
    items = []
    for product in (result.data or []):
        price_tiers = product.get("price_tiers", [])
        best_price = get_best_price(price_tiers) if price_tiers else Decimal(str(product["base_price"]))
        
        active_group = None
        if product["id"] in active_groups:
            group_data = active_groups[product["id"]]
            active_group = build_group_brief(group_data, price_tiers)
        
        items.append(ProductListItem(
            id=product["id"],
            name=product["name"],
            image_url=product.get("image_url"),
            base_price=Decimal(str(product["base_price"])),
            best_price=best_price,
            category_id=product.get("category_id"),
            active_group=active_group,
            total_sold=product.get("total_sold", 0)
        ))
    
    return items
