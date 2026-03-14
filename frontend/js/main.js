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

import { initTelegram, getStartParam, parseStartParam, haptic } from './telegram.js?v=7';
import { api, authorize, getCachedUser } from './api.js?v=7';
import { router, hideLoading, withErrorBoundary } from './app.js?v=7';
import {
    renderHome, renderCatalog, renderProduct, renderGroup,
    renderCheckout, renderOrders, renderOrder, renderProfile,
    renderAddresses, renderGroupsBrowse, renderMyGroups,
    renderReturns, renderReturn,
    renderSupport, renderSupportCreate, renderSupportTicket,
    renderNotifications, renderFAQ,
    renderPrivacy, renderTerms,
    loadNotifBadge, setAppState
} from './pages.js?v=7';

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
        .on('', () => withErrorBoundary(renderHome))
        .on('catalog', () => withErrorBoundary(renderCatalog))
        .on('product/:id', (p) => withErrorBoundary(renderProduct, p.id))
        .on('group/:id', (p) => withErrorBoundary(renderGroup, p.id))
        .on('checkout/:groupId', (p) => withErrorBoundary(renderCheckout, p.groupId))
        .on('orders', () => withErrorBoundary(renderOrders))
        .on('order/:id', (p) => withErrorBoundary(renderOrder, p.id))
        .on('profile', () => withErrorBoundary(renderProfile))
        .on('addresses', () => withErrorBoundary(renderAddresses))
        .on('groups', () => withErrorBoundary(renderGroupsBrowse))
		.on('my-groups', () => withErrorBoundary(renderMyGroups))
        .on('returns', () => withErrorBoundary(renderReturns))
        .on('return/:id', (p) => withErrorBoundary(renderReturn, p.id))
        .on('support', () => withErrorBoundary(renderSupport))
        .on('support/create', () => withErrorBoundary(renderSupportCreate))
        .on('support/:id', (p) => withErrorBoundary(renderSupportTicket, p.id))
        .on('notifications', () => withErrorBoundary(renderNotifications))
        .on('faq', () => withErrorBoundary(renderFAQ))
        .on('privacy', () => renderPrivacy())   // Статические — без boundary
        .on('terms', () => renderTerms());       // Статические — без boundary

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
