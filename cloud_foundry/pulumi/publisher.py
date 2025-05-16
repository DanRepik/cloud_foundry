import pulumi
import pulumi_aws as aws


class Publisher(pulumi.ComponentResource):
    def __init__(
        self, name: str, subscriptions: list[dict], opts: pulumi.ResourceOptions = None
    ):
        """
        :param name: The name of the SNS Topic.
        :param subscriptions: A list of dictionaries, where each dictionary contains:
                              - 'function': The ARN of the Lambda function to subscribe.
                              - 'filter': (Optional) A filter policy for the subscription.
        :param opts: Pulumi resource options.
        """
        super().__init__("cloud_foundry:messaging:Publisher", name, {}, opts)

        # Create an SNS Topic
        self.topic = aws.sns.Topic(
            resource_name=f"{name}-sns-topic", opts=pulumi.ResourceOptions(parent=self)
        )
        # Create subscriptions for the SNS Topic
        # Correctly handle Pulumi Output objects for function ARNs
        self.function_arns = {
            subscription["function"]: subscription.get("filter")
            for subscription in subscriptions
        }

        def create_subscriptions(function_to_filter):
            subscriptions = []
            for index, (function, filter_policy) in enumerate(
                function_to_filter.items()
            ):
                sns_subscription = aws.sns.TopicSubscription(
                    resource_name=f"{name}-subscription-{index}",
                    topic=self.topic.arn,
                    protocol="lambda",
                    endpoint=function.arn,  # Resolve the Pulumi Output here
                    filter_policy=filter_policy,
                    opts=pulumi.ResourceOptions(parent=self.topic),
                )
                subscriptions.append(sns_subscription)

                # Add permission for SNS to invoke the Lambda function
                aws.lambda_.Permission(
                    resource_name=f"{name}-permission-{index}",
                    action="lambda:InvokeFunction",
                    function=function.arn,  # Resolve the Pulumi Output here
                    principal="sns.amazonaws.com",
                    source_arn=self.topic.arn,
                    opts=pulumi.ResourceOptions(parent=self.topic),
                )
            return subscriptions

        # Pass the function-to-filter mapping to the subscription creation function
        self.subscriptions = create_subscriptions(self.function_arns)

        # Register the outputs
        self.register_outputs(
            {
                "topic_arn": self.topic.arn,
                "topic_name": self.topic.name,
            }
        )


def publisher(
    name: str, subscriptions: list[dict], opts: pulumi.ResourceOptions = None
) -> Publisher:
    """
    Create an SNS Publisher with the specified subscriptions.

    :param name: The name of the SNS Topic.
    :param subscriptions: A list of dictionaries, where each dictionary contains:
                          - 'function': The ARN of the Lambda function to subscribe.
                          - 'filter': (Optional) A filter policy for the subscription.
    :param opts: Pulumi resource options.
    :return: An instance of Publisher.
    """
    return Publisher(name, subscriptions, opts)
