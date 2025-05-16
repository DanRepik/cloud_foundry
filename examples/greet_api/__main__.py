# __main__.py

import os
import cloud_foundry

greet_function = cloud_foundry.python_function(
    "greet-function", sources={"app.py": "./app.py"}
)

greet_api = cloud_foundry.rest_api(
    "greet-api",
    specification="./api_spec.yaml",
    integrations=[{"path": "/greet", "method": "get", "function": greet_function}],
    hosted_zone_id=os.environ.get("HOSTED_ZONE_ID"),
)
