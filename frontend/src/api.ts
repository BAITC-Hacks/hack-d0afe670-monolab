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

/** @deprecated Legacy complaint generate response — specialist flow only */
export type ComplaintResponse = {
  subject: string;
  target_department: string;
  document_body: string;
};

export type MatchResponse = {
  match_found: boolean;
  address_display?: string | null;
  message: string;
};

export type CitizenSubmitResponse = {
  service_request_id: string;
  status: string;
  response_deadline: string;
  agency_responsible: string;
};

export type ComplaintEvent = {
  from_status?: string | null;
  to_status: string;
  actor: string;
  note?: string | null;
  created_at: string;
};

export type CitizenTrackResponse = {
  service_request_id: string;
  status: string;
  service_code: string;
  service_name: string;
  address: string;
  description: string;
  requested_datetime: string;
  updated_datetime: string;
  response_deadline?: string | null;
  agency_responsible: string;
  events: ComplaintEvent[];
};

export type SpecialistSummary = {
  id: number;
  service_request_id: string;
  status: string;
  tier: string;
  service_code: string;
  service_name: string;
  address: string;
  lat: number;
  long: number;
  requested_datetime: string;
  updated_datetime: string;
  cv_confidence?: number | null;
  reports_at_location?: number;
  active_reports_at_location?: number;
  location_key?: string | null;
  cluster_label?: string | null;
  urgency_score?: number;
};

export type WarrantyBlock = {
  contract_id?: string | null;
  contractor_name?: string | null;
  contractor_bin?: string | null;
  warranty_end?: string | null;
  customer_name?: string | null;
  trd_buy_id?: string | null;
};

export type SpecialistDetail = SpecialistSummary & {
  description: string;
  media_url?: string | null;
  cv_bbox?: number[] | null;
  agency_responsible: string;
  response_deadline?: string | null;
  warranty?: WarrantyBlock | null;
  generated_claim_subject?: string | null;
  generated_claim_body?: string | null;
  related_service_request_ids?: string[];
  events: ComplaintEvent[];
};

const API_BASE = import.meta.env.VITE_API_URL ?? "";

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

export async function submitComplaint(
  file: File,
  lat: number,
  lng: number,
  description: string
): Promise<CitizenSubmitResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("lat", String(lat));
  form.append("lng", String(lng));
  form.append("description", description);
  const res = await fetch(`${API_BASE}/api/v1/complaints`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Submit failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function trackComplaint(regNumber: string): Promise<CitizenTrackResponse> {
  const res = await fetch(`${API_BASE}/api/v1/complaints/${encodeURIComponent(regNumber)}`);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Track failed: HTTP ${res.status}`);
  }
  return res.json();
}

export type SpecialistListOptions = {
  status?: string;
  tier?: string;
  min_reports?: number;
  sort?: "urgency" | "date";
};

export async function fetchSpecialistComplaints(
  apiKey: string,
  options: SpecialistListOptions = {}
): Promise<SpecialistSummary[]> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.tier) params.set("tier", options.tier);
  if (options.min_reports && options.min_reports > 1) {
    params.set("min_reports", String(options.min_reports));
  }
  if (options.sort) params.set("sort", options.sort);
  const qs = params.toString();
  const res = await fetch(
    `${API_BASE}/api/v1/specialist/complaints${qs ? `?${qs}` : ""}`,
    { headers: { "X-Specialist-Key": apiKey } }
  );
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* plain text */
    }
    throw new Error(detail || `List failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchSpecialistDetail(
  apiKey: string,
  id: number
): Promise<SpecialistDetail> {
  const res = await fetch(`${API_BASE}/api/v1/specialist/complaints/${id}`, {
    headers: { "X-Specialist-Key": apiKey },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Detail failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function specialistApprove(
  apiKey: string,
  id: number,
  note?: string
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/specialist/complaints/${id}/approve`, {
    method: "POST",
    headers: {
      "X-Specialist-Key": apiKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ note }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function specialistReject(
  apiKey: string,
  id: number,
  reason: string
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/specialist/complaints/${id}/reject`, {
    method: "POST",
    headers: {
      "X-Specialist-Key": apiKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function specialistResolve(
  apiKey: string,
  id: number,
  note?: string
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/specialist/complaints/${id}/resolve`, {
    method: "POST",
    headers: {
      "X-Specialist-Key": apiKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ note }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function fetchSpecialistPdf(apiKey: string, id: number): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/v1/specialist/complaints/${id}/pdf`, {
    headers: { "X-Specialist-Key": apiKey },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.blob();
}

export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

export type WarrantyRoadSegment = {
  id: string;
  label: string;
  city: string;
  street?: string | null;
  contract_count: number;
  warranty_active: boolean;
  coordinates: number[][];
  center_lat: number;
  center_lng: number;
};

export type WarrantyMapMarkersResponse = {
  markers: WarrantyRoadSegment[];
  total_contracts: number;
  markers_on_map: number;
  cities: string[];
};

export async function fetchWarrantyMapMarkers(): Promise<WarrantyMapMarkersResponse> {
  const res = await fetch(`${API_BASE}/api/v1/map/markers`);
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}
