"""
Модуль: routers/payments.py
Описание: API эндпоинты для работы с платежами
Проект: GroupBuy Mini App

Этот модуль обрабатывает:
- Webhook'и от ЮKassa
- Получение статуса платежа
- Ручное подтверждение/отмену (для админки)

Эндпоинты:
    POST /api/payments/webhook  — Webhook от ЮKassa
    GET  /api/payments/{id}     — Статус платежа
    POST /api/payments/{id}/capture — Списать средства (админ)
    POST /api/payments/{id}/cancel  — Отменить платёж (админ)

Использование:
    from routers.payments import router
    app.include_router(router)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Header
from pydantic import BaseModel

import sys
sys.path.append("..")
from database.connection import get_db
from database.models import PaymentStatus, PaymentMethod
from services.payment_service import get_payment_service
from services.group_manager import get_group_manager
from utils.auth import get_current_user


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/payments",
    tags=["Платежи"]
)


# ============================================================
# МОДЕЛИ
# ============================================================

class PaymentStatusResponse(BaseModel):
    """Статус платежа."""
    payment_id: int
    external_id: Optional[str] = None
    status: PaymentStatus
    status_text: str
    amount: Decimal
    method: PaymentMethod
    order_id: int
    created_at: datetime
    frozen_at: Optional[datetime] = None
    charged_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None


class WebhookResponse(BaseModel):
    """Ответ на webhook."""
    success: bool
    message: str


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_payment_status_text(status: PaymentStatus) -> str:
    """Получить текст статуса на русском."""
    texts = {
        PaymentStatus.PENDING: "Ожидает оплаты",
        PaymentStatus.FROZEN: "Средства заморожены",
        PaymentStatus.CHARGED: "Оплачен",
        PaymentStatus.REFUNDED: "Возвращён",
        PaymentStatus.CANCELLED: "Отменён",
        PaymentStatus.FAILED: "Ошибка"
    }
    return texts.get(status, str(status))


async def process_successful_payment(order_id: int, db):
    """
    Обработать успешную оплату.
    
    После заморозки средств:
    1. Присоединяем пользователя к сбору
    2. Обновляем статус заказа
    """
    # Получаем заказ
    order = (
        db.table("orders")
        .select("user_id, group_id, comment")
        .eq("id", order_id)
        .limit(1)
        .execute()
    )
    
    if not order.data:
        return False
    
    order_data = order.data[0]
    user_id = order_data["user_id"]
    group_id = order_data["group_id"]
    
    # Извлекаем invited_by из комментария (если есть)
    invited_by = None
    comment = order_data.get("comment", "")
    if "[ref:" in comment:
        try:
            ref_part = comment.split("[ref:")[1].split("]")[0]
            invited_by = int(ref_part)
        except (IndexError, ValueError):
            pass
    
    # Присоединяем к сбору через менеджер
    group_manager = get_group_manager()
    
    result = await group_manager.join_group(
        group_id=group_id,
        user_id=user_id,
        invited_by_user_id=invited_by
    )
    
    # Обновляем статус заказа
    status_history = [{
        "status": "frozen",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "comment": "Оплата заморожена"
    }]
    
    db.table("orders").update({
        "status": "frozen",
        "status_history": status_history
    }).eq("id", order_id).execute()
    
    return result.success


# ============================================================
# WEBHOOK ОТ ЮKASSA
# ============================================================

@router.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Webhook от ЮKassa",
    description="""
    Принимает уведомления от ЮKassa о статусе платежей.
    
    **События:**
    - `payment.waiting_for_capture` — деньги заморожены
    - `payment.succeeded` — платёж успешен
    - `payment.canceled` — платёж отменён
    - `refund.succeeded` — возврат успешен
    
    **Безопасность:**
    Проверяется подпись в заголовке `Webhook-Signature`.
    """
)
async def handle_webhook(
    request: Request,
    webhook_signature: Optional[str] = Header(None, alias="Webhook-Signature")
):
    """
    Обработать webhook от ЮKassa.
    """
    payment_service = get_payment_service()
    db = get_db()
    
    # Получаем тело запроса
    body = await request.body()
    
    # Проверяем подпись (если настроен секрет)
    if webhook_signature:
        is_valid = payment_service.verify_webhook_signature(body, webhook_signature)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
    
    # Парсим JSON
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON"
        )
    
    event_type = data.get("event")
    payment_data = data.get("object", {})
    
    if not event_type or not payment_data:
        return WebhookResponse(
            success=False,
            message="Missing event or object"
        )
    
    # Обрабатываем событие
    payment_id = payment_data.get("id")
    order_id = payment_data.get("metadata", {}).get("order_id")
    
    print(f"[Webhook] {event_type}: payment={payment_id}, order={order_id}")
    
    if event_type == "payment.waiting_for_capture":
        # Деньги заморожены — присоединяем к сбору
        if order_id:
            await process_successful_payment(int(order_id), db)
        
        # Обновляем статус платежа
        await payment_service.handle_webhook(event_type, payment_data)
        
        return WebhookResponse(
            success=True,
            message="Payment frozen, user joined group"
        )
    
    elif event_type == "payment.succeeded":
        # Платёж полностью завершён (после capture)
        await payment_service.handle_webhook(event_type, payment_data)
        
        return WebhookResponse(
            success=True,
            message="Payment succeeded"
        )
    
    elif event_type == "payment.canceled":
        # Платёж отменён
        await payment_service.handle_webhook(event_type, payment_data)
        
        return WebhookResponse(
            success=True,
            message="Payment canceled"
        )
    
    elif event_type == "refund.succeeded":
        # Возврат успешен
        # Обновляем статус платежа
        original_payment_id = payment_data.get("payment_id")
        if original_payment_id:
            db.table("payments").update({
                "status": "refunded",
                "refunded_at": datetime.now(timezone.utc).isoformat()
            }).eq("external_id", original_payment_id).execute()
        
        return WebhookResponse(
            success=True,
            message="Refund succeeded"
        )
    
    return WebhookResponse(
        success=True,
        message=f"Event {event_type} received"
    )


# ============================================================
# СТАТУС ПЛАТЕЖА
# ============================================================

@router.get(
    "/{payment_id}",
    response_model=PaymentStatusResponse,
    summary="Статус платежа",
    description="Получить информацию о платеже."
)
async def get_payment_status(
    payment_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Получить статус платежа.
    """
    db = get_db()
    
    # Получаем платёж с проверкой владельца
    result = (
        db.table("payments")
        .select("*, orders(user_id)")
        .eq("id", payment_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Платёж не найден"
        )
    
    payment_data = result.data[0]
    order_data = payment_data.get("orders", {})
    
    # Проверяем, что платёж принадлежит пользователю
    if order_data.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён"
        )
    
    payment_status = PaymentStatus(payment_data.get("status", "pending"))
    
    return PaymentStatusResponse(
        payment_id=payment_data["id"],
        external_id=payment_data.get("external_id"),
        status=payment_status,
        status_text=get_payment_status_text(payment_status),
        amount=Decimal(str(payment_data.get("amount", 0))),
        method=PaymentMethod(payment_data.get("method", "card")),
        order_id=payment_data.get("order_id"),
        created_at=payment_data.get("created_at"),
        frozen_at=payment_data.get("frozen_at"),
        charged_at=payment_data.get("charged_at"),
        refunded_at=payment_data.get("refunded_at")
    )


# ============================================================
# ПРОВЕРКА СТАТУСА (ДЛЯ ФРОНТЕНДА)
# ============================================================

@router.get(
    "/order/{order_id}/status",
    summary="Статус оплаты заказа",
    description="Проверить статус оплаты для заказа (для polling на фронтенде)."
)
async def check_order_payment_status(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Проверить статус оплаты заказа.
    
    Используется для polling на фронтенде после редиректа с оплаты.
    """
    db = get_db()
    
    # Получаем заказ
    result = (
        db.table("orders")
        .select("status, payments(status, external_id)")
        .eq("id", order_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Заказ не найден"
        )
    
    order_data = result.data[0]
    payments = order_data.get("payments", [])
    
    # Определяем статус
    order_status = order_data.get("status")
    payment_status = payments[0].get("status") if payments else None
    
    is_paid = order_status in ["frozen", "paid", "processing", "shipped", "delivered"]
    is_pending = order_status == "pending" and payment_status in ["pending", None]
    is_failed = payment_status == "failed"
    is_cancelled = order_status == "cancelled" or payment_status == "cancelled"
    
    return {
        "order_id": order_id,
        "order_status": order_status,
        "payment_status": payment_status,
        "is_paid": is_paid,
        "is_pending": is_pending,
        "is_failed": is_failed,
        "is_cancelled": is_cancelled,
        "message": get_status_message(order_status, payment_status)
    }


def get_status_message(order_status: str, payment_status: str) -> str:
    """Получить сообщение о статусе."""
    if order_status in ["frozen", "paid"]:
        return "Оплата прошла успешно! Вы присоединились к сбору."
    elif order_status == "pending" and payment_status == "pending":
        return "Ожидаем оплату..."
    elif payment_status == "failed":
        return "Ошибка оплаты. Попробуйте ещё раз."
    elif order_status == "cancelled" or payment_status == "cancelled":
        return "Заказ отменён."
    else:
        return "Обработка..."


# ============================================================
# АДМИНСКИЕ ФУНКЦИИ
# ============================================================

@router.post(
    "/{payment_id}/capture",
    summary="Списать средства",
    description="""
    Списать замороженные средства.
    
    **Для администраторов.** Используется после завершения сбора.
    """
)
async def capture_payment(
    payment_id: int,
    amount: Optional[Decimal] = None,
    user_id: int = Depends(get_current_user)
):
    """
    Списать замороженные средства.
    
    TODO: Добавить проверку прав администратора.
    """
    db = get_db()
    payment_service = get_payment_service()
    
    # Получаем платёж
    result = (
        db.table("payments")
        .select("external_id, status, amount")
        .eq("id", payment_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Платёж не найден"
        )
    
    payment_data = result.data[0]
    
    if payment_data.get("status") != "frozen":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Платёж не в статусе frozen"
        )
    
    external_id = payment_data.get("external_id")
    if not external_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет external_id платежа"
        )
    
    # Списываем
    capture_result = await payment_service.capture_payment(
        payment_id=external_id,
        amount=amount or Decimal(str(payment_data.get("amount", 0)))
    )
    
    if not capture_result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=capture_result.error
        )
    
    return {
        "success": True,
        "status": capture_result.status,
        "amount": float(capture_result.amount)
    }


@router.post(
    "/{payment_id}/refund",
    summary="Вернуть средства",
    description="""
    Вернуть средства по платежу.
    
    **Для администраторов.** Используется для возвратов.
    """
)
async def refund_payment(
    payment_id: int,
    amount: Optional[Decimal] = None,
    reason: str = "Возврат средств",
    user_id: int = Depends(get_current_user)
):
    """
    Вернуть средства.
    
    TODO: Добавить проверку прав администратора.
    """
    db = get_db()
    payment_service = get_payment_service()
    
    # Получаем платёж
    result = (
        db.table("payments")
        .select("external_id, status, amount")
        .eq("id", payment_id)
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Платёж не найден"
        )
    
    payment_data = result.data[0]
    
    if payment_data.get("status") not in ["charged", "frozen"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Возврат невозможен для этого статуса"
        )
    
    external_id = payment_data.get("external_id")
    if not external_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет external_id платежа"
        )
    
    # Если frozen — отменяем, если charged — возвращаем
    if payment_data.get("status") == "frozen":
        refund_result = await payment_service.cancel_payment(external_id)
    else:
        refund_result = await payment_service.refund_payment(
            payment_id=external_id,
            amount=amount or Decimal(str(payment_data.get("amount", 0))),
            description=reason
        )
    
    if not refund_result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=refund_result.error
        )
    
    return {
        "success": True,
        "message": "Средства возвращены"
    }
