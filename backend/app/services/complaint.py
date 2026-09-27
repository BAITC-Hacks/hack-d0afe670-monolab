from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from app.models.schemas import (
    ComplaintGenerateRequest,
    ComplaintGenerateResponse,
    ContractInfo,
    DefectInfo,
    UserInfo,
)

_DISTRICT_RE = re.compile(
    r"(алмалинск|бостандык|медеу|турксиб|наурызбай|жетысу|ауэзов|алатау)",
    re.IGNORECASE,
)

_DEFECT_LABELS = {
    "pothole": "Глубокая выбоина асфальтобетонного покрытия (яма)",
    "manhole": "Открытый или повреждённый люк колодца",
    "crack": "Трещина асфальтобетонного покрытия",
    "marking": "Стертая или отсутствующая дорожная разметка",
    "subsidence": "Просадка дорожного покрытия / колодца",
}

_SEVERITY_NOTES = {
    "low": "Дефект заметен, но не создаёт немедленной угрозы.",
    "medium": "Дефект существенно ухудшает проходимость участка.",
    "high": "Дефект создаёт прямую угрозу безопасности дорожного движения и сохранности имущества граждан.",
    "critical": (
        "Дефект создаёт непосредственную угрозу жизни и здоровью участников дорожного движения "
        "и требует немедленного реагирования."
    ),
}


def _fmt_date(value: str | date | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    raw = str(value).strip()
    if not raw:
        return "—"
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return raw


def _placeholder_user(user: Optional[UserInfo]) -> tuple[str, str, str]:
    if user is None:
        return ("___________________________", "____________", "+7 (___) ___-__-__")
    return (
        (user.name or "").strip() or "___________________________",
        (user.iin or "").strip() or "____________",
        (user.phone or "").strip() or "+7 (___) ___-__-__",
    )


def _defect_description(defect: DefectInfo) -> str:
    if defect.defect_type and defect.defect_type not in _DEFECT_LABELS:
        return defect.defect_type.strip()
    key = (defect.defect_type or "pothole").lower()
    return _DEFECT_LABELS.get(key, _DEFECT_LABELS["pothole"])


def _severity_sentence(severity: Optional[str]) -> str:
    if not severity:
        return _SEVERITY_NOTES["high"]
    return _SEVERITY_NOTES.get(severity.lower(), _SEVERITY_NOTES["high"])


def _infer_district(address: str) -> Optional[str]:
    match = _DISTRICT_RE.search(address or "")
    if not match:
        return None
    name = match.group(1).capitalize()
    if name.endswith("ск"):
        return f"{name}ий"
    return name


def _target_department(contract: ContractInfo, address: str) -> str:
    if contract.customer_name and contract.customer_name.strip():
        return contract.customer_name.strip()
    district = _infer_district(address)
    if district and "алматы" in address.lower():
        return f"Акимат {district}ского района г. Алматы"
    if "алматы" in address.lower():
        return "Акимат города Алматы"
    return "Акимат (местный исполнительный орган)"


def _copy_line(address: str) -> Optional[str]:
    district = _infer_district(address)
    if district and "алматы" in address.lower():
        return f"Аппарат акима {district}ского района г. Алматы"
    return None


def _warranty_status(contract: ContractInfo) -> str:
    ends = _fmt_date(contract.warranty_ends)
    if contract.warranty_active is False:
        return f"до {ends} г. (гарантия истекла)"
    if contract.warranty_active is True:
        return f"до {ends} г. (гарантия активна)"
    return f"до {ends} г."


def _photo_appendix(photo_urls: list[str]) -> str:
    if not photo_urls:
        return "Приложение: Фотофиксация дефекта с GPS-меткой."
    lines = ["Приложение:"]
    for i, url in enumerate(photo_urls, start=1):
        lines.append(f"  {i}. Фотофиксация дефекта — {url}")
    lines.append("  (фотоматериалы содержат GPS-координаты и дату фиксации).")
    return "\n".join(lines)


def _contract_number(contract: ContractInfo) -> str:
    if contract.contract_number and contract.contract_number.strip():
        return contract.contract_number.strip()
    if contract.trd_buy_id and contract.trd_buy_id.strip():
        return contract.trd_buy_id.strip()
    return "—"


def generate_complaint(body: ComplaintGenerateRequest) -> ComplaintGenerateResponse:
    user_name, user_iin, user_phone = _placeholder_user(body.user_info)
    defect = body.defect_info
    contract = body.contract_info

    address = (defect.address_description or "").strip() or "адрес не указан"
    lat = defect.gps.lat
    lng = defect.gps.lng
    defect_label = _defect_description(defect)
    severity_note = _severity_note(defect.severity)
    target = _target_department(contract, address)
    copy_to = _copy_line(address)

    contract_no = _contract_number(contract)
    contract_date = _fmt_date(contract.contract_date)
    supplier = (contract.supplier_name or "—").strip()
    supplier_bin = (contract.supplier_bin or "—").strip()
    warranty_line = _warranty_status(contract)

    subject = (
        f"Устранение дефекта дорожного покрытия по гарантии (договор № {contract_no})"
    )[:100]

    lines: list[str] = [
        f"В {target}",
        "",
    ]
    if copy_to:
        lines.extend([f"копия: {copy_to}", ""])
    lines.extend(
        [
            "ЗАЯВЛЕНИЕ",
            "",
            "о принятии мер по гарантийному устранению дефекта дорожного покрытия",
            "",
            f"От: {user_name}",
            f"ИИН: {user_iin}",
            f"Тел.: {user_phone}",
            "",
            (
                f"Настоящим сообщаю, что по адресу: {address} "
                f"(GPS-координаты: {lat:.6f}, {lng:.6f}) зафиксировано повреждение "
                f"дорожного покрытия ({defect_label}), превышающее допустимые нормы "
                "СТ РК 1418-2014 «Автомобильные дороги и улицы. Требования к "
                "эксплуатационному состоянию» и СТ РК 2522-2014 (в части допустимых "
                "размеров дефектов покрытия и просадки люков). "
                f"{severity_note}"
            ),
            "",
            (
                "Согласно данным Портала государственных закупок РК (goszakup.gov.kz), "
                f"работы по ремонту/содержанию данного участка выполнялись в рамках "
                f"Договора о государственных закупках № {contract_no} от {contract_date} г."
            ),
            "",
            f"Подрядчик: {supplier} (БИН: {supplier_bin}).",
            "",
            f"Гарантийный срок: {warranty_line}",
            "",
            (
                "На основании ст. 99 Административного процедурно-процессуального "
                "кодекса Республики Казахстан (АППК РК), ст. 12 и 24 Закона РК "
                "«Об автомобильных дорогах», ст. 43 Закона РК «О государственных "
                "закупках», а также требований СТ РК 1418-2014 и СТ РК 2522-2014,"
            ),
            "",
            "ПРОШУ:",
            "",
            "1. Организовать выездную проверку и зафиксировать указанный дефект с составлением дефектного акта.",
            (
                f"2. В адрес подрядчика {supplier} (БИН: {supplier_bin}) направить "
                f"официальную претензию об устранении дефекта за счёт средств подрядчика "
                f"в рамках гарантийных обязательств по Договору № {contract_no}."
            ),
            "3. Установить подрядчику срок устранения дефекта — не более 10 (десяти) календарных дней.",
            (
                "4. Предоставить мотивированный ответ в срок, установленный ст. 99 АППК РК "
                "(15 рабочих дней), с приложением фотоотчёта об устранённом дефекте "
                "через портал e-Otinish."
            ),
            "",
            _photo_appendix(defect.photo_urls),
            "",
            f"Дата: «___» __________ 20__ г.          Подпись: _______________ /{user_name}/",
        ]
    )

    return ComplaintGenerateResponse(
        subject=subject,
        target_department=target,
        document_body="\n".join(lines),
    )


def _severity_note(severity: Optional[str]) -> str:
    return _severity_sentence(severity)
