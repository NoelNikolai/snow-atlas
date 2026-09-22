"use client"

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ChevronDown,
  Clock3,
  Cloud,
  CloudDownload,
  Crosshair,
  Database,
  Layers3,
  LoaderCircle,
  LocateFixed,
  Map as MapIcon,
  Minus,
  MountainSnow,
  Plus,
  RefreshCw,
  Search,
  Snowflake,
} from "lucide-react"
import {
  AttributionControl,
  Map as MapLibreMap,
  Marker,
  type GeoJSONSource,
  type RasterTileSource,
  type StyleSpecification,
} from "maplibre-gl"

import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import {
  alpinePlaces,
  snowClasses,
  type SnowAreaJob,
  type SnowAreaSummary,
  type SnowCellFeature,
  type SnowCellProperties,
  type SnowFeatureCollection,
  type SnowPointResult,
  type SnowProduct,
} from "@/lib/snow-data"

type BasemapMode = "satellite" | "map"
type DataMode = "idle" | "loading" | "live" | "snapshot" | "preparing" | "unavailable"
type SnowCells = Partial<Record<SnowProduct, SnowCellFeature>>

type NominatimResult = {
  display_name: string
  lat: string
  lon: string
}

type WebMcpTool = {
  name: string
  title?: string
  description: string
  inputSchema: Record<string, unknown>
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean }
  execute(input: unknown): unknown | Promise<unknown>
}

declare global {
  interface Document {
    readonly modelContext?: {
      registerTool(tool: WebMcpTool, options?: { signal?: AbortSignal }): void | Promise<void>
    }
  }
}

const snapshotLayerIds = ["snow-fill"]
const farchantSnapshotBounds = [11.045, 47.485, 11.225, 47.575] as const
const emptySnowData: SnowFeatureCollection = { type: "FeatureCollection", features: [] }
const emptySelection: SnowFeatureCollection = { type: "FeatureCollection", features: [] }

function insideFarchantSnapshot([longitude, latitude]: [number, number]) {
  const [west, south, east, north] = farchantSnapshotBounds
  return longitude >= west && longitude <= east && latitude >= south && latitude <= north
}

async function geocodeAddress(value: string) {
  const url = new URL("https://nominatim.openstreetmap.org/search")
  url.searchParams.set("format", "jsonv2")
  url.searchParams.set("q", value)
  url.searchParams.set("limit", "1")
  url.searchParams.set("accept-language", "de")
  const response = await fetch(url, { headers: { Accept: "application/json" } })
  if (!response.ok) throw new Error("Die Ortssuche ist gerade nicht erreichbar.")
  const results = await response.json() as NominatimResult[]
  if (!results[0]) throw new Error("Ort oder Adresse wurde nicht gefunden.")
  return {
    display_name: results[0].display_name,
    latitude: Number(results[0].lat),
    longitude: Number(results[0].lon),
  }
}

function satelliteStyle(): StyleSpecification {
  const mapTilerKey = process.env.NEXT_PUBLIC_MAPTILER_KEY
  const satelliteSource = mapTilerKey
    ? {
        type: "raster" as const,
        url: `https://api.maptiler.com/tiles/satellite-v4/tiles.json?key=${mapTilerKey}`,
        tileSize: 256,
        attribution: "© MapTiler © OpenStreetMap contributors",
      }
    : {
        type: "raster" as const,
        tiles: [
          "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg",
        ],
        tileSize: 256,
        maxzoom: 14,
        attribution: "EOxCloudless by EOX IT Services GmbH · Contains modified Copernicus Sentinel data 2025",
      }

  return {
    version: 8,
    sources: { satellite: satelliteSource },
    layers: [
      { id: "alpine-night", type: "background", paint: { "background-color": "#102023" } },
      {
        id: "satellite",
        type: "raster",
        source: "satellite",
        paint: {
          "raster-brightness-min": 0.06,
          "raster-brightness-max": 0.92,
          "raster-contrast": 0.12,
          "raster-saturation": -0.08,
        },
      },
    ],
  }
}

function baseStyle(mode: BasemapMode): StyleSpecification | string {
  return mode === "satellite" ? satelliteStyle() : "https://tiles.openfreemap.org/styles/liberty"
}

/** Snow sits under the basemap's labels so place names stay readable. */
function firstLabelLayer(map: MapLibreMap) {
  return map.getStyle().layers.find((layer) => layer.type === "symbol")?.id
}

function snowMode(products: Record<SnowProduct, boolean>) {
  if (products.FSC && products.GFSC) return "combined"
  if (products.FSC) return "FSC"
  if (products.GFSC) return "GFSC"
  return null
}

function tileUrl(apiBase: string, products: Record<SnowProduct, boolean>, clouds: boolean, version: string) {
  const mode = snowMode(products) ?? "combined"
  return `${apiBase}/api/v1/snow/tiles/${mode}/{z}/{x}/{y}.png?clouds=${clouds ? 1 : 0}&v=${version}`
}

function addSnowLayers(
  map: MapLibreMap,
  source: { kind: "raster"; url: string; visible: boolean } | { kind: "geojson"; data: SnowFeatureCollection },
) {
  const beforeId = firstLabelLayer(map)
  if (source.kind === "raster" && !map.getSource("snow-raster")) {
    map.addSource("snow-raster", { type: "raster", tiles: [source.url], tileSize: 256, minzoom: 5, maxzoom: 15 })
    map.addLayer({
      id: "snow-raster",
      type: "raster",
      source: "snow-raster",
      layout: { visibility: source.visible ? "visible" : "none" },
      paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 },
    }, beforeId)
  }
  if (source.kind === "geojson" && !map.getSource("snow-cells")) {
    map.addSource("snow-cells", { type: "geojson", data: source.data, promoteId: "cell_id" })
    map.addLayer({
      id: "snow-fill",
      type: "fill",
      source: "snow-cells",
      paint: {
        "fill-color": [
          "step", ["coalesce", ["get", "coverage_percent"], 0],
          snowClasses[0].color,
          snowClasses[1].min, snowClasses[1].color,
          snowClasses[2].min, snowClasses[2].color,
          snowClasses[3].min, snowClasses[3].color,
        ],
        // 0 % stays clickable but invisible: no snow means no paint.
        "fill-opacity": ["case", [">", ["coalesce", ["get", "coverage_percent"], 0], 0], 0.86, 0],
      },
    }, beforeId)
  }
  if (!map.getSource("snow-selection")) {
    map.addSource("snow-selection", { type: "geojson", data: emptySelection })
    map.addLayer({
      id: "snow-selection-casing",
      type: "line",
      source: "snow-selection",
      paint: { "line-color": "#08161c", "line-width": 5, "line-opacity": 0.75 },
    }, beforeId)
    map.addLayer({
      id: "snow-selection",
      type: "line",
      source: "snow-selection",
      paint: { "line-color": "#ffffff", "line-width": 2 },
    }, beforeId)
  }
}

function toProperties(properties: Record<string, unknown>): SnowCellProperties {
  const number = (value: unknown) => value == null ? null : Number(value)
  return {
    cell_id: String(properties.cell_id),
    region_name: String(properties.region_name),
    product: String(properties.product) as SnowProduct,
    coverage_percent: number(properties.coverage_percent),
    observed_at: String(properties.observed_at),
    oldest_observed_at: properties.oldest_observed_at == null ? null : String(properties.oldest_observed_at),
    valid_percent: number(properties.valid_percent),
    snow_pixel_percent: number(properties.snow_pixel_percent),
    cloud_percent: number(properties.cloud_percent),
    resolution_m: Number(properties.resolution_m),
    cell_size_m: number(properties.cell_size_m),
    source_layer: properties.source_layer == null ? null : String(properties.source_layer),
    product_date: properties.product_date == null ? null : String(properties.product_date),
    elevation_m: number(properties.elevation_m),
    confidence: String(properties.confidence) as "hoch" | "mittel",
  }
}

/** Mirrors the tile compositing: FSC wins where it saw the ground, GFSC fills clouds. */
function pickCell(cells: SnowCells, products: Record<SnowProduct, boolean>) {
  const fsc = products.FSC ? cells.FSC : undefined
  const gfsc = products.GFSC ? cells.GFSC : undefined
  if (fsc && (fsc.properties.valid_percent ?? 0) >= 50) return fsc
  return gfsc ?? fsc ?? null
}

function observedLabel(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin",
  }).format(new Date(value))
}

function ageLabel(value: string) {
  const hours = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 3_600_000))
  if (hours < 24) return `vor ${hours} h`
  const days = Math.round(hours / 24)
  return `vor ${days} ${days === 1 ? "Tag" : "Tagen"}`
}

function shortDate(value: string | null | undefined) {
  if (!value) return "—"
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit", month: "short", timeZone: "Europe/Berlin",
  }).format(new Date(value))
}

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value}%`
}

function productFilter(products: Record<SnowProduct, boolean>) {
  const active = (Object.keys(products) as SnowProduct[]).filter((product) => products[product])
  return ["in", ["get", "product"], ["literal", active]] as unknown as never
}

function snowApiBase() {
  const configured = process.env.NEXT_PUBLIC_SNOW_API_URL
  if (configured) return configured.replace(/\/$/, "")
  if (typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname)) {
    return "http://127.0.0.1:8000"
  }
  return ""
}

async function fetchJson<T>(url: string, init?: RequestInit) {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.json().then((body) => (body as { detail?: unknown } | null)?.detail).catch(() => null)
    throw new Error(typeof detail === "string" ? detail : `Anfrage fehlgeschlagen (${response.status})`)
  }
  return await response.json() as T
}

export function SnowMap() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const markersRef = useRef<Marker[]>([])
  const [viewStarted, setViewStarted] = useState(false)
  const [snapshotData, setSnapshotData] = useState<SnowFeatureCollection>(emptySnowData)
  const [cells, setCells] = useState<SnowCells>({})
  const [basemap, setBasemap] = useState<BasemapMode>("map")
  const [products, setProducts] = useState<Record<SnowProduct, boolean>>({ FSC: true, GFSC: true })
  const [showClouds, setShowClouds] = useState(true)
  const [query, setQuery] = useState("")
  const [dataMode, setDataMode] = useState<DataMode>("idle")
  const [statusMessage, setStatusMessage] = useState("")
  const [sourceKind, setSourceKind] = useState<"raster" | "geojson">("raster")
  const [areaSummary, setAreaSummary] = useState<SnowAreaSummary | null>(null)
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchError, setSearchError] = useState("")
  const [layersOpen, setLayersOpen] = useState(false)
  const layerPanelRef = useRef<HTMLElement>(null)
  const basemapRef = useRef(basemap)
  const apiBaseRef = useRef("")
  const sourceKindRef = useRef<"raster" | "geojson">("raster")
  const productsRef = useRef(products)
  const showCloudsRef = useRef(showClouds)
  const dataVersionRef = useRef("0")
  const snapshotDataRef = useRef(snapshotData)
  const selectedRef = useRef<SnowCellFeature | null>(null)
  const requestRef = useRef(0)
  const lastPointRef = useRef<[number, number] | null>(null)
  const locationRef = useRef<{ center: [number, number]; zoom: number }>({ center: [11.1325, 47.531], zoom: 13.1 })

  const selectedCell = useMemo(() => pickCell(cells, products), [cells, products])
  const selected = selectedCell?.properties ?? null
  const usedGapFill = selected?.product === "GFSC" && products.FSC && Boolean(cells.FSC)

  const snapshotCoverage = useMemo(() => {
    const visible = snapshotData.features.filter((feature) => products[feature.properties.product])
    if (!visible.length) return null
    const snowy = visible.filter((feature) => (feature.properties.coverage_percent ?? 0) > 0).length
    return Math.round((100 * snowy) / visible.length)
  }, [products, snapshotData])
  const snowAreaPercent = sourceKind === "geojson" ? snapshotCoverage : areaSummary?.snow_area_percent ?? null

  const activeLayerLabel = useMemo(() => {
    const active = (Object.keys(products) as SnowProduct[]).filter((product) => products[product])
    return active.length ? active.join("+") : "aus"
  }, [products])

  useEffect(() => {
    if (!layersOpen) return
    const closeOnOutside = (event: PointerEvent) => {
      if (!layerPanelRef.current?.contains(event.target as Node)) setLayersOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setLayersOpen(false)
    }
    document.addEventListener("pointerdown", closeOnOutside)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [layersOpen])

  const showFocusMarkers = useCallback((map: MapLibreMap, center: [number, number]) => {
    markersRef.current.forEach((marker) => marker.remove())
    markersRef.current = []
    if (!insideFarchantSnapshot(center)) return
    const addMarker = (coordinates: [number, number], title: string, kind: "place" | "summit") => {
      const element = document.createElement("div")
      element.className = `place-marker ${kind}`
      const dot = document.createElement("span")
      const label = document.createElement("b")
      label.textContent = title
      element.append(dot, label)
      markersRef.current.push(new Marker({ element, anchor: "bottom" }).setLngLat(coordinates).addTo(map))
    }
    addMarker([11.112, 47.531], "Farchant", "place")
    addMarker([11.15317, 47.53135], "Hoher Fricken · 1.940 m", "summit")
  }, [])

  const applyLayerState = useCallback((map: MapLibreMap) => {
    if (map.getLayer("snow-raster")) {
      const visible = snowMode(productsRef.current) !== null
      map.setLayoutProperty("snow-raster", "visibility", visible ? "visible" : "none")
      const source = map.getSource("snow-raster") as RasterTileSource | undefined
      source?.setTiles([tileUrl(apiBaseRef.current, productsRef.current, showCloudsRef.current, dataVersionRef.current)])
    }
    const filter = productFilter(productsRef.current)
    snapshotLayerIds.forEach((id) => {
      if (map.getLayer(id)) map.setFilter(id, filter)
    })
  }, [])

  const restoreSnowOverlay = useCallback((map: MapLibreMap) => {
    addSnowLayers(map, sourceKindRef.current === "raster"
      ? {
          kind: "raster",
          url: tileUrl(apiBaseRef.current, productsRef.current, showCloudsRef.current, dataVersionRef.current),
          visible: snowMode(productsRef.current) !== null,
        }
      : { kind: "geojson", data: snapshotDataRef.current })
    applyLayerState(map)
    const selection = map.getSource("snow-selection") as GeoJSONSource | undefined
    selection?.setData(selectedRef.current ? { type: "FeatureCollection", features: [selectedRef.current] } : emptySelection)
  }, [applyLayerState])

  const refreshSummary = useCallback(async () => {
    const map = mapRef.current
    const apiBase = apiBaseRef.current
    const mode = snowMode(productsRef.current)
    if (!map || !apiBase || sourceKindRef.current !== "raster" || !mode) {
      setAreaSummary(null)
      return
    }
    const bounds = map.getBounds()
    const clamp = (value: number) => Math.max(-85, Math.min(85, value))
    const params = new URLSearchParams({
      west: String(Math.max(-180, bounds.getWest())), east: String(Math.min(180, bounds.getEast())),
      south: String(clamp(bounds.getSouth())), north: String(clamp(bounds.getNorth())), mode,
    })
    try {
      setAreaSummary(await fetchJson<SnowAreaSummary>(`${apiBase}/api/v1/snow/summary?${params}`))
    } catch {
      setAreaSummary(null)
    }
  }, [])

  const queryPoint = useCallback(async (point: [number, number]) => {
    lastPointRef.current = point
    const params = new URLSearchParams({ lon: String(point[0]), lat: String(point[1]) })
    const result = await fetchJson<SnowPointResult>(`${apiBaseRef.current}/api/v1/snow/point?${params}`)
    setCells(result.cells)
    return result
  }, [])

  const refreshDataVersion = useCallback(async () => {
    const status = await fetchJson<{ data_version: string }>(`${apiBaseRef.current}/api/v1/snow/status`)
    dataVersionRef.current = status.data_version
    if (mapRef.current) applyLayerState(mapRef.current)
  }, [applyLayerState])

  const prepareArea = useCallback(async (point: [number, number], label: string) => {
    const request = ++requestRef.current
    setDataMode("preparing")
    setStatusMessage("Frage WEkEO nach aktuellen Aufnahmen …")
    try {
      let job = await fetchJson<SnowAreaJob>(`${apiBaseRef.current}/api/v1/snow/areas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ longitude: point[0], latitude: point[1] }),
      })
      while (job.state === "running") {
        if (request !== requestRef.current) return
        setStatusMessage(job.message)
        await new Promise((resolve) => setTimeout(resolve, 2_000))
        job = await fetchJson<SnowAreaJob>(`${apiBaseRef.current}/api/v1/snow/areas/${job.id}`)
      }
      if (request !== requestRef.current) return
      if (job.state === "failed") throw new Error(job.message)
      await refreshDataVersion()
      const result = await queryPoint(point)
      setDataMode(result.covered ? "live" : "unavailable")
      setStatusMessage(result.covered ? label : "WEkEO hat für diesen Punkt keine gültigen Pixel geliefert.")
      void refreshSummary()
    } catch (error) {
      if (request !== requestRef.current) return
      setDataMode("unavailable")
      setStatusMessage(error instanceof Error ? error.message : "Schneedaten konnten nicht geladen werden.")
    }
  }, [queryPoint, refreshSummary, refreshDataVersion])

  const showLocation = useCallback(async (center: [number, number], label: string, zoom = 13.2) => {
    const request = ++requestRef.current
    locationRef.current = { center, zoom }
    setViewStarted(true)
    setSearchError("")
    setDataMode("loading")
    setStatusMessage(label)

    requestAnimationFrame(() => {
      mapRef.current?.resize()
      if (mapRef.current) showFocusMarkers(mapRef.current, center)
      mapRef.current?.flyTo({ center, zoom, pitch: 30, bearing: -8, duration: 1_150 })
    })

    const apiBase = snowApiBase()
    if (apiBase) {
      try {
        const status = await fetchJson<{ data_version: string }>(`${apiBase}/api/v1/snow/status`)
        if (request !== requestRef.current) return
        apiBaseRef.current = apiBase
        sourceKindRef.current = "raster"
        setSourceKind("raster")
        dataVersionRef.current = status.data_version
        if (mapRef.current?.isStyleLoaded()) restoreSnowOverlay(mapRef.current)
        const result = await queryPoint(center)
        if (request !== requestRef.current) return
        if (result.covered) {
          setDataMode("live")
          return
        }
        await prepareArea(center, label)
        return
      } catch {
        // Backend not running: fall through to the static snapshot.
      }
    }

    apiBaseRef.current = ""
    sourceKindRef.current = "geojson"
    setSourceKind("geojson")
    let collection = emptySnowData
    if (insideFarchantSnapshot(center)) {
      try {
        collection = await fetchJson<SnowFeatureCollection>("/data/farchant-snow.geojson")
      } catch {
        collection = emptySnowData
      }
    }
    if (request !== requestRef.current) return
    snapshotDataRef.current = collection
    setSnapshotData(collection)
    const map = mapRef.current
    if (map?.isStyleLoaded()) {
      restoreSnowOverlay(map)
      ;(map.getSource("snow-cells") as GeoJSONSource | undefined)?.setData(collection)
    }
    if (!collection.features.length) {
      setCells({})
      setDataMode("unavailable")
      setStatusMessage("Ohne lokales Backend gibt es nur den Farchant-Snapshot. Starte ./start.sh für alle Orte.")
      return
    }
    const nearest = collection.features.reduce((best, feature) => {
      const point = feature.geometry.coordinates[0]?.[0] ?? center
      const bestPoint = best.geometry.coordinates[0]?.[0] ?? center
      const distance = (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2
      const bestDistance = (bestPoint[0] - center[0]) ** 2 + (bestPoint[1] - center[1]) ** 2
      return distance < bestDistance ? feature : best
    })
    setCells({ [nearest.properties.product]: nearest })
    setDataMode("snapshot")
  }, [prepareArea, queryPoint, restoreSnowOverlay, showFocusMarkers])

  useEffect(() => {
    if (!viewStarted || !containerRef.current || mapRef.current) return
    const map = new MapLibreMap({
      container: containerRef.current,
      style: baseStyle(basemapRef.current),
      center: locationRef.current.center,
      zoom: locationRef.current.zoom,
      pitch: 28,
      bearing: -7,
      attributionControl: false,
      maxZoom: 17,
    })
    mapRef.current = map
    map.addControl(new AttributionControl({ compact: true }), "bottom-right")
    let summaryTimer: ReturnType<typeof setTimeout> | undefined
    map.on("load", () => {
      restoreSnowOverlay(map)
      showFocusMarkers(map, locationRef.current.center)
    })
    map.on("moveend", () => {
      clearTimeout(summaryTimer)
      summaryTimer = setTimeout(() => void refreshSummary(), 350)
    })
    map.on("click", (event) => {
      if (sourceKindRef.current === "geojson") {
        const feature = map.queryRenderedFeatures(event.point, { layers: ["snow-fill"] })[0]
        if (!feature?.properties) return
        const properties = toProperties(feature.properties)
        setCells({
          [properties.product]: {
            type: "Feature",
            id: properties.cell_id,
            properties,
            geometry: feature.geometry as SnowCellFeature["geometry"],
          },
        })
        return
      }
      if (!apiBaseRef.current) return
      void queryPoint([event.lngLat.lng, event.lngLat.lat]).catch(() => setCells({}))
    })
    map.getCanvas().style.cursor = "crosshair"
    return () => {
      clearTimeout(summaryTimer)
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current = []
      map.remove()
      mapRef.current = null
    }
  }, [queryPoint, refreshSummary, restoreSnowOverlay, showFocusMarkers, viewStarted])

  useEffect(() => { snapshotDataRef.current = snapshotData }, [snapshotData])
  useEffect(() => {
    selectedRef.current = selectedCell
    const selection = mapRef.current?.getSource("snow-selection") as GeoJSONSource | undefined
    selection?.setData(selectedCell ? { type: "FeatureCollection", features: [selectedCell] } : emptySelection)
  }, [selectedCell])
  useEffect(() => {
    productsRef.current = products
    showCloudsRef.current = showClouds
    const map = mapRef.current
    if (map?.isStyleLoaded()) applyLayerState(map)
    void refreshSummary()
  }, [applyLayerState, products, refreshSummary, showClouds])

  useEffect(() => {
    const context = document.modelContext
    if (!context?.registerTool) return
    const lifecycle = new AbortController()
    const register = (tool: WebMcpTool) => {
      try {
        void Promise.resolve(context.registerTool(tool, { signal: lifecycle.signal }))
          .catch((error) => console.warn("Snow Atlas WebMCP registration failed", error))
      } catch (error) {
        console.warn("Snow Atlas WebMCP registration failed", error)
      }
    }

    register({
      name: "navigate_snow_map",
      title: "Schneekarte verschieben",
      description: "Navigiert die sichtbare Schneekarte zu einem unterstützten Alpenort oder zu Koordinaten.",
      inputSchema: {
        type: "object",
        properties: {
          place: { type: "string", description: "Unterstützter Ort, etwa Farchant oder Hoher Fricken." },
          latitude: { type: "number", minimum: -90, maximum: 90 },
          longitude: { type: "number", minimum: -180, maximum: 180 },
          zoom: { type: "number", minimum: 2, maximum: 14 },
        },
        anyOf: [{ required: ["place"] }, { required: ["latitude", "longitude"] }],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(input) {
        if (!input || typeof input !== "object") throw new Error("Ort oder Koordinaten fehlen.")
        const value = input as Record<string, unknown>
        const requestedZoom = typeof value.zoom === "number" && value.zoom >= 2 && value.zoom <= 14 ? value.zoom : undefined
        if (typeof value.place === "string" && value.place.trim()) {
          const placeQuery = value.place.trim().toLocaleLowerCase("de")
          const place = alpinePlaces.find((item) => item.name.toLocaleLowerCase("de").includes(placeQuery))
          if (!place) throw new Error("Dieser Ort ist im MVP noch nicht verfügbar.")
          setQuery(place.name)
          await showLocation(place.center, place.name, requestedZoom ?? place.zoom)
          return { place: place.name, center: place.center, zoom: requestedZoom ?? place.zoom }
        }
        if (typeof value.latitude !== "number" || typeof value.longitude !== "number") {
          throw new Error("latitude und longitude müssen Zahlen sein.")
        }
        if (Math.abs(value.latitude) > 90 || Math.abs(value.longitude) > 180) {
          throw new Error("Die Koordinaten liegen außerhalb des gültigen Bereichs.")
        }
        const center: [number, number] = [value.longitude, value.latitude]
        const label = `${value.latitude.toFixed(3)}, ${value.longitude.toFixed(3)}`
        setQuery(label)
        await showLocation(center, label, requestedZoom ?? 13)
        return { center, zoom: requestedZoom ?? 13 }
      },
    })
    register({
      name: "set_snow_layers",
      title: "Schneelayer einstellen",
      description: "Schaltet die sichtbaren FSC- und GFSC-Schneelayer gemeinsam oder einzeln ein und aus.",
      inputSchema: {
        type: "object",
        properties: { fsc: { type: "boolean" }, gfsc: { type: "boolean" } },
        minProperties: 1,
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute(input) {
        if (!input || typeof input !== "object") throw new Error("Mindestens ein Layer-Status fehlt.")
        const value = input as Record<string, unknown>
        if (value.fsc !== undefined && typeof value.fsc !== "boolean") throw new Error("fsc muss boolean sein.")
        if (value.gfsc !== undefined && typeof value.gfsc !== "boolean") throw new Error("gfsc muss boolean sein.")
        if (value.fsc === undefined && value.gfsc === undefined) throw new Error("Mindestens ein Layer-Status fehlt.")
        const next = {
          FSC: typeof value.fsc === "boolean" ? value.fsc : productsRef.current.FSC,
          GFSC: typeof value.gfsc === "boolean" ? value.gfsc : productsRef.current.GFSC,
        }
        productsRef.current = next
        setProducts(next)
        return { fsc: next.FSC, gfsc: next.GFSC }
      },
    })
    register({
      name: "read_selected_snow_cell",
      title: "Ausgewählte Schneekachel lesen",
      description: "Liest die Messwerte und Aktualität des aktuell ausgewählten Schneeabschnitts.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute(input) {
        if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).length > 0) {
          throw new Error("Dieses Werkzeug erwartet ein leeres Objekt.")
        }
        return selectedRef.current ? { ...selectedRef.current.properties } : { selected: null }
      },
    })
    return () => lifecycle.abort()
  }, [showLocation])

  const changeBasemap = (next: BasemapMode) => {
    if (next === basemap) return
    setBasemap(next)
    basemapRef.current = next
    const map = mapRef.current
    if (!map) return
    // Object styles can finish loading synchronously, so listen before switching.
    map.once("style.load", () => restoreSnowOverlay(map))
    map.setStyle(baseStyle(next))
  }

  const searchLocation = async (event: FormEvent) => {
    event.preventDefault()
    const value = query.trim()
    if (!value) return
    setSearchBusy(true)
    setSearchError("")
    try {
      const normalized = value.toLocaleLowerCase("de")
      const place = alpinePlaces.find((item) => {
        const name = item.name.toLocaleLowerCase("de")
        return name.includes(normalized) || normalized.includes(name)
      })
      if (place) {
        await showLocation(place.center, place.name, place.zoom)
        return
      }
      const coordinates = value.split(/[;,\s]+/).map(Number)
      if (coordinates.length === 2 && coordinates.every(Number.isFinite)) {
        const [latitude, longitude] = coordinates
        if (Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180) {
          await showLocation([longitude, latitude], `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`, 13.2)
          return
        }
      }
      const match = await geocodeAddress(value)
      await showLocation([match.longitude, match.latitude], match.display_name, 13.2)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Suche fehlgeschlagen."
      setSearchError(message)
    } finally {
      setSearchBusy(false)
    }
  }

  const locate = () => {
    if (!navigator.geolocation) {
      setSearchError("Standort wird nicht unterstützt")
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => { void showLocation([coords.longitude, coords.latitude], "Aktueller Standort", 13.2) },
      () => setSearchError("Standort konnte nicht geladen werden"),
      { enableHighAccuracy: true, timeout: 8_000 },
    )
  }

  const reloadHere = () => {
    const point = lastPointRef.current ?? locationRef.current.center
    void prepareArea(point, "Aktualisiert")
  }

  if (!viewStarted) {
    return (
      <main className="start-screen">
        <div className="start-brand brand-lockup" aria-label="Snow Atlas">
          <span className="brand-mark"><MountainSnow aria-hidden="true" /></span>
          <span className="brand-name">Snow <b>Atlas</b></span>
        </div>
        <section className="start-card" aria-labelledby="start-title">
          <p className="eyebrow">Schnee vor der Tour prüfen</p>
          <h1 id="start-title">Welchen Ort möchtest du ansehen?</h1>
          <p className="start-copy">Suche nach einem Ort, einer Adresse oder gib Koordinaten ein.</p>
          <form className="start-search" onSubmit={searchLocation}>
            <Search aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="z. B. Zugspitze oder 47.53, 11.11"
              aria-label="Ort, Adresse oder Koordinaten suchen"
            />
            <Button type="submit" disabled={searchBusy}>{searchBusy ? "Suche …" : "Karte öffnen"}</Button>
          </form>
          {searchError ? <p className="start-error" role="alert">{searchError}</p> : null}
          <button
            className="example-search"
            type="button"
            onClick={() => {
              setQuery("Farchant")
              void showLocation([11.112, 47.531], "Farchant", 13.2)
            }}
          >
            Beispiel: Farchant · Hoher Fricken
          </button>
        </section>
        <p className="start-source">WEkEO FSC/GFSC · Copernicus Sentinel‑2 · 20/60 m Quelldaten</p>
      </main>
    )
  }

  const statusLabel = {
    idle: "Bereit",
    loading: "Lade Schneedaten …",
    live: "WEkEO · lokale Daten",
    snapshot: "WEkEO · Snapshot",
    preparing: "WEkEO · Download läuft",
    unavailable: "Keine Schneedaten",
  }[dataMode]

  return (
    <main className="snow-app">
      <div ref={containerRef} className="snow-map" aria-label="Interaktive Karte der Schneebedeckung in den Alpen" />
      <div className="map-vignette" aria-hidden="true" />

      <header className="topbar">
        <div className="brand-lockup" aria-label="Snow Atlas">
          <span className="brand-mark"><MountainSnow aria-hidden="true" /></span>
          <span className="brand-name">Snow <b>Atlas</b></span>
        </div>
        <form className="search-control" onSubmit={searchLocation}>
          <Search aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ort oder 47.26, 11.40"
            aria-label="Ort oder Koordinaten suchen"
            list="alpine-places"
          />
          <datalist id="alpine-places">
            {alpinePlaces.map((place) => <option key={place.name} value={place.name} />)}
          </datalist>
          <kbd>↵</kbd>
        </form>
        <div className="top-status">
          <span className={dataMode === "live" || dataMode === "snapshot" ? "status-pulse is-live" : "status-pulse"} />
          <span>{statusLabel}</span>
        </div>
      </header>

      <section ref={layerPanelRef} aria-label="Layer" className={layersOpen ? "layer-panel glass-panel is-open" : "layer-panel glass-panel"}>
        <button
          type="button"
          className="panel-heading layer-toggle"
          onClick={() => setLayersOpen((open) => !open)}
          aria-expanded={layersOpen}
          aria-controls="layer-menu"
        >
          <span className="panel-icon"><Layers3 aria-hidden="true" /></span>
          <span className="layer-toggle-text">
            <span className="eyebrow">Layer</span>
            <b>Schneebedeckung</b>
          </span>
          <span className="layer-toggle-state">{activeLayerLabel}</span>
          <ChevronDown className="layer-toggle-chevron" aria-hidden="true" />
        </button>
        <div id="layer-menu" className="layer-menu" hidden={!layersOpen}>
          <div className="layer-list">
            <label className="layer-row">
              <span className="layer-swatch fsc"><Snowflake aria-hidden="true" /></span>
              <span><b>FSC</b><small>Tagesaufnahme · 20 m</small></span>
              <Switch checked={products.FSC} onCheckedChange={(checked) => setProducts((current) => ({ ...current, FSC: checked }))} aria-label="FSC-Layer anzeigen" />
            </label>
            <label className="layer-row">
              <span className="layer-swatch gfsc"><Snowflake aria-hidden="true" /></span>
              <span><b>GFSC</b><small>Lückengefüllt, 7 Tage · 60 m</small></span>
              <Switch checked={products.GFSC} onCheckedChange={(checked) => setProducts((current) => ({ ...current, GFSC: checked }))} aria-label="GFSC-Layer anzeigen" />
            </label>
            <label className="layer-row">
              <span className="layer-swatch cloud"><Cloud aria-hidden="true" /></span>
              <span><b>Wolken</b><small>Schraffiert, wo nichts sichtbar ist</small></span>
              <Switch checked={showClouds} onCheckedChange={setShowClouds} aria-label="Wolken anzeigen" />
            </label>
          </div>
          {products.FSC && products.GFSC ? (
            <p className="layer-note">FSC hat Vorrang. Wo FSC Wolken sieht, füllt GFSC auf.</p>
          ) : null}
          <div className="coverage-summary">
            <div><span>Schneefläche im Ausschnitt</span><strong>{percent(snowAreaPercent)}</strong></div>
            <div className="coverage-track"><span style={{ width: `${snowAreaPercent ?? 0}%` }} /></div>
            {areaSummary && sourceKind === "raster" ? (
              <small>Wolken {areaSummary.cloud_percent}% · keine Daten {areaSummary.nodata_percent}%</small>
            ) : null}
          </div>
        </div>
      </section>

      <nav className="map-tools glass-panel" aria-label="Kartensteuerung">
        <Button type="button" variant="ghost" size="icon" onClick={() => mapRef.current?.zoomIn()} aria-label="Hineinzoomen"><Plus /></Button>
        <Button type="button" variant="ghost" size="icon" onClick={() => mapRef.current?.zoomOut()} aria-label="Herauszoomen"><Minus /></Button>
        <span className="tool-divider" />
        <Button type="button" variant="ghost" size="icon" onClick={locate} aria-label="Meinen Standort zeigen"><LocateFixed /></Button>
      </nav>

      <div className="basemap-switch glass-panel" aria-label="Basiskarte wählen">
        <Button type="button" size="sm" variant="ghost" className={basemap === "satellite" ? "is-active" : ""} onClick={() => changeBasemap("satellite")} aria-pressed={basemap === "satellite"}><Crosshair /> Satellit</Button>
        <Button type="button" size="sm" variant="ghost" className={basemap === "map" ? "is-active" : ""} onClick={() => changeBasemap("map")} aria-pressed={basemap === "map"}><MapIcon /> Karte</Button>
      </div>

      <aside className="snow-detail glass-panel" aria-live="polite">
        {dataMode === "loading" || dataMode === "idle" ? (
          <div className="detail-state">
            <LoaderCircle className="spin" />
            <b>Schneedaten werden abgefragt …</b>
            <span>{statusMessage}</span>
          </div>
        ) : dataMode === "preparing" ? (
          <div className="detail-state">
            <CloudDownload />
            <b>Lade Sentinel-2-Schneedaten für diesen Ort</b>
            <span>Hier lag noch nichts lokal vor. Die neueste FSC- und GFSC-Aufnahme wird von WEkEO geladen, meist in 1–3 Minuten.</span>
            <span className="detail-progress"><LoaderCircle className="spin" /> {statusMessage}</span>
          </div>
        ) : dataMode === "unavailable" ? (
          <div className="detail-state">
            <MapIcon />
            <b>Keine Schneedaten für diesen Ort</b>
            <span>{statusMessage}</span>
            {sourceKind === "raster" ? (
              <Button type="button" onClick={reloadHere}><RefreshCw /> Erneut versuchen</Button>
            ) : (
              <Button type="button" onClick={() => void showLocation([11.112, 47.531], "Farchant", 13.2)}>Farchant öffnen</Button>
            )}
          </div>
        ) : !selected ? (
          <div className="detail-state">
            <Crosshair />
            <b>Keine Daten an diesem Punkt</b>
            <span>Klicke auf einen Bereich ohne graue Abdunklung, um Schneewerte abzufragen.</span>
          </div>
        ) : (
          <>
            <div className="detail-topline">
              <span className={`product-chip ${selected.product.toLowerCase()}`}>{selected.product}</span>
              <span className="detail-age"><Clock3 /> {ageLabel(selected.observed_at)}</span>
            </div>
            <h2>
              {selected.coverage_percent == null
                ? "Von Wolken verdeckt"
                : selected.coverage_percent < 0.1 ? "Kein Schnee erkannt" : "Schnee erkannt"}
            </h2>
            <p className="cell-id">Abschnitt {selected.cell_id}</p>
            <div className="coverage-value">
              <span>{selected.coverage_percent ?? "—"}</span><sup>%</sup><p>mit Schnee bedeckt</p>
            </div>
            <div className="detail-meter"><span style={{ width: `${selected.coverage_percent ?? 0}%` }} /></div>
            {usedGapFill ? <p className="detail-note">FSC ist hier bewölkt. Der Wert stammt aus dem lückengefüllten GFSC.</p> : null}
            <dl className="detail-grid">
              <div><dt><Clock3 /> Aufnahme</dt><dd>{observedLabel(selected.observed_at)}</dd></div>
              <div>
                <dt><Cloud /> {selected.product === "GFSC" ? "AT-Zeitraum" : "Wolken"}</dt>
                <dd>{selected.product === "GFSC" ? `${shortDate(selected.oldest_observed_at)}–${shortDate(selected.observed_at)}` : percent(selected.cloud_percent)}</dd>
              </div>
              <div><dt><Database /> Quelle / Abschnitt</dt><dd>{selected.resolution_m} m / {selected.cell_size_m ?? "—"} m</dd></div>
              <div><dt><MountainSnow /> Gültige Pixel</dt><dd>{percent(selected.valid_percent)}</dd></div>
            </dl>
            {dataMode === "live" ? (
              <button type="button" className="detail-refresh" onClick={reloadHere}>
                <RefreshCw /> Neueste Aufnahmen für diesen Ort laden
              </button>
            ) : null}
          </>
        )}
      </aside>

      <div className="legend glass-panel" aria-label="Legende">
        <span className="legend-title">Schnee %</span>
        {snowClasses.map((item) => (
          <span key={item.label} className="legend-item"><i style={{ background: item.color }} />{item.label}</span>
        ))}
        {showClouds ? <span className="legend-item"><i className="legend-cloud" />Wolken</span> : null}
        <span className="legend-item"><i className="legend-nodata" />keine Daten</span>
      </div>
      {searchError ? <output className="search-feedback" aria-live="polite">{searchError}</output> : null}
    </main>
  )
}
