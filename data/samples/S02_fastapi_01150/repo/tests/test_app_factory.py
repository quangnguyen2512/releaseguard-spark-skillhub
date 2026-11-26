from endpoints.app_factory import create_service_app


def test_create_service_app_lifespan():
    app = create_service_app(lifespan_cm="async_ctx")
    assert app["lifespan"]["mode"] == "lifespan_ctx"
