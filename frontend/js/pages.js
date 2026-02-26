/**
 * ============================================================
 * Модуль: pages.js (v2 — ИСПРАВЛЕН)
 * ============================================================
 * 
 * ИСПРАВЛЕНИЯ:
 *   1. Горячие сборы: product_name/product_image (не product.name)
 *   2. Детали сбора: GroupDetailResponse с плоскими полями
 *   3. Мои сборы: MyGroupsResponse {active, completed, organized}
 *   4. Заказы: OrderListItem с плоскими полями
 *   5. Детали заказа: OrderDetailResponse с address_text
 *   6. Профиль: берёт юзера из appState (не из API повторно)
 */

import { api, getCachedUser } from './api.js?v=5';
import { haptic, showBackButton, hideBackButton, hideMainButton, shareUrl, showConfirm } from './telegram.js?v=5';
import {
    router, formatPrice, calcDiscount, formatDate, getTimeLeft,
    pluralize, showToast, showSheet, escapeHtml, debounce,
    setActiveNav, levelEmoji, levelName, orderStatusInfo, groupStatusInfo,
    productCardSkeleton, hotGroupCardSkeleton
} from './app.js?v=5';

let appState = { user: null, categories: [] };
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

/**
 * Карточка сбора из GroupListItem (плоские поля от бэкенда).
 * 
 * Бэкенд возвращает:
 *   { id, status, current_count, min_participants, product_name, product_image, current_price, base_price, ... }
 * НЕ вложенный product: { name, image_url }
 */
function renderGroupListCard(g) {
    const tl = getTimeLeft(g.deadline);
    const disc = calcDiscount(g.base_price, g.current_price);
    const prog = g.max_participants > 0 ? (g.current_count / g.max_participants * 100) : 0;

    return `
        <a href="#group/${g.id}" class="hot-group-card">
            <div class="hot-group-card__img">
                ${g.product_image
                    ? `<img src="${escapeHtml(g.product_image)}" alt="" loading="lazy">`
                    : '<div class="product-card__img-placeholder">🛍</div>'}
                <div class="hot-group-card__timer">⏳ ${tl.text}</div>
            </div>
            <div class="hot-group-card__body">
                <div class="hot-group-card__name">${escapeHtml(g.product_name)}</div>
                <div class="hot-group-card__stats">
                    <div class="hot-group-card__people">👥 ${pluralize(g.current_count,'участник','участника','участников')}</div>
                    <div class="hot-group-card__price">${formatPrice(g.current_price)} ${disc>0?`<span class="price-discount">-${disc}%</span>`:''}</div>
                </div>
                <div class="progress-bar"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
            </div>
        </a>`;
}


// ============================================================
// ГЛАВНАЯ
// ============================================================

export async function renderHome() {
    setActiveNav('home');
    hideBackButton(); hideMainButton();

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
                <div class="products-scroll" id="hot-list">${hotGroupCardSkeleton().repeat(3)}</div>
            </div>
            <div class="section">
                <div class="section__header"><div class="section__title">Категории</div></div>
                <div class="categories-scroll" id="home-cats"></div>
            </div>
            <div class="section">
                <div class="section__header">
                    <div class="section__title">⭐ Популярное</div>
                    <a href="#catalog" class="section__more">Все →</a>
                </div>
                <div class="products-scroll" id="popular-list">${productCardSkeleton().repeat(4)}</div>
            </div>
        </div>`;

    // Категории — уже в памяти, рисуем сразу
    const cc = document.getElementById('home-cats');
    if (cc && appState.categories?.length) {
        cc.innerHTML = appState.categories.map(c =>
            `<button class="category-chip" onclick="location.hash='catalog?cat=${c.id}'">${c.icon||'📦'} ${escapeHtml(c.name)}</button>`
        ).join('');
    }

    // Данные — параллельно
    Promise.allSettled([loadHotGroups(), loadPopular()]);
}

async function loadHotGroups() {
    try {
        const groups = await api.groups.hot(5);
        const el = document.getElementById('hot-list');
        if (!el) return;
        if (!groups?.length) { el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-hint);width:100%">Пока нет активных сборов</div>'; return; }
        el.innerHTML = groups.map(g => renderGroupListCard(g)).join('');
    } catch(e) { console.error('Hot groups:', e); }
}

async function loadPopular() {
    try {
        const products = await api.products.popular(8);
        const el = document.getElementById('popular-list');
        if (!el) return;
        if (!products?.length) { el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-hint);width:100%">Скоро появятся</div>'; return; }
        el.innerHTML = products.map(p => renderProductCard(p)).join('');
    } catch(e) { console.error('Popular:', e); }
}


// ============================================================
// КАТАЛОГ
// ============================================================

let catS = { search:'', catId:null, page:1, sort:'popular' };

export async function renderCatalog() {
    setActiveNav('catalog'); hideBackButton(); hideMainButton();
    const hp = new URLSearchParams(location.hash.split('?')[1]||'');
    if (hp.get('cat')) catS.catId = parseInt(hp.get('cat'));

    const app = document.getElementById('app');
    app.innerHTML = `
        <div class="page-enter">
            <div class="search-bar">
                <span class="search-bar__icon">🔍</span>
                <input type="text" class="search-bar__input" id="c-search" placeholder="Найти товар..." value="${escapeHtml(catS.search)}">
                <button class="search-bar__clear ${catS.search?'':'hidden'}" id="c-clear">✕</button>
            </div>
            <div class="categories-scroll" id="c-cats"></div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:0 var(--page-padding);margin-bottom:12px">
                <div id="c-count" class="text-hint" style="font-size:0.85rem"></div>
                <select id="c-sort" style="background:var(--bg-secondary);border:none;padding:6px 12px;border-radius:var(--radius-full);font-size:0.85rem;font-weight:600;color:var(--text)">
                    <option value="popular">Популярные</option><option value="price_asc">Дешевле</option><option value="price_desc">Дороже</option><option value="new">Новые</option>
                </select>
            </div>
            <div class="product-grid" id="c-grid">${productCardSkeleton().repeat(6)}</div>
            <div id="c-more" class="hidden" style="padding:16px;text-align:center"><button class="btn btn-secondary btn-block" id="c-more-btn">Загрузить ещё</button></div>
        </div>`;

    const cc = document.getElementById('c-cats');
    if (cc) {
        cc.innerHTML = `<button class="category-chip ${!catS.catId?'active':''}" data-cat="">Все</button>` +
            (appState.categories||[]).map(c=>`<button class="category-chip ${catS.catId===c.id?'active':''}" data-cat="${c.id}">${c.icon||''} ${escapeHtml(c.name)}</button>`).join('');
        cc.addEventListener('click', e => {
            const ch = e.target.closest('.category-chip'); if(!ch)return;
            haptic('light'); catS.catId = ch.dataset.cat ? parseInt(ch.dataset.cat) : null; catS.page=1;
            cc.querySelectorAll('.category-chip').forEach(c=>c.classList.remove('active')); ch.classList.add('active');
            loadCat();
        });
    }

    document.getElementById('c-sort').value = catS.sort;
    const si = document.getElementById('c-search'), cl = document.getElementById('c-clear');
    const ds = debounce(() => { catS.search=si.value; catS.page=1; loadCat(); }, 400);
    si.addEventListener('input', () => { cl.classList.toggle('hidden',!si.value); ds(); });
    cl.addEventListener('click', () => { si.value=''; catS.search=''; cl.classList.add('hidden'); catS.page=1; loadCat(); });
    document.getElementById('c-sort').addEventListener('change', e => { catS.sort=e.target.value; catS.page=1; loadCat(); });
    document.getElementById('c-more-btn')?.addEventListener('click', () => { catS.page++; loadCat(true); });
    loadCat();
}

async function loadCat(append=false) {
    const el = document.getElementById('c-grid'); if(!el) return;
    if(!append) el.innerHTML = productCardSkeleton().repeat(6);
    try {
        const p = { page:catS.page, per_page:12, sort:catS.sort };
        if(catS.search) p.search = catS.search;
        if(catS.catId) p.category_id = catS.catId;
        const r = await api.products.list(p);
        const items = r.items || r;
        const cnt = document.getElementById('c-count');
        if(cnt && r.total!=null) cnt.textContent = pluralize(r.total,'товар','товара','товаров');
        if(!items?.length) {
            if(!append) el.innerHTML = '<div style="grid-column:1/-1"><div class="empty-state"><div class="empty-state__icon">🔍</div><div class="empty-state__title">Ничего не найдено</div></div></div>';
            document.getElementById('c-more')?.classList.add('hidden'); return;
        }
        const html = items.map(p=>renderProductCard(p)).join('');
        if(append) el.insertAdjacentHTML('beforeend', html); else el.innerHTML = html;
        const m = document.getElementById('c-more');
        if(m && r.pages) m.classList.toggle('hidden', catS.page >= r.pages);
    } catch(e) { console.error(e); if(!append) el.innerHTML = '<div style="grid-column:1/-1"><div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div></div>'; }
}


// ============================================================
// СТРАНИЦА ТОВАРА
// ============================================================

export async function renderProduct(id) {
    setActiveNav(''); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter" style="padding-bottom:80px"><div class="skeleton" style="height:300px"></div><div style="padding:16px"><div class="skeleton skeleton-text" style="height:24px;width:80%"></div></div></div>';

    try {
        const p = await api.products.get(id);
        if(!p) { showToast('Товар не найден','error'); router.back(); return; }
        const disc = calcDiscount(p.base_price, p.best_price);
        const productId = p.id;

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:140px">
            <div class="product-page__img">${p.image_url?`<img src="${escapeHtml(p.image_url)}">`: '<div class="product-card__img-placeholder" style="height:300px;font-size:4rem">🧴</div>'}</div>
            <div class="product-page__content">
                <div class="product-page__name">${escapeHtml(p.name)}</div>
                <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px">
                    <span class="price">${formatPrice(p.best_price||p.base_price)}</span>
                    ${disc>0?`<span class="price-old">${formatPrice(p.base_price)}</span><span class="price-discount">-${disc}%</span>`:''}
                </div>
                ${p.description?`<div class="product-page__desc">${escapeHtml(p.description)}</div>`:''}
                ${p.price_tiers?.length?`
                <div class="price-ladder">
                    <div class="price-ladder__title">📊 Чем больше людей — тем дешевле</div>
                    ${p.price_tiers.map(t=>`<div class="price-ladder__step">
                        <div class="price-ladder__people">👥 от ${t.min_quantity}</div>
                        <div class="price-ladder__price">${formatPrice(t.price)}</div>
                        <div class="price-ladder__discount">-${calcDiscount(p.base_price,t.price)}%</div>
                    </div>`).join('')}
                </div>`:''}
                <div id="prod-groups"></div>
            </div>

            <!-- Две кнопки ВСЕГДА видны: Создать сбор + Участвовать -->
            <div class="sticky-action-double">
                <button class="btn btn-primary btn-block btn-lg" id="create-group-btn">🚀 Создать свой сбор</button>
                <div id="join-existing-area"></div>
            </div>
        </div>`;

        // Кнопка "Создать свой сбор"
        document.getElementById('create-group-btn')?.addEventListener('click', async () => {
            haptic('medium');
            const btn = document.getElementById('create-group-btn');
            btn.disabled = true; btn.textContent = 'Создаём...';
            try {
                const result = await api.groups.create({ product_id: productId });
                if (result.group_id) {
                    showToast('Сбор создан! Приглашайте друзей!', 'success');
                    haptic('success');
                    location.hash = `group/${result.group_id}`;
                } else {
                    showToast(result.message || 'Ошибка', 'error');
                    btn.disabled = false; btn.textContent = '🚀 Создать свой сбор';
                }
            } catch(e) {
                showToast(e.message || 'Не удалось создать сбор', 'error');
                haptic('error');
                btn.disabled = false; btn.textContent = '🚀 Создать свой сбор';
            }
        });

        // Загружаем активные сборы
        try {
            const gl = await api.groups.list({ product_id: id, status: 'active' });
            const groups = gl.items || gl;
            const c = document.getElementById('prod-groups');
            const joinArea = document.getElementById('join-existing-area');

            if (groups?.length) {
                // Показываем активные сборы в теле страницы
                if (c) {
                    c.innerHTML = `<div style="margin-top:16px"><div style="font-weight:700;margin-bottom:10px">👥 Активные сборы</div>` +
                    groups.map(g => {
                        const tl=getTimeLeft(g.deadline), prog=g.max_participants>0?g.current_count/g.max_participants*100:0;
                        return `<div class="active-group-widget" data-gid="${g.id}">
                            <div class="active-group-widget__header"><span class="active-group-widget__label">🟢 Активный</span><span class="countdown ${tl.urgent?'urgent':''}">⏳ ${tl.text}</span></div>
                            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><span>👥 ${pluralize(g.current_count,'участник','участника','участников')}</span><span class="price">${formatPrice(g.current_price)}</span></div>
                            <div class="progress-bar"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
                            <button class="btn btn-outline btn-block" style="margin-top:10px" onclick="location.hash='group/${g.id}'">Присоединиться</button>
                        </div>`;
                    }).join('') + '</div>';
                }
                // Подсказка под кнопкой
                if (joinArea) {
                    joinArea.innerHTML = `<div style="text-align:center;font-size:0.8rem;color:var(--text-hint);margin-top:6px">или выберите один из ${pluralize(groups.length,'активного сбора','активных сборов','активных сборов')} выше</div>`;
                }
            }
        } catch(e) { console.error('Groups for product:', e); }

    } catch(e) { console.error(e); showToast('Ошибка загрузки','error'); }
}


// ============================================================
// СТРАНИЦА СБОРА (GroupDetailResponse — плоские поля!)
// ============================================================

export async function renderGroup(id) {
    setActiveNav('groups'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter" style="padding-bottom:80px"><div class="skeleton" style="height:220px"></div><div style="padding:16px"><div class="skeleton skeleton-text" style="height:20px;width:70%"></div></div></div>';

    try {
        /**
         * GroupDetailResponse от бэкенда (ПЛОСКИЕ поля, не вложенные!):
         *   product_name, product_image, product_description, base_price
         *   creator_name, creator_username
         *   current_price, best_price, savings_amount, savings_percent
         *   people_to_next_tier, next_tier_price, next_tier_quantity
         *   price_tiers: [{min_quantity, price}]
         *   is_member, can_join, share_text, share_url
         */
        const g = await api.groups.get(id);
        if(!g) { showToast('Сбор не найден','error'); router.back(); return; }

        const tl = getTimeLeft(g.deadline);
        const disc = Math.round(g.savings_percent || 0);
        const prog = g.progress_percent || 0;
        const st = groupStatusInfo(g.status);

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:90px">
            <div class="product-page__img" style="height:220px">
                ${g.product_image?`<img src="${escapeHtml(g.product_image)}">`:'<div class="product-card__img-placeholder" style="height:220px;font-size:3rem">🛍</div>'}
            </div>
            <div style="padding:16px var(--page-padding)">
                <div class="product-page__name">${escapeHtml(g.product_name)}</div>
                <div style="display:flex;align-items:center;gap:8px;margin:8px 0 16px">
                    <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
                    ${!tl.expired?`<span class="countdown ${tl.urgent?'urgent':''}">⏳ ${tl.text}</span>`:''}
                </div>
                <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:16px">
                    <span class="price" style="font-size:1.6rem">${formatPrice(g.current_price)}</span>
                    ${disc>0?`<span class="price-old" style="font-size:1rem">${formatPrice(g.base_price)}</span><span class="price-discount">-${disc}%</span>`:''}
                </div>
                <div style="margin-bottom:20px">
                    <div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:6px">
                        <span>👥 ${pluralize(g.current_count,'участник','участника','участников')}</span>
                        <span class="text-hint">цель: ${g.min_participants}</span>
                    </div>
                    <div class="progress-bar" style="height:10px"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
                    ${g.people_to_next_tier?`<div style="font-size:0.85rem;color:var(--accent);margin-top:8px;font-weight:600">+${g.people_to_next_tier} чел → цена ${formatPrice(g.next_tier_price)}</div>`:''}
                </div>
                ${g.price_tiers?.length?`
                <div class="price-ladder">
                    <div class="price-ladder__title">📊 Пороги цен</div>
                    ${g.price_tiers.map(t=>{
                        const active = g.current_count >= t.min_quantity;
                        const d = calcDiscount(g.base_price, t.price);
                        return `<div class="price-ladder__step ${active?'active':''}">
                            <div class="price-ladder__people">${active?'✅':'👥'} от ${t.min_quantity}</div>
                            <div class="price-ladder__price">${formatPrice(t.price)}</div>
                            <div class="price-ladder__discount">-${d}%</div>
                        </div>`;
                    }).join('')}
                </div>`:''}
                ${g.creator_name?`
                <div style="display:flex;align-items:center;gap:12px;padding:12px 0;margin-top:8px;border-top:1px solid var(--bg-secondary)">
                    <div class="avatar">${(g.creator_name||'?')[0]}</div>
                    <div><div style="font-weight:600;font-size:0.9rem">${escapeHtml(g.creator_name)}</div><div style="font-size:0.8rem;color:var(--text-hint)">Организатор</div></div>
                </div>`:''}
            </div>
            <div class="sticky-action">
                ${g.status==='active' ? (
                    g.is_member
                        ? `<button class="btn btn-outline btn-block" id="share-btn">📤 Пригласить друзей</button>
                           <button class="btn btn-primary" id="checkout-btn">Оформить</button>`
                        : (g.can_join
                            ? `<div class="sticky-action__price"><div style="font-size:0.75rem;color:var(--text-hint)">текущая цена</div><div class="price">${formatPrice(g.current_price)}</div></div>
                               <button class="btn btn-primary sticky-action__btn" id="join-btn">Присоединиться</button>`
                            : `<button class="btn btn-secondary btn-block" disabled>Вы уже в сборе</button>`)
                ) : '<button class="btn btn-secondary btn-block" onclick="location.hash=\'catalog\'">Смотреть каталог</button>'}
            </div>
        </div>`;

        document.getElementById('join-btn')?.addEventListener('click', async () => {
            haptic('medium');
            try { await api.groups.join(id); showToast('Вы присоединились!','success'); haptic('success'); renderGroup(id); }
            catch(e) { showToast(e.message||'Ошибка','error'); haptic('error'); }
        });

        document.getElementById('share-btn')?.addEventListener('click', async () => {
            haptic('light');
            if (g.share_url) { shareUrl(g.share_url, g.share_text || ''); }
            else { try { const s = await api.groups.share(id); shareUrl(s.url, s.text); } catch(e) { showToast('Ошибка','error'); } }
        });

        document.getElementById('checkout-btn')?.addEventListener('click', () => { haptic('medium'); router.navigate(`checkout/${id}`); });

    } catch(e) { console.error(e); showToast('Ошибка загрузки','error'); }
}


// ============================================================
// ОФОРМЛЕНИЕ ЗАКАЗА
// ============================================================

export async function renderCheckout(groupId) {
    setActiveNav(''); showBackButton(() => router.back());
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter" style="padding-bottom:80px"><div class="topbar"><div class="topbar__title">Оформление</div></div><div style="padding:16px"><div class="skeleton" style="height:160px;border-radius:var(--radius-md)"></div></div></div>';

    try {
        const [g, addrResult] = await Promise.all([
            api.groups.get(groupId),
            api.users.addresses().catch(()=>({items:[]}))
        ]);
        const addrs = addrResult.items || addrResult || [];
        let selAddr = addrs.find(a=>a.is_default)?.id || addrs[0]?.id || null;
        let delType = 'pickup';
        let deliveryCost = 0;
        let deliveryDays = '';
        let selectedCity = addrs.find(a=>a.id===selAddr)?.city || '';
        let pickupPoints = [];
        let selectedPvz = null;

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:90px">
            <div class="topbar"><div class="topbar__title">Оформление заказа</div></div>
            <div class="checkout-section">
                <div class="checkout-section__title">Товар</div>
                <div class="order-card__product">
                    <div class="order-card__img">${g.product_image?`<img src="${escapeHtml(g.product_image)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">`:''}</div>
                    <div class="order-card__info"><div class="order-card__name">${escapeHtml(g.product_name)}</div><div class="order-card__price">${formatPrice(g.current_price)}</div></div>
                </div>
            </div>
            <div class="checkout-section">
                <div class="checkout-section__title">Город доставки</div>
                <div style="position:relative">
                    <input type="text" class="form-input" id="ck-city" placeholder="Введите город..." value="${escapeHtml(selectedCity)}" autocomplete="off">
                    <div id="ck-city-list" class="autocomplete-dropdown" style="display:none"></div>
                </div>
            </div>
            <div class="checkout-section">
                <div class="checkout-section__title">Способ доставки</div>
                <div id="ck-del">
                    <div class="address-card selected" data-del="pickup" style="margin-bottom:8px;cursor:pointer"><div class="address-card__icon">📦</div><div class="address-card__text"><div class="address-card__title">Пункт выдачи (ПВЗ)</div><div class="address-card__detail" id="ck-pvz-info">Выберите город для расчёта</div></div></div>
                    <div class="address-card" data-del="courier" style="cursor:pointer"><div class="address-card__icon">🚚</div><div class="address-card__text"><div class="address-card__title">Курьером до двери</div><div class="address-card__detail" id="ck-courier-info">Выберите город для расчёта</div></div></div>
                </div>
            </div>
            <div id="ck-pvz-section" style="display:none">
                <div class="checkout-section">
                    <div class="checkout-section__title">Пункт выдачи</div>
                    <div id="ck-pvz-list" style="max-height:200px;overflow-y:auto"></div>
                </div>
            </div>
            <div class="checkout-section" id="ck-addr-section" style="display:none">
                <div class="checkout-section__title">Адрес доставки</div>
                <div id="ck-addrs">${addrs.length ? addrs.map(a=>`
                    <div class="address-card ${a.id===selAddr?'selected':''}" data-addr="${a.id}" style="margin-bottom:8px">
                        <div class="address-card__icon">📍</div>
                        <div class="address-card__text"><div class="address-card__title">${escapeHtml(a.title)}</div><div class="address-card__detail">${escapeHtml(a.city)}, ${escapeHtml(a.street)}, д. ${escapeHtml(a.building)}${a.apartment?', кв. '+escapeHtml(a.apartment):''}</div></div>
                    </div>`).join('') : '<div class="empty-state" style="padding:16px"><div class="empty-state__text">Добавьте адрес</div><button class="btn btn-secondary btn-sm" onclick="location.hash=\'addresses\'">Добавить</button></div>'}</div>
            </div>
            <div class="order-summary">
                <div class="order-summary__row"><span>Товар</span><span>${formatPrice(g.current_price)}</span></div>
                <div class="order-summary__row"><span>Доставка</span><span id="ck-dcost">Рассчитывается...</span></div>
                ${deliveryDays?`<div class="order-summary__row"><span>Срок</span><span id="ck-days">${deliveryDays}</span></div>`:''}
                <div class="order-summary__total"><span>Итого</span><span id="ck-total">${formatPrice(g.current_price)}</span></div>
                <div style="font-size:0.8rem;color:var(--text-hint);margin-top:4px">💡 Сумма будет заморожена до завершения сбора</div>
            </div>
            <div class="sticky-action"><button class="btn btn-success btn-block btn-lg" id="pay-btn" disabled>💳 Оплатить</button></div>
        </div>`;

        // Функция обновления итого
        function updateTotal() {
            const dc = document.getElementById('ck-dcost');
            const tot = document.getElementById('ck-total');
            const btn = document.getElementById('pay-btn');
            if(dc) dc.textContent = deliveryCost > 0 ? formatPrice(deliveryCost) : 'Бесплатно';
            const total = parseFloat(g.current_price) + deliveryCost;
            if(tot) tot.textContent = formatPrice(total);
            if(btn) {
                const canPay = selectedCity && (delType==='pickup' ? selectedPvz : selAddr);
                btn.disabled = !canPay;
                btn.textContent = canPay ? `💳 Оплатить ${formatPrice(total)}` : '💳 Оплатить';
            }
        }

        // Расчёт доставки по городу
        async function calcDelivery(city) {
            if(!city || city.length < 2) return;
            try {
                const res = await api.delivery.calculate(city);
                if(res.success && res.tariff) {
                    deliveryCost = res.tariff.price || 0;
                    deliveryDays = res.tariff.min_days && res.tariff.max_days
                        ? `${res.tariff.min_days}-${res.tariff.max_days} дн.` : '';
                    const info = `${formatPrice(deliveryCost)}${deliveryDays ? ', ' + deliveryDays : ''}`;
                    const pvzInfo = document.getElementById('ck-pvz-info');
                    if(pvzInfo) pvzInfo.textContent = info;
                }
                // Тарифы курьера
                const tariffs = await api.delivery.tariffs(city).catch(()=>null);
                if(tariffs?.success && tariffs.tariffs?.length > 1) {
                    const courier = tariffs.tariffs.find(t => t.name?.toLowerCase().includes('дверь'));
                    if(courier) {
                        const ci = document.getElementById('ck-courier-info');
                        if(ci) ci.textContent = `${formatPrice(courier.price)}${courier.min_days ? ', ' + courier.min_days + '-' + courier.max_days + ' дн.' : ''}`;
                    }
                }
            } catch(e) { console.warn('Расчёт доставки:', e); }
            updateTotal();
        }

        // Загрузка ПВЗ
        async function loadPvzPoints(city) {
            const list = document.getElementById('ck-pvz-list');
            if(!list) return;
            list.innerHTML = '<div style="text-align:center;padding:12px;color:var(--text-hint)">Загрузка ПВЗ...</div>';
            try {
                const res = await api.delivery.pickupPoints(city);
                pickupPoints = res.success ? (res.points || []) : [];
                if(!pickupPoints.length) {
                    list.innerHTML = '<div style="text-align:center;padding:12px;color:var(--text-hint)">ПВЗ не найдены</div>';
                    return;
                }
                list.innerHTML = pickupPoints.slice(0, 20).map((p, i) => `
                    <div class="address-card ${i===0?'selected':''}" data-pvz="${escapeHtml(p.code)}" style="margin-bottom:6px;cursor:pointer">
                        <div class="address-card__icon">📦</div>
                        <div class="address-card__text">
                            <div class="address-card__title">${escapeHtml(p.name || 'ПВЗ ' + p.code)}</div>
                            <div class="address-card__detail">${escapeHtml(p.address || '')}${p.work_time ? ' · ' + escapeHtml(p.work_time) : ''}</div>
                        </div>
                    </div>`).join('');
                selectedPvz = pickupPoints[0]?.code || null;
                updateTotal();
            } catch(e) { list.innerHTML = '<div style="padding:12px;color:var(--text-hint)">Ошибка загрузки ПВЗ</div>'; }
        }

        // Автокомплит города
        const cityInput = document.getElementById('ck-city');
        const cityList = document.getElementById('ck-city-list');
        let cityTimer = null;
        cityInput?.addEventListener('input', () => {
            clearTimeout(cityTimer);
            cityTimer = setTimeout(async () => {
                const q = cityInput.value.trim();
                if(q.length < 2) { cityList.style.display='none'; return; }
                try {
                    const res = await api.delivery.cities(q);
                    if(res.success && res.cities?.length) {
                        cityList.innerHTML = res.cities.map(c =>
                            `<div class="autocomplete-item" data-city="${escapeHtml(c.city)}">${escapeHtml(c.city)}${c.region ? ', ' + escapeHtml(c.region) : ''}</div>`
                        ).join('');
                        cityList.style.display = 'block';
                    } else { cityList.style.display = 'none'; }
                } catch(e) { cityList.style.display = 'none'; }
            }, 300);
        });
        cityList?.addEventListener('click', (e) => {
            const item = e.target.closest('.autocomplete-item');
            if(!item) return;
            selectedCity = item.dataset.city;
            cityInput.value = selectedCity;
            cityList.style.display = 'none';
            haptic('light');
            calcDelivery(selectedCity);
            if(delType === 'pickup') {
                document.getElementById('ck-pvz-section').style.display = '';
                loadPvzPoints(selectedCity);
            }
        });

        // Выбор типа доставки
        document.getElementById('ck-del')?.addEventListener('click', e => {
            const c = e.target.closest('[data-del]'); if(!c) return; haptic('light');
            document.querySelectorAll('#ck-del .address-card').forEach(c=>c.classList.remove('selected'));
            c.classList.add('selected'); delType = c.dataset.del;
            
            const pvzSect = document.getElementById('ck-pvz-section');
            const addrSect = document.getElementById('ck-addr-section');
            if(delType === 'pickup') {
                if(pvzSect) pvzSect.style.display = '';
                if(addrSect) addrSect.style.display = 'none';
                if(selectedCity) loadPvzPoints(selectedCity);
            } else {
                if(pvzSect) pvzSect.style.display = 'none';
                if(addrSect) addrSect.style.display = '';
            }
            updateTotal();
        });

        // Выбор ПВЗ
        document.getElementById('ck-pvz-list')?.addEventListener('click', e => {
            const c = e.target.closest('[data-pvz]'); if(!c) return; haptic('light');
            document.querySelectorAll('#ck-pvz-list .address-card').forEach(c=>c.classList.remove('selected'));
            c.classList.add('selected'); selectedPvz = c.dataset.pvz;
            updateTotal();
        });

        // Выбор адреса (для курьера)
        document.getElementById('ck-addrs')?.addEventListener('click', e => {
            const c = e.target.closest('[data-addr]'); if(!c) return; haptic('light');
            document.querySelectorAll('#ck-addrs .address-card').forEach(c=>c.classList.remove('selected'));
            c.classList.add('selected'); selAddr = parseInt(c.dataset.addr);
            updateTotal();
        });

        // Оплата
        document.getElementById('pay-btn')?.addEventListener('click', async () => {
            haptic('medium');
            const btn = document.getElementById('pay-btn'); btn.disabled=true; btn.textContent='Обработка...';
            try {
                const orderData = {
                    group_id: parseInt(groupId),
                    delivery_type: delType,
                    delivery_city: selectedCity,
                    delivery_cost: deliveryCost
                };
                if(delType === 'pickup') {
                    orderData.pvz_code = selectedPvz;
                } else {
                    orderData.address_id = selAddr;
                }
                const order = await api.orders.create(orderData);
                showToast('Заказ оформлен!','success'); haptic('success');
                if(order.payment_url) window.open(order.payment_url,'_blank');
                router.navigate(`order/${order.order_id || order.id}`);
            } catch(e) { btn.disabled=false; btn.textContent='💳 Оплатить'; showToast(e.message||'Ошибка','error'); haptic('error'); }
        });

        // Инициализация: если город уже есть — рассчитать
        if(selectedCity) {
            calcDelivery(selectedCity);
            if(delType === 'pickup') {
                document.getElementById('ck-pvz-section').style.display = '';
                loadPvzPoints(selectedCity);
            }
        }
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}


// ============================================================
// ЗАКАЗЫ (OrderListResponse: {items: [OrderListItem], total})
// ============================================================

export async function renderOrders() {
    setActiveNav('orders'); hideBackButton(); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Мои заказы</div></div><div id="ord-list" style="padding-bottom:16px">'+Array(3).fill('<div class="order-card"><div class="skeleton" style="height:80px"></div></div>').join('')+'</div></div>';

    try {
        const r = await api.orders.list();
        const orders = r.items || r;
        const el = document.getElementById('ord-list'); if(!el) return;

        if(!orders?.length) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state__icon">📦</div><div class="empty-state__title">Заказов пока нет</div><div class="empty-state__text">Присоединитесь к сбору</div><button class="btn btn-primary" onclick="location.hash=\'catalog\'">Каталог</button></div>';
            return;
        }

        // OrderListItem: product_name, product_image (плоские поля)
        el.innerHTML = orders.map(o => {
            const st = orderStatusInfo(o.status);
            return `<a href="#order/${o.id}" class="order-card" style="display:block;text-decoration:none;color:var(--text)">
                <div class="order-card__header"><span class="order-card__number">Заказ #${o.id}</span><span class="badge badge-${st.color}">${st.emoji} ${st.text}</span></div>
                <div class="order-card__product">
                    <div class="order-card__img">${o.product_image?`<img src="${escapeHtml(o.product_image)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">`:''}</div>
                    <div class="order-card__info"><div class="order-card__name">${escapeHtml(o.product_name||'Товар')}</div><div class="order-card__price">${formatPrice(o.total_amount)}</div></div>
                </div>
                <div class="order-card__footer">
                    <span>${formatDate(o.created_at,'relative')}</span>
                    ${o.savings&&parseFloat(o.savings)>0?`<span class="text-success">Экономия ${formatPrice(o.savings)}</span>`:''}
                </div>
            </a>`;
        }).join('');
    } catch(e) { console.error(e); document.getElementById('ord-list').innerHTML = '<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div>'; }
}


// ============================================================
// ДЕТАЛИ ЗАКАЗА (OrderDetailResponse — плоские поля!)
// ============================================================

export async function renderOrder(id) {
    setActiveNav('orders'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Заказ #'+id+'</div></div><div style="padding:16px"><div class="skeleton" style="height:200px;border-radius:var(--radius-lg)"></div></div></div>';

    try {
        const o = await api.orders.get(id);
        if(!o){showToast('Не найден','error');router.back();return;}
        const st = orderStatusInfo(o.status);

        // Таймлайн
        const statuses = ['pending','frozen','paid','processing','shipped','delivered'];
        const curIdx = statuses.indexOf(o.status);

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:80px">
            <div class="topbar"><div class="topbar__title">Заказ #${o.id}</div><span class="badge badge-${st.color}">${st.emoji} ${st.text}</span></div>
            <div class="checkout-section">
                <div class="order-card__product">
                    <div class="order-card__img" style="width:64px;height:64px">${o.product_image?`<img src="${escapeHtml(o.product_image)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">`:''}</div>
                    <div class="order-card__info">
                        <div class="order-card__name">${escapeHtml(o.product_name||'Товар')}</div>
                        <div class="order-card__price" style="font-size:1.1rem">${formatPrice(o.total_amount)}</div>
                        ${o.savings&&parseFloat(o.savings)>0?`<div class="text-success" style="font-size:0.85rem">Экономия ${formatPrice(o.savings)}</div>`:''}
                    </div>
                </div>
            </div>
            ${!['cancelled','refunded'].includes(o.status)?`
            <div class="checkout-section">
                <div class="checkout-section__title">Статус</div>
                <div class="timeline">${statuses.map((s,i)=>{
                    const inf = orderStatusInfo(s);
                    return `<div class="timeline__item ${i<curIdx?'completed':''} ${i===curIdx?'active':''}">
                        <div class="timeline__dot">${i<curIdx?'✓':i===curIdx?inf.emoji:''}</div>
                        <div class="timeline__content"><div class="timeline__title">${inf.text}</div></div>
                    </div>`;
                }).join('')}</div>
            </div>`:''}
            <div class="checkout-section">
                <div class="checkout-section__title">Доставка</div>
                <div class="address-card" style="cursor:default">
                    <div class="address-card__icon">📍</div>
                    <div class="address-card__text">
                        <div class="address-card__title">${escapeHtml(o.delivery_type_text||o.delivery_type)}</div>
                        <div class="address-card__detail">${escapeHtml(o.address_text||'')}</div>
                    </div>
                </div>
                ${o.tracking_number?`<div style="margin-top:8px;font-size:0.85rem"><strong>Трек:</strong> ${escapeHtml(o.tracking_number)}</div>`:''}
            </div>
            <div class="order-summary">
                <div class="order-summary__row"><span>Товар</span><span>${formatPrice(o.final_price)}</span></div>
                <div class="order-summary__row"><span>Доставка</span><span>${parseFloat(o.delivery_cost)>0?formatPrice(o.delivery_cost):'Бесплатно'}</span></div>
                <div class="order-summary__total"><span>Итого</span><span>${formatPrice(o.total_amount)}</span></div>
            </div>
            ${o.can_cancel?`<div style="padding:16px var(--page-padding)"><button class="btn btn-outline btn-block" id="cancel-btn" style="color:var(--danger);border-color:var(--danger)">Отменить заказ</button></div>`:''}
            ${o.status==='delivered'?`<div style="padding:0 var(--page-padding) 16px"><button class="btn btn-outline btn-block" id="return-btn" style="color:var(--warning);border-color:var(--warning)">🔄 Оформить возврат</button></div>`:''}
        </div>`;

        document.getElementById('cancel-btn')?.addEventListener('click', async () => {
            if(!await showConfirm('Отменить заказ?')) return;
            try { await api.orders.cancel(id); showToast('Отменён','success'); renderOrder(id); } catch(e) { showToast(e.message||'Ошибка','error'); }
        });
        document.getElementById('return-btn')?.addEventListener('click', () => {
            haptic('light');
            router.navigate(`return/create/${id}`);
        });
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}


// ============================================================
// ПРОФИЛЬ
// ============================================================

export async function renderProfile() {
    setActiveNav('profile'); hideBackButton(); hideMainButton();
    const app = document.getElementById('app');

    // Берём юзера из состояния (уже загружен при авторизации)
    const u = appState.user;

    if (!u) {
        app.innerHTML = '<div class="empty-state"><div class="empty-state__icon">👤</div><div class="empty-state__title">Не удалось загрузить профиль</div><div class="empty-state__text">Попробуйте перезапустить приложение</div></div>';
        return;
    }

    const lE = levelEmoji(u.level), lN = levelName(u.level);
    const init = (u.first_name || u.username || '?')[0].toUpperCase();

    app.innerHTML = `
    <div class="page-enter">
        <div class="profile-header">
            <div class="profile-header__avatar">${init}</div>
            <div class="profile-header__name">${escapeHtml(u.first_name||'')} ${escapeHtml(u.last_name||'')}</div>
            <div class="profile-header__level">${lE} ${lN}</div>
        </div>
        <div class="profile-stats">
            <div class="profile-stat"><div class="profile-stat__value">${u.total_orders||0}</div><div class="profile-stat__label">Заказов</div></div>
            <div class="profile-stat"><div class="profile-stat__value">${formatPrice(u.total_savings||0)}</div><div class="profile-stat__label">Экономия</div></div>
            <div class="profile-stat"><div class="profile-stat__value">${u.invited_count||0}</div><div class="profile-stat__label">Приглашено</div></div>
        </div>
        <div class="profile-menu">
            <a href="#orders" class="profile-menu__item"><span class="profile-menu__icon">📦</span><span class="profile-menu__text">Мои заказы</span><span class="profile-menu__arrow">›</span></a>
            <a href="#groups" class="profile-menu__item"><span class="profile-menu__icon">👥</span><span class="profile-menu__text">Мои сборы</span><span class="profile-menu__arrow">›</span></a>
            <a href="#addresses" class="profile-menu__item"><span class="profile-menu__icon">📍</span><span class="profile-menu__text">Адреса доставки</span><span class="profile-menu__arrow">›</span></a>
            <a href="#returns" class="profile-menu__item"><span class="profile-menu__icon">🔄</span><span class="profile-menu__text">Мои возвраты</span><span class="profile-menu__arrow">›</span></a>
            <a href="#notifications" class="profile-menu__item"><span class="profile-menu__icon">🔔</span><span class="profile-menu__text">Уведомления</span><span class="profile-menu__arrow">›</span></a>
            <a href="#support" class="profile-menu__item"><span class="profile-menu__icon">💬</span><span class="profile-menu__text">Поддержка</span><span class="profile-menu__arrow">›</span></a>
            <a href="#faq" class="profile-menu__item"><span class="profile-menu__icon">❓</span><span class="profile-menu__text">Частые вопросы</span><span class="profile-menu__arrow">›</span></a>
            <button class="profile-menu__item" id="stats-btn"><span class="profile-menu__icon">📊</span><span class="profile-menu__text">Статистика</span><span class="profile-menu__arrow">›</span></button>
        </div>
    </div>`;

    document.getElementById('stats-btn')?.addEventListener('click', async () => {
        haptic('light');
        try {
            const s = await api.users.stats();
            showSheet('📊 Статистика', `
                <div style="text-align:center;margin-bottom:20px">
                    <div style="font-size:2.5rem">${s.level_emoji||lE}</div>
                    <div style="font-size:1.2rem;font-weight:800;margin-top:8px">${s.level_name||lN}</div>
                    <div style="margin:12px 0"><div class="progress-bar"><div class="progress-bar__fill" style="width:${(s.level_progress||0)*100}%"></div></div></div>
                </div>
                <div class="profile-stats" style="padding:0;margin-bottom:16px">
                    <div class="profile-stat"><div class="profile-stat__value">${s.total_orders||0}</div><div class="profile-stat__label">Заказов</div></div>
                    <div class="profile-stat"><div class="profile-stat__value">${s.groups_participated||0}</div><div class="profile-stat__label">Сборов</div></div>
                    <div class="profile-stat"><div class="profile-stat__value">${s.people_invited||0}</div><div class="profile-stat__label">Приглашено</div></div>
                </div>
            `);
        } catch(e) { showToast('Ошибка','error'); }
    });
}


// ============================================================
// МОИ СБОРЫ (MyGroupsResponse: {active, completed, organized})
// ============================================================

export async function renderMyGroups() {
    setActiveNav('groups'); hideBackButton(); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter"><div class="topbar"><div class="topbar__title">Мои сборы</div></div>
        <div class="tabs" id="g-tabs"><button class="tab active" data-tab="active">Активные</button><button class="tab" data-tab="completed">Завершённые</button><button class="tab" data-tab="organized">Созданные</button></div>
        <div id="g-list">${Array(3).fill('<div class="order-card"><div class="skeleton" style="height:80px"></div></div>').join('')}</div></div>`;

    let curTab = 'active';
    document.getElementById('g-tabs')?.addEventListener('click', e => {
        const t = e.target.closest('.tab'); if(!t)return; haptic('light');
        document.querySelectorAll('#g-tabs .tab').forEach(t=>t.classList.remove('active')); t.classList.add('active');
        curTab = t.dataset.tab; renderGroupsList(curTab);
    });
    loadMyGroupsData();
}

let _myGroupsData = null;

async function loadMyGroupsData() {
    try {
        /**
         * MyGroupsResponse: { active: [...], completed: [...], organized: [...] }
         * Каждый элемент — GroupListItem с плоскими полями
         */
        _myGroupsData = await api.groups.my();
        renderGroupsList('active');
    } catch(e) {
        console.error(e);
        document.getElementById('g-list').innerHTML = '<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div><div class="empty-state__text">Проверьте подключение к интернету</div></div>';
    }
}

function renderGroupsList(tab) {
    const el = document.getElementById('g-list'); if(!el || !_myGroupsData) return;
    const groups = _myGroupsData[tab] || [];

    if(!groups.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-state__icon">👥</div><div class="empty-state__title">${tab==='active'?'Нет активных сборов':tab==='completed'?'Нет завершённых':'Вы ещё не создавали сборов'}</div><button class="btn btn-primary" onclick="location.hash='catalog'">Каталог</button></div>`;
        return;
    }

    // GroupListItem: product_name, product_image, current_price, base_price
    el.innerHTML = groups.map(g => {
        const tl = getTimeLeft(g.deadline);
        const st = groupStatusInfo(g.status);
        const prog = g.progress_percent || 0;
        return `<a href="#group/${g.id}" class="order-card" style="display:block;text-decoration:none;color:var(--text)">
            <div class="order-card__header"><span class="order-card__name">${escapeHtml(g.product_name||'Сбор')}</span><span class="badge badge-${st.color}">${st.emoji} ${st.text}</span></div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin:8px 0">
                <span style="font-size:0.85rem">👥 ${pluralize(g.current_count,'участник','участника','участников')}</span>
                <span class="price" style="font-size:1rem">${formatPrice(g.current_price)}</span>
            </div>
            <div class="progress-bar" style="height:6px"><div class="progress-bar__fill" style="width:${Math.min(prog,100)}%"></div></div>
            ${g.status==='active'&&!tl.expired?`<div style="font-size:0.8rem;color:var(--text-hint);margin-top:6px">⏳ ${tl.text}</div>`:''}
        </a>`;
    }).join('');
}


// ============================================================
// АДРЕСА
// ============================================================

export async function renderAddresses() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter"><div class="topbar"><div class="topbar__title">Адреса</div></div>
        <div id="a-list" class="address-list" style="padding-top:8px"><div class="skeleton" style="height:80px;border-radius:var(--radius-md);margin-bottom:12px"></div></div>
        <div style="padding:16px var(--page-padding)"><button class="btn btn-primary btn-block" id="add-a">+ Добавить адрес</button></div></div>`;
    document.getElementById('add-a')?.addEventListener('click', () => { haptic('light'); showAddrForm(); });
    loadAddrs();
}

async function loadAddrs() {
    const el = document.getElementById('a-list'); if(!el)return;
    try {
        const r = await api.users.addresses();
        const addrs = r.items || r || [];
        if(!addrs.length) { el.innerHTML = '<div class="empty-state" style="padding:24px"><div class="empty-state__icon">📍</div><div class="empty-state__title">Нет адресов</div></div>'; return; }
        el.innerHTML = addrs.map(a => `
            <div class="address-item">
                <div class="address-item__icon">📍</div>
                <div class="address-item__content">
                    <div class="address-item__title">${escapeHtml(a.title)}</div>
                    <div class="address-item__text">${escapeHtml(a.city)}, ${escapeHtml(a.street)}, д. ${escapeHtml(a.building)}${a.apartment?', кв. '+escapeHtml(a.apartment):''}</div>
                    ${a.is_default?'<div class="address-item__default">По умолчанию</div>':''}
                </div>
                <div class="address-item__actions"><button class="address-item__action" data-del="${a.id}">🗑</button></div>
            </div>`).join('');
        el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
            if(!await showConfirm('Удалить адрес?'))return;
            try { await api.users.deleteAddress(b.dataset.del); showToast('Удалён','success'); loadAddrs(); } catch(e) { showToast('Ошибка','error'); }
        }));
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}

function showAddrForm(existing=null) {
    const a = existing||{};
    const s = showSheet(existing?'Изменить':'Новый адрес', `
        <div class="input-group"><label>Название</label><input class="input" id="af-title" placeholder="Дом, Работа..." value="${escapeHtml(a.title||'')}"></div>
        <div class="input-group"><label>Город</label><input class="input" id="af-city" placeholder="Москва" value="${escapeHtml(a.city||'')}"></div>
        <div class="input-group"><label>Улица</label><input class="input" id="af-street" placeholder="ул. Пушкина" value="${escapeHtml(a.street||'')}"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div class="input-group"><label>Дом</label><input class="input" id="af-bld" placeholder="12А" value="${escapeHtml(a.building||'')}"></div>
            <div class="input-group"><label>Квартира</label><input class="input" id="af-apt" placeholder="42" value="${escapeHtml(a.apartment||'')}"></div>
        </div>
        <div class="input-group"><label>Комментарий</label><input class="input" id="af-com" placeholder="Код домофона..." value="${escapeHtml(a.comment||'')}"></div>
        <div class="toggle"><span>По умолчанию</span><button class="toggle__switch ${a.is_default?'active':''}" id="af-def"></button></div>
        <button class="btn btn-primary btn-block" id="af-save" style="margin-top:12px">${existing?'Сохранить':'Добавить'}</button>
    `);
    let isDef = a.is_default||false;
    s.element.querySelector('#af-def')?.addEventListener('click', function(){isDef=!isDef;this.classList.toggle('active',isDef);});
    s.element.querySelector('#af-save')?.addEventListener('click', async () => {
        const d = {
            title: s.element.querySelector('#af-title').value.trim(),
            city: s.element.querySelector('#af-city').value.trim(),
            street: s.element.querySelector('#af-street').value.trim(),
            building: s.element.querySelector('#af-bld').value.trim(),
            apartment: s.element.querySelector('#af-apt').value.trim()||null,
            comment: s.element.querySelector('#af-com').value.trim()||null,
            is_default: isDef
        };
        if(!d.title||!d.city||!d.street||!d.building){showToast('Заполните поля','error');return;}
        try {
            if(existing) await api.users.updateAddress(existing.id,d); else await api.users.addAddress(d);
            showToast(existing?'Обновлён':'Добавлен','success'); haptic('success'); s.close(); loadAddrs();
        } catch(e) { showToast(e.message||'Ошибка','error'); }
    });
}


// ============================================================
// ВОЗВРАТЫ
// ============================================================

const RETURN_REASONS = {
    defect: '🔴 Брак / дефект',
    wrong_size: '📏 Не подошёл размер',
    not_as_described: '❓ Не соответствует описанию',
    changed_mind: '💭 Передумал'
};
const RETURN_STATUS = {
    pending: { text: 'На рассмотрении', emoji: '⏳', color: 'warning' },
    approved: { text: 'Одобрен', emoji: '✅', color: 'success' },
    rejected: { text: 'Отклонён', emoji: '❌', color: 'danger' },
    awaiting_item: { text: 'Ожидает товар', emoji: '📬', color: 'accent' },
    completed: { text: 'Завершён', emoji: '✔️', color: 'success' }
};

export async function renderReturns() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Мои возвраты</div></div><div style="padding:16px"><div class="skeleton" style="height:120px;border-radius:var(--radius-md);margin-bottom:8px"></div><div class="skeleton" style="height:120px;border-radius:var(--radius-md)"></div></div></div>';

    try {
        const res = await api.returns.list();
        const items = res.items || res || [];

        if (!items.length) {
            app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Мои возвраты</div></div><div class="empty-state"><div class="empty-state__icon">🔄</div><div class="empty-state__title">Нет возвратов</div><div class="empty-state__text">Здесь будут ваши заявки на возврат</div></div></div>';
            return;
        }

        app.innerHTML = `
        <div class="page-enter">
            <div class="topbar"><div class="topbar__title">Мои возвраты</div></div>
            <div style="padding:0 var(--page-padding)">
                ${items.map(r => {
                    const st = RETURN_STATUS[r.status] || { text: r.status, emoji: '❓', color: 'accent' };
                    return `<div class="order-card" style="cursor:pointer" onclick="location.hash='return/${r.id}'">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <div><strong>Возврат #${r.id}</strong> <span style="color:var(--text-hint)">· Заказ #${r.order_id}</span></div>
                            <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
                        </div>
                        <div style="margin-top:8px;font-size:0.9rem;color:var(--text-hint)">${RETURN_REASONS[r.reason] || r.reason}</div>
                        <div style="margin-top:4px;font-size:0.85rem;color:var(--text-hint)">${formatDate(r.created_at)}</div>
                    </div>`;
                }).join('')}
            </div>
        </div>`;
    } catch(e) { console.error(e); showToast('Ошибка загрузки','error'); }
}

export async function renderReturnCreate(orderId) {
    setActiveNav(''); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');

    app.innerHTML = `
    <div class="page-enter">
        <div class="topbar"><div class="topbar__title">Оформить возврат</div></div>
        <div style="padding:0 var(--page-padding)">
            <div class="checkout-section">
                <div class="checkout-section__title">Заказ #${orderId}</div>
            </div>
            <div class="checkout-section">
                <div class="checkout-section__title">Причина возврата</div>
                <div id="ret-reasons" style="display:flex;flex-direction:column;gap:8px">
                    ${Object.entries(RETURN_REASONS).map(([k,v]) => `
                        <div class="address-card" data-reason="${k}" style="cursor:pointer">
                            <div class="address-card__text"><div class="address-card__title">${v}</div></div>
                        </div>`).join('')}
                </div>
            </div>
            <div class="checkout-section">
                <div class="checkout-section__title">Опишите проблему</div>
                <textarea class="form-input" id="ret-desc" rows="4" placeholder="Минимум 10 символов..." style="resize:vertical"></textarea>
            </div>
            <button class="btn btn-primary btn-block btn-lg" id="ret-submit" disabled>Отправить заявку</button>
        </div>
    </div>`;

    let selReason = null;
    document.getElementById('ret-reasons')?.addEventListener('click', e => {
        const c = e.target.closest('[data-reason]'); if(!c) return; haptic('light');
        document.querySelectorAll('#ret-reasons .address-card').forEach(c=>c.classList.remove('selected'));
        c.classList.add('selected'); selReason = c.dataset.reason;
        checkRetForm();
    });
    const descEl = document.getElementById('ret-desc');
    descEl?.addEventListener('input', checkRetForm);
    function checkRetForm() {
        const btn = document.getElementById('ret-submit');
        if(btn) btn.disabled = !selReason || (descEl?.value?.trim()?.length || 0) < 10;
    }
    document.getElementById('ret-submit')?.addEventListener('click', async () => {
        const btn = document.getElementById('ret-submit'); btn.disabled = true; btn.textContent = 'Отправка...';
        try {
            await api.returns.create({ order_id: parseInt(orderId), reason: selReason, description: descEl.value.trim() });
            showToast('Заявка отправлена!','success'); haptic('success');
            router.navigate('returns');
        } catch(e) { btn.disabled = false; btn.textContent = 'Отправить заявку'; showToast(e.message||'Ошибка','error'); }
    });
}


// ============================================================
// ПОДДЕРЖКА
// ============================================================

const SUPPORT_CATS = {
    delivery: '🚚 Доставка', payment: '💳 Оплата', product: '📦 Товар',
    order: '📋 Заказ', 'return': '🔄 Возврат', account: '👤 Аккаунт', other: '❓ Другое'
};
const TICKET_STATUS = {
    open: { text: 'Открыто', color: 'danger' }, in_progress: { text: 'В работе', color: 'warning' },
    waiting_user: { text: 'Ожидает ответа', color: 'accent' }, closed: { text: 'Закрыто', color: 'success' }
};

export async function renderSupport() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Поддержка</div></div><div style="padding:16px"><div class="skeleton" style="height:80px;border-radius:var(--radius-md);margin-bottom:8px"></div></div></div>';

    try {
        const res = await api.support.list();
        const items = res.items || res || [];

        app.innerHTML = `
        <div class="page-enter">
            <div class="topbar"><div class="topbar__title">Поддержка</div></div>
            <div style="padding:0 var(--page-padding)">
                <button class="btn btn-primary btn-block" onclick="location.hash='support/create'" style="margin-bottom:16px">💬 Новое обращение</button>
                ${!items.length ? '<div class="empty-state"><div class="empty-state__icon">💬</div><div class="empty-state__title">Нет обращений</div></div>' :
                items.map(t => {
                    const st = TICKET_STATUS[t.status] || { text: t.status, color: 'accent' };
                    const cat = SUPPORT_CATS[t.category] || t.category;
                    const lastMsg = t.last_message || t.message || '';
                    return `<div class="order-card" style="cursor:pointer" onclick="location.hash='support/${t.id}'">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <div><strong>${cat}</strong></div>
                            <span class="badge badge-${st.color}">${st.text}</span>
                        </div>
                        <div style="margin-top:6px;font-size:0.9rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(lastMsg.substring(0,60))}</div>
                        <div style="margin-top:4px;font-size:0.85rem;color:var(--text-hint)">${formatDate(t.created_at)}</div>
                    </div>`;
                }).join('')}
            </div>
        </div>`;
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}

export async function renderSupportCreate() {
    setActiveNav(''); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');

    app.innerHTML = `
    <div class="page-enter">
        <div class="topbar"><div class="topbar__title">Новое обращение</div></div>
        <div style="padding:0 var(--page-padding)">
            <div class="checkout-section">
                <div class="checkout-section__title">Категория</div>
                <div id="sup-cats" style="display:flex;flex-wrap:wrap;gap:8px">
                    ${Object.entries(SUPPORT_CATS).map(([k,v]) => `<button class="category-chip" data-cat="${k}">${v}</button>`).join('')}
                </div>
            </div>
            <div class="checkout-section">
                <div class="checkout-section__title">Сообщение</div>
                <textarea class="form-input" id="sup-msg" rows="5" placeholder="Опишите вашу проблему (мин. 10 символов)..." style="resize:vertical"></textarea>
            </div>
            <button class="btn btn-primary btn-block btn-lg" id="sup-submit" disabled>Отправить</button>
        </div>
    </div>`;

    let selCat = null;
    document.getElementById('sup-cats')?.addEventListener('click', e => {
        const c = e.target.closest('[data-cat]'); if(!c) return; haptic('light');
        document.querySelectorAll('#sup-cats .category-chip').forEach(c=>c.classList.remove('active'));
        c.classList.add('active'); selCat = c.dataset.cat;
        checkSupForm();
    });
    const msgEl = document.getElementById('sup-msg');
    msgEl?.addEventListener('input', checkSupForm);
    function checkSupForm() {
        const btn = document.getElementById('sup-submit');
        if(btn) btn.disabled = !selCat || (msgEl?.value?.trim()?.length || 0) < 10;
    }
    document.getElementById('sup-submit')?.addEventListener('click', async () => {
        const btn = document.getElementById('sup-submit'); btn.disabled = true; btn.textContent = 'Отправка...';
        try {
            const ticket = await api.support.create({ category: selCat, message: msgEl.value.trim() });
            showToast('Обращение создано!','success'); haptic('success');
            router.navigate(`support/${ticket.id || ticket.ticket_id}`);
        } catch(e) { btn.disabled = false; btn.textContent = 'Отправить'; showToast(e.message||'Ошибка','error'); }
    });
}

export async function renderSupportTicket(id) {
    setActiveNav(''); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Обращение #'+id+'</div></div><div style="padding:16px"><div class="skeleton" style="height:200px;border-radius:var(--radius-md)"></div></div></div>';

    try {
        const t = await api.support.get(id);
        if(!t) { showToast('Не найдено','error'); router.back(); return; }
        const msgs = t.messages || [];
        const st = TICKET_STATUS[t.status] || { text: t.status, color: 'accent' };
        const isClosed = t.status === 'closed';

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:${isClosed?'16px':'80px'}">
            <div class="topbar"><div class="topbar__title">${SUPPORT_CATS[t.category]||t.category}</div><span class="badge badge-${st.color}">${st.text}</span></div>
            <div class="chat-messages" id="chat-msgs">
                ${msgs.map(m => `
                    <div class="chat-msg ${m.sender_type==='user'?'chat-msg--user':'chat-msg--support'}">
                        <div class="chat-msg__bubble">${escapeHtml(m.text)}</div>
                        <div class="chat-msg__time">${m.created_at ? formatDate(m.created_at) : ''}</div>
                    </div>`).join('')}
                ${!msgs.length ? '<div style="text-align:center;padding:32px;color:var(--text-hint)">Начало переписки</div>' : ''}
            </div>
            ${!isClosed ? `
            <div class="chat-input-bar">
                <input type="text" class="form-input" id="chat-input" placeholder="Написать..." style="flex:1">
                <button class="btn btn-primary" id="chat-send">➤</button>
            </div>` : '<div style="text-align:center;padding:16px;color:var(--text-hint)">Обращение закрыто</div>'}
        </div>`;

        // Скролл вниз
        const chatEl = document.getElementById('chat-msgs');
        if(chatEl) chatEl.scrollTop = chatEl.scrollHeight;

        if(!isClosed) {
            const input = document.getElementById('chat-input');
            const send = async () => {
                const text = input?.value?.trim();
                if(!text) return;
                input.value = '';
                try {
                    await api.support.sendMessage(id, text);
                    renderSupportTicket(id);
                } catch(e) { showToast(e.message||'Ошибка','error'); }
            };
            document.getElementById('chat-send')?.addEventListener('click', send);
            input?.addEventListener('keydown', e => { if(e.key === 'Enter') send(); });
        }
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}


// ============================================================
// УВЕДОМЛЕНИЯ
// ============================================================

const NOTIF_ICONS = {
    group_joined: '👥', group_completed: '🎉', group_failed: '😔',
    order_paid: '💳', order_shipped: '🚚', order_delivered: '✅',
    price_drop: '📉', level_up: '⬆️', referral_bonus: '🎁',
    return_approved: '✅', return_rejected: '❌', support_reply: '💬'
};

export async function renderNotifications() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Уведомления</div></div><div style="padding:16px"><div class="skeleton" style="height:60px;border-radius:var(--radius-md);margin-bottom:8px"></div><div class="skeleton" style="height:60px;border-radius:var(--radius-md);margin-bottom:8px"></div><div class="skeleton" style="height:60px;border-radius:var(--radius-md)"></div></div></div>';

    try {
        const res = await api.notifications.list();
        const items = res.items || res || [];
        const unread = items.filter(n => !n.is_read).length;

        app.innerHTML = `
        <div class="page-enter">
            <div class="topbar">
                <div class="topbar__title">Уведомления</div>
                ${unread > 0 ? `<button class="btn btn-sm btn-secondary" id="notif-readall">Прочитать все</button>` : ''}
            </div>
            <div style="padding:0 var(--page-padding)">
                ${!items.length ? '<div class="empty-state"><div class="empty-state__icon">🔔</div><div class="empty-state__title">Нет уведомлений</div></div>' :
                items.map(n => `
                    <div class="notif-item ${n.is_read?'':'notif-item--unread'}" data-nid="${n.id}">
                        <div class="notif-item__icon">${NOTIF_ICONS[n.type] || '🔔'}</div>
                        <div class="notif-item__content">
                            <div class="notif-item__title">${escapeHtml(n.title || n.type)}</div>
                            <div class="notif-item__text">${escapeHtml(n.message || '')}</div>
                            <div class="notif-item__time">${formatDate(n.created_at)}</div>
                        </div>
                    </div>`).join('')}
            </div>
        </div>`;

        document.getElementById('notif-readall')?.addEventListener('click', async () => {
            try { await api.notifications.markAllRead(); showToast('Прочитано','success'); renderNotifications(); } catch(e) {}
        });

        // Клик по уведомлению — пометить прочитанным
        document.querySelectorAll('.notif-item[data-nid]').forEach(el => {
            el.addEventListener('click', async () => {
                const nid = el.dataset.nid;
                if(el.classList.contains('notif-item--unread')) {
                    try { await api.notifications.markRead(nid); } catch(e) {}
                    el.classList.remove('notif-item--unread');
                }
            });
        });
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}


// ============================================================
// FAQ
// ============================================================

export async function renderFAQ() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Частые вопросы</div></div><div style="padding:16px"><div class="skeleton" style="height:60px;border-radius:var(--radius-md);margin-bottom:8px"></div><div class="skeleton" style="height:60px;border-radius:var(--radius-md);margin-bottom:8px"></div></div></div>';

    try {
        const res = await api.support.faq();
        const items = res.items || res || [];

        if(!items.length) {
            app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Частые вопросы</div></div><div class="empty-state"><div class="empty-state__icon">❓</div><div class="empty-state__title">Скоро появятся</div></div></div>';
            return;
        }

        // Группируем по категориям
        const grouped = {};
        items.forEach(f => {
            const cat = f.category || 'other';
            if(!grouped[cat]) grouped[cat] = [];
            grouped[cat].push(f);
        });

        app.innerHTML = `
        <div class="page-enter">
            <div class="topbar"><div class="topbar__title">Частые вопросы</div></div>
            <div style="padding:0 var(--page-padding)">
                ${Object.entries(grouped).map(([cat, faqs]) => `
                    <div style="margin-bottom:16px">
                        <div style="font-weight:700;margin-bottom:8px;font-size:0.95rem">${SUPPORT_CATS[cat] || cat}</div>
                        ${faqs.map(f => `
                            <div class="faq-item">
                                <div class="faq-item__q" onclick="this.parentElement.classList.toggle('open')">${escapeHtml(f.question)}<span class="faq-item__arrow">›</span></div>
                                <div class="faq-item__a">${escapeHtml(f.answer)}</div>
                            </div>`).join('')}
                    </div>`).join('')}
                <div style="text-align:center;padding:24px">
                    <div style="color:var(--text-hint);margin-bottom:12px">Не нашли ответ?</div>
                    <button class="btn btn-primary" onclick="location.hash='support/create'">💬 Написать в поддержку</button>
                </div>
            </div>
        </div>`;
    } catch(e) { console.error(e); showToast('Ошибка','error'); }
}
