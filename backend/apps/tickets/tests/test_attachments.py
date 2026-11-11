import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.tickets.models import TicketAttachment

pytestmark = pytest.mark.django_db

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64


def upload(client, ticket_id, name, content, visibility="public"):
    return client.post(
        f"/api/v1/tickets/{ticket_id}/attachments/",
        {"file": SimpleUploadedFile(name, content), "visibility": visibility},
        format="multipart",
    )


def test_upload_and_download_image(create_ticket, client_for, agent):
    ticket = create_ticket()
    client = client_for(agent)
    r = upload(client, ticket["id"], "photo.PNG", PNG)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["content_type"] == "image/png"
    assert body["original_name"] == "photo.PNG"
    assert len(body["sha256"]) == 64

    stored = TicketAttachment.objects.get(pk=body["id"])
    assert "photo" not in stored.file.name  # random storage name

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == PNG
    assert download["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in download["Content-Disposition"]
    assert "inline" in client.get(body["download_url"] + "?inline=1")["Content-Disposition"]


def test_pdf_is_never_served_inline(create_ticket, client_for, agent):
    ticket = create_ticket()
    client = client_for(agent)
    body = upload(client, ticket["id"], "report.pdf", PDF).json()
    assert "attachment" in client.get(body["download_url"] + "?inline=1")["Content-Disposition"]


@pytest.mark.parametrize(
    "name,content,message",
    [
        ("invoice.pdf", ELF, "does not match"),  # executable disguised as a PDF
        ("script.sh", b"#!/bin/sh\necho hi", "not allowed"),
        ("page.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "not allowed"),  # SVG can carry scripts
        ("empty.png", b"", "empty"),
    ],
)
def test_rejects_unsafe_uploads(create_ticket, client_for, agent, name, content, message):
    ticket = create_ticket()
    r = upload(client_for(agent), ticket["id"], name, content)
    assert r.status_code == 400
    assert message in str(r.json()["error"]["details"]).lower()
    assert not TicketAttachment.objects.exists()


def test_rejects_oversized_upload(create_ticket, client_for, agent, settings):
    settings.MAX_UPLOAD_SIZE_MB = 0  # anything non-empty is too big
    ticket = create_ticket()
    r = upload(client_for(agent), ticket["id"], "photo.png", PNG)
    assert r.status_code == 400
    assert "MB" in str(r.json()["error"]["details"])


def test_internal_attachments_hidden_from_customers(create_ticket, client_for, agent, portal_user):
    ticket = create_ticket()
    staff = client_for(agent)
    internal = upload(staff, ticket["id"], "notes.pdf", PDF, visibility="internal").json()
    public = upload(staff, ticket["id"], "photo.png", PNG).json()

    cust = client_for(portal_user)
    visible = [a["id"] for a in cust.get(f"/api/v1/tickets/{ticket['id']}/attachments/").json()]
    assert visible == [public["id"]]
    assert cust.get(internal["download_url"]).status_code == 404
    assert cust.get(public["download_url"]).status_code == 200
    assert upload(cust, ticket["id"], "x.png", PNG, visibility="internal").status_code == 403


def test_attachment_download_isolated_between_orgs(create_ticket, client_for, agent, other_org, make_member):
    from apps.organizations.catalog import RoleCode

    ticket = create_ticket()
    body = upload(client_for(agent), ticket["id"], "photo.png", PNG).json()
    outsider = make_member(other_org, RoleCode.ORG_ADMIN)
    assert client_for(outsider).get(body["download_url"]).status_code == 404
