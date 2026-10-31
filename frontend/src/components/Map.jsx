import { useEffect, useState } from 'react';
import L from 'leaflet';
import { MapContainer, Marker, Popup, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

// Vite does not resolve Leaflet's default marker image paths, so give the marker explicit icons.
const pin = new L.Icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

// If the first tile server blocks or fails, switch to the next one instead of leaving a blank grid.
const TILE_SOURCES = [
  { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', attribution: '&copy; OpenStreetMap contributors' },
  { url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png', attribution: '&copy; OpenStreetMap, &copy; CARTO' },
  { url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', attribution: 'Esri' },
];

function LocationMarker({ onSelect, lat, lng }) {
  const map = useMap();
  useMapEvents({
    click(e) {
      onSelect({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });

  // Depend on the numbers, not on an array that is re-created on every render. Before, every re-render re-centred
  // the map, so it snapped back whenever the user tried to pan.
  useEffect(() => {
    map.setView([lat, lng], map.getZoom());
  }, [map, lat, lng]);

  useEffect(() => {
    const id = window.setTimeout(() => map.invalidateSize(), 200);
    return () => window.clearTimeout(id);
  }, [map]);

  return null;
}

export default function Map({ onSelect, selected }) {
  const [lat, lng] = selected || [27.1767, 78.0081];
  const [tileIndex, setTileIndex] = useState(0);
  const [tileErrors, setTileErrors] = useState(0);
  const source = TILE_SOURCES[tileIndex];

  const handleTileError = () => {
    const next = tileErrors + 1;
    if (next >= 6 && tileIndex < TILE_SOURCES.length - 1) {
      setTileIndex(tileIndex + 1);
      setTileErrors(0);
    } else {
      setTileErrors(next);
    }
  };

  return (
    <MapContainer center={[lat, lng]} zoom={8} scrollWheelZoom className="h-[360px] w-full rounded-2xl">
      <TileLayer key={tileIndex} attribution={source.attribution} url={source.url} eventHandlers={{ tileerror: handleTileError }} />
      <LocationMarker onSelect={onSelect} lat={lat} lng={lng} />
      <Marker position={[lat, lng]} icon={pin}><Popup>Selected location</Popup></Marker>
    </MapContainer>
  );
}
