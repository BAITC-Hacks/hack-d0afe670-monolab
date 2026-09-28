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

export const TIER_LABELS: Record<string, string> = {
  HAZARD_FASTTRACK: "Срочный дефект",
  WARRANTY_CLAIM: "Гарантийный случай",
  GENERAL_MAINTENANCE_REQUEST: "Содержание дороги",
};

export const STATUS_LABELS: Record<string, string> = {
  SUBMITTED: "Подано",
  REGISTERED: "Зарегистрировано",
  IN_REVIEW: "На рассмотрении",
  FORWARDED: "Передано в работу",
  RESOLVED: "Устранено",
  REJECTED: "Отклонено",
};
