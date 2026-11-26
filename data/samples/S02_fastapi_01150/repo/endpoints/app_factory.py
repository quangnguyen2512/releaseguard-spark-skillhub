from api_core.lifespan import register_lifespan_hooks


def create_service_app(lifespan_cm=None):
    hooks = register_lifespan_hooks(lifespan=lifespan_cm)
    return {"service": "catalog-api", "lifespan": hooks}
