import pytest
import logging
from cloud_foundry import is_localstack_deployment

log = logging.Logger(__name__)

api_id: str = None


@pytest.fixture
def gateway_endpoint():
    global api_id
    if not api_id:
        from pulumi import automation as auto

        stack = auto.select_stack(
            stack_name="local",
            work_dir="infra",
        )

        stack.refresh(on_output=print)
        outputs = stack.outputs()
        log.info(f"outputs: {outputs}")

        api_id = outputs["test-api-id"].value if "test-api-id" in outputs else None
        host = (
            "execute-api.localhost.localstack.cloud"
            if is_localstack_deployment()
            else "execute-api.us-east-1.amazonaws.com"
        )
    return f"http://{api_id}.{host}:4566/test-api"
