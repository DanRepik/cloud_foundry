from cloud_foundry.pulumi.ui_publisher import UIPublisher


def test_cache_control_for_payload_and_hashed_assets():
    assert (
        UIPublisher.cache_control_for_key("contract/_payload.json")
        == "public, max-age=31536000, immutable"
    )
    assert (
        UIPublisher.cache_control_for_key("_nuxt/app.abc123.js")
        == "public, max-age=31536000, immutable"
    )


def test_cache_control_for_html_and_generic_json():
    assert (
        UIPublisher.cache_control_for_key("contract/index.html")
        == "public, max-age=300, s-maxage=86400, stale-while-revalidate=3600"
    )
    assert (
        UIPublisher.cache_control_for_key("manifest.webmanifest")
        == "public, max-age=3600, stale-while-revalidate=300"
    )
