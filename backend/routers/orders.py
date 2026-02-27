"""
Модуль: routers/orders.py
Описание: API эндпоинты для работы с заказами
Проект: GroupBuy Mini App

Заказ создаётся когда пользователь присоединяется к сбору и оплачивает.

Жизненный цикл заказа:
    PENDING → FROZEN → PAID → PROCESSING → SHIPPED → DELIVERED
                 ↓
             REFUNDED (если сбор не состоялся)

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

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    """
    Запрос на создание заказа.
    
    Создаёт заказ + присоединяет к сбору + инициирует оплату.
    """
    group_id: int = Field(..., description="ID сбора")
    address_id: int = Field(..., description="ID адреса доставки")
    delivery_type: DeliveryType = Field(
        default=DeliveryType.PICKUP,
        description="Тип доставки"
    )
    payment_method: PaymentMethod = Field(
        default=PaymentMethod.CARD,
        description="Способ оплаты"
    )
    comment: Optional[str] = Field(None, max_length=500, description="Комментарий")
    
    # Реферальная информация
    invited_by_user_id: Optional[int] = Field(None, description="Кто пригласил")


class CreateOrderResponse(BaseModel):
    """Ответ при создании заказа."""
    success: bool
    order_id: Optional[int] = None
    payment_url: Optional[str] = None  # URL для оплаты
    message: str


class OrderListItem(BaseModel):
    """Заказ в списке."""
    id: int
    status: OrderStatus
    status_text: str
    
    # Товар
    product_id: int
    product_name: str
    product_image: Optional[str] = None
    
    # Цены
    final_price: Decimal
    delivery_cost: Decimal
    total_amount: Decimal
    savings: Decimal
    
    # Доставка
    delivery_type: DeliveryType
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    
    # Даты
    created_at: datetime


class OrderDetailResponse(BaseModel):
    """Детальная информация о заказе."""
    id: int
    status: OrderStatus
    status_text: str
    status_history: List[dict] = []
    
    # Сбор
    group_id: int
    group_status: str
    participants_count: int
    
    # Товар
    product_id: int
    product_name: str
    product_description: Optional[str] = None
    product_image: Optional[str] = None
    
    # Цены
    base_price: Decimal
    final_price: Decimal
    delivery_cost: Decimal
    total_amount: Decimal
    savings: Decimal
    savings_percent: float
    
    # Доставка
    delivery_type: DeliveryType
    delivery_type_text: str
    tracking_number: Optional[str] = None
    delivery_service: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    
    # Адрес
    address_id: int
    address_text: str
    
    # Оплата
    payment_status: Optional[PaymentStatus] = None
    payment_method: Optional[PaymentMethod] = None
    
    # Даты
    created_at: datetime
    comment: Optional[str] = None
    
    # Действия
    can_cancel: bool = False
    can_return: bool = False


class OrderListResponse(BaseModel):
    """Ответ со списком заказов."""
    items: List[OrderListItem]
    total: int


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_status_text(status: OrderStatus) -> str:
    """Получить текст статуса на русском."""
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
    """Получить текст типа доставки."""
    texts = {
        DeliveryType.COURIER: "Курьером",
        DeliveryType.PICKUP: "Пункт выдачи",
        DeliveryType.POST: "Почта России"
    }
    return texts.get(delivery_type, str(delivery_type))


def calculate_delivery_cost(delivery_type: DeliveryType, city: str = None) -> Decimal:
    """
    Рассчитать стоимость доставки.
    
    TODO: Интеграция с СДЭК API для реального расчёта.
    """
    # Пока фиксированные цены
    costs = {
        DeliveryType.COURIER: Decimal("490"),
        DeliveryType.PICKUP: Decimal("290"),
        DeliveryType.POST: Decimal("350")
    }
    return costs.get(delivery_type, Decimal("290"))


def format_address(address_data: dict) -> str:
    """Форматировать адрес в строку."""
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

@router.get(
    "",
    response_model=OrderListResponse,
    summary="Мои заказы",
    description="""
    Возвращает список заказов текущего пользователя.
    
    **Фильтры:**
    - `status` — фильтр по статусу (active/completed/all)
    """
)
async def get_my_orders(
    status_filter: str = Query(
        "all",
        alias="status",
        regex="^(active|completed|cancelled|all)$",
        description="Фильтр по статусу"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user_id: int = Depends(get_current_user)
):
    """
    Получить список моих заказов.
    """
    db = get_db()
    
    # Базовый запрос
    query = (
        db.table("orders")
        .select(
            "*, "
            "groups(product_id, products(id, name, image_url, base_price))"
        )
        .eq("user_id", user_id)
    )
    
    # Фильтр по статусу
    if status_filter == "active":
        query = query.in_("status", ["pending", "frozen", "paid", "processing", "shipped"])
    elif status_filter == "completed":
        query = query.eq("status", "delivered")
    elif status_filter == "cancelled":
        query = query.in_("status", ["cancelled", "refunded"])
    
    # Сортировка и пагинация
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
    
    # Подсчёт общего количества
    count_query = (
        db.table("orders")
        .select("id", count="exact")
        .eq("user_id", user_id)
    )
    
    if status_filter == "active":
        count_query = count_query.in_("status", ["pending", "frozen", "paid", "processing", "shipped"])
    elif status_filter == "completed":
        count_query = count_query.eq("status", "delivered")
    elif status_filter == "cancelled":
        count_query = count_query.in_("status", ["cancelled", "refunded"])
    
    count_result = count_query.execute()
    
    return OrderListResponse(
        items=items,
        total=count_result.count or 0
    )


# ============================================================
# ЭНДПОИНТЫ: ДЕТАЛИ ЗАКАЗА
# ============================================================

@router.get(
    "/{order_id}",
    response_model=OrderDetailResponse,
    summary="Детали заказа",
    description="Полная информация о заказе."
)
async def get_order_detail(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Получить детальную информацию о заказе.
    """
    db = get_db()
    
    # Получаем заказ
    result = (
        db.table("orders")
        .select(
            "*, "
            "addresses(*), "
            "groups(*, products(id, name, description, image_url, base_price)), "
            "payments(status, method)"
        )
        .eq("id", order_id)
        .eq("user_id", user_id)  # Проверяем владельца
        .limit(1)
        .execute()
    )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Заказ не найден"
        )
    
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
    
    # Определяем доступные действия
    can_cancel = order_status in [OrderStatus.PENDING, OrderStatus.FROZEN]
    can_return = order_status == OrderStatus.DELIVERED
    
    return OrderDetailResponse(
        id=order_data["id"],
        status=order_status,
        status_text=get_status_text(order_status),
        status_history=order_data.get("status_history", []),
        
        group_id=order_data.get("group_id", 0),
        group_status=group_data.get("status", ""),
        participants_count=group_data.get("current_count", 0),
        
        product_id=product_data.get("id", 0),
        product_name=product_data.get("name", ""),
        product_description=product_data.get("description"),
        product_image=product_data.get("image_url"),
        
        base_price=base_price,
        final_price=final_price,
        delivery_cost=Decimal(str(order_data.get("delivery_cost", 0))),
        total_amount=Decimal(str(order_data.get("total_amount", 0))),
        savings=savings,
        savings_percent=round(savings_percent, 1),
        
        delivery_type=DeliveryType(order_data.get("delivery_type", "pickup")),
        delivery_type_text=get_delivery_type_text(
            DeliveryType(order_data.get("delivery_type", "pickup"))
        ),
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
        
        can_cancel=can_cancel,
        can_return=can_return
    )


# ============================================================
# ЭНДПОИНТЫ: СОЗДАНИЕ ЗАКАЗА
# ============================================================

@router.post(
    "",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать заказ",
    description="""
    Создать заказ и инициировать оплату.
    
    **Процесс:**
    1. Проверяем сбор и адрес
    2. Рассчитываем цену
    3. Создаём заказ в статусе PENDING
    4. Создаём платёж в ЮKassa
    5. Возвращаем URL для оплаты
    
    После оплаты пользователь автоматически присоединяется к сбору.
    """
)
async def create_order(
    request: CreateOrderRequest,
    user_id: int = Depends(get_current_user)
):
    """
    Создать заказ.
    """
    db = get_db()
    group_manager = get_group_manager()
    payment_service = get_payment_service()
    
    # 1. Проверяем сбор
    group = (
        db.table("groups")
        .select("*, products(id, name, base_price, price_tiers)")
        .eq("id", request.group_id)
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
            detail="Сбор недоступен для присоединения"
        )
    
    # 2. Проверяем, нет ли уже активного заказа на этот сбор
    # 
    # Почему проверяем orders, а НЕ group_members?
    # 
    # Наглядно — поток пользователя:
    #   1. На странице сбора нажал «Присоединиться» → join() добавил в group_members
    #   2. Теперь нажал «Оформить» → create_order() создаёт заказ и платёж
    # 
    # Если проверять group_members — пользователь никогда не сможет оплатить,
    # потому что он УЖЕ член группы после шага 1.
    # 
    # Правильно: проверять, нет ли уже ЗАКАЗА (чтобы не создать дубль).
    existing_order = (
        db.table("orders")
        .select("id, status")
        .eq("group_id", request.group_id)
        .eq("user_id", user_id)
        .neq("status", "cancelled")
        .limit(1)
        .execute()
    )
    
    if existing_order.data:
        existing = existing_order.data[0]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"У вас уже есть заказ #{existing['id']} на этот сбор"
        )
    
    # 3. Проверяем адрес
    address = (
        db.table("addresses")
        .select("*")
        .eq("id", request.address_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    
    if not address.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Адрес не найден"
        )
    
    address_data = address.data[0]
    
    # 4. Рассчитываем цену
    product_data = group_data.get("products", {})
    price_tiers = product_data.get("price_tiers", [])
    base_price = Decimal(str(product_data.get("base_price", 0)))
    current_count = group_data.get("current_count", 0)
    
    # Проверяем, является ли пользователь уже участником сбора
    # 
    # Наглядно — два сценария:
    #   A) Пользователь уже нажал «Присоединиться» → он В group_members
    #      → current_count уже ВКЛЮЧАЕТ его → цена по current_count
    #   B) Пользователь пришёл напрямую (без join) → его НЕТ в group_members
    #      → нужно добавить → цена по current_count + 1
    #
    is_already_member = (
        db.table("group_members")
        .select("id")
        .eq("group_id", request.group_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    
    if is_already_member.data:
        # Уже участник — цена по текущему количеству
        final_price = calculate_current_price(price_tiers, current_count, base_price)
    else:
        # Не участник — добавляем в сбор + цена с учётом нового участника
        final_price = calculate_current_price(price_tiers, current_count + 1, base_price)
        db.table("group_members").insert({
            "group_id": request.group_id,
            "user_id": user_id,
            "joined_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        # Обновляем счётчик
        db.table("groups").update({
            "current_count": current_count + 1
        }).eq("id", request.group_id).execute()
    
    delivery_cost = calculate_delivery_cost(request.delivery_type, address_data.get("city"))
    total_amount = final_price + delivery_cost
    
    # 5. Создаём заказ
    order_data = {
        "user_id": user_id,
        "group_id": request.group_id,
        "address_id": request.address_id,
        "final_price": float(final_price),
        "delivery_cost": float(delivery_cost),
        "total_amount": float(total_amount),
        "status": "pending",
        "delivery_type": request.delivery_type.value,
        "comment": request.comment,
        "status_history": [{
            "status": "pending",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "comment": "Заказ создан"
        }]
    }
    
    order_result = db.table("orders").insert(order_data).execute()
    
    if not order_result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось создать заказ"
        )
    
    order_id = order_result.data[0]["id"]
    
    # 6. Создаём платёж
    product_name = product_data.get("name", "Товар")
    description = f"Групповая покупка: {product_name}"
    
    # URL возврата после оплаты
    return_url = f"{settings.TELEGRAM_WEBAPP_URL}?order={order_id}"
    
    payment_result = await payment_service.create_payment(
        amount=total_amount,
        order_id=order_id,
        description=description,
        return_url=return_url
    )
    
    if not payment_result.success:
        # Удаляем заказ если платёж не создался
        db.table("orders").delete().eq("id", order_id).execute()
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=payment_result.error or "Ошибка создания платежа"
        )
    
    # 7. Сохраняем invited_by для будущего присоединения
    if request.invited_by_user_id:
        db.table("orders").update({
            "comment": f"{request.comment or ''}\n[ref:{request.invited_by_user_id}]".strip()
        }).eq("id", order_id).execute()
    
    return CreateOrderResponse(
        success=True,
        order_id=order_id,
        payment_url=payment_result.confirmation_url,
        message="Перейдите по ссылке для оплаты"
    )


# ============================================================
# ЭНДПОИНТЫ: ОТМЕНА ЗАКАЗА
# ============================================================

@router.post(
    "/{order_id}/cancel",
    summary="Отменить заказ",
    description="""
    Отменить заказ.
    
    **Доступно только для статусов:**
    - PENDING — просто отменяем
    - FROZEN — отменяем и размораживаем деньги
    """
)
async def cancel_order(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Отменить заказ.
    """
    db = get_db()
    payment_service = get_payment_service()
    
    # Получаем заказ
    result = (
        db.table("orders")
        .select("*, payments(external_id, status)")
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
    order_status = order_data.get("status")
    
    if order_status not in ["pending", "frozen"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот заказ нельзя отменить"
        )
    
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
    
    return {
        "success": True,
        "message": "Заказ отменён"
    }


# ============================================================
# ЭНДПОИНТЫ: ОТСЛЕЖИВАНИЕ
# ============================================================

@router.get(
    "/{order_id}/tracking",
    summary="Отслеживание доставки",
    description="Получить информацию о доставке заказа."
)
async def get_order_tracking(
    order_id: int,
    user_id: int = Depends(get_current_user)
):
    """
    Получить информацию о доставке.
    """
    db = get_db()
    
    # Получаем заказ
    result = (
        db.table("orders")
        .select("status, tracking_number, delivery_service, estimated_delivery, delivered_at")
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
    
    if not order_data.get("tracking_number"):
        return {
            "status": "pending",
            "message": "Заказ ещё не отправлен",
            "tracking_number": None,
            "tracking_url": None,
            "events": []
        }
    
    # TODO: Интеграция с СДЭК API для получения статуса
    # Пока возвращаем базовую информацию
    
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
        "events": []  # TODO: Заполнять из СДЭК API
    }
