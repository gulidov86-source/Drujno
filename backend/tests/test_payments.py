"""
Тесты: Платёжный поток (webhook подпись, статусы)
Проект: GroupBuy Mini App

Что проверяем:
    1. Валидация подписи webhook от YooKassa
    2. Отклонение фейковых webhook-ов
    3. Тексты статусов платежей

Запуск:
    pytest tests/test_payments.py -v

Аналогия: проверяем что банк отличает настоящий
перевод от поддельного (подпись webhook),
и что клиент видит понятные статусы.
"""

import pytest
import hmac
import hashlib
from unittest.mock import patch, MagicMock

import sys


# ============================================================
# ТЕСТЫ: ПОДПИСЬ WEBHOOK
# ============================================================

class TestWebhookSignature:
    """
    Тесты проверки подписи webhook от YooKassa.
    
    Аналогия: банк присылает перевод с печатью. Мы проверяем
    печать — настоящая или подделка. Без печати — не принимаем.
    """
    
    def test_valid_signature_accepted(self):
        """Валидная подпись (настоящая печать) — принимаем."""
        secret = "test-webhook-secret"
        body = b'{"event":"payment.succeeded","object":{"id":"123"}}'
        
        # Вычисляем правильную подпись
        expected_sig = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        
        with patch("config.settings") as ms:
            ms.YOOKASSA_WEBHOOK_SECRET = secret
            
            # Очищаем кеш
            for mod in list(sys.modules.keys()):
                if "payment_service" in mod:
                    del sys.modules[mod]
            
            from payment_service import PaymentService
            service = PaymentService.__new__(PaymentService)
            
            result = service.verify_webhook_signature(body, expected_sig)
            assert result is True
    
    def test_invalid_signature_rejected(self):
        """Невалидная подпись (поддельная печать) — отклоняем."""
        with patch("config.settings") as ms:
            ms.YOOKASSA_WEBHOOK_SECRET = "real-secret"
            
            for mod in list(sys.modules.keys()):
                if "payment_service" in mod:
                    del sys.modules[mod]
            
            from payment_service import PaymentService
            service = PaymentService.__new__(PaymentService)
            
            body = b'{"event":"payment.succeeded"}'
            result = service.verify_webhook_signature(body, "fake-signature-123")
            assert result is False
    
    def test_empty_secret_rejects(self):
        """
        Без секрета — отклоняем (фикс Спринта 1).
        
        Раньше тут было return True — это была дыра!
        Без секрета = без печати = не принимаем перевод.
        """
        with patch("config.settings") as ms:
            ms.YOOKASSA_WEBHOOK_SECRET = ""
            
            for mod in list(sys.modules.keys()):
                if "payment_service" in mod:
                    del sys.modules[mod]
            
            from payment_service import PaymentService
            service = PaymentService.__new__(PaymentService)
            
            result = service.verify_webhook_signature(b"body", "any-signature")
            assert result is False
    
    def test_different_body_different_signature(self):
        """Разное тело запроса → разная подпись."""
        secret = "test-secret"
        
        sig1 = hmac.new(secret.encode(), b"body1", hashlib.sha256).hexdigest()
        sig2 = hmac.new(secret.encode(), b"body2", hashlib.sha256).hexdigest()
        
        assert sig1 != sig2
    
    def test_tampered_body_rejected(self):
        """
        Если тело запроса изменено (подменили сумму) — подпись не совпадёт.
        
        Аналогия: мошенник перехватил перевод и изменил сумму
        с 1000₽ на 1₽. Но подпись была от оригинала → не совпадёт.
        """
        secret = "test-secret"
        original_body = b'{"amount":"1000","status":"succeeded"}'
        tampered_body = b'{"amount":"1","status":"succeeded"}'
        
        # Подпись от оригинального тела
        original_sig = hmac.new(
            secret.encode(), original_body, hashlib.sha256
        ).hexdigest()
        
        with patch("config.settings") as ms:
            ms.YOOKASSA_WEBHOOK_SECRET = secret
            
            for mod in list(sys.modules.keys()):
                if "payment_service" in mod:
                    del sys.modules[mod]
            
            from payment_service import PaymentService
            service = PaymentService.__new__(PaymentService)
            
            # Оригинальное тело + оригинальная подпись → OK
            assert service.verify_webhook_signature(original_body, original_sig) is True
            
            # Подменённое тело + оригинальная подпись → FAIL
            assert service.verify_webhook_signature(tampered_body, original_sig) is False


# ============================================================
# ТЕСТЫ: СТАТУСЫ ПЛАТЕЖЕЙ
# ============================================================

class TestPaymentStatusText:
    """Тесты текстов статусов."""
    
    def test_all_statuses_have_russian_text(self):
        """Все статусы имеют текст на русском."""
        from payments import get_payment_status_text
        from models import PaymentStatus
        
        for status in PaymentStatus:
            text = get_payment_status_text(status)
            assert isinstance(text, str)
            assert len(text) > 0
            # Проверяем что это не просто enum value
            assert text != status.value
    
    def test_frozen_status_text(self):
        """Статус frozen → 'Средства заморожены'."""
        from payments import get_payment_status_text
        from models import PaymentStatus
        
        text = get_payment_status_text(PaymentStatus.FROZEN)
        assert "замороже" in text.lower()
    
    def test_refunded_status_text(self):
        """Статус refunded → 'Возвращён'."""
        from payments import get_payment_status_text
        from models import PaymentStatus
        
        text = get_payment_status_text(PaymentStatus.REFUNDED)
        assert "возвращ" in text.lower()
