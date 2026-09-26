"""One-time state migration for the single-resource UIPublisher.

UIPublisher used to declare one aws.s3.BucketObjectv2 per site file. It now
publishes the whole build through one resource. Deploying the new version
straight over old state would be destructive: Pulumi runs the new resource's
upload first and deletes the no-longer-declared per-file resources last, and
deleting those removes the very S3 objects that were just uploaded (same
keys), leaving the site empty.

Run this once per stack, right before the first `pulumi up` with the new
cloud_foundry. It removes the per-file resources from the Pulumi state only;
the S3 objects stay where they are, and the next deploy takes them over.

    python -m cloud_foundry.migrations.forget_site_objects --stack dev [--cwd <project dir>] [--dry-run]

--cwd is the Pulumi project directory (the one holding Pulumi.yaml),
relative to where you run the command; it defaults to the current directory.

The exported state is saved next to the working directory first, so
`pulumi stack import --file <backup>` puts it back if needed.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PUBLISHER_TYPE = "cloud_foundry:pulumi:UIPublisher"
OBJECT_TYPE = "aws:s3/bucketObjectv2:BucketObjectv2"


def _urn_type(urn: str) -> str:
    # urn:pulumi:<stack>::<project>::<parent types$...$type>::<name>
    parts = urn.split("::", 3)
    return parts[2].split("$")[-1] if len(parts) == 4 else ""


def forget_site_objects(deployment: dict) -> tuple[dict, list[str]]:
    """Return ``deployment`` without the per-file objects that UIPublisher
    components used to own, and the URNs that were removed."""
    resources = deployment.get("resources") or []
    removed = {
        resource["urn"]
        for resource in resources
        if resource.get("type") == OBJECT_TYPE
        and _urn_type(resource.get("parent", "")) == PUBLISHER_TYPE
    }

    kept = []
    for resource in resources:
        if resource["urn"] in removed:
            continue
        resource = dict(resource)
        if resource.get("dependencies"):
            resource["dependencies"] = [u for u in resource["dependencies"] if u not in removed]
        if resource.get("propertyDependencies"):
            resource["propertyDependencies"] = {
                name: [u for u in urns if u not in removed]
                for name, urns in resource["propertyDependencies"].items()
            }
        if resource.get("deletedWith") in removed:
            resource.pop("deletedWith")
        kept.append(resource)

    return {**deployment, "resources": kept}, sorted(removed)


def _pulumi(args: list[str], cwd: str) -> None:
    subprocess.run(["pulumi", *args], cwd=cwd, check=True)


def _project_problem(cwd: str) -> str | None:
    """Why ``cwd`` can't be used as the Pulumi project directory, if it can't."""
    if not os.path.isdir(cwd):
        return f"{cwd} does not exist"
    if not any(os.path.isfile(os.path.join(cwd, name)) for name in ("Pulumi.yaml", "Pulumi.yml")):
        return f"{cwd} has no Pulumi.yaml"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stack", required=True)
    parser.add_argument(
        "--cwd",
        default=".",
        help="Pulumi project directory, relative to where you run this (default: current directory)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)

    cwd = os.path.abspath(args.cwd)
    problem = _project_problem(cwd)
    if problem:
        print(
            f"{problem}. --cwd must be the Pulumi project directory, relative to "
            f"where you run this command (it defaults to the current directory). "
            f"Nothing was changed.",
            file=sys.stderr,
        )
        return 2
    if shutil.which("pulumi") is None:
        print("The pulumi CLI is not on PATH. Nothing was changed.", file=sys.stderr)
        return 2
    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup = os.path.join(cwd, f"{args.stack}-state-backup-{stamp}.json")
    _pulumi(["stack", "export", "--stack", args.stack, "--file", backup], cwd)

    with open(backup) as f:
        state = json.load(f)
    deployment = state.get("deployment") or {}
    if deployment.get("pending_operations"):
        print(
            "State has pending operations from an interrupted update; resolve those "
            "(pulumi refresh / pulumi cancel) before migrating.",
            file=sys.stderr,
        )
        return 1

    migrated, removed = forget_site_objects(deployment)
    print(f"{len(removed)} per-file site object(s) to drop from the {args.stack} state (S3 is not touched).")
    if not removed or args.dry_run:
        print(f"State export kept at {backup}")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as out:
        json.dump({**state, "deployment": migrated}, out)
    try:
        _pulumi(["stack", "import", "--stack", args.stack, "--file", out.name], cwd)
    finally:
        os.unlink(out.name)
    print(f"Done. Previous state saved to {backup}; restore it with: pulumi stack import --stack {args.stack} --file {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
