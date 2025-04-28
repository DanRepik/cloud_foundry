#!/usr/bin/env python3

import boto3
import json
import os

recepient_email = os.environ["RECIPIENT_EMAIL"]
publisher_function = os.environ["PUBLISHER_FUNCTION"]

# Initialize the Lambda client
lambda_client = boto3.client("lambda")

# Define the SNS-structured message
sns_message = {
    "Records": [
        {
            "Sns": {
                "Message": json.dumps(
                    {
                        "template_name": "hello.html",
                        "recipients": [recepient_email],
                        "subject": "Test Email",
                        "context": {"name": "John Doe"},
                    }
                )
            }
        }
    ]
}

# Invoke the Lambda function
response = lambda_client.invoke(
    FunctionName=publisher_function,  # Replace with your Lambda function name
    InvocationType="RequestResponse",  # Use 'Event' for asynchronous invocation
    Payload=json.dumps(sns_message),
)

# Print the response
response_payload = json.loads(response["Payload"].read())
print("Response:", response_payload)
