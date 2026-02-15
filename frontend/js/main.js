/**
 * ============================================================
 * Модуль: main.js
 * Описание: Точка входа — инициализация и запуск приложения
 * ============================================================
 * 
 * Порядок запуска (как заводится автомобиль):
 *   1. Включаем Telegram (вставляем ключ)
 *   2. Авторизуемся (запускаем двигатель)
 *   3. Загружаем данные (прогреваем)
 *   4. Настраиваем роутер (включаем GPS)
 *   5. Проверяем deep link (может сразу ехать в конкретное место)
 *   6. Показываем главную (поехали!)
 */

import { initTelegram, getStartParam, parseStartParam, haptic } from './telegram.js';
import { api, authorize } from './api.js';
import { router, hideLoading, showToast } from './app.js';
import {
    renderHome, renderCatalog, renderProduct, renderGroup,
    renderCheckout, renderOrders, renderOrder, renderProfile,
    renderAddresses, renderMyGroups, setAppState
} from './pages.js';


// ─── Состояние приложения ───
const appState = {
    user: null,
    categories: []
};


// ============================================================
// ИНИЦИАЛИЗАЦИЯ
// ============================================================

async function init() {
    console.log('🚀 Запуск GroupBuy Mini App...');

    // 1. Telegram
    const inTg = initTelegram();
    console.log(inTg ? '✅ Telegram OK' : '⚠️ Режим браузера');

    // 2. Авторизация
    try {
        const authorized = await authorize();
        if (authorized) {
            appState.user = await api.users.me();
            console.log('✅ Авторизация OK:', appState.user?.first_name);
        }
    } catch (e) {
        console.warn('⚠️ Авторизация:', e.message);
    }

    // 3. Загружаем категории
    try {
        const cats = await api.products.categories();
        appState.categories = cats || [];
    } catch (e) {
        console.warn('⚠️ Категории:', e.message);
        appState.categories = [];
    }

    // 4. Передаём состояние в модуль страниц
    setAppState(appState);

    // 5. Настраиваем маршруты
    router
        .on('', () => renderHome())
        .on('catalog', () => renderCatalog())
        .on('product/:id', (p) => renderProduct(p.id))
        .on('group/:id', (p) => renderGroup(p.id))
        .on('checkout/:groupId', (p) => renderCheckout(p.groupId))
        .on('orders', () => renderOrders())
        .on('order/:id', (p) => renderOrder(p.id))
        .on('profile', () => renderProfile())
        .on('addresses', () => renderAddresses())
        .on('groups', () => renderMyGroups());

    // 6. Проверяем deep link (приоритет)
    const startParam = getStartParam();
    if (startParam) {
        const { groupId } = parseStartParam(startParam);
        if (groupId) {
            console.log('🔗 Deep link → группа:', groupId);
            hideLoading();
            router.navigate(`group/${groupId}`);
            return;
        }
    }

    // 7. Убираем загрузку и запускаем роутер
    hideLoading();
    router.start();
}

// ─── Навигация нижней панели: вибрация при нажатии ───
document.getElementById('navbar')?.addEventListener('click', () => {
    haptic('light');
});


// ─── Запуск ───
document.addEventListener('DOMContentLoaded', init);
