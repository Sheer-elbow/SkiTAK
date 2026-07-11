"""Planned route upload: GPX parsing, PostGIS storage, CoT generation,
and the RabbitMQ broadcast path (against a real broker)."""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

import pytest

from skitak.routes import (
    GpxError,
    broadcast_route_to_teams,
    decimate,
    delete_route,
    get_route,
    parse_gpx,
    route_cot_xml,
    store_route,
)
from skitak.sessions import create_session

GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Col du Test</name><trkseg>
    <trkpt lat="46.00" lon="7.00"><ele>2100</ele></trkpt>
    <trkpt lat="46.01" lon="7.01"><ele>2150.5</ele></trkpt>
    <trkpt lat="46.02" lon="7.02"/>
  </trkseg></trk>
</gpx>"""

GPX_ROUTE_ONLY = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <rte><name>Bridle path</name>
    <rtept lat="51.5" lon="-0.1"/>
    <rtept lat="51.6" lon="-0.2"/>
  </rte>
</gpx>"""


def test_parse_gpx_track():
    name, points = parse_gpx(GPX)
    assert name == "Col du Test"
    assert len(points) == 3
    assert points[0] == (46.0, 7.0, 2100.0)
    assert points[1][2] == 2150.5
    assert points[2][2] is None


def test_parse_gpx_route_points():
    name, points = parse_gpx(GPX_ROUTE_ONLY)
    assert name == "Bridle path"
    assert len(points) == 2


def test_parse_gpx_rejects_garbage():
    with pytest.raises(GpxError):
        parse_gpx(b"not xml")
    with pytest.raises(GpxError):
        parse_gpx(b"<gpx xmlns='http://www.topografix.com/GPX/1/1'></gpx>")
    with pytest.raises(GpxError):
        parse_gpx(b"<notgpx/>")


def test_decimate_keeps_endpoints():
    points = [(float(i), 0.0, None) for i in range(1000)]
    out = decimate(points, limit=50)
    assert len(out) == 50
    assert out[0] == points[0]
    assert out[-1] == points[-1]


def test_store_and_get_route(session):
    sid = uuid.UUID(create_session(session, "S", "hiking", "GUIDE-1"))
    _, points = parse_gpx(GPX)
    store_route(session, sid, "Col du Test", points, uploaded_by="administrator")

    route = get_route(session, sid)
    assert route is not None
    assert route["name"] == "Col du Test"
    assert route["point_count"] == 3
    assert route["points"][0] == {"lat": 46.0, "lon": 7.0}

    # Re-upload replaces (one route per session)
    store_route(session, sid, "Second", points)
    route = get_route(session, sid)
    assert route["name"] == "Second"

    assert delete_route(session, sid) is True
    assert get_route(session, sid) is None


def test_route_cot_is_valid_and_decimated():
    points = [(46.0 + i * 0.001, 7.0, 2000.0) for i in range(500)]
    xml = route_cot_xml("Powder <&> Route", points, route_uid="skitak-route-x")
    event = ET.fromstring(xml)  # must be well-formed despite the hostile name
    assert event.get("type") == "b-m-r"
    links = event.findall("detail/link")
    assert len(links) == 200  # MAX_COT_ROUTE_POINTS
    assert links[0].get("point").startswith("46.0,")
    assert event.find("detail/contact").get("callsign") == "Powder <&> Route"


def test_broadcast_reaches_group_queue():
    """End-to-end against the real broker: a queue bound the way OTS binds
    device queues receives the published route CoT."""
    import json

    import pika

    connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
    channel = connection.channel()
    channel.exchange_declare("groups", durable=True, exchange_type="topic")
    queue = channel.queue_declare("", exclusive=True).method.queue
    channel.queue_bind(queue, exchange="groups", routing_key="skitak-testteam.OUT")

    sent = broadcast_route_to_teams(
        rabbit_host="localhost",
        rabbit_user="guest",
        rabbit_password="guest",
        group_names=["skitak-testteam"],
        cot_xml="<event type='b-m-r'/>",
    )
    assert sent == 1

    method, _, body = channel.basic_get(queue, auto_ack=True)
    assert method is not None, "no message arrived on the group queue"
    payload = json.loads(body)
    assert payload["uid"] == "skitak-server"
    assert "b-m-r" in payload["cot"]
    connection.close()
