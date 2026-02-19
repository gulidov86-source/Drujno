"""
Модуль: routers/delivery.py
Описание: API эндпоинты для работы с доставкой (СДЭК)
Проект: GroupBuy Mini App

Эндпоинты:
    GET  /api/delivery/calculate     — Расчёт стоимости доставки
    GET  /api/delivery/tariffs       — Все доступные тарифы
    GET  /api/delivery/pickup-points — Список пунктов выдачи
    GET  /api/delivery/cities        — Поиск городов
    GET  /api/delivery/tracking/{id} — Отслеживание заказа

Использование:
    from routers.delivery import router
    app.include_router(router)
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

import sys
sys.path.append("..")

from services.cdek_service import (
    get_cdek_service,
    DeliveryTariff,
    PickupPoint,
    CDEKTariffs
)
from utils.auth import get_current_user, get_current_user_optional


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/delivery",
    tags=["Доставка"]
)


# ============================================================
# МОДЕЛИ
# ============================================================

class CalculateRequest(BaseModel):
    """Запрос на расчёт доставки."""
    from_city: str = Field("Москва", description="Город отправления")
    to_city: str = Field(..., description="Город получения")
    weight: int = Field(500, ge=1, le=30000, description="Вес в граммах")
    length: int = Field(10, ge=1, le=150, description="Длина в см")
    width: int = Field(10, ge=1, le=150, description="Ширина в см")
    height: int = Field(10, ge=1, le=150, description="Высота в см")


class CalculateResponse(BaseModel):
    """Результат расчёта доставки."""
    success: bool
    tariff_code: Optional[int] = None
    tariff_name: Optional[str] = None
    delivery_sum: Optional[Decimal] = None
    period_min: Optional[int] = None
    period_max: Optional[int] = None
    period_text: Optional[str] = None
    error: Optional[str] = None


class TariffItem(BaseModel):
    """Тариф доставки."""
    tariff_code: int
    tariff_name: str
    delivery_sum: Decimal
    period_min: int
    period_max: int
    period_text: str
    delivery_mode: int
    delivery_mode_text: str


class TariffsResponse(BaseModel):
    """Список тарифов."""
    success: bool
    tariffs: List[TariffItem] = []
    error: Optional[str] = None


class PickupPointItem(BaseModel):
    """Пункт выдачи."""
    code: str
    name: str
    address: str
    city: str
    work_time: str
    phone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    type: str
    is_dressing_room: bool
    have_cashless: bool


class PickupPointsResponse(BaseModel):
    """Список пунктов выдачи."""
    success: bool
    total: int
    points: List[PickupPointItem] = []
    error: Optional[str] = None


class CityItem(BaseModel):
    """Город."""
    code: int
    city: str
    region: Optional[str] = None
    country: str = "Россия"


class CitiesResponse(BaseModel):
    """Список городов."""
    success: bool
    cities: List[CityItem] = []


class TrackingStatus(BaseModel):
    """Статус отслеживания."""
    code: str
    name: str
    date_time: str
    city: Optional[str] = None


class TrackingResponse(BaseModel):
    """Результат отслеживания."""
    success: bool
    cdek_number: Optional[str] = None
    status: Optional[str] = None
    status_name: Optional[str] = None
    statuses: List[TrackingStatus] = []
    error: Optional[str] = None


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def format_period(min_days: int, max_days: int) -> str:
    """Форматировать срок доставки."""
    if min_days == max_days:
        if min_days == 1:
            return "1 день"
        elif min_days < 5:
            return f"{min_days} дня"
        else:
            return f"{min_days} дней"
    else:
        return f"{min_days}-{max_days} дней"


def get_delivery_mode_text(mode: int) -> str:
    """Получить текст режима доставки."""
    modes = {
        1: "дверь-дверь",
        2: "дверь-склад",
        3: "склад-дверь",
        4: "склад-склад"
    }
    return modes.get(mode, "")


# ============================================================
# ЭНДПОИНТЫ
# ============================================================

@router.get(
    "/calculate",
    response_model=CalculateResponse,
    summary="Расчёт стоимости доставки",
    description="""
    Рассчитать стоимость доставки до ПВЗ (самый дешёвый вариант).
    
    **Параметры:**
    - `to_city` — город получения (обязательно)
    - `weight` — вес в граммах (по умолчанию 500)
    - `from_city` — город отправления (по умолчанию Москва)
    """
)
async def calculate_delivery(
    to_city: str = Query(..., description="Город получения"),
    weight: int = Query(500, ge=1, le=30000, description="Вес в граммах"),
    from_city: str = Query("Москва", description="Город отправления"),
    length: int = Query(10, ge=1, le=150),
    width: int = Query(10, ge=1, le=150),
    height: int = Query(10, ge=1, le=150)
):
    """
    Рассчитать стоимость доставки.
    
    Возвращает оптимальный тариф (доставка в ПВЗ).
    """
    cdek = get_cdek_service()
    
    try:
        tariff = await cdek.calculate_tariff(
            from_city=from_city,
            to_city=to_city,
            weight=weight,
            length=length,
            width=width,
            height=height
        )
        
        if not tariff:
            return CalculateResponse(
                success=False,
                error="Не удалось рассчитать доставку. Проверьте название города."
            )
        
        return CalculateResponse(
            success=True,
            tariff_code=tariff.tariff_code,
            tariff_name=tariff.tariff_name,
            delivery_sum=tariff.delivery_sum,
            period_min=tariff.period_min,
            period_max=tariff.period_max,
            period_text=format_period(tariff.period_min, tariff.period_max)
        )
        
    except Exception as e:
        return CalculateResponse(
            success=False,
            error=f"Ошибка расчёта: {str(e)}"
        )


@router.get(
    "/tariffs",
    response_model=TariffsResponse,
    summary="Все тарифы доставки",
    description="Получить все доступные тарифы для маршрута."
)
async def get_tariffs(
    to_city: str = Query(..., description="Город получения"),
    weight: int = Query(500, ge=1, le=30000, description="Вес в граммах"),
    from_city: str = Query("Москва", description="Город отправления")
):
    """
    Получить все доступные тарифы.
    """
    cdek = get_cdek_service()
    
    try:
        tariffs = await cdek.calculate_all_tariffs(
            from_city=from_city,
            to_city=to_city,
            weight=weight
        )
        
        if not tariffs:
            return TariffsResponse(
                success=False,
                error="Нет доступных тарифов для этого маршрута"
            )
        
        items = [
            TariffItem(
                tariff_code=t.tariff_code,
                tariff_name=t.tariff_name,
                delivery_sum=t.delivery_sum,
                period_min=t.period_min,
                period_max=t.period_max,
                period_text=format_period(t.period_min, t.period_max),
                delivery_mode=t.delivery_mode,
                delivery_mode_text=get_delivery_mode_text(t.delivery_mode)
            )
            for t in tariffs
        ]
        
        return TariffsResponse(
            success=True,
            tariffs=items
        )
        
    except Exception as e:
        return TariffsResponse(
            success=False,
            error=str(e)
        )


@router.get(
    "/pickup-points",
    response_model=PickupPointsResponse,
    summary="Пункты выдачи",
    description="""
    Получить список пунктов выдачи в городе.
    
    **Параметры:**
    - `city` — название города
    - `type` — тип точки: `PVZ` (пункт выдачи) или `POSTAMAT` (постамат)
    """
)
async def get_pickup_points(
    city: str = Query(..., description="Город"),
    type: Optional[str] = Query(None, regex="^(PVZ|POSTAMAT)$", description="Тип точки"),
    limit: int = Query(50, ge=1, le=200, description="Максимум результатов")
):
    """
    Получить пункты выдачи в городе.
    """
    cdek = get_cdek_service()
    
    try:
        points = await cdek.get_pickup_points(
            city=city,
            type=type,
            limit=limit
        )
        
        items = [
            PickupPointItem(
                code=p.code,
                name=p.name,
                address=p.address,
                city=p.city,
                work_time=p.work_time,
                phone=p.phone,
                latitude=p.latitude,
                longitude=p.longitude,
                type=p.type,
                is_dressing_room=p.is_dressing_room,
                have_cashless=p.have_cashless
            )
            for p in points
        ]
        
        return PickupPointsResponse(
            success=True,
            total=len(items),
            points=items
        )
        
    except Exception as e:
        return PickupPointsResponse(
            success=False,
            total=0,
            error=str(e)
        )


@router.get(
    "/cities",
    response_model=CitiesResponse,
    summary="Поиск городов",
    description="Найти города по названию."
)
async def search_cities(
    query: str = Query(..., min_length=2, description="Строка поиска"),
    limit: int = Query(10, ge=1, le=50)
):
    """
    Поиск городов для автокомплита.
    """
    cdek = get_cdek_service()
    
    try:
        cities = await cdek.search_cities(query=query, limit=limit)
        
        return CitiesResponse(
            success=True,
            cities=[
                CityItem(
                    code=c["code"],
                    city=c["city"],
                    region=c.get("region"),
                    country=c.get("country", "Россия")
                )
                for c in cities
            ]
        )
        
    except Exception as e:
        return CitiesResponse(success=False, cities=[])


@router.get(
    "/tracking/{tracking_number}",
    response_model=TrackingResponse,
    summary="Отслеживание заказа",
    description="Получить статус доставки по трек-номеру СДЭК."
)
async def track_order(
    tracking_number: str,
    user_id: Optional[int] = Depends(get_current_user_optional)
):
    """
    Отследить заказ по номеру СДЭК.
    """
    cdek = get_cdek_service()
    
    try:
        statuses = await cdek.get_order_statuses(tracking_number)
        
        if not statuses:
            return TrackingResponse(
                success=False,
                error="Заказ не найден"
            )
        
        # Последний статус — текущий
        current = statuses[-1] if statuses else None
        
        return TrackingResponse(
            success=True,
            cdek_number=tracking_number,
            status=current.code if current else None,
            status_name=current.name if current else None,
            statuses=[
                TrackingStatus(
                    code=s.code,
                    name=s.name,
                    date_time=s.date_time.isoformat(),
                    city=s.city
                )
                for s in statuses
            ]
        )
        
    except Exception as e:
        return TrackingResponse(
            success=False,
            error=str(e)
        )


# ============================================================
# ВНУТРЕННИЕ ЭНДПОИНТЫ (для админки)
# ============================================================

@router.post(
    "/create-shipment",
    summary="Создать отправление",
    description="Создать заказ на доставку в СДЭК. Только для админов.",
    include_in_schema=False  # Скрываем из документации
)
async def create_shipment(
    order_id: int,
    pvz_code: str,
    user_id: int = Depends(get_current_user)
):
    """
    Создать отправление для заказа.
    
    Этот эндпоинт вызывается из админки после того,
    как заказ готов к отправке.
    """
    # TODO: Проверить права администратора
    # TODO: Получить данные заказа из БД
    # TODO: Создать заказ в СДЭК
    # TODO: Сохранить трек-номер в БД
    
    return {
        "success": True,
        "message": "Функция в разработке"
    }
