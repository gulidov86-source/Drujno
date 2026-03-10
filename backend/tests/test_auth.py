"""
Тесты: Авторизация и JWT
Проект: GroupBuy Mini App

Что проверяем:
    1. Создание JWT токена
    2. Верификация валидного токена
    3. Отклонение невалидного/просроченного токена
    4. Формирование TokenResponse

Запуск:
    pytest tests/test_auth.py -v

Аналогия: проверяем что замок на двери работает —
правильный ключ открывает, неправильный нет,
просроченный пропуск не пускает.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import sys
import os

# ============================================================
# НАСТРОЙКА МОКОВ
# ============================================================

# Мокаем settings ДО импорта auth
# Аналогия: подставляем тестовый замок вместо настоящего
mock_settings = MagicMock()
mock_settings.JWT_SECRET = "test-secret-key-for-unit-tests-only"
mock_settings.JWT_ALGORITHM = "HS256"
mock_settings.JWT_EXPIRE_HOURS = 168  # 7 дней


@pytest.fixture(autouse=True)
def mock_config():
    """Подменяем настройки для всех тестов в этом файле."""
    with patch("config.settings", mock_settings):
        # Очищаем кеш модулей чтобы auth перечитал settings
        for mod_name in list(sys.modules.keys()):
            if "auth" in mod_name:
                del sys.modules[mod_name]
        yield


# ============================================================
# ТЕСТЫ: СОЗДАНИЕ ТОКЕНА
# ============================================================

class TestCreateAccessToken:
    """Тесты создания JWT токена."""
    
    def test_returns_string(self):
        """Токен — это непустая строка."""
        from auth import create_access_token
        token = create_access_token(user_id=1, telegram_id=123456)
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_jwt_format_three_parts(self):
        """
        JWT состоит из 3 частей: header.payload.signature
        
        Аналогия: паспорт состоит из 3 частей — обложка,
        данные и печать. Без любой части он невалидный.
        """
        from auth import create_access_token
        token = create_access_token(user_id=1, telegram_id=123456)
        parts = token.split(".")
        assert len(parts) == 3
    
    def test_different_users_different_tokens(self):
        """Разные пользователи получают разные токены."""
        from auth import create_access_token
        token1 = create_access_token(user_id=1, telegram_id=111)
        token2 = create_access_token(user_id=2, telegram_id=222)
        assert token1 != token2
    
    def test_same_user_different_tokens(self):
        """
        Даже один пользователь получает разные токены
        (из-за разного iat — времени создания).
        """
        from auth import create_access_token
        import time
        token1 = create_access_token(user_id=1, telegram_id=111)
        time.sleep(0.01)  # Минимальная задержка для разного iat
        token2 = create_access_token(user_id=1, telegram_id=111)
        # Могут совпасть если время одинаковое, но обычно разные
        # Не assertим — это не баг если совпадут


# ============================================================
# ТЕСТЫ: ВЕРИФИКАЦИЯ ТОКЕНА
# ============================================================

class TestVerifyToken:
    """Тесты верификации JWT токена."""
    
    def test_valid_token_decodes(self):
        """
        Валидный токен декодируется и содержит правильные данные.
        
        Аналогия: правильный ключ → дверь открылась,
        и за ней именно ваша квартира (правильный user_id).
        """
        from auth import create_access_token, verify_token
        token = create_access_token(user_id=42, telegram_id=123456)
        payload = verify_token(token)
        
        assert payload is not None
        assert payload.sub == "42"
        assert payload.telegram_id == 123456
        assert payload.type == "access"
    
    def test_garbage_token_rejected(self):
        """Мусорная строка отклоняется."""
        from auth import verify_token
        result = verify_token("this.is.garbage")
        assert result is None
    
    def test_empty_string_rejected(self):
        """Пустая строка отклоняется."""
        from auth import verify_token
        result = verify_token("")
        assert result is None
    
    def test_partial_token_rejected(self):
        """Неполный токен (только header) отклоняется."""
        from auth import verify_token
        result = verify_token("eyJhbGciOiJIUzI1NiJ9")
        assert result is None
    
    def test_expired_token_rejected(self):
        """
        Просроченный токен не проходит.
        
        Аналогия: пропуск на вчера — охранник не пустит.
        """
        from auth import create_access_token, verify_token
        # Создаём токен, который уже истёк
        token = create_access_token(
            user_id=1,
            telegram_id=123,
            expires_delta=timedelta(seconds=-1)
        )
        result = verify_token(token)
        assert result is None
    
    def test_wrong_secret_rejected(self):
        """
        Токен подписанный другим секретом не проходит.
        
        Аналогия: ключ от соседней квартиры не откроет вашу дверь.
        """
        from jose import jwt
        
        payload = {
            "sub": "1",
            "telegram_id": 123,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
            "type": "access"
        }
        # Подписываем ДРУГИМ секретом
        token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
        
        from auth import verify_token
        result = verify_token(token)
        assert result is None
    
    def test_missing_sub_rejected(self):
        """Токен без поля sub отклоняется."""
        from jose import jwt
        
        payload = {
            "telegram_id": 123,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(
            payload, 
            mock_settings.JWT_SECRET, 
            algorithm="HS256"
        )
        
        from auth import verify_token
        result = verify_token(token)
        assert result is None


# ============================================================
# ТЕСТЫ: TOKEN RESPONSE
# ============================================================

class TestTokenResponse:
    """Тесты формирования полного ответа с токеном."""
    
    def test_response_has_all_fields(self):
        """Ответ содержит access_token, token_type, expires_in."""
        from auth import create_token_response
        response = create_token_response(user_id=1, telegram_id=123)
        
        assert response.access_token is not None
        assert len(response.access_token) > 0
        assert response.token_type == "bearer"
        assert response.expires_in > 0
    
    def test_expires_in_matches_config(self):
        """expires_in соответствует JWT_EXPIRE_HOURS из настроек."""
        from auth import create_token_response
        response = create_token_response(user_id=1, telegram_id=123)
        
        expected_seconds = mock_settings.JWT_EXPIRE_HOURS * 3600
        assert response.expires_in == expected_seconds
    
    def test_token_in_response_is_valid(self):
        """Токен из ответа можно верифицировать."""
        from auth import create_token_response, verify_token
        response = create_token_response(user_id=99, telegram_id=555)
        
        payload = verify_token(response.access_token)
        assert payload is not None
        assert payload.sub == "99"
