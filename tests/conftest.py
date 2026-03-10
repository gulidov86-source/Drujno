import os
import sys

# 1. backend/ в PATH
backend_dir = os.path.dirname(os.path.abspath(__file__))  # ← исправлено
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# 2. Подпапки в PATH (чтобы import price_calculator работал)
for _sub in ["services", "routers", "utils", "database"]:
    _path = os.path.join(backend_dir, _sub)
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

# 3. Фейковые переменные окружения
_test_env = {
    "TELEGRAM_BOT_TOKEN": "test-bot-token",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_KEY": "test-service-key",
    "JWT_SECRET": "test-jwt-secret-for-unit-tests",
    "APP_ENV": "development",
    "DEBUG": "True",
}
for key, value in _test_env.items():
    if key not in os.environ:
        os.environ[key] = value