import unittest

from services.review_score_service import ReviewScoreService


class ReviewScoreServiceTests(unittest.TestCase):
    def test_compute_review_marks_complete_low_risk_receipt_ready_to_approve(self):
        service = ReviewScoreService()

        review = service.compute_review(
            {
                "document_type": "receipt",
                "classification_confidence": 0.98,
                "is_document": True,
                "merchant": "Hotel Central",
                "date": "2026-04-17",
                "total": 45000,
                "currency": "CLP",
                "category": "Lodging",
                "country": "Chile",
                "case_id": "CASE-1",
                "ocr_text": "FACTURA HOTEL CENTRAL FECHA 2026-04-17 RUT 76.123.456-7 IVA TOTAL 45000 " * 5,
            },
            existing_expenses=[],
        )

        self.assertGreaterEqual(review["review_score"], 90)
        self.assertEqual(review["review_status"], "ready_to_approve")
        self.assertEqual(review["review_flags"], [])

    def test_compute_review_flags_exact_duplicate(self):
        service = ReviewScoreService()

        review = service.compute_review(
            {
                "document_type": "receipt",
                "classification_confidence": 0.95,
                "is_document": True,
                "merchant": "Cafe Demo",
                "date": "2026-04-17",
                "total": 12000,
                "currency": "CLP",
                "category": "Meals",
                "country": "Chile",
                "case_id": "CASE-1",
                "ocr_text": "CAFE DEMO FECHA RUT TOTAL IVA " * 8,
            },
            existing_expenses=[
                {
                    "merchant": "Cafe Demo",
                    "date": "2026-04-17",
                    "total": 12000,
                }
            ],
        )

        self.assertIn("Posible duplicado", review["review_flags"])
        self.assertNotEqual(review["review_status"], "ready_to_approve")


if __name__ == "__main__":
    unittest.main()
