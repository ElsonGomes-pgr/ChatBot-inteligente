"""Testes do processador de PII nos logs."""

from app.core.logging import sanitize_pii, _mask_value


class TestMaskValue:

    def test_mask_email(self):
        assert _mask_value("maria@email.com") == "ma***@email.com"

    def test_mask_name(self):
        assert _mask_value("Maria Silva") == "Ma***"

    def test_mask_short_value(self):
        assert _mask_value("AB") == "***"

    def test_mask_empty(self):
        assert _mask_value("") == ""

    def test_mask_phone(self):
        assert _mask_value("+5511999887766") == "+5***"


class TestSanitizePII:

    def test_masks_pii_fields(self):
        event = {
            "event": "handoff_triggered",
            "user_name": "Maria Silva",
            "user_email": "maria@email.com",
            "conversation_id": "abc-123",
        }
        result = sanitize_pii(None, None, event)
        assert result["user_name"] == "Ma***"
        assert result["user_email"] == "ma***@email.com"
        assert result["conversation_id"] == "abc-123"  # não mascarado

    def test_does_not_mask_non_pii(self):
        event = {"event": "test", "intent": "sales", "urgency_score": 0.5}
        result = sanitize_pii(None, None, event)
        assert result == event

    def test_handles_non_string_pii(self):
        event = {"user_name": None, "phone": 12345}
        result = sanitize_pii(None, None, event)
        assert result["user_name"] is None
        assert result["phone"] == 12345
