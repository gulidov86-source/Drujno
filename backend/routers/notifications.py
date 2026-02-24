"""
Модуль: routers/notifications.py
Описание: API эндпоинты для управления уведомлениями пользователя
Проект: GroupBuy Mini App

Эндпоинты:
    GET    /api/notifications                — Список уведомлений
    GET    /api/notifications/unread-count   — Количество непрочитанных
    POST   /api/notifications/{id}/read      — Отметить как прочитанное
    POST   /api/notifications/read-all       — Отметить все как прочитанные
    GET    /api/notifications/settings       — Настройки уведомлений
    PUT    /api/notifications/settings       — Обновить настройки

Это API для фронтенда. Отправка уведомлений через Telegram 
происходит в services/notification_service.py (уже создан).

Использование из фронтенда:
    // Непрочитанные (для бейджа)
    const count = await api.get('/api/notifications/unread-count');
    
    // Список уведомлений
    const notifications = await api.get('/api/notifications?limit=20');
"""

from typing import Optional
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import sys
sys.path.append("..")
from utils.auth import get_current_user
from database.connection import get_supabase_client


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/notifications",
    tags=["Уведомления"],
    responses={401: {"description": "Не авторизован"}}
)


# ============================================================
# МОДЕЛИ
# ============================================================

class NotificationSettingsUpdate(BaseModel):
    """Обновление настроек уведомлений."""
    order_status: Optional[bool] = None
    price_drops: Optional[bool] = None
    group_reminders: Optional[bool] = None
    new_products: Optional[bool] = None
    promotions: Optional[bool] = None


# ============================================================
# ЭНДПОИНТЫ
# ============================================================

@router.get("", summary="Список уведомлений")
async def get_notifications(
    user_id: int = Depends(get_current_user),
    unread_only: bool = Query(default=False, description="Только непрочитанные"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """
    Получить список уведомлений текущего пользователя.
    
    Примеры:
        GET /api/notifications                      — Последние 20
        GET /api/notifications?unread_only=true     — Только непрочитанные
        GET /api/notifications?limit=50&offset=20   — С пагинацией
    """
    db = get_supabase_client()
    
    query = db.table("notifications").select("*").eq("user_id", user_id)
    
    if unread_only:
        query = query.eq("is_read", False)
    
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = query.execute()
    
    notifications = []
    for n in (result.data or []):
        data = n.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = None
        
        notifications.append({
            "id": n["id"],
            "type": n["type"],
            "title": n["title"],
            "message": n["message"],
            "data": data,
            "is_read": n["is_read"],
            "created_at": n["created_at"],
            "icon": _get_notification_icon(n["type"])
        })
    
    return {
        "success": True,
        "data": notifications,
        "count": len(notifications)
    }


@router.get("/unread-count", summary="Количество непрочитанных")
async def get_unread_count(
    user_id: int = Depends(get_current_user)
):
    """
    Получить количество непрочитанных уведомлений.
    
    Используется для отображения бейджа в навигации.
    
    Ответ:
        {"success": true, "count": 5}
    """
    db = get_supabase_client()
    
    result = db.table("notifications").select(
        "id", count="exact"
    ).eq("user_id", user_id).eq("is_read", False).execute()
    
    return {
        "success": True,
        "count": result.count if result.count else 0
    }


@router.post("/{notification_id}/read", summary="Отметить как прочитанное")
async def mark_as_read(
    notification_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Отметить уведомление как прочитанное.
    """
    db = get_supabase_client()
    
    result = db.table("notifications").update({
        "is_read": True
    }).eq("id", notification_id).eq("user_id", user_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    
    return {"success": True}


@router.post("/read-all", summary="Отметить все как прочитанные")
async def mark_all_as_read(
    user_id: int = Depends(get_current_user)
):
    """
    Отметить все уведомления как прочитанные.
    """
    db = get_supabase_client()
    
    db.table("notifications").update({
        "is_read": True
    }).eq("user_id", user_id).eq("is_read", False).execute()
    
    return {
        "success": True,
        "message": "Все уведомления отмечены как прочитанные"
    }


@router.get("/settings", summary="Настройки уведомлений")
async def get_notification_settings(
    user_id: int = Depends(get_current_user)
):
    """
    Получить текущие настройки уведомлений пользователя.
    """
    db = get_supabase_client()
    
    result = db.table("users").select(
        "notification_settings"
    ).eq("id", user_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    settings = result.data[0].get("notification_settings", {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    # Дефолтные настройки если нет в БД
    default_settings = {
        "order_status": True,
        "price_drops": True,
        "group_reminders": True,
        "new_products": False,
        "promotions": False
    }
    
    # Мержим с дефолтными
    merged = {**default_settings, **settings}
    
    return {
        "success": True,
        "data": merged
    }


@router.put("/settings", summary="Обновить настройки уведомлений")
async def update_notification_settings(
    request: NotificationSettingsUpdate,
    user_id: int = Depends(get_current_user)
):
    """
    Обновить настройки уведомлений.
    
    Передавайте только те поля, которые хотите изменить.
    
    Пример:
        PUT /api/notifications/settings
        {"price_drops": false, "promotions": true}
    """
    db = get_supabase_client()
    
    # Получаем текущие настройки
    user_result = db.table("users").select(
        "notification_settings"
    ).eq("id", user_id).execute()
    
    if not user_result.data:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    current = user_result.data[0].get("notification_settings", {})
    if isinstance(current, str):
        current = json.loads(current)
    
    # Обновляем только переданные поля
    update_data = request.model_dump(exclude_none=True)
    current.update(update_data)
    
    # Сохраняем
    db.table("users").update({
        "notification_settings": json.dumps(current)
    }).eq("id", user_id).execute()
    
    return {
        "success": True,
        "data": current,
        "message": "Настройки обновлены"
    }


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _get_notification_icon(notification_type: str) -> str:
    """Эмодзи-иконка для типа уведомления."""
    icons = {
        "group_joined": "👥",
        "group_completed": "🎉",
        "group_failed": "😔",
        "price_drop": "📉",
        "order_paid": "💳",
        "order_shipped": "🚚",
        "order_delivered": "📦",
        "level_up": "⬆️",
        "referral_bonus": "🎁",
        "return_approved": "✅",
        "return_rejected": "❌",
        "support_reply": "💬",
        "new_product": "🆕",
        "promotion": "🔥"
    }
    return icons.get(notification_type, "🔔")
