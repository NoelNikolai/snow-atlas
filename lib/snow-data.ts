export type SnowProduct = "FSC" | "GFSC"

export type SnowCellProperties = {
  cell_id: string
  region_name: string
  product: SnowProduct
  coverage_percent: number | null
  observed_at: string
  oldest_observed_at?: string | null
  valid_percent?: number | null
  snow_pixel_percent?: number | null
  cloud_percent: number | null
  resolution_m: number
  cell_size_m?: number | null
  source_layer?: string | null
  product_date?: string | null
  elevation_m: number | null
  confidence: "hoch" | "mittel"
  source?: string | null
  source_product_id?: string | null
  quality_good_percent?: number | null
  water_percent?: number | null
}

export type SnowCellFeature = {
  type: "Feature"
  id: string
  properties: SnowCellProperties
  geometry: {
    type: "Polygon"
    coordinates: number[][][]
  }
}

export type SnowPointResult = {
  longitude: number
  latitude: number
  covered: boolean
  cells: Partial<Record<SnowProduct, SnowCellFeature>>
  data_version: string
}

export type SnowAreaSummary = {
  snow_area_percent: number | null
  mean_coverage_percent: number | null
  valid_percent: number
  cloud_percent: number
  nodata_percent: number
}

export type SnowAreaJob = {
  id: string
  state: "running" | "done" | "failed"
  message: string
}

// Ordinal one-hue ramp, light -> dark = little -> much snow. Must match
// SNOW_CLASSES in backend/app/processing/snow_raster.py.
export const snowClasses = [
  { min: 1, label: "1–25", color: "#86b6ef" },
  { min: 26, label: "26–50", color: "#3987e5" },
  { min: 51, label: "51–75", color: "#1c5cab" },
  { min: 76, label: "76–100", color: "#0d366b" },
] as const

export type SnowFeatureCollection = {
  type: "FeatureCollection"
  features: SnowCellFeature[]
  metadata?: Record<string, unknown>
}

const observedAt = {
  fresh: "2026-09-22T06:18:00Z",
  recent: "2026-09-22T03:42:00Z",
  daily: "2026-09-21T18:05:00Z",
}

function cell(
  id: string,
  region: string,
  product: SnowProduct,
  coverage: number,
  bounds: [number, number, number, number],
  observed: string,
  cloud: number,
  elevation: number,
  cellSize = 5_000,
): SnowCellFeature {
  const [west, south, east, north] = bounds

  return {
    type: "Feature",
    id,
    properties: {
      cell_id: id,
      region_name: region,
      product,
      coverage_percent: coverage,
      observed_at: observed,
      oldest_observed_at: observed,
      valid_percent: 94,
      snow_pixel_percent: Math.min(100, coverage + 8),
      cloud_percent: cloud,
      resolution_m: product === "FSC" ? 20 : 60,
      cell_size_m: cellSize,
      source_layer: product === "FSC" ? "FSCTOC" : "GF",
      product_date: observed.slice(0, 10),
      elevation_m: elevation,
      confidence: cloud <= 12 ? "hoch" : "mittel",
    },
    geometry: {
      type: "Polygon",
      coordinates: [[
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ]],
    },
  }
}

export const demoSnowData: SnowFeatureCollection = {
  type: "FeatureCollection",
  features: [
    cell("DE-BY-FAR-01", "Farchant · Tal", "FSC", 0, [11.105, 47.526, 11.108, 47.529], observedAt.fresh, 3, 680, 200),
    cell("DE-BY-FRI-01", "Hoher Fricken · Westflanke", "FSC", 18, [11.139, 47.527, 11.142, 47.530], observedAt.fresh, 6, 1_520, 200),
    cell("DE-BY-FRI-02", "Hoher Fricken · Gipfel", "GFSC", 34, [11.153, 47.531, 11.157, 47.535], observedAt.daily, 4, 1_940, 240),
    cell("AT-07-STB", "Stubai · Tirol", "FSC", 82, [10.92, 46.88, 11.42, 47.18], observedAt.fresh, 7, 2_380),
    cell("AT-07-OET", "Ötztal · Tirol", "GFSC", 68, [10.45, 46.72, 10.92, 47.10], observedAt.daily, 11, 2_460),
    cell("AT-07-ARL", "Arlberg", "FSC", 54, [9.92, 46.98, 10.42, 47.34], observedAt.recent, 18, 2_070),
    cell("AT-07-ZIL", "Zillertal", "GFSC", 76, [11.66, 46.84, 12.20, 47.23], observedAt.daily, 9, 2_290),
    cell("AT-05-TAU", "Hohe Tauern", "GFSC", 89, [12.42, 46.82, 13.15, 47.25], observedAt.daily, 5, 2_540),
    cell("IT-32-DOL", "Dolomiten", "FSC", 38, [11.82, 46.34, 12.48, 46.74], observedAt.fresh, 22, 2_120),
    cell("CH-BE-JUN", "Berner Alpen", "GFSC", 71, [7.55, 46.26, 8.18, 46.68], observedAt.daily, 8, 2_350),
    cell("FR-ARA-MBL", "Mont Blanc", "FSC", 93, [6.68, 45.72, 7.12, 46.10], observedAt.recent, 3, 2_710),
    cell("CH-GR-ENG", "Engadin", "GFSC", 64, [9.48, 46.28, 10.16, 46.76], observedAt.daily, 13, 2_260),
  ],
}

export const alpinePlaces = [
  { name: "Farchant", center: [11.112, 47.531] as [number, number], zoom: 13.2 },
  { name: "Hoher Fricken", center: [11.15528, 47.53278] as [number, number], zoom: 14.0 },
  { name: "Innsbruck", center: [11.4041, 47.2692] as [number, number], zoom: 8.4 },
  { name: "Stubai", center: [11.17, 47.02] as [number, number], zoom: 9.2 },
  { name: "Zillertal", center: [11.93, 47.05] as [number, number], zoom: 9.0 },
  { name: "Hohe Tauern", center: [12.82, 47.02] as [number, number], zoom: 8.6 },
  { name: "Mont Blanc", center: [6.87, 45.86] as [number, number], zoom: 9.2 },
  { name: "Berner Alpen", center: [7.88, 46.47] as [number, number], zoom: 8.8 },
]
