/**
 * ============================================================
 * Модуль: api.js
 * Описание: HTTP-клиент для общения с FastAPI backend
 * ============================================================
 * 
 * Представь это как "почтальона":
 *   - Фронтенд (браузер) пишет письмо (запрос)
 *   - api.js доставляет письмо на сервер
 *   - Сервер отвечает, и api.js приносит ответ обратно
 * 
 * Все запросы автоматически:
 *   - Добавляют JWT токен (авторизация)
 *   - Обрабатывают ошибки
 *   - Показывают уведомления при проблемах
 * 
 * Использование:
 *   import { api } from './api.js';
 *   const products = await api.products.list();
 *   const group = await api.groups.get(42);
 */

import { getInitData } from './telegram.js';

// ─── Настройки ───

// Адрес backend сервера
// В разработке: http://localhost:8000
// В production: тот же домен или переменная окружения
const BASE_URL = window.APP_CONFIG?.apiUrl || '';

// Ключ для хранения JWT токена
const TOKEN_KEY = 'groupbuy_token';

// ─── Хранилище токена ───

/**
 * Сохранить JWT токен.
 * Токен — это как пропуск. Получил один раз при входе,
 * показываешь при каждом запросе.
 */
function saveToken(token) {
    try {
        sessionStorage.setItem(TOKEN_KEY, token);
    } catch (e) {
        // Fallback если sessionStorage недоступен
        window._authToken = token;
    }
}

function getToken() {
    try {
        return sessionStorage.getItem(TOKEN_KEY);
    } catch (e) {
        return window._authToken || null;
    }
}

function removeToken() {
    try {
        sessionStorage.removeItem(TOKEN_KEY);
    } catch (e) {
        window._authToken = null;
    }
}

// ─── Базовый HTTP-клиент ───

/**
 * Выполнить HTTP-запрос к API.
 * 
 * Представь: ты идёшь в магазин.
 *   - method: что делаешь (GET=смотришь, POST=покупаешь, PATCH=меняешь)
 *   - path: в какой отдел идёшь ("/api/products")
 *   - body: что несёшь с собой (данные для отправки)
 *   - headers: твой пропуск (JWT токен)
 * 
 * @param {string} method - HTTP метод (GET, POST, PATCH, DELETE)
 * @param {string} path - Путь API (например, "/api/products")
 * @param {Object} body - Тело запроса (для POST/PATCH)
 * @param {Object} options - Дополнительные параметры
 * @returns {Promise<Object>} Ответ сервера
 */
async function request(method, path, body = null, options = {}) {
    const url = `${BASE_URL}${path}`;

    // Заголовки — "шапка" запроса с метаданными
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    // Добавляем токен авторизации, если есть
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    // Настройки запроса
    const config = {
        method,
        headers,
    };

    // Добавляем тело запроса (если есть)
    if (body && method !== 'GET') {
        config.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(url, config);

        // Если 401 — токен протух, нужна повторная авторизация
        if (response.status === 401) {
            removeToken();
            // Пробуем авторизоваться заново
            const reauthorized = await authorize();
            if (reauthorized) {
                // Повторяем оригинальный запрос с новым токеном
                headers['Authorization'] = `Bearer ${getToken()}`;
                const retryResponse = await fetch(url, { ...config, headers });
                return handleResponse(retryResponse);
            }
            throw new ApiError('Требуется авторизация', 401);
        }

        return handleResponse(response);

    } catch (error) {
        if (error instanceof ApiError) throw error;

        // Ошибка сети (нет интернета, сервер недоступен)
        console.error('🔴 Ошибка сети:', error);
        throw new ApiError(
            'Нет связи с сервером. Проверьте интернет.',
            0,
            'NETWORK_ERROR'
        );
    }
}

/**
 * Обработать ответ сервера.
 * 
 * Проверяем: сервер ответил "ОК" или "Ошибка"?
 */
async function handleResponse(response) {
    // Если нет тела ответа (204 No Content)
    if (response.status === 204) return null;

    let data;
    try {
        data = await response.json();
    } catch {
        if (response.ok) return null;
        throw new ApiError('Ошибка сервера', response.status);
    }

    // Если HTTP статус не 2xx — это ошибка
    if (!response.ok) {
        throw new ApiError(
            data.detail || data.message || 'Неизвестная ошибка',
            response.status,
            data.error_code
        );
    }

    return data;
}

/**
 * Класс ошибки API.
 * 
 * Содержит:
 *   - message: описание ошибки для пользователя
 *   - status: HTTP код (404, 500, и т.д.)
 *   - code: внутренний код ошибки
 */
class ApiError extends Error {
    constructor(message, status, code = null) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
    }
}

// ─── Авторизация ───

/**
 * Авторизация через Telegram initData.
 * 
 * Как это работает:
 * 1. Telegram даёт нам initData (подписанная строка)
 * 2. Мы отправляем её на сервер
 * 3. Сервер проверяет подпись (HMAC-SHA256)
 * 4. Если всё ОК → получаем JWT токен
 * 5. Дальше используем токен для всех запросов
 * 
 * @returns {Promise<boolean>} Успешно ли авторизовались
 */
async function authorize() {
    const initData = getInitData();

    if (!initData) {
        console.warn('⚠️ initData не найден. Работаем без авторизации.');
        return false;
    }

    try {
        const response = await fetch(`${BASE_URL}/api/users/auth`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_data: initData })
        });

        const data = await response.json();

        if (response.ok && data.token) {
            saveToken(data.token);
            console.log('✅ Авторизация успешна');
            return true;
        }

        console.error('❌ Ошибка авторизации:', data);
        return false;

    } catch (error) {
        console.error('❌ Ошибка авторизации:', error);
        return false;
    }
}

// ─── API методы (удобные обёртки) ───
// Вместо того чтобы везде писать request('GET', '/api/products'),
// мы создаём удобные методы: api.products.list()

const api = {

    // ─── Пользователи ───
    users: {
        /** Авторизоваться */
        auth: () => authorize(),

        /** Получить свой профиль */
        me: () => request('GET', '/api/users/me'),

        /** Обновить профиль */
        update: (data) => request('PATCH', '/api/users/me', data),

        /** Получить статистику */
        stats: () => request('GET', '/api/users/me/stats'),

        /** Получить адреса */
        addresses: () => request('GET', '/api/users/me/addresses'),

        /** Добавить адрес */
        addAddress: (data) => request('POST', '/api/users/me/addresses', data),

        /** Обновить адрес */
        updateAddress: (id, data) => request('PATCH', `/api/users/me/addresses/${id}`, data),

        /** Удалить адрес */
        deleteAddress: (id) => request('DELETE', `/api/users/me/addresses/${id}`),
    },

    // ─── Товары ───
    products: {
        /** 
         * Получить список товаров.
         * @param {Object} params - Фильтры
         *   params.category_id — ID категории
         *   params.search — поисковый запрос
         *   params.page — номер страницы
         *   params.per_page — товаров на странице
         *   params.sort — сортировка (price_asc, price_desc, popular, new)
         */
        list: (params = {}) => {
            const query = buildQuery(params);
            return request('GET', `/api/products${query}`);
        },

        /** Получить товар по ID */
        get: (id) => request('GET', `/api/products/${id}`),

        /** Получить категории */
        categories: () => request('GET', '/api/products/categories/'),

        /** Получить популярные товары */
        popular: (limit = 10) => request('GET', `/api/products/popular/?limit=${limit}`),
    },

    // ─── Групповые сборы ───
    groups: {
        /** Получить список сборов */
        list: (params = {}) => {
            const query = buildQuery(params);
            return request('GET', `/api/groups${query}`);
        },

        /** Горячие сборы (вот-вот завершатся) */
        hot: (limit = 5) => request('GET', `/api/groups/hot?limit=${limit}`),

        /** Получить сбор по ID */
        get: (id) => request('GET', `/api/groups/${id}`),

        /** Создать сбор */
        create: (data) => request('POST', '/api/groups', data),

        /** Присоединиться к сбору */
        join: (id, referrerId = null) => {
            const body = referrerId ? { invited_by_user_id: referrerId } : {};
            return request('POST', `/api/groups/${id}/join`, body);
        },

        /** Покинуть сбор */
        leave: (id) => request('POST', `/api/groups/${id}/leave`),

        /** Получить данные для шеринга */
        share: (id) => request('GET', `/api/groups/${id}/share`),

        /** Мои сборы */
        my: () => request('GET', '/api/groups/my/all'),
    },

    // ─── Заказы ───
    orders: {
        /** Получить мои заказы */
        list: (params = {}) => {
            const query = buildQuery(params);
            return request('GET', `/api/orders${query}`);
        },

        /** Получить заказ по ID */
        get: (id) => request('GET', `/api/orders/${id}`),

        /** Создать заказ */
        create: (data) => request('POST', '/api/orders', data),

        /** Отменить заказ */
        cancel: (id) => request('POST', `/api/orders/${id}/cancel`),
    },

    // ─── Платежи ───
    payments: {
        /** Получить статус оплаты заказа */
        status: (orderId) => request('GET', `/api/payments/order/${orderId}/status`),
    },
};

// ─── Утилиты ───

/**
 * Построить query string из объекта параметров.
 * 
 * Пример:
 *   buildQuery({ page: 1, search: 'крем' })
 *   → "?page=1&search=%D0%BA%D1%80%D0%B5%D0%BC"
 * 
 * Представь: ты заполняешь фильтры в интернет-магазине.
 * Эта функция превращает фильтры в строку для URL.
 */
function buildQuery(params) {
    const filtered = Object.entries(params)
        .filter(([_, value]) => value !== null && value !== undefined && value !== '');

    if (filtered.length === 0) return '';

    const query = filtered
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
        .join('&');

    return `?${query}`;
}

// ─── Экспорт ───
export { api, authorize, saveToken, getToken, removeToken, ApiError, BASE_URL };
