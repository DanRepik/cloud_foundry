from types import SimpleNamespace

import cloud_foundry.utils.names as names_module
from cloud_foundry.utils.names import project_slug, resource_id


def _patch_config(monkeypatch, values: dict):
    monkeypatch.setattr(
        names_module.pulumi,
        "Config",
        lambda: SimpleNamespace(get=lambda key: values.get(key)),
    )


def _clear_env(monkeypatch):
    monkeypatch.delenv("CLOUD_FOUNDRY_PROJECT_SLUG", raising=False)


def test_project_slug_defaults_to_pulumi_project_name(monkeypatch):
    _clear_env(monkeypatch)
    _patch_config(monkeypatch, {})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")

    assert project_slug() == "civarai-evidence"


def test_project_slug_uses_configured_override(monkeypatch):
    _clear_env(monkeypatch)
    _patch_config(monkeypatch, {"project_slug": "cep"})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")

    assert project_slug() == "cep"


def test_project_slug_ignores_blank_config_override(monkeypatch):
    _clear_env(monkeypatch)
    _patch_config(monkeypatch, {"project_slug": "   "})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")

    assert project_slug() == "civarai-evidence"


def test_project_slug_uses_env_var_override(monkeypatch):
    monkeypatch.setenv("CLOUD_FOUNDRY_PROJECT_SLUG", "cep")
    _patch_config(monkeypatch, {})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")

    assert project_slug() == "cep"


def test_project_slug_env_var_takes_precedence_over_config(monkeypatch):
    monkeypatch.setenv("CLOUD_FOUNDRY_PROJECT_SLUG", "env-slug")
    _patch_config(monkeypatch, {"project_slug": "config-slug"})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")

    assert project_slug() == "env-slug"


def test_project_slug_ignores_blank_env_var(monkeypatch):
    monkeypatch.setenv("CLOUD_FOUNDRY_PROJECT_SLUG", "   ")
    _patch_config(monkeypatch, {"project_slug": "config-slug"})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")

    assert project_slug() == "config-slug"


def test_resource_id_uses_project_slug(monkeypatch):
    _clear_env(monkeypatch)
    _patch_config(monkeypatch, {"project_slug": "cep"})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")
    monkeypatch.setattr(names_module.pulumi, "get_stack", lambda: "dev")

    assert resource_id("ingestion-events") == "cep-dev-ingestion-events"


def test_resource_id_falls_back_to_project_name_without_slug(monkeypatch):
    _clear_env(monkeypatch)
    _patch_config(monkeypatch, {})
    monkeypatch.setattr(names_module.pulumi, "get_project", lambda: "civarai-evidence")
    monkeypatch.setattr(names_module.pulumi, "get_stack", lambda: "dev")

    assert resource_id("ingestion-events") == "civarai-evidence-dev-ingestion-events"


def test_resource_id_without_name_returns_project_stack(monkeypatch):
    _clear_env(monkeypatch)
    _patch_config(monkeypatch, {"project_slug": "cep"})
    monkeypatch.setattr(names_module.pulumi, "get_stack", lambda: "dev")

    assert resource_id() == "cep-dev"
