# Cloud Foundry

Cloud Foundry is a curated collection of components that can be assembled to build cloud-centric applications.

## Set Up

To get started, you can import the package and use it within your Pulumi project. Below is an example demonstrating how to deploy an AWS REST API along with a Lambda function using Cloud Foundry components.

## Hello World Example

The following example deploys an AWS REST API along with a Lambda function that returns a greeting message.

### API Specification

The API_SPEC defines an API, in this case it is a single path operation `/greet`.  This operation accepts an optional query parameter `name` and returns a greeting message. If the `name` parameter is not provided, it defaults to "World."

/explain how cloud the Cloud foundary 

### Lambda Function

The FUNCTION_CODE is Lambda function handler written in Python and handles the `/greet` API request. It takes the `name` from the query string and returns a greeting message in JSON format.

### 1. API Specification

The following OpenAPI specification defines a simple API that exposes a single `GET` endpoint `/greet`. This endpoint accepts an optional query parameter `name` and responds with a greeting message. If no name is provided, it defaults to "World".

```yaml
openapi: 3.0.3
info:
  description: A simple API that returns a greeting message.
  title: Greeting API
  version: 1.0.0
paths:
  /greet:
    get:
      summary: Returns a greeting message.
      description: |
        This endpoint returns a greeting message. It accepts an optional
        query parameter `name`. If `name` is not provided, it defaults to "World".
      parameters:
        - in: query
          name: name
          schema:
            type: string
          description: The name of the person to greet.
          example: John
      responses:
        200:
          description: A greeting message.
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                    description: The greeting message.
                    example: Hello, John!
        400:
          description: Bad Request - Invalid query parameter.
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    description: A description of the error.
                    example: Invalid query parameter
```

### 2. Lambda Function
The Lambda function handles incoming requests to the /greet endpoint. It extracts the name query parameter from the request and returns a JSON response with a greeting message.

```python
import json

def handler(event, context):
    print(f"event: {event}")
    # Extract the 'name' parameter from the query string; default to 'World'
    name = (event.get("queryStringParameters", None) or {}).get("name", "World")
    
    # Return a JSON response with the greeting message
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Hello, {name}!"
        }),
        "headers": {
            "Content-Type": "application/json"
        }
    }
```

### 3. Deploying with Cloud Foundry
With Cloud Foundry, you can define the REST API and the Lambda function in a simple and concise manner. The following code defines the Lambda function and integrates it with the REST API using the API specification from step 1.


```python

import cloud_foundry

# Define the Lambda function using Cloud Foundry's python_function component
greet_function = cloud_foundry.python_function(
    "greet-function",
    handler="app.handler",  # Entry point for the Lambda function
    sources={"app.py": FUNCTION_CODE},  # Lambda function source code
    requirements=[
        "requests==2.27.1",  # Any Python dependencies for the Lambda function
    ],
)

# Define the REST API and integrate it with the Lambda function
rest_api = cloud_foundry.rest_api(
    "greet-api",
    body=API_SPEC,  # OpenAPI spec for the API
    integrations=[{"path": "/greet", "method": "get", "function": greet_function}]
)
```

### 4 Putting It All Together

```python
# __main__.py

import cloud_foundry

# OpenAPI specification for the REST API
API_SPEC = """
openapi: 3.0.3
info:
  description: A simple API that returns a greeting message.
  title: Greeting API
  version: 1.0.0
security:
  - oauth: []
paths:
  /greet:
    get:
      summary: Returns a greeting message.
      description: 'This endpoint returns a greeting message. It accepts an optional
        query parameter `name`. If `name` is not provided, it defaults to "World".'
      parameters:
        - description: The name of the person to greet.
          example: John
          in: query
          name: name
          required: false
          schema:
            type: string
      security:
        -  oauth: []
      responses:
        200:
          content:
            application/json:
              schema:
                properties:
                    message:
                      description: The greeting message.
                      example: Hello, John!
                      type: string
                type: object
          description: A greeting message.
        400:
          content:
            application/json:
              schema:
                properties:
                  error:
                    description: A description of the error.
                    example: Invalid query parameter
                    type: string
                type: object
          description: Bad Request - Invalid query parameter
"""

# Lambda function code
FUNCTION_CODE = """
import json

def handler(event, context):
    name = (event.get("queryStringParameters", None) or {}).get("name", "World")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Hello, {name}!"
        }),
        "headers": {
            "Content-Type": "application/json"
        }
    }
"""

# Define the Lambda function
greet_function = cloud_foundry.python_function(
    "greet-function",
    handler="app.handler",
    sources={"app.py": FUNCTION_CODE},
    requirements=[
        "requests==2.27.1",
    ],
)

# Define the REST API using Cloud Foundry
rest_api = cloud_foundry.rest_api(
    "greet-api",
    body=API_SPEC,
    integrations=[{"path": "/greet", "method": "get", "function": greet_function}]
)
```


**API_SPEC:** This variable contains the OpenAPI specification for the REST API, which defines the /greet endpoint and its parameters and responses.

**FUNCTION_CODE:** The Python code that defines the Lambda function, which processes requests to the /greet endpoint and returns a greeting message.

**greet_function:** This is the Lambda function created using Cloud Foundry's python_function component. It defines the function handler and includes the function source code and dependencies.

**rest_api:** This is the REST API created using Cloud Foundry's rest_api component. It integrates the /greet endpoint with the greet_function Lambda function.
By running this setup, you will deploy a simple REST API on AWS that responds to requests by returning a greeting message.

## Conclusion

Cloud Foundry simplifies the process of deploying cloud-native applications by providing easy-to-use components for defining REST APIs and Lambda functions. This example demonstrates how to deploy a basic API that returns a greeting message using Pulumi and Cloud Foundry.