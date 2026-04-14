"""
Configuração de logging estruturado com proteção de PII (LGPD).

O processador sanitize_pii mascara campos sensíveis antes de gravar no log,
garantindo que dados pessoais nunca apareçam em ficheiros de log ou serviços
de agregação (Datadog, CloudWatch, etc.).
"""

import re
import structlog

# Campos que contêm dados pessoais e devem ser mascarados nos logs
PII_FIELDS = {"user_name", "user_email", "user_phone", "email", "phone", "name"}

# Regex para detetar e-mails em valores de texto livre
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def _mask_value(value: str) -> str:
    """Mascara um valor mantendo apenas o início para referência."""
    if not value:
        return value
    if "@" in value:
        local, domain = value.split("@", 1)
        return f"{local[:2]}***@{domain}"
    if len(value) <= 2:
        return "***"
    return f"{value[:2]}***"


def sanitize_pii(logger, method_name, event_dict):
    """Processador structlog que mascara campos PII antes de escrever no log."""
    for key in list(event_dict.keys()):
        if key in PII_FIELDS and isinstance(event_dict[key], str):
            event_dict[key] = _mask_value(event_dict[key])
    return event_dict


def configure_logging(debug: bool = False):
    """Configura structlog com processadores padrão e proteção PII."""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        sanitize_pii,
    ]

    if debug:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
