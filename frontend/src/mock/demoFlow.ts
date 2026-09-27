import type {
  ComplaintResponse,
  CVDetectionResponse,
  MatchResponse,
} from "../api";

export type DedupInfo = {
  isDuplicate: boolean;
  reportCount: number;
};

export const MOCK_CV: CVDetectionResponse = {
  detections: [
    {
      defect_class: "pothole",
      confidence: 0.94,
      bbox: [0.22, 0.38, 0.68, 0.72],
    },
  ],
  severity_tier: "WARRANTY_CLAIM",
  primary_defect: "pothole",
  message: "defect_detected",
};

export const MOCK_MATCH: MatchResponse = {
  match_found: true,
  street_name: "ул. Абая",
  address_display: "г. Алматы, ул. Абая, 150",
  contract_id: "KZ-2023-88412",
  trd_buy_id: "8841201",
  contract_title: "Капитальный ремонт участка ул. Абая",
  customer_name: "Управление пассажирского транспорта и автомобильных дорог г. Алматы",
  supplier: {
    name: 'ТОО "Астана ДорСтрой"',
    bin: "123456789012",
  },
  warranty_active: true,
  warranty_ends: "2026-09-30",
  days_remaining: 368,
  completed_on: "2023-09-15",
  message: "match_found",
};

export const MOCK_DEDUP: DedupInfo = {
  isDuplicate: true,
  reportCount: 3,
};

export const MOCK_COMPLAINT: ComplaintResponse = {
  subject: "Претензия по гарантийному обязательству — дефект на ул. Абая",
  target_department:
    "Управление пассажирского транспорта и автомобильных дорог г. Алматы",
  document_body: `ЗАЯВЛЕНИЕ

Прошу принять меры в отношении подрядчика ТОО "Астана ДорСтрой" (БИН 123456789012),
выполнившего ремонт участка ул. Абая в 2023 году, в связи с выявленным дефектом
(глубокая выбоина) в гарантийный период до 30.09.2026.

Координаты: 43.24040, 76.90780
Фото прилагается.`,
  llm_enhanced: true,
  e_otinish: {
    web_url: "https://eotinish.kz/ru/myApp",
    android_intent: "https://eotinish.kz/ru/myApp",
    ios_app_store: "https://eotinish.kz/ru/myApp",
    android_play_store: "https://eotinish.kz/ru/myApp",
  },
};

export const MOCK_TICKET_ID = "#4092";
export const MOCK_TENDER_AMOUNT = "450 млн ₸";

const DEFECT_LABELS: Record<string, string> = {
  pothole: "Глубокая яма",
  sunken_manhole: "Повреждённый люк",
  crack_longitudinal: "Трещина покрытия",
  crack_alligator: "Сетка трещин",
  rutting: "Колейность",
};

export function defectLabel(cvClass: string): string {
  return DEFECT_LABELS[cvClass] ?? cvClass;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE !== "false";
}

export async function demoDetectDefect(): Promise<CVDetectionResponse> {
  await delay(480);
  return MOCK_CV;
}

export async function demoMatchDefect(): Promise<MatchResponse> {
  await delay(2000);
  return MOCK_MATCH;
}

export async function demoGenerateComplaint(): Promise<ComplaintResponse> {
  await delay(1200);
  return MOCK_COMPLAINT;
}

export async function demoSubmitTicket(): Promise<string> {
  await delay(1500);
  return MOCK_TICKET_ID;
}
