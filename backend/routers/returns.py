"""
Модуль: routers/returns.py
Описание: API эндпоинты для управления возвратами товаров
Проект: GroupBuy Mini App

Эндпоинты:
    POST /api/returns                    — Создать заявку на возврат
    GET  /api/returns                    — Список моих возвратов
    GET  /api/returns/{id}               — Детали возврата
    POST /api/returns/{id}/cancel        — Отменить заявку

Логика возвратов:
    1. Пользователь оформляет возврат (заказ в статусе delivered)
    2. Заявка создаётся со статусом pending
    3. Админ рассматривает (через админ-бот) → approved / rejected
    4. Если approved → пользователь отправляет товар обратно (awaiting_item)
    5. Товар получен → completed, деньги возвращаются

Использование из фронтенда:
    // Создать возврат
    await api.post('/api/returns', {
        order_id: 42,
        reason: 'defect',
        description: 'Трещина на корпусе'
    });
"""

from typing import Optional, List
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sys
sys.path.append("..")
from utils.auth import get_current_user
from database.connection import get_supabase_client
from database.models import ReturnStatus, ReturnReason


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/returns",
    tags=["Возвраты"],
    responses={401: {"description": "Не авторизован"}}
)


# ============================================================
# МОДЕЛИ ЗАПРОСОВ
# ============================================================

class CreateReturnRequest(BaseModel):
    """Запрос на создание возврата."""
    order_id: int = Field(..., description="ID заказа")
    reason: ReturnReason = Field(..., description="Причина возврата")
    description: str = Field(..., min_length=10, max_length=2000, description="Описание проблемы")
    photos: List[str] = Field(default=[], description="URL фотографий (если есть)")

    class Config:
        json_schema_extra = {
            "example": {
                "order_id": 42,
                "reason": "defect",
                "description": "На корпусе глубокая трещина, товар пришёл повреждённым",
                "photos": []
            }
        }


# ============================================================
# ЭНДПОИНТЫ
# ============================================================

@router.post("", summary="Создать заявку на возврат")
async def create_return(
    request: CreateReturnRequest,
    user_id: int = Depends(get_current_user)
):
    """
    Создать заявку на возврат товара.
    
    Условия:
    - Заказ должен быть в статусе 'delivered'
    - Заказ должен принадлежать текущему пользователю
    - На этот заказ ещё нет активного возврата
    
    Пример:
        POST /api/returns
        {
            "order_id": 42,
            "reason": "defect",
            "description": "Товар повреждён при доставке"
        }
    """
    db = get_supabase_client()
    
    # 1. Проверяем что заказ существует и принадлежит пользователю
    order_result = db.table("orders").select("*").eq(
        "id", request.order_id
    ).eq(
        "user_id", user_id
    ).execute()
    
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    
    order = order_result.data[0]
    
    # 2. Проверяем статус заказа (возврат возможен только для доставленных)
    if order["status"] not in ("delivered", "paid", "processing", "shipped"):
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя оформить возврат для заказа в статусе '{order['status']}'"
        )
    
    # 3. Проверяем что нет активного возврата на этот заказ
    existing = db.table("returns").select("id, status").eq(
        "order_id", request.order_id
    ).in_(
        "status", ["pending", "approved", "awaiting_item"]
    ).execute()
    
    if existing.data:
        raise HTTPException(
            status_code=400,
            detail="На этот заказ уже есть активная заявка на возврат"
        )
    
    # 4. Создаём заявку
    import json
    return_data = {
        "order_id": request.order_id,
        "reason": request.reason.value,
        "description": request.description,
        "photos": json.dumps(request.photos),
        "status": ReturnStatus.PENDING.value,
        "refund_amount": float(order["total_amount"])  # По умолчанию — полная сумма
    }
    
    result = db.table("returns").insert(return_data).execute()
    
    if not result.data:
        raise HTTPException(status_code=500, detail="Ошибка создания заявки")
    
    return_record = result.data[0]
    
    # 5. Обновляем статус заказа
    db.table("orders").update({
        "status": "refunded"
    }).eq("id", request.order_id).execute()
    
    # TODO: Отправить уведомление админу через notification_service
    
    return {
        "success": True,
        "data": {
            "id": return_record["id"],
            "order_id": request.order_id,
            "status": "pending",
            "reason": request.reason.value,
            "refund_amount": order["total_amount"],
            "message": "Заявка на возврат создана. Мы рассмотрим её в течение 2 рабочих дней."
        }
    }


@router.get("", summary="Мои возвраты")
async def get_my_returns(
    user_id: int = Depends(get_current_user),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """
    Получить список заявок на возврат текущего пользователя.
    
    Примеры:
        GET /api/returns                     — Все возвраты
        GET /api/returns?status=pending      — Только на рассмотрении
    """
    db = get_supabase_client()
    
    # Получаем заказы пользователя
    orders_result = db.table("orders").select("id").eq(
        "user_id", user_id
    ).execute()
    
    if not orders_result.data:
        return {"success": True, "data": [], "count": 0}
    
    order_ids = [o["id"] for o in orders_result.data]
    
    # Получаем возвраты по этим заказам
    query = db.table("returns").select("*").in_("order_id", order_ids)
    
    if status:
        query = query.eq("status", status)
    
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = query.execute()
    
    # Обогащаем данными заказов
    returns_data = []
    for ret in (result.data or []):
        # Получаем информацию о заказе
        order_info = db.table("orders").select(
            "id, final_price, total_amount, status"
        ).eq("id", ret["order_id"]).execute()
        
        order = order_info.data[0] if order_info.data else {}
        
        returns_data.append({
            "id": ret["id"],
            "order_id": ret["order_id"],
            "reason": ret["reason"],
            "description": ret["description"],
            "status": ret["status"],
            "refund_amount": ret.get("refund_amount"),
            "admin_comment": ret.get("admin_comment"),
            "created_at": ret["created_at"],
            "order_amount": order.get("total_amount"),
            "order_status": order.get("status")
        })
    
    return {
        "success": True,
        "data": returns_data,
        "count": len(returns_data)
    }


@router.get("/{return_id}", summary="Детали возврата")
async def get_return_detail(
    return_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Получить подробную информацию о заявке на возврат.
    """
    db = get_supabase_client()
    
    # Получаем возврат
    result = db.table("returns").select("*").eq("id", return_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    ret = result.data[0]
    
    # Проверяем что заказ принадлежит пользователю
    order_result = db.table("orders").select("*").eq(
        "id", ret["order_id"]
    ).eq(
        "user_id", user_id
    ).execute()
    
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    order = order_result.data[0]
    
    # Получаем информацию о товаре через группу
    product_name = "Товар"
    group_result = db.table("groups").select(
        "product_id"
    ).eq("id", order["group_id"]).execute()
    
    if group_result.data:
        product_result = db.table("products").select(
            "name, image_url"
        ).eq("id", group_result.data[0]["product_id"]).execute()
        
        if product_result.data:
            product_name = product_result.data[0]["name"]
    
    return {
        "success": True,
        "data": {
            "id": ret["id"],
            "order_id": ret["order_id"],
            "reason": ret["reason"],
            "reason_display": _get_reason_display(ret["reason"]),
            "description": ret["description"],
            "photos": ret.get("photos", []),
            "status": ret["status"],
            "status_display": _get_status_display(ret["status"]),
            "refund_amount": ret.get("refund_amount"),
            "admin_comment": ret.get("admin_comment"),
            "created_at": ret["created_at"],
            "completed_at": ret.get("completed_at"),
            "product_name": product_name,
            "order_amount": order["total_amount"]
        }
    }


@router.post("/{return_id}/cancel", summary="Отменить заявку на возврат")
async def cancel_return(
    return_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Отменить заявку на возврат.
    
    Возможно только если заявка в статусе 'pending'.
    """
    db = get_supabase_client()
    
    # Получаем возврат
    result = db.table("returns").select("*").eq("id", return_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    ret = result.data[0]
    
    # Проверяем владельца
    order_result = db.table("orders").select("user_id, status").eq(
        "id", ret["order_id"]
    ).execute()
    
    if not order_result.data or order_result.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Проверяем статус
    if ret["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail="Отменить можно только заявку в статусе 'На рассмотрении'"
        )
    
    # Отменяем (удаляем заявку)
    db.table("returns").delete().eq("id", return_id).execute()
    
    # Восстанавливаем статус заказа
    db.table("orders").update({
        "status": "delivered"
    }).eq("id", ret["order_id"]).execute()
    
    return {
        "success": True,
        "message": "Заявка на возврат отменена"
    }


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _get_reason_display(reason: str) -> str:
    """Человекочитаемая причина возврата."""
    reasons = {
        "wrong_size": "Не подошёл размер/цвет",
        "defect": "Брак/дефект",
        "not_as_described": "Не соответствует описанию",
        "changed_mind": "Передумал"
    }
    return reasons.get(reason, reason)


def _get_status_display(status: str) -> str:
    """Человекочитаемый статус возврата."""
    statuses = {
        "pending": "На рассмотрении",
        "approved": "Одобрен",
        "rejected": "Отклонён",
        "awaiting_item": "Ожидаем возврат товара",
        "completed": "Завершён"
    }
    return statuses.get(status, status)
