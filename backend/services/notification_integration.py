"""
Модуль: services/notification_integration.py
Описание: Интеграция уведомлений с бизнес-логикой приложения
Проект: GroupBuy Mini App

Этот модуль связывает NotificationService с остальными частями приложения.
Содержит готовые функции для отправки уведомлений в типичных сценариях.

Использование:
    from services.notification_integration import (
        notify_on_join,
        notify_group_completed,
        notify_group_failed,
        notify_expiring_groups
    )
    
    # Когда кто-то присоединился к сбору
    await notify_on_join(group_id=42, new_member_id=123)
    
    # Когда сбор завершился успешно
    await notify_group_completed(group_id=42)
"""

import asyncio
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, timezone

import sys
sys.path.append("..")

from database.connection import get_db
from services.notification_service import (
    get_notification_service,
    NotificationType
)


def format_price(amount) -> str:
    """Форматировать цену: 19000 → '19 000 ₽'"""
    try:
        value = int(float(amount))
        return f"{value:,}₽".replace(",", " ")
    except:
        return f"{amount}₽"


# ============================================================
# УВЕДОМЛЕНИЯ О СБОРАХ
# ============================================================

async def notify_on_join(
    group_id: int,
    new_member_id: int,
    invited_by_id: Optional[int] = None
) -> bool:
    """
    Отправить уведомление организатору о новом участнике.
    
    Вызывается после успешного присоединения к сбору.
    
    Параметры:
        group_id: ID сбора
        new_member_id: ID нового участника
        invited_by_id: ID пригласившего (для реферальных бонусов)
    
    Возвращает:
        bool: Успешно ли отправлено
    
    Пример:
        # В group_manager.py после успешного join
        await notify_on_join(group_id=42, new_member_id=123)
    """
    db = get_db()
    notifier = get_notification_service()
    
    try:
        # Получаем данные сбора
        group = (
            db.table("groups")
            .select("""
                id, creator_id, current_count, min_participants, max_participants,
                products(id, name, image_url, base_price)
            """)
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            return False
        
        group_data = group.data[0]
        creator_id = group_data["creator_id"]
        
        # Не уведомляем, если присоединился сам организатор
        if new_member_id == creator_id:
            return True
        
        # Получаем данные организатора (telegram_id)
        creator = (
            db.table("users")
            .select("telegram_id")
            .eq("id", creator_id)
            .limit(1)
            .execute()
        )
        
        if not creator.data or not creator.data[0].get("telegram_id"):
            print(f"⚠️ Организатор {creator_id} не имеет telegram_id")
            return False
        
        creator_telegram_id = creator.data[0]["telegram_id"]
        
        # Получаем имя нового участника
        new_member = (
            db.table("users")
            .select("first_name, username")
            .eq("id", new_member_id)
            .limit(1)
            .execute()
        )
        
        member_name = "Новый участник"
        if new_member.data:
            member_name = new_member.data[0].get("first_name") or \
                         new_member.data[0].get("username") or \
                         "Участник"
        
        # Отправляем уведомление организатору
        product_data = group_data.get("products", {})
        
        success = await notifier.notify_group_joined(
            organizer_telegram_id=creator_telegram_id,
            participant_name=member_name,
            group_id=group_id,
            product_name=product_data.get("name", "Товар"),
            current_count=group_data["current_count"],
            min_participants=group_data["min_participants"]
        )
        
        return success
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_on_join: {e}")
        return False


async def notify_group_completed(group_id: int) -> dict:
    """
    Уведомить всех участников о успешном завершении сбора.
    
    Параметры:
        group_id: ID сбора
    
    Возвращает:
        dict: {"success": N, "failed": M}
    
    Пример:
        result = await notify_group_completed(42)
        print(f"Уведомлено: {result['success']}")
    """
    db = get_db()
    notifier = get_notification_service()
    
    result = {"success": 0, "failed": 0}
    
    try:
        # Получаем данные сбора
        group = (
            db.table("groups")
            .select("""
                id, current_count,
                products(name, base_price, price_tiers)
            """)
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            return result
        
        group_data = group.data[0]
        product_data = group_data.get("products", {})
        
        # Рассчитываем финальную цену
        from services.price_calculator import calculate_current_price
        
        price_tiers = product_data.get("price_tiers", [])
        base_price = Decimal(str(product_data.get("base_price", 0)))
        current_count = group_data["current_count"]
        
        final_price = calculate_current_price(price_tiers, current_count, base_price)
        savings = base_price - final_price
        
        # Получаем всех участников
        members = (
            db.table("group_members")
            .select("user_id, users(telegram_id)")
            .eq("group_id", group_id)
            .execute()
        )
        
        if not members.data:
            return result
        
        # Собираем telegram_ids
        telegram_ids = []
        for member in members.data:
            user_data = member.get("users", {})
            telegram_id = user_data.get("telegram_id") if user_data else None
            if telegram_id:
                telegram_ids.append(telegram_id)
        
        if not telegram_ids:
            return result
        
        # Отправляем уведомления
        data = {
            "group_id": group_id,
            "product_name": product_data.get("name", "Товар"),
            "current_count": current_count,
            "final_price": format_price(final_price),
            "savings": format_price(savings)
        }
        
        result = await notifier.notify_group_participants(
            participant_telegram_ids=telegram_ids,
            notification_type=NotificationType.GROUP_COMPLETED,
            data=data
        )
        
        print(f"✅ Сбор #{group_id}: уведомлено {result['success']} участников")
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_group_completed: {e}")
    
    return result


async def notify_group_failed(group_id: int) -> dict:
    """
    Уведомить всех участников о несостоявшемся сборе.
    
    Параметры:
        group_id: ID сбора
    
    Возвращает:
        dict: {"success": N, "failed": M}
    """
    db = get_db()
    notifier = get_notification_service()
    
    result = {"success": 0, "failed": 0}
    
    try:
        # Получаем данные сбора
        group = (
            db.table("groups")
            .select("""
                id, current_count, min_participants,
                products(name)
            """)
            .eq("id", group_id)
            .limit(1)
            .execute()
        )
        
        if not group.data:
            return result
        
        group_data = group.data[0]
        product_data = group_data.get("products", {})
        
        # Получаем всех участников
        members = (
            db.table("group_members")
            .select("user_id, users(telegram_id)")
            .eq("group_id", group_id)
            .execute()
        )
        
        if not members.data:
            return result
        
        # Собираем telegram_ids
        telegram_ids = []
        for member in members.data:
            user_data = member.get("users", {})
            telegram_id = user_data.get("telegram_id") if user_data else None
            if telegram_id:
                telegram_ids.append(telegram_id)
        
        if not telegram_ids:
            return result
        
        # Отправляем уведомления
        data = {
            "group_id": group_id,
            "product_name": product_data.get("name", "Товар"),
            "current_count": group_data["current_count"],
            "min_participants": group_data["min_participants"]
        }
        
        result = await notifier.notify_group_participants(
            participant_telegram_ids=telegram_ids,
            notification_type=NotificationType.GROUP_FAILED,
            data=data
        )
        
        print(f"😔 Сбор #{group_id}: уведомлено {result['success']} участников о неудаче")
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_group_failed: {e}")
    
    return result


async def notify_expiring_groups(hours_before: int = 2) -> dict:
    """
    Отправить уведомления о скором завершении сборов.
    
    Находит сборы, до дедлайна которых осталось менее N часов,
    и отправляет напоминания участникам.
    
    Параметры:
        hours_before: За сколько часов до дедлайна уведомлять
    
    Возвращает:
        dict: {"groups_notified": N, "total_sent": M}
    
    Пример:
        # Вызывать из cron каждый час
        await notify_expiring_groups(hours_before=2)
    """
    from datetime import timedelta
    
    db = get_db()
    notifier = get_notification_service()
    
    result = {"groups_notified": 0, "total_sent": 0}
    
    try:
        now = datetime.now(timezone.utc)
        deadline_threshold = now + timedelta(hours=hours_before)
        
        # Находим сборы, которые скоро завершатся
        # И которые ещё не были уведомлены (нужно добавить поле expiry_notified)
        expiring_groups = (
            db.table("groups")
            .select("""
                id, current_count, min_participants, deadline,
                products(name)
            """)
            .eq("status", "active")
            .lte("deadline", deadline_threshold.isoformat())
            .gte("deadline", now.isoformat())
            .execute()
        )
        
        if not expiring_groups.data:
            print("  Нет сборов с истекающим дедлайном")
            return result
        
        for group_data in expiring_groups.data:
            group_id = group_data["id"]
            product_data = group_data.get("products", {})
            
            # Получаем участников
            members = (
                db.table("group_members")
                .select("users(telegram_id)")
                .eq("group_id", group_id)
                .execute()
            )
            
            telegram_ids = []
            for member in members.data or []:
                user_data = member.get("users", {})
                telegram_id = user_data.get("telegram_id") if user_data else None
                if telegram_id:
                    telegram_ids.append(telegram_id)
            
            if not telegram_ids:
                continue
            
            # Отправляем уведомления
            data = {
                "group_id": group_id,
                "product_name": product_data.get("name", "Товар"),
                "current_count": group_data["current_count"],
                "min_participants": group_data["min_participants"]
            }
            
            send_result = await notifier.notify_group_participants(
                participant_telegram_ids=telegram_ids,
                notification_type=NotificationType.GROUP_EXPIRING,
                data=data
            )
            
            result["groups_notified"] += 1
            result["total_sent"] += send_result.get("success", 0)
            
            print(f"⏰ Сбор #{group_id}: напомнили {send_result['success']} участникам")
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_expiring_groups: {e}")
    
    return result


# ============================================================
# УВЕДОМЛЕНИЯ О ЗАКАЗАХ
# ============================================================

async def notify_order_shipped(
    order_id: int,
    tracking_number: str,
    delivery_service: str = "СДЭК",
    estimated_date: str = "3-5 дней"
) -> bool:
    """
    Уведомить покупателя об отправке заказа.
    
    Параметры:
        order_id: ID заказа
        tracking_number: Трек-номер
        delivery_service: Служба доставки
        estimated_date: Ожидаемая дата
    
    Возвращает:
        bool: Успешно ли отправлено
    """
    db = get_db()
    notifier = get_notification_service()
    
    try:
        # Получаем данные заказа
        order = (
            db.table("orders")
            .select("""
                id, user_id,
                users(telegram_id),
                groups(products(name))
            """)
            .eq("id", order_id)
            .limit(1)
            .execute()
        )
        
        if not order.data:
            return False
        
        order_data = order.data[0]
        user_data = order_data.get("users", {})
        telegram_id = user_data.get("telegram_id") if user_data else None
        
        if not telegram_id:
            return False
        
        # Получаем название товара
        groups = order_data.get("groups", {})
        products = groups.get("products", {}) if groups else {}
        product_name = products.get("name", "Товар") if products else "Товар"
        
        return await notifier.notify_order_shipped(
            telegram_id=telegram_id,
            order_id=order_id,
            product_name=product_name,
            tracking_number=tracking_number,
            delivery_service=delivery_service,
            estimated_date=estimated_date
        )
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_order_shipped: {e}")
        return False


# ============================================================
# УВЕДОМЛЕНИЯ О УРОВНЯХ
# ============================================================

async def notify_level_up(user_id: int, old_level: str, new_level: str) -> bool:
    """
    Уведомить пользователя о повышении уровня.
    
    Параметры:
        user_id: ID пользователя
        old_level: Старый уровень
        new_level: Новый уровень
    
    Возвращает:
        bool: Успешно ли отправлено
    """
    db = get_db()
    notifier = get_notification_service()
    
    # Эмодзи и названия уровней
    level_info = {
        "novice": ("🌱", "Новичок", []),
        "buyer": ("🛒", "Покупатель", ["Доступ к эксклюзивным сборам"]),
        "activist": ("⭐", "Активист", ["Скидка 2% на все заказы", "Приоритетная поддержка"]),
        "expert": ("🔥", "Эксперт", ["Скидка 3% на все заказы", "Ранний доступ к новинкам"]),
        "ambassador": ("👑", "Амбассадор", ["Скидка 5% на все заказы", "Бесплатная доставка", "VIP-поддержка"])
    }
    
    try:
        # Получаем telegram_id
        user = (
            db.table("users")
            .select("telegram_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        
        if not user.data:
            return False
        
        telegram_id = user.data[0].get("telegram_id")
        if not telegram_id:
            return False
        
        old_info = level_info.get(old_level, ("❓", old_level, []))
        new_info = level_info.get(new_level, ("❓", new_level, []))
        
        return await notifier.notify_level_up(
            telegram_id=telegram_id,
            old_level=old_info[1],
            new_level=new_info[1],
            old_level_emoji=old_info[0],
            new_level_emoji=new_info[0],
            benefits=new_info[2] if new_info[2] else ["Новые возможности скоро появятся!"]
        )
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_level_up: {e}")
        return False


# ============================================================
# ПРИВЕТСТВИЕ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

async def notify_welcome(user_id: int) -> bool:
    """
    Отправить приветственное сообщение новому пользователю.
    
    Параметры:
        user_id: ID пользователя
    
    Возвращает:
        bool: Успешно ли отправлено
    """
    db = get_db()
    notifier = get_notification_service()
    
    try:
        user = (
            db.table("users")
            .select("telegram_id, first_name")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        
        if not user.data:
            return False
        
        user_data = user.data[0]
        telegram_id = user_data.get("telegram_id")
        first_name = user_data.get("first_name", "друг")
        
        if not telegram_id:
            return False
        
        return await notifier.notify_welcome(
            telegram_id=telegram_id,
            first_name=first_name
        )
        
    except Exception as e:
        print(f"⚠️ Ошибка notify_welcome: {e}")
        return False
