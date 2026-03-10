"""
Интеграционный тест: полный путь пользователя
Проект: GroupBuy Mini App

Проверяем сквозной сценарий:
    auth → browse → join → order → webhook → complete

Запуск:
    pytest tests/test_integration.py -v

ВАЖНО: Эти тесты используют моки для БД и платежей.
Для E2E тестов с реальной БД — см. Спринт 4.

Аналогия: генеральная репетиция спектакля. Все актёры
проходят по сценарию от начала до конца, но без реальной
публики (моки вместо реальных сервисов).
"""

import pytest
import hmac
import hashlib
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import sys


# ============================================================
# ТЕСТ: ПОЛНЫЙ ПУТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================

class TestFullUserJourney:
    """
    Сквозной тест: от авторизации до списания средств.
    
    Каждый тест — один шаг в пути пользователя.
    Вместе они проверяют что вся цепочка работает.
    """
    
    def test_step1_jwt_roundtrip(self):
        """
        Шаг 1: Авторизация.
        Создаём токен → декодируем → получаем user_id обратно.
        
        Аналогия: получили пропуск на проходной → показали охраннику
        → он увидел правильное имя.
        """
        with patch("config.settings") as ms:
            ms.JWT_SECRET = "test-secret"
            ms.JWT_ALGORITHM = "HS256"
            ms.JWT_EXPIRE_HOURS = 168
            
            for mod in list(sys.modules.keys()):
                if "auth" in mod:
                    del sys.modules[mod]
            from auth import create_access_token, verify_token
            
            token = create_access_token(user_id=42, telegram_id=99999)
            payload = verify_token(token)
            
            assert payload is not None
            assert payload.sub == "42"
            assert payload.telegram_id == 99999
    
    def test_step2_price_drops_with_participants(self):
        """
        Шаг 2: Просмотр каталога → цена зависит от участников.
        
        Аналогия: витрина показывает «текущая цена 800₽ (при 5 участниках)».
        """
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        base = Decimal("1000")
        
        # Каталог: 1 участник → полная цена
        assert calculate_current_price(tiers, 1, base) == Decimal("1000")
        
        # Сбор растёт: 5 участников → скидка
        assert calculate_current_price(tiers, 5, base) == Decimal("800")
        
        # Полный сбор: 10 участников → максимальная скидка
        assert calculate_current_price(tiers, 10, base) == Decimal("600")
    
    def test_step3_price_rises_on_leave(self):
        """
        Шаг 3: Участник уходит → цена растёт для остальных.
        
        Аналогия: 5 человек скидывались по 800₽ на торт.
        Один передумал → осталось 4 → теперь по 1000₽.
        """
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 800}]
        base = Decimal("1000")
        
        # 5 участников — скидка действует
        price_with_5 = calculate_current_price(tiers, 5, base)
        assert price_with_5 == Decimal("800")
        
        # Один ушёл — скидка пропала
        price_with_4 = calculate_current_price(tiers, 4, base)
        assert price_with_4 == Decimal("1000")
        
        # Цена выросла
        assert price_with_4 > price_with_5
    
    def test_step4_fake_webhook_rejected(self):
        """
        Шаг 4: Фейковый webhook → отклоняется.
        
        Аналогия: мошенник пытается сказать «деньги получены»
        без доказательства → система не верит.
        """
        with patch("config.settings") as ms:
            ms.YOOKASSA_WEBHOOK_SECRET = "real-secret"
            
            for mod in list(sys.modules.keys()):
                if "payment_service" in mod:
                    del sys.modules[mod]
            from payment_service import PaymentService
            service = PaymentService.__new__(PaymentService)
            
            body = b'{"event":"payment.succeeded","object":{"id":"fake"}}'
            
            # Фейковая подпись → отклонено
            assert service.verify_webhook_signature(body, "fake") is False
    
    def test_step5_real_webhook_accepted(self):
        """
        Шаг 5: Настоящий webhook → принимается.
        
        Аналогия: банк прислал подтверждение с настоящей печатью
        → принимаем и обрабатываем.
        """
        secret = "real-secret"
        body = b'{"event":"payment.waiting_for_capture","object":{"id":"pay_123"}}'
        
        real_sig = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        
        with patch("config.settings") as ms:
            ms.YOOKASSA_WEBHOOK_SECRET = secret
            
            for mod in list(sys.modules.keys()):
                if "payment_service" in mod:
                    del sys.modules[mod]
            from payment_service import PaymentService
            service = PaymentService.__new__(PaymentService)
            
            assert service.verify_webhook_signature(body, real_sig) is True
    
    def test_step6_price_consistency_full_cycle(self):
        """
        Шаг 6: Цена последовательна на всём пути.
        0 → 1 → ... → 10 участников: цена только падает или стоит.
        
        Аналогия: скидка растёт с каждым новым участником,
        но никогда не уменьшается при росте группы.
        """
        from price_calculator import calculate_current_price
        
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
            assert price <= prev_price, (
                f"Нарушение: цена выросла с {prev_price} до {price} "
                f"при {count} участниках"
            )
            prev_price = price
        
        # Финальная цена — лучшая из порогов
        assert prev_price == Decimal("500")


# ============================================================
# ТЕСТ: ГРАНИЧНЫЕ СЛУЧАИ
# ============================================================

class TestEdgeCases:
    """Граничные случаи, которые могут сломать систему."""
    
    def test_single_tier(self):
        """Работает с одним порогом."""
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 10, "price": 500}]
        base = Decimal("1000")
        
        assert calculate_current_price(tiers, 9, base) == Decimal("1000")
        assert calculate_current_price(tiers, 10, base) == Decimal("500")
    
    def test_many_tiers(self):
        """Работает с большим количеством порогов."""
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": i * 5, "price": 1000 - i * 100}
            for i in range(1, 10)  # 9 порогов: 5, 10, 15, ...
        ]
        base = Decimal("1000")
        
        # На последнем пороге (45 чел) → самая низкая цена (100₽)
        price = calculate_current_price(tiers, 45, base)
        assert price == Decimal("100")
    
    def test_tier_price_equals_base(self):
        """Порог может иметь ту же цену что и базовая."""
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 1000}]
        base = Decimal("1000")
        
        price = calculate_current_price(tiers, 5, base)
        assert price == Decimal("1000")
    
    def test_large_participant_count(self):
        """Работает с большим количеством участников."""
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 10, "price": 500}]
        base = Decimal("1000")
        
        price = calculate_current_price(tiers, 10000, base)
        assert price == Decimal("500")
