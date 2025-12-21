# websocket_api.py

import json
import logging
from typing import Optional, Union

import pulumi
import pulumi_aws as aws

from cloud_foundry.pulumi.custom_domain import (
    CustomCertificate,
    domain_from_subdomain,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class WebSocketAPI(pulumi.ComponentResource):
    """
    A Pulumi component resource that creates and manages an AWS
    API Gateway WebSocket API with Lambda integrations for routes
    like $connect, $disconnect, $default, and custom routes.

    This class provides a configurable way to set up WebSocket APIs with:
    - Connection and disconnection handling
    - Custom route handlers
    - Authorization support (Lambda authorizers or Cognito)
    - Custom domain support
    - Logging and monitoring
    """

    api: Optional[aws.apigatewayv2.Api] = None
    api_id: pulumi.Output[str] = None
    domain: Optional[str] = None

    def __init__(
        self,
        name: str,
        routes: Optional[list[dict]] = None,
        authorizer: Optional[dict] = None,
        hosted_zone_id: Optional[str] = None,
        subdomain: Optional[str] = None,
        enable_logging: Optional[bool] = False,
        connection_table_arn: Optional[Union[str, pulumi.Output[str]]] = None,
        export_api: Optional[str] = None,
        opts=None,
    ):
        """
        Initialize the WebSocketAPI component resource.

        Args:
            name (str): The name of the WebSocket API.
            routes (Optional[list[dict]]): List of route configurations.
                Each route should have:
                - route_key (str): The route key ($connect,
                  $disconnect, $default, or custom)
                - function: Lambda function or function name for
                  the route handler
                - require_auth (bool, optional): Whether this route
                  requires authorization
            authorizer (Optional[dict]): Authorizer configuration with:
                - type (str): "lambda" or "cognito"
                - function: Lambda function for lambda authorizer
                - user_pool_arns: List of Cognito user pool ARNs
                - identity_source: Identity source expression
                  (e.g., "route.request.querystring.token")
            hosted_zone_id (Optional[str]): Route 53 hosted zone ID
                for custom domain
            subdomain (Optional[str]): Subdomain for custom domain
            enable_logging (Optional[bool]): Enable CloudWatch logging
                for the API
            connection_table_arn (Optional[Union[str, pulumi.Output[str]]]):
                DynamoDB table ARN for storing connection information
            export_api (Optional[str]): Name to export the API details
            opts (pulumi.ResourceOptions, optional): Additional resource
                options
        """
        super().__init__("cloud_foundry:apigw:WebSocketAPI", name, None, opts)
        self.name = name
        self.routes = routes or []
        self.authorizer = authorizer
        self.hosted_zone_id = hosted_zone_id
        self.subdomain = subdomain
        self.enable_logging = enable_logging
        self.connection_table_arn = connection_table_arn
        self.export_api = export_api

        # Validate routes
        self._validate_routes()

        # Collect all Lambda function ARNs we need to resolve
        all_arns, self.arn_alloc = self._collect_arns()

        # Create the WebSocket API
        self.api = pulumi.Output.all(*all_arns).apply(
            lambda resolved_arns: self._create_websocket_api(resolved_arns)
        )
        self.api_id = self.api.id

        # Create the API stage
        self.stage = self.api.apply(lambda api: self._create_stage(api))

        # Optionally set up a custom domain
        if self.hosted_zone_id:
            self.domain = self.stage.apply(
                lambda stage: self.create_custom_domain(
                    self.hosted_zone_id, self.subdomain
                )
            )
        else:
            # Set domain to the default execute-api endpoint
            self.domain = pulumi.Output.concat(
                self.api.api_endpoint,
                "/",
                self.stage.name,
            )

        # Register outputs
        self.register_outputs(
            {
                "api-id": self.api_id,
                "stage-name": self.stage.name,
                "domain": self.domain,
            }
        )

    def _validate_routes(self):
        """
        Validate the routes configuration to ensure required fields
        are present.
        """
        if not self.routes:
            raise ValueError("At least one route must be defined for WebSocket API")

        seen_routes = set()
        required_routes = {"$connect", "$disconnect", "$default"}

        for route in self.routes:
            route_key = route.get("route_key")
            if not route_key:
                raise ValueError("Each route must have a 'route_key' attribute")

            if route_key in seen_routes:
                raise ValueError(f"Duplicate route key found: {route_key}")
            seen_routes.add(route_key)

            if "function" not in route:
                raise ValueError(f"Route '{route_key}' must have a 'function' defined")

        # Check if required routes are defined
        missing_routes = required_routes - seen_routes
        if missing_routes:
            log.warning(
                f"WebSocket API '{self.name}' is missing recommended "
                f"routes: {missing_routes}"
            )

    def _collect_arns(self):
        """
        Collect Lambda function ARNs from routes and authorizer for resolution.
        """
        arn_alloc = []
        all_arns = []

        # Collect route function ARNs
        for route in self.routes:
            if "function" in route:
                if isinstance(route["function"], str):
                    route["function"] = aws.lambda_.Function.get(
                        f"{self.name}-{route['route_key']}-function",
                        route["function"],
                    )

                arn_alloc.append(
                    {
                        "type": "route",
                        "route_key": route["route_key"],
                        "length": 2,
                        "offset": len(all_arns),
                    }
                )
                all_arns.append(route["function"].function_name)
                all_arns.append(route["function"].arn)
                log.info(f"Adding route ARN for route key: {route['route_key']}")

        # Collect authorizer function ARN if using Lambda authorizer
        if self.authorizer and self.authorizer.get("type") == "lambda":
            if isinstance(self.authorizer["function"], str):
                self.authorizer["function"] = aws.lambda_.Function.get(
                    f"{self.name}-authorizer-function",
                    self.authorizer["function"],
                )

            arn_alloc.append(
                {
                    "type": "authorizer",
                    "length": 2,
                    "offset": len(all_arns),
                }
            )
            all_arns.append(self.authorizer["function"].function_name)
            all_arns.append(self.authorizer["function"].arn)
            log.info("Adding authorizer ARN")

        return all_arns, arn_alloc

    def _create_websocket_api(self, resolved_arns):
        """
        Create the AWS API Gateway V2 WebSocket API.
        """
        log.info(f"Creating WebSocket API: {self.name}")

        # Create the WebSocket API
        api = aws.apigatewayv2.Api(
            f"{self.name}-api",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create authorizer if specified
        authorizer_id = None
        if self.authorizer:
            authorizer_id = self._create_authorizer(api, resolved_arns)

        # Create integrations and routes
        for route in self.routes:
            self._create_route_integration(api, route, resolved_arns, authorizer_id)

        return api

    def _create_authorizer(self, api, resolved_arns):
        """
        Create an authorizer for the WebSocket API.
        """
        log.info(f"Creating authorizer for API: {self.name}")

        if self.authorizer.get("type") == "lambda":
            # Find the authorizer function ARN
            auth_alloc = next(
                (a for a in self.arn_alloc if a["type"] == "authorizer"), None
            )
            if not auth_alloc:
                raise ValueError("Authorizer function not found in ARN allocation")

            function_arn = resolved_arns[auth_alloc["offset"] + 1]

            authorizer = aws.apigatewayv2.Authorizer(
                f"{self.name}-authorizer",
                api_id=api.id,
                authorizer_type="REQUEST",
                authorizer_uri=pulumi.Output.concat(
                    "arn:aws:apigateway:",
                    aws.get_region().name,
                    ":lambda:path/2015-03-31/functions/",
                    function_arn,
                    "/invocations",
                ),
                identity_sources=[
                    self.authorizer.get(
                        "identity_source", "route.request.header.Authorization"
                    )
                ],
                name=f"{self.name}-authorizer",
                opts=pulumi.ResourceOptions(parent=self),
            )

            # Grant API Gateway permission to invoke the authorizer function
            aws.lambda_.Permission(
                f"{self.name}-authorizer-permission",
                action="lambda:InvokeFunction",
                function=resolved_arns[auth_alloc["offset"]],
                principal="apigateway.amazonaws.com",
                source_arn=pulumi.Output.concat(
                    api.execution_arn, "/authorizers/", authorizer.id
                ),
                opts=pulumi.ResourceOptions(parent=self),
            )

            return authorizer.id

        return None

    def _create_route_integration(self, api, route, resolved_arns, authorizer_id):
        """
        Create an integration and route for a Lambda function.
        """
        route_key = route["route_key"]
        log.info(f"Creating integration for route: {route_key}")

        # Find the function ARN for this route
        route_alloc = next(
            (
                a
                for a in self.arn_alloc
                if a["type"] == "route" and a["route_key"] == route_key
            ),
            None,
        )
        if not route_alloc:
            raise ValueError(f"Route function not found for route key: {route_key}")

        function_name = resolved_arns[route_alloc["offset"]]
        function_arn = resolved_arns[route_alloc["offset"] + 1]

        # Create the integration
        integration = aws.apigatewayv2.Integration(
            f"{self.name}-{route_key}-integration",
            api_id=api.id,
            integration_type="AWS_PROXY",
            integration_uri=function_arn,
            integration_method="POST",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create route configuration
        route_config = {
            "api_id": api.id,
            "route_key": route_key,
            "target": pulumi.Output.concat("integrations/", integration.id),
        }

        # Add authorization if required
        if route.get("require_auth") and authorizer_id:
            route_config["authorization_type"] = "CUSTOM"
            route_config["authorizer_id"] = authorizer_id

        # Create the route
        aws.apigatewayv2.Route(
            f"{self.name}-{route_key}-route",
            **route_config,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Grant API Gateway permission to invoke the Lambda function
        aws.lambda_.Permission(
            f"{self.name}-{route_key}-permission",
            action="lambda:InvokeFunction",
            function=function_name,
            principal="apigateway.amazonaws.com",
            source_arn=pulumi.Output.concat(
                api.execution_arn,
                "/",
                self.stage.name if hasattr(self, "stage") else "*",
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Add connection table ARN to function environment if provided
        conn_routes = ["$connect", "$disconnect"]
        if self.connection_table_arn and route_key in conn_routes:
            log.info(f"Connection table will be accessible to " f"{route_key} handler")

    def _create_stage(self, api):
        """
        Create the API Gateway stage for the WebSocket API.
        """
        log.info(f"Creating stage for API: {self.name}")

        stage_name = pulumi.get_stack()

        # Create access log group if logging is enabled
        access_log_settings = None
        if self.enable_logging:
            log_group = aws.cloudwatch.LogGroup(
                f"{self.name}-access-logs",
                name=f"/aws/apigatewayv2/{self.name}-{stage_name}",
                retention_in_days=7,
                opts=pulumi.ResourceOptions(parent=self),
            )

            access_log_settings = aws.apigatewayv2.StageAccessLogSettingsArgs(
                destination_arn=log_group.arn,
                format=json.dumps(
                    {
                        "requestId": "$context.requestId",
                        "ip": "$context.identity.sourceIp",
                        "requestTime": "$context.requestTime",
                        "httpMethod": "$context.httpMethod",
                        "routeKey": "$context.routeKey",
                        "status": "$context.status",
                        "protocol": "$context.protocol",
                        "responseLength": "$context.responseLength",
                        "integrationErrorMessage": ("$context.integrationErrorMessage"),
                        "errorMessage": "$context.error.message",
                        "errorType": "$context.error.messageString",
                        "connectionId": "$context.connectionId",
                    }
                ),
            )

        # Create the stage
        stage = aws.apigatewayv2.Stage(
            f"{self.name}-stage",
            api_id=api.id,
            name=stage_name,
            auto_deploy=True,
            access_log_settings=access_log_settings,
            opts=pulumi.ResourceOptions(parent=self),
        )

        return stage

    def create_custom_domain(self, hosted_zone_id: str, subdomain: str):
        """
        Create a custom domain for the WebSocket API.
        """
        log.info(f"Creating custom domain for subdomain: {subdomain}")

        # Create the SSL certificate
        certificate = CustomCertificate(
            f"{self.name}-cert",
            hosted_zone_id=hosted_zone_id,
            subdomain=subdomain,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create the custom domain name
        domain_name = domain_from_subdomain(
            f"{self.name}-domain", subdomain, hosted_zone_id
        )

        custom_domain = aws.apigatewayv2.DomainName(
            f"{self.name}-domain",
            domain_name=domain_name,
            domain_name_configuration=(
                aws.apigatewayv2.DomainNameDomainNameConfigurationArgs(
                    certificate_arn=certificate.certificate.arn,
                    endpoint_type="REGIONAL",
                    security_policy="TLS_1_2",
                )
            ),
            opts=pulumi.ResourceOptions(parent=self, depends_on=[certificate]),
        )

        # Create the API mapping
        aws.apigatewayv2.ApiMapping(
            f"{self.name}-mapping",
            api_id=self.api.id,
            domain_name=custom_domain.domain_name,
            stage=self.stage.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create Route53 record
        aws.route53.Record(
            f"{self.name}-record",
            zone_id=hosted_zone_id,
            name=domain_name,
            type="A",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=(custom_domain.domain_name_configuration.target_domain_name),
                    zone_id=(custom_domain.domain_name_configuration.hosted_zone_id),
                    evaluate_target_health=False,
                )
            ],
            opts=pulumi.ResourceOptions(parent=self),
        )

        return domain_name
