import pulumi
import pulumi_aws as aws


class GatewayAPI(pulumi.ComponentResource):
    rest_api: aws.apigateway.RestApi

    def __init__(self, name, body: str, opts=None):
        super().__init__("cloud_forge:apigw:RestAPI", name, None, opts)

        self.rest_api = aws.apigateway.RestApi(
            f"{name}-http-api",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}-rest-api",
            body=body,
            opts=pulumi.ResourceOptions(parent=self),
        )

        deployment = aws.apigateway.Deployment(
            f"{name}-deployment",
            rest_api=self.rest_api.id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        aws.apigateway.Stage(
            f"{name}-stage",
            rest_api=self.rest_api.id,
            deployment=deployment.id,
            stage_name=name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        pulumi.export(f"{name}-id", self.rest_api.id)
        self.register_outputs({
            "id": self.rest_api.id
        })

    def id(self) -> pulumi.Output[str]:
        return self.rest_api.id


def rest_api(name: str, body: str):
    rest_api = GatewayAPI(name, body)
