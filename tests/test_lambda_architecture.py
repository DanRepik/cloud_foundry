from types import SimpleNamespace

import cloud_foundry.pulumi.function as function_module
from cloud_foundry.pulumi.function import default_lambda_architecture


def test_default_lambda_architecture_stays_x86_for_non_local_arm_host():
    assert default_lambda_architecture(
        stack_name="prod", host_machine="arm64"
    ) == "x86_64"


def test_default_lambda_architecture_stays_x86_for_local_arm_host():
    assert default_lambda_architecture(
        stack_name="local-issue-33", host_machine="arm64"
    ) == "x86_64"


def test_default_lambda_architecture_stays_x86_for_local_x86_host():
    assert default_lambda_architecture(
        stack_name="local-issue-33", host_machine="x86_64"
    ) == "x86_64"


def test_default_lambda_architecture_honors_config_override(monkeypatch):
    monkeypatch.setattr(
        function_module.pulumi,
        "Config",
        lambda: SimpleNamespace(get=lambda key: "arm64" if key == "lambda_architecture" else None),
    )

    assert default_lambda_architecture(
        stack_name="local-issue-33", host_machine="x86_64"
    ) == "arm64"
