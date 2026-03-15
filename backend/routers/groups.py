"""
Модуль: routers/groups.py
Описание: API эндпоинты для работы с групповыми сборами
Проект: GroupBuy Mini App

Это ядро API — работа с групповыми закупками.

ОБНОВЛЕНО: Добавлена интеграция с системой уведомлений (Фаза 8).
ОБНОВЛЕНО: Добавлен Rate Limiting на создание сборов (Спринт 1).
ОБНОВЛЕНО: Пересчёт цены при выходе участника (Спринт 2).

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

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request, status
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
from rate_limiter import limiter, create_limit
# === ОПТИМИЗАЦИЯ ===
from utils.async_db import async_execute
from utils.server_cache import server_cache, CACHE_TTL_HOT_GROUPS


# ============================================================
# ИМПОРТ УВЕДОМЛЕНИЙ
# ============================================================

try:
    from services.notification_integration import notify_on_join
    NOTIFICATIONS_ENABLED = True
    print("✅ Уведомления включены")
except ImportError:
    NOTIFICATIONS_ENABLED = False
    print("⚠️ Уведомления недоступны (notification_integration не найден)")


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
    id: int
    status: GroupStatus
    current_count: int
    min_participants: int
    max_participants: int
    progress_percent: float
    deadline: datetime
    time_left: str
    current_price: Decimal
    best_price: Decimal
    base_price: Decimal
    savings_percent: float
    product_id: int
    product_name: str
    product_image: Optional[str] = None
    creator_id: int
    creator_name: Optional[str] = None


class GroupListResponse(BaseModel):
    items: List[GroupListItem]
    total: int
    page: int
    per_page: int


class GroupDetailResponse(BaseModel):
    id: int
    status: GroupStatus
    current_count: int
    min_participants: int
    max_participants: int
    progress_percent: float
    deadline: datetime
    time_left: str
    created_at: datetime
    current_price: Decimal
    best_price: Decimal
    base_price: Decimal
    savings_amount: Decimal
    savings_percent: float
    next_tier_price: Optional[Decimal] = None
    next_tier_quantity: Optional[int] = None
    people_to_next_tier: Optional[int] = None
    tiers_progress: List[TierProgress] = []
    product_id: int
    product_name: str
    product_description: Optional[str] = None
    product_image: Optional[str] = None
    product_images: List[str] = []
    price_tiers: List[PriceTier] = []
    creator_id: int
    creator_name: Optional[str] = None
    creator_username: Optional[str] = None
    is_member: bool = False
    is_creator: bool = False
    user_invited_count: int = 0
    can_join: bool = True
    share_text: Optional[str] = None
    share_url: Optional[str] = None


class CreateGroupRequest(BaseModel):
    product_id: int = Field(..., description="ID товара")
    min_participants: Optional[int] = Field(None, ge=2, le=100, description="Минимум участников")
    max_participants: Optional[int] = Field(None, ge=2, le=500, description="Максимум участников")
    deadline_days: Optional[int] = Field(None, ge=1, le=30, description="Срок в днях")


class CreateGroupResponse(BaseModel):
    success: bool
    group_id: Optional[int] = None
    message: str


class JoinGroupRequest(BaseModel):
    invited_by_user_id: Optional[int] = Field(None, description="ID пригласившего")
    start_param: Optional[str] = Field(None, description="Параметр из deep link")


class JoinGroupResponse(BaseModel):
    success: bool
    group_id: int
    current_count: int
    current_price: Decimal
    previous_price: Optional[Decimal] = None
    price_dropped: bool = False
    message: str


class ShareDataResponse(BaseModel):
    text: str
    url: str
    button_text: str


class MyGroupsResponse(BaseModel):
    active: List[GroupListItem]
    completed: List[GroupListItem]
    organized: List[GroupListItem]


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def format_time_left(deadline) -> str:
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


def build_group_list_item(group_data, product_data, creator_data=None):
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

@router.get("", response_model=GroupListResponse, summary="Список активных сборов")
async def get_groups(
    category_id: Optional[int] = Query(None, description="Категория товара"),
    product_id: Optional[int] = Query(None, description="ID товара"),
    status: str = Query("active", pattern="^(active|completed|all)$", description="Статус сбора"),
    sort_by: str = Query("popular", pattern="^(popular|ending_soon|new|almost_done)$", description="Сортировка"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    db = get_db()
    query = db.table("groups").select(
        "*, products(id, name, image_url, base_price, price_tiers, category_id), "
        "users!groups_creator_id_fkey(id, first_name)",
        count="exact"
    )
    if status == "active":
        query = query.eq("status", "active")
    elif status == "completed":
        query = query.eq("status", "completed")
    if product_id:
        query = query.eq("product_id", product_id)
    if sort_by == "popular":
        query = query.order("current_count", desc=True)
    elif sort_by == "ending_soon":
        query = query.order("deadline", desc=False)
    elif sort_by == "new":
        query = query.order("created_at", desc=True)
    elif sort_by == "almost_done":
        query = query.order("current_count", desc=True)
    offset = (page - 1) * per_page
    query = query.range(offset, offset + per_page - 1)
    result = await async_execute(query)
    items = []
    for group_data in (result.data or []):
        product_data = group_data.get("products", {})
        if category_id and product_data.get("category_id") != category_id:
            continue
        creator_data = group_data.get("users", {})
        if sort_by == "almost_done":
            max_p = group_data.get("max_participants", 100)
            current = group_data.get("current_count", 0)
            if max_p > 0 and (current / max_p) < 0.8:
                continue
        items.append(build_group_list_item(group_data, product_data, creator_data))
    return GroupListResponse(items=items, total=result.count or 0, page=page, per_page=per_page)


@router.get("/hot", response_model=List[GroupListItem], summary="Горячие сборы")
async def get_hot_groups(limit: int = Query(10, ge=1, le=50)):
    # --- Серверный кеш (15 сек) ---
    cache_key = f"groups:hot:{limit}"
    cached = server_cache.get(cache_key)
    if cached is not None:
        return cached
    
    db = get_db()
    result = await async_execute(
        db.table("groups")
        .select("*, products(id, name, image_url, base_price, price_tiers)")
        .eq("status", "active")
        .order("current_count", desc=True)
        .limit(limit * 2)
    )
    
    now = datetime.now(timezone.utc)
    hot_groups = []
    for group_data in (result.data or []):
        product_data = group_data.get("products", {})
        max_p = group_data.get("max_participants", 100)
        current = group_data.get("current_count", 0)
        progress = (current / max_p) if max_p > 0 else 0
        deadline = datetime.fromisoformat(group_data["deadline"].replace("Z", "+00:00"))
        hours_left = (deadline - now).total_seconds() / 3600
        is_hot = progress > 0.7 or (0 < hours_left < 24)
        if is_hot:
            hot_groups.append(build_group_list_item(group_data, product_data))
        if len(hot_groups) >= limit:
            break
    
    # --- Сохраняем в кеш ---
    server_cache.set(cache_key, hot_groups, ttl=CACHE_TTL_HOT_GROUPS)
    
    return hot_groups


# ============================================================
# ЭНДПОИНТЫ: ДЕТАЛИ СБОРА
# ============================================================

@router.get("/{group_id}", response_model=GroupDetailResponse, summary="Детали сбора")
async def get_group_detail(
    group_id: int,
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    db = get_db()
    result = await async_execute(
        db.table("groups")
        .select(
            "*, "
            "products(id, name, description, image_url, images, base_price, price_tiers), "
            "users!groups_creator_id_fkey(id, first_name, username)"
        )
        .eq("id", group_id)
        .limit(1)
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сбор не найден")

    group_data = result.data[0]
    product_data = group_data.get("products", {})
    creator_data = group_data.get("users", {})
    price_tiers = product_data.get("price_tiers", [])
    base_price = Decimal(str(product_data.get("base_price", 0)))
    current_count = group_data.get("current_count", 0)
    max_participants = group_data.get("max_participants", 100)
    price_info = get_full_price_info(price_tiers, base_price, current_count)
    tiers_progress = get_tiers_progress(price_tiers, current_count)
    progress = (current_count / max_participants * 100) if max_participants > 0 else 0

    is_member = False
    is_creator = False
    user_invited_count = 0
    can_join = group_data.get("status") == "active"
    if user_id:
        is_creator = group_data.get("creator_id") == user_id
        membership = await async_execute(
            db.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).limit(1)
        )
        is_member = bool(membership.data)
        if is_member:
            can_join = False
        invited = await async_execute(
            db.table("group_members").select("id", count="exact").eq("group_id", group_id).eq("invited_by_user_id", user_id)
        )
        user_invited_count = invited.count or 0

    price_tier_objects = [PriceTier(min_quantity=t["min_quantity"], price=Decimal(str(t["price"]))) for t in price_tiers]

    return GroupDetailResponse(
        id=group_data["id"], status=GroupStatus(group_data.get("status", "active")),
        current_count=current_count, min_participants=group_data.get("min_participants", 3),
        max_participants=max_participants, progress_percent=round(progress, 1),
        deadline=group_data.get("deadline"), time_left=format_time_left(group_data.get("deadline")),
        created_at=group_data.get("created_at"),
        current_price=price_info.current_price, best_price=price_info.best_price,
        base_price=price_info.base_price, savings_amount=price_info.savings_amount,
        savings_percent=price_info.savings_percent,
        next_tier_price=price_info.next_tier_price, next_tier_quantity=price_info.next_tier_quantity,
        people_to_next_tier=price_info.people_to_next_tier, tiers_progress=tiers_progress,
        product_id=product_data.get("id", 0), product_name=product_data.get("name", ""),
        product_description=product_data.get("description"), product_image=product_data.get("image_url"),
        product_images=product_data.get("images", []), price_tiers=price_tier_objects,
        creator_id=creator_data.get("id", 0), creator_name=creator_data.get("first_name"),
        creator_username=creator_data.get("username"),
        is_member=is_member, is_creator=is_creator,
        user_invited_count=user_invited_count, can_join=can_join
    )


# ============================================================
# ЭНДПОИНТЫ: СОЗДАНИЕ И УПРАВЛЕНИЕ
# ============================================================

@router.post(
    "",
    response_model=CreateGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать сбор",
)
@limiter.limit(create_limit)
async def create_group(
    request: Request,
    body: CreateGroupRequest,
    user_id: int = Depends(get_current_user)
):
    manager = get_group_manager()
    result = await manager.create_group(
        product_id=body.product_id, creator_id=user_id,
        min_participants=body.min_participants, max_participants=body.max_participants,
        deadline_days=body.deadline_days
    )
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
    server_cache.invalidate_prefix("groups:")    
    return CreateGroupResponse(success=True, group_id=result.group_id, message=result.message)


@router.post("/{group_id}/join", response_model=JoinGroupResponse, summary="Присоединиться к сбору")
async def join_group(
    group_id: int,
    background_tasks: BackgroundTasks,
    join_request: JoinGroupRequest = JoinGroupRequest(),
    user_id: int = Depends(get_current_user)
):
    invited_by = join_request.invited_by_user_id
    if join_request.start_param and not invited_by:
        parsed = parse_start_param(join_request.start_param)
        invited_by = parsed.get("referrer_id")
    if invited_by == user_id:
        invited_by = None

    manager = get_group_manager()
    result = await manager.join_group(group_id=group_id, user_id=user_id, invited_by_user_id=invited_by)
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)

    if NOTIFICATIONS_ENABLED:
        background_tasks.add_task(notify_on_join, group_id=group_id, new_member_id=user_id, invited_by_id=invited_by)
    # Инвалидируем кеш сборов (участник вступил — данные устарели)
    server_cache.invalidate_prefix("groups:")
    return JoinGroupResponse(
        success=True, group_id=result.group_id, current_count=result.current_count,
        current_price=result.current_price, previous_price=result.previous_price,
        price_dropped=result.price_dropped, message=result.message
    )


# ============================================================
# ВЫХОД ИЗ СБОРА (Спринт 2 — пересчёт цены)
# ============================================================

@router.post(
    "/{group_id}/leave",
    summary="Покинуть сбор",
    description="""
    Покинуть групповой сбор.
    
    **Ограничения:**
    - Нельзя покинуть завершённый сбор
    - Создатель не может покинуть свой сбор
    
    **При выходе (Спринт 2):**
    - Цена пересчитывается для всех оставшихся участников
    - Если цена выросла — информация возвращается в ответе
    """
)
async def leave_group(
    group_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Покинуть сбор с пересчётом цены.
    
    Аналогия: вас было 10 человек и пицца стоила 100₽ каждому.
    Один ушёл → осталось 9 → теперь 111₽ каждому. Честно предупредить!
    """
    db = get_db()
    
    # Получаем сбор С ТОВАРОМ (нужно для пересчёта цены)
    group = await async_execute(
        db.table("groups")
        .select("status, creator_id, current_count, min_participants, "
                "product_id, products(base_price, price_tiers)")
        .eq("id", group_id)
        .limit(1)
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
    membership = await async_execute(
        db.table("group_members")
        .select("id")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .limit(1)
    )
    
    if not membership.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Вы не участвуете в этом сборе"
        )
    
    # ============================================================
    # ПЕРЕСЧЁТ ЦЕНЫ (Спринт 2)
    # ============================================================
    # Аналогия: 10 человек скидывались по 100₽. Один ушёл →
    # 9 человек → теперь по 111₽. Считаем разницу и предупреждаем.
    
    product_data = group_data.get("products", {})
    price_tiers = product_data.get("price_tiers", [])
    base_price = Decimal(str(product_data.get("base_price", 0)))
    old_count = group_data["current_count"]
    
    # Цена ДО выхода
    old_price = calculate_current_price(price_tiers, old_count, base_price)
    
    # Удаляем из участников
    dawait async_execute(db.table("group_members").delete().eq("group_id", group_id).eq("user_id", user_id))
    
    # Обновляем счётчик вручную (для надёжности, не полагаемся только на триггер)
    new_count = max(0, old_count - 1)
    await async_execute(db.table("groups").update({
        "current_count": new_count
    }).eq("id", group_id))
    
    # Цена ПОСЛЕ выхода
    new_price = calculate_current_price(price_tiers, new_count, base_price)
    price_increased = new_price > old_price
    
    # Формируем ответ
    result = {
        "success": True,
        "message": "Вы покинули сбор",
        "participants_left": new_count,
    }
    
    if price_increased:
        result["price_changed"] = True
        result["old_price"] = float(old_price)
        result["new_price"] = float(new_price)
        result["message"] = (
            f"Вы покинули сбор. Цена для остальных участников "
            f"выросла с {int(old_price):,}₽ до {int(new_price):,}₽".replace(",", " ")
        )
    # Инвалидируем кеш сборов (участник вступил — данные устарели)
    server_cache.invalidate_prefix("groups:")
    return result


@router.post("/{group_id}/cancel", summary="Отменить сбор")
async def cancel_group(
    group_id: int,
    user_id: int = Depends(get_current_user)
):
    manager = get_group_manager()
    try:
        result = await manager.cancel_group(group_id, user_id)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"success": True, "old_status": result.old_status, "new_status": result.new_status, "message": "Сбор отменён"}


# ============================================================
# ШЕРИНГ
# ============================================================

@router.get("/{group_id}/share", response_model=ShareDataResponse, summary="Данные для шеринга")
async def get_share_data(
    group_id: int,
    user_id: int = Depends(get_current_user)
):
    manager = get_group_manager()
    bot_username = "drujno_bot"
    try:
        data = await manager.get_share_data(group_id, user_id, bot_username)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return ShareDataResponse(**data)


# ============================================================
# МОИ СБОРЫ
# ============================================================

@router.get("/my/all", response_model=MyGroupsResponse, summary="Мои сборы")
async def get_my_groups(user_id: int = Depends(get_current_user)):
    db = get_db()
    memberships = await async_execute(db.table("group_members").select("group_id").eq("user_id", user_id))
    group_ids = [m["group_id"] for m in (memberships.data or [])]
    active = []
    completed = []
    organized = []
    if group_ids:
        groups = await async_execute(db.table("groups").select("*, products(id, name, image_url, base_price, price_tiers)").in_("id", group_ids))
        for group_data in (groups.data or []):
            product_data = group_data.get("products", {})
            item = build_group_list_item(group_data, product_data)
            if group_data["status"] == "active":
                active.append(item)
            elif group_data["status"] == "completed":
                completed.append(item)
    my_groups = await async_execute(db.table("groups").select("*, products(id, name, image_url, base_price, price_tiers)").eq("creator_id", user_id))
    for group_data in (my_groups.data or []):
        product_data = group_data.get("products", {})
        item = build_group_list_item(group_data, product_data)
        organized.append(item)
    return MyGroupsResponse(active=active, completed=completed, organized=organized)


# ============================================================
# УЧАСТНИКИ
# ============================================================

@router.get("/{group_id}/members", summary="Участники сбора")
async def get_group_members(
    group_id: int,
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    db = get_db()
    group = await async_execute(db.table("groups").select("id").eq("id", group_id).limit(1))
    if not group.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сбор не найден")
    members = await async_execute(
        db.table("group_members")
        .select("user_id, joined_at, users(first_name, username)")
        .eq("group_id", group_id)
        .order("joined_at", desc=False)
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
    return {"group_id": group_id, "total": len(result), "members": result}
