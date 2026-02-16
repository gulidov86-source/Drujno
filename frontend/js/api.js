/**
 * ============================================================
 * Модуль: api.js (v2 — ИСПРАВЛЕН)
 * ============================================================
 * 
 * ИСПРАВЛЕНИЯ:
 *   1. authorize() — парсит data.token.access_token (не data.token)
 *   2. Токен хранится в памяти (sessionStorage ненадёжен в Mini App)
 *   3. Кешируем юзера из ответа авторизации (экономим запрос /me)
 *   4. Один retry при 401 вместо бесконечной рекурсии
 */

import { getInitData } from './telegram.js?v=4';

const BASE_URL = window.APP_CONFIG?.apiUrl || '';

// ─── Токен и юзер в памяти ───
let _token = null;
let _cachedUser = null;

function saveToken(t) { _token = t; }
function getToken() { return _token; }
function removeToken() { _token = null; }
function getCachedUser() { return _cachedUser; }
function setCachedUser(u) { _cachedUser = u; }

// ─── HTTP клиент ───

async function request(method, path, body = null, opts = {}) {
    const url = `${BASE_URL}${path}`;
    const headers = { 'Content-Type': 'application/json', ...opts.headers };

    if (_token) headers['Authorization'] = `Bearer ${_token}`;

    const config = { method, headers };
    if (body && method !== 'GET') config.body = JSON.stringify(body);

    try {
        const res = await fetch(url, config);

        if (res.status === 401 && !opts._retried) {
            removeToken();
            const ok = await authorize();
            if (ok) return request(method, path, body, { ...opts, _retried: true });
            throw new ApiError('Требуется авторизация', 401);
        }

        return handleResponse(res);
    } catch (e) {
        if (e instanceof ApiError) throw e;
        throw new ApiError('Нет связи с сервером', 0, 'NETWORK_ERROR');
    }
}

async function handleResponse(res) {
    if (res.status === 204) return null;
    let data;
    try { data = await res.json(); } catch { if (res.ok) return null; throw new ApiError('Ошибка сервера', res.status); }
    if (!res.ok) throw new ApiError(data.detail || data.message || 'Ошибка', res.status);
    return data;
}

class ApiError extends Error {
    constructor(message, status, code = null) {
        super(message); this.name = 'ApiError'; this.status = status; this.code = code;
    }
}

// ─── Авторизация ───

/**
 * Бэкенд /api/users/auth возвращает:
 * {
 *   "user": { id, first_name, level, ... },
 *   "token": { "access_token": "eyJ...", "token_type": "bearer", "expires_in": 604800 },
 *   "is_new": false
 * }
 */
async function authorize() {
    const initData = getInitData();
    if (!initData) { console.warn('⚠️ Нет initData'); return false; }

    try {
        const res = await fetch(`${BASE_URL}/api/users/auth`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_data: initData })
        });
        const data = await res.json();

        // ✅ Ключевое исправление: token.access_token
        if (res.ok && data.token?.access_token) {
            saveToken(data.token.access_token);
            setCachedUser(data.user);
            console.log('✅ Авторизация OK:', data.user?.first_name);
            return true;
        }
        console.error('❌ Авторизация:', data.detail || data);
        return false;
    } catch (e) {
        console.error('❌ Авторизация ошибка:', e);
        return false;
    }
}

// ─── API ───

const api = {
    users: {
        auth: () => authorize(),
        me: async () => { if (_cachedUser) return _cachedUser; return request('GET', '/api/users/me'); },
        meForce: () => request('GET', '/api/users/me'),
        update: (d) => request('PATCH', '/api/users/me', d),
        stats: () => request('GET', '/api/users/me/stats'),
        addresses: () => request('GET', '/api/users/me/addresses'),
        addAddress: (d) => request('POST', '/api/users/me/addresses', d),
        updateAddress: (id, d) => request('PATCH', `/api/users/me/addresses/${id}`, d),
        deleteAddress: (id) => request('DELETE', `/api/users/me/addresses/${id}`),
    },
    products: {
        list: (p = {}) => request('GET', `/api/products${buildQuery(p)}`),
        get: (id) => request('GET', `/api/products/${id}`),
        categories: () => request('GET', '/api/products/categories/'),
        popular: (n = 10) => request('GET', `/api/products/popular/?limit=${n}`),
    },
    groups: {
        list: (p = {}) => request('GET', `/api/groups${buildQuery(p)}`),
        hot: (n = 5) => request('GET', `/api/groups/hot?limit=${n}`),
        get: (id) => request('GET', `/api/groups/${id}`),
        create: (d) => request('POST', '/api/groups', d),
        join: (id, ref = null) => request('POST', `/api/groups/${id}/join`, ref ? { invited_by_user_id: ref } : {}),
        leave: (id) => request('POST', `/api/groups/${id}/leave`),
        share: (id) => request('GET', `/api/groups/${id}/share`),
        my: () => request('GET', '/api/groups/my/all'),
    },
    orders: {
        list: (p = {}) => request('GET', `/api/orders${buildQuery(p)}`),
        get: (id) => request('GET', `/api/orders/${id}`),
        create: (d) => request('POST', '/api/orders', d),
        cancel: (id) => request('POST', `/api/orders/${id}/cancel`),
    },
    payments: {
        status: (oid) => request('GET', `/api/payments/order/${oid}/status`),
    },
};

function buildQuery(p) {
    const f = Object.entries(p).filter(([_, v]) => v != null && v !== '');
    return f.length ? '?' + f.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&') : '';
}

export { api, authorize, saveToken, getToken, removeToken, getCachedUser, setCachedUser, ApiError, BASE_URL };
