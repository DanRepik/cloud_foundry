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


def test_main_refuses_a_directory_without_pulumi_yaml(tmp_path, capsys):
    # e.g. `--cwd infra/api` run from inside infra/api already
    from unittest import mock

    from cloud_foundry.migrations import forget_site_objects as migration

    with mock.patch.object(migration, "_pulumi") as pulumi:
        missing = migration.main(["--stack", "dev", "--cwd", str(tmp_path / "infra" / "api")])
        no_project = migration.main(["--stack", "dev", "--cwd", str(tmp_path)])

    assert missing == 2 and no_project == 2
    pulumi.assert_not_called()
    err = capsys.readouterr().err
    assert "does not exist" in err and "has no Pulumi.yaml" in err
    assert "Nothing was changed" in err


def test_main_defaults_to_the_current_directory(tmp_path, monkeypatch):
    from unittest import mock

    from cloud_foundry.migrations import forget_site_objects as migration

    (tmp_path / "Pulumi.yaml").write_text("name: x\nruntime: python\n")
    monkeypatch.chdir(tmp_path)

    def fake_pulumi(args, cwd):
        assert cwd == str(tmp_path)
        if args[:2] == ["stack", "export"]:
            with open(args[args.index("--file") + 1], "w") as f:
                f.write('{"version": 3, "deployment": {"resources": []}}')

    with (
        mock.patch.object(migration, "_pulumi", side_effect=fake_pulumi) as pulumi,
        mock.patch.object(migration.shutil, "which", return_value="/usr/bin/pulumi"),
    ):
        assert migration.main(["--stack", "dev"]) == 0

    assert pulumi.call_args_list[0].args[0][:2] == ["stack", "export"]
    assert len(pulumi.call_args_list) == 1  # nothing to drop, so no import
