from billing.invoice_exporter import export_invoice_json


def test_export_invoice_json_preserves_tz():
    out = export_invoice_json("INV-9", "2026-11-20T08:00:00+00:00")
    assert out["recorded_at"].endswith("+00:00")
