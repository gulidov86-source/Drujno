"""
Модуль: routers/image_upload.py
Описание: Загрузка изображений товаров в Supabase Storage
Проект: GroupBuy Mini App (Спринт 3)

Аналогия: фотоателье в магазине. Приносишь фото товара →
оно сохраняется в альбом (Supabase Storage) → получаешь
ссылку, по которой его можно показать покупателям.

Ограничения:
    - Максимум 2MB
    - Только jpg/png
    - Только для админов

Эндпоинты:
    POST /api/admin/upload-image — Загрузить изображение

Подготовка в Supabase:
    1. Dashboard → Storage → New Bucket → "products" (public)
    2. Policies → Allow public SELECT (для показа картинок)
    3. Policies → Allow INSERT/UPDATE для service_role

Использование:
    curl -X POST /api/admin/upload-image \
        -H "Authorization: Bearer <token>" \
        -F "file=@photo.jpg" \
        -F "product_id=42"
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status

import sys
sys.path.append("..")
from config import settings
from database.connection import get_db
from utils.auth import get_current_user


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Название бакета в Supabase Storage
BUCKET_NAME = "products"

# Максимальный размер файла (2MB)
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

# Допустимые типы файлов
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(
    prefix="/api/admin",
    tags=["Админ — Изображения"]
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def validate_image(file: UploadFile) -> None:
    """
    Проверить что файл — допустимое изображение.
    
    Аналогия: охранник на входе в фотоателье проверяет
    что вы принесли фото, а не кирпич.
    """
    # Проверяем Content-Type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый тип файла: {file.content_type}. "
                   f"Разрешены: jpg, png"
        )
    
    # Проверяем расширение
    if file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Недопустимое расширение: {ext}. Разрешены: jpg, png"
            )


def get_storage_url(file_path: str) -> str:
    """
    Получить публичный URL файла в Supabase Storage.
    
    Пример:
        get_storage_url("products/abc123.jpg")
        → "https://xxx.supabase.co/storage/v1/object/public/products/abc123.jpg"
    """
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{file_path}"


# ============================================================
# ЭНДПОИНТЫ
# ============================================================

@router.post(
    "/upload-image",
    summary="Загрузить изображение товара",
    description="""
    Загрузить изображение и привязать к товару.
    
    **Ограничения:**
    - Максимум 2MB
    - Только jpg/png
    
    **Возвращает:**
    - `url` — публичная ссылка на изображение
    """
)
async def upload_product_image(
    file: UploadFile = File(..., description="Изображение (jpg/png, до 2MB)"),
    product_id: Optional[int] = Form(None, description="ID товара (если нужно привязать)"),
    user_id: int = Depends(get_current_user)
):
    """
    Загрузить изображение товара в Supabase Storage.
    
    Процесс:
    1. Валидируем файл (тип, размер)
    2. Генерируем уникальное имя
    3. Загружаем в Supabase Storage бакет "products"
    4. Если указан product_id — обновляем image_url товара
    5. Возвращаем публичный URL
    """
    # TODO: Добавить проверку прав администратора
    # Пока доступно всем авторизованным (для MVP)
    
    # 1. Валидируем файл
    validate_image(file)
    
    # 2. Читаем содержимое и проверяем размер
    content = await file.read()
    
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Файл слишком большой: {len(content) / 1024 / 1024:.1f}MB. "
                   f"Максимум: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
        )
    
    # 3. Генерируем уникальное имя файла
    # Аналогия: каждому фото в ателье присваивают номер,
    # чтобы два разных фото не назывались одинаково
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    storage_path = unique_name  # В корне бакета
    
    # 4. Загружаем в Supabase Storage
    db = get_db()
    
    try:
        # Supabase Python SDK: storage.from_(bucket).upload(path, file)
        result = db.storage.from_(BUCKET_NAME).upload(
            path=storage_path,
            file=content,
            file_options={
                "content-type": file.content_type or "image/jpeg",
                "cache-control": "3600",  # Кешировать 1 час
            }
        )
    except Exception as e:
        error_msg = str(e)
        
        # Если бакет не существует — подсказываем
        if "not found" in error_msg.lower() or "bucket" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Бакет '{BUCKET_NAME}' не найден в Supabase Storage. "
                       f"Создайте его: Dashboard → Storage → New Bucket → '{BUCKET_NAME}' (public)"
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки: {error_msg}"
        )
    
    # 5. Формируем публичный URL
    public_url = get_storage_url(storage_path)
    
    # 6. Если указан product_id — обновляем товар
    if product_id:
        try:
            db.table("products").update({
                "image_url": public_url
            }).eq("id", product_id).execute()
        except Exception as e:
            # Картинка загружена, но привязка не удалась — не критично
            print(f"[Upload] ⚠️ Картинка загружена, но привязка к товару {product_id} не удалась: {e}")
    
    return {
        "success": True,
        "url": public_url,
        "filename": unique_name,
        "size": len(content),
        "product_id": product_id,
        "message": "Изображение загружено" + (f" и привязано к товару #{product_id}" if product_id else "")
    }
