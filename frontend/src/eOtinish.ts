import type { ComplaintResponse } from "./api";

function isAndroid(): boolean {
  return /android/i.test(navigator.userAgent);
}

function isIOS(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

export function downloadPdfFromBase64(base64: string, filename: string): void {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

export function openEOtinish(complaint: ComplaintResponse): void {
  const links = complaint.e_otinish;
  if (!links) {
    window.open("https://eotinish.kz/ru/myApp", "_blank", "noopener,noreferrer");
    return;
  }

  if (isAndroid()) {
    window.location.href = links.android_intent;
    return;
  }

  if (isIOS()) {
    window.open(links.web_url, "_blank", "noopener,noreferrer");
    return;
  }

  window.open(links.web_url, "_blank", "noopener,noreferrer");
}

export function eOtinishHint(): string {
  if (isAndroid() || isIOS()) {
    return "Текст скопирован, PDF сохранён. В e-Otinish: вставьте текст, прикрепите PDF и подпишите.";
  }
  return "Текст скопирован, PDF скачан. Откройте e-Otinish в eGov Mobile, вставьте текст и прикрепите PDF.";
}
