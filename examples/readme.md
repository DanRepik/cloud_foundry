# Examples README

This document explains how to run the examples provided in this repository.

## Prerequisites
- AWS account credentials must be configured. You can set them up using the AWS CLI or by exporting the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.
- Python 3.7 or higher installed on your system.
- `pip` package manager installed.

## Steps to Run the Examples

From the folder of the example;

1. **Create a Virtual Environment**
    Run the following command to create a virtual environment:
    ```bash
    python -m venv venv
    ```

2. **Activate the Virtual Environment**
    - On macOS/Linux:
      ```bash
      source venv/bin/activate
      ```
    - On Windows:
      ```bash
      venv\Scripts\activate
      ```

3. **Install Dependencies**
    Use `pip` to install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4. **Create a Stack**
    Run the following command to create a Pulumi stack:

    ```bash
    pulumi stack init
    ```

5. **Deploy the Stack**
    Deploy the stack using the following Pulumi command:
    ```bash
    pulumi up -y
    ```

    > **Note**: Deployment creates AWS resources. To clean up these resources after use, run the following command:
    > ```bash
    > pulumi destroy -y
    > ```
## Additional Notes

- Ensure you have the necessary permissions and access to deploy the stack.
- Refer to the individual example documentation for specific details.

## Available Examples

### Hello Function
The `hello_function` example demonstrates how to deploy a simple AWS Lambda function using Pulumi. This example is ideal for understanding the basics of serverless function deployment.

- **Key Features**:
    - Deploys an AWS Lambda function.
    - The function code is defined inline within the Pulumi program.
    - Outputs a simple "Hello, World!" message.

- **Usage**:
    Follow the steps outlined above to set up and deploy this example.

For more examples, refer to the repository's `examples` directory.

Enjoy exploring the examples!
