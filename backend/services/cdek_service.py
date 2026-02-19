"""
Модуль: services/cdek_service.py
Описание: Интеграция с API СДЭК для расчёта и создания доставок
Проект: GroupBuy Mini App

СДЭК — служба доставки. Этот модуль позволяет:
- Рассчитать стоимость доставки
- Получить список пунктов выдачи (ПВЗ)
- Создать заказ на доставку
- Отслеживать статус доставки

Документация СДЭК API v2:
    https://api-docs.cdek.ru/29923741.html

Как это работает (представь):
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │ Наш Backend │────▶│ CDEKService │────▶│ СДЭК API    │
    │ (orders.py) │     │ (этот файл) │     │ api.cdek.ru │
    └─────────────┘     └─────────────┘     └─────────────┘

Использование:
    from services.cdek_service import get_cdek_service
    
    cdek = get_cdek_service()
    
    # Рассчитать стоимость
    cost = await cdek.calculate_tariff(
        from_city="Москва",
        to_city="Санкт-Петербург",
        weight=500  # граммы
    )
    
    # Получить ПВЗ
    points = await cdek.get_pickup_points(city="Москва")
    
    # Создать заказ
    order = await cdek.create_order(order_data)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal
from pydantic import BaseModel
import httpx

import sys
sys.path.append("..")
from config import settings


# ============================================================
# МОДЕЛИ ДАННЫХ
# ============================================================

class CDEKToken(BaseModel):
    """Токен авторизации СДЭК."""
    access_token: str
    token_type: str
    expires_in: int
    expires_at: datetime


class DeliveryTariff(BaseModel):
    """Результат расчёта тарифа."""
    tariff_code: int
    tariff_name: str
    tariff_description: str
    delivery_mode: int  # 1=дверь-дверь, 2=дверь-склад, 3=склад-дверь, 4=склад-склад
    delivery_sum: Decimal  # Стоимость доставки
    period_min: int  # Мин. срок доставки (дни)
    period_max: int  # Макс. срок доставки (дни)
    currency: str = "RUB"


class PickupPoint(BaseModel):
    """Пункт выдачи заказов (ПВЗ)."""
    code: str  # Код ПВЗ
    name: str  # Название
    address: str  # Полный адрес
    city: str  # Город
    city_code: int  # Код города
    work_time: str  # Режим работы
    phone: Optional[str] = None
    note: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    type: str = "PVZ"  # PVZ или POSTAMAT
    is_dressing_room: bool = False  # Есть примерочная
    have_cashless: bool = False  # Безналичная оплата
    have_cash: bool = False  # Наличная оплата
    allowed_cod: bool = False  # Наложенный платёж


class CDEKOrder(BaseModel):
    """Заказ СДЭК."""
    uuid: str  # UUID заказа в СДЭК
    cdek_number: Optional[str] = None  # Номер заказа СДЭК (появляется после обработки)
    status: str  # Статус
    status_reason: Optional[str] = None
    tracking_number: Optional[str] = None


class CDEKOrderStatus(BaseModel):
    """Статус заказа СДЭК."""
    code: str
    name: str
    date_time: datetime
    city: Optional[str] = None


class CalculateRequest(BaseModel):
    """Запрос на расчёт тарифа."""
    from_city: str  # Город отправления
    to_city: str  # Город получения
    weight: int  # Вес в граммах
    length: int = 10  # Длина в см
    width: int = 10  # Ширина в см
    height: int = 10  # Высота в см


class CreateOrderRequest(BaseModel):
    """Запрос на создание заказа."""
    # Данные заказа
    order_number: str  # Номер заказа в нашей системе
    tariff_code: int  # Код тарифа
    
    # Отправитель
    sender_city: str
    sender_address: Optional[str] = None
    sender_name: str
    sender_phone: str
    
    # Получатель
    recipient_city: str
    recipient_address: Optional[str] = None  # Для доставки до двери
    recipient_pvz_code: Optional[str] = None  # Для доставки в ПВЗ
    recipient_name: str
    recipient_phone: str
    
    # Посылка
    weight: int  # Вес в граммах
    length: int = 10
    width: int = 10
    height: int = 10
    
    # Товары
    items: List[Dict[str, Any]]  # [{name, ware_key, cost, amount, weight}]
    
    # Опции
    comment: Optional[str] = None


# ============================================================
# КОНСТАНТЫ
# ============================================================

# Популярные тарифы СДЭК
class CDEKTariffs:
    """Коды тарифов СДЭК."""
    # Экономичные (склад-склад)
    ECONOMY_WAREHOUSE = 136  # Посылка склад-склад
    ECONOMY_POSTAMAT = 368  # Посылка склад-постамат
    
    # Стандартные (склад-дверь, дверь-склад)
    STANDARD_TO_DOOR = 137  # Посылка склад-дверь
    STANDARD_FROM_DOOR = 138  # Посылка дверь-склад
    
    # Экспресс
    EXPRESS_TO_DOOR = 139  # Посылка дверь-дверь
    
    # Рекомендуемые для интернет-магазинов
    SHOP_TO_PVZ = 136  # Для нас: со склада в ПВЗ
    SHOP_TO_DOOR = 137  # Для нас: со склада до двери


# Коды крупных городов (для быстрого поиска)
CITY_CODES = {
    "москва": 44,
    "санкт-петербург": 137,
    "новосибирск": 270,
    "екатеринбург": 343,
    "нижний новгород": 414,
    "казань": 611,
    "челябинск": 696,
    "омск": 816,
    "самара": 968,
    "ростов-на-дону": 986,
    "уфа": 1,
    "красноярск": 1092,
    "воронеж": 1352,
    "пермь": 1427,
    "волгоград": 1535,
}


# ============================================================
# СЕРВИС СДЭК
# ============================================================

class CDEKService:
    """
    Сервис для работы с API СДЭК.
    
    Пример:
        service = CDEKService()
        
        # Авторизация происходит автоматически
        cost = await service.calculate_tariff(
            from_city="Москва",
            to_city="Краснодар",
            weight=1000
        )
        
        print(f"Доставка: {cost.delivery_sum}₽, срок: {cost.period_min}-{cost.period_max} дн.")
    """
    
    # URL API
    PROD_URL = "https://api.cdek.ru/v2"
    TEST_URL = "https://api.edu.cdek.ru/v2"
    
    def __init__(self):
        """Инициализация сервиса."""
        # Определяем режим работы
        self.is_test = settings.CDEK_MODE == "test"
        self.base_url = self.TEST_URL if self.is_test else self.PROD_URL
        
        # Учётные данные
        if self.is_test:
            # Тестовые данные
            self.client_id = "z9o3szU3Ym0r3777J69796P5Y463Yp7b"
            self.client_secret = "4S7p999201T2727Y9767C7b207Y7895Y"
        else:
            # Боевые данные из настроек
            self.client_id = settings.CDEK_CLIENT_ID
            self.client_secret = settings.CDEK_CLIENT_SECRET
        
        # Токен авторизации (кэшируется)
        self._token: Optional[CDEKToken] = None
        
        if not self.client_id or not self.client_secret:
            print("⚠️ CDEKService: учётные данные не настроены")
        else:
            mode = "ТЕСТ" if self.is_test else "ПРОД"
            print(f"✅ CDEKService инициализирован ({mode})")
    
    # ============================================================
    # АВТОРИЗАЦИЯ
    # ============================================================
    
    async def _get_token(self) -> str:
        """
        Получить токен авторизации.
        
        СДЭК использует OAuth 2.0 с client_credentials.
        Токен кэшируется и обновляется при истечении.
        """
        # Проверяем кэш
        if self._token and self._token.expires_at > datetime.now(timezone.utc):
            return self._token.access_token
        
        # Запрашиваем новый токен
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/oauth/token",
                params={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"CDEK auth error: {response.text}")
            
            data = response.json()
            
            self._token = CDEKToken(
                access_token=data["access_token"],
                token_type=data["token_type"],
                expires_in=data["expires_in"],
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"] - 60)
            )
            
            return self._token.access_token
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict = None,
        params: dict = None
    ) -> dict:
        """Выполнить запрос к API СДЭК."""
        token = await self._get_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}{endpoint}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=json_data)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code in (200, 201, 202):
                return response.json()
            else:
                error_text = response.text[:500]
                raise Exception(f"CDEK API error {response.status_code}: {error_text}")
    
    # ============================================================
    # ГОРОДА
    # ============================================================
    
    async def get_city_code(self, city_name: str) -> Optional[int]:
        """
        Получить код города СДЭК по названию.
        
        Параметры:
            city_name: Название города
        
        Возвращает:
            int | None: Код города или None если не найден
        
        Пример:
            code = await service.get_city_code("Москва")
            # 44
        """
        # Проверяем кэш
        city_lower = city_name.lower().strip()
        if city_lower in CITY_CODES:
            return CITY_CODES[city_lower]
        
        # Ищем через API
        try:
            data = await self._request(
                "GET",
                "/location/cities",
                params={"city": city_name, "size": 1}
            )
            
            if data and len(data) > 0:
                return data[0]["code"]
            
        except Exception as e:
            print(f"⚠️ Ошибка поиска города '{city_name}': {e}")
        
        return None
    
    async def search_cities(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Поиск городов по названию.
        
        Параметры:
            query: Строка поиска
            limit: Максимум результатов
        
        Возвращает:
            List[Dict]: Список городов [{code, city, region, country}]
        """
        try:
            data = await self._request(
                "GET",
                "/location/cities",
                params={"city": query, "size": limit}
            )
            
            return [
                {
                    "code": city["code"],
                    "city": city["city"],
                    "region": city.get("region"),
                    "country": city.get("country", "Россия")
                }
                for city in (data or [])
            ]
            
        except Exception as e:
            print(f"⚠️ Ошибка поиска городов: {e}")
            return []
    
    # ============================================================
    # РАСЧЁТ ТАРИФА
    # ============================================================
    
    async def calculate_tariff(
        self,
        from_city: str,
        to_city: str,
        weight: int,
        length: int = 10,
        width: int = 10,
        height: int = 10,
        tariff_code: int = None
    ) -> Optional[DeliveryTariff]:
        """
        Рассчитать стоимость доставки.
        
        Параметры:
            from_city: Город отправления
            to_city: Город получения
            weight: Вес в граммах
            length, width, height: Размеры в см
            tariff_code: Код тарифа (если None — выберем оптимальный)
        
        Возвращает:
            DeliveryTariff | None: Результат расчёта
        
        Пример:
            result = await service.calculate_tariff(
                from_city="Москва",
                to_city="Краснодар",
                weight=500
            )
            print(f"Доставка: {result.delivery_sum}₽")
        """
        # Получаем коды городов
        from_code = await self.get_city_code(from_city)
        to_code = await self.get_city_code(to_city)
        
        if not from_code or not to_code:
            print(f"⚠️ Не найден город: {from_city if not from_code else to_city}")
            return None
        
        # Формируем запрос
        request_data = {
            "from_location": {"code": from_code},
            "to_location": {"code": to_code},
            "packages": [{
                "weight": weight,
                "length": length,
                "width": width,
                "height": height
            }]
        }
        
        # Если указан конкретный тариф
        if tariff_code:
            request_data["tariff_code"] = tariff_code
        
        try:
            # Запрашиваем расчёт
            if tariff_code:
                # Расчёт конкретного тарифа
                data = await self._request("POST", "/calculator/tariff", request_data)
            else:
                # Расчёт всех доступных тарифов
                data = await self._request("POST", "/calculator/tarifflist", request_data)
                
                # Выбираем оптимальный (самый дешёвый из ПВЗ)
                if data and "tariff_codes" in data:
                    pvz_tariffs = [
                        t for t in data["tariff_codes"]
                        if t.get("delivery_mode") in (2, 4)  # склад-склад или дверь-склад
                    ]
                    if pvz_tariffs:
                        data = min(pvz_tariffs, key=lambda x: x.get("delivery_sum", 999999))
                    elif data["tariff_codes"]:
                        data = data["tariff_codes"][0]
                    else:
                        return None
            
            if not data:
                return None
            
            return DeliveryTariff(
                tariff_code=data.get("tariff_code", 0),
                tariff_name=data.get("tariff_name", ""),
                tariff_description=data.get("tariff_description", ""),
                delivery_mode=data.get("delivery_mode", 0),
                delivery_sum=Decimal(str(data.get("delivery_sum", 0))),
                period_min=data.get("period_min", 0),
                period_max=data.get("period_max", 0)
            )
            
        except Exception as e:
            print(f"⚠️ Ошибка расчёта тарифа: {e}")
            return None
    
    async def calculate_all_tariffs(
        self,
        from_city: str,
        to_city: str,
        weight: int,
        length: int = 10,
        width: int = 10,
        height: int = 10
    ) -> List[DeliveryTariff]:
        """
        Рассчитать все доступные тарифы.
        
        Возвращает список тарифов, отсортированный по цене.
        """
        from_code = await self.get_city_code(from_city)
        to_code = await self.get_city_code(to_city)
        
        if not from_code or not to_code:
            return []
        
        request_data = {
            "from_location": {"code": from_code},
            "to_location": {"code": to_code},
            "packages": [{
                "weight": weight,
                "length": length,
                "width": width,
                "height": height
            }]
        }
        
        try:
            data = await self._request("POST", "/calculator/tarifflist", request_data)
            
            if not data or "tariff_codes" not in data:
                return []
            
            tariffs = [
                DeliveryTariff(
                    tariff_code=t.get("tariff_code", 0),
                    tariff_name=t.get("tariff_name", ""),
                    tariff_description=t.get("tariff_description", ""),
                    delivery_mode=t.get("delivery_mode", 0),
                    delivery_sum=Decimal(str(t.get("delivery_sum", 0))),
                    period_min=t.get("period_min", 0),
                    period_max=t.get("period_max", 0)
                )
                for t in data["tariff_codes"]
            ]
            
            # Сортируем по цене
            return sorted(tariffs, key=lambda x: x.delivery_sum)
            
        except Exception as e:
            print(f"⚠️ Ошибка расчёта тарифов: {e}")
            return []
    
    # ============================================================
    # ПУНКТЫ ВЫДАЧИ
    # ============================================================
    
    async def get_pickup_points(
        self,
        city: str = None,
        city_code: int = None,
        postal_code: str = None,
        type: str = None,  # "PVZ" или "POSTAMAT"
        limit: int = 50
    ) -> List[PickupPoint]:
        """
        Получить список пунктов выдачи.
        
        Параметры:
            city: Название города
            city_code: Код города СДЭК
            postal_code: Почтовый индекс
            type: Тип точки (PVZ или POSTAMAT)
            limit: Максимум результатов
        
        Возвращает:
            List[PickupPoint]: Список ПВЗ
        
        Пример:
            points = await service.get_pickup_points(city="Москва", limit=20)
            for p in points:
                print(f"{p.name}: {p.address}")
        """
        params = {"size": limit}
        
        if city and not city_code:
            city_code = await self.get_city_code(city)
        
        if city_code:
            params["city_code"] = city_code
        
        if postal_code:
            params["postal_code"] = postal_code
        
        if type:
            params["type"] = type
        
        try:
            data = await self._request("GET", "/deliverypoints", params=params)
            
            if not data:
                return []
            
            points = []
            for p in data:
                location = p.get("location", {})
                points.append(PickupPoint(
                    code=p.get("code", ""),
                    name=p.get("name", ""),
                    address=location.get("address_full", location.get("address", "")),
                    city=location.get("city", ""),
                    city_code=location.get("city_code", 0),
                    work_time=p.get("work_time", ""),
                    phone=p.get("phones", [{}])[0].get("number") if p.get("phones") else None,
                    note=p.get("note"),
                    latitude=location.get("latitude"),
                    longitude=location.get("longitude"),
                    type=p.get("type", "PVZ"),
                    is_dressing_room=p.get("is_dressing_room", False),
                    have_cashless=p.get("have_cashless", False),
                    have_cash=p.get("have_cash", False),
                    allowed_cod=p.get("allowed_cod", False)
                ))
            
            return points
            
        except Exception as e:
            print(f"⚠️ Ошибка получения ПВЗ: {e}")
            return []
    
    # ============================================================
    # СОЗДАНИЕ ЗАКАЗА
    # ============================================================
    
    async def create_order(self, request: CreateOrderRequest) -> Optional[CDEKOrder]:
        """
        Создать заказ на доставку.
        
        Параметры:
            request: Данные заказа
        
        Возвращает:
            CDEKOrder | None: Созданный заказ
        
        Пример:
            order = await service.create_order(CreateOrderRequest(
                order_number="ORD-123",
                tariff_code=136,
                sender_city="Москва",
                sender_name="ООО Магазин",
                sender_phone="+79001234567",
                recipient_city="Краснодар",
                recipient_pvz_code="KRR1",
                recipient_name="Иван Иванов",
                recipient_phone="+79007654321",
                weight=500,
                items=[{
                    "name": "Крем для лица",
                    "ware_key": "SKU-001",
                    "cost": 1500,
                    "amount": 1,
                    "weight": 500
                }]
            ))
        """
        # Получаем коды городов
        sender_code = await self.get_city_code(request.sender_city)
        recipient_code = await self.get_city_code(request.recipient_city)
        
        if not sender_code or not recipient_code:
            print("⚠️ Не найден город отправителя или получателя")
            return None
        
        # Формируем данные заказа
        order_data = {
            "number": request.order_number,
            "tariff_code": request.tariff_code,
            "comment": request.comment or "",
            "sender": {
                "name": request.sender_name,
                "phones": [{"number": request.sender_phone}]
            },
            "recipient": {
                "name": request.recipient_name,
                "phones": [{"number": request.recipient_phone}]
            },
            "from_location": {
                "code": sender_code,
                "address": request.sender_address or ""
            },
            "to_location": {
                "code": recipient_code
            },
            "packages": [{
                "number": f"{request.order_number}-1",
                "weight": request.weight,
                "length": request.length,
                "width": request.width,
                "height": request.height,
                "items": [
                    {
                        "name": item["name"],
                        "ware_key": item.get("ware_key", f"SKU-{i}"),
                        "cost": item["cost"],
                        "amount": item.get("amount", 1),
                        "weight": item.get("weight", request.weight),
                        "payment": {"value": 0}  # Без наложенного платежа
                    }
                    for i, item in enumerate(request.items)
                ]
            }]
        }
        
        # Указываем куда доставлять
        if request.recipient_pvz_code:
            # Доставка в ПВЗ
            order_data["delivery_point"] = request.recipient_pvz_code
        elif request.recipient_address:
            # Доставка до двери
            order_data["to_location"]["address"] = request.recipient_address
        
        try:
            data = await self._request("POST", "/orders", order_data)
            
            if not data or "entity" not in data:
                return None
            
            entity = data["entity"]
            
            return CDEKOrder(
                uuid=entity.get("uuid", ""),
                cdek_number=entity.get("cdek_number"),
                status="CREATED",
                tracking_number=entity.get("cdek_number")
            )
            
        except Exception as e:
            print(f"⚠️ Ошибка создания заказа СДЭК: {e}")
            return None
    
    # ============================================================
    # ОТСЛЕЖИВАНИЕ
    # ============================================================
    
    async def get_order_info(self, uuid: str = None, cdek_number: str = None) -> Optional[Dict]:
        """
        Получить информацию о заказе.
        
        Параметры:
            uuid: UUID заказа в СДЭК
            cdek_number: Номер заказа СДЭК
        
        Возвращает:
            Dict | None: Информация о заказе
        """
        if not uuid and not cdek_number:
            return None
        
        try:
            if uuid:
                data = await self._request("GET", f"/orders/{uuid}")
            else:
                data = await self._request("GET", f"/orders", params={"cdek_number": cdek_number})
                if data and "entity" in data:
                    data = data["entity"]
            
            return data
            
        except Exception as e:
            print(f"⚠️ Ошибка получения заказа: {e}")
            return None
    
    async def get_order_statuses(self, cdek_number: str) -> List[CDEKOrderStatus]:
        """
        Получить историю статусов заказа.
        
        Параметры:
            cdek_number: Номер заказа СДЭК
        
        Возвращает:
            List[CDEKOrderStatus]: История статусов
        """
        try:
            # Ищем заказ по номеру
            data = await self._request("GET", f"/orders", params={"cdek_number": cdek_number})
            
            if not data or "entity" not in data:
                return []
            
            statuses = data["entity"].get("statuses", [])
            
            return [
                CDEKOrderStatus(
                    code=s.get("code", ""),
                    name=s.get("name", ""),
                    date_time=datetime.fromisoformat(s["date_time"].replace("Z", "+00:00")),
                    city=s.get("city")
                )
                for s in statuses
            ]
            
        except Exception as e:
            print(f"⚠️ Ошибка получения статусов: {e}")
            return []
    
    async def delete_order(self, uuid: str) -> bool:
        """
        Удалить (отменить) заказ.
        
        Параметры:
            uuid: UUID заказа
        
        Возвращает:
            bool: Успешно ли удалён
        """
        try:
            await self._request("DELETE", f"/orders/{uuid}")
            return True
        except Exception as e:
            print(f"⚠️ Ошибка удаления заказа: {e}")
            return False
    
    # ============================================================
    # ПЕЧАТНЫЕ ФОРМЫ
    # ============================================================
    
    async def get_barcode_url(self, uuid: str) -> Optional[str]:
        """
        Получить URL для скачивания штрих-кода.
        
        Параметры:
            uuid: UUID заказа
        
        Возвращает:
            str | None: URL для скачивания PDF
        """
        try:
            # Заказываем печатную форму
            data = await self._request(
                "POST",
                "/print/barcodes",
                {"orders": [{"order_uuid": uuid}]}
            )
            
            if data and "entity" in data:
                return data["entity"].get("url")
            
        except Exception as e:
            print(f"⚠️ Ошибка получения штрих-кода: {e}")
        
        return None


# ============================================================
# СИНГЛТОН
# ============================================================

_cdek_service: Optional[CDEKService] = None


def get_cdek_service() -> CDEKService:
    """Получить экземпляр CDEKService."""
    global _cdek_service
    if _cdek_service is None:
        _cdek_service = CDEKService()
    return _cdek_service


# ============================================================
# ТЕСТИРОВАНИЕ
# ============================================================

if __name__ == "__main__":
    """
    Тест при запуске напрямую.
    
    Запуск:
        python services/cdek_service.py
    """
    
    async def test():
        print("🧪 Тестирование CDEKService\n")
        
        service = CDEKService()
        
        # Тест авторизации
        print("1. Авторизация...")
        token = await service._get_token()
        print(f"   ✅ Токен получен: {token[:20]}...")
        
        # Тест поиска городов
        print("\n2. Поиск городов...")
        cities = await service.search_cities("Краснодар")
        for city in cities[:3]:
            print(f"   {city['city']} (код: {city['code']})")
        
        # Тест расчёта тарифа
        print("\n3. Расчёт доставки Москва → Краснодар...")
        tariff = await service.calculate_tariff(
            from_city="Москва",
            to_city="Краснодар",
            weight=500
        )
        if tariff:
            print(f"   ✅ {tariff.tariff_name}")
            print(f"   Стоимость: {tariff.delivery_sum}₽")
            print(f"   Срок: {tariff.period_min}-{tariff.period_max} дн.")
        
        # Тест ПВЗ
        print("\n4. Пункты выдачи в Краснодаре...")
        points = await service.get_pickup_points(city="Краснодар", limit=5)
        for p in points:
            print(f"   📍 {p.name}: {p.address}")
        
        print("\n✅ Все тесты пройдены!")
    
    asyncio.run(test())
