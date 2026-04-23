from cloud_foundry.pulumi.site_bucket import default_bucket_name, is_production_stack


def test_default_bucket_name_preserves_historical_format(monkeypatch):
    monkeypatch.setattr("pulumi.get_project", lambda: "demo")
    monkeypatch.setattr("pulumi.get_stack", lambda: "dev")

    assert default_bucket_name("frontend") == "demo-dev-frontend"


def test_is_production_stack_matches_prod_names():
    assert is_production_stack("prod") is True
    assert is_production_stack("production") is True
    assert is_production_stack("prod-us-east-1") is True


def test_is_production_stack_rejects_non_prod_names():
    assert is_production_stack("dev") is False
    assert is_production_stack("staging") is False
    assert is_production_stack("local-issue-33") is False
