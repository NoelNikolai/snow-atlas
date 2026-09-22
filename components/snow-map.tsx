"use client"

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Clock3,
  Cloud,
  Crosshair,
  Database,
  Layers3,
  LocateFixed,
  Map as MapIcon,
  Minus,
  MountainSnow,
  Plus,
  Search,
  Snowflake,
} from "lucide-react"
import {
  AttributionControl,
  Map as MapLibreMap,
  Marker,
  type GeoJSONSource,
  type StyleSpecification,
} from "maplibre-gl"

import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import {
  alpinePlaces,
  demoSnowData,
  type SnowCellProperties,
  type SnowFeatureCollection,
  type SnowProduct,
} from "@/lib/snow-data"

type BasemapMode = "satellite" | "map"
type DataMode = "demo" | "snapshot" | "live"

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

const snowLayerIds = ["snow-fill", "snow-edge-outer", "snow-edge-inner"]
const farchantSnapshotBounds = [11.045, 47.485, 11.225, 47.575] as const

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

function addSnowLayers(map: MapLibreMap, data: SnowFeatureCollection) {
  if (map.getSource("snow-cells")) return
  map.addSource("snow-cells", { type: "geojson", data, promoteId: "cell_id" })

  map.addLayer({
    id: "snow-fill",
    type: "fill",
    source: "snow-cells",
    paint: {
      "fill-color": [
        "interpolate", ["linear"], ["get", "coverage_percent"],
        0, "#8cd6eb", 55, "#c9f0f7", 100, "#ffffff",
      ],
      "fill-opacity": [
        "interpolate", ["linear"], ["get", "coverage_percent"],
        0, 0.035, 1, 0.1, 20, 0.18, 100, 0.52,
      ],
      "fill-outline-color": "rgba(255,255,255,0)",
    },
  })
  map.addLayer({
    id: "snow-edge-outer",
    type: "line",
    source: "snow-cells",
    paint: {
      "line-color": "rgba(255,255,255,0.92)",
      "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.2, 14, 4],
      "line-opacity": ["interpolate", ["linear"], ["get", "coverage_percent"], 0, 0.11, 1, 0.36, 100, 0.76],
      "line-blur": 0.3,
    },
  })
  map.addLayer({
    id: "snow-edge-inner",
    type: "line",
    source: "snow-cells",
    paint: {
      "line-color": ["match", ["get", "product"], "FSC", "#eafcff", "#6ee7ff"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.5, 14, 2.2],
      "line-opacity": ["interpolate", ["linear"], ["get", "coverage_percent"], 0, 0.08, 1, 0.55, 100, 1],
      "line-dasharray": [1.2, 1.5],
    },
  })
  map.addLayer({
    id: "snow-selected",
    type: "line",
    source: "snow-cells",
    filter: ["==", ["get", "cell_id"], ""],
    paint: {
      "line-color": "#ffffff",
      "line-width": 3,
      "line-offset": 4,
      "line-opacity": 0.95,
    },
  })
}

function toProperties(properties: Record<string, unknown>): SnowCellProperties {
  return {
    cell_id: String(properties.cell_id),
    region_name: String(properties.region_name),
    product: String(properties.product) as SnowProduct,
    coverage_percent: Number(properties.coverage_percent),
    observed_at: String(properties.observed_at),
    oldest_observed_at: properties.oldest_observed_at == null ? null : String(properties.oldest_observed_at),
    valid_percent: properties.valid_percent == null ? null : Number(properties.valid_percent),
    snow_pixel_percent: properties.snow_pixel_percent == null ? null : Number(properties.snow_pixel_percent),
    cloud_percent: properties.cloud_percent == null ? null : Number(properties.cloud_percent),
    resolution_m: Number(properties.resolution_m),
    cell_size_m: properties.cell_size_m == null ? null : Number(properties.cell_size_m),
    source_layer: properties.source_layer == null ? null : String(properties.source_layer),
    product_date: properties.product_date == null ? null : String(properties.product_date),
    elevation_m: properties.elevation_m == null ? null : Number(properties.elevation_m),
    confidence: String(properties.confidence) as "hoch" | "mittel",
  }
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

export function SnowMap() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const markersRef = useRef<Marker[]>([])
  const [viewStarted, setViewStarted] = useState(false)
  const [snowData, setSnowData] = useState<SnowFeatureCollection>(demoSnowData)
  const [selected, setSelected] = useState<SnowCellProperties>(demoSnowData.features[0].properties)
  const [basemap, setBasemap] = useState<BasemapMode>("map")
  const [products, setProducts] = useState<Record<SnowProduct, boolean>>({ FSC: true, GFSC: false })
  const [query, setQuery] = useState("")
  const [searchHint, setSearchHint] = useState("Ort oder Koordinaten")
  const [dataMode, setDataMode] = useState<DataMode>("demo")
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchError, setSearchError] = useState("")
  const productsRef = useRef(products)
  const snowDataRef = useRef(snowData)
  const selectedRef = useRef(selected)
  const locationRef = useRef<{ center: [number, number]; zoom: number }>({ center: [11.1325, 47.531], zoom: 13.1 })

  const totalCoverage = useMemo(() => {
    const visible = snowData.features.filter((feature) => products[feature.properties.product])
    if (!visible.length) return 0
    const sum = visible.reduce((value, feature) => value + feature.properties.coverage_percent, 0)
    return Math.round(sum / visible.length)
  }, [products, snowData])

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
    const filter = productFilter(productsRef.current)
    snowLayerIds.forEach((id) => {
      if (map.getLayer(id)) map.setFilter(id, filter)
    })
  }, [])

  const restoreSnowOverlay = useCallback((map: MapLibreMap) => {
    addSnowLayers(map, snowDataRef.current)
    applyLayerState(map)
    if (map.getLayer("snow-selected")) {
      map.setFilter("snow-selected", ["==", ["get", "cell_id"], selectedRef.current.cell_id])
    }
  }, [applyLayerState])

  const showLocation = useCallback(async (center: [number, number], label: string, zoom = 13.2) => {
    const mapCenter: [number, number] = insideFarchantSnapshot(center) ? [11.1325, 47.531] : center
    locationRef.current = { center: mapCenter, zoom: insideFarchantSnapshot(center) ? 13.1 : zoom }
    setViewStarted(true)
    setSearchHint(label)
    setSearchError("")

    requestAnimationFrame(() => {
      mapRef.current?.resize()
      if (mapRef.current) showFocusMarkers(mapRef.current, center)
      mapRef.current?.flyTo({ center: mapCenter, zoom: locationRef.current.zoom, pitch: 30, bearing: -8, duration: 1_150 })
    })

    const displayCollection = (collection: SnowFeatureCollection, mode: DataMode) => {
      snowDataRef.current = collection
      setSnowData(collection)
      setDataMode(mode)
      const source = mapRef.current?.getSource("snow-cells") as GeoJSONSource | undefined
      source?.setData(collection)
      if (!collection.features.length) return
      const nearest = collection.features.reduce((best, feature) => {
        const point = feature.geometry.coordinates[0]?.[0] ?? center
        const bestPoint = best.geometry.coordinates[0]?.[0] ?? center
        const distance = (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2
        const bestDistance = (bestPoint[0] - center[0]) ** 2 + (bestPoint[1] - center[1]) ** 2
        return distance < bestDistance ? feature : best
      })
      setSelected(nearest.properties)
    }

    const loadFallback = async () => {
      if (insideFarchantSnapshot(center)) {
        try {
          const response = await fetch("/data/farchant-snow.geojson")
          if (!response.ok) throw new Error("Snapshot unavailable")
          displayCollection(await response.json() as SnowFeatureCollection, "snapshot")
          setSearchHint(`${label} · WEkEO-Snapshot`)
          return
        } catch {
          // The clearly labelled demo below remains usable offline.
        }
      }
      displayCollection(demoSnowData, "demo")
      setSearchHint(`${label} · Demo-Daten`)
    }

    const apiBase = snowApiBase()
    if (!apiBase) {
      await loadFallback()
      return
    }

    const params = new URLSearchParams({
      west: String(center[0] - 0.09), south: String(center[1] - 0.07),
      east: String(center[0] + 0.09), north: String(center[1] + 0.07),
    })
    try {
      const response = await fetch(`${apiBase}/api/v1/snow/cells?${params}`)
      if (!response.ok) throw new Error("Snow API unavailable")
      const payload = await response.json() as SnowFeatureCollection
      if (!payload.features.length) {
        await loadFallback()
        return
      }
      displayCollection(payload, "live")
    } catch {
      await loadFallback()
    }
  }, [showFocusMarkers])

  useEffect(() => {
    if (!viewStarted || !containerRef.current || mapRef.current) return
    const map = new MapLibreMap({
      container: containerRef.current,
      style: baseStyle("map"),
      center: locationRef.current.center,
      zoom: locationRef.current.zoom,
      pitch: 28,
      bearing: -7,
      attributionControl: false,
      maxZoom: 17,
    })
    mapRef.current = map
    map.addControl(new AttributionControl({ compact: true }), "bottom-right")
    map.on("load", () => {
      restoreSnowOverlay(map)
      showFocusMarkers(map, locationRef.current.center)
    })
    map.on("click", "snow-fill", (event) => {
      const feature = event.features?.[0]
      if (feature?.properties) setSelected(toProperties(feature.properties))
    })
    map.on("mouseenter", "snow-fill", () => { map.getCanvas().style.cursor = "pointer" })
    map.on("mouseleave", "snow-fill", () => { map.getCanvas().style.cursor = "grab" })
    return () => {
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current = []
      map.remove()
      mapRef.current = null
    }
  }, [restoreSnowOverlay, showFocusMarkers, viewStarted])

  useEffect(() => { snowDataRef.current = snowData }, [snowData])
  useEffect(() => { selectedRef.current = selected }, [selected])
  useEffect(() => {
    productsRef.current = products
    const map = mapRef.current
    if (map?.isStyleLoaded()) applyLayerState(map)
  }, [applyLayerState, products])
  useEffect(() => {
    const map = mapRef.current
    if (map?.getLayer("snow-selected")) {
      map.setFilter("snow-selected", ["==", ["get", "cell_id"], selected.cell_id])
    }
  }, [selected.cell_id])

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
        const map = mapRef.current
        if (map?.isStyleLoaded()) applyLayerState(map)
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
        return { ...selectedRef.current }
      },
    })
    return () => lifecycle.abort()
  }, [applyLayerState, showLocation])

  const changeBasemap = (next: BasemapMode) => {
    if (next === basemap) return
    setBasemap(next)
    const map = mapRef.current
    if (!map) return
    map.setStyle(baseStyle(next))
    map.once("style.load", () => restoreSnowOverlay(map))
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
      const apiBase = snowApiBase()
      let match: { display_name: string; latitude: number; longitude: number }
      if (apiBase) {
        try {
          const response = await fetch(`${apiBase}/api/v1/geocode/search?q=${encodeURIComponent(value)}`)
          if (!response.ok) throw new Error("Local geocoder unavailable")
          match = await response.json() as typeof match
        } catch {
          match = await geocodeAddress(value)
        }
      } else {
        match = await geocodeAddress(value)
      }
      await showLocation([match.longitude, match.latitude], match.display_name, 13.2)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Suche fehlgeschlagen."
      setSearchError(message)
      setSearchHint(message)
    } finally {
      setSearchBusy(false)
    }
  }

  const locate = () => {
    if (!navigator.geolocation) {
      setSearchHint("Standort wird nicht unterstützt")
      return
    }
    setSearchHint("Standort wird gesucht …")
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => { void showLocation([coords.longitude, coords.latitude], "Aktueller Standort", 13.2) },
      () => setSearchHint("Standort konnte nicht geladen werden"),
      { enableHighAccuracy: true, timeout: 8_000 },
    )
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
              placeholder="z. B. Farchant oder 47.53, 11.11"
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
          <span className={dataMode !== "demo" ? "status-pulse is-live" : "status-pulse"} />
          <span>{dataMode === "live" ? "WEkEO · lokale Daten" : dataMode === "snapshot" ? "WEkEO · Snapshot" : "MVP · Demo-Daten"}</span>
        </div>
      </header>

      <section className="layer-panel glass-panel" aria-labelledby="layers-title">
        <div className="panel-heading">
          <span className="panel-icon"><Layers3 aria-hidden="true" /></span>
          <div><p className="eyebrow">Layer</p><h1 id="layers-title">Schneebedeckung</h1></div>
        </div>
        <div className="layer-list">
          <label className="layer-row">
            <span className="layer-swatch fsc"><Snowflake aria-hidden="true" /></span>
            <span><b>FSC</b><small>Fraktionaler Schnee · 20 m</small></span>
            <Switch checked={products.FSC} onCheckedChange={(checked) => setProducts((current) => ({ ...current, FSC: checked }))} aria-label="FSC-Layer anzeigen" />
          </label>
          <label className="layer-row">
            <span className="layer-swatch gfsc"><Snowflake aria-hidden="true" /></span>
            <span><b>GFSC</b><small>Gap-filled Schnee · 60 m</small></span>
            <Switch checked={products.GFSC} onCheckedChange={(checked) => setProducts((current) => ({ ...current, GFSC: checked }))} aria-label="GFSC-Layer anzeigen" />
          </label>
        </div>
        <div className="coverage-summary">
          <div><span>Ø sichtbare Kacheln</span><strong>{totalCoverage}%</strong></div>
          <div className="coverage-track"><span style={{ width: `${totalCoverage}%` }} /></div>
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
        <div className="detail-topline">
          <span className={`product-chip ${selected.product.toLowerCase()}`}>{selected.product}</span>
          <span className="detail-age"><Clock3 /> {ageLabel(selected.observed_at)}</span>
        </div>
        <h2>{selected.region_name}</h2>
        <p className="cell-id">Abschnitt {selected.cell_id}</p>
        <div className="coverage-value"><span>{selected.coverage_percent}</span><sup>%</sup><p>mit Schnee bedeckt</p></div>
        <div className="detail-meter"><span style={{ width: `${selected.coverage_percent}%` }} /></div>
        <dl className="detail-grid">
          <div><dt><Clock3 /> Aufnahme</dt><dd>{observedLabel(selected.observed_at)}</dd></div>
          <div>
            <dt><Cloud /> {selected.product === "GFSC" ? "AT-Zeitraum" : "Wolken"}</dt>
            <dd>{selected.product === "GFSC" ? `${shortDate(selected.oldest_observed_at)}–${shortDate(selected.observed_at)}` : selected.cloud_percent == null ? "—" : `${selected.cloud_percent}%`}</dd>
          </div>
          <div><dt><Database /> Quelle / Abschnitt</dt><dd>{selected.resolution_m} m / {selected.cell_size_m ?? "—"} m</dd></div>
          <div><dt><MountainSnow /> Gültige Pixel</dt><dd>{selected.valid_percent == null ? "—" : `${selected.valid_percent}%`}</dd></div>
        </dl>
      </aside>

      <div className="legend glass-panel" aria-label="Legende"><span>wenig</span><i className="legend-gradient" /><span>viel Schnee</span></div>
      {searchError ? <output className="search-feedback" aria-live="polite">{searchError}</output> : null}
    </main>
  )
}
