"""
Модуль: services/notification_service.py
Описание: Сервис уведомлений через Telegram Bot API
Проект: GroupBuy Mini App

Отправляет пользователям уведомления о событиях:
- Сборы: новый участник, завершение, провал
- Заказы: оплата, отправка, доставка
- Бонусы: повышение уровня, реферальные бонусы

Как это работает (представь):
    ┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
    │ GroupManager│────▶│NotificationService│────▶│ Telegram API│
    │ PaymentServ │     │ (этот файл)      │     │ (Bot API)   │
    └─────────────┘     └──────────────────┘     └─────────────┘
    
    Когда что-то происходит (человек присоединился к сбору),
    вызывается NotificationService, который отправляет
    красивое сообщение пользователю через бота.

Использование:
    from services.notification_service import get_notification_service
    
    notifier = get_notification_service()
    
    # Кто-то присоединился к сбору
    await notifier.notify_group_joined(
        organizer_telegram_id=123456789,
        participant_name="Маша",
        group_id=42,
        product_name="Корейский крем",
        current_count=5,
        min_participants=10
    )
"""

import asyncio
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import httpx

import sys
sys.path.append("..")
from config import settings


# ============================================================
# ТИПЫ УВЕДОМЛЕНИЙ
# ============================================================

class NotificationType(str, Enum):
    """
    Типы уведомлений.
    
    Каждый тип имеет свой шаблон сообщения и эмодзи.
    """
    # Сборы
    GROUP_JOINED = "group_joined"           # Кто-то присоединился
    GROUP_COMPLETED = "group_completed"     # Сбор успешно завершён
    GROUP_FAILED = "group_failed"           # Сбор не состоялся
    GROUP_EXPIRING = "group_expiring"       # Скоро дедлайн (за 2 часа)
    
    # Заказы
    ORDER_CREATED = "order_created"         # Заказ создан
    ORDER_PAID = "order_paid"               # Оплата получена
    ORDER_SHIPPED = "order_shipped"         # Заказ отправлен
    ORDER_DELIVERED = "order_delivered"     # Заказ доставлен
    ORDER_CANCELLED = "order_cancelled"     # Заказ отменён
    
    # Бонусы и уровни
    LEVEL_UP = "level_up"                   # Повышение уровня
    REFERRAL_BONUS = "referral_bonus"       # Бонус за приглашение
    
    # Система
    WELCOME = "welcome"                      # Приветствие нового пользователя


# ============================================================
# ШАБЛОНЫ СООБЩЕНИЙ
# ============================================================

# Словарь шаблонов: {тип: (заголовок, текст)}
# Используем {placeholder} для подстановки данных
MESSAGE_TEMPLATES: Dict[NotificationType, tuple] = {
    
    # ─── СБОРЫ ───
    
    NotificationType.GROUP_JOINED: (
        "👥 Новый участник!",
        """К вашему сбору присоединился <b>{participant_name}</b>!

🛍 <b>{product_name}</b>
👥 Участников: <b>{current_count}</b> из {min_participants}
{progress_bar}

{motivation_text}"""
    ),
    
    NotificationType.GROUP_COMPLETED: (
        "🎉 Сбор завершён!",
        """Поздравляем! Ваш сбор успешно завершён!

🛍 <b>{product_name}</b>
👥 Участников: <b>{current_count}</b>
💰 Финальная цена: <b>{final_price}</b>
💵 Вы сэкономили: <b>{savings}</b>

Скоро товар будет отправлен!"""
    ),
    
    NotificationType.GROUP_FAILED: (
        "😔 Сбор не состоялся",
        """К сожалению, сбор не набрал достаточно участников.

🛍 <b>{product_name}</b>
👥 Набрано: {current_count} из {min_participants}

💳 Деньги будут возвращены автоматически в течение 24 часов.

Не расстраивайтесь! Создайте новый сбор и пригласите больше друзей 💪"""
    ),
    
    NotificationType.GROUP_EXPIRING: (
        "⏰ Сбор скоро завершится!",
        """До конца сбора осталось 2 часа!

🛍 <b>{product_name}</b>
👥 Участников: <b>{current_count}</b> из {min_participants}

{action_text}"""
    ),
    
    # ─── ЗАКАЗЫ ───
    
    NotificationType.ORDER_CREATED: (
        "🛒 Заказ создан",
        """Вы присоединились к сбору!

🛍 <b>{product_name}</b>
💰 Сумма: <b>{amount}</b>
📦 Заказ №{order_id}

💳 Деньги заморожены до завершения сбора.
Пригласите друзей, чтобы снизить цену!"""
    ),
    
    NotificationType.ORDER_PAID: (
        "✅ Оплата получена",
        """Сбор завершён, оплата списана!

🛍 <b>{product_name}</b>
💰 Сумма: <b>{amount}</b>
📦 Заказ №{order_id}

Скоро начнём комплектацию заказа."""
    ),
    
    NotificationType.ORDER_SHIPPED: (
        "🚚 Заказ отправлен!",
        """Ваш заказ в пути!

📦 Заказ №{order_id}
🛍 <b>{product_name}</b>
📮 Трек-номер: <code>{tracking_number}</code>
🚛 Служба доставки: {delivery_service}

Ожидаемая дата доставки: <b>{estimated_date}</b>"""
    ),
    
    NotificationType.ORDER_DELIVERED: (
        "📬 Заказ доставлен!",
        """Ваш заказ доставлен!

📦 Заказ №{order_id}
🛍 <b>{product_name}</b>

Спасибо за покупку! 🙏
Оставьте отзыв, это поможет другим покупателям."""
    ),
    
    NotificationType.ORDER_CANCELLED: (
        "❌ Заказ отменён",
        """Ваш заказ был отменён.

📦 Заказ №{order_id}
🛍 <b>{product_name}</b>

💳 Деньги будут возвращены в течение 24 часов."""
    ),
    
    # ─── БОНУСЫ ───
    
    NotificationType.LEVEL_UP: (
        "🎊 Новый уровень!",
        """Поздравляем с повышением!

{old_level_emoji} {old_level_name} → {new_level_emoji} <b>{new_level_name}</b>

🎁 Ваши новые привилегии:
{benefits}

Продолжайте в том же духе! 💪"""
    ),
    
    NotificationType.REFERRAL_BONUS: (
        "🎁 Реферальный бонус!",
        """Ваш друг <b>{friend_name}</b> сделал заказ!

💰 Ваш бонус: <b>{bonus_amount}</b>
📊 Всего приглашено: {total_invited}

Продолжайте приглашать друзей и получать бонусы!"""
    ),
    
    # ─── СИСТЕМА ───
    
    NotificationType.WELCOME: (
        "👋 Добро пожаловать в GroupBuy!",
        """Привет, <b>{first_name}</b>!

Теперь ты можешь:
✅ Покупать товары со скидкой до 50%
✅ Создавать свои сборы
✅ Приглашать друзей и получать бонусы

🛍 <b>Как это работает:</b>
1. Выбери товар
2. Создай сбор или присоединись к существующему
3. Пригласи друзей — чем больше людей, тем ниже цена
4. Когда сбор завершится — все получат товар по лучшей цене!

Начни прямо сейчас 👇"""
    ),
}


# ============================================================
# СЕРВИС УВЕДОМЛЕНИЙ
# ============================================================

class NotificationService:
    """
    Сервис для отправки уведомлений через Telegram Bot API.
    
    Использует httpx для асинхронных запросов к API Telegram.
    Не требует aiogram или python-telegram-bot.
    
    Пример:
        service = NotificationService()
        
        await service.send_notification(
            telegram_id=123456789,
            notification_type=NotificationType.GROUP_JOINED,
            data={
                "participant_name": "Маша",
                "product_name": "Крем для лица",
                "current_count": 5,
                "min_participants": 10
            }
        )
    """
    
    # URL Telegram Bot API
    API_BASE = "https://api.telegram.org/bot{token}"
    
    def __init__(self, bot_token: str = None):
        """
        Инициализация сервиса.
        
        Параметры:
            bot_token: Токен бота (если None — берётся из настроек)
        """
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.api_url = self.API_BASE.format(token=self.bot_token)
        
        # Получаем username бота для ссылок
        self.bot_username = None
        
        if not self.bot_token:
            print("⚠️  NotificationService: TELEGRAM_BOT_TOKEN не настроен")
    
    async def _get_bot_username(self) -> str:
        """Получить username бота (кэшируется)."""
        if self.bot_username:
            return self.bot_username
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url}/getMe")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        self.bot_username = data["result"]["username"]
                        return self.bot_username
        except Exception as e:
            print(f"⚠️  Не удалось получить username бота: {e}")
        
        return "drujno_bot"  # Fallback
    
    # ============================================================
    # ОСНОВНОЙ МЕТОД ОТПРАВКИ
    # ============================================================
    
    async def send_message(
        self,
        telegram_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict = None,
        disable_notification: bool = False
    ) -> bool:
        """
        Отправить сообщение пользователю.
        
        Параметры:
            telegram_id: ID пользователя в Telegram
            text: Текст сообщения (поддерживает HTML)
            parse_mode: Режим парсинга (HTML, Markdown)
            reply_markup: Клавиатура (InlineKeyboard)
            disable_notification: Тихое уведомление
        
        Возвращает:
            bool: True если успешно
        
        Пример:
            success = await service.send_message(
                telegram_id=123456789,
                text="<b>Привет!</b> Это тест.",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Открыть", "url": "https://t.me/bot/app"}
                    ]]
                }
            )
        """
        if not self.bot_token:
            print("⚠️  Нет токена бота — уведомление не отправлено")
            return False
        
        payload = {
            "chat_id": telegram_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification
        }
        
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.api_url}/sendMessage",
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("ok"):
                        return True
                    else:
                        print(f"⚠️  Telegram API error: {result.get('description')}")
                else:
                    print(f"⚠️  HTTP {response.status_code}: {response.text[:200]}")
                    
        except httpx.TimeoutException:
            print(f"⚠️  Timeout при отправке сообщения {telegram_id}")
        except Exception as e:
            print(f"⚠️  Ошибка отправки уведомления: {e}")
        
        return False
    
    async def send_notification(
        self,
        telegram_id: int,
        notification_type: NotificationType,
        data: dict,
        buttons: List[dict] = None
    ) -> bool:
        """
        Отправить типизированное уведомление.
        
        Параметры:
            telegram_id: ID пользователя в Telegram
            notification_type: Тип уведомления
            data: Данные для подстановки в шаблон
            buttons: Дополнительные кнопки
        
        Возвращает:
            bool: True если успешно
        
        Пример:
            await service.send_notification(
                telegram_id=123456789,
                notification_type=NotificationType.GROUP_JOINED,
                data={
                    "participant_name": "Маша",
                    "product_name": "Крем",
                    "current_count": 5,
                    "min_participants": 10
                }
            )
        """
        # Получаем шаблон
        template = MESSAGE_TEMPLATES.get(notification_type)
        if not template:
            print(f"⚠️  Неизвестный тип уведомления: {notification_type}")
            return False
        
        title, body = template
        
        # Добавляем вспомогательные данные
        data = self._enrich_data(notification_type, data)
        
        # Формируем текст
        try:
            text = f"<b>{title}</b>\n\n{body.format(**data)}"
        except KeyError as e:
            print(f"⚠️  Не хватает данных для шаблона: {e}")
            return False
        
        # Формируем клавиатуру
        reply_markup = None
        if buttons:
            reply_markup = {"inline_keyboard": [buttons]}
        else:
            # Дефолтные кнопки по типу уведомления
            reply_markup = await self._get_default_buttons(notification_type, data)
        
        return await self.send_message(
            telegram_id=telegram_id,
            text=text,
            reply_markup=reply_markup
        )
    
    def _enrich_data(self, notification_type: NotificationType, data: dict) -> dict:
        """
        Дополнить данные вспомогательными полями.
        
        Добавляет:
        - progress_bar: Визуальный прогресс-бар
        - motivation_text: Мотивационный текст
        - action_text: Призыв к действию
        """
        enriched = data.copy()
        
        # Прогресс-бар для сборов
        if "current_count" in data and "min_participants" in data:
            current = data["current_count"]
            total = data["min_participants"]
            progress = min(current / total, 1.0) if total > 0 else 0
            
            # Визуальный прогресс-бар
            filled = int(progress * 10)
            empty = 10 - filled
            enriched["progress_bar"] = f"{'▓' * filled}{'░' * empty} {int(progress * 100)}%"
            
            # Мотивационный текст
            remaining = total - current
            if remaining > 0:
                enriched["motivation_text"] = f"🎯 Осталось пригласить: {remaining} чел."
            else:
                enriched["motivation_text"] = "✅ Минимум набран! Но можно больше для лучшей цены."
        
        # Текст для истекающего сбора
        if notification_type == NotificationType.GROUP_EXPIRING:
            current = data.get("current_count", 0)
            minimum = data.get("min_participants", 0)
            if current >= minimum:
                enriched["action_text"] = "✅ Минимум уже набран — сбор состоится!"
            else:
                remaining = minimum - current
                enriched["action_text"] = f"⚠️ Нужно ещё {remaining} чел. Поделитесь ссылкой!"
        
        return enriched
    
    async def _get_default_buttons(
        self, 
        notification_type: NotificationType, 
        data: dict
    ) -> Optional[dict]:
        """Получить дефолтные кнопки для типа уведомления."""
        
        bot_username = await self._get_bot_username()
        buttons = []
        
        if notification_type in [
            NotificationType.GROUP_JOINED,
            NotificationType.GROUP_EXPIRING
        ]:
            group_id = data.get("group_id")
            if group_id:
                buttons.append({
                    "text": "👥 Открыть сбор",
                    "url": f"https://t.me/{bot_username}/app?startapp=g_{group_id}"
                })
                buttons.append({
                    "text": "📤 Поделиться",
                    "url": f"https://t.me/share/url?url=https://t.me/{bot_username}/app?startapp=g_{group_id}&text=Присоединяйся к сбору!"
                })
        
        elif notification_type == NotificationType.GROUP_COMPLETED:
            buttons.append({
                "text": "📦 Мои заказы",
                "url": f"https://t.me/{bot_username}/app?startapp=orders"
            })
        
        elif notification_type == NotificationType.GROUP_FAILED:
            buttons.append({
                "text": "🛍 Каталог",
                "url": f"https://t.me/{bot_username}/app?startapp=catalog"
            })
        
        elif notification_type in [
            NotificationType.ORDER_CREATED,
            NotificationType.ORDER_PAID,
            NotificationType.ORDER_SHIPPED,
            NotificationType.ORDER_DELIVERED
        ]:
            order_id = data.get("order_id")
            if order_id:
                buttons.append({
                    "text": "📦 Детали заказа",
                    "url": f"https://t.me/{bot_username}/app?startapp=order_{order_id}"
                })
        
        elif notification_type == NotificationType.WELCOME:
            buttons.append({
                "text": "🛍 Начать покупки",
                "url": f"https://t.me/{bot_username}/app"
            })
        
        if buttons:
            # Разбиваем на строки по 2 кнопки
            rows = []
            for i in range(0, len(buttons), 2):
                rows.append(buttons[i:i+2])
            return {"inline_keyboard": rows}
        
        return None
    
    # ============================================================
    # УДОБНЫЕ МЕТОДЫ ДЛЯ КОНКРЕТНЫХ УВЕДОМЛЕНИЙ
    # ============================================================
    
    async def notify_group_joined(
        self,
        organizer_telegram_id: int,
        participant_name: str,
        group_id: int,
        product_name: str,
        current_count: int,
        min_participants: int
    ) -> bool:
        """
        Уведомить организатора о новом участнике.
        
        Пример:
            await notifier.notify_group_joined(
                organizer_telegram_id=123456789,
                participant_name="Маша",
                group_id=42,
                product_name="Корейский крем",
                current_count=5,
                min_participants=10
            )
        """
        return await self.send_notification(
            telegram_id=organizer_telegram_id,
            notification_type=NotificationType.GROUP_JOINED,
            data={
                "participant_name": participant_name,
                "group_id": group_id,
                "product_name": product_name,
                "current_count": current_count,
                "min_participants": min_participants
            }
        )
    
    async def notify_group_completed(
        self,
        telegram_id: int,
        group_id: int,
        product_name: str,
        current_count: int,
        final_price: str,
        savings: str
    ) -> bool:
        """Уведомить участника о успешном завершении сбора."""
        return await self.send_notification(
            telegram_id=telegram_id,
            notification_type=NotificationType.GROUP_COMPLETED,
            data={
                "group_id": group_id,
                "product_name": product_name,
                "current_count": current_count,
                "final_price": final_price,
                "savings": savings
            }
        )
    
    async def notify_group_failed(
        self,
        telegram_id: int,
        group_id: int,
        product_name: str,
        current_count: int,
        min_participants: int
    ) -> bool:
        """Уведомить участника о несостоявшемся сборе."""
        return await self.send_notification(
            telegram_id=telegram_id,
            notification_type=NotificationType.GROUP_FAILED,
            data={
                "group_id": group_id,
                "product_name": product_name,
                "current_count": current_count,
                "min_participants": min_participants
            }
        )
    
    async def notify_group_expiring(
        self,
        telegram_id: int,
        group_id: int,
        product_name: str,
        current_count: int,
        min_participants: int
    ) -> bool:
        """Уведомить о скором завершении сбора (за 2 часа)."""
        return await self.send_notification(
            telegram_id=telegram_id,
            notification_type=NotificationType.GROUP_EXPIRING,
            data={
                "group_id": group_id,
                "product_name": product_name,
                "current_count": current_count,
                "min_participants": min_participants
            }
        )
    
    async def notify_order_shipped(
        self,
        telegram_id: int,
        order_id: int,
        product_name: str,
        tracking_number: str,
        delivery_service: str = "СДЭК",
        estimated_date: str = "3-5 дней"
    ) -> bool:
        """Уведомить об отправке заказа."""
        return await self.send_notification(
            telegram_id=telegram_id,
            notification_type=NotificationType.ORDER_SHIPPED,
            data={
                "order_id": order_id,
                "product_name": product_name,
                "tracking_number": tracking_number,
                "delivery_service": delivery_service,
                "estimated_date": estimated_date
            }
        )
    
    async def notify_level_up(
        self,
        telegram_id: int,
        old_level: str,
        new_level: str,
        old_level_emoji: str,
        new_level_emoji: str,
        benefits: List[str]
    ) -> bool:
        """Уведомить о повышении уровня."""
        benefits_text = "\n".join([f"• {b}" for b in benefits])
        
        return await self.send_notification(
            telegram_id=telegram_id,
            notification_type=NotificationType.LEVEL_UP,
            data={
                "old_level_name": old_level,
                "new_level_name": new_level,
                "old_level_emoji": old_level_emoji,
                "new_level_emoji": new_level_emoji,
                "benefits": benefits_text
            }
        )
    
    async def notify_welcome(
        self,
        telegram_id: int,
        first_name: str
    ) -> bool:
        """Приветственное сообщение для нового пользователя."""
        return await self.send_notification(
            telegram_id=telegram_id,
            notification_type=NotificationType.WELCOME,
            data={"first_name": first_name}
        )
    
    # ============================================================
    # МАССОВАЯ РАССЫЛКА
    # ============================================================
    
    async def notify_group_participants(
        self,
        participant_telegram_ids: List[int],
        notification_type: NotificationType,
        data: dict,
        exclude_telegram_id: int = None
    ) -> dict:
        """
        Отправить уведомление всем участникам сбора.
        
        Параметры:
            participant_telegram_ids: Список ID пользователей
            notification_type: Тип уведомления
            data: Данные для шаблона
            exclude_telegram_id: Исключить этого пользователя (например, организатора)
        
        Возвращает:
            dict: {"success": N, "failed": M}
        
        Пример:
            result = await notifier.notify_group_participants(
                participant_telegram_ids=[111, 222, 333],
                notification_type=NotificationType.GROUP_COMPLETED,
                data={...}
            )
            print(f"Отправлено: {result['success']}")
        """
        success = 0
        failed = 0
        
        tasks = []
        for telegram_id in participant_telegram_ids:
            if exclude_telegram_id and telegram_id == exclude_telegram_id:
                continue
            
            tasks.append(
                self.send_notification(telegram_id, notification_type, data)
            )
        
        # Выполняем параллельно, но не слишком быстро (лимиты Telegram)
        # Telegram позволяет ~30 сообщений в секунду
        for i in range(0, len(tasks), 25):
            batch = tasks[i:i+25]
            results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in results:
                if result is True:
                    success += 1
                else:
                    failed += 1
            
            # Небольшая пауза между батчами
            if i + 25 < len(tasks):
                await asyncio.sleep(1)
        
        return {"success": success, "failed": failed}


# ============================================================
# СИНГЛТОН
# ============================================================

_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Получить экземпляр NotificationService."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


# ============================================================
# ТЕСТИРОВАНИЕ
# ============================================================

if __name__ == "__main__":
    """
    Тест при запуске напрямую.
    
    Запуск:
        python services/notification_service.py
    """
    import asyncio
    
    async def test():
        print("🧪 Тестирование NotificationService\n")
        
        service = NotificationService()
        
        # Тест формирования сообщения (без отправки)
        data = {
            "participant_name": "Тест",
            "product_name": "Тестовый товар",
            "current_count": 3,
            "min_participants": 10,
            "group_id": 1
        }
        
        enriched = service._enrich_data(NotificationType.GROUP_JOINED, data)
        print("Прогресс-бар:", enriched.get("progress_bar"))
        print("Мотивация:", enriched.get("motivation_text"))
        
        print("\n✅ Тест завершён")
    
    asyncio.run(test())
