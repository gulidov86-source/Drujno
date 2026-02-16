/**
 * ============================================================
 * Модуль: app.js
 * Описание: Утилиты приложения — роутинг, форматирование, helpers
 * ============================================================
 * 
 * Представь это как "набор инструментов":
 *   - Роутер: как GPS-навигатор, показывает нужную страницу
 *   - Форматтер: как калькулятор, красиво показывает цены/даты
 *   - Helpers: всякие мелкие инструменты (тосты, модалки, и т.д.)
 */

import { haptic } from './telegram.js?v=2';

// ============================================================
// РОУТЕР (навигация между страницами)
// ============================================================

/**
 * Простой SPA-роутер на хешах.
 * 
 * Как это работает:
 *   URL: index.html#catalog → показываем страницу каталога
 *   URL: index.html#product/42 → показываем товар ID=42
 * 
 * Почему хеши (#)?
 *   Потому что Mini App — это одна HTML-страница,
 *   а хеш-часть URL не вызывает перезагрузку страницы.
 *   Это как переключение каналов на ТВ — телевизор (страница)
 *   один, а каналы (экраны) разные.
 */
class Router {
    constructor() {
        /** Маршруты: { 'catalog': функция-обработчик } */
        this.routes = {};
        /** Текущий маршрут */
        this.current = '';
        /** История для кнопки "Назад" */
        this.history = [];
        
        // Слушаем изменение хеша
        window.addEventListener('hashchange', () => this._handleRoute());
    }

    /**
     * Зарегистрировать маршрут.
     * 
     * @param {string} path - Путь (например, 'catalog', 'product/:id')
     * @param {Function} handler - Функция-обработчик
     * 
     * Пример:
     *   router.on('product/:id', (params) => showProduct(params.id));
     */
    on(path, handler) {
        this.routes[path] = handler;
        return this; // Для цепочек: router.on('a', fn).on('b', fn)
    }

    /**
     * Перейти на страницу.
     * 
     * @param {string} path - Куда перейти (например, 'product/42')
     * @param {boolean} addToHistory - Добавлять ли в историю
     */
    navigate(path, addToHistory = true) {
        if (addToHistory && this.current) {
            this.history.push(this.current);
        }
        window.location.hash = path;
    }

    /**
     * Вернуться назад.
     */
    back() {
        if (this.history.length > 0) {
            const prev = this.history.pop();
            window.location.hash = prev;
        } else {
            window.location.hash = '';
        }
    }

    /**
     * Запустить роутер (обработать текущий URL).
     */
    start() {
        this._handleRoute();
    }

    /**
     * Внутренний метод: обработка маршрута.
     * 
     * Берёт хеш из URL и ищет подходящий обработчик.
     */
    _handleRoute() {
        const hash = window.location.hash.slice(1) || ''; // Убираем '#'
        this.current = hash;

        // Ищем точное совпадение
        if (this.routes[hash]) {
            this.routes[hash]({});
            return;
        }

        // Ищем маршрут с параметрами (product/:id → product/42)
        for (const [pattern, handler] of Object.entries(this.routes)) {
            const params = this._matchRoute(pattern, hash);
            if (params) {
                handler(params);
                return;
            }
        }

        // Маршрут по умолчанию (главная)
        if (this.routes['']) {
            this.routes['']({}); 
        }
    }

    /**
     * Сопоставить URL с шаблоном маршрута.
     * 
     * Пример:
     *   pattern: 'product/:id'
     *   path: 'product/42'
     *   → { id: '42' }
     */
    _matchRoute(pattern, path) {
        const patternParts = pattern.split('/');
        const pathParts = path.split('/');

        if (patternParts.length !== pathParts.length) return null;

        const params = {};

        for (let i = 0; i < patternParts.length; i++) {
            if (patternParts[i].startsWith(':')) {
                // Это параметр — запоминаем
                const key = patternParts[i].slice(1);
                params[key] = pathParts[i];
            } else if (patternParts[i] !== pathParts[i]) {
                // Не совпадает — этот маршрут не подходит
                return null;
            }
        }

        return params;
    }
}

// Создаём единственный экземпляр роутера
const router = new Router();

// ============================================================
// ФОРМАТИРОВАНИЕ
// ============================================================

/**
 * Форматировать цену в рублях.
 * 
 * Пример:
 *   formatPrice(1990) → "1 990 ₽"
 *   formatPrice(25000) → "25 000 ₽"
 * 
 * @param {number|string} price - Цена
 * @returns {string}
 */
function formatPrice(price) {
    if (price === null || price === undefined) return '';
    const num = typeof price === 'string' ? parseFloat(price) : price;
    return num.toLocaleString('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        maximumFractionDigits: 0,
        minimumFractionDigits: 0
    });
}

/**
 * Рассчитать процент скидки.
 * 
 * Пример:
 *   calcDiscount(25000, 19000) → 24
 *   (было 25000, стало 19000 → скидка 24%)
 */
function calcDiscount(originalPrice, currentPrice) {
    if (!originalPrice || !currentPrice) return 0;
    const orig = parseFloat(originalPrice);
    const curr = parseFloat(currentPrice);
    return Math.round((1 - curr / orig) * 100);
}

/**
 * Форматировать дату.
 * 
 * @param {string|Date} date - Дата
 * @param {string} format - Формат ('short', 'long', 'time', 'relative')
 * 
 * Примеры:
 *   formatDate('2026-02-14', 'short') → "14 фев"
 *   formatDate('2026-02-14', 'long') → "14 февраля 2026"
 *   formatDate('2026-02-14T10:30', 'time') → "10:30"
 *   formatDate('2026-02-14T10:30', 'relative') → "2 часа назад"
 */
function formatDate(date, format = 'short') {
    if (!date) return '';
    const d = new Date(date);
    const now = new Date();

    switch (format) {
        case 'short':
            return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });

        case 'long':
            return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });

        case 'time':
            return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });

        case 'datetime':
            return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
                + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });

        case 'relative': {
            const diffMs = now - d;
            const diffMin = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMin < 1) return 'только что';
            if (diffMin < 60) return `${diffMin} мин назад`;
            if (diffHours < 24) return `${diffHours} ч назад`;
            if (diffDays < 7) return `${diffDays} дн назад`;
            return formatDate(date, 'short');
        }

        default:
            return d.toLocaleDateString('ru-RU');
    }
}

/**
 * Рассчитать оставшееся время до дедлайна.
 * 
 * Возвращает строку вида: "2д 14ч", "3ч 25м", "12м"
 * 
 * @param {string|Date} deadline - Дата дедлайна
 * @returns {Object} { text, urgent, expired }
 */
function getTimeLeft(deadline) {
    if (!deadline) return { text: '', urgent: false, expired: true };

    const now = new Date();
    const end = new Date(deadline);
    const diffMs = end - now;

    if (diffMs <= 0) {
        return { text: 'Завершён', urgent: false, expired: true };
    }

    const days = Math.floor(diffMs / 86400000);
    const hours = Math.floor((diffMs % 86400000) / 3600000);
    const minutes = Math.floor((diffMs % 3600000) / 60000);

    let text;
    if (days > 0) {
        text = `${days}д ${hours}ч`;
    } else if (hours > 0) {
        text = `${hours}ч ${minutes}м`;
    } else {
        text = `${minutes}м`;
    }

    return {
        text,
        urgent: days === 0 && hours < 6, // Меньше 6 часов = срочно
        expired: false
    };
}

/**
 * Склонение слов (русский язык).
 * 
 * Пример:
 *   pluralize(1, 'участник', 'участника', 'участников') → '1 участник'
 *   pluralize(3, 'участник', 'участника', 'участников') → '3 участника'
 *   pluralize(5, 'участник', 'участника', 'участников') → '5 участников'
 */
function pluralize(count, one, few, many) {
    const abs = Math.abs(count) % 100;
    const lastDigit = abs % 10;

    if (abs > 10 && abs < 20) return `${count} ${many}`;
    if (lastDigit > 1 && lastDigit < 5) return `${count} ${few}`;
    if (lastDigit === 1) return `${count} ${one}`;
    return `${count} ${many}`;
}

// ============================================================
// UI HELPERS
// ============================================================

/**
 * Показать тост (уведомление сверху экрана).
 * 
 * Представь: небольшая плашка выезжает сверху,
 * показывает сообщение 3 секунды и уезжает обратно.
 * 
 * @param {string} message - Текст сообщения
 * @param {string} type - 'info' | 'success' | 'error'
 */
function showToast(message, type = 'info') {
    // Удаляем предыдущий тост
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast ${type === 'success' ? 'toast-success' : type === 'error' ? 'toast-error' : ''}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Показываем с небольшой задержкой (для анимации)
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Вибрация
    if (type === 'success') haptic('success');
    if (type === 'error') haptic('error');

    // Убираем через 3 секунды
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Показать нижнюю шторку (bottom sheet).
 * 
 * @param {string} title - Заголовок
 * @param {string} content - HTML содержимое
 * @param {Function} onClose - Callback при закрытии
 * @returns {Object} { close, element }
 */
function showSheet(title, content, onClose = null) {
    // Оверлей (затемнение фона)
    const overlay = document.createElement('div');
    overlay.className = 'sheet-overlay';

    // Шторка
    const sheet = document.createElement('div');
    sheet.className = 'sheet';
    sheet.innerHTML = `
        <div class="sheet__handle"></div>
        <div class="sheet__header">
            <div class="sheet__title">${title}</div>
            <button class="sheet__close" aria-label="Закрыть">✕</button>
        </div>
        <div class="sheet__body">${content}</div>
    `;

    document.body.appendChild(overlay);
    document.body.appendChild(sheet);

    // Показываем с анимацией
    requestAnimationFrame(() => {
        overlay.classList.add('active');
        sheet.classList.add('active');
    });

    // Функция закрытия
    const close = () => {
        overlay.classList.remove('active');
        sheet.classList.remove('active');
        setTimeout(() => {
            overlay.remove();
            sheet.remove();
        }, 350);
        if (onClose) onClose();
    };

    overlay.addEventListener('click', close);
    sheet.querySelector('.sheet__close').addEventListener('click', close);

    return { close, element: sheet };
}

/**
 * Показать страницу загрузки.
 */
function showLoading(text = 'Загрузка...') {
    let loader = document.getElementById('app-loader');
    if (!loader) {
        loader = document.createElement('div');
        loader.id = 'app-loader';
        loader.className = 'loading-overlay';
        loader.innerHTML = `
            <div class="spinner"></div>
            <div class="loading-overlay__text">${text}</div>
        `;
        document.body.appendChild(loader);
    }
    loader.style.display = 'flex';
}

function hideLoading() {
    const loader = document.getElementById('app-loader');
    if (loader) {
        loader.style.display = 'none';
    }
}

/**
 * Создать скелетон-загрузку для карточки товара.
 * 
 * Скелетон — это "скелет" контента, который показывается
 * пока данные загружаются. Вместо текста — серые блоки,
 * которые пульсируют. Это лучше, чем спиннер, потому что
 * пользователь видит структуру будущего контента.
 */
function productCardSkeleton() {
    return `
        <div class="product-card">
            <div class="product-card__img">
                <div class="skeleton skeleton-img"></div>
            </div>
            <div class="product-card__body">
                <div class="skeleton skeleton-text" style="width: 90%"></div>
                <div class="skeleton skeleton-text" style="width: 60%"></div>
                <div class="skeleton skeleton-text" style="width: 40%; margin-top: 8px"></div>
            </div>
        </div>
    `;
}

function hotGroupCardSkeleton() {
    return `
        <div class="hot-group-card">
            <div class="skeleton" style="height: 120px"></div>
            <div class="hot-group-card__body">
                <div class="skeleton skeleton-text" style="width: 80%"></div>
                <div class="skeleton skeleton-text" style="width: 50%"></div>
                <div class="skeleton skeleton-text" style="width: 100%; height: 8px; margin-top: 8px"></div>
            </div>
        </div>
    `;
}

/**
 * Безопасная вставка HTML с экранированием пользовательского ввода.
 */
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Дебаунс — задержка выполнения функции.
 * 
 * Представь: ты набираешь поисковый запрос.
 * Без дебаунса: каждая буква = запрос к серверу.
 * С дебаунсом: ждём 300мс после последней буквы → один запрос.
 * 
 * @param {Function} fn - Функция
 * @param {number} delay - Задержка в мс
 */
function debounce(fn, delay = 300) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

/**
 * Обновить активный пункт навигации.
 */
function setActiveNav(name) {
    document.querySelectorAll('.navbar__item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === name);
    });
}

/**
 * Emoji для уровня пользователя.
 */
function levelEmoji(level) {
    const emojis = {
        newcomer: '🌱',
        buyer: '🛒',
        activist: '⭐',
        expert: '🔥',
        ambassador: '👑'
    };
    return emojis[level] || '🌱';
}

/**
 * Название уровня на русском.
 */
function levelName(level) {
    const names = {
        newcomer: 'Новичок',
        buyer: 'Покупатель',
        activist: 'Активист',
        expert: 'Эксперт',
        ambassador: 'Амбассадор'
    };
    return names[level] || 'Новичок';
}

/**
 * Emoji и текст для статуса заказа.
 */
function orderStatusInfo(status) {
    const info = {
        pending: { emoji: '🕐', text: 'Ожидает оплаты', color: 'warning' },
        frozen: { emoji: '❄️', text: 'Оплата заморожена', color: 'info' },
        paid: { emoji: '✅', text: 'Оплачен', color: 'success' },
        processing: { emoji: '📦', text: 'Обрабатывается', color: 'accent' },
        shipped: { emoji: '🚚', text: 'Отправлен', color: 'accent' },
        delivered: { emoji: '🎉', text: 'Доставлен', color: 'success' },
        cancelled: { emoji: '❌', text: 'Отменён', color: 'danger' },
        refunded: { emoji: '↩️', text: 'Возвращён', color: 'danger' },
    };
    return info[status] || { emoji: '❓', text: status, color: '' };
}

/**
 * Emoji и текст для статуса сбора.
 */
function groupStatusInfo(status) {
    const info = {
        active: { emoji: '🟢', text: 'Идёт набор', color: 'success' },
        completed: { emoji: '✅', text: 'Завершён', color: 'success' },
        failed: { emoji: '❌', text: 'Не состоялся', color: 'danger' },
        cancelled: { emoji: '🚫', text: 'Отменён', color: 'danger' },
    };
    return info[status] || { emoji: '❓', text: status, color: '' };
}

// ─── Экспорт ───
export {
    router,
    Router,
    formatPrice,
    calcDiscount,
    formatDate,
    getTimeLeft,
    pluralize,
    showToast,
    showSheet,
    showLoading,
    hideLoading,
    productCardSkeleton,
    hotGroupCardSkeleton,
    escapeHtml,
    debounce,
    setActiveNav,
    levelEmoji,
    levelName,
    orderStatusInfo,
    groupStatusInfo
};
