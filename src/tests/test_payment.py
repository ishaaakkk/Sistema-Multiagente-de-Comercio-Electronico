"""Tests de validacion de tarjeta (ProveedorPagos)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilities.payment import validate_card_payment


class PaymentValidationTests(unittest.TestCase):
    def test_accepts_any_digits(self):
        for card in ("4111111111111111", "1234", "4000000000000002", "4242424242424241", "999"):
            ok, msg = validate_card_payment(card)
            self.assertTrue(ok, f"{card}: {msg}")

    def test_rejects_empty(self):
        ok, msg = validate_card_payment("")
        self.assertFalse(ok)
        self.assertIn("Falta", msg)


if __name__ == "__main__":
    unittest.main()
