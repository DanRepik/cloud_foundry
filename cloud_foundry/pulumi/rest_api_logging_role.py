import json
import pulumi
import pulumi_aws as aws


class ApiGatewayLoggingRole(pulumi.ComponentResource):
    def __init__(self, name: str, opts: pulumi.ResourceOptions = None):
        super().__init__("custom:resource:ApiGatewayLoggingRole", name, {}, opts)

        # Define the trust policy for the IAM role
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "apigateway.amazonaws.com"},
                    "Actions": "sts:AssumeRole",
                }
            ],
        }

        # Create the IAM role
        self.api_gateway_role = aws.iam.Role(
            f"{name}-cloudwatch-role",
            assume_role_policy=json.dumps(trust_policy),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Define the permissions policy for the IAM role
        permissions_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Actions": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    "Resources": "*",
                }
            ],
        }

        # Attach the permissions policy to the IAM role
        self.api_gateway_role_policy = aws.iam.RolePolicy(
            f"{name}-cloudwatch-policy",
            role=self.api_gateway_role.id,
            policy=json.dumps(permissions_policy),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Export the IAM role ARN
        self.register_outputs({"api_gateway_role_arn": self.api_gateway_role.arn})
