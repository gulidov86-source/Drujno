"""
Модуль: routers/users.py
Описание: API эндпоинты для работы с пользователями
Проект: GroupBuy Mini App

Эндпоинты:
    POST /api/users/auth       — Авторизация через Telegram
    GET  /api/users/me         — Получить свой профиль
    PATCH /api/users/me        — Обновить профиль
    GET  /api/users/me/stats   — Статистика пользователя
    
    GET  /api/users/me/addresses     — Список адресов
    POST /api/users/me/addresses     — Добавить адрес
    PATCH /api/users/me/addresses/{id} — Обновить адрес
    DELETE /api/users/me/addresses/{id} — Удалить адрес

Использование:
    from routers.users import router
    app.include_router(router)
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel

import sys
sys.path.append("..")
from config import settings
from database.connection import get_db, DatabaseHelper
from database.models import (
    User, UserCreate, UserUpdate, UserStats, UserLevel,
    Address, AddressCreate,
    NotificationSettings
)
from utils.telegram import (
    validate_telegram_init_data,
    parse_telegram_user,
    parse_telegram_init_data,
    is_init_data_expired
)
from utils.auth import (
    create_token_response,
    get_current_user,
    get_current_user_optional,
    TokenResponse
)


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/users",
    tags=["Пользователи"]
)


# ============================================================
# МОДЕЛИ ЗАПРОСОВ/ОТВЕТОВ
# ============================================================

class AuthRequest(BaseModel):
    """
    Запрос авторизации.
    
    Атрибуты:
        init_data: Строка initData от Telegram WebApp
    
    Пример:
        {
            "init_data": "query_id=AAH...&user=%7B%22id%22...&hash=abc123"
        }
    """
    init_data: str


class AuthResponse(BaseModel):
    """
    Ответ при успешной авторизации.
    
    Атрибуты:
        user: Данные пользователя
        token: JWT токен
        is_new: True если пользователь только что создан
    """
    user: User
    token: TokenResponse
    is_new: bool = False


class ProfileResponse(BaseModel):
    """Профиль пользователя с дополнительной информацией."""
    user: User
    stats: UserStats
    addresses_count: int
    notification_settings: NotificationSettings


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_level_info(level: UserLevel) -> dict:
    """
    Получить информацию об уровне.
    
    Возвращает emoji и название на русском.
    """
    level_map = {
        UserLevel.NEWCOMER: {"emoji": "🌱", "name": "Новичок"},
        UserLevel.BUYER: {"emoji": "🛒", "name": "Покупатель"},
        UserLevel.ACTIVIST: {"emoji": "⭐", "name": "Активист"},
        UserLevel.EXPERT: {"emoji": "🔥", "name": "Эксперт"},
        UserLevel.AMBASSADOR: {"emoji": "👑", "name": "Амбассадор"},
    }
    return level_map.get(level, {"emoji": "🌱", "name": "Новичок"})


def calculate_level_progress(user_data: dict) -> float:
    """
    Рассчитать прогресс до следующего уровня.
    
    Возвращает число от 0 до 1.
    """
    level = user_data.get("level", "newcomer")
    orders = user_data.get("total_orders", 0)
    invites = user_data.get("invited_count", 0)
    groups = user_data.get("groups_organized", 0)
    
    # Требования для каждого уровня
    requirements = {
        "newcomer": {"orders": 3},  # До buyer
        "buyer": {"orders": 10, "invites": 20},  # До activist
        "activist": {"orders": 25, "groups": 5},  # До expert
        "expert": {"orders": 50, "groups": 15},  # До ambassador
        "ambassador": {}  # Максимальный уровень
    }
    
    reqs = requirements.get(level, {})
    if not reqs:
        return 1.0  # Максимальный уровень
    
    # Считаем прогресс по каждому требованию
    progresses = []
    
    if "orders" in reqs:
        progresses.append(min(1.0, orders / reqs["orders"]))
    if "invites" in reqs:
        progresses.append(min(1.0, invites / reqs["invites"]))
    if "groups" in reqs:
        progresses.append(min(1.0, groups / reqs["groups"]))
    
    if not progresses:
        return 0.0
    
    # Возвращаем минимальный прогресс (нужно выполнить все требования)
    return min(progresses)


def get_next_level_requirements(level: str) -> Optional[dict]:
    """Получить требования для следующего уровня."""
    requirements = {
        "newcomer": {"orders_needed": 3, "description": "Сделай 3 заказа"},
        "buyer": {"orders_needed": 10, "invites_needed": 20, 
                  "description": "10 заказов и 20 приглашений"},
        "activist": {"orders_needed": 25, "groups_to_close": 5,
                     "description": "25 заказов и 5 успешных сборов"},
        "expert": {"orders_needed": 50, "groups_to_close": 15,
                   "description": "50 заказов и 15 успешных сборов"},
        "ambassador": None  # Максимальный уровень
    }
    return requirements.get(level)


# ============================================================
# ЭНДПОИНТЫ: АВТОРИЗАЦИЯ
# ============================================================

@router.post(
    "/auth",
    response_model=AuthResponse,
    summary="Авторизация через Telegram",
    description="""
    Авторизует пользователя через Telegram Mini App.
    
    Принимает initData от Telegram, проверяет подпись,
    создаёт/обновляет пользователя и возвращает JWT токен.
    
    **Как получить initData на фронтенде:**
    ```javascript
    const initData = window.Telegram.WebApp.initData;
    ```
    """
)
async def auth_telegram(request: AuthRequest):
    """
    Авторизация через Telegram.
    
    Процесс:
    1. Проверяем подпись initData
    2. Проверяем срок действия
    3. Парсим данные пользователя
    4. Находим или создаём пользователя в БД
    5. Генерируем JWT токен
    """
    init_data = request.init_data
    
    # 1. Проверяем подпись
    if not validate_telegram_init_data(init_data):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидные данные Telegram. Подпись не прошла проверку."
        )
    
    # 2. Проверяем срок действия (24 часа)
    if is_init_data_expired(init_data, max_age_seconds=86400):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия устарела. Пожалуйста, перезапустите приложение."
        )
    
    # 3. Парсим данные пользователя
    tg_data = parse_telegram_init_data(init_data)
    if not tg_data or not tg_data.user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось получить данные пользователя"
        )
    
    tg_user = tg_data.user
    db = get_db()
    is_new = False
    
    # 4. Ищем пользователя по telegram_id
    result = (
        db.table("users")
        .select("*")
        .eq("telegram_id", tg_user.id)
        .limit(1)
        .execute()
    )
    
    if result.data and len(result.data) > 0:
        # Пользователь существует — обновляем данные
        user_data = result.data[0]
        
        # Обновляем данные из Telegram (могли измениться)
        update_data = {
            "username": tg_user.username,
            "first_name": tg_user.first_name,
            "last_name": tg_user.last_name,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        db.table("users").update(update_data).eq("id", user_data["id"]).execute()
        user_data.update(update_data)
        
    else:
        # Новый пользователь — создаём
        is_new = True
        
        new_user_data = {
            "telegram_id": tg_user.id,
            "username": tg_user.username,
            "first_name": tg_user.first_name,
            "last_name": tg_user.last_name,
            "level": "newcomer",
            "total_orders": 0,
            "total_savings": 0,
            "invited_count": 0,
            "groups_organized": 0
        }
        
        result = db.table("users").insert(new_user_data).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось создать пользователя"
            )
        
        user_data = result.data[0]
    
    # 5. Генерируем токен
    token = create_token_response(
        user_id=user_data["id"],
        telegram_id=tg_user.id
    )
    
    # Формируем ответ
    user = User(
        id=user_data["id"],
        telegram_id=user_data["telegram_id"],
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
        phone=user_data.get("phone"),
        level=UserLevel(user_data.get("level", "newcomer")),
        total_orders=user_data.get("total_orders", 0),
        total_savings=user_data.get("total_savings", 0),
        invited_count=user_data.get("invited_count", 0),
        groups_organized=user_data.get("groups_organized", 0),
        created_at=user_data.get("created_at"),
        updated_at=user_data.get("updated_at")
    )
    
    return AuthResponse(
        user=user,
        token=token,
        is_new=is_new
    )


# ============================================================
# ЭНДПОИНТЫ: ПРОФИЛЬ
# ============================================================

@router.get(
    "/me",
    response_model=User,
    summary="Получить свой профиль",
    description="Возвращает данные текущего авторизованного пользователя."
)
async def get_my_profile(user_id: int = Depends(get_current_user)):
    """
    Получить профиль текущего пользователя.
    
    Требует авторизации (JWT токен в заголовке).
    """
    db = get_db()
    
    result = (
        db.table("users")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    user_data = result.data[0]
    
    return User(
        id=user_data["id"],
        telegram_id=user_data["telegram_id"],
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
        phone=user_data.get("phone"),
        level=UserLevel(user_data.get("level", "newcomer")),
        total_orders=user_data.get("total_orders", 0),
        total_savings=user_data.get("total_savings", 0),
        invited_count=user_data.get("invited_count", 0),
        groups_organized=user_data.get("groups_organized", 0),
        created_at=user_data.get("created_at"),
        updated_at=user_data.get("updated_at")
    )


@router.patch(
    "/me",
    response_model=User,
    summary="Обновить профиль",
    description="Обновляет данные текущего пользователя."
)
async def update_my_profile(
    update_data: UserUpdate,
    user_id: int = Depends(get_current_user)
):
    """
    Обновить профиль текущего пользователя.
    
    Можно обновить: first_name, last_name, phone.
    Username обновляется автоматически из Telegram.
    """
    db = get_db()
    
    # Формируем данные для обновления (только непустые поля)
    data_to_update = {}
    if update_data.first_name is not None:
        data_to_update["first_name"] = update_data.first_name
    if update_data.last_name is not None:
        data_to_update["last_name"] = update_data.last_name
    if update_data.phone is not None:
        data_to_update["phone"] = update_data.phone
    
    if not data_to_update:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет данных для обновления"
        )
    
    data_to_update["updated_at"] = datetime.utcnow().isoformat()
    
    # Обновляем
    result = (
        db.table("users")
        .update(data_to_update)
        .eq("id", user_id)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    user_data = result.data[0]
    
    return User(
        id=user_data["id"],
        telegram_id=user_data["telegram_id"],
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
        phone=user_data.get("phone"),
        level=UserLevel(user_data.get("level", "newcomer")),
        total_orders=user_data.get("total_orders", 0),
        total_savings=user_data.get("total_savings", 0),
        invited_count=user_data.get("invited_count", 0),
        groups_organized=user_data.get("groups_organized", 0),
        created_at=user_data.get("created_at"),
        updated_at=user_data.get("updated_at")
    )


@router.get(
    "/me/stats",
    response_model=UserStats,
    summary="Статистика пользователя",
    description="Возвращает статистику и прогресс до следующего уровня."
)
async def get_my_stats(user_id: int = Depends(get_current_user)):
    """
    Получить статистику пользователя.
    
    Включает:
    - Текущий уровень с emoji и названием
    - Прогресс до следующего уровня
    - Количество заказов, экономию, приглашённых
    """
    db = get_db()
    
    # Получаем пользователя
    result = db.table("users").select("*").eq("id", user_id).limit(1).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    user_data = result.data[0]
    level = UserLevel(user_data.get("level", "newcomer"))
    level_info = get_level_info(level)
    
    # Считаем участие в сборах
    members_result = (
        db.table("group_members")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    groups_participated = members_result.count or 0
    
    return UserStats(
        level=level,
        level_emoji=level_info["emoji"],
        level_name=level_info["name"],
        level_progress=calculate_level_progress(user_data),
        total_orders=user_data.get("total_orders", 0),
        total_savings=user_data.get("total_savings", 0),
        groups_participated=groups_participated,
        groups_organized=user_data.get("groups_organized", 0),
        people_invited=user_data.get("invited_count", 0),
        next_level_requirements=get_next_level_requirements(user_data.get("level", "newcomer"))
    )


# ============================================================
# ЭНДПОИНТЫ: АДРЕСА
# ============================================================

@router.get(
    "/me/addresses",
    response_model=List[Address],
    summary="Список адресов доставки",
    description="Возвращает все адреса доставки пользователя."
)
async def get_my_addresses(user_id: int = Depends(get_current_user)):
    """Получить все адреса пользователя."""
    db = get_db()
    
    result = (
        db.table("addresses")
        .select("*")
        .eq("user_id", user_id)
        .order("is_default", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    
    return [Address(**addr) for addr in (result.data or [])]


@router.post(
    "/me/addresses",
    response_model=Address,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить адрес",
    description="Добавляет новый адрес доставки."
)
async def add_address(
    address_data: AddressCreate,
    user_id: int = Depends(get_current_user)
):
    """
    Добавить новый адрес.
    
    Если is_default=True, снимает флаг с других адресов.
    """
    db = get_db()
    
    # Если новый адрес по умолчанию — снимаем флаг с остальных
    if address_data.is_default:
        db.table("addresses").update({"is_default": False}).eq("user_id", user_id).execute()
    
    # Создаём адрес
    new_address = {
        "user_id": user_id,
        "title": address_data.title,
        "city": address_data.city,
        "street": address_data.street,
        "building": address_data.building,
        "apartment": address_data.apartment,
        "entrance": address_data.entrance,
        "floor": address_data.floor,
        "postal_code": address_data.postal_code,
        "comment": address_data.comment,
        "is_default": address_data.is_default
    }
    
    result = db.table("addresses").insert(new_address).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось создать адрес"
        )
    
    return Address(**result.data[0])


@router.patch(
    "/me/addresses/{address_id}",
    response_model=Address,
    summary="Обновить адрес",
    description="Обновляет существующий адрес доставки."
)
async def update_address(
    address_id: int,
    address_data: AddressCreate,
    user_id: int = Depends(get_current_user)
):
    """Обновить адрес."""
    db = get_db()
    
    # Проверяем, что адрес принадлежит пользователю
    existing = (
        db.table("addresses")
        .select("id")
        .eq("id", address_id)
        .eq("user_id", user_id)
        .execute()
    )
    
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Адрес не найден"
        )
    
    # Если делаем адресом по умолчанию — снимаем флаг с остальных
    if address_data.is_default:
        db.table("addresses").update({"is_default": False}).eq("user_id", user_id).execute()
    
    # Обновляем
    update_data = {
        "title": address_data.title,
        "city": address_data.city,
        "street": address_data.street,
        "building": address_data.building,
        "apartment": address_data.apartment,
        "entrance": address_data.entrance,
        "floor": address_data.floor,
        "postal_code": address_data.postal_code,
        "comment": address_data.comment,
        "is_default": address_data.is_default
    }
    
    result = db.table("addresses").update(update_data).eq("id", address_id).execute()
    
    return Address(**result.data[0])


@router.delete(
    "/me/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить адрес",
    description="Удаляет адрес доставки."
)
async def delete_address(
    address_id: int,
    user_id: int = Depends(get_current_user)
):
    """Удалить адрес."""
    db = get_db()
    
    # Проверяем, что адрес принадлежит пользователю
    existing = (
        db.table("addresses")
        .select("id")
        .eq("id", address_id)
        .eq("user_id", user_id)
        .execute()
    )
    
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Адрес не найден"
        )
    
    # Удаляем
    db.table("addresses").delete().eq("id", address_id).execute()
    
    return None


# ============================================================
# ЭНДПОИНТЫ: НАСТРОЙКИ УВЕДОМЛЕНИЙ
# ============================================================

@router.get(
    "/me/notifications",
    response_model=NotificationSettings,
    summary="Настройки уведомлений",
    description="Возвращает текущие настройки уведомлений."
)
async def get_notification_settings(user_id: int = Depends(get_current_user)):
    """Получить настройки уведомлений."""
    db = get_db()
    
    result = (
        db.table("users")
        .select("notification_settings")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    settings_data = result.data[0].get("notification_settings", {})
    return NotificationSettings(**settings_data)


@router.patch(
    "/me/notifications",
    response_model=NotificationSettings,
    summary="Обновить настройки уведомлений",
    description="Обновляет настройки уведомлений."
)
async def update_notification_settings(
    settings_data: NotificationSettings,
    user_id: int = Depends(get_current_user)
):
    """Обновить настройки уведомлений."""
    db = get_db()
    
    result = (
        db.table("users")
        .update({"notification_settings": settings_data.model_dump()})
        .eq("id", user_id)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    return settings_data
