/**
 * ============================================================
 * Модуль: main.js (v3 — полная интеграция)
 * ============================================================
 */

import { initTelegram, getStartParam, parseStartParam, haptic } from './telegram.js?v=5';
import { api, authorize, getCachedUser } from './api.js?v=5';
import { router, hideLoading } from './app.js?v=5';
import {
    renderHome, renderCatalog, renderProduct, renderGroup,
    renderCheckout, renderOrders, renderOrder, renderProfile,
    renderAddresses, renderMyGroups,
    renderReturns, renderReturnCreate,
    renderSupport, renderSupportCreate, renderSupportTicket,
    renderNotifications, renderFAQ,
    setAppState
} from './pages.js?v=5';

const appState = { user: null, categories: [] };

async function init() {
    console.log('🚀 GroupBuy запуск...');

    // 1. Telegram — мгновенно
    initTelegram();

    // 2. Авторизация + категории ПАРАЛЛЕЛЬНО
    const [authOk, cats] = await Promise.allSettled([
        authorize(),
        api.products.categories().catch(() => [])
    ]);

    if (authOk.status === 'fulfilled' && authOk.value) {
        appState.user = getCachedUser();
        console.log('👤 Юзер:', appState.user?.first_name);
    }

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
        // Новые маршруты
        .on('returns', () => renderReturns())
        .on('return/create/:orderId', (p) => renderReturnCreate(p.orderId))
        .on('support', () => renderSupport())
        .on('support/create', () => renderSupportCreate())
        .on('support/:id', (p) => renderSupportTicket(p.id))
        .on('notifications', () => renderNotifications())
        .on('faq', () => renderFAQ());

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

    // 7. Бейдж непрочитанных уведомлений
    loadNotifBadge();
}

async function loadNotifBadge() {
    try {
        const res = await api.notifications.unreadCount();
        const count = res.count || res.unread_count || 0;
        if (count > 0) {
            const profileNav = document.querySelector('[data-page="profile"] .navbar__icon');
            if (profileNav) {
                // Добавляем бейдж если ещё нет
                let badge = profileNav.querySelector('.notif-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'notif-badge';
                    profileNav.style.position = 'relative';
                    profileNav.appendChild(badge);
                }
                badge.textContent = count > 99 ? '99+' : count;
                badge.style.display = '';
            }
        }
    } catch(e) { /* тихо игнорируем */ }
}

document.getElementById('navbar')?.addEventListener('click', () => haptic('light'));
document.addEventListener('DOMContentLoaded', init);
