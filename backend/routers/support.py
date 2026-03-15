"""
Модуль: routers/support.py
Описание: API эндпоинты для техподдержки (тикеты)
Проект: GroupBuy Mini App

Эндпоинты:
    POST /api/support                        — Создать обращение
    GET  /api/support                        — Мои обращения
    GET  /api/support/{id}                   — Детали обращения
    POST /api/support/{id}/message           — Отправить сообщение
    POST /api/support/{id}/close             — Закрыть обращение
    GET  /api/support/faq                    — Часто задаваемые вопросы

Логика:
    1. Пользователь создаёт тикет с категорией и сообщением
    2. Тикет появляется в админ-боте
    3. Админ отвечает → пользователь получает уведомление
    4. Переписка идёт через messages (JSON массив в БД)

Использование из фронтенда:
    // Создать обращение
    await api.post('/api/support', {
        category: 'delivery',
        message: 'Не могу отследить посылку',
        order_id: 42
    });
"""

from typing import Optional, List
from datetime import datetime
import uuid
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sys
sys.path.append("..")
from utils.auth import get_current_user
from database.connection import get_supabase_client
from utils.async_db import async_execute


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/support",
    tags=["Поддержка"],
    responses={401: {"description": "Не авторизован"}}
)


# ============================================================
# МОДЕЛИ ЗАПРОСОВ
# ============================================================

class CreateTicketRequest(BaseModel):
    """Запрос на создание обращения."""
    category: str = Field(..., description="Категория: delivery, payment, product, order, other")
    message: str = Field(..., min_length=10, max_length=2000, description="Текст обращения")
    order_id: Optional[int] = Field(None, description="ID заказа (если связано)")

    class Config:
        json_schema_extra = {
            "example": {
                "category": "delivery",
                "message": "Не могу отследить свою посылку, прошло уже 10 дней",
                "order_id": 42
            }
        }


class SendMessageRequest(BaseModel):
    """Отправка сообщения в тикет."""
    text: str = Field(..., min_length=1, max_length=2000, description="Текст сообщения")


# ============================================================
# КАТЕГОРИИ ОБРАЩЕНИЙ
# ============================================================

SUPPORT_CATEGORIES = {
    "delivery": "🚚 Доставка",
    "payment": "💳 Оплата",
    "product": "📦 Товар",
    "order": "📋 Заказ",
    "return": "🔄 Возврат",
    "account": "👤 Аккаунт",
    "other": "❓ Другое"
}


# ============================================================
# ЭНДПОИНТЫ
# ============================================================

@router.post("", summary="Создать обращение")
async def create_ticket(
    request: CreateTicketRequest,
    user_id: int = Depends(get_current_user)
):
    """
    Создать новое обращение в поддержку.
    
    Категории: delivery, payment, product, order, return, account, other
    
    Пример:
        POST /api/support
        {
            "category": "delivery",
            "message": "Когда будет доставлен заказ?",
            "order_id": 42
        }
    """
    db = get_supabase_client()
    
    # Проверяем категорию
    if request.category not in SUPPORT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестная категория. Допустимые: {', '.join(SUPPORT_CATEGORIES.keys())}"
        )
    
    # Если указан order_id — проверяем что заказ принадлежит пользователю
    if request.order_id:
        order_check = await async_execute(
            db.table("orders").select("id").eq(
                "id", request.order_id
            ).eq("user_id", user_id)
        )
        
        if not order_check.data:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    
    # Формируем первое сообщение
    first_message = {
        "id": str(uuid.uuid4()),
        "sender_type": "user",
        "sender_id": user_id,
        "text": request.message,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Создаём тикет
    ticket_data = {
        "user_id": user_id,
        "order_id": request.order_id,
        "category": request.category,
        "status": "open",
        "messages": json.dumps([first_message])
    }
    
    result = await async_execute(
        db.table("support_tickets").insert(ticket_data)
    )
    
    if not result.data:
        raise HTTPException(status_code=500, detail="Ошибка создания обращения")
    
    ticket = result.data[0]
    
    # TODO: Отправить уведомление админу
    
    return {
        "success": True,
        "data": {
            "id": ticket["id"],
            "category": request.category,
            "category_display": SUPPORT_CATEGORIES[request.category],
            "status": "open",
            "message": "Обращение создано. Мы ответим в ближайшее время."
        }
    }


@router.get("", summary="Мои обращения")
async def get_my_tickets(
    user_id: int = Depends(get_current_user),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """
    Получить список обращений текущего пользователя.
    
    Примеры:
        GET /api/support                    — Все обращения
        GET /api/support?status=open        — Только открытые
    """
    db = get_supabase_client()
    
    query = db.table("support_tickets").select("*").eq("user_id", user_id)
    
    if status:
        query = query.eq("status", status)
    
    query = query.order("updated_at", desc=True).range(offset, offset + limit - 1)
    result = await async_execute(query)
    
    tickets = []
    for t in (result.data or []):
        messages = t.get("messages", [])
        if isinstance(messages, str):
            messages = json.loads(messages)
        
        # Последнее сообщение
        last_message = messages[-1] if messages else None
        
        # Количество непрочитанных (от поддержки)
        unread_count = sum(
            1 for m in messages 
            if m.get("sender_type") == "support" and not m.get("read", False)
        )
        
        tickets.append({
            "id": t["id"],
            "category": t["category"],
            "category_display": SUPPORT_CATEGORIES.get(t["category"], t["category"]),
            "status": t["status"],
            "status_display": _get_status_display(t["status"]),
            "order_id": t.get("order_id"),
            "messages_count": len(messages),
            "unread_count": unread_count,
            "last_message": {
                "text": last_message["text"][:100] if last_message else "",
                "sender_type": last_message.get("sender_type", "") if last_message else "",
                "created_at": last_message.get("created_at", "") if last_message else ""
            } if last_message else None,
            "created_at": t["created_at"],
            "updated_at": t.get("updated_at")
        })
    
    return {
        "success": True,
        "data": tickets,
        "count": len(tickets)
    }


@router.get("/faq", summary="Часто задаваемые вопросы")
async def get_faq(
    category: Optional[str] = Query(None, description="Фильтр по категории")
):
    """
    Получить список часто задаваемых вопросов.
    
    Не требует авторизации.
    
    Примеры:
        GET /api/support/faq                   — Все FAQ
        GET /api/support/faq?category=Оплата  — FAQ по оплате
    """
    db = get_supabase_client()
    
    query = db.table("faq").select("*").eq("is_active", True)
    
    if category:
        query = query.eq("category", category)
    
    query = query.order("sort_order", desc=False)
    result = await async_execute(query)
    
    # Группируем по категориям
    faq_by_category = {}
    for item in (result.data or []):
        cat = item["category"]
        if cat not in faq_by_category:
            faq_by_category[cat] = []
        faq_by_category[cat].append({
            "id": item["id"],
            "question": item["question"],
            "answer": item["answer"]
        })
    
    return {
        "success": True,
        "data": faq_by_category,
        "categories": list(faq_by_category.keys())
    }


@router.get("/{ticket_id}", summary="Детали обращения")
async def get_ticket_detail(
    ticket_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Получить полную информацию об обращении, включая переписку.
    """
    db = get_supabase_client()
    
    result = await async_execute(
        db.table("support_tickets").select("*").eq(
            "id", ticket_id
        ).eq("user_id", user_id)
    )
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    
    ticket = result.data[0]
    messages = ticket.get("messages", [])
    if isinstance(messages, str):
        messages = json.loads(messages)
    
    return {
        "success": True,
        "data": {
            "id": ticket["id"],
            "category": ticket["category"],
            "category_display": SUPPORT_CATEGORIES.get(ticket["category"], ticket["category"]),
            "status": ticket["status"],
            "status_display": _get_status_display(ticket["status"]),
            "order_id": ticket.get("order_id"),
            "messages": messages,
            "resolution": ticket.get("resolution"),
            "created_at": ticket["created_at"],
            "updated_at": ticket.get("updated_at")
        }
    }


@router.post("/{ticket_id}/message", summary="Отправить сообщение")
async def send_message(
    ticket_id: int,
    request: SendMessageRequest,
    user_id: int = Depends(get_current_user)
):
    """
    Отправить сообщение в обращение.
    
    Доступно только если тикет не закрыт.
    """
    db = get_supabase_client()
    
    # Получаем тикет
    result = await async_execute(
        db.table("support_tickets").select("*").eq(
            "id", ticket_id
        ).eq("user_id", user_id)
    )
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    
    ticket = result.data[0]
    
    if ticket["status"] == "closed":
        raise HTTPException(status_code=400, detail="Обращение закрыто")
    
    # Добавляем сообщение
    messages = ticket.get("messages", [])
    if isinstance(messages, str):
        messages = json.loads(messages)
    
    new_message = {
        "id": str(uuid.uuid4()),
        "sender_type": "user",
        "sender_id": user_id,
        "text": request.text,
        "created_at": datetime.utcnow().isoformat()
    }
    messages.append(new_message)
    
    # Обновляем тикет
    await async_execute(
        db.table("support_tickets").update({
            "messages": json.dumps(messages),
            "status": "open"  # Если был waiting_user — возвращаем в open
        }).eq("id", ticket_id)
    )
    
    # TODO: Уведомить админа о новом сообщении
    
    return {
        "success": True,
        "data": new_message
    }


@router.post("/{ticket_id}/close", summary="Закрыть обращение")
async def close_ticket(
    ticket_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Закрыть обращение (со стороны пользователя).
    """
    db = get_supabase_client()
    
    result = await async_execute(
        db.table("support_tickets").select("id, status").eq(
            "id", ticket_id
        ).eq("user_id", user_id)
    )
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    
    if result.data[0]["status"] == "closed":
        raise HTTPException(status_code=400, detail="Обращение уже закрыто")
    
    await async_execute(
        db.table("support_tickets").update({
            "status": "closed"
        }).eq("id", ticket_id)
    )
    
    return {
        "success": True,
        "message": "Обращение закрыто"
    }


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _get_status_display(status: str) -> str:
    """Человекочитаемый статус тикета."""
    statuses = {
        "open": "Открыт",
        "in_progress": "В работе",
        "waiting_user": "Ожидает ответа",
        "closed": "Закрыт"
    }
    return statuses.get(status, status)