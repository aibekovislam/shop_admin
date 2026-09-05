from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock, patch

from core.turan_catalog import USED, audit_catalog, fill_web_prices, identity, selling_price, stock_rows


class TuranCatalogTests(TestCase):
    def test_web_fallback_preserves_wholesale_price(self):
        audit = {"items": [
            {"name": "POCO X8 PRO 12/512GB GREEN", "price_status": "matched", "price_kgs": "10000"},
            {"name": "POCO X8 PRO 12/512GB WHITE", "price_status": "needs_research", "price_kgs": None},
        ], "summary": {}}
        filled = fill_web_prices(audit)
        self.assertEqual(filled["items"][0]["price_kgs"], "10000")
        self.assertEqual(filled["items"][1]["price_kgs"], "44880")
        self.assertEqual(filled["summary"]["web"], 1)

    def workbook(self, rows, title="Лист1"):
        sheet = Mock(title=title, values=rows)
        book = Mock()
        book.__iter__ = Mock(return_value=iter([sheet]))
        book.__getitem__ = Mock(return_value=sheet)
        return book

    def test_prices_use_fixed_rate_and_source_markup(self):
        self.assertEqual(selling_price("100", "USD", "wholesale"), Decimal("10120"))
        self.assertEqual(selling_price("100", "USD", "web"), Decimal("9680"))
        self.assertEqual(selling_price("10000", "KGS", "web"), Decimal("11000"))
        for value in ("NaN", "Infinity", "-1", "0"):
            with self.assertRaises(ValueError):
                selling_price(value, "USD", "web")

    def test_used_variants_and_different_models(self):
        for name in ("iPhone б/у", "iPhone Б.У.", "Mac B/U", "Watch Б\\У", "iPad бу", "Phone DAMAGED"):
            self.assertTrue(USED.search(name), name)
        self.assertNotEqual(identity("POCO X8 PRO 8/512 BLACK"), identity("POCO X8 PRO 12/512 BLACK"))
        self.assertNotEqual(identity("iPhone 17 Pro 256 HK"), identity("iPhone 17 Pro 256 JA"))
        self.assertEqual(identity("Air Pods 4 ANC"), identity("AIRPODS 4 - ACTIVE NOISE CANCELLATION (MXP93)"))

    def test_stock_section_boundaries(self):
        book = self.workbook([
            ("SHAT MOBILE", 20), ("Other product", 20), ("Итого", 20),
            ("WEBSITE TURAN", 3), ("Product", 3), ("Итого", 3), ("G17 NEW", 100),
        ])
        with patch("core.turan_catalog.load_workbook", return_value=book):
            self.assertEqual(stock_rows("stock.xlsx"), [{"row": 5, "name": "Product", "quantity": 3}])
        book.close.assert_called_once()

    def test_inconsistent_total_rejected(self):
        book = self.workbook([("WEBSITE TURAN", 3), ("Product", 2), ("Итого", 3)])
        with patch("core.turan_catalog.load_workbook", return_value=book):
            with self.assertRaises(ValueError):
                stock_rows("stock.xlsx")

    def test_turan_prices_preferred_and_conflicts_not_guessed(self):
        book = self.workbook([
            ("Product", 1, 200), ("Conflict", 1, 100), ("Conflict", 1, 120),
            ("WEBSITE TURAN", "Кол-во", "Цена"), ("Product", 2, "150,00"), ("Итого", 2, 300),
        ])
        stocks = [{"row": i, "name": name, "quantity": 1} for i, name in enumerate(
            ["Product", "Conflict", "Missing", "Used Б.У"], 1
        )]
        with patch("core.turan_catalog.load_workbook", return_value=book), patch("core.turan_catalog.stock_rows", return_value=stocks):
            result = audit_catalog("stock.xlsx", "prices.xlsx")
        self.assertEqual(result["items"][0]["price_kgs"], "15180")
        self.assertEqual(result["items"][1]["price_status"], "conflicting_wholesale")
        self.assertEqual(result["items"][2]["price_status"], "needs_research")
        self.assertEqual(result["summary"]["excluded"], 1)
