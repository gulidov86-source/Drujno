"""
Модуль: services/level_system.py
Описание: Система уровней и лояльности пользователей
Проект: GroupBuy Mini App

Уровни пользователей:
    1. NEWCOMER (Новичок) 🌱 — Начальный уровень
    2. BUYER (Покупатель) 🛒 — 3+ заказа
    3. ACTIVIST (Активист) ⭐ — 10+ заказов, 20+ приглашений
    4. EXPERT (Эксперт) 🔥 — 25+ заказов, 5+ закрытых сборов
    5. AMBASSADOR (Амбассадор) 👑 — 50+ заказов, 15+ закрытых сборов

Привилегии:
    - Activist: Бонус 2%, ранний доступ к товарам
    - Expert: Бонус 3%, создание сборов, приоритет в поддержке
    - Ambassador: Бонус 5%, эксклюзивные товары, бесплатная доставка

Использование:
    from services.level_system import LevelSystem
    
    system = LevelSystem()
    
    # Проверить и обновить уровень
    result = await system.check_and_update_level(user_id=42)
    
    # Получить бонус для уровня
    bonus_percent = system.get_level_bonus("expert")  # 3.0
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from pydantic import BaseModel
from enum import Enum

import sys
sys.path.append("..")
from database.connection import get_db


# ============================================================
# КОНСТАНТЫ
# ============================================================

class UserLevel(str, Enum):
    """Уровни пользователей."""
    NEWCOMER = "newcomer"
    BUYER = "buyer"
    ACTIVIST = "activist"
    EXPERT = "expert"
    AMBASSADOR = "ambassador"


# Информация об уровнях
LEVEL_INFO = {
    UserLevel.NEWCOMER: {
        "name": "Новичок",
        "emoji": "🌱",
        "bonus_percent": 0,
        "can_create_groups": False,
        "priority_support": False,
        "free_delivery": False,
        "early_access": False
    },
    UserLevel.BUYER: {
        "name": "Покупатель",
        "emoji": "🛒",
        "bonus_percent": 0,
        "can_create_groups": False,
        "priority_support": False,
        "free_delivery": False,
        "early_access": False
    },
    UserLevel.ACTIVIST: {
        "name": "Активист",
        "emoji": "⭐",
        "bonus_percent": 2,
        "can_create_groups": False,
        "priority_support": False,
        "free_delivery": False,
        "early_access": True
    },
    UserLevel.EXPERT: {
        "name": "Эксперт",
        "emoji": "🔥",
        "bonus_percent": 3,
        "can_create_groups": True,
        "priority_support": True,
        "free_delivery": False,
        "early_access": True
    },
    UserLevel.AMBASSADOR: {
        "name": "Амбассадор",
        "emoji": "👑",
        "bonus_percent": 5,
        "can_create_groups": True,
        "priority_support": True,
        "free_delivery": True,
        "early_access": True
    }
}

# Требования для каждого уровня
LEVEL_REQUIREMENTS = {
    UserLevel.NEWCOMER: {
        "orders": 0,
        "invited": 0,
        "groups_organized": 0
    },
    UserLevel.BUYER: {
        "orders": 3,
        "invited": 0,
        "groups_organized": 0
    },
    UserLevel.ACTIVIST: {
        "orders": 10,
        "invited": 20,
        "groups_organized": 0
    },
    UserLevel.EXPERT: {
        "orders": 25,
        "invited": 0,
        "groups_organized": 5
    },
    UserLevel.AMBASSADOR: {
        "orders": 50,
        "invited": 0,
        "groups_organized": 15
    }
}

# Порядок уровней (для определения следующего)
LEVEL_ORDER = [
    UserLevel.NEWCOMER,
    UserLevel.BUYER,
    UserLevel.ACTIVIST,
    UserLevel.EXPERT,
    UserLevel.AMBASSADOR
]


# ============================================================
# МОДЕЛИ
# ============================================================

class LevelCheckResult(BaseModel):
    """Результат проверки уровня."""
    current_level: UserLevel
    new_level: Optional[UserLevel] = None
    level_changed: bool = False
    message: str


class LevelProgress(BaseModel):
    """Прогресс до следующего уровня."""
    current_level: UserLevel
    current_level_name: str
    current_level_emoji: str
    
    next_level: Optional[UserLevel] = None
    next_level_name: Optional[str] = None
    
    # Текущие показатели
    orders: int
    invited: int
    groups_organized: int
    
    # Требования для следующего уровня
    orders_required: Optional[int] = None
    invited_required: Optional[int] = None
    groups_required: Optional[int] = None
    
    # Прогресс (0-100)
    progress_percent: float
    
    # Что нужно сделать
    requirements_text: Optional[str] = None


# ============================================================
# СЕРВИС
# ============================================================

class LevelSystem:
    """
    Система уровней пользователей.
    
    Пример:
        system = LevelSystem()
        
        # Проверить уровень после заказа
        result = await system.check_and_update_level(user_id=42)
        if result.level_changed:
            print(f"Поздравляем! Новый уровень: {result.new_level}")
    """
    
    def __init__(self):
        """Инициализация."""
        self.db = get_db()
    
    def get_level_info(self, level: UserLevel) -> Dict[str, Any]:
        """
        Получить информацию об уровне.
        
        Параметры:
            level: Уровень пользователя
        
        Возвращает:
            dict: Информация об уровне
        """
        return LEVEL_INFO.get(level, LEVEL_INFO[UserLevel.NEWCOMER])
    
    def get_level_bonus(self, level: str) -> float:
        """
        Получить процент бонуса для уровня.
        
        Параметры:
            level: Строковое название уровня
        
        Возвращает:
            float: Процент бонуса
        """
        try:
            level_enum = UserLevel(level)
            return LEVEL_INFO[level_enum]["bonus_percent"]
        except (ValueError, KeyError):
            return 0
    
    def get_next_level(self, current_level: UserLevel) -> Optional[UserLevel]:
        """
        Получить следующий уровень.
        
        Параметры:
            current_level: Текущий уровень
        
        Возвращает:
            UserLevel | None: Следующий уровень или None если максимальный
        """
        try:
            current_index = LEVEL_ORDER.index(current_level)
            if current_index < len(LEVEL_ORDER) - 1:
                return LEVEL_ORDER[current_index + 1]
        except ValueError:
            pass
        return None
    
    def calculate_level(
        self,
        orders: int,
        invited: int,
        groups_organized: int
    ) -> UserLevel:
        """
        Рассчитать уровень на основе показателей.
        
        Идём от высшего уровня к низшему и возвращаем первый подходящий.
        
        Параметры:
            orders: Количество заказов
            invited: Количество приглашённых
            groups_organized: Количество организованных сборов
        
        Возвращает:
            UserLevel: Рассчитанный уровень
        """
        # Проверяем от высшего к низшему
        for level in reversed(LEVEL_ORDER):
            reqs = LEVEL_REQUIREMENTS[level]
            
            orders_ok = orders >= reqs["orders"]
            invited_ok = invited >= reqs["invited"]
            groups_ok = groups_organized >= reqs["groups_organized"]
            
            if orders_ok and invited_ok and groups_ok:
                return level
        
        return UserLevel.NEWCOMER
    
    async def check_and_update_level(self, user_id: int) -> LevelCheckResult:
        """
        Проверить и обновить уровень пользователя.
        
        Параметры:
            user_id: ID пользователя
        
        Возвращает:
            LevelCheckResult: Результат проверки
        """
        # Получаем данные пользователя
        result = (
            self.db.table("users")
            .select("level, total_orders, invited_count, groups_organized")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        
        if not result.data:
            return LevelCheckResult(
                current_level=UserLevel.NEWCOMER,
                level_changed=False,
                message="Пользователь не найден"
            )
        
        user_data = result.data[0]
        current_level = UserLevel(user_data.get("level", "newcomer"))
        
        # Рассчитываем новый уровень
        new_level = self.calculate_level(
            orders=user_data.get("total_orders", 0),
            invited=user_data.get("invited_count", 0),
            groups_organized=user_data.get("groups_organized", 0)
        )
        
        # Проверяем, изменился ли уровень
        if new_level != current_level:
            # Определяем, повышение или понижение
            current_index = LEVEL_ORDER.index(current_level)
            new_index = LEVEL_ORDER.index(new_level)
            
            if new_index > current_index:
                # Повышение уровня
                self.db.table("users").update({
                    "level": new_level.value
                }).eq("id", user_id).execute()
                
                level_info = self.get_level_info(new_level)
                
                return LevelCheckResult(
                    current_level=current_level,
                    new_level=new_level,
                    level_changed=True,
                    message=f"Поздравляем! Вы достигли уровня {level_info['emoji']} {level_info['name']}!"
                )
            else:
                # Понижение — обычно не делаем, но можно
                pass
        
        return LevelCheckResult(
            current_level=current_level,
            level_changed=False,
            message="Уровень не изменился"
        )
    
    async def get_level_progress(self, user_id: int) -> LevelProgress:
        """
        Получить прогресс пользователя до следующего уровня.
        
        Параметры:
            user_id: ID пользователя
        
        Возвращает:
            LevelProgress: Информация о прогрессе
        """
        # Получаем данные пользователя
        result = (
            self.db.table("users")
            .select("level, total_orders, invited_count, groups_organized")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        
        if not result.data:
            # Возвращаем дефолтные данные
            info = self.get_level_info(UserLevel.NEWCOMER)
            return LevelProgress(
                current_level=UserLevel.NEWCOMER,
                current_level_name=info["name"],
                current_level_emoji=info["emoji"],
                orders=0,
                invited=0,
                groups_organized=0,
                progress_percent=0
            )
        
        user_data = result.data[0]
        current_level = UserLevel(user_data.get("level", "newcomer"))
        current_info = self.get_level_info(current_level)
        
        orders = user_data.get("total_orders", 0)
        invited = user_data.get("invited_count", 0)
        groups = user_data.get("groups_organized", 0)
        
        # Получаем следующий уровень
        next_level = self.get_next_level(current_level)
        
        if next_level is None:
            # Максимальный уровень
            return LevelProgress(
                current_level=current_level,
                current_level_name=current_info["name"],
                current_level_emoji=current_info["emoji"],
                orders=orders,
                invited=invited,
                groups_organized=groups,
                progress_percent=100,
                requirements_text="Вы достигли максимального уровня!"
            )
        
        next_info = self.get_level_info(next_level)
        next_reqs = LEVEL_REQUIREMENTS[next_level]
        
        # Рассчитываем прогресс
        progresses = []
        requirements_parts = []
        
        if next_reqs["orders"] > 0:
            progress = min(1.0, orders / next_reqs["orders"])
            progresses.append(progress)
            if orders < next_reqs["orders"]:
                requirements_parts.append(f"{next_reqs['orders'] - orders} заказов")
        
        if next_reqs["invited"] > 0:
            progress = min(1.0, invited / next_reqs["invited"])
            progresses.append(progress)
            if invited < next_reqs["invited"]:
                requirements_parts.append(f"{next_reqs['invited'] - invited} приглашений")
        
        if next_reqs["groups_organized"] > 0:
            progress = min(1.0, groups / next_reqs["groups_organized"])
            progresses.append(progress)
            if groups < next_reqs["groups_organized"]:
                requirements_parts.append(f"{next_reqs['groups_organized'] - groups} сборов")
        
        # Общий прогресс — минимум из всех (нужно выполнить все требования)
        total_progress = min(progresses) * 100 if progresses else 0
        
        # Формируем текст требований
        requirements_text = None
        if requirements_parts:
            requirements_text = "Нужно ещё: " + ", ".join(requirements_parts)
        
        return LevelProgress(
            current_level=current_level,
            current_level_name=current_info["name"],
            current_level_emoji=current_info["emoji"],
            next_level=next_level,
            next_level_name=next_info["name"],
            orders=orders,
            invited=invited,
            groups_organized=groups,
            orders_required=next_reqs["orders"] if next_reqs["orders"] > 0 else None,
            invited_required=next_reqs["invited"] if next_reqs["invited"] > 0 else None,
            groups_required=next_reqs["groups_organized"] if next_reqs["groups_organized"] > 0 else None,
            progress_percent=round(total_progress, 1),
            requirements_text=requirements_text
        )
    
    def can_create_groups(self, level: str) -> bool:
        """
        Проверить, может ли пользователь создавать сборы.
        
        Параметры:
            level: Уровень пользователя
        
        Возвращает:
            bool: True если может
        """
        try:
            level_enum = UserLevel(level)
            return LEVEL_INFO[level_enum]["can_create_groups"]
        except (ValueError, KeyError):
            return False
    
    def get_delivery_discount(self, level: str) -> Decimal:
        """
        Получить скидку на доставку.
        
        Параметры:
            level: Уровень пользователя
        
        Возвращает:
            Decimal: Процент скидки (0-100)
        """
        try:
            level_enum = UserLevel(level)
            if LEVEL_INFO[level_enum]["free_delivery"]:
                return Decimal("100")  # Бесплатная доставка
            return Decimal("0")
        except (ValueError, KeyError):
            return Decimal("0")


# ============================================================
# СИНГЛТОН
# ============================================================

_level_system: Optional[LevelSystem] = None


def get_level_system() -> LevelSystem:
    """Получить экземпляр LevelSystem."""
    global _level_system
    if _level_system is None:
        _level_system = LevelSystem()
    return _level_system


# ============================================================
# ТЕСТИРОВАНИЕ
# ============================================================

if __name__ == "__main__":
    """Тесты."""
    print("🧪 Тестирование level_system.py\n")
    
    system = LevelSystem()
    
    # Тест расчёта уровня
    print("1. Расчёт уровня:")
    test_cases = [
        (0, 0, 0),    # newcomer
        (3, 0, 0),    # buyer
        (10, 20, 0),  # activist
        (25, 0, 5),   # expert
        (50, 0, 15),  # ambassador
    ]
    
    for orders, invited, groups in test_cases:
        level = system.calculate_level(orders, invited, groups)
        info = system.get_level_info(level)
        print(f"   {orders} заказов, {invited} приглашений, {groups} сборов → {info['emoji']} {info['name']}")
    
    # Тест бонусов
    print("\n2. Бонусы по уровням:")
    for level in LEVEL_ORDER:
        bonus = system.get_level_bonus(level.value)
        info = system.get_level_info(level)
        print(f"   {info['emoji']} {info['name']}: {bonus}%")
    
    print("\n✅ Тесты завершены")
