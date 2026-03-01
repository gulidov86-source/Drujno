"""
Модуль: routers/analytics.py
Описание: Сбор аналитических событий от фронтенда
Проект: GroupBuy Mini App

Наглядно — как это работает:
    
    Фронтенд                    Бэкенд                  База данных
    ─────────                   ──────                   ───────────
    Юзер открыл товар           
    → trackEvent('product_view')
    → POST /api/analytics/event → analytics.py           → таблица events
                                  парсит событие            {user_id, event, data}
                                  добавляет user_id

Зачем:
    Без аналитики ты слепой — не знаешь:
    - Сколько людей заходит (DAU)
    - Где "отваливаются" (воронка)
    - Работает ли реклама (конверсия)
    
    С аналитикой видишь:
    100 зашли → 40 посмотрели товар → 15 вступили в сбор → 8 оплатили
    Конверсия: 8%, узкое горлышко: просмотр → вступление

Ключевые события:
    page_view       — открытие страницы
    product_view    — просмотр товара
    group_view      — просмотр сбора
    group_join      — вступление в сбор
    checkout_start  — начало оформления
    payment_start   — переход к оплате
    payment_success — успешная оплата
    share_click     — нажал "пригласить"

Эндпоинты:
    POST /api/analytics/event  — Записать событие (от фронтенда)
    GET  /api/analytics/funnel — Воронка конверсии (для админа)
    GET  /api/analytics/daily  — Ежедневная статистика (для админа)

Использование:
    from routers.analytics import router
    app.include_router(router)
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import json

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field

import sys
sys.path.append("..")
from database.connection import get_supabase_client
from utils.auth import get_current_user

# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/analytics",
    tags=["Аналитика"]
)


# ============================================================
# МОДЕЛИ
# ============================================================

class TrackEventRequest(BaseModel):
    """
    Событие аналитики от фронтенда.
    
    Пример:
        {
            "event": "product_view",
            "data": {"product_id": 42},
            "ts": 1709123456789
        }
    """
    event: str = Field(..., max_length=100, description="Имя события")
    data: Optional[dict] = Field(default={}, description="Дополнительные данные")
    ts: Optional[int] = Field(None, description="Timestamp с фронтенда (ms)")


# Допустимые события — защита от мусора
ALLOWED_EVENTS = {
    "page_view", "product_view", "group_view", "group_join",
    "checkout_start", "payment_start", "payment_success",
    "share_click", "support_create", "return_create",
    "search", "catalog_filter", "notification_click",
}


# ============================================================
# ЭНДПОИНТЫ
# ============================================================

@router.post("/event", summary="Записать событие")
async def track_event(
    request: Request,
    body: TrackEventRequest = None
):
    """
    Записать аналитическое событие.
    
    Принимает данные двумя способами:
    1. JSON body (обычный POST)
    2. sendBeacon (Content-Type может быть text/plain)
    
    Не требует авторизации — но если токен есть, привяжет к user_id.
    Это важно для sendBeacon, который не передаёт заголовки.
    """
    db = get_supabase_client()
    
    # Парсим тело — может прийти через sendBeacon как raw text
    if body is None:
        try:
            raw = await request.body()
            parsed = json.loads(raw)
            body = TrackEventRequest(**parsed)
        except Exception:
            return {"success": True}  # Молча проглатываем ошибки
    
    # Проверяем допустимость события
    if body.event not in ALLOWED_EVENTS:
        return {"success": True}  # Не ругаемся, просто игнорируем
    
    # Пробуем извлечь user_id из токена (если передан)
    user_id = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from utils.auth import decode_token
            token_data = decode_token(auth_header.replace("Bearer ", ""))
            user_id = token_data.get("user_id")
        except Exception:
            pass
    
    # Записываем событие
    try:
        event_data = {
            "user_id": user_id,
            "event": body.event,
            "data": json.dumps(body.data or {}),
            "client_ts": datetime.fromtimestamp(body.ts / 1000, tz=timezone.utc).isoformat() if body.ts else None,
        }
        db.table("analytics_events").insert(event_data).execute()
    except Exception as e:
        # Аналитика не должна ронять приложение
        print(f"⚠️ Analytics error: {e}")
    
    return {"success": True}


@router.get("/funnel", summary="Воронка конверсии")
async def get_funnel(
    days: int = Query(default=7, ge=1, le=90, description="За сколько дней"),
    user_id: int = Depends(get_current_user)
):
    """
    Воронка конверсии за N дней.
    
    Наглядно — показывает сколько людей прошли каждый этап:
    
        page_view (100) → product_view (45) → group_view (25)
        → checkout_start (12) → payment_start (10) → payment_success (7)
    
    Возвращает:
        { "steps": [{"event": "page_view", "count": 100}, ...] }
    """
    # TODO: проверить что user_id — админ
    
    db = get_supabase_client()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    funnel_events = [
        "page_view", "product_view", "group_view",
        "checkout_start", "payment_start", "payment_success"
    ]
    
    steps = []
    for event in funnel_events:
        result = db.table("analytics_events").select(
            "user_id", count="exact"
        ).eq("event", event).gte("created_at", since).execute()
        
        steps.append({
            "event": event,
            "count": result.count or 0
        })
    
    return {
        "success": True,
        "days": days,
        "steps": steps
    }


@router.get("/daily", summary="Ежедневная статистика")
async def get_daily_stats(
    days: int = Query(default=7, ge=1, le=90),
    user_id: int = Depends(get_current_user)
):
    """
    Количество уникальных пользователей и событий за каждый день.
    
    Наглядно:
        2026-03-01: 45 юзеров, 230 событий
        2026-03-02: 52 юзера, 310 событий
        ...
    """
    db = get_supabase_client()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    result = db.table("analytics_events").select(
        "event, created_at, user_id"
    ).gte("created_at", since).order("created_at", desc=True).execute()
    
    # Группируем по дням
    daily = {}
    for row in (result.data or []):
        day = row["created_at"][:10]  # "2026-03-01"
        if day not in daily:
            daily[day] = {"events": 0, "users": set()}
        daily[day]["events"] += 1
        if row.get("user_id"):
            daily[day]["users"].add(row["user_id"])
    
    # Сериализуем
    stats = [
        {"date": day, "events": d["events"], "unique_users": len(d["users"])}
        for day, d in sorted(daily.items(), reverse=True)
    ]
    
    return {
        "success": True,
        "days": days,
        "stats": stats
    }
