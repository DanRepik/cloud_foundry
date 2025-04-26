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
            cc = sns_message.get("cc", [])
            bcc = sns_message.get("bcc", [])

            email_body = render_template(template_name, context_data)
            response = send_email(recipients, subject, email_body, cc, bcc)
            responses.append(response)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Emails sent successfully", "responses": responses}
            ),
        }

    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def render_template(template_name, context):
    log.info(f"Loading template: {template_name}")
    template_path = os.path.join(os.path.dirname(__file__), "templates", template_name)
    with open(template_path, "r") as file:
        template_content = file.read()

    template = Template(template_content)
    return template.render(context)


def send_email(recipients, subject, body, cc, bcc):
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
