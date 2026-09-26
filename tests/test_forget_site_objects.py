from cloud_foundry.migrations.forget_site_objects import forget_site_objects

STACK = "urn:pulumi:dev::arc-api"
PUBLISHER = f"{STACK}::pulumi:pulumi:Stack$cloud_foundry:pulumi:SiteBucket$cloud_foundry:pulumi:UIPublisher::contract-ui"
OBJECT = f"{STACK}::pulumi:pulumi:Stack$cloud_foundry:pulumi:SiteBucket$cloud_foundry:pulumi:UIPublisher$aws:s3/bucketObjectv2:BucketObjectv2::index.html"
CODE_OBJECT = f"{STACK}::pulumi:pulumi:Stack$cloud_foundry:pulumi:Function$aws:s3/bucketObjectv2:BucketObjectv2::fn-code"
FUNCTION = f"{STACK}::pulumi:pulumi:Stack$cloud_foundry:pulumi:Function$aws:lambda/function:Function::fn"


def test_drops_only_objects_owned_by_a_ui_publisher():
    deployment = {
        "resources": [
            {"urn": PUBLISHER, "type": "cloud_foundry:pulumi:UIPublisher"},
            {"urn": OBJECT, "type": "aws:s3/bucketObjectv2:BucketObjectv2", "parent": PUBLISHER},
            {"urn": CODE_OBJECT, "type": "aws:s3/bucketObjectv2:BucketObjectv2", "parent": "urn:pulumi:dev::arc-api::pulumi:pulumi:Stack$cloud_foundry:pulumi:Function::fn"},
            {"urn": FUNCTION, "type": "aws:lambda/function:Function", "dependencies": [CODE_OBJECT, OBJECT],
             "propertyDependencies": {"s3Key": [CODE_OBJECT, OBJECT]}},
        ]
    }

    migrated, removed = forget_site_objects(deployment)

    assert removed == [OBJECT]
    assert [r["urn"] for r in migrated["resources"]] == [PUBLISHER, CODE_OBJECT, FUNCTION]
    function = migrated["resources"][2]
    assert function["dependencies"] == [CODE_OBJECT]
    assert function["propertyDependencies"] == {"s3Key": [CODE_OBJECT]}
    # the input is left untouched
    assert len(deployment["resources"]) == 4
