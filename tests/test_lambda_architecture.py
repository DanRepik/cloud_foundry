from cloud_foundry.pulumi.function import default_lambda_architecture


def test_default_lambda_architecture_stays_x86_for_non_local_arm_host():
    assert default_lambda_architecture(
        stack_name="prod", host_machine="arm64"
    ) == "x86_64"


def test_default_lambda_architecture_uses_arm_for_local_arm_host():
    assert default_lambda_architecture(
        stack_name="local-issue-33", host_machine="arm64"
    ) == "arm64"


def test_default_lambda_architecture_stays_x86_for_local_x86_host():
    assert default_lambda_architecture(
        stack_name="local-issue-33", host_machine="x86_64"
    ) == "x86_64"
