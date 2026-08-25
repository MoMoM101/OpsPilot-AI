import json

import httpx
import pytest

from opspilot_runner.connectors.prometheus import (
    PrometheusConnector,
    PrometheusConnectorError,
)
from opspilot_runner.target_policy import ProbeTargetPolicy


@pytest.mark.asyncio
async def test_prometheus_instant_query_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prometheus/api/v1/query"
        assert request.url.params["query"] == "up"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"__name__": "up", "instance": "api:8000"},
                            "value": [1720000000, "1"],
                        }
                    ],
                },
            },
        )

    connector = PrometheusConnector(
        ProbeTargetPolicy(["localhost"], [9090]),
        transport=httpx.MockTransport(handler),
    )
    result = await connector.execute(
        "prometheus.query",
        {
            "baseUrl": "http://localhost:9090/prometheus",
            "query": "up",
        },
        10,
    )
    payload = json.loads(result.output)

    assert payload["data"]["resultType"] == "vector"
    assert payload["data"]["result"][0]["metric"]["instance"] == "api:8000"
    assert result.truncated is False


@pytest.mark.asyncio
async def test_prometheus_range_query_caps_samples() -> None:
    samples = [[1720000000 + index, str(index)] for index in range(600)]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [{"metric": {"job": "api"}, "values": samples}],
                },
            },
        )

    connector = PrometheusConnector(
        ProbeTargetPolicy(["localhost"], [9090]),
        max_output_bytes=65536,
        transport=httpx.MockTransport(handler),
    )
    result = await connector.execute(
        "prometheus.query_range",
        {
            "baseUrl": "http://localhost:9090",
            "query": "rate(http_requests_total[5m])",
            "start": "2026-08-09T00:00:00Z",
            "end": "2026-08-09T01:00:00Z",
            "stepSeconds": 60,
        },
        10,
    )
    series = json.loads(result.output)["data"]["result"][0]

    assert len(series["values"]) == 500
    assert series["samplesTruncated"] is True
    assert result.truncated is True


def test_prometheus_rejects_unsafe_url_and_excessive_range() -> None:
    connector = PrometheusConnector(ProbeTargetPolicy(["localhost"], [9090]))

    with pytest.raises(PrometheusConnectorError) as unsafe_url:
        connector._validate(
            "prometheus.query",
            {
                "baseUrl": "http://user:pass@localhost:9090",
                "query": "up",
            },
        )
    assert unsafe_url.value.code == "UNSAFE_PROMETHEUS_URL"

    with pytest.raises(PrometheusConnectorError) as excessive_range:
        connector._validate(
            "prometheus.query_range",
            {
                "baseUrl": "http://localhost:9090",
                "query": "up",
                "start": "2026-08-09T00:00:00Z",
                "end": "2026-08-09T07:00:00Z",
                "stepSeconds": 60,
            },
        )
    assert excessive_range.value.code == "INVALID_PROMETHEUS_RANGE"


@pytest.mark.asyncio
async def test_prometheus_rejects_oversized_response() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1048577)

    connector = PrometheusConnector(
        ProbeTargetPolicy(["localhost"], [9090]),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PrometheusConnectorError) as error:
        await connector.execute(
            "prometheus.query",
            {"baseUrl": "http://localhost:9090", "query": "up"},
            10,
        )

    assert error.value.code == "PROMETHEUS_RESPONSE_TOO_LARGE"
