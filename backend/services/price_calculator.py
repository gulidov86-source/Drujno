"""
Модуль: services/price_calculator.py
Описание: Расчёт динамических цен для групповых сборов
Проект: GroupBuy Mini App

Это ядро бизнес-логики: цена зависит от количества участников.

Как работает:
    1. У товара есть базовая цена (розничная)
    2. Есть ценовые пороги (price_tiers): при N участниках цена = X
    3. Чем больше участников — тем ниже цена

Пример:
    Базовая цена: 25 000₽
    Пороги:
        - 3 человека → 22 000₽
        - 10 человек → 19 000₽
        - 25 человек → 16 500₽
    
    Если сейчас 15 участников → цена 19 000₽
    (достигли порог 10, но не 25)

Использование:
    from services.price_calculator import calculate_current_price
    
    price = calculate_current_price(
        price_tiers=[
            {"min_quantity": 3, "price": 22000},
            {"min_quantity": 10, "price": 19000},
        ],
        participants_count=7
    )
    # price = 22000 (достигли порог 3, но не 10)
"""

from decimal import Decimal
from typing import List, Optional, Tuple
from pydantic import BaseModel


# ============================================================
# МОДЕЛИ
# ============================================================

class PriceTier(BaseModel):
    """
    Ценовой порог.
    
    Атрибуты:
        min_quantity: Минимум участников для этой цены
        price: Цена при достижении порога
    """
    min_quantity: int
    price: Decimal


class PriceInfo(BaseModel):
    """
    Полная информация о цене.
    
    Используется для отображения на фронтенде.
    """
    current_price: Decimal       # Текущая цена
    base_price: Decimal          # Базовая (розничная) цена
    best_price: Decimal          # Лучшая возможная цена
    savings_amount: Decimal      # Экономия (base - current)
    savings_percent: float       # Процент экономии
    participants: int            # Текущее количество участников
    
    # До следующего порога
    next_tier_price: Optional[Decimal] = None   # Цена на след. пороге
    next_tier_quantity: Optional[int] = None    # Нужно участников
    people_to_next_tier: Optional[int] = None   # Осталось людей


class TierProgress(BaseModel):
    """
    Прогресс по ценовым порогам.
    
    Используется для визуализации (прогресс-бары).
    """
    tier_price: Decimal          # Цена порога
    tier_quantity: int           # Нужно участников
    is_reached: bool             # Достигнут ли
    is_current: bool             # Это текущий уровень
    progress_percent: float      # Прогресс до этого порога (0-100)


# ============================================================
# ОСНОВНЫЕ ФУНКЦИИ
# ============================================================

def calculate_current_price(
    price_tiers: List[dict],
    participants_count: int,
    base_price: Decimal = None
) -> Decimal:
    """
    Рассчитать текущую цену на основе количества участников.
    
    Алгоритм:
    1. Сортируем пороги по min_quantity (по убыванию)
    2. Находим первый порог, где min_quantity <= participants_count
    3. Возвращаем соответствующую цену
    
    Параметры:
        price_tiers: Список ценовых порогов
            [{"min_quantity": 3, "price": 22000}, ...]
        participants_count: Текущее количество участников
        base_price: Базовая цена (если участников меньше минимума)
    
    Возвращает:
        Decimal: Текущая цена
    
    Примеры:
        >>> tiers = [
        ...     {"min_quantity": 3, "price": 22000},
        ...     {"min_quantity": 10, "price": 19000},
        ...     {"min_quantity": 25, "price": 16500}
        ... ]
        
        >>> calculate_current_price(tiers, 1)
        Decimal('25000')  # Меньше минимума → базовая цена
        
        >>> calculate_current_price(tiers, 5)
        Decimal('22000')  # Достигли 3, но не 10
        
        >>> calculate_current_price(tiers, 15)
        Decimal('19000')  # Достигли 10, но не 25
        
        >>> calculate_current_price(tiers, 30)
        Decimal('16500')  # Достигли 25
    """
    if not price_tiers:
        # Нет порогов — возвращаем базовую цену
        return Decimal(str(base_price)) if base_price else Decimal("0")
    
    # Преобразуем в объекты PriceTier и сортируем по убыванию min_quantity
    tiers = []
    for tier in price_tiers:
        tiers.append(PriceTier(
            min_quantity=tier["min_quantity"],
            price=Decimal(str(tier["price"]))
        ))
    
    tiers.sort(key=lambda t: t.min_quantity, reverse=True)
    
    # Ищем первый достигнутый порог
    for tier in tiers:
        if participants_count >= tier.min_quantity:
            return tier.price
    
    # Не достигли ни одного порога — возвращаем базовую цену
    if base_price:
        return Decimal(str(base_price))
    
    # Если нет базовой цены, берём цену первого (самого маленького) порога
    return tiers[-1].price if tiers else Decimal("0")


def get_best_price(price_tiers: List[dict]) -> Decimal:
    """
    Получить лучшую (минимальную) возможную цену.
    
    Это цена при максимальном количестве участников.
    
    Параметры:
        price_tiers: Список ценовых порогов
    
    Возвращает:
        Decimal: Минимальная возможная цена
    
    Пример:
        >>> tiers = [
        ...     {"min_quantity": 3, "price": 22000},
        ...     {"min_quantity": 25, "price": 16500}
        ... ]
        >>> get_best_price(tiers)
        Decimal('16500')
    """
    if not price_tiers:
        return Decimal("0")
    
    # Находим порог с наибольшим min_quantity
    max_tier = max(price_tiers, key=lambda t: t["min_quantity"])
    return Decimal(str(max_tier["price"]))


def calculate_savings(
    base_price: Decimal,
    current_price: Decimal
) -> Tuple[Decimal, float]:
    """
    Рассчитать экономию.
    
    Параметры:
        base_price: Базовая (розничная) цена
        current_price: Текущая цена
    
    Возвращает:
        Tuple[Decimal, float]: (сумма экономии, процент)
    
    Пример:
        >>> calculate_savings(Decimal("25000"), Decimal("19000"))
        (Decimal('6000'), 24.0)
    """
    base = Decimal(str(base_price))
    current = Decimal(str(current_price))
    
    savings_amount = base - current
    
    if base > 0:
        savings_percent = float((savings_amount / base) * 100)
    else:
        savings_percent = 0.0
    
    return savings_amount, round(savings_percent, 1)


def get_next_tier_info(
    price_tiers: List[dict],
    current_participants: int
) -> Optional[dict]:
    """
    Получить информацию о следующем ценовом пороге.
    
    Параметры:
        price_tiers: Список ценовых порогов
        current_participants: Текущее количество участников
    
    Возвращает:
        dict | None: Информация о следующем пороге или None
            {
                "next_price": Decimal,      # Цена на след. пороге
                "next_quantity": int,       # Нужно участников
                "people_needed": int,       # Осталось людей
                "savings_per_person": Decimal  # Экономия на человека
            }
    
    Пример:
        >>> tiers = [
        ...     {"min_quantity": 10, "price": 19000},
        ...     {"min_quantity": 25, "price": 16500}
        ... ]
        >>> get_next_tier_info(tiers, 15)
        {
            "next_price": Decimal('16500'),
            "next_quantity": 25,
            "people_needed": 10,
            "savings_per_person": Decimal('2500')
        }
    """
    if not price_tiers:
        return None
    
    # Сортируем по min_quantity (по возрастанию)
    sorted_tiers = sorted(price_tiers, key=lambda t: t["min_quantity"])
    
    # Находим текущий и следующий порог
    current_price = None
    next_tier = None
    
    for i, tier in enumerate(sorted_tiers):
        if tier["min_quantity"] <= current_participants:
            current_price = Decimal(str(tier["price"]))
        else:
            # Это первый недостигнутый порог — он и есть следующий
            next_tier = tier
            break
    
    if next_tier is None:
        # Достигли максимального порога
        return None
    
    next_price = Decimal(str(next_tier["price"]))
    people_needed = next_tier["min_quantity"] - current_participants
    
    # Экономия на человека при достижении следующего порога
    if current_price:
        savings_per_person = current_price - next_price
    else:
        savings_per_person = Decimal("0")
    
    return {
        "next_price": next_price,
        "next_quantity": next_tier["min_quantity"],
        "people_needed": people_needed,
        "savings_per_person": savings_per_person
    }


def get_full_price_info(
    price_tiers: List[dict],
    base_price: Decimal,
    participants_count: int
) -> PriceInfo:
    """
    Получить полную информацию о цене.
    
    Собирает всю информацию в один объект для фронтенда.
    
    Параметры:
        price_tiers: Список ценовых порогов
        base_price: Базовая цена
        participants_count: Текущее количество участников
    
    Возвращает:
        PriceInfo: Полная информация о цене
    
    Пример:
        >>> info = get_full_price_info(tiers, Decimal("25000"), 15)
        >>> print(info.current_price)
        19000
        >>> print(info.savings_percent)
        24.0
        >>> print(info.people_to_next_tier)
        10
    """
    base = Decimal(str(base_price))
    current = calculate_current_price(price_tiers, participants_count, base)
    best = get_best_price(price_tiers) if price_tiers else base
    
    savings_amount, savings_percent = calculate_savings(base, current)
    next_tier = get_next_tier_info(price_tiers, participants_count)
    
    return PriceInfo(
        current_price=current,
        base_price=base,
        best_price=best,
        savings_amount=savings_amount,
        savings_percent=savings_percent,
        participants=participants_count,
        next_tier_price=next_tier["next_price"] if next_tier else None,
        next_tier_quantity=next_tier["next_quantity"] if next_tier else None,
        people_to_next_tier=next_tier["people_needed"] if next_tier else None
    )


def get_tiers_progress(
    price_tiers: List[dict],
    participants_count: int
) -> List[TierProgress]:
    """
    Получить прогресс по всем ценовым порогам.
    
    Используется для визуализации "лестницы цен".
    
    Параметры:
        price_tiers: Список ценовых порогов
        participants_count: Текущее количество участников
    
    Возвращает:
        List[TierProgress]: Прогресс по каждому порогу
    
    Пример:
        >>> progress = get_tiers_progress(tiers, 15)
        >>> for tier in progress:
        ...     print(f"{tier.tier_quantity}: {tier.is_reached}, {tier.progress_percent}%")
        3: True, 100.0%
        10: True, 100.0%
        25: False, 60.0%
    """
    if not price_tiers:
        return []
    
    # Сортируем по min_quantity
    sorted_tiers = sorted(price_tiers, key=lambda t: t["min_quantity"])
    
    result = []
    prev_quantity = 0
    current_tier_found = False
    
    for tier in sorted_tiers:
        quantity = tier["min_quantity"]
        price = Decimal(str(tier["price"]))
        
        is_reached = participants_count >= quantity
        
        # Определяем, это ли текущий уровень (достигнут, но следующий — нет)
        is_current = False
        if is_reached and not current_tier_found:
            # Проверяем, есть ли следующий порог и достигнут ли он
            next_tier = next(
                (t for t in sorted_tiers if t["min_quantity"] > quantity),
                None
            )
            if next_tier is None or participants_count < next_tier["min_quantity"]:
                is_current = True
                current_tier_found = True
        
        # Рассчитываем прогресс
        if is_reached:
            progress = 100.0
        else:
            # Прогресс от предыдущего порога до этого
            range_size = quantity - prev_quantity
            progress_in_range = participants_count - prev_quantity
            progress = min(100.0, max(0.0, (progress_in_range / range_size) * 100))
        
        result.append(TierProgress(
            tier_price=price,
            tier_quantity=quantity,
            is_reached=is_reached,
            is_current=is_current,
            progress_percent=round(progress, 1)
        ))
        
        prev_quantity = quantity
    
    return result


# ============================================================
# ГЕНЕРАЦИЯ СООБЩЕНИЙ
# ============================================================

def generate_price_message(
    price_tiers: List[dict],
    base_price: Decimal,
    participants_count: int
) -> str:
    """
    Сгенерировать текстовое сообщение о цене.
    
    Используется для уведомлений и шеринга.
    
    Параметры:
        price_tiers: Ценовые пороги
        base_price: Базовая цена
        participants_count: Количество участников
    
    Возвращает:
        str: Сообщение о цене
    
    Пример:
        >>> generate_price_message(tiers, 25000, 15)
        "💰 Текущая цена: 19 000₽ (экономия 24%)\n👥 Ещё 10 человек — и будет 16 500₽!"
    """
    info = get_full_price_info(price_tiers, base_price, participants_count)
    
    # Форматируем цены с пробелами (19 000)
    def format_price(price: Decimal) -> str:
        return f"{int(price):,}".replace(",", " ")
    
    lines = []
    
    # Текущая цена и экономия
    if info.savings_percent > 0:
        lines.append(
            f"💰 Текущая цена: {format_price(info.current_price)}₽ "
            f"(экономия {info.savings_percent:.0f}%)"
        )
    else:
        lines.append(f"💰 Текущая цена: {format_price(info.current_price)}₽")
    
    # Следующий порог
    if info.people_to_next_tier and info.next_tier_price:
        lines.append(
            f"👥 Ещё {info.people_to_next_tier} человек — "
            f"и будет {format_price(info.next_tier_price)}₽!"
        )
    
    return "\n".join(lines)


def generate_share_text(
    product_name: str,
    price_tiers: List[dict],
    base_price: Decimal,
    participants_count: int
) -> str:
    """
    Сгенерировать текст для шеринга сбора.
    
    Параметры:
        product_name: Название товара
        price_tiers: Ценовые пороги
        base_price: Базовая цена
        participants_count: Количество участников
    
    Возвращает:
        str: Текст для шеринга
    """
    info = get_full_price_info(price_tiers, base_price, participants_count)
    
    def format_price(price: Decimal) -> str:
        return f"{int(price):,}".replace(",", " ")
    
    text = f"🛍 Собираем на {product_name}!\n\n"
    text += f"💰 Сейчас: {format_price(info.current_price)}₽\n"
    text += f"🎯 Может быть: {format_price(info.best_price)}₽\n"
    text += f"👥 Уже {participants_count} человек\n\n"
    text += "Присоединяйся 👇"
    
    return text


# ============================================================
# ТЕСТИРОВАНИЕ
# ============================================================

if __name__ == "__main__":
    """
    Тесты при запуске файла напрямую.
    
    Запуск:
        python services/price_calculator.py
    """
    print("🧪 Тестирование price_calculator.py\n")
    
    # Тестовые пороги
    tiers = [
        {"min_quantity": 3, "price": 22000},
        {"min_quantity": 10, "price": 19000},
        {"min_quantity": 25, "price": 16500}
    ]
    base = Decimal("25000")
    
    # Тест расчёта цены
    print("1. Расчёт цены при разном количестве участников:")
    for count in [1, 3, 7, 10, 15, 25, 50]:
        price = calculate_current_price(tiers, count, base)
        print(f"   {count} участников → {price}₽")
    
    # Тест экономии
    print("\n2. Расчёт экономии:")
    amount, percent = calculate_savings(base, Decimal("19000"))
    print(f"   При цене 19000₽: экономия {amount}₽ ({percent}%)")
    
    # Тест следующего порога
    print("\n3. Следующий порог:")
    next_tier = get_next_tier_info(tiers, 15)
    if next_tier:
        print(f"   Следующая цена: {next_tier['next_price']}₽")
        print(f"   Нужно людей: {next_tier['next_quantity']}")
        print(f"   Осталось: {next_tier['people_needed']}")
    
    # Тест прогресса
    print("\n4. Прогресс по порогам (15 участников):")
    progress = get_tiers_progress(tiers, 15)
    for p in progress:
        status = "✅" if p.is_reached else "⬜"
        current = " ← текущий" if p.is_current else ""
        print(f"   {status} {p.tier_quantity} чел. → {p.tier_price}₽ ({p.progress_percent}%){current}")
    
    # Тест сообщения
    print("\n5. Сгенерированное сообщение:")
    message = generate_price_message(tiers, base, 15)
    print(f"   {message}")
    
    print("\n✅ Тесты завершены")
