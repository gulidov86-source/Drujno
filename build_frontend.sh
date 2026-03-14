#!/bin/bash
# ============================================================
# build_frontend.sh — Сборка и минификация фронтенда
# ============================================================
#
# ЧТО ДЕЛАЕТ:
#   1. Собирает все JS-модули в один файл (bundle)
#   2. Минифицирует JS и CSS
#   3. Обновляет index.html с ссылками на минифицированные файлы
#   4. Выводит экономию в размере файлов
#
# ЗАЧЕМ:
#   - Без сборки: 5 отдельных HTTP-запросов за JS-файлами
#   - После сборки: 1 запрос за одним файлом
#   - Минификация: уменьшает размер ~60-70%
#
#   Аналогия: вместо 5 посылок курьер привозит одну коробку,
#   и она ещё и сжата вакуумом.
#
# ИСПОЛЬЗОВАНИЕ:
#   chmod +x build_frontend.sh
#   ./build_frontend.sh
#
# ТРЕБОВАНИЯ:
#   npm install -g esbuild   (или npx esbuild)
#
# ============================================================

set -e  # Останавливаемся при первой ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🔨 Сборка фронтенда..."
echo "─────────────────────────"

# Проверяем наличие esbuild
if ! command -v esbuild &> /dev/null && ! npx esbuild --version &> /dev/null 2>&1; then
    echo -e "${RED}❌ esbuild не найден. Установите:${NC}"
    echo "   npm install -g esbuild"
    exit 1
fi

ESBUILD="esbuild"
if ! command -v esbuild &> /dev/null; then
    ESBUILD="npx esbuild"
fi

# Директории
FRONTEND_DIR="frontend"
JS_DIR="$FRONTEND_DIR/js"
CSS_DIR="$FRONTEND_DIR/css"
DIST_DIR="$FRONTEND_DIR/dist"

# Создаём папку dist
mkdir -p "$DIST_DIR"

# ============================================================
# Шаг 1: Собрать и минифицировать JS
# ============================================================
echo ""
echo "📦 JS: Сборка модулей в один bundle..."

# Размер до сборки
BEFORE_JS=$(cat "$JS_DIR/main.js" "$JS_DIR/api.js" "$JS_DIR/app.js" "$JS_DIR/pages.js" "$JS_DIR/telegram.js" 2>/dev/null | wc -c)

# esbuild: bundle (объединяет все import) + minify (сжимает)
# --format=esm — сохраняем ES-модули
# --target=es2020 — совместимость с Telegram WebView
$ESBUILD "$JS_DIR/main.js" \
    --bundle \
    --minify \
    --format=esm \
    --target=es2020 \
    --outfile="$DIST_DIR/bundle.min.js" \
    2>&1

AFTER_JS=$(wc -c < "$DIST_DIR/bundle.min.js")
SAVED_JS=$((BEFORE_JS - AFTER_JS))

echo -e "   ${GREEN}✅ bundle.min.js: ${BEFORE_JS}B → ${AFTER_JS}B (−${SAVED_JS}B, $(( SAVED_JS * 100 / BEFORE_JS ))%)${NC}"


# ============================================================
# Шаг 2: Минифицировать CSS
# ============================================================
echo ""
echo "🎨 CSS: Минификация..."

BEFORE_CSS=$(wc -c < "$CSS_DIR/styles.css")

$ESBUILD "$CSS_DIR/styles.css" \
    --minify \
    --outfile="$DIST_DIR/styles.min.css" \
    2>&1

AFTER_CSS=$(wc -c < "$DIST_DIR/styles.min.css")
SAVED_CSS=$((BEFORE_CSS - AFTER_CSS))

echo -e "   ${GREEN}✅ styles.min.css: ${BEFORE_CSS}B → ${AFTER_CSS}B (−${SAVED_CSS}B, $(( SAVED_CSS * 100 / BEFORE_CSS ))%)${NC}"


# ============================================================
# Шаг 3: Сгенерировать версию (cache-busting)
# ============================================================
VERSION=$(date +%s | tail -c 7)
echo ""
echo "🏷  Версия: v=${VERSION}"


# ============================================================
# Шаг 4: Создать production index.html
# ============================================================
echo ""
echo "📄 Генерация index.html для production..."

cat > "$DIST_DIR/index.html" << HEREDOC
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>GroupBuy</title>
    <!-- Preload: браузер начнёт загрузку ДО парсинга HTML -->
    <link rel="preload" href="dist/bundle.min.js?v=${VERSION}" as="script" crossorigin>
    <link rel="preload" href="dist/styles.min.css?v=${VERSION}" as="style">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link rel="stylesheet" href="dist/styles.min.css?v=${VERSION}">
</head>
<body>

<div id="app-loader" class="loading-overlay">
    <div class="spinner"></div>
    <div class="loading-overlay__text">Загрузка...</div>
</div>

<div id="app"></div>

<nav class="navbar" id="navbar">
    <a href="#" class="navbar__item active" data-page="home">
        <span class="navbar__icon">🏠</span><span>Главная</span>
    </a>
    <a href="#catalog" class="navbar__item" data-page="catalog">
        <span class="navbar__icon">🔍</span><span>Каталог</span>
    </a>
    <a href="#groups" class="navbar__item" data-page="groups">
        <span class="navbar__icon">👥</span><span>Сборы</span>
    </a>
    <a href="#orders" class="navbar__item" data-page="orders">
        <span class="navbar__icon">📦</span><span>Заказы</span>
    </a>
    <a href="#profile" class="navbar__item" data-page="profile">
        <span class="navbar__icon">👤</span><span>Профиль</span>
    </a>
</nav>

<script type="module" src="dist/bundle.min.js?v=${VERSION}"></script>
</body>
</html>
HEREDOC

echo -e "   ${GREEN}✅ dist/index.html создан${NC}"


# ============================================================
# ИТОГ
# ============================================================
echo ""
echo "─────────────────────────"
TOTAL_BEFORE=$((BEFORE_JS + BEFORE_CSS))
TOTAL_AFTER=$((AFTER_JS + AFTER_CSS))
TOTAL_SAVED=$((TOTAL_BEFORE - TOTAL_AFTER))

echo -e "📊 ${GREEN}Итого: ${TOTAL_BEFORE}B → ${TOTAL_AFTER}B${NC}"
echo -e "   ${GREEN}Экономия: ${TOTAL_SAVED}B ($(( TOTAL_SAVED * 100 / TOTAL_BEFORE ))%)${NC}"
echo -e "   ${GREEN}HTTP-запросов: 5 → 1 (JS) + 1 (CSS)${NC}"
echo ""
echo -e "${YELLOW}📌 Не забудь:${NC}"
echo "   1. В main.py обновить mount статики на dist/"
echo "   2. Если используешь Railway — добавить npm в buildpack"
echo "   3. Запускать этот скрипт перед каждым деплоем"
echo ""
echo "🚀 Готово!"
