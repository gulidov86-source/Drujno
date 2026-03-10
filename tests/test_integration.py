"""
Интеграционный тест: полный путь пользователя
Проект: GroupBuy Mini App

Запуск: pytest backend/tests/test_integration.py -v
"""

import pytest
import hmac
import hashlib
from decimal import Decimal

from utils.auth import create_access_token, verify_token
from services.price_calculator import calculate_current_price
from services.payment_service import PaymentService
from config import settings


# ============================================================
# ТЕСТ: ПОЛНЫЙ ПУТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================

class TestFullUserJourney:
    """
    Сквозной тест: от авторизации до списания средств.
    Каждый метод — один шаг в пути пользователя.
    """

    def test_step1_jwt_roundtrip(self):
        """Шаг 1: Создаём токен → декодируем → получаем user_id обратно."""
        token = create_access_token(user_id=42, telegram_id=99999)
        payload = verify_token(token)

        assert payload is not None
        assert payload.sub == "42"
        assert payload.telegram_id == 99999

    def test_step2_price_drops_with_participants(self):
        """Шаг 2: Цена падает с ростом участников."""
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        base = Decimal("1000")

        assert calculate_current_price(tiers, 1, base) == Decimal("1000")
        assert calculate_current_price(tiers, 5, base) == Decimal("800")
        assert calculate_current_price(tiers, 10, base) == Decimal("600")

    def test_step3_price_rises_on_leave(self):
        """Шаг 3: Участник уходит → цена растёт для остальных."""
        tiers = [{"min_quantity": 5, "price": 800}]
        base = Decimal("1000")

        assert calculate_current_price(tiers, 5, base) == Decimal("800")
        assert calculate_current_price(tiers, 4, base) == Decimal("1000")

    def test_step4_fake_webhook_rejected(self):
        """Шаг 4: Фейковый webhook → отклоняется."""
        old_secret = settings.YOOKASSA_WEBHOOK_SECRET
        settings.YOOKASSA_WEBHOOK_SECRET = "real-secret"

        try:
            service = PaymentService.__new__(PaymentService)
            body = b'{"event":"payment.succeeded","object":{"id":"fake"}}'
            assert service.verify_webhook_signature(body, "fake") is False
        finally:
            settings.YOOKASSA_WEBHOOK_SECRET = old_secret

    def test_step5_real_webhook_accepted(self):
        """Шаг 5: Настоящий webhook → принимается."""
        old_secret = settings.YOOKASSA_WEBHOOK_SECRET
        settings.YOOKASSA_WEBHOOK_SECRET = "real-secret"

        try:
            body = b'{"event":"payment.waiting_for_capture","object":{"id":"pay_123"}}'
            real_sig = hmac.new(b"real-secret", body, hashlib.sha256).hexdigest()

            service = PaymentService.__new__(PaymentService)
            assert service.verify_webhook_signature(body, real_sig) is True
        finally:
            settings.YOOKASSA_WEBHOOK_SECRET = old_secret

    def test_step6_price_consistency_full_cycle(self):
        """Шаг 6: Цена последовательна 0→25 участников — только падает."""
        tiers = [
            {"min_quantity": 3, "price": 900},
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600},
            {"min_quantity": 20, "price": 500}
        ]
        base = Decimal("1000")

        prev_price = base
        for count in range(0, 25):
            price = calculate_current_price(tiers, count, base)
            assert price <= prev_price
            prev_price = price

        assert prev_price == Decimal("500")


# ============================================================
# ТЕСТ: ГРАНИЧНЫЕ СЛУЧАИ
# ============================================================

class TestEdgeCases:
    """Граничные случаи, которые могут сломать систему."""

    def test_single_tier(self):
        """Работает с одним порогом."""
        tiers = [{"min_quantity": 10, "price": 500}]
        base = Decimal("1000")

        assert calculate_current_price(tiers, 9, base) == Decimal("1000")
        assert calculate_current_price(tiers, 10, base) == Decimal("500")

    def test_many_tiers(self):
        """Работает с 9 порогами."""
        tiers = [
            {"min_quantity": i * 5, "price": 1000 - i * 100}
            for i in range(1, 10)
        ]
        base = Decimal("1000")

        price = calculate_current_price(tiers, 45, base)
        assert price == Decimal("100")

    def test_tier_price_equals_base(self):
        """Порог с той же ценой что базовая."""
        tiers = [{"min_quantity": 5, "price": 1000}]
        base = Decimal("1000")

        price = calculate_current_price(tiers, 5, base)
        assert price == Decimal("1000")

    def test_large_participant_count(self):
        """Работает с 10000 участников."""
        tiers = [{"min_quantity": 10, "price": 500}]
        base = Decimal("1000")

        price = calculate_current_price(tiers, 10000, base)
        assert price == Decimal("500")
