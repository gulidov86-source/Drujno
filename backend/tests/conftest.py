"""
Общая конфигурация pytest для всех тестов.

Структура проекта:
    project_root/
    ├── backend/          ← тут main.py, auth.py, config.py и т.д.
    │   ├── main.py
    │   ├── auth.py
    │   ├── config.py
    │   ├── ...
    │   └── tests/        ← мы здесь
    │       ├── conftest.py
    │       ├── test_auth.py
    │       └── ...

Добавляет backend/ в sys.path, чтобы
импорты вида `from auth import ...` работали.
"""
import sys
import os

# tests/ лежит внутри backend/, значит:
# __file__        = backend/tests/conftest.py
# parent dir      = backend/tests/
# parent.parent   = backend/        ← вот сюда нужен путь
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
