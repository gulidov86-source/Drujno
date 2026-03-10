"""
Тесты: Платёжный поток (webhook подпись, статусы)
Проект: GroupBuy Mini App

Запуск: pytest backend/tests/test_payments.py -v
"""

import pytest
import hmac
import hashlib

from services.payment_service import PaymentService
from routers.payments import get_payment_status_text
from database.models import PaymentStatus
from config import settings


# ============================================================
# ТЕСТЫ: ПОДПИСЬ WEBHOOK
# ============================================================

class TestWebhookSignature:
    """
    Тесты проверки подписи webhook от YooKassa.

    Аналогия: банк присылает перевод с печатью. Мы проверяем
    печать — настоящая или подделка. Без печати — не принимаем.
    """

    def _make_service(self):
        """Создать экземпляр PaymentService без вызова __init__ (без БД)."""
        return PaymentService.__new__(PaymentService)

    def test_valid_signature_accepted(self):
        """Валидная подпись — принимаем."""
        # Временно подставляем тестовый секрет
        old_secret = settings.YOOKASSA_WEBHOOK_SECRET
        settings.YOOKASSA_WEBHOOK_SECRET = "test-webhook-secret"

        try:
            body = b'{"event":"payment.succeeded","object":{"id":"123"}}'
            expected_sig = hmac.new(
                b"test-webhook-secret", body, hashlib.sha256
            ).hexdigest()

            service = self._make_service()
            assert service.verify_webhook_signature(body, expected_sig) is True
        finally:
            settings.YOOKASSA_WEBHOOK_SECRET = old_secret

    def test_invalid_signature_rejected(self):
        """Невалидная подпись — отклоняем."""
        old_secret = settings.YOOKASSA_WEBHOOK_SECRET
        settings.YOOKASSA_WEBHOOK_SECRET = "real-secret"

        try:
            service = self._make_service()
            body = b'{"event":"payment.succeeded"}'
            assert service.verify_webhook_signature(body, "fake-signature") is False
        finally:
            settings.YOOKASSA_WEBHOOK_SECRET = old_secret

    def test_empty_secret_rejects(self):
        """Без секрета — отклоняем (фикс Спринта 1)."""
        old_secret = settings.YOOKASSA_WEBHOOK_SECRET
        settings.YOOKASSA_WEBHOOK_SECRET = ""

        try:
            service = self._make_service()
            assert service.verify_webhook_signature(b"body", "any-sig") is False
        finally:
            settings.YOOKASSA_WEBHOOK_SECRET = old_secret

    def test_different_body_different_signature(self):
        """Разное тело запроса → разная подпись."""
        secret = b"test-secret"
        sig1 = hmac.new(secret, b"body1", hashlib.sha256).hexdigest()
        sig2 = hmac.new(secret, b"body2", hashlib.sha256).hexdigest()
        assert sig1 != sig2

    def test_tampered_body_rejected(self):
        """Подменённое тело → подпись не совпадёт."""
        old_secret = settings.YOOKASSA_WEBHOOK_SECRET
        settings.YOOKASSA_WEBHOOK_SECRET = "test-secret"

        try:
            original_body = b'{"amount":"1000","status":"succeeded"}'
            tampered_body = b'{"amount":"1","status":"succeeded"}'

            original_sig = hmac.new(
                b"test-secret", original_body, hashlib.sha256
            ).hexdigest()

            service = self._make_service()
            # Оригинальное тело + оригинальная подпись → OK
            assert service.verify_webhook_signature(original_body, original_sig) is True
            # Подменённое тело + оригинальная подпись → FAIL
            assert service.verify_webhook_signature(tampered_body, original_sig) is False
        finally:
            settings.YOOKASSA_WEBHOOK_SECRET = old_secret


# ============================================================
# ТЕСТЫ: СТАТУСЫ ПЛАТЕЖЕЙ
# ============================================================

class TestPaymentStatusText:
    """Тесты текстов статусов."""

    def test_all_statuses_have_russian_text(self):
        """Все статусы имеют текст на русском."""
        for status in PaymentStatus:
            text = get_payment_status_text(status)
            assert isinstance(text, str)
            assert len(text) > 0
            assert text != status.value  # Не просто enum value

    def test_frozen_status_text(self):
        """Статус frozen → содержит 'замороже'."""
        text = get_payment_status_text(PaymentStatus.FROZEN)
        assert "замороже" in text.lower()

    def test_refunded_status_text(self):
        """Статус refunded → содержит 'возвращ'."""
        text = get_payment_status_text(PaymentStatus.REFUNDED)
        assert "возвращ" in text.lower()
