"""
Модуль: database/models.py
Описание: Pydantic-модели данных для всех сущностей приложения
Проект: GroupBuy Mini App

Этот файл содержит:
    1. Enum-ы (перечисления) для статусов
    2. Base-модели (общие поля)
    3. Модели для каждой таблицы (Create, Update, Response)

Структура именования:
    - UserCreate — для создания записи
    - UserUpdate — для обновления (все поля опциональны)
    - User — полная модель (ответ API)

Использование:
    from database.models import User, UserCreate, GroupStatus
    
    # Создание пользователя
    new_user = UserCreate(telegram_id=123, username="ivan")
    
    # Проверка статуса
    if group.status == GroupStatus.ACTIVE:
        print("Сбор активен")
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from decimal import Decimal


# ============================================================
# ПЕРЕЧИСЛЕНИЯ (ENUM)
# ============================================================

class UserLevel(str, Enum):
    """
    Уровни пользователей в системе лояльности.
    
    Каждый уровень даёт определённые привилегии:
    - NEWCOMER: Базовый доступ
    - BUYER: 3+ заказа
    - ACTIVIST: 10+ заказов, 20+ приглашений
    - EXPERT: 25+ заказов, может создавать сборы
    - AMBASSADOR: 50+ заказов, VIP-привилегии
    """
    NEWCOMER = "newcomer"      # 🌱 Новичок
    BUYER = "buyer"            # 🛒 Покупатель
    ACTIVIST = "activist"      # ⭐ Активист
    EXPERT = "expert"          # 🔥 Эксперт
    AMBASSADOR = "ambassador"  # 👑 Амбассадор


class GroupStatus(str, Enum):
    """
    Статусы группового сбора.
    
    Жизненный цикл:
    ACTIVE → COMPLETED (если набрали людей)
           → FAILED (если не набрали до дедлайна)
           → CANCELLED (отменён вручную)
    """
    ACTIVE = "active"          # Идёт набор участников
    COMPLETED = "completed"    # Успешно завершён
    FAILED = "failed"          # Не набрали минимум
    CANCELLED = "cancelled"    # Отменён


class OrderStatus(str, Enum):
    """
    Статусы заказа.
    
    Жизненный цикл:
    PENDING → FROZEN → PAID → PROCESSING → SHIPPED → DELIVERED
                  ↓
              REFUNDED (если сбор не состоялся)
    
    Или: любой статус → CANCELLED (отмена)
    """
    PENDING = "pending"        # Ожидает оплаты
    FROZEN = "frozen"          # Деньги заморожены
    PAID = "paid"              # Оплачен (деньги списаны)
    PROCESSING = "processing"  # Обрабатывается
    SHIPPED = "shipped"        # Отправлен
    DELIVERED = "delivered"    # Доставлен
    CANCELLED = "cancelled"    # Отменён
    REFUNDED = "refunded"      # Возвращён


class PaymentStatus(str, Enum):
    """
    Статусы платежа.
    
    PENDING → FROZEN → CHARGED
                  ↓
              REFUNDED / CANCELLED
    """
    PENDING = "pending"        # Ожидает оплаты
    FROZEN = "frozen"          # Заморожен (холд)
    CHARGED = "charged"        # Списан
    REFUNDED = "refunded"      # Возвращён
    CANCELLED = "cancelled"    # Отменён
    FAILED = "failed"          # Ошибка


class PaymentMethod(str, Enum):
    """Способы оплаты."""
    CARD = "card"              # Банковская карта
    SBP = "sbp"                # Система быстрых платежей
    TELEGRAM_PAY = "telegram_pay"  # Telegram Pay


class ReturnStatus(str, Enum):
    """
    Статусы заявки на возврат.
    
    PENDING → APPROVED → AWAITING_ITEM → COMPLETED
          ↓
       REJECTED
    """
    PENDING = "pending"        # На рассмотрении
    APPROVED = "approved"      # Одобрен
    REJECTED = "rejected"      # Отклонён
    AWAITING_ITEM = "awaiting_item"  # Ждём товар обратно
    COMPLETED = "completed"    # Завершён (деньги возвращены)


class ReturnReason(str, Enum):
    """Причины возврата товара."""
    WRONG_SIZE = "wrong_size"          # Не подошёл размер/цвет
    DEFECT = "defect"                  # Брак
    NOT_AS_DESCRIBED = "not_as_described"  # Не соответствует описанию
    CHANGED_MIND = "changed_mind"      # Передумал


class SupportTicketStatus(str, Enum):
    """Статусы обращения в поддержку."""
    OPEN = "open"              # Открыт
    IN_PROGRESS = "in_progress"  # В работе
    WAITING_USER = "waiting_user"  # Ожидает ответа пользователя
    CLOSED = "closed"          # Закрыт


class DeliveryType(str, Enum):
    """Типы доставки."""
    COURIER = "courier"        # Курьером
    PICKUP = "pickup"          # Пункт выдачи
    POST = "post"              # Почта России


# ============================================================
# БАЗОВЫЕ МОДЕЛИ
# ============================================================

class TimestampMixin(BaseModel):
    """
    Миксин с полями времени.
    
    Добавляет created_at и updated_at к модели.
    """
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


# ============================================================
# ПОЛЬЗОВАТЕЛИ (USERS)
# ============================================================

class UserCreate(BaseModel):
    """
    Модель для создания пользователя.
    
    Используется при первой авторизации через Telegram.
    
    Пример:
        user_data = UserCreate(
            telegram_id=123456789,
            username="ivan_petrov",
            first_name="Иван"
        )
    """
    telegram_id: int = Field(..., description="ID пользователя в Telegram")
    username: Optional[str] = Field(None, max_length=100, description="Username в Telegram")
    first_name: Optional[str] = Field(None, max_length=100, description="Имя")
    last_name: Optional[str] = Field(None, max_length=100, description="Фамилия")
    phone: Optional[str] = Field(None, max_length=20, description="Телефон")
    
    class Config:
        json_schema_extra = {
            "example": {
                "telegram_id": 123456789,
                "username": "ivan_petrov",
                "first_name": "Иван",
                "last_name": "Петров"
            }
        }


class UserUpdate(BaseModel):
    """
    Модель для обновления пользователя.
    
    Все поля опциональны — обновляем только переданные.
    """
    username: Optional[str] = Field(None, max_length=100)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)


class User(TimestampMixin):
    """
    Полная модель пользователя.
    
    Возвращается в ответах API.
    
    Атрибуты:
        id: Внутренний ID в БД
        telegram_id: ID в Telegram
        username: Username в Telegram
        first_name: Имя
        last_name: Фамилия
        phone: Телефон
        level: Уровень лояльности
        total_orders: Всего заказов
        total_savings: Общая экономия (рубли)
        invited_count: Сколько людей пригласил
        groups_organized: Сколько сборов организовал
    """
    id: int
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    level: UserLevel = UserLevel.NEWCOMER
    total_orders: int = 0
    total_savings: Decimal = Decimal("0")
    invited_count: int = 0
    groups_organized: int = 0
    
    class Config:
        from_attributes = True  # Позволяет создавать из ORM-объектов


class UserStats(BaseModel):
    """
    Статистика пользователя для профиля.
    
    Показывает прогресс и достижения.
    """
    level: UserLevel
    level_emoji: str
    level_name: str
    level_progress: float = Field(..., ge=0, le=1, description="Прогресс до след. уровня (0-1)")
    total_orders: int
    total_savings: Decimal
    groups_participated: int
    groups_organized: int
    people_invited: int
    next_level_requirements: Optional[dict] = None


# ============================================================
# ТОВАРЫ (PRODUCTS)
# ============================================================

class PriceTier(BaseModel):
    """
    Ценовой порог для товара.
    
    Определяет цену при определённом количестве участников.
    
    Пример:
        tier = PriceTier(min_quantity=10, price=Decimal("19000"))
        # При 10+ участниках цена = 19000₽
    """
    min_quantity: int = Field(..., ge=1, description="Минимум участников для этой цены")
    price: Decimal = Field(..., gt=0, description="Цена в рублях")


class ProductCreate(BaseModel):
    """
    Модель для создания товара.
    
    Используется админом при добавлении товара в каталог.
    """
    name: str = Field(..., min_length=1, max_length=200, description="Название товара")
    description: Optional[str] = Field(None, max_length=5000, description="Описание")
    image_url: Optional[str] = Field(None, description="URL изображения")
    base_price: Decimal = Field(..., gt=0, description="Базовая (розничная) цена")
    category_id: Optional[int] = Field(None, description="ID категории")
    stock: int = Field(default=0, ge=0, description="Остаток на складе")
    supplier_id: Optional[int] = Field(None, description="ID поставщика")
    price_tiers: List[PriceTier] = Field(default=[], description="Ценовые пороги")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "AirPods Pro 2",
                "description": "Беспроводные наушники Apple с шумоподавлением",
                "image_url": "https://example.com/airpods.jpg",
                "base_price": 25000,
                "category_id": 1,
                "stock": 100,
                "price_tiers": [
                    {"min_quantity": 3, "price": 22000},
                    {"min_quantity": 10, "price": 19000},
                    {"min_quantity": 25, "price": 16500}
                ]
            }
        }


class ProductUpdate(BaseModel):
    """Модель для обновления товара."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    image_url: Optional[str] = None
    base_price: Optional[Decimal] = Field(None, gt=0)
    category_id: Optional[int] = None
    stock: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    price_tiers: Optional[List[PriceTier]] = None


class Product(TimestampMixin):
    """
    Полная модель товара.
    
    Включает рассчитанные поля для удобства фронтенда.
    """
    id: int
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    base_price: Decimal
    category_id: Optional[int] = None
    stock: int = 0
    is_active: bool = True
    price_tiers: List[PriceTier] = []
    
    # Рассчитываемые поля (заполняются в сервисе)
    best_price: Optional[Decimal] = None  # Минимально возможная цена
    total_sold: int = 0  # Сколько раз куплен
    
    class Config:
        from_attributes = True


class ProductWithActiveGroup(Product):
    """
    Товар с информацией об активном сборе.
    
    Используется в ленте товаров для показа текущего прогресса.
    """
    active_group: Optional["GroupBrief"] = None


# ============================================================
# КАТЕГОРИИ (CATEGORIES)
# ============================================================

class Category(BaseModel):
    """Категория товаров."""
    id: int
    name: str
    slug: str  # URL-friendly название
    icon: Optional[str] = None  # Эмодзи или URL иконки
    parent_id: Optional[int] = None  # Для подкатегорий
    products_count: int = 0


# ============================================================
# ГРУППОВЫЕ СБОРЫ (GROUPS)
# ============================================================

class GroupCreate(BaseModel):
    """
    Модель для создания сбора.
    
    Создаётся когда пользователь (эксперт+) инициирует сбор.
    """
    product_id: int = Field(..., description="ID товара")
    min_participants: Optional[int] = Field(None, ge=2, description="Минимум участников")
    max_participants: Optional[int] = Field(None, ge=2, description="Максимум участников")
    deadline_days: Optional[int] = Field(None, ge=1, le=30, description="Срок сбора в днях")


class GroupJoin(BaseModel):
    """
    Модель для присоединения к сбору.
    
    invited_by используется для отслеживания рефералов.
    """
    invited_by_user_id: Optional[int] = Field(None, description="ID пригласившего")


class GroupBrief(BaseModel):
    """
    Краткая информация о сборе для ленты/карточек.
    
    Используется когда не нужна полная информация.
    """
    id: int
    status: GroupStatus
    current_count: int
    current_price: Decimal
    progress_percent: float  # 0-100
    deadline: datetime
    time_left: str  # "2д 14ч" — для отображения


class Group(TimestampMixin):
    """
    Полная модель группового сбора.
    
    Центральная сущность приложения.
    """
    id: int
    product_id: int
    creator_id: int  # Кто создал сбор
    status: GroupStatus = GroupStatus.ACTIVE
    min_participants: int
    max_participants: int
    current_count: int = 0
    deadline: datetime
    
    # Связанные данные (заполняются при запросе)
    product: Optional[Product] = None
    creator: Optional[User] = None
    current_price: Optional[Decimal] = None
    next_price: Optional[Decimal] = None  # Цена на след. пороге
    people_to_next_price: Optional[int] = None  # Сколько до след. порога
    
    class Config:
        from_attributes = True


class GroupDetail(Group):
    """
    Детальная информация о сборе.
    
    Включает информацию о текущем пользователе.
    """
    is_member: bool = False  # Участвует ли текущий юзер
    user_invited_count: int = 0  # Сколько людей привёл юзер
    can_join: bool = True  # Можно ли присоединиться
    
    # Для шеринга
    share_text: Optional[str] = None
    share_url: Optional[str] = None


class GroupMember(BaseModel):
    """Участник сбора."""
    id: int
    group_id: int
    user_id: int
    invited_by_user_id: Optional[int] = None
    joined_at: datetime
    
    # Связанные данные
    user: Optional[User] = None


# ============================================================
# ЗАКАЗЫ (ORDERS)
# ============================================================

class AddressCreate(BaseModel):
    """Модель для создания адреса доставки."""
    title: str = Field(..., max_length=50, description="Название (Дом, Работа)")
    city: str = Field(..., max_length=100)
    street: str = Field(..., max_length=200)
    building: str = Field(..., max_length=20)
    apartment: Optional[str] = Field(None, max_length=20)
    entrance: Optional[str] = Field(None, max_length=10)
    floor: Optional[str] = Field(None, max_length=10)
    postal_code: Optional[str] = Field(None, max_length=10)
    comment: Optional[str] = Field(None, max_length=500)
    is_default: bool = False


class Address(AddressCreate):
    """Полная модель адреса."""
    id: int
    user_id: int
    
    @property
    def full_address(self) -> str:
        """Полный адрес одной строкой."""
        parts = [self.city, self.street, f"д. {self.building}"]
        if self.apartment:
            parts.append(f"кв. {self.apartment}")
        return ", ".join(parts)


class OrderCreate(BaseModel):
    """Модель для создания заказа."""
    group_id: int = Field(..., description="ID сбора")
    address_id: int = Field(..., description="ID адреса доставки")
    delivery_type: DeliveryType = DeliveryType.PICKUP
    comment: Optional[str] = Field(None, max_length=500)


class Order(TimestampMixin):
    """Полная модель заказа."""
    id: int
    user_id: int
    group_id: int
    address_id: int
    final_price: Decimal  # Финальная цена товара
    delivery_cost: Decimal = Decimal("0")
    total_amount: Decimal  # final_price + delivery_cost
    status: OrderStatus = OrderStatus.PENDING
    delivery_type: DeliveryType
    tracking_number: Optional[str] = None
    delivery_service: Optional[str] = None  # "cdek", "russian_post"
    estimated_delivery: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    comment: Optional[str] = None
    
    # Связанные данные
    product: Optional[Product] = None
    group: Optional[Group] = None
    address: Optional[Address] = None
    payment: Optional["Payment"] = None
    
    # Рассчитываемые
    savings: Optional[Decimal] = None  # Сколько сэкономил
    
    class Config:
        from_attributes = True


class OrderTimeline(BaseModel):
    """История изменений статуса заказа."""
    status: OrderStatus
    timestamp: datetime
    comment: Optional[str] = None


# ============================================================
# ПЛАТЕЖИ (PAYMENTS)
# ============================================================

class PaymentCreate(BaseModel):
    """Модель для создания платежа."""
    order_id: int
    method: PaymentMethod = PaymentMethod.CARD
    return_url: Optional[str] = None  # Куда вернуть после оплаты


class Payment(TimestampMixin):
    """Полная модель платежа."""
    id: int
    order_id: int
    amount: Decimal
    status: PaymentStatus = PaymentStatus.PENDING
    method: PaymentMethod
    external_id: Optional[str] = None  # ID в платёжной системе
    frozen_at: Optional[datetime] = None
    charged_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class PaymentResponse(BaseModel):
    """Ответ при создании платежа."""
    payment_id: int
    amount: Decimal
    payment_url: str  # URL для оплаты
    status: PaymentStatus


# ============================================================
# ВОЗВРАТЫ (RETURNS)
# ============================================================

class ReturnCreate(BaseModel):
    """Модель для создания заявки на возврат."""
    order_id: int
    reason: ReturnReason
    description: str = Field(..., min_length=10, max_length=2000)


class Return(TimestampMixin):
    """Полная модель возврата."""
    id: int
    order_id: int
    reason: ReturnReason
    description: str
    photos: List[str] = []  # URLs фотографий
    status: ReturnStatus = ReturnStatus.PENDING
    refund_amount: Optional[Decimal] = None
    admin_comment: Optional[str] = None
    completed_at: Optional[datetime] = None
    
    # Связанные данные
    order: Optional[Order] = None
    
    class Config:
        from_attributes = True


# ============================================================
# ТЕХПОДДЕРЖКА (SUPPORT)
# ============================================================

class SupportMessage(BaseModel):
    """Сообщение в чате поддержки."""
    id: str  # UUID
    sender_type: str  # "user", "support", "bot"
    sender_id: Optional[int] = None
    text: str
    attachments: List[str] = []  # URLs файлов
    created_at: datetime


class SupportTicketCreate(BaseModel):
    """Создание обращения в поддержку."""
    order_id: Optional[int] = None  # Если связано с заказом
    category: str = Field(..., description="Категория обращения")
    message: str = Field(..., min_length=10, max_length=2000)


class SupportTicket(TimestampMixin):
    """Полная модель обращения."""
    id: int
    user_id: int
    order_id: Optional[int] = None
    category: str
    status: SupportTicketStatus = SupportTicketStatus.OPEN
    messages: List[SupportMessage] = []
    
    # Связанные данные
    user: Optional[User] = None
    order: Optional[Order] = None
    
    class Config:
        from_attributes = True


# ============================================================
# УВЕДОМЛЕНИЯ (NOTIFICATIONS)
# ============================================================

class NotificationSettings(BaseModel):
    """Настройки уведомлений пользователя."""
    order_status: bool = True  # Статусы заказов
    price_drops: bool = True  # Падение цены в сборах
    group_reminders: bool = True  # Напоминания о сборах
    new_products: bool = False  # Новые товары
    promotions: bool = False  # Акции


class Notification(BaseModel):
    """Уведомление для пользователя."""
    id: int
    user_id: int
    type: str  # "price_drop", "order_shipped", etc.
    title: str
    message: str
    data: Optional[dict] = None  # Дополнительные данные
    is_read: bool = False
    created_at: datetime


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ МОДЕЛИ
# ============================================================

class PaginatedResponse(BaseModel):
    """Обёртка для пагинированных ответов."""
    items: List
    total: int
    page: int
    per_page: int
    pages: int  # Всего страниц


class ShareData(BaseModel):
    """Данные для шеринга сбора."""
    text: str  # Текст сообщения
    url: str  # Deep link
    button_text: str = "Присоединиться"


class FAQ(BaseModel):
    """Вопрос-ответ для раздела помощи."""
    id: int
    category: str
    question: str
    answer: str
    order: int = 0


# Обновляем forward references
ProductWithActiveGroup.model_rebuild()
GroupDetail.model_rebuild()
Order.model_rebuild()
