export type SupplierInfo = {
  name: string;
  bin: string;
};

export type MatchResponse = {
  match_found: boolean;
  street_name?: string | null;
  address_display?: string | null;
  contract_id?: string | null;
  trd_buy_id?: string | null;
  contract_title?: string | null;
  customer_name?: string | null;
  supplier?: SupplierInfo | null;
  warranty_active?: boolean | null;
  warranty_ends?: string | null;
  days_remaining?: number | null;
  completed_on?: string | null;
  message: string;
};

export type HealthResponse = {
  contracts_count?: number | null;
  tenderai_contracts?: number | null;
  data_source?: string;
  goszakup_live_enabled?: boolean;
};

export type EOtinishLinks = {
  web_url: string;
  android_intent: string;
  ios_app_store: string;
  android_play_store: string;
};

export type ComplaintResponse = {
  subject: string;
  target_department: string;
  document_body: string;
  pdf_base64?: string | null;
  pdf_filename?: string | null;
  llm_enhanced?: boolean;
  e_otinish?: EOtinishLinks | null;
};

export type ComplaintPayload = {
  user_info?: { name?: string; iin?: string; phone?: string };
  defect_info: {
    address_description: string;
    gps: { lat: number; lng: number };
    defect_type?: string;
    severity?: string;
    photo_urls?: string[];
    photo_base64?: string;
  };
  contract_info: {
    contract_number?: string;
    trd_buy_id?: string;
    contract_date?: string;
    customer_name?: string;
    supplier_name: string;
    supplier_bin?: string;
    warranty_ends?: string;
    warranty_active?: boolean | null;
  };
};

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export async function matchDefect(lat: number, lng: number): Promise<MatchResponse> {
  const url = `${API_BASE}/api/v1/match?lat=${lat}&lng=${lng}&defect_type=pothole`;
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

export type WarrantyRoadSegment = {
  id: string;
  label: string;
  city: string;
  street?: string | null;
  contract_count: number;
  warranty_active: boolean;
  coordinates: number[][]; // [[lat, lng], ...]
};

export type WarrantyMarkersResponse = {
  markers: WarrantyRoadSegment[];
  total_contracts: number;
  markers_on_map: number;
  cities?: string[];
};

export async function fetchWarrantyMarkers(): Promise<WarrantyMarkersResponse> {
  const res = await fetch(`${API_BASE}/api/v1/map/markers`);
  if (!res.ok) throw new Error("markers failed");
  return res.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/health`);
  if (!res.ok) throw new Error("health failed");
  return res.json();
}

export type CVDetection = {
  defect_class: string;
  confidence: number;
  bbox: number[];
};

export type CVDetectionResponse = {
  detections: CVDetection[];
  severity_tier?: "HAZARD_FASTTRACK" | "WARRANTY_CLAIM" | null;
  primary_defect?: string | null;
  message: string;
};

export type DefectReportResponse = {
  cv: CVDetectionResponse;
  match?: MatchResponse | null;
  severity_tier?: "HAZARD_FASTTRACK" | "WARRANTY_CLAIM" | null;
  message: string;
};

export async function detectDefect(file: File): Promise<CVDetectionResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1/cv/detect`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `CV detect failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function reportDefect(
  file: File,
  lat: number,
  lng: number
): Promise<DefectReportResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("lat", String(lat));
  form.append("lng", String(lng));
  const res = await fetch(`${API_BASE}/api/v1/report`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Report failed: HTTP ${res.status}`);
  }
  return res.json();
}

/** Map YOLO class names to frontend defect_type dropdown values. */
export function cvClassToDefectType(cvClass: string): string {
  const map: Record<string, string> = {
    pothole: "pothole",
    sunken_manhole: "manhole",
    crack_longitudinal: "crack",
    crack_alligator: "crack",
    rutting: "subsidence",
  };
  return map[cvClass] ?? "pothole";
}

export async function generateComplaint(payload: ComplaintPayload): Promise<ComplaintResponse> {
  const res = await fetch(`${API_BASE}/api/v1/complaint/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}
