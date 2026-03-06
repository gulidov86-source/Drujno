"""
Модуль: logger.py
Описание: Настройка структурного логирования (structlog)
Проект: GroupBuy Mini App

Аналогия: print() — это крик в пустоту, потом не найдёшь.
structlog — это секретарь, который записывает всё в журнал:
кто, когда, что, зачем. Можно искать и фильтровать.

Два режима:
    - dev: красивый цветной вывод в консоль (для разработки)
    - prod: JSON-формат (для Railway logs, Sentry, Datadog)

Использование:
    from logger import get_logger
    
    logger = get_logger("payments")
    
    # Простое сообщение
    logger.info("Webhook получен", event="payment.succeeded", order_id=42)
    
    # Ошибка (с traceback)
    try:
        ...
    except Exception as e:
        logger.error("Ошибка оплаты", error=str(e), payment_id="abc", exc_info=True)
    
    # Предупреждение
    logger.warning("Webhook без подписи", ip=client_ip)

В логах Railway (prod) это будет JSON:
    {"event": "Webhook получен", "module": "payments",
     "event_type": "payment.succeeded", "order_id": 42,
     "timestamp": "2026-03-04T12:00:00Z", "level": "info"}
"""

import logging
import sys
import structlog


# ============================================================
# НАСТРОЙКА STRUCTLOG
# ============================================================

def setup_logging():
    """
    Настроить structlog для всего приложения.
    
    Вызывается один раз при первом импорте модуля.
    
    Dev-режим:  красивый цветной вывод → удобно читать в терминале
    Prod-режим: JSON → легко парсить в Railway, Sentry, Datadog
    """
    from config import is_development
    
    # Общие процессоры (обработчики) для каждого лог-сообщения
    # Аналогия: конвейер, через который проходит каждое сообщение
    shared_processors = [
        # Добавить данные из contextvars (request_id и т.д.)
        structlog.contextvars.merge_contextvars,
        # Добавить уровень лога (info, warning, error)
        structlog.processors.add_log_level,
        # Добавить timestamp в ISO формате
        structlog.processors.TimeStamper(fmt="iso"),
        # Добавить stack trace если есть
        structlog.processors.StackInfoRenderer(),
    ]
    
    if is_development():
        # Dev: красивый цветной вывод
        # Пример: 2026-03-04 12:00:00 [info] Webhook получен  event=payment.succeeded
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # Prod: JSON — каждая строка это JSON-объект
        # Пример: {"event":"Webhook получен","level":"info",...}
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(module_name: str):
    """
    Получить логгер для модуля.
    
    Параметры:
        module_name: Имя модуля (для фильтрации в логах)
    
    Возвращает:
        structlog.BoundLogger: Логгер с привязанным именем модуля
    
    Пример:
        logger = get_logger("payments")
        logger.info("Платёж создан", amount=1000, order_id=42)
        
        # В JSON-логах:
        # {"event": "Платёж создан", "module": "payments",
        #  "amount": 1000, "order_id": 42, "level": "info",
        #  "timestamp": "2026-03-04T12:00:00Z"}
    """
    return structlog.get_logger(module=module_name)


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================

# Настраиваем логирование при первом импорте модуля
# Все последующие вызовы get_logger() будут использовать эту конфигурацию
setup_logging()
