"""Unit tests — Metadata Validator"""

import pytest

from app.ingestion.metadata import validate_metadata


def _valid_record(**overrides) -> dict:
    """Return a valid metadata record, optionally overriding fields."""
    record = {
        "domain_id": "ocp_sno_support",
        "title": "SNO Installation Guide",
        "source_uri": "local://docs/sno-install.pdf",
        "product": "OpenShift",
        "ocp_version": "4.16",
        "deployment_type": ["SNO"],
        "document_type": "installation_guide",
        "classification": "public",
        "components": ["bootstrap", "dns"],
    }
    record.update(overrides)
    return record


class TestValidateMetadata:

    def test_valid_record_passes(self):
        result = validate_metadata(_valid_record())
        assert result.valid is True
        assert result.errors == []

    def test_missing_required_field_fails(self):
        for field in ["domain_id", "title", "source_uri", "product",
                      "ocp_version", "deployment_type", "document_type", "classification"]:
            record = _valid_record()
            del record[field]
            result = validate_metadata(record)
            assert result.valid is False, f"Should fail when '{field}' is missing"
            assert any(field in err for err in result.errors)

    def test_invalid_product_fails(self):
        result = validate_metadata(_valid_record(product="WatsonDiscovery"))
        assert result.valid is False
        assert any("product" in err for err in result.errors)

    def test_invalid_ocp_version_fails(self):
        result = validate_metadata(_valid_record(ocp_version="3.11"))
        assert result.valid is False
        assert any("ocp_version" in err for err in result.errors)

    def test_invalid_deployment_type_fails(self):
        result = validate_metadata(_valid_record(deployment_type=["InvalidType"]))
        assert result.valid is False
        assert any("deployment_type" in err for err in result.errors)

    def test_empty_deployment_type_fails(self):
        result = validate_metadata(_valid_record(deployment_type=[]))
        assert result.valid is False

    def test_invalid_document_type_fails(self):
        result = validate_metadata(_valid_record(document_type="blog_post"))
        assert result.valid is False
        assert any("document_type" in err for err in result.errors)

    def test_invalid_classification_fails(self):
        result = validate_metadata(_valid_record(classification="secret"))
        assert result.valid is False
        assert any("classification" in err for err in result.errors)

    def test_valid_access_scope_passes(self):
        result = validate_metadata(_valid_record(access_scope=["public", "isa_technical"]))
        assert result.valid is True

    def test_invalid_access_scope_fails(self):
        result = validate_metadata(_valid_record(access_scope=["unapproved_audience"]))
        assert result.valid is False
        assert any("access_scope" in err for err in result.errors)

    def test_invalid_component_fails(self):
        result = validate_metadata(_valid_record(components=["bootstrap", "ticketing"]))
        assert result.valid is False
        assert any("ticketing" in err for err in result.errors)

    def test_components_optional(self):
        record = _valid_record()
        del record["components"]
        result = validate_metadata(record)
        assert result.valid is True

    def test_ibm_product_catalog_metadata_passes(self):
        result = validate_metadata(_valid_record(
            domain_id="ibm_products",
            product="IBM product catalog",
            product_version="current",
            document_type="product_catalog",
            ocp_version=None,
            deployment_type=[],
            components=[],
        ))
        assert result.valid is True
        assert result.errors == []

    def test_multiple_valid_deployment_types(self):
        result = validate_metadata(_valid_record(deployment_type=["SNO", "standard"]))
        assert result.valid is True

    def test_wrong_domain_id_fails(self):
        result = validate_metadata(_valid_record(domain_id="watson_discovery"))
        assert result.valid is False
        assert any("domain_id" in err for err in result.errors)

    def test_all_valid_ocp_versions_pass(self):
        for version in ["4.14", "4.15", "4.16", "4.17"]:
            result = validate_metadata(_valid_record(ocp_version=version))
            assert result.valid is True, f"Version {version} should be valid"
