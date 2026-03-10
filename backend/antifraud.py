"""
Модуль: services/antifraud.py
Описание: Антифрод-система для обнаружения подозрительных пользователей
Проект: GroupBuy Mini App

Аналогия: охранник в магазине. Не мешает обычным покупателям,
но замечает тех, кто слишком часто возвращает товары или
отменяет заказы.

Правила:
    1. 3+ отмен заказов подряд → is_suspicious = True
    2. 3+ возвратов за последние 30 дней → is_suspicious = True

Использование:
    from antifraud import check_user_suspicious
    
    # Вызывать после каждой отмены/возврата
    result = await check_user_suspicious(user_id)
    if result["is_suspicious"]:
        print(f"Подозрительный: {result['reason']}")
"""

from datetime import datetime, timedelta, timezone

import sys
sys.path.append("..")
from database.connection import get_db


# ============================================================
# НАСТРОЙКИ АНТИФРОДА
# ============================================================

# Порог отмен подряд для пометки
MAX_CANCELLATIONS_STREAK = 3

# Порог возвратов за месяц
MAX_RETURNS_PER_MONTH = 3

# Сколько последних заказов проверять на серию отмен
ORDERS_TO_CHECK = 5


# ============================================================
# ОСНОВНАЯ ПРОВЕРКА
# ============================================================

async def check_user_suspicious(user_id: int) -> dict:
    """
    Проверить, стал ли пользователь подозрительным.
    
    Вызывать после каждой отмены заказа или оформления возврата.
    
    Параметры:
        user_id: ID пользователя
    
    Возвращает:
        dict: {
            "is_suspicious": bool,
            "reason": str | None,
            "cancellations_streak": int,
            "returns_month": int
        }
    
    Пример:
        result = await check_user_suspicious(42)
        # {"is_suspicious": True, "reason": "3+ отмен подряд (серия: 3)", ...}
    """
    db = get_db()
    
    # ============================================================
    # ПРОВЕРКА 1: Серия отмен подряд
    # ============================================================
    # Берём последние N заказов и считаем сколько отмен идут подряд
    # с конца (самые свежие). Как только встречаем не-отмену — стоп.
    #
    # Аналогия: если человек 3 раза подряд бронирует столик
    # и не приходит — ресторан его блокирует
    
    recent_orders = (
        db.table("orders")
        .select("status")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(ORDERS_TO_CHECK)
        .execute()
    )
    
    cancellations_streak = 0
    for order in (recent_orders.data or []):
        if order["status"] == "cancelled":
            cancellations_streak += 1
        else:
            break  # Серия прервалась
    
    # ============================================================
    # ПРОВЕРКА 2: Возвраты за последний месяц
    # ============================================================
    # Аналогия: покупатель, который каждую неделю возвращает товар —
    # скорее всего, злоупотребляет
    
    thirty_days_ago = (
        datetime.now(timezone.utc) - timedelta(days=30)
    ).isoformat()
    
    returns_result = (
        db.table("returns")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", thirty_days_ago)
        .execute()
    )
    
    returns_month = returns_result.count or 0
    
    # ============================================================
    # РЕШЕНИЕ: помечать или нет
    # ============================================================
    
    reason = None
    is_suspicious = False
    
    if cancellations_streak >= MAX_CANCELLATIONS_STREAK:
        is_suspicious = True
        reason = f"{MAX_CANCELLATIONS_STREAK}+ отмен подряд (серия: {cancellations_streak})"
    
    if returns_month >= MAX_RETURNS_PER_MONTH:
        is_suspicious = True
        reason_part = f"{MAX_RETURNS_PER_MONTH}+ возвратов за месяц ({returns_month})"
        reason = f"{reason}; {reason_part}" if reason else reason_part
    
    # Обновляем флаг в БД (только если стал подозрительным)
    if is_suspicious:
        db.table("users").update({
            "is_suspicious": True,
            "suspicious_reason": reason,
            "suspicious_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", user_id).execute()
        
        print(f"[Antifraud] ⚠️ Пользователь {user_id} помечен: {reason}")
        
        # TODO: Отправить алерт в admin_bot через Telegram Bot API
        # from bot import send_admin_alert
        # await send_admin_alert(f"⚠️ Подозрительный пользователь #{user_id}: {reason}")
    
    return {
        "is_suspicious": is_suspicious,
        "reason": reason,
        "cancellations_streak": cancellations_streak,
        "returns_month": returns_month
    }


# ============================================================
# АДМИНИСТРАТИВНЫЕ ФУНКЦИИ
# ============================================================

async def clear_suspicious_flag(user_id: int):
    """
    Снять флаг подозрительности (ручное действие админа).
    
    Параметры:
        user_id: ID пользователя
    """
    db = get_db()
    db.table("users").update({
        "is_suspicious": False,
        "suspicious_reason": None,
        "suspicious_at": None
    }).eq("id", user_id).execute()
    
    print(f"[Antifraud] ✅ Пользователь {user_id}: флаг подозрительности снят")


async def get_suspicious_users() -> list:
    """
    Получить список всех подозрительных пользователей.
    
    Возвращает:
        list: Список пользователей с флагом is_suspicious
    """
    db = get_db()
    result = (
        db.table("users")
        .select("id, telegram_id, username, first_name, "
                "is_suspicious, suspicious_reason, suspicious_at")
        .eq("is_suspicious", True)
        .order("suspicious_at", desc=True)
        .execute()
    )
    return result.data or []
