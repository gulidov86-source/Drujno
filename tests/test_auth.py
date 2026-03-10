"""
Тесты: Авторизация и JWT
Проект: GroupBuy Mini App

Запуск: pytest backend/tests/test_auth.py -v
"""

import pytest
from datetime import datetime, timedelta

# conftest.py уже добавил backend/ в sys.path
# и подставил фейковые env vars → config.py загрузится без ошибок
from utils.auth import create_access_token, verify_token, create_token_response
from config import settings


# ============================================================
# ТЕСТЫ: СОЗДАНИЕ ТОКЕНА
# ============================================================

class TestCreateAccessToken:
    """Тесты создания JWT токена."""

    def test_returns_string(self):
        """Токен — это непустая строка."""
        token = create_access_token(user_id=1, telegram_id=123456)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_jwt_format_three_parts(self):
        """JWT состоит из 3 частей: header.payload.signature."""
        token = create_access_token(user_id=1, telegram_id=123456)
        parts = token.split(".")
        assert len(parts) == 3

    def test_different_users_different_tokens(self):
        """Разные пользователи получают разные токены."""
        token1 = create_access_token(user_id=1, telegram_id=111)
        token2 = create_access_token(user_id=2, telegram_id=222)
        assert token1 != token2


# ============================================================
# ТЕСТЫ: ВЕРИФИКАЦИЯ ТОКЕНА
# ============================================================

class TestVerifyToken:
    """Тесты верификации JWT токена."""

    def test_valid_token_decodes(self):
        """Валидный токен декодируется и содержит правильные данные."""
        token = create_access_token(user_id=42, telegram_id=123456)
        payload = verify_token(token)

        assert payload is not None
        assert payload.sub == "42"
        assert payload.telegram_id == 123456
        assert payload.type == "access"

    def test_garbage_token_rejected(self):
        """Мусорная строка отклоняется."""
        result = verify_token("this.is.garbage")
        assert result is None

    def test_empty_string_rejected(self):
        """Пустая строка отклоняется."""
        result = verify_token("")
        assert result is None

    def test_partial_token_rejected(self):
        """Неполный токен отклоняется."""
        result = verify_token("eyJhbGciOiJIUzI1NiJ9")
        assert result is None

    def test_expired_token_rejected(self):
        """Просроченный токен не проходит."""
        token = create_access_token(
            user_id=1,
            telegram_id=123,
            expires_delta=timedelta(seconds=-1)
        )
        result = verify_token(token)
        assert result is None

    def test_wrong_secret_rejected(self):
        """Токен подписанный другим секретом не проходит."""
        from jose import jwt

        payload = {
            "sub": "1",
            "telegram_id": 123,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
            "type": "access"
        }
        token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
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
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        result = verify_token(token)
        assert result is None


# ============================================================
# ТЕСТЫ: TOKEN RESPONSE
# ============================================================

class TestTokenResponse:
    """Тесты формирования полного ответа с токеном."""

    def test_response_has_all_fields(self):
        """Ответ содержит access_token, token_type, expires_in."""
        response = create_token_response(user_id=1, telegram_id=123)
        assert response.access_token is not None
        assert len(response.access_token) > 0
        assert response.token_type == "bearer"
        assert response.expires_in > 0

    def test_expires_in_matches_config(self):
        """expires_in соответствует JWT_EXPIRE_HOURS из настроек."""
        response = create_token_response(user_id=1, telegram_id=123)
        expected_seconds = settings.JWT_EXPIRE_HOURS * 3600
        assert response.expires_in == expected_seconds

    def test_token_in_response_is_valid(self):
        """Токен из ответа можно верифицировать."""
        response = create_token_response(user_id=99, telegram_id=555)
        payload = verify_token(response.access_token)
        assert payload is not None
        assert payload.sub == "99"
