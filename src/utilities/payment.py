"""Utilidades de pago (tarjeta) para el ProveedorPagos."""

from __future__ import annotations


def normalize_card_digits(card_number: str | None) -> str:
    return "".join(ch for ch in str(card_number or "") if ch.isdigit())


def mask_card(card_number: str | None) -> str:
    digits = normalize_card_digits(card_number)
    if len(digits) >= 4:
        return f"****{digits[-4:]}"
    return ""


def validate_card_payment(card_number: str | None) -> tuple[bool, str]:
    """Valida PAN para cobro (modo clase: cualquier numero con digitos)."""

    digits = normalize_card_digits(card_number)
    if not digits:
        return False, "Falta el numero de tarjeta"
    if len(digits) > 25:
        return False, "Numero de tarjeta demasiado largo"
    return True, ""


def payment_method_label(method: str, card_number: str | None = None) -> str:
    """Etiqueta humana para logs/UI sin exponer el PAN completo."""

    method = (method or "tarjeta").strip().lower()
    if method != "tarjeta":
        return method
    masked = mask_card(card_number)
    return f"tarjeta {masked}" if masked else "tarjeta"
