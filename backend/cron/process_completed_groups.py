"""
Модуль: cron/process_completed_groups.py
Описание: Обработка завершённых сборов — списание замороженных средств
Проект: GroupBuy Mini App

Этот скрипт:
1. Находит сборы в статусе "completed"
2. Для каждого сбора находит все заказы в статусе "frozen"
3. Списывает средства через capture
4. Обновляет статусы заказов на "paid"
5. Начисляет бонусы и обновляет статистику

Запуск:
    # Вручную
    python cron/process_completed_groups.py
    
    # Через cron (каждые 10 минут)
    */10 * * * * cd /path/to/backend && python -m cron.process_completed_groups

ВАЖНО: Запускать ПОСЛЕ check_groups.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, "..")
sys.path.insert(0, ".")

from database.connection import get_db
from services.payment_service import get_payment_service
from services.price_calculator import calculate_current_price


async def process_completed_groups():
    """
    Обработать все завершённые сборы.
    
    Для каждого сбора в статусе "completed":
    1. Рассчитываем финальную цену
    2. Списываем средства со всех участников
    3. Обновляем статистику пользователей
    """
    print(f"[{datetime.now().isoformat()}] Обработка завершённых сборов...")
    
    db = get_db()
    payment_service = get_payment_service()
    
    # Находим завершённые сборы, которые ещё не обработаны
    # (есть заказы в статусе frozen)
    completed_groups = (
        db.table("groups")
        .select("id, product_id, current_count, products(base_price, price_tiers)")
        .eq("status", "completed")
        .execute()
    )
    
    if not completed_groups.data:
        print("  Нет сборов для обработки")
        return
    
    total_processed = 0
    total_charged = Decimal("0")
    
    for group_data in completed_groups.data:
        group_id = group_data["id"]
        
        # Проверяем, есть ли замороженные заказы
        frozen_orders = (
            db.table("orders")
            .select("id, user_id, final_price, total_amount, payments(id, external_id, status, amount)")
            .eq("group_id", group_id)
            .eq("status", "frozen")
            .execute()
        )
        
        if not frozen_orders.data:
            # Все заказы уже обработаны
            continue
        
        print(f"\n  Сбор #{group_id}: {len(frozen_orders.data)} заказов для обработки")
        
        # Рассчитываем финальную цену
        product_data = group_data.get("products", {})
        price_tiers = product_data.get("price_tiers", [])
        base_price = Decimal(str(product_data.get("base_price", 0)))
        current_count = group_data.get("current_count", 0)
        
        final_price = calculate_current_price(price_tiers, current_count, base_price)
        
        print(f"    Финальная цена: {final_price}₽ ({current_count} участников)")
        
        # Обрабатываем каждый заказ
        for order_data in frozen_orders.data:
            order_id = order_data["id"]
            user_id = order_data["user_id"]
            payments = order_data.get("payments", [])
            
            if not payments:
                print(f"    ⚠️ Заказ #{order_id}: нет платежа")
                continue
            
            payment = payments[0]  # Берём первый платёж
            
            if payment.get("status") != "frozen":
                print(f"    ⚠️ Заказ #{order_id}: платёж не frozen ({payment.get('status')})")
                continue
            
            external_id = payment.get("external_id")
            if not external_id:
                print(f"    ⚠️ Заказ #{order_id}: нет external_id")
                continue
            
            # Списываем средства
            # Важно: списываем финальную цену + доставка
            original_amount = Decimal(str(order_data.get("total_amount", 0)))
            original_product_price = Decimal(str(order_data.get("final_price", 0)))
            delivery_cost = original_amount - original_product_price
            
            # Новая сумма = финальная цена + доставка
            new_total = final_price + delivery_cost
            
            # Если цена упала — списываем меньше
            capture_amount = min(original_amount, new_total)
            
            print(f"    Заказ #{order_id}: списание {capture_amount}₽")
            
            result = await payment_service.capture_payment(
                payment_id=external_id,
                amount=capture_amount
            )
            
            if result.success:
                # Обновляем заказ
                savings = base_price - final_price
                
                status_history = [{
                    "status": "paid",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "comment": f"Оплачено {capture_amount}₽"
                }]
                
                db.table("orders").update({
                    "status": "paid",
                    "final_price": float(final_price),
                    "total_amount": float(capture_amount),
                    "status_history": status_history
                }).eq("id", order_id).execute()
                
                # Обновляем статистику пользователя
                user = (
                    db.table("users")
                    .select("total_orders, total_savings")
                    .eq("id", user_id)
                    .limit(1)
                    .execute()
                )
                
                if user.data:
                    new_orders = user.data[0].get("total_orders", 0) + 1
                    new_savings = Decimal(str(user.data[0].get("total_savings", 0))) + savings
                    
                    db.table("users").update({
                        "total_orders": new_orders,
                        "total_savings": float(new_savings)
                    }).eq("id", user_id).execute()
                
                total_processed += 1
                total_charged += capture_amount
                
                print(f"      ✅ Успешно (экономия: {savings}₽)")
            else:
                print(f"      ❌ Ошибка: {result.error}")
    
    print(f"\n[{datetime.now().isoformat()}] Обработка завершена")
    print(f"  Заказов обработано: {total_processed}")
    print(f"  Сумма списаний: {total_charged}₽")


async def process_failed_groups():
    """
    Обработать неудавшиеся сборы — вернуть средства.
    
    Для каждого сбора в статусе "failed":
    1. Находим все заказы в статусе "frozen"
    2. Отменяем платежи (разморозка)
    3. Обновляем статусы заказов на "refunded"
    """
    print(f"\n[{datetime.now().isoformat()}] Обработка неудавшихся сборов...")
    
    db = get_db()
    payment_service = get_payment_service()
    
    # Находим неудавшиеся сборы
    failed_groups = (
        db.table("groups")
        .select("id")
        .eq("status", "failed")
        .execute()
    )
    
    if not failed_groups.data:
        print("  Нет неудавшихся сборов для обработки")
        return
    
    total_refunded = 0
    
    for group_data in failed_groups.data:
        group_id = group_data["id"]
        
        # Находим замороженные заказы
        frozen_orders = (
            db.table("orders")
            .select("id, payments(id, external_id, status)")
            .eq("group_id", group_id)
            .eq("status", "frozen")
            .execute()
        )
        
        if not frozen_orders.data:
            continue
        
        print(f"\n  Сбор #{group_id}: {len(frozen_orders.data)} заказов для возврата")
        
        for order_data in frozen_orders.data:
            order_id = order_data["id"]
            payments = order_data.get("payments", [])
            
            if not payments:
                continue
            
            payment = payments[0]
            external_id = payment.get("external_id")
            
            if not external_id or payment.get("status") != "frozen":
                continue
            
            # Отменяем платёж
            result = await payment_service.cancel_payment(external_id)
            
            if result.success:
                # Обновляем заказ
                status_history = [{
                    "status": "refunded",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "comment": "Сбор не состоялся, средства возвращены"
                }]
                
                db.table("orders").update({
                    "status": "refunded",
                    "status_history": status_history
                }).eq("id", order_id).execute()
                
                total_refunded += 1
                print(f"    ✅ Заказ #{order_id}: средства возвращены")
            else:
                print(f"    ❌ Заказ #{order_id}: ошибка возврата - {result.error}")
    
    print(f"\n  Возвратов выполнено: {total_refunded}")


async def main():
    """Основная функция."""
    await process_completed_groups()
    await process_failed_groups()


if __name__ == "__main__":
    asyncio.run(main())
