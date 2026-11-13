import json
import os
import unittest
from unittest.mock import patch

from db import connection as db_connection
from db.forecasting import fill_monthly_gaps, forecast_demand, forecast_revenue
from db.reports import can_view_reports, normalize_filters
from db.peak_period import aggregate_peak_rows
from db.customer_affinity_report import aggregate_affinity_rows
import ai_service


class UpgradeFeatureTests(unittest.TestCase):
    def test_report_permissions_and_date_validation(self):
        self.assertTrue(can_view_reports({"role": "Admin", "allowed_menus": []}))
        self.assertTrue(can_view_reports({"role": "User", "allowed_menus": ["reports"]}))
        self.assertFalse(can_view_reports({"role": "User", "allowed_menus": []}))
        with self.assertRaises(ValueError):
            normalize_filters({"start_date": "2026-03-02", "end_date": "2026-03-01"})

    def test_forecast_reports_insufficient_history(self):
        result = forecast_demand([{"period": "2026-01", "quantity": 4}])
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["forecast"], [])

    def test_forecast_is_bounded_and_exposes_accuracy(self):
        result = forecast_demand([
            {"period": "2026-01", "quantity": 10},
            {"period": "2026-02", "quantity": 12},
            {"period": "2026-03", "quantity": 14},
        ])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["forecast"][0]["period"], "2026-04")
        self.assertIsNotNone(result["accuracy"])

    def test_fill_monthly_gaps_returns_contiguous_window_and_missing_months(self):
        filled, missing = fill_monthly_gaps([
            {"year_month": "2025-10", "revenue": 100, "invoices": 1},
            {"year_month": "2026-01", "revenue": 400, "invoices": 4},
        ], months=4)
        self.assertEqual([row["year_month"] for row in filled], ["2025-10", "2025-11", "2025-12", "2026-01"])
        self.assertEqual(missing, ["2025-11", "2025-12"])
        self.assertEqual(filled[1]["revenue"], 0.0)
        self.assertTrue(filled[1]["missing"])
        self.assertEqual(filled[3]["revenue"], 400)

    def test_forecast_revenue_uses_revenue_metric(self):
        result = forecast_revenue([
            {"period": "2026-01", "revenue": 100},
            {"period": "2026-02", "revenue": 120},
            {"period": "2026-03", "revenue": 140},
        ])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metric"], "revenue")
        self.assertEqual(result["forecast"][0]["period"], "2026-04")
        self.assertIn("revenue", result["forecast"][0])

    def test_db_timeouts_and_read_only_credentials_are_configurable(self):
        with patch.dict(os.environ, {
            "DB_USER": "app", "DB_PASSWORD": "pw",
            "DB_READONLY_USER": "readonly", "DB_READONLY_PASSWORD": "ropw",
            "DB_CONNECT_TIMEOUT": "2", "DB_READ_TIMEOUT": "7", "DB_WRITE_TIMEOUT": "9",
        }, clear=False), patch.object(db_connection.pymysql, "connect") as connect:
            db_connection.get_connection()
            kwargs = connect.call_args.kwargs
            self.assertEqual(kwargs["user"], "app")
            self.assertEqual(kwargs["connect_timeout"], 2)
            self.assertEqual(kwargs["read_timeout"], 7)
            self.assertEqual(kwargs["write_timeout"], 9)
            with db_connection.read_only_connection_mode():
                db_connection.get_connection()
            readonly_kwargs = connect.call_args.kwargs
            self.assertEqual(readonly_kwargs["user"], "readonly")
            self.assertEqual(readonly_kwargs["password"], "ropw")
        self.assertEqual(db_connection._credentials()[0], os.getenv("DB_USER", "root"))

    def test_ai_context_removes_customer_contacts_and_has_provenance(self):
        self.addCleanup(ai_service._CONTEXT_CACHE.update, data=None, ts=0)
        with patch.object(ai_service.database, "get_dashboard_kpis", return_value={}), \
             patch.object(ai_service.database, "get_monthly_sales_trend", return_value=[
                 {"year_month": "2026-01", "revenue": 100, "invoices": 1}
             ]), \
             patch.object(ai_service.database, "get_top_selling_products", return_value=[]), \
             patch.object(ai_service.database, "get_inventory_summary", return_value=[]), \
             patch.object(ai_service.database, "get_top_customers", return_value=[
                 {"CS_NAME": "Synthetic", "mobile": "01700000000", "address": "Private", "email": "a@example.com"}
             ]), \
             patch.object(ai_service.database, "get_affinity_overview", return_value={}), \
             patch.object(ai_service.database, "get_peak_timing_summary", return_value={
                 "peak_day": {"day_name": "Friday", "invoices": 2, "revenue": 200},
                 "peak_hour": {"hr_label": "10:00", "invoices": 2, "revenue": 200},
                 "peak_month": {"ym": "2026-01", "month_label": "Jan 2026", "invoices": 1, "revenue": 100},
                 "month_distribution": [{"ym": "2026-01"}],
             }):
            ai_service._CONTEXT_CACHE.update(data=None, ts=0)
            context = ai_service.build_business_context()
        self.assertNotIn("mobile", context["top_customers"][0])
        self.assertNotIn("address", context["top_customers"][0])
        self.assertNotIn("email", context["top_customers"][0])
        serialized = ai_service._context_text(context)
        self.assertNotIn("01700000000", serialized)
        self.assertNotIn("Private", serialized)
        self.assertNotIn("a@example.com", serialized)
        self.assertEqual(context["provenance"]["sales_period"]["from"], "2025-02")
        self.assertEqual(context["provenance"]["sales_period"]["to"], "2026-01")
        self.assertEqual(len(context["monthly_sales_trend"]), 12)
        self.assertEqual(len(context["provenance"]["missing_months"]), 11)
        self.assertFalse(context["forecast_readiness"]["sufficient"])
        self.assertTrue(context["peak_period"]["available"])
        metadata = ai_service.context_metadata(context)
        self.assertEqual(metadata["sales_period"]["to"], "2026-01")
        self.assertEqual(metadata["forecast_status"], "insufficient_data")
        self.assertTrue(metadata["forecast_is_directional"])

    def test_prompts_match_available_context(self):
        self.assertIn("12 months", ai_service._FORECAST_PROMPT)
        self.assertNotIn("24", ai_service._FORECAST_PROMPT)
        without_peak = ai_service._insights_prompt({"peak_period": {"available": False}})
        with_peak = ai_service._insights_prompt({"peak_period": {"available": True}})
        self.assertNotIn("Peak", without_peak)
        self.assertIn("Peak-period", with_peak)

    def test_peak_filters_comparisons_returns_and_empty_months(self):
        report = aggregate_peak_rows([
            {"sales_date": "2026-01-05", "product_id": "P1", "category_id": "C1", "product_name": "Printer", "quantity": 3, "unit_price": 100},
            {"sales_date": "2026-01-05", "product_id": "P1", "category_id": "C1", "product_name": "Printer", "quantity": -1, "unit_price": 100},
            {"sales_date": "2026-03-05", "product_id": "P2", "category_id": "C2", "product_name": "Ink", "quantity": 2, "unit_price": 50},
            {"sales_date": None, "product_id": "P1", "category_id": "C1", "quantity": 99, "unit_price": 1},
        ], {"start_date": "2026-01-01", "end_date": "2026-03-31", "product_id": "P1"})
        self.assertEqual([x["period"] for x in report["monthly"]], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(report["monthly"][0]["quantity"], 2)
        self.assertEqual(report["monthly"][0]["sales"], 200)
        self.assertEqual(report["monthly"][1]["quantity"], 0)
        self.assertEqual(report["row_count"], 2)

    def test_peak_export_shape_can_be_written_without_business_data(self):
        from openpyxl import Workbook
        report = aggregate_peak_rows([
            {"sales_date": "2026-01-01", "product_id": "P1", "product_name": "Synthetic", "quantity": 2, "unit_price": 10}
        ], {})
        book = Workbook()
        sheet = book.active
        sheet.append(["Period", "Quantity", "Sales amount"])
        for row in report["monthly"]:
            sheet.append([row["period"], row["quantity"], row["sales"]])
        self.assertEqual(sheet.max_row, 2)

    def test_affinity_filters_calculate_returns_discounts_and_distinct_frequency(self):
        report = aggregate_affinity_rows([
            {"sale_id": "S1", "sales_date": "2026-01-01", "customer_id": "C1", "customer_name": "Acme", "product_id": "P1", "product_name": "Printer", "category_id": "CAT1", "quantity": 2, "unit_price": 100, "discount": 10},
            {"sale_id": "S1", "sales_date": "2026-01-01", "customer_id": "C1", "customer_name": "Acme", "product_id": "P2", "product_name": "Ink", "category_id": "CAT2", "quantity": 1, "unit_price": 50},
            {"sale_id": "S2", "sales_date": "2026-02-01", "customer_id": "C1", "customer_name": "Acme", "product_id": "P1", "product_name": "Printer", "category_id": "CAT1", "quantity": -1, "unit_price": 100},
            {"sale_id": "S3", "sales_date": "2026-02-02", "customer_id": None, "product_id": "P1", "product_name": "Printer", "category_id": "CAT1", "quantity": 1, "unit_price": 100},
        ], {"customer_id": "C1"})
        self.assertEqual(report["summary"]["spending"], 140)
        self.assertEqual(report["customer_view"][0]["purchase_frequency"], 2)
        self.assertEqual(report["summary"]["repeat_customers"], 1)
        self.assertEqual(report["product_view"][0]["quantity"], 1)

    def test_affinity_export_shape_and_permission(self):
        from openpyxl import Workbook
        self.assertFalse(can_view_reports({"role": "User", "allowed_menus": []}))
        report = aggregate_affinity_rows([
            {"sale_id": "S1", "sales_date": "2026-01-01", "customer_id": "C1", "product_id": "P1", "quantity": 1, "unit_price": 25}
        ], {})
        book = Workbook()
        book.active.append(["Customer", "Spending"])
        book.active.append([report["customer_view"][0]["customer_id"], report["customer_view"][0]["spending"]])
        self.assertEqual(book.active.max_row, 2)


class SalesExportValidationTests(unittest.TestCase):
    def assert_invalid_filters_return_422(self, endpoint):
        import main

        message = "End date must be on or after start date."
        with patch.object(main, "_report_access", return_value={"role": "Admin"}), \
             patch.object(main.database, "get_sales_report", side_effect=ValueError(message)):
            response = endpoint(None, start_date="2026-03-02", end_date="2026-03-01")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(json.loads(response.body), {"success": False, "message": message})

    def test_sales_xlsx_returns_422_for_invalid_filters(self):
        import main
        self.assert_invalid_filters_return_422(main.sales_report_xlsx)

    def test_sales_pdf_returns_422_for_invalid_filters(self):
        import main
        self.assert_invalid_filters_return_422(main.sales_report_pdf)


if __name__ == "__main__":
    unittest.main()
