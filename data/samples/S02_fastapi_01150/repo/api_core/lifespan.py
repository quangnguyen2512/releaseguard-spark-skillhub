def register_lifespan_hooks(lifespan=None):
    if lifespan is None:
        return {"mode": "default", "active": False}
    return {"mode": "lifespan_ctx", "handler": lifespan, "active": True}
