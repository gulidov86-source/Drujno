"""
Модуль: scheduler.py
Описание: Фоновые задачи по расписанию (APScheduler)
Проект: GroupBuy Mini App

Аналогия: робот-уборщик, который каждые 5 минут проверяет
не нужно ли убраться (проверить сборы), и каждые 10 минут —
не нужно ли вынести мусор (обработать завершённые).

Задачи:
    1. check_groups — каждые 5 мин — проверяет просроченные сборы
    2. process_completed — каждые 10 мин — списывает средства

Интеграция с FastAPI:
    В main.py в lifespan:
        from scheduler import start_scheduler, stop_scheduler
        start_scheduler()   # при старте
        stop_scheduler()    # при остановке
"""

import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


# ============================================================
# ЗАДАЧИ
# ============================================================

async def job_check_groups():
    """
    Проверить просроченные сборы.
    
    Что делает:
        - Находит активные сборы с истёкшим дедлайном
        - Если набрано достаточно людей → статус "completed"
        - Если мало людей → статус "failed" + возврат средств
    
    Импортируем внутри функции чтобы:
        1. Избежать circular imports
        2. Ошибка в импорте не убьёт весь scheduler
    """
    try:
        from services.group_manager import get_group_manager
        
        print(f"[Scheduler] {datetime.now().isoformat()} — Проверка просроченных сборов...")
        manager = get_group_manager()
        result = await manager.check_expired_groups()
        print(f"[Scheduler] ✅ Проверка сборов завершена: {result}")
    except Exception as e:
        # Ошибка в задаче НЕ должна убить scheduler
        print(f"[Scheduler] ❌ Ошибка check_groups: {e}")


async def job_process_completed():
    """
    Обработать завершённые сборы (capture платежей).
    
    Что делает:
        - Находит сборы в статусе "completed"
        - Для каждого заказа вызывает capture (списание средств)
        - Обновляет статусы заказов на "paid"
        - Начисляет бонусы организаторам
    """
    try:
        from process_completed_groups import process_completed_groups
        
        print(f"[Scheduler] {datetime.now().isoformat()} — Обработка завершённых сборов...")
        await process_completed_groups()
        print(f"[Scheduler] ✅ Обработка завершена")
    except Exception as e:
        print(f"[Scheduler] ❌ Ошибка process_completed: {e}")


# ============================================================
# ПЛАНИРОВЩИК
# ============================================================

scheduler = AsyncIOScheduler()

# Проверка просроченных сборов — каждые 5 минут
# Аналогия: каждые 5 минут смотрим — не протухли ли какие-то сборы
scheduler.add_job(
    job_check_groups,
    trigger=IntervalTrigger(minutes=5),
    id="check_groups",
    name="Проверка просроченных сборов",
    replace_existing=True,
    max_instances=1,  # Не запускать новую задачу пока старая не завершилась
)

# Обработка завершённых сборов — каждые 10 минут
# Аналогия: каждые 10 минут проверяем — не надо ли списать деньги
scheduler.add_job(
    job_process_completed,
    trigger=IntervalTrigger(minutes=10),
    id="process_completed",
    name="Обработка завершённых сборов",
    replace_existing=True,
    max_instances=1,
)


# ============================================================
# УПРАВЛЕНИЕ
# ============================================================

def start_scheduler():
    """Запустить планировщик при старте приложения."""
    scheduler.start()
    print("⏰ Scheduler запущен:")
    print("   - check_groups: каждые 5 мин")
    print("   - process_completed: каждые 10 мин")


def stop_scheduler():
    """Остановить планировщик при остановке приложения."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("⏰ Scheduler остановлен")
