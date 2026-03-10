"""
Тесты: Жизненный цикл сборов и расчёт цен
Проект: GroupBuy Mini App

Что проверяем:
    1. Расчёт цены по порогам (price tiers)
    2. Форматирование оставшегося времени
    3. Поведение цены при входе/выходе участников

Запуск:
    pytest tests/test_groups.py -v

Аналогия: проверяем что «калькулятор скидок» работает правильно —
больше людей = ниже цена, кто-то ушёл = цена поднимается.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone


# ============================================================
# ТЕСТЫ: РАСЧЁТ ЦЕНЫ ПО ПОРОГАМ
# ============================================================

class TestCalculateCurrentPrice:
    """
    Тесты расчёта текущей цены в зависимости от количества участников.
    
    Аналогия: оптовый магазин. Купил 1 штуку — полная цена.
    Купили 5 человек — скидка 20%. Купили 10 — скидка 40%.
    """
    
    def test_no_tiers_returns_base_price(self):
        """Без порогов → всегда базовая цена (нет скидок)."""
        from price_calculator import calculate_current_price
        
        price = calculate_current_price(
            price_tiers=[],
            participants_count=5,
            base_price=Decimal("1000")
        )
        assert price == Decimal("1000")
    
    def test_below_first_tier_returns_base(self):
        """
        Меньше первого порога → базовая цена.
        
        Пример: порог начинается с 5 человек, а пришло только 3
        → скидки нет, платят по полной.
        """
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 800}]
        price = calculate_current_price(tiers, 3, Decimal("1000"))
        assert price == Decimal("1000")
    
    def test_at_first_tier_returns_tier_price(self):
        """
        Ровно на первом пороге → цена порога.
        
        Пример: порог 5 человек = 800₽. Пришло 5 → цена 800₽.
        """
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        price = calculate_current_price(tiers, 5, Decimal("1000"))
        assert price == Decimal("800")
    
    def test_between_tiers_returns_lower_reached(self):
        """
        Между порогами → цена последнего достигнутого.
        
        Пример: 7 человек. Порог 5=800₽ достигнут, порог 10=600₽ нет.
        Значит цена 800₽.
        """
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        price = calculate_current_price(tiers, 7, Decimal("1000"))
        assert price == Decimal("800")
    
    def test_at_second_tier_returns_second_price(self):
        """На втором пороге → цена второго порога."""
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        price = calculate_current_price(tiers, 10, Decimal("1000"))
        assert price == Decimal("600")
    
    def test_above_all_tiers_returns_best_price(self):
        """
        Выше всех порогов → лучшая цена.
        
        Пример: 20 человек, максимальный порог 10=600₽.
        Цена всё равно 600₽ (лучшая из доступных).
        """
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        price = calculate_current_price(tiers, 20, Decimal("1000"))
        assert price == Decimal("600")
    
    def test_zero_participants_returns_base(self):
        """0 участников → базовая цена."""
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 800}]
        price = calculate_current_price(tiers, 0, Decimal("1000"))
        assert price == Decimal("1000")
    
    def test_one_participant_returns_base(self):
        """1 участник (создатель) → базовая цена."""
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 800}]
        price = calculate_current_price(tiers, 1, Decimal("1000"))
        assert price == Decimal("1000")


# ============================================================
# ТЕСТЫ: ПОВЕДЕНИЕ ЦЕНЫ ПРИ ВХОДЕ/ВЫХОДЕ
# ============================================================

class TestPriceDynamics:
    """
    Тесты динамики цены: что происходит когда люди приходят и уходят.
    
    Аналогия: чем больше людей скидывается на подарок —
    тем меньше платит каждый. Но если кто-то передумал —
    оставшимся придётся доплатить.
    """
    
    def test_price_drops_when_threshold_reached(self):
        """
        Цена падает при достижении порога.
        4 чел = 1000₽, 5-й пришёл = 800₽.
        """
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 800}]
        base = Decimal("1000")
        
        price_before = calculate_current_price(tiers, 4, base)
        price_after = calculate_current_price(tiers, 5, base)
        
        assert price_before == Decimal("1000")
        assert price_after == Decimal("800")
        assert price_after < price_before
    
    def test_price_rises_when_drops_below_threshold(self):
        """
        Цена растёт если участник уходит и число падает ниже порога.
        5 чел = 800₽, один ушёл → 4 чел = 1000₽.
        """
        from price_calculator import calculate_current_price
        
        tiers = [{"min_quantity": 5, "price": 800}]
        base = Decimal("1000")
        
        price_with_5 = calculate_current_price(tiers, 5, base)
        price_with_4 = calculate_current_price(tiers, 4, base)
        
        assert price_with_5 == Decimal("800")
        assert price_with_4 == Decimal("1000")
        assert price_with_4 > price_with_5
    
    def test_price_stable_within_tier(self):
        """
        Цена стабильна между порогами.
        5, 6, 7, 8, 9 человек → всё равно 800₽.
        """
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 5, "price": 800},
            {"min_quantity": 10, "price": 600}
        ]
        base = Decimal("1000")
        
        for count in range(5, 10):
            price = calculate_current_price(tiers, count, base)
            assert price == Decimal("800"), f"При {count} участниках цена должна быть 800"
    
    def test_monotonically_decreasing_or_equal(self):
        """
        Цена не может расти при УВЕЛИЧЕНИИ числа участников.
        Каждый новый человек → цена или падает, или не меняется.
        """
        from price_calculator import calculate_current_price
        
        tiers = [
            {"min_quantity": 3, "price": 900},
            {"min_quantity": 7, "price": 750},
            {"min_quantity": 15, "price": 600}
        ]
        base = Decimal("1000")
        
        prev_price = base
        for count in range(1, 20):
            current_price = calculate_current_price(tiers, count, base)
            assert current_price <= prev_price, (
                f"Цена выросла с {prev_price} до {current_price} "
                f"при увеличении участников с {count-1} до {count}"
            )
            prev_price = current_price


# ============================================================
# ТЕСТЫ: ФОРМАТИРОВАНИЕ ВРЕМЕНИ
# ============================================================

class TestFormatTimeLeft:
    """
    Тесты форматирования оставшегося времени.
    
    Аналогия: таймер на посылке — «доставим через 2д 5ч».
    """
    
    def test_days_and_hours(self):
        """Больше суток → формат '2д 5ч'."""
        from groups import format_time_left
        
        future = datetime.now(timezone.utc) + timedelta(days=2, hours=5)
        result = format_time_left(future)
        assert "д" in result
        assert "ч" in result
    
    def test_only_hours(self):
        """Меньше суток → формат '5ч 30м'."""
        from groups import format_time_left
        
        future = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        result = format_time_left(future)
        assert "ч" in result
        assert "м" in result
        assert "д" not in result
    
    def test_only_minutes(self):
        """Меньше часа → формат '45м'."""
        from groups import format_time_left
        
        future = datetime.now(timezone.utc) + timedelta(minutes=45)
        result = format_time_left(future)
        assert "м" in result
    
    def test_expired_shows_completed(self):
        """Время вышло → 'Завершён'."""
        from groups import format_time_left
        
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        result = format_time_left(past)
        assert result == "Завершён"
    
    def test_string_datetime_input(self):
        """Принимает строку ISO формата (как из БД)."""
        from groups import format_time_left
        
        future = datetime.now(timezone.utc) + timedelta(days=1)
        result = format_time_left(future.isoformat())
        assert isinstance(result, str)
        assert len(result) > 0
