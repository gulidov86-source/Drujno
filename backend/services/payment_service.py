"""
Модуль: services/payment_service.py
Описание: Интеграция с платёжной системой ЮKassa
Проект: GroupBuy Mini App

ЮKassa (ex. Яндекс.Касса) — платёжный провайдер для приёма платежей.

Особенность нашей интеграции:
- Используем двухэтапную оплату (холдирование)
- Деньги сначала замораживаются, потом списываются
- Если сбор не состоялся — возвращаем автоматически

Документация ЮKassa:
    https://yookassa.ru/developers/api

Использование:
    from services.payment_service import PaymentService
    
    service = PaymentService()
    
    # Создать платёж
    payment = await service.create_payment(
        amount=19000,
        order_id=42,
        description="Групповая покупка: AirPods Pro",
        return_url="https://t.me/bot/app"
    )
    
    # Списать замороженные средства
    await service.capture_payment(payment_id="...")
    
    # Вернуть средства
    await service.refund_payment(payment_id="...", amount=19000)
"""

import uuid
import hashlib
import hmac
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel
import httpx

import sys
sys.path.append("..")
from config import settings
from database.connection import get_db


# ============================================================
# МОДЕЛИ
# ============================================================

class PaymentAmount(BaseModel):
    """Сумма платежа."""
    value: str  # "19000.00"
    currency: str = "RUB"


class PaymentConfirmation(BaseModel):
    """Данные для подтверждения платежа."""
    type: str  # "redirect"
    confirmation_url: Optional[str] = None  # URL для редиректа


class PaymentRecipient(BaseModel):
    """Получатель платежа."""
    gateway_id: Optional[str] = None
    account_id: Optional[str] = None


class YooKassaPayment(BaseModel):
    """
    Платёж ЮKassa.
    
    Структура ответа от API.
    """
    id: str
    status: str  # pending, waiting_for_capture, succeeded, canceled
    amount: PaymentAmount
    description: Optional[str] = None
    confirmation: Optional[PaymentConfirmation] = None
    paid: bool = False
    captured_at: Optional[str] = None
    created_at: str
    metadata: Optional[Dict[str, Any]] = None
    
    @property
    def is_waiting_for_capture(self) -> bool:
        """Ожидает подтверждения списания (холд)."""
        return self.status == "waiting_for_capture"
    
    @property
    def is_succeeded(self) -> bool:
        """Успешно завершён."""
        return self.status == "succeeded"
    
    @property
    def is_canceled(self) -> bool:
        """Отменён."""
        return self.status == "canceled"


class PaymentCreateResult(BaseModel):
    """Результат создания платежа."""
    success: bool
    payment_id: Optional[str] = None
    confirmation_url: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None


class PaymentCaptureResult(BaseModel):
    """Результат списания средств."""
    success: bool
    payment_id: str
    status: str
    amount: Decimal
    error: Optional[str] = None


class RefundResult(BaseModel):
    """Результат возврата."""
    success: bool
    refund_id: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[Decimal] = None
    error: Optional[str] = None


# ============================================================
# СЕРВИС ПЛАТЕЖЕЙ
# ============================================================

class PaymentService:
    """
    Сервис для работы с платежами через ЮKassa.
    
    Пример:
        service = PaymentService()
        
        # Создаём платёж с холдированием
        result = await service.create_payment(
            amount=Decimal("19000"),
            order_id=42,
            description="AirPods Pro"
        )
        
        if result.success:
            # Перенаправляем пользователя на оплату
            redirect_url = result.confirmation_url
    """
    
    # URL API ЮKassa
    API_URL = "https://api.yookassa.ru/v3"
    
    def __init__(self):
        """Инициализация сервиса."""
        self.shop_id = settings.YOOKASSA_SHOP_ID
        self.secret_key = settings.YOOKASSA_SECRET_KEY
        self.db = get_db()
        
        # Проверяем наличие настроек
        if not self.shop_id or not self.secret_key:
            print("⚠️  PaymentService: YOOKASSA credentials не настроены")
    
    def _get_auth(self) -> tuple:
        """Получить данные авторизации для API."""
        return (self.shop_id, self.secret_key)
    
    def _get_headers(self, idempotence_key: str = None) -> dict:
        """
        Получить заголовки для запроса.
        
        Idempotence-Key нужен для защиты от дублирования запросов.
        """
        headers = {
            "Content-Type": "application/json"
        }
        
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key
        else:
            headers["Idempotence-Key"] = str(uuid.uuid4())
        
        return headers
    
    # ============================================================
    # СОЗДАНИЕ ПЛАТЕЖА
    # ============================================================
    
    async def create_payment(
        self,
        amount: Decimal,
        order_id: int,
        description: str,
        return_url: str = None,
        user_email: str = None,
        user_phone: str = None,
        save_payment_method: bool = False
    ) -> PaymentCreateResult:
        """
        Создать платёж в ЮKassa.
        
        Используем capture=False для двухэтапной оплаты:
        1. Деньги замораживаются на карте
        2. Потом списываем через capture_payment()
        
        Параметры:
            amount: Сумма платежа
            order_id: ID заказа в нашей системе
            description: Описание (покажется пользователю)
            return_url: Куда вернуть после оплаты
            user_email: Email для чека (опционально)
            user_phone: Телефон для чека (опционально)
            save_payment_method: Сохранить способ оплаты
        
        Возвращает:
            PaymentCreateResult: Результат с URL для оплаты
        
        Пример:
            result = await service.create_payment(
                amount=Decimal("19000"),
                order_id=42,
                description="Групповая покупка: AirPods Pro",
                return_url="https://t.me/MyBot/app?order=42"
            )
            
            if result.success:
                # Редирект пользователя
                print(f"Оплата: {result.confirmation_url}")
        """
        if not self.shop_id or not self.secret_key:
            return PaymentCreateResult(
                success=False,
                error="Платёжная система не настроена"
            )
        
        # Формируем запрос
        payment_data = {
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "capture": False,  # Двухэтапная оплата!
            "description": description,
            "metadata": {
                "order_id": str(order_id)
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url or settings.TELEGRAM_WEBAPP_URL
            }
        }
        
        # Данные для чека (54-ФЗ)
        if user_email or user_phone:
            payment_data["receipt"] = {
                "customer": {}
            }
            if user_email:
                payment_data["receipt"]["customer"]["email"] = user_email
            if user_phone:
                payment_data["receipt"]["customer"]["phone"] = user_phone
            
            # Позиции чека
            payment_data["receipt"]["items"] = [{
                "description": description[:128],  # Макс 128 символов
                "quantity": "1.00",
                "amount": {
                    "value": str(amount),
                    "currency": "RUB"
                },
                "vat_code": 1,  # НДС не облагается
                "payment_mode": "full_payment",
                "payment_subject": "commodity"
            }]
        
        if save_payment_method:
            payment_data["save_payment_method"] = True
        
        # Отправляем запрос
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.API_URL}/payments",
                    json=payment_data,
                    auth=self._get_auth(),
                    headers=self._get_headers()
                )
                
                if response.status_code in (200, 201):
                    data = response.json()
                    payment = YooKassaPayment(**data)
                    
                    # Сохраняем в БД
                    await self._save_payment_to_db(
                        external_id=payment.id,
                        order_id=order_id,
                        amount=amount,
                        status="pending"
                    )
                    
                    return PaymentCreateResult(
                        success=True,
                        payment_id=payment.id,
                        confirmation_url=payment.confirmation.confirmation_url if payment.confirmation else None,
                        status=payment.status
                    )
                else:
                    error_data = response.json()
                    error_msg = error_data.get("description", "Ошибка создания платежа")
                    
                    return PaymentCreateResult(
                        success=False,
                        error=error_msg
                    )
                    
        except Exception as e:
            return PaymentCreateResult(
                success=False,
                error=f"Ошибка соединения: {str(e)}"
            )
    
    # ============================================================
    # ПОДТВЕРЖДЕНИЕ ПЛАТЕЖА (СПИСАНИЕ)
    # ============================================================
    
    async def capture_payment(
        self,
        payment_id: str,
        amount: Decimal = None
    ) -> PaymentCaptureResult:
        """
        Подтвердить платёж и списать деньги.
        
        Вызывается когда сбор успешно завершён.
        
        Параметры:
            payment_id: ID платежа в ЮKassa
            amount: Сумма списания (можно меньше холда)
        
        Возвращает:
            PaymentCaptureResult: Результат списания
        
        Пример:
            # Сбор завершён — списываем деньги
            result = await service.capture_payment(
                payment_id="2b8e5c4d-...",
                amount=Decimal("16500")  # Финальная цена ниже!
            )
        """
        if not self.shop_id:
            return PaymentCaptureResult(
                success=False,
                payment_id=payment_id,
                status="error",
                amount=Decimal("0"),
                error="Платёжная система не настроена"
            )
        
        capture_data = {}
        if amount:
            capture_data["amount"] = {
                "value": str(amount),
                "currency": "RUB"
            }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.API_URL}/payments/{payment_id}/capture",
                    json=capture_data,
                    auth=self._get_auth(),
                    headers=self._get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    payment = YooKassaPayment(**data)
                    
                    # Обновляем статус в БД
                    await self._update_payment_status(
                        external_id=payment_id,
                        status="charged",
                        charged_at=datetime.now(timezone.utc)
                    )
                    
                    return PaymentCaptureResult(
                        success=True,
                        payment_id=payment.id,
                        status=payment.status,
                        amount=Decimal(payment.amount.value)
                    )
                else:
                    error_data = response.json()
                    return PaymentCaptureResult(
                        success=False,
                        payment_id=payment_id,
                        status="error",
                        amount=Decimal("0"),
                        error=error_data.get("description", "Ошибка списания")
                    )
                    
        except Exception as e:
            return PaymentCaptureResult(
                success=False,
                payment_id=payment_id,
                status="error",
                amount=Decimal("0"),
                error=str(e)
            )
    
    # ============================================================
    # ОТМЕНА ПЛАТЕЖА
    # ============================================================
    
    async def cancel_payment(self, payment_id: str) -> PaymentCaptureResult:
        """
        Отменить платёж (разморозить деньги).
        
        Вызывается когда сбор не состоялся.
        
        Параметры:
            payment_id: ID платежа в ЮKassa
        
        Пример:
            # Сбор не состоялся — возвращаем холд
            await service.cancel_payment(payment_id="2b8e5c4d-...")
        """
        if not self.shop_id:
            return PaymentCaptureResult(
                success=False,
                payment_id=payment_id,
                status="error",
                amount=Decimal("0"),
                error="Платёжная система не настроена"
            )
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.API_URL}/payments/{payment_id}/cancel",
                    json={},
                    auth=self._get_auth(),
                    headers=self._get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    payment = YooKassaPayment(**data)
                    
                    # Обновляем статус в БД
                    await self._update_payment_status(
                        external_id=payment_id,
                        status="cancelled"
                    )
                    
                    return PaymentCaptureResult(
                        success=True,
                        payment_id=payment.id,
                        status=payment.status,
                        amount=Decimal(payment.amount.value)
                    )
                else:
                    error_data = response.json()
                    return PaymentCaptureResult(
                        success=False,
                        payment_id=payment_id,
                        status="error",
                        amount=Decimal("0"),
                        error=error_data.get("description", "Ошибка отмены")
                    )
                    
        except Exception as e:
            return PaymentCaptureResult(
                success=False,
                payment_id=payment_id,
                status="error",
                amount=Decimal("0"),
                error=str(e)
            )
    
    # ============================================================
    # ВОЗВРАТ
    # ============================================================
    
    async def refund_payment(
        self,
        payment_id: str,
        amount: Decimal,
        description: str = "Возврат средств"
    ) -> RefundResult:
        """
        Создать возврат средств.
        
        Используется для возвратов после успешного заказа.
        
        Параметры:
            payment_id: ID оригинального платежа
            amount: Сумма возврата
            description: Причина возврата
        
        Пример:
            # Клиент вернул товар
            result = await service.refund_payment(
                payment_id="2b8e5c4d-...",
                amount=Decimal("16500"),
                description="Возврат товара"
            )
        """
        if not self.shop_id:
            return RefundResult(
                success=False,
                error="Платёжная система не настроена"
            )
        
        refund_data = {
            "payment_id": payment_id,
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "description": description
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.API_URL}/refunds",
                    json=refund_data,
                    auth=self._get_auth(),
                    headers=self._get_headers()
                )
                
                if response.status_code in (200, 201):
                    data = response.json()
                    
                    # Обновляем статус в БД
                    await self._update_payment_status(
                        external_id=payment_id,
                        status="refunded",
                        refunded_at=datetime.now(timezone.utc)
                    )
                    
                    return RefundResult(
                        success=True,
                        refund_id=data.get("id"),
                        status=data.get("status"),
                        amount=Decimal(data["amount"]["value"])
                    )
                else:
                    error_data = response.json()
                    return RefundResult(
                        success=False,
                        error=error_data.get("description", "Ошибка возврата")
                    )
                    
        except Exception as e:
            return RefundResult(
                success=False,
                error=str(e)
            )
    
    # ============================================================
    # ПОЛУЧЕНИЕ ИНФОРМАЦИИ О ПЛАТЕЖЕ
    # ============================================================
    
    async def get_payment(self, payment_id: str) -> Optional[YooKassaPayment]:
        """
        Получить информацию о платеже.
        
        Параметры:
            payment_id: ID платежа в ЮKassa
        
        Возвращает:
            YooKassaPayment | None: Данные платежа
        """
        if not self.shop_id:
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.API_URL}/payments/{payment_id}",
                    auth=self._get_auth()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return YooKassaPayment(**data)
                    
        except Exception:
            pass
        
        return None
    
    # ============================================================
    # WEBHOOK
    # ============================================================
    
    def verify_webhook_signature(
        self,
        body: bytes,
        signature: str
    ) -> bool:
        """
        Проверить подпись webhook от ЮKassa.
        
        Параметры:
            body: Тело запроса (bytes)
            signature: Значение заголовка Webhook-Signature
        
        Возвращает:
            bool: True если подпись верна
        """
        if not settings.YOOKASSA_WEBHOOK_SECRET:
            # Без секрета не можем проверить
            return True  # Для разработки
        
        expected = hmac.new(
            settings.YOOKASSA_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    async def handle_webhook(self, event_type: str, payment_data: dict) -> bool:
        """
        Обработать webhook от ЮKassa.
        
        Типы событий:
        - payment.waiting_for_capture: Деньги заморожены
        - payment.succeeded: Платёж успешен (после capture)
        - payment.canceled: Платёж отменён
        - refund.succeeded: Возврат успешен
        
        Параметры:
            event_type: Тип события
            payment_data: Данные платежа
        
        Возвращает:
            bool: Успешно ли обработано
        """
        payment_id = payment_data.get("id")
        status = payment_data.get("status")
        
        if event_type == "payment.waiting_for_capture":
            # Деньги заморожены — обновляем статус заказа
            await self._update_payment_status(
                external_id=payment_id,
                status="frozen",
                frozen_at=datetime.now(timezone.utc)
            )
            
            # Обновляем заказ
            order_id = payment_data.get("metadata", {}).get("order_id")
            if order_id:
                self.db.table("orders").update({
                    "status": "frozen"
                }).eq("id", int(order_id)).execute()
            
            return True
            
        elif event_type == "payment.succeeded":
            # Платёж успешен
            await self._update_payment_status(
                external_id=payment_id,
                status="charged",
                charged_at=datetime.now(timezone.utc)
            )
            
            order_id = payment_data.get("metadata", {}).get("order_id")
            if order_id:
                self.db.table("orders").update({
                    "status": "paid"
                }).eq("id", int(order_id)).execute()
            
            return True
            
        elif event_type == "payment.canceled":
            # Платёж отменён
            await self._update_payment_status(
                external_id=payment_id,
                status="cancelled"
            )
            
            order_id = payment_data.get("metadata", {}).get("order_id")
            if order_id:
                self.db.table("orders").update({
                    "status": "cancelled"
                }).eq("id", int(order_id)).execute()
            
            return True
        
        return False
    
    # ============================================================
    # РАБОТА С БД
    # ============================================================
    
    async def _save_payment_to_db(
        self,
        external_id: str,
        order_id: int,
        amount: Decimal,
        status: str
    ):
        """Сохранить платёж в БД."""
        self.db.table("payments").insert({
            "order_id": order_id,
            "amount": float(amount),
            "status": status,
            "method": "card",
            "external_id": external_id
        }).execute()
    
    async def _update_payment_status(
        self,
        external_id: str,
        status: str,
        frozen_at: datetime = None,
        charged_at: datetime = None,
        refunded_at: datetime = None
    ):
        """Обновить статус платежа в БД."""
        update_data = {"status": status}
        
        if frozen_at:
            update_data["frozen_at"] = frozen_at.isoformat()
        if charged_at:
            update_data["charged_at"] = charged_at.isoformat()
        if refunded_at:
            update_data["refunded_at"] = refunded_at.isoformat()
        
        self.db.table("payments").update(update_data).eq("external_id", external_id).execute()


# ============================================================
# СИНГЛТОН
# ============================================================

_payment_service: Optional[PaymentService] = None


def get_payment_service() -> PaymentService:
    """Получить экземпляр PaymentService."""
    global _payment_service
    if _payment_service is None:
        _payment_service = PaymentService()
    return _payment_service
