import os
import sys

# backend/ в PATH
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, backend_dir)

# Подпапки в PATH
for _sub in ["services", "routers", "utils", "database"]:
    _path = os.path.join(backend_dir, _sub)
    if os.path.isdir(_path):
        sys.path.insert(0, _path)

# Фейковые переменные — ДО любых импортов
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "True")