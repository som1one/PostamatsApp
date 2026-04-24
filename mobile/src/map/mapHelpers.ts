import * as Location from "expo-location";
import { Platform } from "react-native";

import type { City, Locker } from "../types";

export type GeoPoint = {
  latitude: number;
  longitude: number;
};

export type MapRegion = GeoPoint & {
  latitudeDelta: number;
  longitudeDelta: number;
};

export type GeoLocationState = "idle" | "loading" | "ready" | "denied" | "unavailable";

export const DEFAULT_SPB_REGION: MapRegion = {
  latitude: 59.93873,
  longitude: 30.316229,
  latitudeDelta: 0.18,
  longitudeDelta: 0.12,
};

export function lockerGeoPoint(locker: Locker): GeoPoint | null {
  if (typeof locker.lat !== "number" || typeof locker.lon !== "number") {
    return null;
  }

  return {
    latitude: locker.lat,
    longitude: locker.lon,
  };
}

export function averageGeoPoint(points: GeoPoint[]): GeoPoint | null {
  if (!points.length) {
    return null;
  }

  const totals = points.reduce(
    (acc, point) => ({
      latitude: acc.latitude + point.latitude,
      longitude: acc.longitude + point.longitude,
    }),
    { latitude: 0, longitude: 0 },
  );

  return {
    latitude: totals.latitude / points.length,
    longitude: totals.longitude / points.length,
  };
}

export function createFocusRegion(point: GeoPoint, zoom = 0.032): MapRegion {
  return {
    latitude: point.latitude,
    longitude: point.longitude,
    latitudeDelta: zoom,
    longitudeDelta: zoom * 0.72,
  };
}

export function createBoundsRegion(points: GeoPoint[]): MapRegion {
  if (!points.length) {
    return DEFAULT_SPB_REGION;
  }

  if (points.length === 1) {
    return createFocusRegion(points[0], 0.05);
  }

  const latitudes = points.map((point) => point.latitude);
  const longitudes = points.map((point) => point.longitude);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLon = Math.min(...longitudes);
  const maxLon = Math.max(...longitudes);
  const center = averageGeoPoint(points) ?? DEFAULT_SPB_REGION;

  return {
    latitude: center.latitude,
    longitude: center.longitude,
    latitudeDelta: Math.max(0.05, (maxLat - minLat) * 1.8),
    longitudeDelta: Math.max(0.05, (maxLon - minLon) * 1.7),
  };
}

export function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function haversineDistanceKm(from: GeoPoint, to: GeoPoint) {
  const earthRadiusKm = 6371;
  const toRad = (degrees: number) => (degrees * Math.PI) / 180;
  const deltaLat = toRad(to.latitude - from.latitude);
  const deltaLon = toRad(to.longitude - from.longitude);
  const latFrom = toRad(from.latitude);
  const latTo = toRad(to.latitude);
  const arc =
    Math.sin(deltaLat / 2) ** 2 +
    Math.sin(deltaLon / 2) ** 2 * Math.cos(latFrom) * Math.cos(latTo);
  return earthRadiusKm * 2 * Math.atan2(Math.sqrt(arc), Math.sqrt(1 - arc));
}

export async function resolveUserGeoPoint(): Promise<{ point: GeoPoint | null; state: GeoLocationState }> {
  if (Platform.OS === "web") {
    const browserScope = globalThis as unknown as {
      navigator?: {
        geolocation?: {
          getCurrentPosition: (
            success: (position: { coords: { latitude: number; longitude: number } }) => void,
            error?: (positionError: { code?: number }) => void,
            options?: { enableHighAccuracy?: boolean; timeout?: number; maximumAge?: number },
          ) => void;
        };
      };
    };
    const geolocation = browserScope.navigator?.geolocation;
    if (!geolocation) {
      return { point: null, state: "unavailable" };
    }

    return new Promise((resolve) => {
      geolocation.getCurrentPosition(
        (position) => {
          resolve({
            point: {
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
            },
            state: "ready",
          });
        },
        (positionError) => {
          resolve({
            point: null,
            state: positionError?.code === 1 ? "denied" : "unavailable",
          });
        },
        {
          enableHighAccuracy: false,
          timeout: 12000,
          maximumAge: 60000,
        },
      );
    });
  }

  try {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== "granted") {
      return { point: null, state: "denied" };
    }

    const lastKnown = await Location.getLastKnownPositionAsync();
    if (lastKnown?.coords) {
      return {
        point: {
          latitude: lastKnown.coords.latitude,
          longitude: lastKnown.coords.longitude,
        },
        state: "ready",
      };
    }

    const current = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return {
      point: {
        latitude: current.coords.latitude,
        longitude: current.coords.longitude,
      },
      state: "ready",
    };
  } catch {
    return { point: null, state: "unavailable" };
  }
}

export function findNearestCityIdByLockers(userPoint: GeoPoint, cities: City[], lockers: Locker[]) {
  if (!cities.length || !lockers.length) {
    return "";
  }

  const citySet = new Set(cities.map((city) => city.id));
  let bestCityId = "";
  let bestDistance = Number.POSITIVE_INFINITY;

  lockers.forEach((locker) => {
    if (!citySet.has(locker.cityId)) {
      return;
    }
    const lockerPoint = lockerGeoPoint(locker);
    if (!lockerPoint) {
      return;
    }

    const distance = haversineDistanceKm(userPoint, lockerPoint);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestCityId = locker.cityId;
    }
  });

  return bestCityId;
}

export function formatDistanceBadge(distanceKm?: number | null) {
  if (typeof distanceKm !== "number" || !Number.isFinite(distanceKm)) {
    return "—";
  }

  if (distanceKm < 1) {
    return distanceKm.toFixed(1).replace(".", ",");
  }

  if (distanceKm < 10) {
    return distanceKm.toFixed(1).replace(".", ",");
  }

  return String(Math.round(distanceKm));
}
