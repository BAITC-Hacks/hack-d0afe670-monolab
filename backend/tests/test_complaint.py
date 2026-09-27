from app.models.schemas import ComplaintGenerateRequest, ContractInfo, DefectInfo, GpsCoords
from app.services.complaint import generate_complaint


def test_generate_complaint_example_payload():
    body = ComplaintGenerateRequest(
        defect_info=DefectInfo(
            address_description="г. Алматы, пр. Абая, напротив дома 150",
            gps=GpsCoords(lat=43.2389, lng=76.8897),
            defect_type="Глубокая выбоина асфальтобетонного покрытия (яма)",
            photo_urls=["https://storage.e-jol.kz/defects/123_1.jpg"],
        ),
        contract_info=ContractInfo(
            contract_number="010340004562/2024-1",
            contract_date="15.05.2024",
            customer_name="Управление городской мобильности города Алматы",
            supplier_name="ТОО 'КазДоравто'",
            supplier_bin="180440023910",
            warranty_ends="15.05.2027",
            warranty_active=True,
        ),
    )
    result = generate_complaint(body)

    assert len(result.subject) <= 100
    assert "Управление городской мобильности" in result.target_department
    assert "ЗАЯВЛЕНИЕ" in result.document_body
    assert "010340004562/2024-1" in result.document_body
    assert "КазДоравто" in result.document_body
    assert "АППК РК" in result.document_body
    assert "ст. 43" in result.document_body
    assert "10 (десяти) календарных дней" in result.document_body
    assert "43.238900, 76.889700" in result.document_body


def test_generate_general_complaint_without_contract():
    body = ComplaintGenerateRequest(
        complaint_mode="general",
        defect_info=DefectInfo(
            address_description="г. Алматы, ул. Тестовая",
            gps=GpsCoords(lat=43.24, lng=76.91),
            defect_type="pothole",
        ),
    )
    result = generate_complaint(body)

    assert "активный гарантийный договор подрядчика не найден" in result.document_body
    assert "010340004562" not in result.document_body
