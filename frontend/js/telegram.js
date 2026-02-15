/**
 * ============================================================
 * Модуль: telegram.js
 * Описание: Интеграция с Telegram WebApp API
 * ============================================================
 * 
 * Что делает:
 *   - Инициализирует Telegram Mini App
 *   - Настраивает тему и цвета
 *   - Управляет MainButton, BackButton
 *   - Извлекает initData для авторизации
 * 
 * Как представить:
 *   Это "мост" между нашим приложением и Telegram.
 *   Как переводчик — наше приложение говорит на JS,
 *   а Telegram понимает только свой API. Этот модуль переводит.
 * 
 * Использование:
 *   import { tg, initTelegram, showMainButton } from './telegram.js';
 */

// ─── Telegram WebApp объект ───
// Telegram вставляет его в window при открытии Mini App
const tg = window.Telegram?.WebApp;

/**
 * Инициализация Telegram Mini App.
 * 
 * Вызывается один раз при загрузке приложения.
 * Как "рукопожатие" — говорим Telegram, что мы готовы.
 */
function initTelegram() {
    if (!tg) {
        console.warn('⚠️ Telegram WebApp не найден. Работаем в режиме браузера.');
        return false;
    }

    // Говорим Telegram: "Мы загрузились, можно показывать"
    tg.ready();

    // Расширяем на весь экран (убираем верхнюю плашку)
    tg.expand();

    // Включаем обработку закрытия (чтобы пользователь не закрыл случайно)
    tg.enableClosingConfirmation();

    // Устанавливаем цвет шапки
    if (tg.setHeaderColor) {
        tg.setHeaderColor('bg_color');
    }

    // Устанавливаем цвет нижней панели
    if (tg.setBackgroundColor) {
        tg.setBackgroundColor('bg_color');
    }

    console.log('✅ Telegram Mini App инициализирован');
    console.log('📱 Платформа:', tg.platform);
    console.log('🎨 Тема:', tg.colorScheme);

    return true;
}

/**
 * Получить initData для авторизации.
 * 
 * initData — это подписанная Telegram строка с данными юзера.
 * Представь это как "пропуск": Telegram даёт его юзеру,
 * а наш сервер проверяет, что пропуск настоящий.
 * 
 * @returns {string} initData строка
 */
function getInitData() {
    if (!tg) return '';
    return tg.initData || '';
}

/**
 * Получить данные пользователя из Telegram.
 * 
 * @returns {Object|null} { id, first_name, last_name, username, ... }
 */
function getTelegramUser() {
    if (!tg || !tg.initDataUnsafe?.user) return null;
    return tg.initDataUnsafe.user;
}

/**
 * Получить start_param (deep link параметр).
 * 
 * Когда пользователь переходит по ссылке типа:
 * https://t.me/bot?startapp=g_123_r_456
 * 
 * start_param = "g_123_r_456"
 * 
 * @returns {string|null}
 */
function getStartParam() {
    if (!tg || !tg.initDataUnsafe) return null;
    return tg.initDataUnsafe.start_param || null;
}

/**
 * Парсинг deep link параметра.
 * 
 * Формат: g_{groupId}_r_{referrerId}
 * Пример: "g_42_r_7" → { groupId: 42, referrerId: 7 }
 * 
 * @param {string} param - start_param строка
 * @returns {Object} { groupId, referrerId }
 */
function parseStartParam(param) {
    const result = { groupId: null, referrerId: null };
    if (!param) return result;

    const parts = param.split('_');
    // g_42_r_7 → ["g", "42", "r", "7"]
    for (let i = 0; i < parts.length; i++) {
        if (parts[i] === 'g' && parts[i + 1]) {
            result.groupId = parseInt(parts[i + 1]);
        }
        if (parts[i] === 'r' && parts[i + 1]) {
            result.referrerId = parseInt(parts[i + 1]);
        }
    }

    return result;
}

// ─── MainButton (кнопка внизу экрана от Telegram) ───

/**
 * Показать главную кнопку Telegram.
 * 
 * Это специальная кнопка, встроенная в интерфейс Telegram.
 * Она появляется внизу экрана, и юзеры ей доверяют.
 * 
 * @param {string} text - Текст на кнопке
 * @param {Function} callback - Что делать при нажатии
 * @param {Object} options - Дополнительные настройки
 */
function showMainButton(text, callback, options = {}) {
    if (!tg?.MainButton) return;

    const btn = tg.MainButton;
    btn.text = text;

    if (options.color) btn.color = options.color;
    if (options.textColor) btn.textColor = options.textColor;

    // Убираем старые обработчики, чтобы не было дублей
    btn.offClick(callback);
    btn.onClick(callback);

    btn.show();

    if (options.loading) {
        btn.showProgress(true);
    }
}

/**
 * Скрыть главную кнопку.
 */
function hideMainButton() {
    if (!tg?.MainButton) return;
    tg.MainButton.hide();
}

/**
 * Показать/скрыть загрузку на MainButton.
 */
function setMainButtonLoading(loading) {
    if (!tg?.MainButton) return;
    if (loading) {
        tg.MainButton.showProgress(true);
        tg.MainButton.disable();
    } else {
        tg.MainButton.hideProgress();
        tg.MainButton.enable();
    }
}

// ─── BackButton (кнопка "Назад") ───

/**
 * Показать кнопку "Назад" в шапке Telegram.
 * 
 * @param {Function} callback - Что делать при нажатии
 */
function showBackButton(callback) {
    if (!tg?.BackButton) return;
    tg.BackButton.offClick(callback);
    tg.BackButton.onClick(callback);
    tg.BackButton.show();
}

/**
 * Скрыть кнопку "Назад".
 */
function hideBackButton() {
    if (!tg?.BackButton) return;
    tg.BackButton.hide();
}

// ─── Haptic Feedback (вибрация) ───

/**
 * Тактильная обратная связь.
 * 
 * Как вибрация геймпада — телефон слегка вибрирует,
 * давая понять юзеру, что действие выполнено.
 * 
 * @param {string} type - 'success' | 'warning' | 'error' | 'light' | 'medium' | 'heavy'
 */
function haptic(type = 'light') {
    if (!tg?.HapticFeedback) return;

    switch (type) {
        case 'success':
            tg.HapticFeedback.notificationOccurred('success');
            break;
        case 'warning':
            tg.HapticFeedback.notificationOccurred('warning');
            break;
        case 'error':
            tg.HapticFeedback.notificationOccurred('error');
            break;
        case 'light':
        case 'medium':
        case 'heavy':
            tg.HapticFeedback.impactOccurred(type);
            break;
    }
}

// ─── Попапы и диалоги ───

/**
 * Показать нативный попап Telegram.
 * 
 * @param {string} title - Заголовок
 * @param {string} message - Текст
 * @param {Array} buttons - Кнопки [{ type: 'ok', text: 'ОК' }]
 * @returns {Promise<string>} ID нажатой кнопки
 */
function showPopup(title, message, buttons = [{ type: 'ok' }]) {
    return new Promise((resolve) => {
        if (!tg?.showPopup) {
            // Fallback для браузера
            alert(`${title}\n${message}`);
            resolve('ok');
            return;
        }

        tg.showPopup({ title, message, buttons }, (buttonId) => {
            resolve(buttonId);
        });
    });
}

/**
 * Показать подтверждение.
 * 
 * @param {string} message - Текст
 * @returns {Promise<boolean>}
 */
function showConfirm(message) {
    return new Promise((resolve) => {
        if (!tg?.showConfirm) {
            resolve(confirm(message));
            return;
        }

        tg.showConfirm(message, (confirmed) => {
            resolve(confirmed);
        });
    });
}

// ─── Шеринг ───

/**
 * Открыть диалог шеринга в Telegram.
 * 
 * @param {string} url - URL для шеринга
 * @param {string} text - Текст сообщения
 */
function shareUrl(url, text = '') {
    if (!tg) {
        // Fallback
        if (navigator.share) {
            navigator.share({ url, text });
        } else {
            window.open(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`);
        }
        return;
    }

    // Telegram switchInlineQuery или openTelegramLink
    const shareLink = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
    tg.openTelegramLink(shareLink);
}

/**
 * Закрыть Mini App.
 */
function closeApp() {
    if (!tg) {
        window.close();
        return;
    }
    tg.close();
}

/**
 * Проверить, запущено ли приложение в Telegram.
 */
function isInTelegram() {
    return !!tg;
}

/**
 * Получить тему (light/dark).
 */
function getColorScheme() {
    if (!tg) return 'light';
    return tg.colorScheme || 'light';
}

// ─── Экспорт ───
export {
    tg,
    initTelegram,
    getInitData,
    getTelegramUser,
    getStartParam,
    parseStartParam,
    showMainButton,
    hideMainButton,
    setMainButtonLoading,
    showBackButton,
    hideBackButton,
    haptic,
    showPopup,
    showConfirm,
    shareUrl,
    closeApp,
    isInTelegram,
    getColorScheme
};
