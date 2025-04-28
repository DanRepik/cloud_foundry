import boto3
import json
from jinja2 import Template
import os
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

ses_client = boto3.client("ses")

MAIL_ORIGIN = os.environ["MAIL_ORIGIN"]


def handler(event, context):
    log.info("Received event: %s", json.dumps(event))
    try:
        responses = []
        for record in event["Records"]:
            if "Sns" in record:
                sns_message = json.loads(record["Sns"]["Message"])
            elif "body" in record:
                sns_message = json.loads(record["body"])
            else:
                raise ValueError("Unsupported message format")
            template_name = sns_message["template_name"]
            context_data = sns_message["context"]
            recipients = sns_message["recipients"]
            subject = sns_message["subject"]
            cc = sns_message.get("cc", [])  # Get CC list, default to an empty list
            bcc = sns_message.get("bcc", [])  # Get BCC list, default to an empty list

            email_body = render_template(template_name, context_data)
            response = send_email(recipients, subject, email_body, cc, bcc)
            responses.append(response)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Emails sent successfully", "responses": responses}
            ),
        }
        template_name = sns_message["template_name"]
        context_data = sns_message["context"]
        recipients = sns_message["recipients"]
        subject = sns_message["subject"]
        cc = sns_message.get("cc", [])  # Get CC list, default to an empty list
        bcc = sns_message.get("bcc", [])  # Get BCC list, default to an empty list

        email_body = render_template(template_name, context_data)
        response = send_email(recipients, subject, email_body, cc, bcc)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Email sent successfully", "response": response}
            ),
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def render_template(template_name, context):
    log.debug(f"Loading template: {template_name}")
    template_path = os.path.join(os.path.dirname(__file__), "templates", template_name)
    with open(template_path, "r") as file:
        template_content = file.read()

    log.debug(
        f"Template content loaded: {template_content[:100]}..."
    )  # Log first 100 characters
    template = Template(template_content)
    rendered_content = template.render(context)
    log.debug(
        f"Rendered template with context: {rendered_content[:100]}..."
    )  # Log first 100 characters

    return rendered_content


def send_email(recipients, subject, body, cc=None, bcc=None):
    # Default CC and BCC to empty lists if not provided
    cc = cc or []
    bcc = bcc or []

    response = ses_client.send_email(
        Source=MAIL_ORIGIN,  # Use the email from the environment variable
        Destination={
            "ToAddresses": recipients,
            "CcAddresses": cc,  # Add CC addresses
            "BccAddresses": bcc,  # Add BCC addresses
        },
        Message={"Subject": {"Data": subject}, "Body": {"Html": {"Data": body}}},
    )
    return response
