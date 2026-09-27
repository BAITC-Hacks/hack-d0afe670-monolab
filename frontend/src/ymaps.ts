const YMAPS_SCRIPT_ID = "yandex-maps-script";

export interface YMapEvent {
  get: (key: string) => number[];
}

export interface YPlacemark {
  geometry: {
    setCoordinates: (coords: number[]) => void;
    getCoordinates: () => number[];
  };
  events: { add: (event: string, cb: () => void) => void };
}

export interface YPolyline {
  events: { add: (event: string, cb: () => void) => void };
}

export interface YGeoObjects {
  add: (obj: YPlacemark | YPolyline) => void;
  remove: (obj: YPlacemark | YPolyline) => void;
}

export interface YMap {
  geoObjects: YGeoObjects;
  setCenter: (center: number[], zoom?: number) => void;
  events: { add: (event: string, cb: (e: YMapEvent) => void) => void };
  destroy: () => void;
}

export interface YMapsAPI {
  ready: (cb: () => void) => void;
  Map: new (
    parent: HTMLElement | string,
    state: { center: number[]; zoom: number; controls?: string[] },
    options?: Record<string, unknown>
  ) => YMap;
  Placemark: new (
    coords: number[],
    properties?: Record<string, unknown>,
    options?: Record<string, unknown>
  ) => YPlacemark;
  Polyline: new (
    coords: number[][],
    properties?: Record<string, unknown>,
    options?: Record<string, unknown>
  ) => YPolyline;
}

type YmapsWindow = Window & { ymaps?: YMapsAPI };

export function loadYmaps(apiKey: string): Promise<YMapsAPI> {
  return new Promise((resolve, reject) => {
    const w = window as YmapsWindow;
    if (w.ymaps) {
      w.ymaps.ready(() => resolve(w.ymaps!));
      return;
    }

    const existing = document.getElementById(YMAPS_SCRIPT_ID);
    if (existing) {
      existing.addEventListener("load", () => w.ymaps?.ready(() => resolve(w.ymaps!)));
      existing.addEventListener("error", () => reject(new Error("Yandex Maps failed to load")));
      return;
    }

    const script = document.createElement("script");
    script.id = YMAPS_SCRIPT_ID;
    script.src = `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(apiKey)}&lang=ru_RU`;
    script.async = true;
    script.onload = () => {
      if (!w.ymaps) {
        reject(new Error("ymaps missing after script load"));
        return;
      }
      w.ymaps.ready(() => resolve(w.ymaps!));
    };
    script.onerror = () => reject(new Error("Could not load Yandex Maps"));
    document.head.appendChild(script);
  });
}
