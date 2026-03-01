/**
 * ============================================================
 * Модуль: main.js (v2 — ИСПРАВЛЕН)
 * ============================================================
 * 
 * ИСПРАВЛЕНИЯ:
 *   1. Юзер берётся из кеша авторизации (не отдельный запрос /me)
 *   2. Категории загружаются параллельно с авторизацией  
 *   3. Быстрый старт — не ждём категории для показа интерфейса
 */

import { initTelegram, getStartParam, parseStartParam, haptic } from './telegram.js?v=4';
import { api, authorize, getCachedUser } from './api.js?v=4';
import { router, hideLoading } from './app.js?v=4';
import {
    renderHome, renderCatalog, renderProduct, renderGroup,
    renderCheckout, renderOrders, renderOrder, renderProfile,
    renderAddresses, renderMyGroups,
    renderReturns, renderReturn,
    renderSupport, renderSupportCreate, renderSupportTicket,
    renderNotifications, renderFAQ,
    renderPrivacy, renderTerms,
    loadNotifBadge, setAppState
} from './pages.js?v=4';

const appState = { user: null, categories: [] };

async function init() {
    console.log('🚀 GroupBuy запуск...');

    // 1. Telegram — мгновенно
    initTelegram();

    // 2. Авторизация + категории ПАРАЛЛЕЛЬНО (вместо последовательно)
    const [authOk, cats] = await Promise.allSettled([
        authorize(),
        api.products.categories().catch(() => [])
    ]);

    // Юзер уже закеширован в authorize()
    if (authOk.status === 'fulfilled' && authOk.value) {
        appState.user = getCachedUser();
        console.log('👤 Юзер:', appState.user?.first_name);
    }

    // Категории
    if (cats.status === 'fulfilled') {
        appState.categories = cats.value || [];
    }

    // 3. Передаём состояние
    setAppState(appState);

    // 4. Маршруты
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
        .on('groups', () => renderMyGroups())
        // Новые маршруты — Этап 2
        .on('returns', () => renderReturns())
        .on('return/:id', (p) => renderReturn(p.id))
        .on('support', () => renderSupport())
        .on('support/create', () => renderSupportCreate())
        .on('support/:id', (p) => renderSupportTicket(p.id))
        .on('notifications', () => renderNotifications())
        .on('faq', () => renderFAQ())
        // Юридические страницы — Этап 3
        .on('privacy', () => renderPrivacy())
        .on('terms', () => renderTerms());

    // 5. Deep link
    const sp = getStartParam();
    if (sp) {
        const { groupId } = parseStartParam(sp);
        if (groupId) {
            hideLoading();
            router.navigate(`group/${groupId}`);
            return;
        }
    }

    // 6. Старт
    hideLoading();
    router.start();

    // 7. Бейдж непрочитанных уведомлений (не блокирует запуск)
    if (appState.user) loadNotifBadge();
}

document.getElementById('navbar')?.addEventListener('click', () => haptic('light'));
document.addEventListener('DOMContentLoaded', init);
