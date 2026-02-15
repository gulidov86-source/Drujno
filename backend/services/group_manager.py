"""
Модуль: services/group_manager.py
Описание: Управление жизненным циклом групповых сборов
Проект: GroupBuy Mini App

Это ядро бизнес-логики приложения. Отвечает за:
- Создание сборов
- Присоединение участников
- Завершение/отмену сборов
- Расчёт бонусов организатора
- Проверку просроченных сборов (для cron)

Жизненный цикл сбора:
    1. ACTIVE — идёт набор участников
    2. COMPLETED — набрали минимум, сбор успешен
    3. FAILED — не набрали до дедлайна
    4. CANCELLED — отменён вручную

Использование:
    from services.group_manager import GroupManager
    
    manager = GroupManager()
    
    # Создать сбор
    group = await manager.create_group(product_id=1, creator_id=42)
    
    # Присоединиться
    result = await manager.join_group(group_id=1, user_id=123, invited_by=42)
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, List, Tuple
from pydantic import BaseModel

import sys
sys.path.append("..")
from config import settings
from database.connection import get_db
from services.price_calculator import (
    calculate_current_price,
    get_best_price,
    get_next_tier_info,
    generate_share_text
)


# ============================================================
# МОДЕЛИ
# ============================================================

class JoinResult(BaseModel):
    """
    Результат присоединения к сбору.
    """
    success: bool
    group_id: int
    user_id: int
    current_count: int
    current_price: Decimal
    previous_price: Optional[Decimal] = None  # Если цена изменилась
    price_dropped: bool = False
    message: str


class GroupCreateResult(BaseModel):
    """
    Результат создания сбора.
    """
    success: bool
    group_id: Optional[int] = None
    message: str


class GroupStatusResult(BaseModel):
    """
    Результат проверки/изменения статуса сбора.
    """
    group_id: int
    old_status: str
    new_status: str
    participants_count: int
    final_price: Optional[Decimal] = None


# ============================================================
# МЕНЕДЖЕР СБОРОВ
# ============================================================

class GroupManager:
    """
    Менеджер групповых сборов.
    
    Управляет всей логикой работы со сборами.
    
    Пример:
        manager = GroupManager()
        
        # Создание сбора
        result = await manager.create_group(
            product_id=1,
            creator_id=42,
            min_participants=5,
            deadline_days=7
        )
        
        # Присоединение
        join_result = await manager.join_group(
            group_id=result.group_id,
            user_id=123,
            invited_by_user_id=42
        )
    """
    
    def __init__(self):
        """Инициализация менеджера."""
        self.db = get_db()
    
    # ============================================================
    # СОЗДАНИЕ СБОРА
    # ============================================================
    
    async def create_group(
        self,
        product_id: int,
        creator_id: int,
        min_participants: Optional[int] = None,
        max_participants: Optional[int] = None,
        deadline_days: Optional[int] = None
    ) -> GroupCreateResult:
        """
        Создать новый групповой сбор.
        
        Параметры:
            product_id: ID товара
            creator_id: ID пользователя-создателя
            min_participants: Минимум участников (по умолчанию из настроек)
            max_participants: Максимум участников (по умолчанию из настроек)
            deadline_days: Срок сбора в днях (по умолчанию из настроек)
        
        Возвращает:
            GroupCreateResult: Результат создания
        
        Логика:
            1. Проверяем существование товара
            2. Проверяем, нет ли уже активного сбора на этот товар
            3. Проверяем права пользователя (уровень)
            4. Создаём сбор
            5. Добавляем создателя как первого участника
        """
        # Значения по умолчанию
        min_p = min_participants or settings.DEFAULT_MIN_PARTICIPANTS
        max_p = max_participants or settings.DEFAULT_MAX_PARTICIPANTS
        days = deadline_days or settings.DEFAULT_GROUP_DEADLINE_DAYS
        
        # 1. Проверяем товар
        product = (
            self.db.table("products")
            .select("id, name, is_active, stock")
            .eq("id", product_id)
            .limit(1)
            .execute()
        )
        
        if not product.data:
            return GroupCreateResult(
                success=False,
                message="Товар не найден"
            )
        
        product_data = product.data[0]
        
        if not product_data.get("is_active"):
            return GroupCreateResult(
                success=False,
                message="Товар недоступен для заказа"
            )
        
        if product_data.get("stock", 0) <= 0:
            return GroupCreateResult(
                success=False,
                message="Товар закончился на складе"
            )
        
        # 2. Проверяем, нет ли активного сбора
        existing_group = (
            self.db.table("groups")
            .select("id")
            .eq("product_id", product_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        
        if existing_group.data:
            return GroupCreateResult(
                success=False,
                group_id=existing_group.data[0]["id"],
                message="На этот товар уже есть активный сбор. Присоединяйтесь!"
            )
        
        # 3. Проверяем уровень пользователя (опционально)
        user = (
            self.db.table("users")
            .select("level")
            .eq("id", creator_id)
            .limit(1)
            .execute()
        )
        
        if not user.data:
            return GroupCreateResult(
                success=False,
                message="Пользователь не найден"
            )
        
        # Для MVP разрешаем всем создавать сборы
        # В будущем можно ограничить: level in ("expert", "ambassador")
        
        # 4. Создаём сбор
        deadline = datetime.now(timezone.utc) + timedelta(days=days)
        
        new_group = {
            "product_id": product_id,
            "creator_id": creator_id,
            "status": "active",
            "min_participants": min_p,
            "max_participants": max_p,
            "current_count": 1,  # Создатель — первый участник
            "deadline": deadline.isoformat()
        }
        
        result = self.db.table("groups").insert(new_group).execute()
        
        if not result.data:
            return GroupCreateResult(
                success=False,
                message="Не удалось создать сбор"
            )
        
        group_id = result.data[0]["id"]
        
        # 5. Добавляем создателя как участника
        self.db.table("group_members").insert({
            "group_id": group_id,
            "user_id": creator_id,
            "invited_by_user_id": None  # Создатель никем не приглашён
        }).execute()
        
        # Обновляем статистику пользователя
        self.db.table("users").update({
            "groups_organized": self.db.table("users")
                .select("groups_organized")
                .eq("id", creator_id)
                .limit(1)
                .execute()
                .data[0].get("groups_organized", 0) + 1
        }).eq("id", creator_id).execute()
        
        return GroupCreateResult(
            success=True,
            group_id=group_id,
            message=f"Сбор на «{product_data['name']}» создан!"
        )
    
    # ============================================================
    # ПРИСОЕДИНЕНИЕ К СБОРУ
    # ============================================================
    
    async def join_group(
        self,
        group_id: int,
        user_id: int,
        invited_by_user_id: Optional[int] = None
    ) -> JoinResult:
        """
        Присоединиться к групповому сбору.
        
        Параметры:
            group_id: ID сбора
            user_id: ID пользователя
            invited_by_user_id: ID пригласившего (для реферальной статистики)
        
        Возвращает:
            JoinResult: Результат присоединения
        
        Логика:
            1. Проверяем существование сбора
            2. Проверяем, что сбор активен
            3. Проверяем, что пользователь ещё не участвует
            4. Проверяем, что не превышен лимит
            5. Добавляем участника
            6. Обновляем счётчик (триггер в БД)
            7. Проверяем, не пора ли закрыть сбор
            8. Обновляем статистику рефералов
        """
        # 1. Получаем сбор с товаром
        group = (
            self.db.table("groups")
            .select("*, products(base_price, price_tiers)")
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            return JoinResult(
                success=False,
                group_id=group_id,
                user_id=user_id,
                current_count=0,
                current_price=Decimal("0"),
                message="Сбор не найден"
            )
        
        group_data = group.data[0]
        
        # 2. Проверяем статус
        if group_data["status"] != "active":
            status_messages = {
                "completed": "Сбор уже завершён",
                "failed": "Сбор не состоялся",
                "cancelled": "Сбор отменён"
            }
            return JoinResult(
                success=False,
                group_id=group_id,
                user_id=user_id,
                current_count=group_data["current_count"],
                current_price=Decimal("0"),
                message=status_messages.get(group_data["status"], "Сбор недоступен")
            )
        
        # Проверяем дедлайн
        deadline = datetime.fromisoformat(group_data["deadline"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > deadline:
            return JoinResult(
                success=False,
                group_id=group_id,
                user_id=user_id,
                current_count=group_data["current_count"],
                current_price=Decimal("0"),
                message="Время сбора истекло"
            )
        
        # 3. Проверяем, не участвует ли уже
        existing_member = (
            self.db.table("group_members")
            .select("id")
            .eq("group_id", group_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        
        if existing_member.data:
            return JoinResult(
                success=False,
                group_id=group_id,
                user_id=user_id,
                current_count=group_data["current_count"],
                current_price=Decimal("0"),
                message="Вы уже участвуете в этом сборе"
            )
        
        # 4. Проверяем лимит
        if group_data["current_count"] >= group_data["max_participants"]:
            return JoinResult(
                success=False,
                group_id=group_id,
                user_id=user_id,
                current_count=group_data["current_count"],
                current_price=Decimal("0"),
                message="Сбор уже заполнен"
            )
        
        # Получаем данные о ценах
        product_data = group_data.get("products", {})
        price_tiers = product_data.get("price_tiers", [])
        base_price = Decimal(str(product_data.get("base_price", 0)))
        
        # Цена ДО присоединения
        old_count = group_data["current_count"]
        old_price = calculate_current_price(price_tiers, old_count, base_price)
        
        # 5. Добавляем участника
        self.db.table("group_members").insert({
            "group_id": group_id,
            "user_id": user_id,
            "invited_by_user_id": invited_by_user_id
        }).execute()
        
        # Счётчик обновится автоматически триггером в БД
        # Но для ответа нам нужно новое значение
        new_count = old_count + 1
        
        # Цена ПОСЛЕ присоединения
        new_price = calculate_current_price(price_tiers, new_count, base_price)
        price_dropped = new_price < old_price
        
        # 6. Обновляем статистику рефералов
        if invited_by_user_id:
            # Увеличиваем счётчик приглашений у пригласившего
            inviter = (
                self.db.table("users")
                .select("invited_count")
                .eq("id", invited_by_user_id)
                .limit(1)
                .execute()
            )
            
            if inviter.data:
                new_invited_count = inviter.data[0].get("invited_count", 0) + 1
                self.db.table("users").update({
                    "invited_count": new_invited_count
                }).eq("id", invited_by_user_id).execute()
        
        # 7. Проверяем, не пора ли автоматически завершить сбор
        # (достигнут максимум участников)
        if new_count >= group_data["max_participants"]:
            await self.complete_group(group_id)
        
        # Формируем сообщение
        if price_dropped:
            message = f"Отлично! Цена упала до {int(new_price):,}₽!".replace(",", " ")
        else:
            next_tier = get_next_tier_info(price_tiers, new_count)
            if next_tier:
                message = f"Вы в сборе! Ещё {next_tier['people_needed']} человек — и цена упадёт!"
            else:
                message = "Вы успешно присоединились к сбору!"
        
        return JoinResult(
            success=True,
            group_id=group_id,
            user_id=user_id,
            current_count=new_count,
            current_price=new_price,
            previous_price=old_price if price_dropped else None,
            price_dropped=price_dropped,
            message=message
        )
    
    # ============================================================
    # ЗАВЕРШЕНИЕ СБОРА
    # ============================================================
    
    async def complete_group(self, group_id: int) -> GroupStatusResult:
        """
        Успешно завершить сбор.
        
        Вызывается когда:
        - Достигнут максимум участников
        - Истёк дедлайн, но минимум набран
        - Вручную администратором
        
        Действия:
        1. Меняем статус на "completed"
        2. Фиксируем финальную цену
        3. Начисляем бонус организатору
        4. (TODO) Создаём заказы для участников
        5. (TODO) Отправляем уведомления
        """
        # Получаем сбор
        group = (
            self.db.table("groups")
            .select("*, products(base_price, price_tiers)")
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            raise ValueError(f"Сбор {group_id} не найден")
        
        group_data = group.data[0]
        old_status = group_data["status"]
        
        if old_status != "active":
            return GroupStatusResult(
                group_id=group_id,
                old_status=old_status,
                new_status=old_status,
                participants_count=group_data["current_count"],
                final_price=None
            )
        
        # Рассчитываем финальную цену
        product_data = group_data.get("products", {})
        price_tiers = product_data.get("price_tiers", [])
        base_price = Decimal(str(product_data.get("base_price", 0)))
        current_count = group_data["current_count"]
        
        final_price = calculate_current_price(price_tiers, current_count, base_price)
        
        # Обновляем статус
        self.db.table("groups").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
        
        # Начисляем бонус организатору
        await self._award_organizer_bonus(group_data, final_price)
        
        # TODO: Создать заказы для всех участников
        # TODO: Отправить уведомления
        
        return GroupStatusResult(
            group_id=group_id,
            old_status=old_status,
            new_status="completed",
            participants_count=current_count,
            final_price=final_price
        )
    
    async def fail_group(self, group_id: int) -> GroupStatusResult:
        """
        Отметить сбор как неудавшийся.
        
        Вызывается когда:
        - Истёк дедлайн, минимум не набран
        
        Действия:
        1. Меняем статус на "failed"
        2. (TODO) Возвращаем замороженные средства
        3. (TODO) Отправляем уведомления
        """
        group = (
            self.db.table("groups")
            .select("*")
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            raise ValueError(f"Сбор {group_id} не найден")
        
        group_data = group.data[0]
        old_status = group_data["status"]
        
        if old_status != "active":
            return GroupStatusResult(
                group_id=group_id,
                old_status=old_status,
                new_status=old_status,
                participants_count=group_data["current_count"]
            )
        
        # Обновляем статус
        self.db.table("groups").update({
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
        
        # TODO: Вернуть замороженные средства
        # TODO: Отправить уведомления
        
        return GroupStatusResult(
            group_id=group_id,
            old_status=old_status,
            new_status="failed",
            participants_count=group_data["current_count"]
        )
    
    async def cancel_group(self, group_id: int, user_id: int) -> GroupStatusResult:
        """
        Отменить сбор.
        
        Может отменить только создатель или админ.
        """
        group = (
            self.db.table("groups")
            .select("*")
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            raise ValueError(f"Сбор {group_id} не найден")
        
        group_data = group.data[0]
        
        # Проверяем права
        if group_data["creator_id"] != user_id:
            raise PermissionError("Только создатель может отменить сбор")
        
        old_status = group_data["status"]
        
        if old_status != "active":
            return GroupStatusResult(
                group_id=group_id,
                old_status=old_status,
                new_status=old_status,
                participants_count=group_data["current_count"]
            )
        
        # Обновляем статус
        self.db.table("groups").update({
            "status": "cancelled",
            "completed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
        
        return GroupStatusResult(
            group_id=group_id,
            old_status=old_status,
            new_status="cancelled",
            participants_count=group_data["current_count"]
        )
    
    # ============================================================
    # ПРОВЕРКА ПРОСРОЧЕННЫХ СБОРОВ (CRON)
    # ============================================================
    
    async def check_expired_groups(self) -> List[GroupStatusResult]:
        """
        Проверить и обработать просроченные сборы.
        
        Вызывается по cron (каждые 5-15 минут).
        
        Логика:
        - Если deadline прошёл и current_count >= min_participants → completed
        - Если deadline прошёл и current_count < min_participants → failed
        """
        now = datetime.now(timezone.utc).isoformat()
        
        # Находим просроченные активные сборы
        expired = (
            self.db.table("groups")
            .select("*")
            .eq("status", "active")
            .lt("deadline", now)
            .execute()
        )
        
        results = []
        
        for group_data in (expired.data or []):
            group_id = group_data["id"]
            current_count = group_data["current_count"]
            min_participants = group_data["min_participants"]
            
            if current_count >= min_participants:
                # Успех
                result = await self.complete_group(group_id)
            else:
                # Неудача
                result = await self.fail_group(group_id)
            
            results.append(result)
        
        return results
    
    # ============================================================
    # БОНУСЫ ОРГАНИЗАТОРА
    # ============================================================
    
    async def _award_organizer_bonus(
        self,
        group_data: dict,
        final_price: Decimal
    ) -> Decimal:
        """
        Начислить бонус организатору сбора.
        
        Бонус зависит от:
        - Уровня пользователя
        - Суммы сбора
        
        Параметры:
            group_data: Данные сбора
            final_price: Финальная цена товара
        
        Возвращает:
            Decimal: Сумма бонуса
        """
        creator_id = group_data["creator_id"]
        current_count = group_data["current_count"]
        
        # Получаем уровень организатора
        user = (
            self.db.table("users")
            .select("level, total_savings")
            .eq("id", creator_id)
            .limit(1)
            .execute()
        )
        
        if not user.data:
            return Decimal("0")
        
        user_data = user.data[0]
        level = user_data.get("level", "newcomer")
        
        # Множитель по уровню
        level_multipliers = {
            "newcomer": 1.0,
            "buyer": 1.0,
            "activist": 1.5,
            "expert": 2.0,
            "ambassador": 2.5
        }
        multiplier = level_multipliers.get(level, 1.0)
        
        # Базовый процент бонуса
        base_percent = settings.ORGANIZER_BONUS_PERCENT / 100
        
        # Общая сумма сбора
        total_amount = final_price * current_count
        
        # Бонус
        bonus = total_amount * Decimal(str(base_percent)) * Decimal(str(multiplier))
        bonus = bonus.quantize(Decimal("0.01"))
        
        # Добавляем к экономии пользователя
        new_savings = Decimal(str(user_data.get("total_savings", 0))) + bonus
        
        self.db.table("users").update({
            "total_savings": float(new_savings)
        }).eq("id", creator_id).execute()
        
        return bonus
    
    # ============================================================
    # ПОЛУЧЕНИЕ ДАННЫХ ДЛЯ ШЕРИНГА
    # ============================================================
    
    async def get_share_data(
        self,
        group_id: int,
        user_id: int,
        bot_username: str
    ) -> dict:
        """
        Получить данные для шеринга сбора.
        
        Параметры:
            group_id: ID сбора
            user_id: ID пользователя (для реферальной ссылки)
            bot_username: Username бота
        
        Возвращает:
            dict: Данные для шеринга
                {
                    "text": "Текст сообщения",
                    "url": "Deep link",
                    "button_text": "Текст кнопки"
                }
        """
        # Получаем сбор с товаром
        group = (
            self.db.table("groups")
            .select("*, products(name, base_price, price_tiers)")
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            raise ValueError(f"Сбор {group_id} не найден")
        
        group_data = group.data[0]
        product_data = group_data.get("products", {})
        
        product_name = product_data.get("name", "Товар")
        base_price = Decimal(str(product_data.get("base_price", 0)))
        price_tiers = product_data.get("price_tiers", [])
        current_count = group_data["current_count"]
        
        # Генерируем текст
        text = generate_share_text(
            product_name=product_name,
            price_tiers=price_tiers,
            base_price=base_price,
            participants_count=current_count
        )
        
        # Генерируем ссылку
        from utils.telegram import generate_share_link
        url = generate_share_link(group_id, user_id, bot_username)
        
        return {
            "text": text,
            "url": url,
            "button_text": "Присоединиться"
        }
    
    # ============================================================
    # СТАТИСТИКА
    # ============================================================
    
    async def get_user_groups_stats(self, user_id: int) -> dict:
        """
        Получить статистику участия пользователя в сборах.
        
        Параметры:
            user_id: ID пользователя
        
        Возвращает:
            dict: Статистика
        """
        # Сборы где пользователь — участник
        memberships = (
            self.db.table("group_members")
            .select("group_id, groups(status)")
            .eq("user_id", user_id)
            .execute()
        )
        
        stats = {
            "total_participated": 0,
            "active": 0,
            "completed": 0,
            "failed": 0
        }
        
        for member in (memberships.data or []):
            stats["total_participated"] += 1
            group = member.get("groups", {})
            status = group.get("status", "active")
            if status in stats:
                stats[status] += 1
        
        # Сборы где пользователь — организатор
        organized = (
            self.db.table("groups")
            .select("id", count="exact")
            .eq("creator_id", user_id)
            .execute()
        )
        stats["organized"] = organized.count or 0
        
        # Количество приглашённых в сборы этого пользователя
        invited = (
            self.db.table("group_members")
            .select("id", count="exact")
            .eq("invited_by_user_id", user_id)
            .execute()
        )
        stats["people_invited"] = invited.count or 0
        
        return stats


# ============================================================
# СИНГЛТОН
# ============================================================

_group_manager: Optional[GroupManager] = None


def get_group_manager() -> GroupManager:
    """
    Получить экземпляр GroupManager (синглтон).
    """
    global _group_manager
    if _group_manager is None:
        _group_manager = GroupManager()
    return _group_manager
