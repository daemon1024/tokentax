"""Unit test for the OTel Demo OTLP-JSON loader (synthetic fixture, no live stack)."""

from __future__ import annotations

import json

from tokentax.otel_loader import parse_otlp_jsonl


def _doc(service, sev_num, sev_text, body, trace, attrs):
    return {"resourceLogs": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
        "scopeLogs": [{"logRecords": [{
            "timeUnixNano": "1675079459971622667",
            "severityNumber": sev_num, "severityText": sev_text,
            "body": {"stringValue": body},
            "traceId": trace, "spanId": "04ba577c01a08838",
            "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
        }]}],
    }]}


def test_parse_and_severity_and_attr_fold(tmp_path):
    p = tmp_path / "logs.jsonl"
    p.write_text("\n".join(json.dumps(d) for d in [
        _doc("product-catalog", 17, "ERROR", "failed to retrieve product", "abc123",
             {"demo.product.id": "OLJCESPC7Z", "telemetry.sdk.language": "go"}),
        _doc("cart", 9, "Information", "GetCartAsync called", "def456", {}),  # .NET-style sev text
        _doc("frontend", 0, "", "raw nginx line", "", {}),
    ]))
    recs = parse_otlp_jsonl(p)
    assert len(recs) == 3
    pc = recs[0]
    assert pc.pod == "product-catalog" and pc.level == "ERROR" and pc.is_error
    assert pc.trace_id == "abc123"
    assert "OLJCESPC7Z" in pc.to_plain()              # attribute folded into message
    assert "telemetry.sdk.language" not in pc.to_plain()  # noise attrs dropped
    assert recs[1].level == "INFO"                    # severityNumber 9 -> INFO (not "Information")
    assert recs[2].level == "" and not recs[2].trace_id
