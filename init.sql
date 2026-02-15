-- ============================================================
-- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ GROUPBUY MINI APP
-- ============================================================
-- 
-- Как использовать:
-- 1. Открой Supabase Dashboard
-- 2. Перейди в SQL Editor
-- 3. Скопируй и выполни этот скрипт
--
-- ВАЖНО: Выполняй скрипт целиком, не по частям!
-- ============================================================


-- ============================================================
-- РАСШИРЕНИЯ
-- ============================================================

-- UUID для генерации уникальных идентификаторов
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================
-- ТАБЛИЦА: users (Пользователи)
-- ============================================================
-- Хранит данные пользователей из Telegram

CREATE TABLE IF NOT EXISTS users (
    -- Первичный ключ (автоинкремент)
    id BIGSERIAL PRIMARY KEY,
    
    -- ID пользователя в Telegram (уникальный)
    telegram_id BIGINT UNIQUE NOT NULL,
    
    -- Данные профиля из Telegram
    username VARCHAR(100),           -- @username
    first_name VARCHAR(100),         -- Имя
    last_name VARCHAR(100),          -- Фамилия
    phone VARCHAR(20),               -- Телефон (если поделился)
    
    -- Система уровней
    -- Возможные значения: newcomer, buyer, activist, expert, ambassador
    level VARCHAR(20) DEFAULT 'newcomer' NOT NULL,
    
    -- Статистика пользователя
    total_orders INTEGER DEFAULT 0,          -- Всего заказов
    total_savings DECIMAL(12, 2) DEFAULT 0,  -- Общая экономия (рубли)
    invited_count INTEGER DEFAULT 0,         -- Приглашённых людей
    groups_organized INTEGER DEFAULT 0,      -- Организованных сборов
    
    -- Настройки уведомлений (JSON)
    notification_settings JSONB DEFAULT '{
        "order_status": true,
        "price_drops": true,
        "group_reminders": true,
        "new_products": false,
        "promotions": false
    }'::jsonb,
    
    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_level ON users(level);

-- Комментарий к таблице
COMMENT ON TABLE users IS 'Пользователи приложения (из Telegram)';


-- ============================================================
-- ТАБЛИЦА: categories (Категории товаров)
-- ============================================================

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    
    name VARCHAR(100) NOT NULL,          -- Название категории
    slug VARCHAR(100) UNIQUE NOT NULL,   -- URL-friendly название
    icon VARCHAR(50),                    -- Эмодзи или название иконки
    
    -- Для подкатегорий (опционально)
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    
    -- Порядок сортировки
    sort_order INTEGER DEFAULT 0,
    
    -- Активность
    is_active BOOLEAN DEFAULT true,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE categories IS 'Категории товаров';


-- ============================================================
-- ТАБЛИЦА: products (Товары)
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    
    -- Основная информация
    name VARCHAR(200) NOT NULL,
    description TEXT,
    image_url TEXT,                      -- URL главного изображения
    images JSONB DEFAULT '[]'::jsonb,    -- Дополнительные изображения
    
    -- Цены
    base_price DECIMAL(12, 2) NOT NULL,  -- Розничная цена
    
    -- Ценовые пороги (массив объектов)
    -- Формат: [{"min_quantity": 3, "price": 22000}, ...]
    price_tiers JSONB DEFAULT '[]'::jsonb,
    
    -- Связи
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    supplier_id INTEGER,                 -- ID поставщика (если будет таблица)
    
    -- Склад
    stock INTEGER DEFAULT 0,             -- Остаток
    
    -- Статистика
    total_sold INTEGER DEFAULT 0,        -- Продано всего
    
    -- Статус
    is_active BOOLEAN DEFAULT true,
    
    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_name ON products USING gin(to_tsvector('russian', name));

COMMENT ON TABLE products IS 'Каталог товаров';


-- ============================================================
-- ТАБЛИЦА: groups (Групповые сборы)
-- ============================================================
-- Ядро приложения: групповые закупки

CREATE TABLE IF NOT EXISTS groups (
    id BIGSERIAL PRIMARY KEY,
    
    -- Связи
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    creator_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Статус сбора
    -- Возможные значения: active, completed, failed, cancelled
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    
    -- Параметры сбора
    min_participants INTEGER NOT NULL DEFAULT 3,   -- Минимум для успеха
    max_participants INTEGER NOT NULL DEFAULT 100, -- Максимум участников
    current_count INTEGER DEFAULT 0,               -- Текущее количество
    
    -- Сроки
    deadline TIMESTAMP WITH TIME ZONE NOT NULL,    -- Дедлайн сбора
    completed_at TIMESTAMP WITH TIME ZONE,         -- Когда завершился
    
    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_groups_product ON groups(product_id);
CREATE INDEX IF NOT EXISTS idx_groups_status ON groups(status);
CREATE INDEX IF NOT EXISTS idx_groups_deadline ON groups(deadline);
CREATE INDEX IF NOT EXISTS idx_groups_creator ON groups(creator_id);

COMMENT ON TABLE groups IS 'Групповые сборы (закупки)';


-- ============================================================
-- ТАБЛИЦА: group_members (Участники сборов)
-- ============================================================
-- Связь между пользователями и сборами

CREATE TABLE IF NOT EXISTS group_members (
    id BIGSERIAL PRIMARY KEY,
    
    -- Связи
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Реферальная система
    invited_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    
    -- Когда присоединился
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Уникальность: один пользователь — один раз в сборе
    UNIQUE(group_id, user_id)
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_group_members_group ON group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members(user_id);
CREATE INDEX IF NOT EXISTS idx_group_members_invited_by ON group_members(invited_by_user_id);

COMMENT ON TABLE group_members IS 'Участники групповых сборов';


-- ============================================================
-- ТАБЛИЦА: addresses (Адреса доставки)
-- ============================================================

CREATE TABLE IF NOT EXISTS addresses (
    id BIGSERIAL PRIMARY KEY,
    
    -- Владелец адреса
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Название для удобства
    title VARCHAR(50) NOT NULL,          -- "Дом", "Работа"
    
    -- Адрес
    city VARCHAR(100) NOT NULL,
    street VARCHAR(200) NOT NULL,
    building VARCHAR(20) NOT NULL,
    apartment VARCHAR(20),
    entrance VARCHAR(10),
    floor VARCHAR(10),
    postal_code VARCHAR(10),
    
    -- Комментарий курьеру
    comment VARCHAR(500),
    
    -- Адрес по умолчанию
    is_default BOOLEAN DEFAULT false,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индекс
CREATE INDEX IF NOT EXISTS idx_addresses_user ON addresses(user_id);

COMMENT ON TABLE addresses IS 'Адреса доставки пользователей';


-- ============================================================
-- ТАБЛИЦА: orders (Заказы)
-- ============================================================

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    
    -- Связи
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    address_id BIGINT NOT NULL REFERENCES addresses(id) ON DELETE RESTRICT,
    
    -- Цены
    final_price DECIMAL(12, 2) NOT NULL,      -- Цена товара
    delivery_cost DECIMAL(12, 2) DEFAULT 0,   -- Стоимость доставки
    total_amount DECIMAL(12, 2) NOT NULL,     -- Итого (цена + доставка)
    
    -- Статус
    -- pending, frozen, paid, processing, shipped, delivered, cancelled, refunded
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    
    -- Доставка
    delivery_type VARCHAR(20) DEFAULT 'pickup',  -- courier, pickup, post
    tracking_number VARCHAR(50),
    delivery_service VARCHAR(50),                -- cdek, russian_post
    estimated_delivery TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    
    -- Комментарий к заказу
    comment VARCHAR(500),
    
    -- История статусов (JSON массив)
    status_history JSONB DEFAULT '[]'::jsonb,
    
    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_group ON orders(group_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

COMMENT ON TABLE orders IS 'Заказы пользователей';


-- ============================================================
-- ТАБЛИЦА: payments (Платежи)
-- ============================================================

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    
    -- Связь с заказом
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    
    -- Сумма
    amount DECIMAL(12, 2) NOT NULL,
    
    -- Статус
    -- pending, frozen, charged, refunded, cancelled, failed
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    
    -- Способ оплаты: card, sbp, telegram_pay
    method VARCHAR(20) NOT NULL,
    
    -- ID в платёжной системе (ЮKassa)
    external_id VARCHAR(100),
    
    -- Временные метки операций
    frozen_at TIMESTAMP WITH TIME ZONE,    -- Когда заморозили
    charged_at TIMESTAMP WITH TIME ZONE,   -- Когда списали
    refunded_at TIMESTAMP WITH TIME ZONE,  -- Когда вернули
    
    -- Ошибка (если была)
    error_message TEXT,
    
    -- Сырые данные от платёжки (для отладки)
    raw_response JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_external_id ON payments(external_id);

COMMENT ON TABLE payments IS 'Платежи и транзакции';


-- ============================================================
-- ТАБЛИЦА: returns (Возвраты)
-- ============================================================

CREATE TABLE IF NOT EXISTS returns (
    id BIGSERIAL PRIMARY KEY,
    
    -- Связь с заказом
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    
    -- Причина возврата: wrong_size, defect, not_as_described, changed_mind
    reason VARCHAR(30) NOT NULL,
    
    -- Описание проблемы
    description TEXT NOT NULL,
    
    -- Фотографии (массив URL)
    photos JSONB DEFAULT '[]'::jsonb,
    
    -- Статус: pending, approved, rejected, awaiting_item, completed
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    
    -- Сумма возврата
    refund_amount DECIMAL(12, 2),
    
    -- Комментарий администратора
    admin_comment TEXT,
    
    -- Когда завершён
    completed_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индекс
CREATE INDEX IF NOT EXISTS idx_returns_order ON returns(order_id);
CREATE INDEX IF NOT EXISTS idx_returns_status ON returns(status);

COMMENT ON TABLE returns IS 'Заявки на возврат товаров';


-- ============================================================
-- ТАБЛИЦА: support_tickets (Обращения в поддержку)
-- ============================================================

CREATE TABLE IF NOT EXISTS support_tickets (
    id BIGSERIAL PRIMARY KEY,
    
    -- Связи
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id BIGINT REFERENCES orders(id) ON DELETE SET NULL,  -- Опционально
    
    -- Категория обращения
    category VARCHAR(50) NOT NULL,
    
    -- Статус: open, in_progress, waiting_user, closed
    status VARCHAR(20) DEFAULT 'open' NOT NULL,
    
    -- Сообщения (JSON массив)
    -- Формат: [{"id": "uuid", "sender_type": "user", "text": "...", "created_at": "..."}]
    messages JSONB DEFAULT '[]'::jsonb,
    
    -- Резолюция (при закрытии)
    resolution TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_support_user ON support_tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_support_status ON support_tickets(status);

COMMENT ON TABLE support_tickets IS 'Обращения в техподдержку';


-- ============================================================
-- ТАБЛИЦА: notifications (Уведомления)
-- ============================================================

CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    
    -- Получатель
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Тип уведомления
    type VARCHAR(50) NOT NULL,  -- price_drop, order_shipped, group_completed...
    
    -- Содержимое
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    
    -- Дополнительные данные (JSON)
    data JSONB,
    
    -- Прочитано ли
    is_read BOOLEAN DEFAULT false,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, is_read) WHERE is_read = false;

COMMENT ON TABLE notifications IS 'Уведомления для пользователей';


-- ============================================================
-- ТАБЛИЦА: faq (Часто задаваемые вопросы)
-- ============================================================

CREATE TABLE IF NOT EXISTS faq (
    id SERIAL PRIMARY KEY,
    
    category VARCHAR(100) NOT NULL,      -- Категория вопроса
    question TEXT NOT NULL,              -- Вопрос
    answer TEXT NOT NULL,                -- Ответ
    
    sort_order INTEGER DEFAULT 0,        -- Порядок отображения
    is_active BOOLEAN DEFAULT true,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE faq IS 'Часто задаваемые вопросы';


-- ============================================================
-- ФУНКЦИИ И ТРИГГЕРЫ
-- ============================================================

-- Функция для автоматического обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Применяем триггер ко всем таблицам с updated_at
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_groups_updated_at
    BEFORE UPDATE ON groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_returns_updated_at
    BEFORE UPDATE ON returns
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_support_tickets_updated_at
    BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- ФУНКЦИЯ: Обновление счётчика участников сбора
-- ============================================================

CREATE OR REPLACE FUNCTION update_group_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- При добавлении участника
        UPDATE groups 
        SET current_count = current_count + 1,
            updated_at = NOW()
        WHERE id = NEW.group_id;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        -- При удалении участника
        UPDATE groups 
        SET current_count = current_count - 1,
            updated_at = NOW()
        WHERE id = OLD.group_id;
        RETURN OLD;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Триггер на таблицу участников
CREATE TRIGGER trigger_update_group_count
    AFTER INSERT OR DELETE ON group_members
    FOR EACH ROW EXECUTE FUNCTION update_group_count();


-- ============================================================
-- НАЧАЛЬНЫЕ ДАННЫЕ: Категории
-- ============================================================

INSERT INTO categories (name, slug, icon, sort_order) VALUES
    ('Электроника', 'electronics', '📱', 1),
    ('Косметика', 'cosmetics', '💄', 2),
    ('Одежда', 'clothing', '👕', 3),
    ('Дом и сад', 'home', '🏠', 4),
    ('Спорт', 'sports', '⚽', 5),
    ('Детские товары', 'kids', '🧸', 6)
ON CONFLICT (slug) DO NOTHING;


-- ============================================================
-- НАЧАЛЬНЫЕ ДАННЫЕ: FAQ
-- ============================================================

INSERT INTO faq (category, question, answer, sort_order) VALUES
    ('Оплата', 'Когда спишутся деньги?', 
     'Деньги замораживаются при оформлении заказа, но списываются только когда сбор успешно завершится. Если сбор не состоится — деньги вернутся автоматически в течение 24 часов.', 1),
    
    ('Оплата', 'Какие способы оплаты доступны?',
     'Мы принимаем банковские карты (Visa, Mastercard, Мир) и оплату через СБП (Систему быстрых платежей).', 2),
    
    ('Сборы', 'Как работает групповой сбор?',
     'Вы присоединяетесь к сбору на товар. Чем больше людей участвует — тем ниже цена для всех. Когда набирается минимум участников или истекает срок, сбор завершается и товар отправляется.', 3),
    
    ('Сборы', 'Что если сбор не состоится?',
     'Если не набралось минимальное количество участников до дедлайна, сбор отменяется и все деньги возвращаются автоматически.', 4),
    
    ('Доставка', 'Как узнать статус доставки?',
     'Статус заказа и трек-номер появятся в разделе "Мои заказы" после отправки. Вы также получите уведомление в Telegram.', 5),
    
    ('Возврат', 'Как оформить возврат?',
     'Откройте заказ в разделе "Мои заказы" и нажмите "Оформить возврат". Заполните причину и приложите фото (если товар с браком). Мы рассмотрим заявку в течение 2 рабочих дней.', 6)
ON CONFLICT DO NOTHING;


-- ============================================================
-- ГОТОВО!
-- ============================================================

-- Проверка: выводим созданные таблицы
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
