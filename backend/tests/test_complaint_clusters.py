from types import SimpleNamespace

from app.services.complaint_clusters import build_complaint_clusters, urgency_rank


def _complaint(cid: int, lat: float, lng: float, address: str, status: str = "REGISTERED"):
    return SimpleNamespace(
        id=cid,
        lat=lat,
        long=lng,
        address=address,
        status=status,
        service_request_id=f"TLP-2026-{cid:06d}",
        requested_datetime=None,
        tier="GENERAL_MAINTENANCE_REQUEST",
    )


def test_clusters_nearby_complaints_grouped():
    rows = [
        _complaint(1, 43.22108, 76.89002, "ул. Басенова, Алматы"),
        _complaint(2, 43.22129, 76.89047, "ул. Басенова, Алматы"),
        _complaint(3, 43.29673, 76.99433, "пр. Рыскулова, Алматы"),
    ]
    clusters = build_complaint_clusters(rows)
    assert clusters[1].reports_at_location == 2
    assert clusters[2].reports_at_location == 2
    assert clusters[3].reports_at_location == 1
    assert "Басенова" in clusters[1].cluster_label


def test_urgency_rank_prefers_mass_reports():
    assert urgency_rank(10, "GENERAL_MAINTENANCE_REQUEST") > urgency_rank(1, "HAZARD_FASTTRACK")
