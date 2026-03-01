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

import { api, getCachedUser } from './api.js?v=4';
import { haptic, showBackButton, hideBackButton, hideMainButton, shareUrl, showConfirm } from './telegram.js?v=4';
import {
    router, formatPrice, calcDiscount, formatDate, getTimeLeft,
    pluralize, showToast, showSheet, escapeHtml, debounce,
    setActiveNav, levelEmoji, levelName, orderStatusInfo, groupStatusInfo,
    productCardSkeleton, hotGroupCardSkeleton
} from './app.js?v=4';

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
    trackEvent('page_view', { page: 'home' });

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
    trackEvent('product_view', { product_id: id });
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
    trackEvent('group_view', { group_id: id });
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
    trackEvent('checkout_start', { group_id: groupId });
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
                <div class="checkout-section__title">Адрес доставки</div>
                <div id="ck-addrs">${addrs.length ? addrs.map(a=>`
                    <div class="address-card ${a.id===selAddr?'selected':''}" data-addr="${a.id}" style="margin-bottom:8px">
                        <div class="address-card__icon">📍</div>
                        <div class="address-card__text"><div class="address-card__title">${escapeHtml(a.title)}</div><div class="address-card__detail">${escapeHtml(a.city)}, ${escapeHtml(a.street)}, д. ${escapeHtml(a.building)}${a.apartment?', кв. '+escapeHtml(a.apartment):''}</div></div>
                    </div>`).join('') : '<div class="empty-state" style="padding:16px"><div class="empty-state__text">Добавьте адрес</div><button class="btn btn-secondary btn-sm" onclick="location.hash=\'addresses\'">Добавить</button></div>'}</div>
            </div>
            <div class="checkout-section">
                <div class="checkout-section__title">Доставка</div>
                <div id="ck-del">
                    <div class="address-card selected" data-del="pickup" style="margin-bottom:8px;cursor:pointer"><div class="address-card__icon">📦</div><div class="address-card__text"><div class="address-card__title">Пункт выдачи</div><div class="address-card__detail">Бесплатно</div></div></div>
                    <div class="address-card" data-del="courier" style="cursor:pointer"><div class="address-card__icon">🚚</div><div class="address-card__text"><div class="address-card__title">Курьером</div><div class="address-card__detail">от 300 ₽</div></div></div>
                </div>
            </div>
            <div class="order-summary">
                <div class="order-summary__row"><span>Товар</span><span>${formatPrice(g.current_price)}</span></div>
                <div class="order-summary__row"><span>Доставка</span><span id="ck-dcost">Бесплатно</span></div>
                <div class="order-summary__total"><span>Итого</span><span id="ck-total">${formatPrice(g.current_price)}</span></div>
                <div style="font-size:0.8rem;color:var(--text-hint);margin-top:4px">💡 Сумма будет заморожена до завершения сбора</div>
            </div>
            <div class="sticky-action"><button class="btn btn-success btn-block btn-lg" id="pay-btn" ${!addrs.length?'disabled':''}>💳 Оплатить ${formatPrice(g.current_price)}</button></div>
        </div>`;

        document.getElementById('ck-addrs')?.addEventListener('click', e => {
            const c = e.target.closest('[data-addr]'); if(!c) return; haptic('light');
            document.querySelectorAll('#ck-addrs .address-card').forEach(c=>c.classList.remove('selected'));
            c.classList.add('selected'); selAddr = parseInt(c.dataset.addr);
        });

        document.getElementById('ck-del')?.addEventListener('click', e => {
            const c = e.target.closest('[data-del]'); if(!c) return; haptic('light');
            document.querySelectorAll('#ck-del .address-card').forEach(c=>c.classList.remove('selected'));
            c.classList.add('selected'); delType = c.dataset.del;
            const cost = delType==='courier'?300:0;
            document.getElementById('ck-dcost').textContent = cost?formatPrice(cost):'Бесплатно';
            document.getElementById('ck-total').textContent = formatPrice(parseFloat(g.current_price)+cost);
        });

        document.getElementById('pay-btn')?.addEventListener('click', async () => {
            if(!selAddr){showToast('Выберите адрес','error');return;}
            haptic('medium');
            const btn = document.getElementById('pay-btn'); btn.disabled=true; btn.textContent='Обработка...';
            try {
                const order = await api.orders.create({group_id:parseInt(groupId), address_id:selAddr, delivery_type:delType});
                showToast('Заказ оформлен!','success'); haptic('success');
                if(order.payment_url) window.open(order.payment_url,'_blank');
                router.navigate(`order/${order.order_id || order.id}`);
            } catch(e) { btn.disabled=false; btn.textContent='💳 Оплатить'; showToast(e.message||'Ошибка','error'); haptic('error'); }
        });
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
            ${o.status === 'delivered' ? `<div style="padding:0 var(--page-padding) 16px"><button class="btn btn-outline btn-block" id="return-btn">🔄 Оформить возврат</button></div>` : ''}
        </div>`;

        document.getElementById('cancel-btn')?.addEventListener('click', async () => {
            if(!await showConfirm('Отменить заказ?')) return;
            try { await api.orders.cancel(id); showToast('Отменён','success'); renderOrder(id); } catch(e) { showToast(e.message||'Ошибка','error'); }
        });

        // Кнопка возврата — открывает шторку с формой
        document.getElementById('return-btn')?.addEventListener('click', () => {
            haptic('light');
            showReturnForm(id);
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
            <a href="#returns" class="profile-menu__item"><span class="profile-menu__icon">🔄</span><span class="profile-menu__text">Мои возвраты</span><span class="profile-menu__arrow">›</span></a>
            <a href="#addresses" class="profile-menu__item"><span class="profile-menu__icon">📍</span><span class="profile-menu__text">Адреса доставки</span><span class="profile-menu__arrow">›</span></a>
            <div class="profile-menu__divider"></div>
            <a href="#notifications" class="profile-menu__item"><span class="profile-menu__icon">🔔</span><span class="profile-menu__text">Уведомления</span><span class="profile-menu__arrow">›</span></a>
            <a href="#support" class="profile-menu__item"><span class="profile-menu__icon">💬</span><span class="profile-menu__text">Поддержка</span><span class="profile-menu__arrow">›</span></a>
            <a href="#faq" class="profile-menu__item"><span class="profile-menu__icon">❓</span><span class="profile-menu__text">FAQ</span><span class="profile-menu__arrow">›</span></a>
            <div class="profile-menu__divider"></div>
            <button class="profile-menu__item" id="stats-btn"><span class="profile-menu__icon">📊</span><span class="profile-menu__text">Статистика</span><span class="profile-menu__arrow">›</span></button>
            <div class="profile-menu__divider"></div>
            <a href="#privacy" class="profile-menu__item"><span class="profile-menu__icon">🔒</span><span class="profile-menu__text">Политика конфиденциальности</span><span class="profile-menu__arrow">›</span></a>
            <a href="#terms" class="profile-menu__item"><span class="profile-menu__icon">📄</span><span class="profile-menu__text">Пользовательское соглашение</span><span class="profile-menu__arrow">›</span></a>
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
// ВОЗВРАТЫ — список
// ============================================================

/**
 * Статусы возвратов для UI.
 * 
 * Представь: заявка на возврат — это как посылка в обратную сторону.
 * Сначала "На рассмотрении" (ждёт решения админа),
 * потом "Одобрен" → "Ждём товар" → "Завершён" (деньги вернули).
 * Или "Отклонён" — если причина не подходит.
 */
function returnStatusInfo(status) {
    const info = {
        pending:       { emoji: '🕐', text: 'На рассмотрении', color: 'warning' },
        approved:      { emoji: '✅', text: 'Одобрен',         color: 'success' },
        rejected:      { emoji: '❌', text: 'Отклонён',        color: 'danger' },
        awaiting_item: { emoji: '📦', text: 'Ждём товар',      color: 'info' },
        completed:     { emoji: '💰', text: 'Завершён',        color: 'success' },
    };
    return info[status] || { emoji: '❓', text: status, color: '' };
}

/**
 * Причины возврата — человекопонятные названия.
 */
function returnReasonText(reason) {
    const map = {
        wrong_size:       'Не подошёл размер/цвет',
        defect:           'Брак / дефект',
        not_as_described: 'Не соответствует описанию',
        changed_mind:     'Передумал(а)',
    };
    return map[reason] || reason;
}

/**
 * Статусы тикетов поддержки.
 */
function ticketStatusInfo(status) {
    const info = {
        open:         { emoji: '🟢', text: 'Открыт',           color: 'success' },
        in_progress:  { emoji: '🔄', text: 'В работе',         color: 'accent' },
        waiting_user: { emoji: '💬', text: 'Ждёт вашего ответа', color: 'warning' },
        closed:       { emoji: '✅', text: 'Закрыт',           color: '' },
    };
    return info[status] || { emoji: '❓', text: status, color: '' };
}


export async function renderReturns() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter">
        <div class="topbar"><div class="topbar__title">Мои возвраты</div></div>
        <div id="ret-list" style="padding-bottom:16px">
            ${Array(2).fill('<div class="order-card"><div class="skeleton" style="height:80px"></div></div>').join('')}
        </div>
    </div>`;

    try {
        const r = await api.returns.list();
        const items = r.items || r || [];
        const el = document.getElementById('ret-list'); if (!el) return;

        if (!items.length) {
            el.innerHTML = `<div class="empty-state">
                <div class="empty-state__icon">🔄</div>
                <div class="empty-state__title">Возвратов нет</div>
                <div class="empty-state__text">Здесь появятся ваши заявки на возврат</div>
            </div>`;
            return;
        }

        el.innerHTML = items.map(ret => {
            const st = returnStatusInfo(ret.status);
            return `<a href="#return/${ret.id}" class="order-card" style="display:block;text-decoration:none;color:var(--text)">
                <div class="order-card__header">
                    <span class="order-card__number">Возврат #${ret.id}</span>
                    <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
                </div>
                <div class="order-card__product">
                    <div class="order-card__info">
                        <div class="order-card__name">${escapeHtml(ret.product_name || 'Заказ #' + ret.order_id)}</div>
                        <div style="font-size:0.85rem;color:var(--text-hint)">${returnReasonText(ret.reason)}</div>
                    </div>
                </div>
                <div class="order-card__footer">
                    <span>${formatDate(ret.created_at, 'relative')}</span>
                    ${ret.refund_amount ? `<span class="text-success">${formatPrice(ret.refund_amount)}</span>` : ''}
                </div>
            </a>`;
        }).join('');
    } catch (e) {
        console.error(e);
        document.getElementById('ret-list').innerHTML = '<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div>';
    }
}


// ============================================================
// ВОЗВРАТ — детали
// ============================================================

export async function renderReturn(id) {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Возврат #' + id + '</div></div><div style="padding:16px"><div class="skeleton" style="height:200px;border-radius:var(--radius-lg)"></div></div></div>';

    try {
        const ret = await api.returns.get(id);
        if (!ret) { showToast('Не найден', 'error'); router.back(); return; }
        const st = returnStatusInfo(ret.status);

        // Таймлайн возврата
        const steps = ['pending', 'approved', 'awaiting_item', 'completed'];
        const isRejected = ret.status === 'rejected';
        const curIdx = steps.indexOf(ret.status);

        app.innerHTML = `
        <div class="page-enter">
            <div class="topbar">
                <div class="topbar__title">Возврат #${ret.id}</div>
                <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
            </div>

            <div class="checkout-section">
                <div class="checkout-section__title">Товар</div>
                <div class="order-card__product">
                    <div class="order-card__img">${ret.product_image ? `<img src="${escapeHtml(ret.product_image)}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)">` : ''}</div>
                    <div class="order-card__info">
                        <div class="order-card__name">${escapeHtml(ret.product_name || 'Заказ #' + ret.order_id)}</div>
                        ${ret.refund_amount ? `<div class="order-card__price">${formatPrice(ret.refund_amount)}</div>` : ''}
                    </div>
                </div>
            </div>

            <div class="checkout-section">
                <div class="checkout-section__title">Причина</div>
                <div style="padding:0 var(--page-padding)">
                    <div style="font-weight:600;margin-bottom:4px">${returnReasonText(ret.reason)}</div>
                    ${ret.description ? `<div style="font-size:0.9rem;color:var(--text-secondary)">${escapeHtml(ret.description)}</div>` : ''}
                </div>
            </div>

            ${!isRejected ? `
            <div class="checkout-section">
                <div class="checkout-section__title">Прогресс</div>
                <div class="timeline">${steps.map((s, i) => {
                    const inf = returnStatusInfo(s);
                    return `<div class="timeline__item ${i < curIdx ? 'completed' : ''} ${i === curIdx ? 'active' : ''}">
                        <div class="timeline__dot">${i < curIdx ? '✓' : i === curIdx ? inf.emoji : ''}</div>
                        <div class="timeline__content"><div class="timeline__title">${inf.text}</div></div>
                    </div>`;
                }).join('')}</div>
            </div>` : `
            <div class="checkout-section">
                <div style="padding:16px var(--page-padding);text-align:center">
                    <div style="font-size:2rem;margin-bottom:8px">❌</div>
                    <div style="font-weight:600;margin-bottom:4px">Заявка отклонена</div>
                    ${ret.admin_comment ? `<div style="font-size:0.9rem;color:var(--text-hint)">${escapeHtml(ret.admin_comment)}</div>` : ''}
                </div>
            </div>`}

            ${ret.status === 'pending' ? `
            <div style="padding:16px var(--page-padding)">
                <button class="btn btn-outline btn-block" id="cancel-ret-btn" style="color:var(--danger);border-color:var(--danger)">Отменить заявку</button>
            </div>` : ''}
        </div>`;

        document.getElementById('cancel-ret-btn')?.addEventListener('click', async () => {
            if (!await showConfirm('Отменить заявку на возврат?')) return;
            try {
                await api.returns.cancel(id);
                showToast('Заявка отменена', 'success');
                router.navigate('returns');
            } catch (e) { showToast(e.message || 'Ошибка', 'error'); }
        });
    } catch (e) { console.error(e); showToast('Ошибка', 'error'); }
}


// ============================================================
// СОЗДАНИЕ ВОЗВРАТА — форма (вызывается из заказа)
// ============================================================

/**
 * Показывает шторку для оформления возврата.
 *
 * Представь: пользователь открыл заказ со статусом "Доставлен",
 * нажал "Оформить возврат" → внизу выезжает форма:
 *   1. Выбор причины (выпадающий список)
 *   2. Описание проблемы (текстовое поле)
 *   3. Кнопка "Отправить"
 */
function showReturnForm(orderId) {
    const s = showSheet('🔄 Оформить возврат', `
        <div class="input-group">
            <label>Причина возврата</label>
            <select class="input" id="ret-reason">
                <option value="">— Выберите —</option>
                <option value="wrong_size">Не подошёл размер/цвет</option>
                <option value="defect">Брак / дефект</option>
                <option value="not_as_described">Не соответствует описанию</option>
                <option value="changed_mind">Передумал(а)</option>
            </select>
        </div>
        <div class="input-group">
            <label>Опишите проблему</label>
            <textarea class="input" id="ret-desc" rows="3" placeholder="Расскажите, что не так с товаром..."></textarea>
        </div>
        <button class="btn btn-primary btn-block" id="ret-submit" style="margin-top:12px">Отправить заявку</button>
    `);

    s.element.querySelector('#ret-submit')?.addEventListener('click', async () => {
        const reason = s.element.querySelector('#ret-reason').value;
        const description = s.element.querySelector('#ret-desc').value.trim();

        if (!reason) { showToast('Выберите причину', 'error'); return; }
        if (!description) { showToast('Опишите проблему', 'error'); return; }

        const btn = s.element.querySelector('#ret-submit');
        btn.disabled = true; btn.textContent = 'Отправка...';

        try {
            const result = await api.returns.create({ order_id: parseInt(orderId), reason, description });
            showToast('Заявка создана!', 'success');
            haptic('success');
            s.close();
            router.navigate(`return/${result.return_id || result.id}`);
        } catch (e) {
            showToast(e.message || 'Ошибка', 'error');
            btn.disabled = false; btn.textContent = 'Отправить заявку';
        }
    });
}


// ============================================================
// ПОДДЕРЖКА — список тикетов
// ============================================================

export async function renderSupport() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter">
        <div class="topbar">
            <div class="topbar__title">Поддержка</div>
            <button class="btn btn-sm btn-primary" id="new-ticket-btn" style="font-size:0.8rem;padding:6px 14px">+ Обращение</button>
        </div>
        <div id="sup-list" style="padding-bottom:16px">
            ${Array(2).fill('<div class="order-card"><div class="skeleton" style="height:70px"></div></div>').join('')}
        </div>
    </div>`;

    document.getElementById('new-ticket-btn')?.addEventListener('click', () => {
        haptic('light'); router.navigate('support/create');
    });

    try {
        const r = await api.support.list();
        const items = r.items || r || [];
        const el = document.getElementById('sup-list'); if (!el) return;

        if (!items.length) {
            el.innerHTML = `<div class="empty-state">
                <div class="empty-state__icon">💬</div>
                <div class="empty-state__title">Обращений нет</div>
                <div class="empty-state__text">Если есть вопрос — напишите нам!</div>
                <button class="btn btn-primary" onclick="location.hash='support/create'">Написать</button>
            </div>`;
            return;
        }

        el.innerHTML = items.map(t => {
            const st = ticketStatusInfo(t.status);
            return `<a href="#support/${t.id}" class="order-card" style="display:block;text-decoration:none;color:var(--text)">
                <div class="order-card__header">
                    <span class="order-card__number">${escapeHtml(t.category_display || t.category)}</span>
                    <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
                </div>
                <div style="padding:0 16px 8px">
                    <div style="font-size:0.9rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(t.last_message?.text || t.message || '')}</div>
                </div>
                <div class="order-card__footer">
                    <span>${formatDate(t.updated_at || t.created_at, 'relative')}</span>
                    ${t.unread_count ? `<span class="badge badge-accent">${t.unread_count} новых</span>` : ''}
                </div>
            </a>`;
        }).join('');
    } catch (e) {
        console.error(e);
        document.getElementById('sup-list').innerHTML = '<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div>';
    }
}


// ============================================================
// ПОДДЕРЖКА — создание обращения
// ============================================================

export async function renderSupportCreate() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');

    app.innerHTML = `
    <div class="page-enter">
        <div class="topbar"><div class="topbar__title">Новое обращение</div></div>
        <div style="padding:16px var(--page-padding)">
            <div class="input-group">
                <label>Тема обращения</label>
                <select class="input" id="sc-cat">
                    <option value="">— Выберите —</option>
                    <option value="delivery">🚚 Доставка</option>
                    <option value="payment">💳 Оплата</option>
                    <option value="product">📦 Товар</option>
                    <option value="order">📋 Заказ</option>
                    <option value="return">🔄 Возврат</option>
                    <option value="account">👤 Аккаунт</option>
                    <option value="other">❓ Другое</option>
                </select>
            </div>
            <div class="input-group">
                <label>Номер заказа <span style="color:var(--text-hint)">(если есть)</span></label>
                <input class="input" id="sc-order" type="number" placeholder="Например: 42">
            </div>
            <div class="input-group">
                <label>Сообщение</label>
                <textarea class="input" id="sc-msg" rows="4" placeholder="Опишите вашу проблему или вопрос..."></textarea>
            </div>
            <button class="btn btn-primary btn-block btn-lg" id="sc-submit">Отправить</button>
        </div>
    </div>`;

    document.getElementById('sc-submit')?.addEventListener('click', async () => {
        const category = document.getElementById('sc-cat').value;
        const message = document.getElementById('sc-msg').value.trim();
        const orderId = document.getElementById('sc-order').value.trim();

        if (!category) { showToast('Выберите тему', 'error'); return; }
        if (!message) { showToast('Напишите сообщение', 'error'); return; }

        const btn = document.getElementById('sc-submit');
        btn.disabled = true; btn.textContent = 'Отправка...';

        try {
            const d = { category, message };
            if (orderId) d.order_id = parseInt(orderId);
            const result = await api.support.create(d);
            showToast('Обращение создано!', 'success');
            haptic('success');
            router.navigate(`support/${result.ticket_id || result.id}`);
        } catch (e) {
            showToast(e.message || 'Ошибка', 'error');
            btn.disabled = false; btn.textContent = 'Отправить';
        }
    });
}


// ============================================================
// ПОДДЕРЖКА — переписка (чат с поддержкой)
// ============================================================

/**
 * Чат с поддержкой — как мессенджер:
 * - Сообщения пользователя справа (синие)
 * - Ответы поддержки слева (серые)
 * - Внизу поле ввода + кнопка отправки
 */
export async function renderSupportTicket(id) {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = '<div class="page-enter"><div class="topbar"><div class="topbar__title">Обращение</div></div><div style="padding:16px"><div class="skeleton" style="height:200px;border-radius:var(--radius-lg)"></div></div></div>';

    try {
        const t = await api.support.get(id);
        if (!t) { showToast('Не найден', 'error'); router.back(); return; }
        const st = ticketStatusInfo(t.status);
        const messages = t.messages || [];
        const isClosed = t.status === 'closed';

        app.innerHTML = `
        <div class="page-enter" style="padding-bottom:${isClosed ? '16px' : '76px'}">
            <div class="topbar">
                <div>
                    <div class="topbar__title">${escapeHtml(t.category_display || t.category)}</div>
                    <div style="font-size:0.75rem;color:var(--text-hint)">#${t.id}</div>
                </div>
                <span class="badge badge-${st.color}">${st.emoji} ${st.text}</span>
            </div>

            <div class="chat-messages" id="chat-msgs">
                ${messages.map(m => `
                    <div class="chat-msg ${m.sender_type === 'user' ? 'chat-msg--user' : 'chat-msg--support'}">
                        <div class="chat-msg__bubble">${escapeHtml(m.text)}</div>
                        <div class="chat-msg__time">${formatDate(m.created_at, 'datetime')}</div>
                    </div>
                `).join('')}
                ${!messages.length ? '<div style="text-align:center;padding:24px;color:var(--text-hint)">Начало переписки</div>' : ''}
            </div>

            ${!isClosed ? `
            <div class="chat-input-bar" id="chat-bar">
                <input class="input chat-input" id="chat-input" placeholder="Ваше сообщение..." autocomplete="off">
                <button class="btn btn-primary chat-send-btn" id="chat-send">→</button>
            </div>` : `
            <div style="text-align:center;padding:16px;color:var(--text-hint);font-size:0.85rem">
                ✅ Обращение закрыто
            </div>`}
        </div>`;

        // Скроллим чат вниз
        const chatEl = document.getElementById('chat-msgs');
        if (chatEl) chatEl.scrollTop = chatEl.scrollHeight;

        // Отправка сообщения
        const sendMsg = async () => {
            const input = document.getElementById('chat-input');
            const text = input?.value.trim();
            if (!text) return;

            input.value = '';
            const chatMsgs = document.getElementById('chat-msgs');

            // Оптимистично добавляем сообщение (мгновенно)
            const msgEl = document.createElement('div');
            msgEl.className = 'chat-msg chat-msg--user';
            msgEl.innerHTML = `<div class="chat-msg__bubble">${escapeHtml(text)}</div><div class="chat-msg__time">только что</div>`;
            chatMsgs?.appendChild(msgEl);
            chatMsgs.scrollTop = chatMsgs.scrollHeight;

            try {
                await api.support.sendMessage(id, text);
                haptic('light');
            } catch (e) {
                msgEl.querySelector('.chat-msg__bubble').style.opacity = '0.5';
                showToast('Не удалось отправить', 'error');
            }
        };

        document.getElementById('chat-send')?.addEventListener('click', sendMsg);
        document.getElementById('chat-input')?.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
        });

    } catch (e) { console.error(e); showToast('Ошибка', 'error'); }
}


// ============================================================
// УВЕДОМЛЕНИЯ
// ============================================================

/**
 * Типы уведомлений — иконки для визуального различия.
 *
 * Представь: уведомление — это как SMS от магазина.
 * По иконке сразу видно о чём: оплата, доставка, акция и т.д.
 */
function notifIcon(type) {
    const icons = {
        payment:  '💳',
        order:    '📦',
        group:    '👥',
        delivery: '🚚',
        return:   '🔄',
        support:  '💬',
        promo:    '🎉',
        system:   'ℹ️',
    };
    return icons[type] || '🔔';
}

export async function renderNotifications() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter">
        <div class="topbar">
            <div class="topbar__title">Уведомления</div>
            <button class="btn btn-sm btn-secondary" id="mark-all-btn" style="font-size:0.8rem;padding:6px 12px">Прочитать все</button>
        </div>
        <div id="notif-list" style="padding-bottom:16px">
            ${Array(3).fill('<div class="order-card"><div class="skeleton" style="height:60px"></div></div>').join('')}
        </div>
    </div>`;

    document.getElementById('mark-all-btn')?.addEventListener('click', async () => {
        try {
            await api.notifications.markAllRead();
            showToast('Все прочитаны', 'success');
            // Обновляем бейдж
            updateNotifBadge(0);
            // Убираем выделение непрочитанных
            document.querySelectorAll('.notif-item--unread').forEach(el => el.classList.remove('notif-item--unread'));
        } catch (e) { showToast('Ошибка', 'error'); }
    });

    try {
        const r = await api.notifications.list({ limit: 50 });
        const items = r.items || r || [];
        const el = document.getElementById('notif-list'); if (!el) return;

        if (!items.length) {
            el.innerHTML = `<div class="empty-state">
                <div class="empty-state__icon">🔔</div>
                <div class="empty-state__title">Пока тихо</div>
                <div class="empty-state__text">Здесь будут уведомления о заказах, сборах и акциях</div>
            </div>`;
            return;
        }

        el.innerHTML = items.map(n => `
            <div class="notif-item ${!n.is_read ? 'notif-item--unread' : ''}" data-nid="${n.id}" ${n.link ? `onclick="location.hash='${escapeHtml(n.link)}'"` : ''} style="cursor:${n.link ? 'pointer' : 'default'}">
                <div class="notif-item__icon">${notifIcon(n.type)}</div>
                <div class="notif-item__body">
                    <div class="notif-item__title">${escapeHtml(n.title)}</div>
                    <div class="notif-item__text">${escapeHtml(n.message || n.body || '')}</div>
                    <div class="notif-item__time">${formatDate(n.created_at, 'relative')}</div>
                </div>
                ${!n.is_read ? '<div class="notif-item__dot"></div>' : ''}
            </div>
        `).join('');

        // Отмечаем как прочитанное при клике
        el.querySelectorAll('.notif-item--unread').forEach(item => {
            item.addEventListener('click', async () => {
                const nid = item.dataset.nid;
                try {
                    await api.notifications.markRead(nid);
                    item.classList.remove('notif-item--unread');
                    item.querySelector('.notif-item__dot')?.remove();
                } catch (e) { /* молча */ }
            });
        });
    } catch (e) {
        console.error(e);
        document.getElementById('notif-list').innerHTML = '<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div>';
    }
}


// ============================================================
// FAQ — Часто задаваемые вопросы
// ============================================================

/**
 * FAQ — как аккордеон: нажал на вопрос — раскрылся ответ.
 * Вопросы сгруппированы по категориям (Оплата, Доставка и т.д.)
 */
export async function renderFAQ() {
    setActiveNav('profile'); showBackButton(() => router.back()); hideMainButton();
    const app = document.getElementById('app');
    app.innerHTML = `<div class="page-enter">
        <div class="topbar"><div class="topbar__title">FAQ</div></div>
        <div id="faq-list" style="padding:8px var(--page-padding) 16px">
            <div class="skeleton" style="height:200px;border-radius:var(--radius-md)"></div>
        </div>
    </div>`;

    try {
        const r = await api.support.faq();
        const data = r.data || r || {};
        const el = document.getElementById('faq-list'); if (!el) return;

        const categories = Object.entries(data);
        if (!categories.length) {
            el.innerHTML = `<div class="empty-state">
                <div class="empty-state__icon">📚</div>
                <div class="empty-state__title">FAQ пока пуст</div>
                <div class="empty-state__text">Скоро здесь появятся ответы на частые вопросы</div>
            </div>`;
            return;
        }

        el.innerHTML = categories.map(([cat, questions]) => `
            <div style="margin-bottom:16px">
                <div style="font-weight:700;font-size:1rem;margin-bottom:8px;padding:4px 0">${escapeHtml(cat)}</div>
                ${questions.map((q, i) => `
                    <div class="faq-item">
                        <button class="faq-item__question" data-faq="${cat}-${i}">
                            <span>${escapeHtml(q.question)}</span>
                            <span class="faq-item__arrow">›</span>
                        </button>
                        <div class="faq-item__answer" id="faq-${cat}-${i}" style="display:none">
                            ${escapeHtml(q.answer)}
                        </div>
                    </div>
                `).join('')}
            </div>
        `).join('');

        // Аккордеон — клик по вопросу раскрывает ответ
        el.querySelectorAll('.faq-item__question').forEach(btn => {
            btn.addEventListener('click', () => {
                haptic('light');
                const id = btn.dataset.faq;
                const answer = document.getElementById('faq-' + id);
                const arrow = btn.querySelector('.faq-item__arrow');
                if (!answer) return;

                const isOpen = answer.style.display !== 'none';
                answer.style.display = isOpen ? 'none' : 'block';
                if (arrow) arrow.style.transform = isOpen ? '' : 'rotate(90deg)';
            });
        });
    } catch (e) {
        console.error(e);
        document.getElementById('faq-list').innerHTML = '<div class="empty-state"><div class="empty-state__icon">⚠️</div><div class="empty-state__title">Ошибка загрузки</div></div>';
    }
}



// ============================================================
// ЮРИДИЧЕСКИЕ СТРАНИЦЫ
// ============================================================

/**
 * Политика конфиденциальности.
 * 
 * Зачем: ЮKassa и закон РФ (152-ФЗ) требуют ссылку на политику
 * обработки персональных данных. Без неё не подключить оплату.
 */
export function renderPrivacy() {
    setActiveNav('profile'); showBackButton();
    const app = document.getElementById('app');
    app.innerHTML = `
    <div class="page-enter">
        <div class="topbar"><div class="topbar__title">Конфиденциальность</div></div>
        <div style="padding:16px;line-height:1.6;font-size:0.95rem" class="legal-text">
            <h3>Политика конфиденциальности</h3>
            <p>Дата обновления: 1 марта 2026 г.</p>

            <h4>1. Общие положения</h4>
            <p>Настоящая Политика определяет порядок обработки персональных данных пользователей сервиса GroupBuy (далее — «Сервис»). Используя Сервис, вы даёте согласие на обработку данных в соответствии с настоящей Политикой.</p>

            <h4>2. Какие данные мы собираем</h4>
            <p>При использовании Сервиса через Telegram Mini App мы получаем:</p>
            <p>— Telegram ID, имя, фамилию и username (из Telegram WebApp API);</p>
            <p>— адрес доставки (при оформлении заказа);</p>
            <p>— данные о заказах и платежах;</p>
            <p>— обращения в поддержку.</p>
            <p>Мы <b>не получаем и не храним</b> данные банковских карт — платежи обрабатываются ЮKassa.</p>

            <h4>3. Цели обработки</h4>
            <p>Данные используются для: оформления и доставки заказов, работы групповых сборов, уведомлений о статусе заказов, ответов на обращения в поддержку, улучшения Сервиса.</p>

            <h4>4. Хранение и защита</h4>
            <p>Данные хранятся на защищённых серверах (Supabase) с шифрованием. Доступ к данным имеют только уполномоченные сотрудники. Срок хранения — до удаления аккаунта пользователем или 3 года с момента последнего использования.</p>

            <h4>5. Передача третьим лицам</h4>
            <p>Данные передаются: службе доставки СДЭК (для отправки посылок), ЮKassa (для обработки платежей). Данные не передаются в рекламных целях.</p>

            <h4>6. Ваши права</h4>
            <p>Вы можете запросить информацию о ваших данных, потребовать их изменения или удаления, написав в поддержку Сервиса.</p>

            <h4>7. Контакты</h4>
            <p>По вопросам обработки данных обращайтесь через раздел «Поддержка» в приложении.</p>
        </div>
    </div>`;
    trackEvent('page_view', { page: 'privacy' });
}


/**
 * Пользовательское соглашение (оферта).
 * 
 * Зачем: юридическое основание для приёма денег.
 * Нажимая «Оплатить», пользователь соглашается с условиями.
 */
export function renderTerms() {
    setActiveNav('profile'); showBackButton();
    const app = document.getElementById('app');
    app.innerHTML = `
    <div class="page-enter">
        <div class="topbar"><div class="topbar__title">Соглашение</div></div>
        <div style="padding:16px;line-height:1.6;font-size:0.95rem" class="legal-text">
            <h3>Пользовательское соглашение</h3>
            <p>Дата обновления: 1 марта 2026 г.</p>

            <h4>1. Предмет соглашения</h4>
            <p>Настоящее Соглашение регулирует использование сервиса GroupBuy (далее — «Сервис»), предоставляющего возможность участия в групповых покупках товаров.</p>

            <h4>2. Регистрация</h4>
            <p>Регистрация происходит автоматически при входе через Telegram. Используя Сервис, вы подтверждаете что вам исполнилось 18 лет.</p>

            <h4>3. Групповые сборы</h4>
            <p>Сбор — совместная покупка товара группой участников. Цена зависит от количества участников и снижается при увеличении группы. Если минимальное количество участников не набрано до дедлайна — сбор отменяется, средства возвращаются автоматически.</p>

            <h4>4. Оплата</h4>
            <p>Оплата производится через ЮKassa. При оформлении заказа средства замораживаются (холдируются). Списание происходит только после успешного завершения сбора. В случае отмены сбора средства возвращаются в течение 24 часов.</p>

            <h4>5. Доставка</h4>
            <p>Доставка осуществляется службой СДЭК. Стоимость рассчитывается автоматически при оформлении заказа. Сроки доставки зависят от региона и указаны при оформлении.</p>

            <h4>6. Возвраты</h4>
            <p>Возврат товара возможен в течение 14 дней с момента получения в соответствии с Законом РФ «О защите прав потребителей». Для оформления возврата используйте раздел «Мои возвраты» в приложении.</p>

            <h4>7. Ответственность</h4>
            <p>Сервис не несёт ответственности за задержки доставки по вине транспортной компании. Сервис гарантирует возврат средств при отмене сбора.</p>

            <h4>8. Изменение условий</h4>
            <p>Мы вправе изменять условия Соглашения, уведомляя пользователей через приложение. Продолжение использования Сервиса означает согласие с изменениями.</p>

            <h4>9. Контакты</h4>
            <p>По любым вопросам обращайтесь через раздел «Поддержка» в приложении.</p>
        </div>
    </div>`;
    trackEvent('page_view', { page: 'terms' });
}


// ============================================================
// АНАЛИТИКА — простой трекер событий
// ============================================================

/**
 * Отправляет событие аналитики на бэкенд.
 * 
 * Наглядно — это как камера в магазине:
 *   Покупатель вошёл     → trackEvent('page_view', {page: 'home'})
 *   Открыл товар         → trackEvent('product_view', {id: 42})
 *   Присоединился к сбору → trackEvent('group_join', {group_id: 7})
 *   Оплатил              → trackEvent('payment_start', {order_id: 15})
 * 
 * Потом можно посмотреть воронку:
 *   100 зашли → 40 открыли товар → 15 вступили → 8 оплатили
 *   Конверсия: 8%
 * 
 * Событие отправляется "тихо" (fire-and-forget) — 
 * не блокирует интерфейс и не показывает ошибки.
 */
export function trackEvent(event, data = {}) {
    try {
        api.analytics?.track(event, data);
    } catch (e) {
        // Аналитика не должна ломать приложение
    }
}

// ============================================================
// БЕЙДЖ НЕПРОЧИТАННЫХ УВЕДОМЛЕНИЙ
// ============================================================

/**
 * Обновляет бейдж (кружок с цифрой) на иконке профиля в навбаре.
 * 
 * Представь: как на иконке мессенджера — красный кружок с "3",
 * значит 3 непрочитанных. Если 0 — кружок исчезает.
 */
export function updateNotifBadge(count) {
    const profileNav = document.querySelector('.navbar__item[data-page="profile"]');
    if (!profileNav) return;

    // Удаляем старый бейдж
    const oldBadge = profileNav.querySelector('.navbar__badge');
    if (oldBadge) oldBadge.remove();

    // Добавляем новый если есть непрочитанные
    if (count > 0) {
        profileNav.style.position = 'relative';
        const badge = document.createElement('span');
        badge.className = 'navbar__badge';
        badge.textContent = count > 99 ? '99+' : count;
        profileNav.appendChild(badge);
    }
}

/**
 * Загружает количество непрочитанных и обновляет бейдж.
 * Вызывается при инициализации приложения.
 */
export async function loadNotifBadge() {
    try {
        const r = await api.notifications.unreadCount();
        const count = r.count ?? r.unread_count ?? r ?? 0;
        updateNotifBadge(typeof count === 'number' ? count : 0);
    } catch (e) {
        // Молча — бейдж не критичен
        console.warn('Notif badge error:', e);
    }
}
