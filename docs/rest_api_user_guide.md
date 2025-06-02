# User Guide: Accelerate Your API Development with the `rest_api` Function

Building and managing APIs can be a time-consuming process, especially when dealing with complex configurations like Lambda integrations, token validation, and CORS. What if you could simplify this process and focus on delivering value faster? Enter the `rest_api` function—a utility designed to streamline the creation of AWS API Gateway REST APIs using Pulumi.

In this guide, we’ll explore how the `rest_api` function enables developers to rapidly build robust APIs with minimal effort, enabling faster development cycles and quicker time-to-market.

---

## Why Use the `rest_api` Function?

The `rest_api` function is a game-changer for developers working with AWS API Gateway. It abstracts away much of the boilerplate and complexity involved in setting up an API Gateway, allowing you to focus on your application services. With just a few lines of code, you can:

- Dynamically build an API Gateway REST API.
- Attach Lambda functions as backend integrations.
- Configure token validation using Lambda functions or Cognito User Pools.
- Enable Cross-Origin Resource Sharing (CORS).
- Optionally enable logging and attach a Web Application Firewall (WAF).

This level of automation and simplicity translates directly into faster development and reliable deployment.


## How It Works

Building an API specification with the `rest_api` function allows you to focus on defining your application's Path operations using the  OpenAPI specification. Once the specification is ready, you then integrate functions with the path operations defined in the API, streamlining the development process.

## Hello World Example

The following example deploys an AWS REST API along with a Lambda function that returns a greeting message. This implementation consists of three parts. The API specification, the Function handler, and the Cloud Foundry deployment code.

### 1. API Specification

The first component required to build a REST API with Cloud Foundry is the API specification. This OpenAPI specification serves as the foundation for the API. When constructing a REST API, integrations with functions are linked to the path operations defined in the API specification. Additionally, authorizer functions can be associated with the API to provide authentication and authorization for these path operations.

In this example the API specification is a single path operation /greet. This operation accepts an optional query parameter name and returns a greeting message. If the name parameter is not provided, it defaults to "World."

```yaml
# api_config.yaml
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

In some cases, you may want to combine multiple OpenAPI specification documents to construct a single API. The `rest_api` function supports this use case by allowing you to supply a list of multiple specifications that are then merged into a unified API definition.

Combining multiple OpenAPI specifications enables modular API design, supporting use cases like microservices, feature modularity, versioning, and third-party integrations for easier management and scalability.


### Step 1: Define Lambda Integrations

Once the API specification is ready, the next step is to define the integrations. In this step, you will implement the services that correspond to the path operations specified in the API definition.

The `rest_api` function exposes only path operations with defined integrations, the resulting API includes only functional endpoints.  This approach allows flexibility during development, as incomplete working versions can be deployed.

Here is the python service code for the greet service.

```python
# app.py
import json

def handler(event, _):
    name = (event.get("queryStringParameters") or {}).get("name", "World")

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

To deploy the code into a functional Lambda service, we will use a `python_function` found in the Cloud Foundry project, that simplifies the deployment of Python Lambda functions.


```python
greet_function = cloud_foundry.python_function( "greet-function", sources={"app.py": "./app.py"})
```

Then when defining  the `rest_api` API paths and methods are associated to Lambda functions.  For example the integration of the `greet_function` would be;

```python
integrations = [
    {
        "path": "/greet",
        "method": "get",
        "function": greet_function,
    }
]
```

This simple configuration tells the API Gateway to route `GET` requests on the `/greet` path to the `greet_lambda` function.

Integrations to existing Lambda functions can be made by supplying the name of an existing function.  This approach allows common functions like log in and log out to be reused between API's leveraging the modularity and flexibility of Lambda functions and API Gateway integrations.

By designing Lambda functions to handle specific tasks, such as logging in or logging out, developers can isolate and reuse these functions across multiple APIs or products without duplicating code. Deploying these functions as standalone services (e.g., `login-function` or `logout-function`) allows them to be integrated into different APIs by simply referencing their names in the `rest_api` configuration. This eliminates the need to redeploy or rewrite functionality for each product.

The `rest_api` function facilitates this by enabling API Gateway to map specific API paths (e.g., `/login`, `/logout`) and HTTP methods (e.g., `POST`, `GET`) to these reusable Lambda functions. This ensures consistent behavior across products while allowing customization of API paths as needed.

Additionally, since these functions are deployed independently, updates to their logic can be made centrally. This ensures that all products using these functions automatically benefit from the changes without requiring individual updates.

By reusing common functionality like authentication, developers can focus on product-specific features. This approach accelerates development and ensures consistency across products, reducing overall development effort.

### Step 3:Create the Deployment Code

With the API specification and Lambda function implementations in place, we can use `rest_api` function to simplify the process of creating an Rest API Gateway. By combining these components, it configures the necessary routes, integrates the specified Lambda functions, and sets up the API Gateway to handle requests. This approach abstracts the complexity of API Gateway configuration, allowing developers to focus on defining application functionality rather than managing infrastructure.

If a hosted zone is available, the `rest_api` function can also create a custom domain name for the gateway. This custom domain name is a subdomain of the hosted zone and can be customized to any valid name. If omitted, the default format is `{project}-{stack name}`.

Using a custom domain name for your API offers several benefits, including improved branding, easier accessibility, and enhanced security. Instead of relying on the default AWS API Gateway domain (e.g., `xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/xxxxxx`), you can map your API to a domain name that aligns with your organization or product. This approach also provides flexibility, allowing the default domain to change without disrupting consuming applications.


```python
# __main__.py

import cloud_foundry

greet_function = cloud_foundry.python_function( "greet-function", sources={"app.py": "./app.py"})

greet_api = cloud_foundry.rest_api(
    "greet-api",
    specification="./api_spec.yaml",
    integrations=[{"path": "/greet", "method": "get", "function": greet_function}],
    hosted_zone_id=os.environ.get("HOSTED_ZONE_ID"),
)
```

### Deploy and Test

With the following files;

* `__main__.py` containing the cloud_foundry deployment code,
* 'app.py' containg the Lambda function code,
* 'api_spec.yaml' containing the OpenAPI specification.

The deployment can be run, creating the Rest API Gateway.

```bash
pulumi up -y
```

Once the deployment is complete, we can use `curl` to access the service.  For example if the domain name associated with the hosted zone was `example.com` and the stack name is `dev` then the `curl` commands would be;

```bash
curl http://greet-api-dev.example.com/greet
# or
curl 'http://greet-api-dev.example.com/greet?name=Dan'
```

If no hosted zone was provided then the API host name must be obtained from the Pulumi stack outputs. There will be a greet-api-host in the stack output.  This output will be in the form xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/greet-api, an can be used as the base URL for accessing the API.  For example `curl` can used to send a requests the service;

```bash
# without parameter
curl https://$(pulumi stack output greet-api-host)/greet
# or with a name parameter.
# Note the quotes to protect the '?' from filename globbing.
curl https://$(pulumi stack output greet-api-host)'/greet?name=Dan'
```

Either way using a custom domain name or the default the examples will produce the following result:

```
{"message": "Hello, World!"}
{"message": "Hello, Dan!"}
```

## Conclusion

The example presented, a "Hello World" API, serves as a simple demonstration of how to use the `rest_api` function to quickly deploy a functional API. While this example focuses on basic functionality, real-world APIs must address critical concerns such as security, ensuring that access is restricted to authorized users. In the next article, we will explore how to implement authentication and authorization mechanisms to secure your APIs effectively.

The `rest_api` function is a powerful tool for developers looking to accelerate their API development process. By simplifying the creation and management of AWS API Gateway REST APIs, it enables you to deliver features faster, with fewer errors and greater scalability.

If you’re building APIs for your applicat, try out the `rest_api`, it might just transform the way you work.
