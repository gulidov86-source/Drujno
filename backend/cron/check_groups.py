"""
Модуль: cron/check_groups.py
Описание: Cron-задача для проверки просроченных сборов
Проект: GroupBuy Mini App

Этот скрипт проверяет все активные сборы и:
- Завершает те, где истёк дедлайн и набрано достаточно людей
- Отмечает неудавшимися те, где истёк дедлайн и людей мало

Запуск:
    # Вручную
    python cron/check_groups.py
    
    # Через cron (каждые 5 минут)
    */5 * * * * cd /path/to/app && python cron/check_groups.py

    # Через systemd timer
    # Создать /etc/systemd/system/groupbuy-check.timer
    
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
            
            for result in results:
                status_emoji = "✅" if result.new_status == "completed" else "❌"
                print(
                    f"  {status_emoji} Сбор #{result.group_id}: "
                    f"{result.old_status} → {result.new_status} "
                    f"({result.participants_count} участников)"
                )
                
                if result.final_price:
                    print(f"      Финальная цена: {result.final_price}₽")
        
        print(f"[{datetime.now().isoformat()}] Проверка завершена")
        
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] ОШИБКА: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
