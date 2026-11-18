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
    # Errors must reach Lambda: a normal return tells SNS/SQS the message was
    # delivered, so it is deleted instead of retried or sent to the DLQ.
    failures = []
    for record in event["Records"]:
        try:
            send_record(record)
        except Exception:
            if "messageId" not in record:  # SNS or direct invoke: let it retry
                raise
            log.exception("Failed to send SQS message %s", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
    # Read by SQS event source mappings with ReportBatchItemFailures.
    return {"batchItemFailures": failures}


def send_record(record):
    if "Sns" in record:
        message = json.loads(record["Sns"]["Message"])
    elif "body" in record:
        message = json.loads(record["body"])
    else:
        raise ValueError("Unsupported message format")

    email_body = render_template(message["template_name"], message["context"])
    return send_email(
        message["recipients"],
        message["subject"],
        email_body,
        message.get("cc", []),
        message.get("bcc", []),
    )


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
