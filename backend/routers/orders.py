"""
Модуль: routers/orders.py
Описание: API эндпоинты для работы с заказами
Проект: GroupBuy Mini App

Заказ создаётся когда пользователь присоединяется к сбору и оплачивает.

Жизненный цикл заказа:
    PENDING → FROZEN → PAID → PROCESSING → SHIPPED → DELIVERED
                 ↓
             REFUNDED (если сбор не состоялся)

ОБНОВЛЕНО: Добавлен Rate Limiting на создание заказов (Спринт 1).
ОБНОВЛЕНО: Антифрод-проверка при отмене заказа (Спринт 2).

Эндпоинты:
    GET  /api/orders           — Мои заказы
    GET  /api/orders/{id}      — Детали заказа
    POST /api/orders           — Создать заказ (присоединение к сбору + оплата)
    POST /api/orders/{id}/cancel — Отменить заказ

Использование:
    from routers.orders import router
    app.include_router(router)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

import sys
sys.path.append("..")
from config import settings
from database.connection import get_db
from database.models import (
    Order, OrderStatus, OrderCreate, DeliveryType,
    PaymentStatus, PaymentMethod
)
from services.price_calculator import calculate_current_price
from services.payment_service import get_payment_service
from services.group_manager import get_group_manager
from utils.auth import get_current_user
from rate_limiter import limiter, create_limit


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/orders",
    tags=["Заказы"]
)


# ============================================================
# МОДЕЛИ ЗАПРОСОВ/ОТВЕТОВ
# ============================================================

class CreateOrderRequest(BaseModel):
    group_id: int = Field(..., description="ID сбора")
    address_id: int = Field(..., description="ID адреса доставки")
    delivery_type: DeliveryType = Field(default=DeliveryType.PICKUP, description="Тип доставки")
    payment_method: PaymentMethod = Field(default=PaymentMethod.CARD, description="Способ оплаты")
    comment: Optional[str] = Field(None, max_length=500, description="Комментарий")
    invited_by_user_id: Optional[int] = Field(None, description="Кто пригласил")


class CreateOrderResponse(BaseModel):
    success: bool
    order_id: Optional[int] = None
    payment_url: Optional[str] = None
    message: str


class OrderListItem(BaseModel):
    id: int
    status: OrderStatus
    status_text: str
    product_id: int
    product_name: str
    product_image: Optional[str] = None
    final_price: Decimal
    delivery_cost: Decimal
    total_amount: Decimal
    savings: Decimal
    delivery_type: DeliveryType
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    created_at: datetime


class OrderDetailResponse(BaseModel):
    id: int
    status: OrderStatus
    status_text: str
    status_history: List[dict] = []
    group_id: int
    group_status: str
    participants_count: int
    product_id: int
    product_name: str
    product_description: Optional[str] = None
    product_image: Optional[str] = None
    base_price: Decimal
    final_price: Decimal
    delivery_cost: Decimal
    total_amount: Decimal
    savings: Decimal
    savings_percent: float
    delivery_type: DeliveryType
    delivery_type_text: str
    tracking_number: Optional[str] = None
    delivery_service: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    address_id: int
    address_text: str
    payment_status: Optional[PaymentStatus] = None
    payment_method: Optional[PaymentMethod] = None
    created_at: datetime
    comment: Optional[str] = None
    can_cancel: bool = False
    can_return: bool = False


class OrderListResponse(BaseModel):
    items: List[OrderListItem]
    total: int


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_status_text(status: OrderStatus) -> str:
    status_texts = {
        OrderStatus.PENDING: "Ожидает оплаты",
        OrderStatus.FROZEN: "Оплата заморожена",
        OrderStatus.PAID: "Оплачен",
        OrderStatus.PROCESSING: "Обрабатывается",
        OrderStatus.SHIPPED: "Отправлен",
        OrderStatus.DELIVERED: "Доставлен",
        OrderStatus.CANCELLED: "Отменён",
        OrderStatus.REFUNDED: "Возвращён"
    }
    return status_texts.get(status, str(status))


def get_delivery_type_text(delivery_type: DeliveryType) -> str:
    texts = {
        DeliveryType.COURIER: "Курьером",
        DeliveryType.PICKUP: "Пункт выдачи",
        DeliveryType.POST: "Почта России"
    }
    return texts.get(delivery_type, str(delivery_type))


def calculate_delivery_cost(delivery_type: DeliveryType, city: str = None) -> Decimal:
    costs = {
        DeliveryType.COURIER: Decimal("490"),
        DeliveryType.PICKUP: Decimal("290"),
        DeliveryType.POST: Decimal("350")
    }
    return costs.get(delivery_type, Decimal("290"))


def format_address(address_data: dict) -> str:
    parts = [address_data.get("city", "")]
    if address_data.get("street"):
        parts.append(address_data["street"])
    if address_data.get("building"):
        parts.append(f"д. {address_data['building']}")
    if address_data.get("apartment"):
        parts.append(f"кв. {address_data['apartment']}")
    return ", ".join(filter(None, parts))


# ============================================================
# ЭНДПОИНТЫ: СПИСОК ЗАКАЗОВ
# ============================================================

@router.get("", response_model=OrderListResponse, summary="Мои заказы")
async def get_my_orders(
    status_filter: str = Query("all", alias="status", regex="^(active|completed|cancelled|all)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user_id: int = Depends(get_current_user)
):
    db = get_db()
    query = (
        db.table("orders")
        .select("*, groups(product_id, products(id, name, image_url, base_price))")
        .eq("user_id", user_id)
    )
    if status_filter == "active":
        query = query.in_("status", ["pending", "frozen", "paid", "processing", "shipped"])
    elif status_filter == "completed":
        query = query.eq("status", "delivered")
    elif status_filter == "cancelled":
        query = query.in_("status", ["cancelled", "refunded"])

    query = query.order("created_at", desc=True)
    offset = (page - 1) * per_page
    query = query.range(offset, offset + per_page - 1)
    result = query.execute()

    items = []
    for order_data in (result.data or []):
        group_data = order_data.get("groups", {})
        product_data = group_data.get("products", {})
        base_price = Decimal(str(product_data.get("base_price", 0)))
        final_price = Decimal(str(order_data.get("final_price", 0)))
        savings = base_price - final_price
        items.append(OrderListItem(
            id=order_data["id"],
            status=OrderStatus(order_data.get("status", "pending")),
            status_text=get_status_text(OrderStatus(order_data.get("status", "pending"))),
            product_id=product_data.get("id", 0),
            product_name=product_data.get("name", ""),
            product_image=product_data.get("image_url"),
            final_price=final_price,
            delivery_cost=Decimal(str(order_data.get("delivery_cost", 0))),
            total_amount=Decimal(str(order_data.get("total_amount", 0))),
            savings=savings,
            delivery_type=DeliveryType(order_data.get("delivery_type", "pickup")),
            tracking_number=order_data.get("tracking_number"),
            estimated_delivery=order_data.get("estimated_delivery"),
            created_at=order_data.get("created_at")
        ))

    count_query = db.table("orders").select("id", count="exact").eq("user_id", user_id)
    if status_filter == "active":
        count_query = count_query.in_("status", ["pending", "frozen", "paid", "processing", "shipped"])
    elif status_filter == "completed":
        count_query = count_query.eq("status", "delivered")
    elif status_filter == "cancelled":
        count_query = count_query.in_("status", ["cancelled", "refunded"])
    count_result = count_query.execute()

    return OrderListResponse(items=items, total=count_result.count or 0)


# ============================================================
# ЭНДПОИНТЫ: ДЕТАЛИ ЗАКАЗА
# ============================================================

@router.get("/{order_id}", response_model=OrderDetailResponse, summary="Детали заказа")
async def get_order_detail(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    db = get_db()
    result = (
        db.table("orders")
        .select("*, addresses(*), groups(*, products(id, name, description, image_url, base_price)), payments(status, method)")
        .eq("id", order_id).eq("user_id", user_id).limit(1).execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")

    order_data = result.data[0]
    group_data = order_data.get("groups", {})
    product_data = group_data.get("products", {})
    address_data = order_data.get("addresses", {})
    payment_data = order_data.get("payments", [{}])[0] if order_data.get("payments") else {}

    base_price = Decimal(str(product_data.get("base_price", 0)))
    final_price = Decimal(str(order_data.get("final_price", 0)))
    savings = base_price - final_price
    savings_percent = float((savings / base_price) * 100) if base_price > 0 else 0
    order_status = OrderStatus(order_data.get("status", "pending"))
    can_cancel = order_status in [OrderStatus.PENDING, OrderStatus.FROZEN]
    can_return = order_status == OrderStatus.DELIVERED

    return OrderDetailResponse(
        id=order_data["id"], status=order_status,
        status_text=get_status_text(order_status),
        status_history=order_data.get("status_history", []),
        group_id=order_data.get("group_id", 0),
        group_status=group_data.get("status", ""),
        participants_count=group_data.get("current_count", 0),
        product_id=product_data.get("id", 0),
        product_name=product_data.get("name", ""),
        product_description=product_data.get("description"),
        product_image=product_data.get("image_url"),
        base_price=base_price, final_price=final_price,
        delivery_cost=Decimal(str(order_data.get("delivery_cost", 0))),
        total_amount=Decimal(str(order_data.get("total_amount", 0))),
        savings=savings, savings_percent=round(savings_percent, 1),
        delivery_type=DeliveryType(order_data.get("delivery_type", "pickup")),
        delivery_type_text=get_delivery_type_text(DeliveryType(order_data.get("delivery_type", "pickup"))),
        tracking_number=order_data.get("tracking_number"),
        delivery_service=order_data.get("delivery_service"),
        estimated_delivery=order_data.get("estimated_delivery"),
        delivered_at=order_data.get("delivered_at"),
        address_id=order_data.get("address_id", 0),
        address_text=format_address(address_data),
        payment_status=PaymentStatus(payment_data.get("status")) if payment_data.get("status") else None,
        payment_method=PaymentMethod(payment_data.get("method")) if payment_data.get("method") else None,
        created_at=order_data.get("created_at"),
        comment=order_data.get("comment"),
        can_cancel=can_cancel, can_return=can_return
    )


# ============================================================
# ЭНДПОИНТЫ: СОЗДАНИЕ ЗАКАЗА
# ============================================================

@router.post(
    "",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать заказ",
)
@limiter.limit(create_limit)
async def create_order(
    request: Request,
    body: CreateOrderRequest,
    user_id: int = Depends(get_current_user)
):
    db = get_db()
    group_manager = get_group_manager()
    payment_service = get_payment_service()

    # 1. Проверяем сбор
    group = (
        db.table("groups")
        .select("*, products(id, name, base_price, price_tiers)")
        .eq("id", body.group_id).limit(1).execute()
    )
    if not group.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сбор не найден")

    group_data = group.data[0]
    if group_data["status"] != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сбор недоступен для присоединения")

    # 2. Проверяем дубль заказа
    existing_order = (
        db.table("orders").select("id, status")
        .eq("group_id", body.group_id).eq("user_id", user_id)
        .neq("status", "cancelled").limit(1).execute()
    )
    if existing_order.data:
        existing = existing_order.data[0]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"У вас уже есть заказ #{existing['id']} на этот сбор")

    # 3. Проверяем адрес
    address = db.table("addresses").select("*").eq("id", body.address_id).eq("user_id", user_id).limit(1).execute()
    if not address.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Адрес не найден")
    address_data = address.data[0]

    # 4. Рассчитываем цену
    product_data = group_data.get("products", {})
    price_tiers = product_data.get("price_tiers", [])
    base_price = Decimal(str(product_data.get("base_price", 0)))
    current_count = group_data.get("current_count", 0)

    is_already_member = (
        db.table("group_members").select("id")
        .eq("group_id", body.group_id).eq("user_id", user_id).limit(1).execute()
    )
    if is_already_member.data:
        final_price = calculate_current_price(price_tiers, current_count, base_price)
    else:
        final_price = calculate_current_price(price_tiers, current_count + 1, base_price)
        db.table("group_members").insert({
            "group_id": body.group_id, "user_id": user_id,
            "joined_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        # НЕ обновляем current_count вручную!
        # Триггер БД на group_members автоматически делает +1.
        # Если обновлять И здесь, И триггером — будет двойной счёт.

    delivery_cost = calculate_delivery_cost(body.delivery_type, address_data.get("city"))
    total_amount = final_price + delivery_cost

    # 5. Создаём заказ
    order_data = {
        "user_id": user_id, "group_id": body.group_id, "address_id": body.address_id,
        "final_price": float(final_price), "delivery_cost": float(delivery_cost),
        "total_amount": float(total_amount), "status": "pending",
        "delivery_type": body.delivery_type.value, "comment": body.comment,
        "status_history": [{"status": "pending", "timestamp": datetime.now(timezone.utc).isoformat(), "comment": "Заказ создан"}]
    }
    order_result = db.table("orders").insert(order_data).execute()
    if not order_result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось создать заказ")
    order_id = order_result.data[0]["id"]

    # 6. Создаём платёж
    product_name = product_data.get("name", "Товар")
    description = f"Групповая покупка: {product_name}"
    return_url = f"{settings.TELEGRAM_WEBAPP_URL}?order={order_id}"
    user_data = db.table("users").select("phone").eq("id", user_id).limit(1).execute()
    user_phone = user_data.data[0].get("phone") if user_data.data else None

    receipt_items = [{"name": product_name[:128], "quantity": 1, "price": str(final_price)}]
    if delivery_cost > 0:
        receipt_items.append({"name": "Доставка СДЭК", "quantity": 1, "price": str(delivery_cost)})

    payment_result = await payment_service.create_payment(
        amount=total_amount, order_id=order_id, description=description,
        return_url=return_url, user_phone=user_phone, items=receipt_items
    )
    if not payment_result.success:
        db.table("orders").delete().eq("id", order_id).execute()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=payment_result.error or "Ошибка создания платежа")

    # 7. Сохраняем invited_by
    if body.invited_by_user_id:
        db.table("orders").update({
            "comment": f"{body.comment or ''}\n[ref:{body.invited_by_user_id}]".strip()
        }).eq("id", order_id).execute()

    return CreateOrderResponse(
        success=True, order_id=order_id,
        payment_url=payment_result.confirmation_url,
        message="Перейдите по ссылке для оплаты"
    )


# ============================================================
# ПОВТОРНАЯ ОПЛАТА
# ============================================================
# Аналогия: ты подошёл к кассе самообслуживания, отсканировал товары,
# но ушёл не оплатив. Эндпоинт — это кнопка «Вернуться к кассе»:
# создаёт новую платёжную ссылку для того же заказа.

@router.post(
    "/{order_id}/retry-payment",
    response_model=CreateOrderResponse,
    summary="Повторить оплату",
    description="Создать новую ссылку на оплату для заказа в статусе pending."
)
async def retry_payment(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    db = get_db()
    payment_service = get_payment_service()

    # Получаем заказ
    result = (
        db.table("orders")
        .select("*, groups(product_id, products(id, name))")
        .eq("id", order_id).eq("user_id", user_id).limit(1).execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")

    order_data = result.data[0]

    # Только pending можно оплатить повторно
    if order_data["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Повторная оплата доступна только для заказов в ожидании"
        )

    total_amount = Decimal(str(order_data.get("total_amount", 0)))
    final_price = Decimal(str(order_data.get("final_price", 0)))
    delivery_cost = Decimal(str(order_data.get("delivery_cost", 0)))

    product_data = order_data.get("groups", {}).get("products", {})
    product_name = product_data.get("name", "Товар")
    description = f"Групповая покупка: {product_name}"
    return_url = f"{settings.TELEGRAM_WEBAPP_URL}?order={order_id}"

    # Телефон для чека (54-ФЗ)
    user_data = db.table("users").select("phone").eq("id", user_id).limit(1).execute()
    user_phone = user_data.data[0].get("phone") if user_data.data else None

    receipt_items = [{"name": product_name[:128], "quantity": 1, "price": str(final_price)}]
    if delivery_cost > 0:
        receipt_items.append({"name": "Доставка СДЭК", "quantity": 1, "price": str(delivery_cost)})

    payment_result = await payment_service.create_payment(
        amount=total_amount, order_id=order_id, description=description,
        return_url=return_url, user_phone=user_phone, items=receipt_items
    )

    if not payment_result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=payment_result.error or "Ошибка создания платежа"
        )

    return CreateOrderResponse(
        success=True, order_id=order_id,
        payment_url=payment_result.confirmation_url,
        message="Перейдите по ссылке для оплаты"
    )

# ============================================================
# ОТМЕНА ЗАКАЗА (Спринт 2 — антифрод-проверка)
# ============================================================

@router.post(
    "/{order_id}/cancel",
    summary="Отменить заказ",
    description="""
    Отменить заказ.
    
    **Доступно только для статусов:**
    - PENDING — просто отменяем
    - FROZEN — отменяем и размораживаем деньги
    
    **Антифрод (Спринт 2):**
    После отмены проверяем, не стал ли пользователь подозрительным
    (3+ отмен подряд → is_suspicious = true).
    """
)
async def cancel_order(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    db = get_db()
    payment_service = get_payment_service()

    # Получаем заказ
    result = (
        db.table("orders")
        .select("*, payments(external_id, status)")
        .eq("id", order_id).eq("user_id", user_id).limit(1).execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")

    order_data = result.data[0]
    order_status = order_data.get("status")

    if order_status not in ["pending", "frozen"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Этот заказ нельзя отменить")

    # Если есть замороженный платёж — отменяем его
    payments = order_data.get("payments", [])
    if payments:
        for payment in payments:
            if payment.get("status") == "frozen" and payment.get("external_id"):
                await payment_service.cancel_payment(payment["external_id"])

    # Обновляем статус заказа
    status_history = order_data.get("status_history", [])
    status_history.append({
        "status": "cancelled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "comment": "Отменён пользователем"
    })

    db.table("orders").update({
        "status": "cancelled",
        "status_history": status_history
    }).eq("id", order_id).execute()

    # ============================================================
    # АНТИФРОД-ПРОВЕРКА (Спринт 2)
    # ============================================================
    # После отмены проверяем: не стал ли пользователь подозрительным?
    # Если 3+ отмен подряд → помечаем is_suspicious = true.
    #
    # Аналогия: человек 3 раза подряд бронирует столик и не приходит →
    # ресторан берёт его на заметку.
    #
    # try/except чтобы ошибка антифрода не сломала отмену заказа.
    try:
        from antifraud import check_user_suspicious
        await check_user_suspicious(user_id)
    except Exception as e:
        print(f"[Antifraud] Ошибка проверки при отмене заказа: {e}")

    return {"success": True, "message": "Заказ отменён"}


# ============================================================
# ЭНДПОИНТЫ: ОТСЛЕЖИВАНИЕ
# ============================================================

@router.get("/{order_id}/tracking", summary="Отслеживание доставки")
async def get_order_tracking(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    db = get_db()
    result = (
        db.table("orders")
        .select("status, tracking_number, delivery_service, estimated_delivery, delivered_at")
        .eq("id", order_id).eq("user_id", user_id).limit(1).execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")

    order_data = result.data[0]
    if not order_data.get("tracking_number"):
        return {
            "status": "pending", "message": "Заказ ещё не отправлен",
            "tracking_number": None, "tracking_url": None, "events": []
        }

    tracking_url = None
    if order_data.get("delivery_service") == "cdek":
        tracking_url = f"https://www.cdek.ru/ru/tracking?order_id={order_data['tracking_number']}"

    return {
        "status": order_data.get("status"),
        "tracking_number": order_data.get("tracking_number"),
        "delivery_service": order_data.get("delivery_service"),
        "tracking_url": tracking_url,
        "estimated_delivery": order_data.get("estimated_delivery"),
        "delivered_at": order_data.get("delivered_at"),
        "events": []
    }
