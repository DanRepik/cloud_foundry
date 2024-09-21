import pulumi
import pulumi_aws as aws


class GatewayAPI(pulumi.ComponentResource):
    rest_api: aws.apigateway.RestApi

    def __init__(self, name, body: str, opts=None):
        super().__init__("cloud_forge:apigw:RestAPI", name, None, opts)

        self.rest_api = aws.apigateway.RestApi(
            f"{name}-http-api", name=f"{name}-http-api", body=body, opts=opts
        )

    def id(self) -> pulumi.Output[str]:
        return self.rest_api.id
