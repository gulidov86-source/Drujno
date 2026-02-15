"""
Модуль: routers/groups.py
Описание: API эндпоинты для работы с групповыми сборами
Проект: GroupBuy Mini App

Это ядро API — работа с групповыми закупками.

Эндпоинты:
    GET  /api/groups              — Список активных сборов
    GET  /api/groups/{id}         — Детали сбора
    POST /api/groups              — Создать сбор
    POST /api/groups/{id}/join    — Присоединиться к сбору
    POST /api/groups/{id}/leave   — Покинуть сбор
    GET  /api/groups/{id}/share   — Данные для шеринга
    POST /api/groups/{id}/cancel  — Отменить сбор
    GET  /api/groups/my           — Мои сборы

Использование:
    from routers.groups import router
    app.include_router(router)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

import sys
sys.path.append("..")
from database.connection import get_db
from database.models import (
    Group, GroupBrief, GroupStatus, GroupCreate, GroupJoin,
    Product, User, PriceTier
)
from services.group_manager import get_group_manager, JoinResult
from services.price_calculator import (
    calculate_current_price,
    get_best_price,
    get_full_price_info,
    get_tiers_progress,
    TierProgress
)
from utils.auth import get_current_user, get_current_user_optional
from utils.telegram import parse_start_param


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/groups",
    tags=["Групповые сборы"]
)


# ============================================================
# МОДЕЛИ ЗАПРОСОВ/ОТВЕТОВ
# ============================================================

class GroupListItem(BaseModel):
    """
    Сбор в списке (лента).
    """
    id: int
    status: GroupStatus
    current_count: int
    min_participants: int
    max_participants: int
    progress_percent: float
    deadline: datetime
    time_left: str
    
    # Цены
    current_price: Decimal
    best_price: Decimal
    base_price: Decimal
    savings_percent: float
    
    # Товар
    product_id: int
    product_name: str
    product_image: Optional[str] = None
    
    # Организатор
    creator_id: int
    creator_name: Optional[str] = None


class GroupListResponse(BaseModel):
    """Ответ со списком сборов."""
    items: List[GroupListItem]
    total: int
    page: int
    per_page: int


class GroupDetailResponse(BaseModel):
    """
    Детальная информация о сборе.
    """
    id: int
    status: GroupStatus
    current_count: int
    min_participants: int
    max_participants: int
    progress_percent: float
    deadline: datetime
    time_left: str
    created_at: datetime
    
    # Цены
    current_price: Decimal
    best_price: Decimal
    base_price: Decimal
    savings_amount: Decimal
    savings_percent: float
    
    # До следующего порога
    next_tier_price: Optional[Decimal] = None
    next_tier_quantity: Optional[int] = None
    people_to_next_tier: Optional[int] = None
    
    # Прогресс по порогам
    tiers_progress: List[TierProgress] = []
    
    # Товар
    product_id: int
    product_name: str
    product_description: Optional[str] = None
    product_image: Optional[str] = None
    product_images: List[str] = []
    price_tiers: List[PriceTier] = []
    
    # Организатор
    creator_id: int
    creator_name: Optional[str] = None
    creator_username: Optional[str] = None
    
    # Для текущего пользователя
    is_member: bool = False
    is_creator: bool = False
    user_invited_count: int = 0
    can_join: bool = True
    
    # Для шеринга
    share_text: Optional[str] = None
    share_url: Optional[str] = None


class CreateGroupRequest(BaseModel):
    """Запрос на создание сбора."""
    product_id: int = Field(..., description="ID товара")
    min_participants: Optional[int] = Field(None, ge=2, le=100, description="Минимум участников")
    max_participants: Optional[int] = Field(None, ge=2, le=500, description="Максимум участников")
    deadline_days: Optional[int] = Field(None, ge=1, le=30, description="Срок в днях")


class CreateGroupResponse(BaseModel):
    """Ответ при создании сбора."""
    success: bool
    group_id: Optional[int] = None
    message: str


class JoinGroupRequest(BaseModel):
    """Запрос на присоединение к сбору."""
    invited_by_user_id: Optional[int] = Field(None, description="ID пригласившего")
    start_param: Optional[str] = Field(None, description="Параметр из deep link")


class JoinGroupResponse(BaseModel):
    """Ответ при присоединении к сбору."""
    success: bool
    group_id: int
    current_count: int
    current_price: Decimal
    previous_price: Optional[Decimal] = None
    price_dropped: bool = False
    message: str


class ShareDataResponse(BaseModel):
    """Данные для шеринга сбора."""
    text: str
    url: str
    button_text: str


class MyGroupsResponse(BaseModel):
    """Мои сборы по категориям."""
    active: List[GroupListItem]
    completed: List[GroupListItem]
    organized: List[GroupListItem]


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def format_time_left(deadline) -> str:
    """Форматировать оставшееся время."""
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
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


def build_group_list_item(
    group_data: dict,
    product_data: dict,
    creator_data: Optional[dict] = None
) -> GroupListItem:
    """Построить элемент списка сборов."""
    price_tiers = product_data.get("price_tiers", [])
    base_price = Decimal(str(product_data.get("base_price", 0)))
    current_count = group_data.get("current_count", 0)
    max_participants = group_data.get("max_participants", 100)
    
    current_price = calculate_current_price(price_tiers, current_count, base_price)
    best_price = get_best_price(price_tiers) if price_tiers else base_price
    
    progress = (current_count / max_participants * 100) if max_participants > 0 else 0
    
    savings_percent = 0
    if base_price > 0:
        savings_percent = float((base_price - current_price) / base_price * 100)
    
    return GroupListItem(
        id=group_data["id"],
        status=GroupStatus(group_data.get("status", "active")),
        current_count=current_count,
        min_participants=group_data.get("min_participants", 3),
        max_participants=max_participants,
        progress_percent=round(progress, 1),
        deadline=group_data.get("deadline"),
        time_left=format_time_left(group_data.get("deadline")),
        current_price=current_price,
        best_price=best_price,
        base_price=base_price,
        savings_percent=round(savings_percent, 1),
        product_id=product_data.get("id", 0),
        product_name=product_data.get("name", ""),
        product_image=product_data.get("image_url"),
        creator_id=group_data.get("creator_id", 0),
        creator_name=creator_data.get("first_name") if creator_data else None
    )


# ============================================================
# ЭНДПОИНТЫ: СПИСОК СБОРОВ
# ============================================================

@router.get(
    "",
    response_model=GroupListResponse,
    summary="Список активных сборов",
    description="""
    Возвращает список активных групповых сборов.
    
    **Сортировка:**
    - `popular` — по количеству участников
    - `ending_soon` — скоро заканчиваются
    - `new` — недавно созданные
    - `almost_done` — близкие к завершению (>80%)
    
    **Фильтры:**
    - `category_id` — категория товара
    - `min_participants` — минимум участников
    """
)
async def get_groups(
    # Фильтры
    category_id: Optional[int] = Query(None, description="Категория товара"),
    status: str = Query("active", regex="^(active|completed|all)$", description="Статус сбора"),
    
    # Сортировка
    sort_by: str = Query(
        "popular",
        regex="^(popular|ending_soon|new|almost_done)$",
        description="Сортировка"
    ),
    
    # Пагинация
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    
    # Авторизация (опциональная)
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    """
    Получить список сборов.
    """
    db = get_db()
    
    # Базовый запрос
    query = db.table("groups").select(
        "*, products(id, name, image_url, base_price, price_tiers, category_id), "
        "users!groups_creator_id_fkey(id, first_name)",
        count="exact"
    )
    
    # Фильтр по статусу
    if status == "active":
        query = query.eq("status", "active")
    elif status == "completed":
        query = query.eq("status", "completed")
    # "all" — без фильтра
    
    # Сортировка
    if sort_by == "popular":
        query = query.order("current_count", desc=True)
    elif sort_by == "ending_soon":
        query = query.order("deadline", desc=False)
    elif sort_by == "new":
        query = query.order("created_at", desc=True)
    elif sort_by == "almost_done":
        query = query.order("current_count", desc=True)
    
    # Пагинация
    offset = (page - 1) * per_page
    query = query.range(offset, offset + per_page - 1)
    
    result = query.execute()
    
    # Фильтруем по категории (после запроса, т.к. это связанная таблица)
    items = []
    for group_data in (result.data or []):
        product_data = group_data.get("products", {})
        
        # Фильтр по категории
        if category_id and product_data.get("category_id") != category_id:
            continue
        
        creator_data = group_data.get("users", {})
        
        # Фильтр "almost_done" — только >80%
        if sort_by == "almost_done":
            max_p = group_data.get("max_participants", 100)
            current = group_data.get("current_count", 0)
            if max_p > 0 and (current / max_p) < 0.8:
                continue
        
        items.append(build_group_list_item(group_data, product_data, creator_data))
    
    return GroupListResponse(
        items=items,
        total=result.count or 0,
        page=page,
        per_page=per_page
    )


@router.get(
    "/hot",
    response_model=List[GroupListItem],
    summary="Горячие сборы",
    description="Сборы, которые скоро завершатся или близки к цели."
)
async def get_hot_groups(
    limit: int = Query(10, ge=1, le=50)
):
    """
    Получить горячие сборы.
    
    Критерии:
    - Прогресс > 70%
    - Или до дедлайна < 24 часа
    """
    db = get_db()
    
    # Получаем активные сборы
    result = (
        db.table("groups")
        .select("*, products(id, name, image_url, base_price, price_tiers)")
        .eq("status", "active")
        .order("current_count", desc=True)
        .limit(limit * 2)  # Берём с запасом для фильтрации
        .execute()
    )
    
    now = datetime.now(timezone.utc)
    hot_groups = []
    
    for group_data in (result.data or []):
        product_data = group_data.get("products", {})
        
        # Проверяем критерии "горячести"
        max_p = group_data.get("max_participants", 100)
        current = group_data.get("current_count", 0)
        progress = (current / max_p) if max_p > 0 else 0
        
        deadline = datetime.fromisoformat(
            group_data["deadline"].replace("Z", "+00:00")
        )
        hours_left = (deadline - now).total_seconds() / 3600
        
        # Горячий если прогресс > 70% или осталось < 24 часа
        is_hot = progress > 0.7 or (0 < hours_left < 24)
        
        if is_hot:
            hot_groups.append(build_group_list_item(group_data, product_data))
        
        if len(hot_groups) >= limit:
            break
    
    return hot_groups


# ============================================================
# ЭНДПОИНТЫ: ДЕТАЛИ СБОРА
# ============================================================

@router.get(
    "/{group_id}",
    response_model=GroupDetailResponse,
    summary="Детали сбора",
    description="Полная информация о групповом сборе."
)
async def get_group_detail(
    group_id: int,
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    """
    Получить детальную информацию о сборе.
    """
    db = get_db()
    
    # Получаем сбор с товаром и создателем
    result = (
        db.table("groups")
        .select(
            "*, "
            "products(id, name, description, image_url, images, base_price, price_tiers), "
            "users!groups_creator_id_fkey(id, first_name, username)"
        )
        .eq("id", group_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сбор не найден"
        )
    
    group_data = result.data[0]
    product_data = group_data.get("products", {})
    creator_data = group_data.get("users", {})
    
    # Рассчитываем цены
    price_tiers = product_data.get("price_tiers", [])
    base_price = Decimal(str(product_data.get("base_price", 0)))
    current_count = group_data.get("current_count", 0)
    max_participants = group_data.get("max_participants", 100)
    
    price_info = get_full_price_info(price_tiers, base_price, current_count)
    tiers_progress = get_tiers_progress(price_tiers, current_count)
    
    progress = (current_count / max_participants * 100) if max_participants > 0 else 0
    
    # Проверяем участие текущего пользователя
    is_member = False
    is_creator = False
    user_invited_count = 0
    can_join = group_data.get("status") == "active"
    
    if user_id:
        is_creator = group_data.get("creator_id") == user_id
        
        # Проверяем членство
        membership = (
            db.table("group_members")
            .select("id")
            .eq("group_id", group_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        is_member = bool(membership.data)
        
        if is_member:
            can_join = False
        
        # Считаем приглашённых
        invited = (
            db.table("group_members")
            .select("id", count="exact")
            .eq("group_id", group_id)
            .eq("invited_by_user_id", user_id)
            .execute()
        )
        user_invited_count = invited.count or 0
    
    # Формируем ценовые пороги
    price_tier_objects = [
        PriceTier(min_quantity=t["min_quantity"], price=Decimal(str(t["price"])))
        for t in price_tiers
    ]
    
    return GroupDetailResponse(
        id=group_data["id"],
        status=GroupStatus(group_data.get("status", "active")),
        current_count=current_count,
        min_participants=group_data.get("min_participants", 3),
        max_participants=max_participants,
        progress_percent=round(progress, 1),
        deadline=group_data.get("deadline"),
        time_left=format_time_left(group_data.get("deadline")),
        created_at=group_data.get("created_at"),
        
        current_price=price_info.current_price,
        best_price=price_info.best_price,
        base_price=price_info.base_price,
        savings_amount=price_info.savings_amount,
        savings_percent=price_info.savings_percent,
        
        next_tier_price=price_info.next_tier_price,
        next_tier_quantity=price_info.next_tier_quantity,
        people_to_next_tier=price_info.people_to_next_tier,
        
        tiers_progress=tiers_progress,
        
        product_id=product_data.get("id", 0),
        product_name=product_data.get("name", ""),
        product_description=product_data.get("description"),
        product_image=product_data.get("image_url"),
        product_images=product_data.get("images", []),
        price_tiers=price_tier_objects,
        
        creator_id=creator_data.get("id", 0),
        creator_name=creator_data.get("first_name"),
        creator_username=creator_data.get("username"),
        
        is_member=is_member,
        is_creator=is_creator,
        user_invited_count=user_invited_count,
        can_join=can_join
    )


# ============================================================
# ЭНДПОИНТЫ: СОЗДАНИЕ И УПРАВЛЕНИЕ
# ============================================================

@router.post(
    "",
    response_model=CreateGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать сбор",
    description="""
    Создать новый групповой сбор.
    
    **Требования:**
    - Авторизация
    - Товар должен быть активен
    - На товар не должно быть активного сбора
    """
)
async def create_group(
    request: CreateGroupRequest,
    user_id: int = Depends(get_current_user)
):
    """
    Создать новый сбор.
    """
    manager = get_group_manager()
    
    result = await manager.create_group(
        product_id=request.product_id,
        creator_id=user_id,
        min_participants=request.min_participants,
        max_participants=request.max_participants,
        deadline_days=request.deadline_days
    )
    
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message
        )
    
    return CreateGroupResponse(
        success=True,
        group_id=result.group_id,
        message=result.message
    )


@router.post(
    "/{group_id}/join",
    response_model=JoinGroupResponse,
    summary="Присоединиться к сбору",
    description="""
    Присоединиться к групповому сбору.
    
    **Параметры:**
    - `invited_by_user_id` — ID пригласившего (опционально)
    - `start_param` — параметр из deep link (парсится автоматически)
    """
)
async def join_group(
    group_id: int,
    request: JoinGroupRequest = JoinGroupRequest(),
    user_id: int = Depends(get_current_user)
):
    """
    Присоединиться к сбору.
    """
    # Парсим start_param если есть
    invited_by = request.invited_by_user_id
    
    if request.start_param and not invited_by:
        parsed = parse_start_param(request.start_param)
        invited_by = parsed.get("referrer_id")
    
    # Нельзя пригласить самого себя
    if invited_by == user_id:
        invited_by = None
    
    manager = get_group_manager()
    
    result = await manager.join_group(
        group_id=group_id,
        user_id=user_id,
        invited_by_user_id=invited_by
    )
    
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message
        )
    
    return JoinGroupResponse(
        success=True,
        group_id=result.group_id,
        current_count=result.current_count,
        current_price=result.current_price,
        previous_price=result.previous_price,
        price_dropped=result.price_dropped,
        message=result.message
    )


@router.post(
    "/{group_id}/leave",
    summary="Покинуть сбор",
    description="""
    Покинуть групповой сбор.
    
    **Ограничения:**
    - Нельзя покинуть завершённый сбор
    - Создатель не может покинуть свой сбор
    """
)
async def leave_group(
    group_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Покинуть сбор.
    """
    db = get_db()
    
    # Проверяем сбор
    group = (
        db.table("groups")
        .select("status, creator_id")
        .eq("id", group_id)
        .limit(1)
        .execute()
    )
    
    if not group.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сбор не найден"
        )
    
    group_data = group.data[0]
    
    if group_data["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя покинуть завершённый сбор"
        )
    
    if group_data["creator_id"] == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Создатель не может покинуть свой сбор. Используйте отмену."
        )
    
    # Проверяем членство
    membership = (
        db.table("group_members")
        .select("id")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    
    if not membership.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Вы не участвуете в этом сборе"
        )
    
    # Удаляем из участников
    db.table("group_members").delete().eq("group_id", group_id).eq("user_id", user_id).execute()
    
    # Счётчик обновится автоматически триггером
    
    return {"success": True, "message": "Вы покинули сбор"}


@router.post(
    "/{group_id}/cancel",
    summary="Отменить сбор",
    description="Отменить сбор. Доступно только создателю."
)
async def cancel_group(
    group_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Отменить сбор.
    """
    manager = get_group_manager()
    
    try:
        result = await manager.cancel_group(group_id, user_id)
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    
    return {
        "success": True,
        "old_status": result.old_status,
        "new_status": result.new_status,
        "message": "Сбор отменён"
    }


# ============================================================
# ЭНДПОИНТЫ: ШЕРИНГ
# ============================================================

@router.get(
    "/{group_id}/share",
    response_model=ShareDataResponse,
    summary="Данные для шеринга",
    description="Получить текст и ссылку для шеринга сбора."
)
async def get_share_data(
    group_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Получить данные для шеринга.
    """
    manager = get_group_manager()
    
    # TODO: Получить username бота из настроек
    bot_username = "GroupBuyTestBot"  # Заменить на реальный
    
    try:
        data = await manager.get_share_data(group_id, user_id, bot_username)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    
    return ShareDataResponse(**data)


# ============================================================
# ЭНДПОИНТЫ: МОИ СБОРЫ
# ============================================================

@router.get(
    "/my/all",
    response_model=MyGroupsResponse,
    summary="Мои сборы",
    description="Сборы, в которых я участвую или которые я создал."
)
async def get_my_groups(
    user_id: int = Depends(get_current_user)
):
    """
    Получить мои сборы.
    """
    db = get_db()
    
    # Сборы где я участник
    memberships = (
        db.table("group_members")
        .select("group_id")
        .eq("user_id", user_id)
        .execute()
    )
    
    group_ids = [m["group_id"] for m in (memberships.data or [])]
    
    active = []
    completed = []
    organized = []
    
    if group_ids:
        # Получаем эти сборы
        groups = (
            db.table("groups")
            .select("*, products(id, name, image_url, base_price, price_tiers)")
            .in_("id", group_ids)
            .execute()
        )
        
        for group_data in (groups.data or []):
            product_data = group_data.get("products", {})
            item = build_group_list_item(group_data, product_data)
            
            if group_data["status"] == "active":
                active.append(item)
            elif group_data["status"] == "completed":
                completed.append(item)
    
    # Сборы где я организатор
    my_groups = (
        db.table("groups")
        .select("*, products(id, name, image_url, base_price, price_tiers)")
        .eq("creator_id", user_id)
        .execute()
    )
    
    for group_data in (my_groups.data or []):
        product_data = group_data.get("products", {})
        item = build_group_list_item(group_data, product_data)
        organized.append(item)
    
    return MyGroupsResponse(
        active=active,
        completed=completed,
        organized=organized
    )


# ============================================================
# ЭНДПОИНТЫ: УЧАСТНИКИ
# ============================================================

@router.get(
    "/{group_id}/members",
    summary="Участники сбора",
    description="Список участников сбора."
)
async def get_group_members(
    group_id: int,
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    """
    Получить список участников.
    
    Показывает только имена и когда присоединились.
    """
    db = get_db()
    
    # Проверяем сбор
    group = (
        db.table("groups")
        .select("id")
        .eq("id", group_id)
        .limit(1)
        .execute()
    )
    
    if not group.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сбор не найден"
        )
    
    # Получаем участников
    members = (
        db.table("group_members")
        .select("user_id, joined_at, users(first_name, username)")
        .eq("group_id", group_id)
        .order("joined_at", desc=False)
        .execute()
    )
    
    result = []
    for member in (members.data or []):
        user_data = member.get("users", {})
        result.append({
            "user_id": member["user_id"],
            "first_name": user_data.get("first_name", "Участник"),
            "joined_at": member["joined_at"],
            "is_me": member["user_id"] == user_id if user_id else False
        })
    
    return {
        "group_id": group_id,
        "total": len(result),
        "members": result
    }
