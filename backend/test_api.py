"""
============================================================
СКРИПТ ТЕСТИРОВАНИЯ API — GroupBuy Mini App
============================================================

Этот скрипт проверяет все эндпоинты перед запуском.

Использование:
    1. Установи BASE_URL на свой Railway домен
    2. Запусти: python test_api.py
    3. Зелёные ✅ = работает, красные ❌ = проблема

Представь это как чеклист перед полётом самолёта:
    пилот проходит по списку и проверяет каждую систему.
    Мы делаем то же самое, но для нашего API.
============================================================
"""

import asyncio
import aiohttp
import json
import time
import sys

# ============================================================
# НАСТРОЙКИ
# ============================================================

# Замени на свой URL в Railway
BASE_URL = "https://drujno-production.up.railway.app"

# Тайм-аут запросов (секунды)
TIMEOUT = 15

# ============================================================
# ХЕЛПЕРЫ
# ============================================================

class Colors:
    """ANSI-цвета для терминала"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg):
    print(f"  {Colors.GREEN}✅ {msg}{Colors.END}")

def fail(msg, detail=""):
    print(f"  {Colors.RED}❌ {msg}{Colors.END}")
    if detail:
        print(f"     {Colors.GRAY}{detail}{Colors.END}")

def warn(msg):
    print(f"  {Colors.YELLOW}⚠️  {msg}{Colors.END}")

def section(title):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}{Colors.END}")

# Счётчики
results = {"pass": 0, "fail": 0, "warn": 0}

async def test_endpoint(session, method, path, expected_status=200, body=None, headers=None, name=None):
    """
    Тестирует один эндпоинт.
    
    Как это работает (наглядно):
    
    Наш скрипт  ──GET /health──►  Railway сервер
                                      │
                ◄──200 OK + JSON──────┘
    
    Мы проверяем: 
      1. Пришёл ли ответ вообще? (сервер жив)
      2. Правильный ли статус-код? (200 = ОК, 401 = нет доступа)
      3. Есть ли JSON в ответе? (данные корректны)
    """
    url = f"{BASE_URL}{path}"
    label = name or f"{method} {path}"
    
    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with session.request(
            method, url, 
            json=body, 
            headers=headers,
            timeout=timeout
        ) as resp:
            status = resp.status
            try:
                data = await resp.json()
            except:
                data = await resp.text()
            
            if status == expected_status:
                ok(f"{label} → {status}")
                results["pass"] += 1
                return {"ok": True, "status": status, "data": data}
            else:
                fail(f"{label} → {status} (ожидался {expected_status})", 
                     str(data)[:200] if data else "")
                results["fail"] += 1
                return {"ok": False, "status": status, "data": data}
                
    except asyncio.TimeoutError:
        fail(f"{label} → TIMEOUT ({TIMEOUT}s)")
        results["fail"] += 1
        return {"ok": False, "error": "timeout"}
    except aiohttp.ClientError as e:
        fail(f"{label} → CONNECTION ERROR", str(e))
        results["fail"] += 1
        return {"ok": False, "error": str(e)}


# ============================================================
# ТЕСТЫ
# ============================================================

async def run_tests():
    """Запуск всех тестов"""
    
    print(f"\n{Colors.BOLD}🧪 ТЕСТИРОВАНИЕ API GroupBuy Mini App{Colors.END}")
    print(f"{Colors.GRAY}URL: {BASE_URL}{Colors.END}")
    print(f"{Colors.GRAY}Время: {time.strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    
    async with aiohttp.ClientSession() as session:
        
        # ── 1. Системные эндпоинты ──
        section("1. СИСТЕМНЫЕ ЭНДПОИНТЫ")
        
        r = await test_endpoint(session, "GET", "/health", name="Health Check")
        if r["ok"]:
            data = r["data"]
            if isinstance(data, dict):
                db_status = data.get("checks", {}).get("database", {}).get("status")
                env = data.get("environment", "?")
                if db_status == "ok":
                    ok(f"  БД подключена, режим: {env}")
                else:
                    fail(f"  БД: {db_status}")
        
        await test_endpoint(session, "GET", "/config", name="Public Config")
        
        # ── 2. Каталог (без авторизации) ──
        section("2. КАТАЛОГ (публичные эндпоинты)")
        
        r = await test_endpoint(session, "GET", "/api/products", name="Список товаров")
        if r["ok"] and isinstance(r["data"], list):
            active_count = len(r["data"])
            ok(f"  Найдено товаров: {active_count}")
            if active_count < 10:
                warn(f"  Мало товаров! Запусти real_products.sql")
                results["warn"] += 1
        
        await test_endpoint(session, "GET", "/api/products/categories/", name="Категории")
        await test_endpoint(session, "GET", "/api/products/popular/", name="Популярные товары")
        
        # Конкретный товар (берём первый из списка)
        if r["ok"] and isinstance(r["data"], list) and len(r["data"]) > 0:
            product_id = r["data"][0].get("id", 1)
            await test_endpoint(session, "GET", f"/api/products/{product_id}", 
                              name=f"Товар #{product_id}")
        
        # ── 3. Сборы (публичные) ──
        section("3. СБОРЫ (публичные)")
        
        r = await test_endpoint(session, "GET", "/api/groups/hot", name="Горячие сборы")
        if r["ok"] and isinstance(r["data"], list):
            ok(f"  Активных сборов: {len(r['data'])}")
        
        # ── 4. Авторизация ──
        section("4. АВТОРИЗАЦИЯ")
        
        # Без initData должен вернуть ошибку
        r = await test_endpoint(
            session, "POST", "/api/users/auth", 
            expected_status=422,
            body={},
            name="Auth без initData (ожидаем 422)"
        )
        
        # ── 5. Защищённые эндпоинты (без токена = 401/403) ──
        section("5. ЗАЩИТА ЭНДПОИНТОВ (без токена → 401/403)")
        
        for path, name in [
            ("/api/users/me", "Профиль"),
            ("/api/orders", "Заказы"),
            ("/api/groups/my/all", "Мои сборы"),
            ("/api/notifications", "Уведомления"),
            ("/api/support", "Тикеты"),
            ("/api/returns", "Возвраты"),
        ]:
            # Без токена должно быть 401 или 403
            r = await test_endpoint(
                session, "GET", path,
                expected_status=401,
                name=f"{name} без токена → 401"
            )
            # Некоторые эндпоинты могут возвращать 403
            if not r["ok"] and r.get("status") == 403:
                ok(f"  {name} вернул 403 (тоже ок — защищён)")
                results["fail"] -= 1
                results["pass"] += 1
        
        # ── 6. Доставка ──
        section("6. ДОСТАВКА (СДЭК)")
        
        r = await test_endpoint(
            session, "GET", "/api/delivery/cities?query=Москва",
            name="Поиск города: Москва"
        )
        if r["ok"]:
            if isinstance(r["data"], list) and len(r["data"]) > 0:
                ok(f"  Найдено городов: {len(r['data'])}")
            else:
                warn("  Города не найдены (СДЭК API может быть недоступен)")
                results["warn"] += 1
        
        # ── 7. FAQ ──
        section("7. FAQ")
        
        r = await test_endpoint(session, "GET", "/api/support/faq", name="FAQ список")
        if r["ok"] and isinstance(r["data"], list):
            ok(f"  Вопросов: {len(r['data'])}")
            if len(r["data"]) < 5:
                warn("  Мало FAQ! Запусти real_products.sql")
                results["warn"] += 1
        
        # ── 8. Webhook (должен принимать POST) ──
        section("8. WEBHOOK ЮKassa")
        
        # Отправляем пустой POST — должен ответить (не 404/405)
        r = await test_endpoint(
            session, "POST", "/api/payments/webhook",
            expected_status=200,
            body={"type": "notification", "event": "payment.test"},
            name="Webhook endpoint доступен"
        )
        if not r["ok"]:
            if r.get("status") in [400, 422]:
                ok("  Webhook доступен (вернул ошибку валидации — это нормально)")
                results["fail"] -= 1
                results["pass"] += 1
            elif r.get("status") == 404:
                fail("  Webhook НЕ найден! Проверь роуты payments.py")
            elif r.get("status") == 405:
                fail("  Webhook не принимает POST! Проверь метод")
        
        # ── 9. Статические файлы ──
        section("9. ФРОНТЕНД")
        
        # Проверяем что index.html доступен
        r = await test_endpoint(session, "GET", "/", name="index.html (главная)")
        
        for path, name in [
            ("/js/main.js", "main.js"),
            ("/js/pages.js", "pages.js"),
            ("/js/api.js", "api.js"),
            ("/css/styles.css", "styles.css"),
        ]:
            await test_endpoint(session, "GET", path, name=name)
    
    # ── ИТОГИ ──
    section("ИТОГИ")
    total = results["pass"] + results["fail"]
    
    print(f"\n  {Colors.GREEN}Пройдено: {results['pass']}{Colors.END}")
    print(f"  {Colors.RED}Провалено: {results['fail']}{Colors.END}")
    if results["warn"] > 0:
        print(f"  {Colors.YELLOW}Предупреждения: {results['warn']}{Colors.END}")
    
    print()
    if results["fail"] == 0:
        print(f"  {Colors.GREEN}{Colors.BOLD}🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!{Colors.END}")
        print(f"  {Colors.GREEN}Приложение готово к запуску.{Colors.END}")
    elif results["fail"] <= 3:
        print(f"  {Colors.YELLOW}{Colors.BOLD}⚠️  ПОЧТИ ГОТОВО{Colors.END}")
        print(f"  {Colors.YELLOW}Исправь {results['fail']} проблем(ы) выше.{Colors.END}")
    else:
        print(f"  {Colors.RED}{Colors.BOLD}🚫 ЕСТЬ СЕРЬЁЗНЫЕ ПРОБЛЕМЫ{Colors.END}")
        print(f"  {Colors.RED}Исправь {results['fail']} проблем перед запуском.{Colors.END}")
    
    print()
    return results["fail"] == 0


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════╗
║    🧪 GroupBuy API Test Suite                  ║
║    Тестирование перед запуском                 ║
╚════════════════════════════════════════════════╝
    """)
    
    if len(sys.argv) > 1:
        BASE_URL = sys.argv[1].rstrip("/")
        print(f"  URL из аргумента: {BASE_URL}")
    
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
