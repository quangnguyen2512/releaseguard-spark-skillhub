from validation.serializer import dump_audit_record


def export_invoice_json(invoice_id, created_iso):
    payload = dump_audit_record(f"invoice:{invoice_id}", created_iso)
    return payload
