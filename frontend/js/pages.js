/**
 * ============================================================
 * Модуль: pages.js
 * Описание: Функции рендеринга всех страниц приложения
 * ============================================================
 * 
 * Каждая функция render* рисует свою «страницу» в контейнере #app.
 * 
 * Представь: #app — это экран телевизора.
 * Каждая render-функция — это «канал».
 * Роутер переключает каналы.
 */

import { api } from './api.js';
import { haptic, showBackButton, hideBackButton, hideMainButton, showMainButton, setMainButtonLoading, shareUrl, showConfirm } from './telegram.js';
import {
    router, formatPrice, calcDiscount, formatDate, getTimeLeft,
    pluralize, showToast, showSheet, escapeHtml, debounce,
    setActiveNav, levelEmoji, levelName, orderStatusInfo, groupStatusInfo,
    productCardSkeleton, hotGroupCardSkeleton
} from './app.js';

// ─── Общее состояние ───
let appState = {
    user: null,
    categories: []
};

export function setAppState(s) { appState = s; }

// ============================================================
// ОБЩИЕ КОМПОНЕНТЫ
// ============================================================

function renderProductCard(product) {
    const discount = calcDiscount(product.base_price, product.best_price);
    return `
        <a href="#product/${product.id}" class="product-card">
            <div class="product-card__img">
                ${product.image_url
                    ? `<img src="${escapeHtml(product.image_url)}" alt="" loading="lazy">`
                    : `<div class="product-card__img-placeholder">🧴</div>`}
                ${discount > 0 ? `<span class="badge badge-hot product-card__badge">-${discount}%</span>` : ''}
            </div>
            <div class="product-card__body">
                <div class="product-card__name">${escapeHtml(product.name)}</div>
                <div class="product-card__prices">
                    ${product.best_price && discount > 0
                        ? `<span class="product-card__price">${formatPrice(product.best_price)}</span>
                           <span class="product-card__old-price">${formatPrice(product.base_price)}</span>`
                        : `<span class="product-card__price">${formatPrice(product.base_price)}</span>`}
                </div>
            </div>
        </a>`;
}


// ============================================================
// ГЛАВНАЯ
// ============================================================

export async function renderHome() {
    setActiveNav('home');
    hideBackButton();
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `
        <div class="page-enter">
            <div class="hero">
                <div class="hero__title">Покупай вместе —<br>плати меньше!</div>
                <div class="hero__subtitle">Собирай группу и получай скидки до 50%</div>
                <button class="hero__btn" onclick="location.hash='catalog'">Смотреть каталог →</button>
            </div>

            <div class="section">
                <div class="section__header">
                    <div class="section__title">🔥 Горячие сборы</div>
                    <a href="#groups" class="section__more">Все →</a>
                </div>
                <div class="products-scroll" id="hot-groups-list">
                    ${hotGroupCardSkeleton().repeat(3)}
                </div>
            </div>

            <div class="section">
                <div class="section__header"><div class="section__title">Категории</div></div>
                <div class="categories-scroll" id="home-categories"></div>
            </div>

            <div class="section">
                <div class="section__header">
                    <div class="section__title">⭐ Популярное</div>
                    <a href="#catalog" class="section__more">Все →</a>
                </div>
                <div class="products-scroll" id="popular-products">
                    ${productCardSkeleton().repeat(4)}
                </div>
            </div>
        </div>`;

    // Параллельная загрузка
    loadHotGroups();
    loadPopularProducts();

    const catContainer = document.getElementById('home-categories');
    if (catContainer && appState.categories.length) {
        catContainer.innerHTML = appState.categories.map(c =>
            `<button class="category-chip" onclick="location.hash='catalog?cat=${c.id}'">${c.icon || '📦'} ${escapeHtml(c.name)}</button>`
        ).join('');
    }
}

async function loadHotGroups() {
    try {
        const groups = await api.groups.hot(5);
        const el = document.getElementById('hot-groups-list');
        if (!el) return;
        if (!groups?.length) {
            el.innerHTML = `<div style="padding:20px;text-align:center;color:var(--text-hint);width:100%">Пока нет активных сборов</div>`;
            return;
        }
        el.innerHTML = groups.map(g => {
            const p = g.product || {};
            const tl = getTimeLeft(g.deadline);
            const disc = calcDiscount(p.base_price, g.current_price);
            const prog = g.current_count / g.min_participants * 100;
            return `
                <a href="#group/${g.id}" class="hot-group-card">
                    <div class="hot-group-card__img">
                        ${p.image_url ? `<img src="${escapeHtml(p.image_url)}" alt="" loading="lazy">` : '<div class="product-card__img-placeholder">🛍</div>'}
                        <div class="hot-group-card__timer">⏳ ${tl.text}</div>
                    </div>
                    <div class="hot-group-card__body">
                        <div class="hot-group-card__name">${escapeHtml(p.name)}</div>
                        <div class="hot-group-card__stats">
                            <div class="hot-group-card__people">👥 ${pluralize(g.current_count,'участник','участника','участников')}</div>
                            <div class="hot-group-card__price">${formatPrice(g.current_price)} ${disc>0?`<span class="price-discount">-${disc}%</span>`:''}</div>
                        </div>
                        <div class="progress-bar"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
                    </div>
                </a>`;
        }).join('');
    } catch(e) { console.error(e); }
}

async function loadPopularProducts() {
    try {
        const products = await api.products.popular(8);
        const el = document.getElementById('popular-products');
        if (!el) return;
        if (!products?.length) { el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-hint);width:100%">Скоро появятся</div>'; return; }
        el.innerHTML = products.map(p => renderProductCard(p)).join('');
    } catch(e) { console.error(e); }
}


// ============================================================
// КАТАЛОГ
// ============================================================

let catState = { search:'', categoryId:null, page:1, sort:'popular' };

export async function renderCatalog() {
    setActiveNav('catalog');
    hideBackButton();
    hideMainButton();

    const hp = new URLSearchParams(location.hash.split('?')[1]||'');
    if (hp.get('cat')) catState.categoryId = parseInt(hp.get('cat'));

    const app = document.getElementById('app');
    app.innerHTML = `
        <div class="page-enter">
            <div class="search-bar">
                <span class="search-bar__icon">🔍</span>
                <input type="text" class="search-bar__input" id="cat-search" placeholder="Найти товар..." value="${escapeHtml(catState.search)}">
                <button class="search-bar__clear ${catState.search?'':'hidden'}" id="cat-clear">✕</button>
            </div>
            <div class="categories-scroll" id="cat-categories"></div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:0 var(--page-padding);margin-bottom:12px">
                <div id="cat-count" class="text-hint" style="font-size:0.85rem"></div>
                <select id="cat-sort" style="background:var(--bg-secondary);border:none;padding:6px 12px;border-radius:var(--radius-full);font-size:0.85rem;font-weight:600;color:var(--text)">
                    <option value="popular">Популярные</option>
                    <option value="price_asc">Дешевле</option>
                    <option value="price_desc">Дороже</option>
                    <option value="new">Новые</option>
                </select>
            </div>
            <div class="product-grid" id="cat-products">${productCardSkeleton().repeat(6)}</div>
            <div id="cat-more" class="hidden" style="padding:16px;text-align:center">
                <button class="btn btn-secondary btn-block" id="cat-more-btn">Загрузить ещё</button>
            </div>
        </div>`;

    // Категории
    const cc = document.getElementById('cat-categories');
    if (cc) {
        cc.innerHTML = `<button class="category-chip ${!catState.categoryId?'active':''}" data-cat="">Все</button>` +
            appState.categories.map(c=>`<button class="category-chip ${catState.categoryId===c.id?'active':''}" data-cat="${c.id}">${c.icon||''} ${escapeHtml(c.name)}</button>`).join('');
        cc.addEventListener('click', e => {
            const chip = e.target.closest('.category-chip');
            if(!chip)return;
            haptic('light');
            catState.categoryId = chip.dataset.cat ? parseInt(chip.dataset.cat) : null;
            catState.page = 1;
            cc.querySelectorAll('.category-chip').forEach(c=>c.classList.remove('active'));
            chip.classList.add('active');
            loadCatalog();
        });
    }

    document.getElementById('cat-sort').value = catState.sort;
    const searchEl = document.getElementById('cat-search');
    const clearEl = document.getElementById('cat-clear');

    const doSearch = debounce(() => { catState.search=searchEl.value; catState.page=1; loadCatalog(); }, 400);
    searchEl.addEventListener('input', () => { clearEl.classList.toggle('hidden',!searchEl.value); doSearch(); });
    clearEl.addEventListener('click', () => { searchEl.value=''; catState.search=''; clearEl.classList.add('hidden'); catState.page=1; loadCatalog(); });
    document.getElementById('cat-sort').addEventListener('change', e => { catState.sort=e.target.value; catState.page=1; loadCatalog(); });
    document.getElementById('cat-more-btn')?.addEventListener('click', () => { catState.page++; loadCatalog(true); });

    loadCatalog();
}

async function loadCatalog(append=false) {
    const el = document.getElementById('cat-products');
    if(!el)return;
    if(!append) el.innerHTML = productCardSkeleton().repeat(6);

    try {
        const params = { page:catState.page, per_page:12, sort:catState.sort };
        if(catState.search) params.search = catState.search;
        if(catState.categoryId) params.category_id = catState.categoryId;

        const result = await api.products.list(params);
        const items = result.items || result;

        const countEl = document.getElementById('cat-count');
        if(countEl && result.total!==undefined) countEl.textContent = pluralize(result.total,'товар','товара','товаров');

        if(!items?.length) {
            if(!append) el.innerHTML = `<div style="grid-column:1/-1"><div class="empty-state"><div class="empty-state__icon">🔍</div><div class="empty-state__title">Ничего не найдено</div><div class="empty-state__text">Попробуйте изменить фильтры</div></div></div>`;
            document.getElementById('cat-more')?.classList.add('hidden');
            return;
        }

        const html = items.map(p=>renderProductCard(p)).join('');
        if(append) el.insertAdjacentHTML('beforeend', html);
        else el.innerHTML = html;

        const more = document.getElementById('cat-more');
        if(more && result.pages) more.classList.toggle('hidden', catState.page >= result.pages);
    } catch(e) {
        console.error(e);
        if(!append) el.innerHTML = `<div style="grid-column:1/-1"><div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div></div>`;
    }
}


// ============================================================
// СТРАНИЦА ТОВАРА
// ============================================================

export async function renderProduct(id) {
    setActiveNav('');
    showBackButton(() => router.back());
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter" style="padding-bottom:80px">
        <div class="product-page__img"><div class="skeleton" style="height:300px"></div></div>
        <div class="product-page__content">
            <div class="skeleton skeleton-text" style="width:80%;height:24px"></div>
            <div class="skeleton skeleton-text" style="width:60%;margin-top:8px"></div>
            <div class="skeleton" style="height:120px;margin-top:16px;border-radius:var(--radius-lg)"></div>
        </div>
    </div>`;

    try {
        const product = await api.products.get(id);
        if(!product) { showToast('Товар не найден','error'); router.back(); return; }

        const discount = calcDiscount(product.base_price, product.best_price);

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:90px">
            <div class="product-page__img">
                ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : `<div class="product-card__img-placeholder" style="height:300px;font-size:4rem">🧴</div>`}
            </div>
            <div class="product-page__content">
                <div class="product-page__name">${escapeHtml(product.name)}</div>
                <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px">
                    <span class="price">${formatPrice(product.best_price || product.base_price)}</span>
                    ${discount>0?`<span class="price-old">${formatPrice(product.base_price)}</span><span class="price-discount">-${discount}%</span>`:''}
                </div>
                ${product.description ? `<div class="product-page__desc">${escapeHtml(product.description)}</div>` : ''}

                <!-- Ценовая лестница -->
                ${product.price_tiers?.length ? `
                <div class="price-ladder">
                    <div class="price-ladder__title">📊 Чем больше людей — тем дешевле</div>
                    ${product.price_tiers.map(t => {
                        const d = calcDiscount(product.base_price, t.price);
                        return `<div class="price-ladder__step">
                            <div class="price-ladder__people">👥 от ${t.min_quantity}</div>
                            <div class="price-ladder__price">${formatPrice(t.price)}</div>
                            <div class="price-ladder__discount">-${d}%</div>
                        </div>`;
                    }).join('')}
                </div>` : ''}

                <div id="product-groups"></div>
            </div>
            <div class="sticky-action">
                <div class="sticky-action__price">
                    <div style="font-size:0.75rem;color:var(--text-hint)">от</div>
                    <div class="price">${formatPrice(product.best_price || product.base_price)}</div>
                </div>
                <button class="btn btn-primary sticky-action__btn" id="product-join-btn">Участвовать в сборе</button>
            </div>
        </div>`;

        // Загрузим активные сборы для товара
        loadProductGroups(id);

        document.getElementById('product-join-btn')?.addEventListener('click', () => {
            haptic('medium');
            // Если есть активный сбор — идём к нему, иначе создаём
            const firstGroup = document.querySelector('[data-group-id]');
            if(firstGroup) {
                router.navigate(`group/${firstGroup.dataset.groupId}`);
            } else {
                showToast('Сборов пока нет. Следите за обновлениями!','info');
            }
        });

    } catch(e) {
        console.error(e);
        showToast('Ошибка загрузки товара','error');
    }
}

async function loadProductGroups(productId) {
    const container = document.getElementById('product-groups');
    if(!container) return;
    try {
        const groups = await api.groups.list({ product_id: productId, status: 'active' });
        const items = groups.items || groups;
        if(!items?.length) return;

        container.innerHTML = items.map(g => {
            const tl = getTimeLeft(g.deadline);
            const prog = g.current_count / g.min_participants * 100;
            return `
            <div class="active-group-widget" data-group-id="${g.id}">
                <div class="active-group-widget__header">
                    <span class="active-group-widget__label">🟢 Активный сбор</span>
                    <span class="countdown ${tl.urgent?'urgent':''}"><span class="countdown__icon">⏳</span> ${tl.text}</span>
                </div>
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                    <span style="font-size:0.9rem">👥 ${pluralize(g.current_count,'участник','участника','участников')}</span>
                    <span class="price">${formatPrice(g.current_price)}</span>
                </div>
                <div class="progress-bar"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
                ${g.people_to_next_price ? `<div style="font-size:0.8rem;color:var(--text-hint);margin-top:6px">Ещё ${pluralize(g.people_to_next_price,'человек','человека','человек')} до ${formatPrice(g.next_price)}</div>` : ''}
                <button class="btn btn-primary btn-block" style="margin-top:12px" onclick="location.hash='group/${g.id}'">Присоединиться</button>
            </div>`;
        }).join('');
    } catch(e) { console.error(e); }
}


// ============================================================
// СТРАНИЦА СБОРА
// ============================================================

export async function renderGroup(id) {
    setActiveNav('groups');
    showBackButton(() => router.back());
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter" style="padding-bottom:80px">
        <div class="skeleton" style="height:200px"></div>
        <div style="padding:16px"><div class="skeleton skeleton-text" style="height:20px;width:70%"></div></div>
    </div>`;

    try {
        const group = await api.groups.get(id);
        if(!group) { showToast('Сбор не найден','error'); router.back(); return; }

        const product = group.product || {};
        const tl = getTimeLeft(group.deadline);
        const disc = calcDiscount(product.base_price, group.current_price);
        const prog = group.current_count / group.min_participants * 100;
        const status = groupStatusInfo(group.status);

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:90px">
            <!-- Фото товара -->
            <div class="product-page__img">
                ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : `<div class="product-card__img-placeholder" style="height:220px;font-size:3rem">🛍</div>`}
            </div>

            <!-- Информация -->
            <div style="padding:16px var(--page-padding)">
                <div class="product-page__name">${escapeHtml(product.name)}</div>

                <!-- Статус и таймер -->
                <div style="display:flex;align-items:center;gap:8px;margin:8px 0 16px">
                    <span class="badge badge-${status.color}">${status.emoji} ${status.text}</span>
                    ${!tl.expired ? `<span class="countdown ${tl.urgent?'urgent':''}">⏳ ${tl.text}</span>` : ''}
                </div>

                <!-- Цена -->
                <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:16px">
                    <span class="price" style="font-size:1.6rem">${formatPrice(group.current_price)}</span>
                    ${disc>0?`<span class="price-old" style="font-size:1rem">${formatPrice(product.base_price)}</span><span class="price-discount">-${disc}%</span>`:''}
                </div>

                <!-- Прогресс -->
                <div style="margin-bottom:20px">
                    <div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:6px">
                        <span>👥 ${pluralize(group.current_count,'участник','участника','участников')}</span>
                        <span class="text-hint">цель: ${group.min_participants}</span>
                    </div>
                    <div class="progress-bar" style="height:10px">
                        <div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div>
                    </div>
                    ${group.people_to_next_price ? `
                    <div style="font-size:0.85rem;color:var(--accent);margin-top:8px;font-weight:600">
                        +${group.people_to_next_price} чел → цена ${formatPrice(group.next_price)}
                    </div>` : ''}
                </div>

                <!-- Ценовая лестница -->
                ${product.price_tiers?.length ? `
                <div class="price-ladder">
                    <div class="price-ladder__title">📊 Пороги цен</div>
                    ${product.price_tiers.map(t => {
                        const active = group.current_count >= t.min_quantity;
                        const d = calcDiscount(product.base_price, t.price);
                        return `<div class="price-ladder__step ${active?'active':''}">
                            <div class="price-ladder__people">${active?'✅':'👥'} от ${t.min_quantity}</div>
                            <div class="price-ladder__price">${formatPrice(t.price)}</div>
                            <div class="price-ladder__discount">-${d}%</div>
                        </div>`;
                    }).join('')}
                </div>` : ''}

                <!-- Организатор -->
                ${group.creator ? `
                <div style="display:flex;align-items:center;gap:12px;padding:12px 0;margin-top:8px;border-top:1px solid var(--bg-secondary)">
                    <div class="avatar">${(group.creator.first_name||'?')[0]}</div>
                    <div>
                        <div style="font-weight:600;font-size:0.9rem">${escapeHtml(group.creator.first_name||group.creator.username||'Организатор')}</div>
                        <div style="font-size:0.8rem;color:var(--text-hint)">Организатор сбора</div>
                    </div>
                </div>` : ''}
            </div>

            <!-- Кнопки -->
            <div class="sticky-action">
                ${group.status === 'active' ? (
                    group.is_member
                        ? `<button class="btn btn-outline btn-block" id="share-btn">📤 Пригласить друзей</button>
                           <button class="btn btn-primary" id="checkout-btn">Оформить</button>`
                        : `<div class="sticky-action__price">
                            <div style="font-size:0.75rem;color:var(--text-hint)">текущая цена</div>
                            <div class="price">${formatPrice(group.current_price)}</div>
                          </div>
                          <button class="btn btn-primary sticky-action__btn" id="join-btn">Присоединиться</button>`
                ) : `<button class="btn btn-secondary btn-block" onclick="location.hash='catalog'">Смотреть каталог</button>`}
            </div>
        </div>`;

        // Обработчики кнопок
        document.getElementById('join-btn')?.addEventListener('click', async () => {
            haptic('medium');
            try {
                await api.groups.join(id);
                showToast('Вы присоединились к сбору!','success');
                haptic('success');
                renderGroup(id); // Перерисовываем
            } catch(e) {
                showToast(e.message||'Ошибка','error');
                haptic('error');
            }
        });

        document.getElementById('share-btn')?.addEventListener('click', async () => {
            haptic('light');
            try {
                const shareData = await api.groups.share(id);
                shareUrl(shareData.url, shareData.text);
            } catch(e) {
                showToast('Ошибка шеринга','error');
            }
        });

        document.getElementById('checkout-btn')?.addEventListener('click', () => {
            haptic('medium');
            router.navigate(`checkout/${id}`);
        });

    } catch(e) {
        console.error(e);
        showToast('Ошибка загрузки','error');
    }
}


// ============================================================
// ОФОРМЛЕНИЕ ЗАКАЗА
// ============================================================

export async function renderCheckout(groupId) {
    setActiveNav('');
    showBackButton(() => router.back());

    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter" style="padding-bottom:80px">
        <div class="topbar"><div class="topbar__title">Оформление заказа</div></div>
        <div style="padding:16px">
            <div class="skeleton" style="height:80px;border-radius:var(--radius-md);margin-bottom:12px"></div>
            <div class="skeleton" style="height:80px;border-radius:var(--radius-md)"></div>
        </div>
    </div>`;

    try {
        const [group, addresses] = await Promise.all([
            api.groups.get(groupId),
            api.users.addresses().catch(()=>[])
        ]);

        const product = group.product || {};
        let selectedAddressId = null;
        const addrList = addresses.items || addresses || [];
        if(addrList.length) {
            const def = addrList.find(a=>a.is_default);
            selectedAddressId = def ? def.id : addrList[0].id;
        }

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:90px">
            <div class="topbar"><div class="topbar__title">Оформление заказа</div></div>

            <!-- Товар -->
            <div class="checkout-section">
                <div class="checkout-section__title">Товар</div>
                <div class="order-card__product">
                    <div class="order-card__img">${product.image_url?`<img src="${escapeHtml(product.image_url)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">`:''}</div>
                    <div class="order-card__info">
                        <div class="order-card__name">${escapeHtml(product.name)}</div>
                        <div class="order-card__price">${formatPrice(group.current_price)}</div>
                    </div>
                </div>
            </div>

            <!-- Адрес -->
            <div class="checkout-section">
                <div class="checkout-section__title">Адрес доставки</div>
                <div id="checkout-addresses">
                    ${addrList.length ? addrList.map(a => `
                        <div class="address-card ${a.id===selectedAddressId?'selected':''}" data-addr="${a.id}" style="margin-bottom:8px">
                            <div class="address-card__icon">📍</div>
                            <div class="address-card__text">
                                <div class="address-card__title">${escapeHtml(a.title)}</div>
                                <div class="address-card__detail">${escapeHtml(a.city)}, ${escapeHtml(a.street)}, д. ${escapeHtml(a.building)}${a.apartment?', кв. '+escapeHtml(a.apartment):''}</div>
                            </div>
                        </div>
                    `).join('') : `
                        <div class="empty-state" style="padding:16px">
                            <div class="empty-state__text">Добавьте адрес доставки</div>
                            <button class="btn btn-secondary btn-sm" onclick="location.hash='addresses'">Добавить адрес</button>
                        </div>
                    `}
                </div>
            </div>

            <!-- Тип доставки -->
            <div class="checkout-section">
                <div class="checkout-section__title">Способ доставки</div>
                <div id="delivery-options">
                    <label class="address-card selected" style="margin-bottom:8px;cursor:pointer" data-delivery="pickup">
                        <div class="address-card__icon">📦</div>
                        <div class="address-card__text">
                            <div class="address-card__title">Пункт выдачи</div>
                            <div class="address-card__detail">Бесплатно</div>
                        </div>
                    </label>
                    <label class="address-card" style="margin-bottom:8px;cursor:pointer" data-delivery="courier">
                        <div class="address-card__icon">🚚</div>
                        <div class="address-card__text">
                            <div class="address-card__title">Курьером</div>
                            <div class="address-card__detail">от 300 ₽</div>
                        </div>
                    </label>
                </div>
            </div>

            <!-- Итого -->
            <div class="order-summary">
                <div class="order-summary__row"><span>Товар</span><span>${formatPrice(group.current_price)}</span></div>
                <div class="order-summary__row"><span>Доставка</span><span id="delivery-cost">Бесплатно</span></div>
                <div class="order-summary__total"><span>Итого</span><span id="total-amount">${formatPrice(group.current_price)}</span></div>
                <div style="font-size:0.8rem;color:var(--text-hint);margin-top:4px">💡 Сумма будет заморожена до завершения сбора</div>
            </div>

            <!-- Кнопка -->
            <div class="sticky-action">
                <button class="btn btn-success btn-block btn-lg" id="pay-btn" ${!addrList.length?'disabled':''}>
                    💳 Оплатить ${formatPrice(group.current_price)}
                </button>
            </div>
        </div>`;

        // Выбор адреса
        document.getElementById('checkout-addresses')?.addEventListener('click', e => {
            const card = e.target.closest('.address-card');
            if(!card || !card.dataset.addr) return;
            haptic('light');
            document.querySelectorAll('#checkout-addresses .address-card').forEach(c=>c.classList.remove('selected'));
            card.classList.add('selected');
            selectedAddressId = parseInt(card.dataset.addr);
        });

        // Выбор доставки
        let deliveryType = 'pickup';
        document.getElementById('delivery-options')?.addEventListener('click', e => {
            const card = e.target.closest('.address-card');
            if(!card) return;
            haptic('light');
            document.querySelectorAll('#delivery-options .address-card').forEach(c=>c.classList.remove('selected'));
            card.classList.add('selected');
            deliveryType = card.dataset.delivery;
            const cost = deliveryType === 'courier' ? 300 : 0;
            document.getElementById('delivery-cost').textContent = cost ? formatPrice(cost) : 'Бесплатно';
            document.getElementById('total-amount').textContent = formatPrice(parseFloat(group.current_price) + cost);
            document.getElementById('pay-btn').textContent = `💳 Оплатить ${formatPrice(parseFloat(group.current_price) + cost)}`;
        });

        // Оплата
        document.getElementById('pay-btn')?.addEventListener('click', async () => {
            if(!selectedAddressId) { showToast('Выберите адрес доставки','error'); return; }
            haptic('medium');
            const btn = document.getElementById('pay-btn');
            btn.disabled = true;
            btn.textContent = 'Обработка...';

            try {
                const order = await api.orders.create({
                    group_id: parseInt(groupId),
                    address_id: selectedAddressId,
                    delivery_type: deliveryType
                });

                showToast('Заказ оформлен!','success');
                haptic('success');

                // Если есть ссылка на оплату — открываем
                if(order.payment_url) {
                    window.open(order.payment_url, '_blank');
                }

                router.navigate(`order/${order.id}`);
            } catch(e) {
                btn.disabled = false;
                btn.textContent = `💳 Оплатить`;
                showToast(e.message||'Ошибка оплаты','error');
                haptic('error');
            }
        });

    } catch(e) {
        console.error(e);
        showToast('Ошибка загрузки','error');
    }
}


// ============================================================
// ЗАКАЗЫ
// ============================================================

export async function renderOrders() {
    setActiveNav('orders');
    hideBackButton();
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `
        <div class="page-enter">
            <div class="topbar"><div class="topbar__title">Мои заказы</div></div>
            <div id="orders-list" style="padding-bottom:16px">
                ${Array(3).fill('<div class="order-card"><div class="skeleton" style="height:100px"></div></div>').join('')}
            </div>
        </div>`;

    try {
        const result = await api.orders.list();
        const orders = result.items || result;
        const container = document.getElementById('orders-list');
        if(!container)return;

        if(!orders?.length) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state__icon">📦</div><div class="empty-state__title">Заказов пока нет</div><div class="empty-state__text">Присоединитесь к сбору, чтобы сделать первый заказ</div><button class="btn btn-primary" onclick="location.hash='catalog'">Смотреть каталог</button></div>`;
            return;
        }

        container.innerHTML = orders.map(o => {
            const st = orderStatusInfo(o.status);
            const product = o.product || {};
            return `
            <a href="#order/${o.id}" class="order-card" style="display:block;text-decoration:none;color:var(--text)">
                <div class="order-card__header">
                    <span class="order-card__number">Заказ #${o.id}</span>
                    <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
                </div>
                <div class="order-card__product">
                    <div class="order-card__img">${product.image_url?`<img src="${escapeHtml(product.image_url)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">`:''}</div>
                    <div class="order-card__info">
                        <div class="order-card__name">${escapeHtml(product.name||'Товар')}</div>
                        <div class="order-card__price">${formatPrice(o.total_amount)}</div>
                    </div>
                </div>
                <div class="order-card__footer">
                    <span>${formatDate(o.created_at,'relative')}</span>
                    ${o.savings ? `<span class="text-success">Экономия ${formatPrice(o.savings)}</span>` : ''}
                </div>
            </a>`;
        }).join('');

    } catch(e) {
        console.error(e);
        showToast('Ошибка загрузки заказов','error');
    }
}


// ============================================================
// ДЕТАЛИ ЗАКАЗА
// ============================================================

export async function renderOrder(id) {
    setActiveNav('orders');
    showBackButton(() => router.back());
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter"><div class="topbar"><div class="topbar__title">Заказ #${id}</div></div><div style="padding:16px"><div class="skeleton" style="height:200px;border-radius:var(--radius-lg)"></div></div></div>`;

    try {
        const order = await api.orders.get(id);
        if(!order) { showToast('Заказ не найден','error'); router.back(); return; }

        const st = orderStatusInfo(order.status);
        const product = order.product || {};
        const address = order.address || {};

        // Таймлайн статусов
        const statuses = ['pending','frozen','paid','processing','shipped','delivered'];
        const currentIdx = statuses.indexOf(order.status);

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:80px">
            <div class="topbar">
                <div class="topbar__title">Заказ #${order.id}</div>
                <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
            </div>

            <!-- Товар -->
            <div class="checkout-section">
                <div class="order-card__product">
                    <div class="order-card__img" style="width:64px;height:64px">${product.image_url?`<img src="${escapeHtml(product.image_url)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">`:''}</div>
                    <div class="order-card__info">
                        <div class="order-card__name">${escapeHtml(product.name||'Товар')}</div>
                        <div class="order-card__price" style="font-size:1.1rem">${formatPrice(order.total_amount)}</div>
                        ${order.savings?`<div class="text-success" style="font-size:0.85rem">Экономия ${formatPrice(order.savings)}</div>`:''}
                    </div>
                </div>
            </div>

            <!-- Таймлайн -->
            ${order.status !== 'cancelled' && order.status !== 'refunded' ? `
            <div class="checkout-section">
                <div class="checkout-section__title">Статус</div>
                <div class="timeline">
                    ${statuses.map((s, i) => {
                        const info = orderStatusInfo(s);
                        const completed = i < currentIdx;
                        const active = i === currentIdx;
                        return `<div class="timeline__item ${completed?'completed':''} ${active?'active':''}">
                            <div class="timeline__dot">${completed?'✓':active?info.emoji:''}</div>
                            <div class="timeline__content">
                                <div class="timeline__title">${info.text}</div>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            </div>` : ''}

            <!-- Доставка -->
            <div class="checkout-section">
                <div class="checkout-section__title">Доставка</div>
                <div class="address-card" style="cursor:default">
                    <div class="address-card__icon">📍</div>
                    <div class="address-card__text">
                        <div class="address-card__title">${escapeHtml(address.title||'Адрес')}</div>
                        <div class="address-card__detail">${escapeHtml(address.city||'')}, ${escapeHtml(address.street||'')}, д. ${escapeHtml(address.building||'')}${address.apartment?', кв. '+escapeHtml(address.apartment):''}</div>
                    </div>
                </div>
                ${order.tracking_number ? `<div style="margin-top:8px;font-size:0.85rem"><strong>Трек-номер:</strong> ${escapeHtml(order.tracking_number)}</div>` : ''}
            </div>

            <!-- Суммы -->
            <div class="order-summary">
                <div class="order-summary__row"><span>Товар</span><span>${formatPrice(order.final_price)}</span></div>
                <div class="order-summary__row"><span>Доставка</span><span>${parseFloat(order.delivery_cost)>0?formatPrice(order.delivery_cost):'Бесплатно'}</span></div>
                <div class="order-summary__total"><span>Итого</span><span>${formatPrice(order.total_amount)}</span></div>
            </div>

            <!-- Действия -->
            ${['pending','frozen'].includes(order.status) ? `
            <div style="padding:16px var(--page-padding)">
                <button class="btn btn-outline btn-block" id="cancel-order-btn" style="color:var(--danger);border-color:var(--danger)">Отменить заказ</button>
            </div>` : ''}
        </div>`;

        document.getElementById('cancel-order-btn')?.addEventListener('click', async () => {
            const confirmed = await showConfirm('Отменить заказ? Деньги будут возвращены.');
            if(!confirmed) return;
            try {
                await api.orders.cancel(id);
                showToast('Заказ отменён','success');
                renderOrder(id);
            } catch(e) { showToast(e.message||'Ошибка','error'); }
        });

    } catch(e) {
        console.error(e);
        showToast('Ошибка загрузки','error');
    }
}


// ============================================================
// ПРОФИЛЬ
// ============================================================

export async function renderProfile() {
    setActiveNav('profile');
    hideBackButton();
    hideMainButton();

    const app = document.getElementById('app');
    const u = appState.user;

    if (!u) {
        app.innerHTML = `<div class="empty-state"><div class="empty-state__icon">👤</div><div class="empty-state__title">Войдите через Telegram</div><div class="empty-state__text">Откройте приложение через Telegram для авторизации</div></div>`;
        return;
    }

    const lvlE = levelEmoji(u.level);
    const lvlN = levelName(u.level);
    const initial = (u.first_name || u.username || '?')[0].toUpperCase();

    app.innerHTML = `
    <div class="page-enter">
        <div class="profile-header">
            <div class="profile-header__avatar">${initial}</div>
            <div class="profile-header__name">${escapeHtml(u.first_name||'')} ${escapeHtml(u.last_name||'')}</div>
            <div class="profile-header__level">${lvlE} ${lvlN}</div>
        </div>

        <div class="profile-stats">
            <div class="profile-stat">
                <div class="profile-stat__value">${u.total_orders||0}</div>
                <div class="profile-stat__label">Заказов</div>
            </div>
            <div class="profile-stat">
                <div class="profile-stat__value">${formatPrice(u.total_savings||0)}</div>
                <div class="profile-stat__label">Экономия</div>
            </div>
            <div class="profile-stat">
                <div class="profile-stat__value">${u.invited_count||0}</div>
                <div class="profile-stat__label">Приглашено</div>
            </div>
        </div>

        <div class="profile-menu">
            <a href="#orders" class="profile-menu__item">
                <span class="profile-menu__icon">📦</span>
                <span class="profile-menu__text">Мои заказы</span>
                <span class="profile-menu__arrow">›</span>
            </a>
            <a href="#groups" class="profile-menu__item">
                <span class="profile-menu__icon">👥</span>
                <span class="profile-menu__text">Мои сборы</span>
                <span class="profile-menu__arrow">›</span>
            </a>
            <a href="#addresses" class="profile-menu__item">
                <span class="profile-menu__icon">📍</span>
                <span class="profile-menu__text">Адреса доставки</span>
                <span class="profile-menu__arrow">›</span>
            </a>
            <button class="profile-menu__item" id="stats-btn">
                <span class="profile-menu__icon">📊</span>
                <span class="profile-menu__text">Уровень и статистика</span>
                <span class="profile-menu__arrow">›</span>
            </button>
        </div>
    </div>`;

    document.getElementById('stats-btn')?.addEventListener('click', async () => {
        haptic('light');
        try {
            const stats = await api.users.stats();
            showSheet('📊 Статистика', `
                <div style="text-align:center;margin-bottom:20px">
                    <div style="font-size:2.5rem">${stats.level_emoji||lvlE}</div>
                    <div style="font-size:1.2rem;font-weight:800;margin-top:8px">${stats.level_name||lvlN}</div>
                    <div style="margin:12px 0">
                        <div class="progress-bar" style="height:8px"><div class="progress-bar__fill" style="width:${(stats.level_progress||0)*100}%"></div></div>
                        <div style="font-size:0.8rem;color:var(--text-hint);margin-top:4px">Прогресс до следующего уровня</div>
                    </div>
                </div>
                <div class="profile-stats" style="padding:0;margin-bottom:16px">
                    <div class="profile-stat"><div class="profile-stat__value">${stats.total_orders||0}</div><div class="profile-stat__label">Заказов</div></div>
                    <div class="profile-stat"><div class="profile-stat__value">${stats.groups_participated||0}</div><div class="profile-stat__label">Сборов</div></div>
                    <div class="profile-stat"><div class="profile-stat__value">${stats.people_invited||0}</div><div class="profile-stat__label">Приглашено</div></div>
                </div>
                ${stats.next_level_requirements ? `
                <div style="font-size:0.85rem;color:var(--text-hint)">
                    <div style="font-weight:700;margin-bottom:8px">Для следующего уровня:</div>
                    ${stats.next_level_requirements.orders?`<div>📦 Заказов: ${stats.total_orders||0}/${stats.next_level_requirements.orders}</div>`:''}
                    ${stats.next_level_requirements.invites?`<div>👥 Приглашений: ${stats.people_invited||0}/${stats.next_level_requirements.invites}</div>`:''}
                    ${stats.next_level_requirements.groups?`<div>🎯 Сборов: ${stats.groups_organized||0}/${stats.next_level_requirements.groups}</div>`:''}
                </div>` : '<div style="color:var(--success);font-weight:700;text-align:center">🎉 Максимальный уровень!</div>'}
            `);
        } catch(e) { showToast('Ошибка загрузки','error'); }
    });
}


// ============================================================
// МОИ СБОРЫ
// ============================================================

export async function renderMyGroups() {
    setActiveNav('groups');
    hideBackButton();
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `
        <div class="page-enter">
            <div class="topbar"><div class="topbar__title">Мои сборы</div></div>
            <div class="tabs" id="groups-tabs">
                <button class="tab active" data-tab="active">Активные</button>
                <button class="tab" data-tab="completed">Завершённые</button>
                <button class="tab" data-tab="all">Все</button>
            </div>
            <div id="groups-list">
                ${Array(3).fill('<div class="order-card"><div class="skeleton" style="height:100px"></div></div>').join('')}
            </div>
        </div>`;

    let currentTab = 'active';

    document.getElementById('groups-tabs')?.addEventListener('click', e => {
        const tab = e.target.closest('.tab');
        if(!tab) return;
        haptic('light');
        document.querySelectorAll('#groups-tabs .tab').forEach(t=>t.classList.remove('active'));
        tab.classList.add('active');
        currentTab = tab.dataset.tab;
        loadMyGroups(currentTab);
    });

    loadMyGroups(currentTab);
}

async function loadMyGroups(filter) {
    const container = document.getElementById('groups-list');
    if(!container) return;

    try {
        const result = await api.groups.my();
        let groups = result.items || result || [];

        if(filter === 'active') groups = groups.filter(g=>g.status==='active');
        else if(filter === 'completed') groups = groups.filter(g=>['completed','failed','cancelled'].includes(g.status));

        if(!groups.length) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state__icon">👥</div><div class="empty-state__title">Нет сборов</div><div class="empty-state__text">Присоединяйтесь к сборам и приглашайте друзей</div><button class="btn btn-primary" onclick="location.hash='catalog'">Смотреть каталог</button></div>`;
            return;
        }

        container.innerHTML = groups.map(g => {
            const product = g.product || {};
            const tl = getTimeLeft(g.deadline);
            const st = groupStatusInfo(g.status);
            const prog = g.current_count / g.min_participants * 100;
            return `
            <a href="#group/${g.id}" class="order-card" style="display:block;text-decoration:none;color:var(--text)">
                <div class="order-card__header">
                    <span class="order-card__name">${escapeHtml(product.name||'Сбор')}</span>
                    <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
                </div>
                <div style="display:flex;align-items:center;justify-content:space-between;margin:8px 0">
                    <span style="font-size:0.85rem">👥 ${pluralize(g.current_count,'участник','участника','участников')}</span>
                    <span class="price" style="font-size:1rem">${formatPrice(g.current_price)}</span>
                </div>
                <div class="progress-bar" style="height:6px"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
                ${g.status==='active'&&!tl.expired?`<div style="font-size:0.8rem;color:var(--text-hint);margin-top:6px">⏳ ${tl.text}</div>`:''}
            </a>`;
        }).join('');
    } catch(e) {
        console.error(e);
        container.innerHTML = `<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div>`;
    }
}


// ============================================================
// АДРЕСА
// ============================================================

export async function renderAddresses() {
    setActiveNav('profile');
    showBackButton(() => router.back());
    hideMainButton();

    const app = document.getElementById('app');
    app.innerHTML = `
        <div class="page-enter">
            <div class="topbar">
                <div class="topbar__title">Адреса доставки</div>
            </div>
            <div id="addr-list" class="address-list" style="padding-top:8px">
                <div class="skeleton" style="height:80px;border-radius:var(--radius-md);margin-bottom:12px"></div>
            </div>
            <div style="padding:16px var(--page-padding)">
                <button class="btn btn-primary btn-block" id="add-addr-btn">+ Добавить адрес</button>
            </div>
        </div>`;

    document.getElementById('add-addr-btn')?.addEventListener('click', () => {
        haptic('light');
        showAddressForm();
    });

    loadAddresses();
}

async function loadAddresses() {
    const container = document.getElementById('addr-list');
    if(!container) return;

    try {
        const result = await api.users.addresses();
        const addresses = result.items || result || [];

        if(!addresses.length) {
            container.innerHTML = `<div class="empty-state" style="padding:24px"><div class="empty-state__icon">📍</div><div class="empty-state__title">Нет адресов</div><div class="empty-state__text">Добавьте адрес для доставки заказов</div></div>`;
            return;
        }

        container.innerHTML = addresses.map(a => `
            <div class="address-item">
                <div class="address-item__icon">📍</div>
                <div class="address-item__content">
                    <div class="address-item__title">${escapeHtml(a.title)}</div>
                    <div class="address-item__text">${escapeHtml(a.city)}, ${escapeHtml(a.street)}, д. ${escapeHtml(a.building)}${a.apartment?', кв. '+escapeHtml(a.apartment):''}</div>
                    ${a.is_default?'<div class="address-item__default">По умолчанию</div>':''}
                </div>
                <div class="address-item__actions">
                    <button class="address-item__action" data-edit="${a.id}">✏️</button>
                    <button class="address-item__action" data-delete="${a.id}">🗑</button>
                </div>
            </div>
        `).join('');

        // Обработчики
        container.querySelectorAll('[data-delete]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const confirmed = await showConfirm('Удалить адрес?');
                if(!confirmed) return;
                try {
                    await api.users.deleteAddress(btn.dataset.delete);
                    showToast('Адрес удалён','success');
                    loadAddresses();
                } catch(e) { showToast('Ошибка','error'); }
            });
        });

    } catch(e) {
        console.error(e);
        showToast('Ошибка загрузки','error');
    }
}

function showAddressForm(existing = null) {
    const isEdit = !!existing;
    const a = existing || {};

    const sheet = showSheet(isEdit?'Изменить адрес':'Новый адрес', `
        <div class="input-group">
            <label>Название</label>
            <input class="input" id="addr-title" placeholder="Дом, Работа, Дача..." value="${escapeHtml(a.title||'')}">
        </div>
        <div class="input-group">
            <label>Город</label>
            <input class="input" id="addr-city" placeholder="Москва" value="${escapeHtml(a.city||'')}">
        </div>
        <div class="input-group">
            <label>Улица</label>
            <input class="input" id="addr-street" placeholder="ул. Пушкина" value="${escapeHtml(a.street||'')}">
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div class="input-group">
                <label>Дом</label>
                <input class="input" id="addr-building" placeholder="12А" value="${escapeHtml(a.building||'')}">
            </div>
            <div class="input-group">
                <label>Квартира</label>
                <input class="input" id="addr-apt" placeholder="42" value="${escapeHtml(a.apartment||'')}">
            </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div class="input-group">
                <label>Подъезд</label>
                <input class="input" id="addr-entrance" placeholder="2" value="${escapeHtml(a.entrance||'')}">
            </div>
            <div class="input-group">
                <label>Этаж</label>
                <input class="input" id="addr-floor" placeholder="5" value="${escapeHtml(a.floor||'')}">
            </div>
        </div>
        <div class="input-group">
            <label>Комментарий</label>
            <input class="input" id="addr-comment" placeholder="Код домофона, ориентиры..." value="${escapeHtml(a.comment||'')}">
        </div>
        <div class="toggle">
            <span>Сделать адресом по умолчанию</span>
            <button class="toggle__switch ${a.is_default?'active':''}" id="addr-default"></button>
        </div>
        <button class="btn btn-primary btn-block" id="addr-save" style="margin-top:12px">${isEdit?'Сохранить':'Добавить'}</button>
    `);

    // Переключатель
    const toggle = sheet.element.querySelector('#addr-default');
    let isDefault = a.is_default || false;
    toggle?.addEventListener('click', () => {
        isDefault = !isDefault;
        toggle.classList.toggle('active', isDefault);
    });

    // Сохранение
    sheet.element.querySelector('#addr-save')?.addEventListener('click', async () => {
        const data = {
            title: sheet.element.querySelector('#addr-title').value.trim(),
            city: sheet.element.querySelector('#addr-city').value.trim(),
            street: sheet.element.querySelector('#addr-street').value.trim(),
            building: sheet.element.querySelector('#addr-building').value.trim(),
            apartment: sheet.element.querySelector('#addr-apt').value.trim() || null,
            entrance: sheet.element.querySelector('#addr-entrance').value.trim() || null,
            floor: sheet.element.querySelector('#addr-floor').value.trim() || null,
            comment: sheet.element.querySelector('#addr-comment').value.trim() || null,
            is_default: isDefault
        };

        if(!data.title || !data.city || !data.street || !data.building) {
            showToast('Заполните обязательные поля','error');
            return;
        }

        try {
            if(isEdit) await api.users.updateAddress(existing.id, data);
            else await api.users.addAddress(data);
            showToast(isEdit?'Адрес обновлён':'Адрес добавлен','success');
            haptic('success');
            sheet.close();
            loadAddresses();
        } catch(e) { showToast(e.message||'Ошибка','error'); }
    });
}
