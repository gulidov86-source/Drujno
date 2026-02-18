"""
Модуль: cron/check_groups.py
Описание: Cron-задача для проверки просроченных сборов + уведомления
Проект: GroupBuy Mini App

Этот скрипт проверяет все активные сборы и:
- Завершает те, где истёк дедлайн и набрано достаточно людей
- Отмечает неудавшимися те, где истёк дедлайн и людей мало
- Отправляет уведомления участникам о завершении/неудаче
- Напоминает о скором завершении (за 2 часа)

Запуск:
    # Вручную
    python cron/check_groups.py
    
    # Через cron (каждые 5 минут)
    */5 * * * * cd /path/to/app && python cron/check_groups.py

В Railway/Render:
    Использовать встроенные cron jobs или отдельный worker
"""

import asyncio
import sys
from datetime import datetime

# Добавляем путь к backend
sys.path.insert(0, "..")
sys.path.insert(0, ".")

from services.group_manager import get_group_manager

# Импортируем функции уведомлений
try:
    from services.notification_integration import (
        notify_group_completed,
        notify_group_failed,
        notify_expiring_groups
    )
    NOTIFICATIONS_ENABLED = True
except ImportError:
    NOTIFICATIONS_ENABLED = False
    print("⚠️ Уведомления недоступны (notification_integration не найден)")


async def check_and_notify_expiring():
    """
    Проверить и уведомить о скором завершении сборов.
    
    Находит сборы, до завершения которых осталось ~2 часа,
    и отправляет напоминания участникам.
    """
    if not NOTIFICATIONS_ENABLED:
        return
    
    print(f"\n[{datetime.now().isoformat()}] Проверка истекающих сборов...")
    
    try:
        result = await notify_expiring_groups(hours_before=2)
        
        if result["groups_notified"] > 0:
            print(f"  Напоминания: {result['groups_notified']} сборов, {result['total_sent']} уведомлений")
        else:
            print("  Нет сборов, требующих напоминания")
            
    except Exception as e:
        print(f"  ⚠️ Ошибка при отправке напоминаний: {e}")


async def main():
    """
    Основная функция проверки сборов.
    """
    print(f"[{datetime.now().isoformat()}] Запуск проверки просроченных сборов...")
    
    manager = get_group_manager()
    
    try:
        results = await manager.check_expired_groups()
        
        if not results:
            print("  Нет просроченных сборов")
        else:
            print(f"  Обработано сборов: {len(results)}")
            
            # Собираем результаты для уведомлений
            completed_groups = []
            failed_groups = []
            
            for result in results:
                status_emoji = "✅" if result.new_status == "completed" else "❌"
                print(
                    f"  {status_emoji} Сбор #{result.group_id}: "
                    f"{result.old_status} → {result.new_status} "
                    f"({result.participants_count} участников)"
                )
                
                if result.final_price:
                    print(f"      Финальная цена: {result.final_price}₽")
                
                # Собираем для уведомлений
                if result.new_status == "completed":
                    completed_groups.append(result.group_id)
                elif result.new_status == "failed":
                    failed_groups.append(result.group_id)
            
            # Отправляем уведомления
            if NOTIFICATIONS_ENABLED:
                print(f"\n[{datetime.now().isoformat()}] Отправка уведомлений...")
                
                # Уведомления о успешном завершении
                for group_id in completed_groups:
                    try:
                        await notify_group_completed(group_id)
                    except Exception as e:
                        print(f"  ⚠️ Ошибка уведомления для сбора #{group_id}: {e}")
                
                # Уведомления о неудаче
                for group_id in failed_groups:
                    try:
                        await notify_group_failed(group_id)
                    except Exception as e:
                        print(f"  ⚠️ Ошибка уведомления для сбора #{group_id}: {e}")
        
        # Проверяем сборы, которые скоро завершатся
        await check_and_notify_expiring()
        
        print(f"\n[{datetime.now().isoformat()}] Проверка завершена")
        
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] ОШИБКА: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
