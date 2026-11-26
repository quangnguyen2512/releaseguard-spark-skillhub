def dump_audit_record(event_name, iso_timestamp):
    return {"event": event_name, "recorded_at": iso_timestamp}
