#!/usr/bin/env python3
import subprocess
import json
import requests
import sys


def get_pulumi_stack_output(stack_name):
    """
    Gets the output of a Pulumi stack using the command line.

    Args:
        stack_name (str): The name of the Pulumi stack.

    Returns:
        dict: The output of the Pulumi stack as a dictionary.
    """
    try:
        result = subprocess.run(
            ["pulumi", "stack", "output", "--stack", stack_name, "--json"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error executing Pulumi command: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON output: {e}")
        return None


def request_greet_service(api_url, name=None):
    """
    Sends a request to the greet service.

    Args:
        api_url (str): The URL of the greet service.
        name (str, optional): The name to greet. Defaults to None.

    Returns:
        dict: The response from the greet service as a dictionary.
    """
    try:
        params = {"name": name} if name else {}
        response = requests.get(f"https://{api_url}/greet", params=params)
        print(f"Request sent: {response.request.method} {response.request.url}")
        print(f"Headers: {response.request.headers}")
        if response.request.body:
            print(f"Body: {response.request.body}")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error making request to greet service: {e}")
        return None


stack_output = get_pulumi_stack_output("dev")
print(f"Stack output: {stack_output}")
if not stack_output:
    print("Failed to retrieve stack output.")


# Check if a name is provided as a command-line argument
name = sys.argv[1] if len(sys.argv) > 1 else None

api_host = stack_output.get("greet-api-host")

print(f"{request_greet_service(api_host, name)}")
