"""
Модуль: bot.py
Описание: Основной Telegram бот для GroupBuy Mini App
Проект: GroupBuy Mini App

Что делает:
    - /start — приветствие + кнопка открытия Mini App
    - Deep links — переход к конкретному сбору (приглашения)
    - Отправка уведомлений пользователям

Как работает deep link (наглядно):
    1. Маша находит сбор и нажимает "Пригласить друзей"
    2. Генерируется ссылка: t.me/GroupBuyBot?startapp=g_42_r_123
       где g_42 — сбор #42, r_123 — Маша (реферер #123)
    3. Петя открывает ссылку → Telegram открывает бота
    4. Бот парсит параметр → открывает Mini App на странице сбора #42
    5. Петя присоединяется → Маша получает бонус

Запуск:
    python bot.py

Деплой:
    Railway Worker (отдельный сервис)
    Или вместе с FastAPI через asyncio
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, MenuButtonWebApp
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import sys
sys.path.append("..")
from config import settings

# ============================================================
# НАСТРОЙКА
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("groupbuy_bot")

bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

WEBAPP_URL = settings.TELEGRAM_WEBAPP_URL


# ============================================================
# КОМАНДА /start
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    """
    Обработчик /start — главная точка входа.
    
    Два сценария:
      A) Обычный старт: /start → приветствие + кнопка Mini App
      B) Deep link: /start g_42_r_123 → открываем Mini App на сбор #42
    
    Наглядно — deep link параметр:
      "g_42_r_123" означает:
        g_42   → group_id = 42 (какой сбор)
        r_123  → referrer_id = 123 (кто пригласил)
    """
    deep_link = command.args  # Параметр после /start (если есть)
    user = message.from_user
    
    logger.info(f"👤 /start от {user.first_name} (id={user.id}), deep_link={deep_link}")
    
    if deep_link:
        # Deep link — открываем Mini App на конкретной странице
        # Параметр передаётся в startapp → фронтенд его обрабатывает
        webapp_url = f"{WEBAPP_URL}#group/{_parse_group_id(deep_link)}" if _parse_group_id(deep_link) else WEBAPP_URL
        
        await message.answer(
            f"👋 Привет, <b>{user.first_name}</b>!\n\n"
            f"Тебя пригласили в групповой сбор! 🛍\n"
            f"Присоединяйся — чем больше людей, тем ниже цена для всех!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🛍 Открыть сбор",
                    web_app=WebAppInfo(url=webapp_url)
                )],
                [InlineKeyboardButton(
                    text="📦 Весь каталог",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )]
            ])
        )
    else:
        # Обычный старт — приветствие
        await message.answer(
            f"👋 Привет, <b>{user.first_name}</b>!\n\n"
            f"<b>GroupBuy</b> — покупай вместе, плати меньше! 🎉\n\n"
            f"Как это работает:\n"
            f"1️⃣ Выбери товар из каталога\n"
            f"2️⃣ Присоединись к сбору или создай свой\n"
            f"3️⃣ Пригласи друзей — цена снижается\n"
            f"4️⃣ Когда набралась группа — все получают скидку!\n\n"
            f"🔥 Скидки до <b>50%</b> на корейскую косметику",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🛍 Открыть магазин",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )],
                [InlineKeyboardButton(
                    text="❓ Как это работает",
                    callback_data="how_it_works"
                )]
            ])
        )


@dp.callback_query(F.data == "how_it_works")
async def how_it_works(callback: types.CallbackQuery):
    """Объяснение механики групповых покупок."""
    await callback.message.edit_text(
        "📖 <b>Как работает GroupBuy?</b>\n\n"
        "<b>Групповой сбор</b> — это совместная покупка.\n"
        "Несколько людей объединяются, чтобы купить один товар оптом.\n\n"
        "💰 <b>Почему дешевле?</b>\n"
        "Поставщик даёт скидку за объём. Чем больше людей — тем больше скидка.\n\n"
        "⏰ <b>Как проходит сбор?</b>\n"
        "• Вы присоединяетесь и оплачиваете (деньги замораживаются)\n"
        "• Если набралось нужное число людей — товар заказывается\n"
        "• Если не набралось — деньги возвращаются автоматически\n\n"
        "🔒 <b>Безопасно?</b>\n"
        "Да! Деньги списываются только после успешного сбора.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🛍 Попробовать",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )],
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="back_to_start"
            )]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    """Вернуться к приветствию."""
    user = callback.from_user
    await callback.message.edit_text(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"<b>GroupBuy</b> — покупай вместе, плати меньше! 🎉\n\n"
        f"Нажми кнопку ниже, чтобы открыть магазин:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🛍 Открыть магазин",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )],
            [InlineKeyboardButton(
                text="❓ Как это работает",
                callback_data="how_it_works"
            )]
        ])
    )
    await callback.answer()


# ============================================================
# КОМАНДА /help
# ============================================================

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Справка по боту."""
    await message.answer(
        "ℹ️ <b>Справка GroupBuy</b>\n\n"
        "/start — Открыть магазин\n"
        "/help — Эта справка\n"
        "/support — Написать в поддержку\n\n"
        "📱 Основной функционал доступен в Mini App.\n"
        "Нажмите кнопку «Открыть магазин» для перехода.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🛍 Открыть магазин",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )]
        ])
    )


@dp.message(Command("support"))
async def cmd_support(message: types.Message):
    """Переход в поддержку через Mini App."""
    await message.answer(
        "💬 <b>Поддержка</b>\n\n"
        "Написать в поддержку можно через приложение:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Открыть поддержку",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}#support/create")
            )]
        ])
    )


# ============================================================
# УТИЛИТЫ
# ============================================================

def _parse_group_id(deep_link: str) -> str | None:
    """
    Извлечь group_id из deep link параметра.
    
    Наглядно:
      "g_42_r_123" → "42"
      "g_42"       → "42"
      "foobar"     → None
    """
    if not deep_link:
        return None
    
    parts = deep_link.split("_")
    for i, part in enumerate(parts):
        if part == "g" and i + 1 < len(parts):
            return parts[i + 1]
    
    return None


# ============================================================
# ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЙ
# ============================================================

async def send_notification(telegram_id: int, text: str, markup=None):
    """
    Отправить уведомление пользователю в Telegram.
    
    Вызывается из notification_service.py когда нужно 
    отправить push-уведомление.
    
    Наглядно: 
      Бэкенд решил что пользователю нужно сообщить о чём-то
      → вызывает send_notification(telegram_id, "Ваш заказ отправлен! 🚚")
      → пользователь получает сообщение в чат с ботом
    """
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            reply_markup=markup
        )
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления {telegram_id}: {e}")
        return False


async def notify_order_status(telegram_id: int, order_id: int, status: str, product_name: str = ""):
    """Уведомление об изменении статуса заказа."""
    status_texts = {
        "paid": f"✅ Оплата подтверждена!\nЗаказ #{order_id} — {product_name}",
        "processing": f"⚙️ Заказ #{order_id} обрабатывается\n{product_name}",
        "shipped": f"🚚 Заказ #{order_id} отправлен!\n{product_name}\nСкоро появится трек-номер",
        "delivered": f"🎉 Заказ #{order_id} доставлен!\n{product_name}\nНе забудьте проверить товар",
        "cancelled": f"❌ Заказ #{order_id} отменён\n{product_name}\nДеньги вернутся в течение 24ч",
        "refunded": f"💰 Возврат по заказу #{order_id}\n{product_name}\nДеньги вернутся на карту",
    }
    
    text = status_texts.get(status, f"📦 Статус заказа #{order_id} изменён: {status}")
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📦 Посмотреть заказ",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}#order/{order_id}")
        )]
    ])
    
    return await send_notification(telegram_id, text, markup)


async def notify_group_completed(telegram_id: int, group_id: int, product_name: str, final_price: str):
    """Уведомление о завершении сбора."""
    text = (
        f"🎉 <b>Сбор завершён!</b>\n\n"
        f"Товар: {product_name}\n"
        f"Финальная цена: {final_price}\n\n"
        f"Деньги списываются, товар скоро будет отправлен!"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="👥 Посмотреть сбор",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}#group/{group_id}")
        )]
    ])
    
    return await send_notification(telegram_id, text, markup)


# ============================================================
# НАСТРОЙКА КНОПКИ МЕНЮ (Menu Button)
# ============================================================

async def setup_menu_button():
    """
    Настраивает кнопку "Menu" в чате с ботом.
    
    Вместо стандартной кнопки "Menu" пользователь видит
    "🛍 Магазин" — и по клику открывается Mini App.
    
    Это то же самое, что настраивается в BotFather,
    но можно сделать программно.
    """
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🛍 Магазин",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        )
        logger.info("✅ Menu Button настроен")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось настроить Menu Button: {e}")


async def setup_commands():
    """Регистрация команд в меню бота."""
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Открыть магазин"),
        types.BotCommand(command="help", description="Справка"),
        types.BotCommand(command="support", description="Поддержка"),
    ])
    logger.info("✅ Команды зарегистрированы")


# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    """Запуск бота."""
    logger.info("🤖 Запуск GroupBuy Bot...")
    
    # Настраиваем кнопку и команды
    await setup_menu_button()
    await setup_commands()
    
    # Запускаем polling (бот слушает сообщения)
    logger.info("✅ Бот запущен. Слушаем сообщения...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
