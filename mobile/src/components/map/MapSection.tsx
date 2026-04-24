import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";

import {
  DEFAULT_SPB_REGION,
  averageGeoPoint,
  clampNumber,
  createBoundsRegion,
  createFocusRegion,
  formatDistanceBadge,
  haversineDistanceKm,
  lockerGeoPoint,
  type GeoLocationState,
  type GeoPoint,
} from "../../map/mapHelpers";
import {
  YANDEX_MAPS_API_KEY,
  buildLockerBalloonHtml,
  getYandexMapsApi,
  loadYandexMapsScript,
  type YandexMapInstance,
} from "../../map/yandex";
import { MAP_CARD_GAP, MAP_CARD_WIDTH, palette, styles } from "../../styles/appStyles";
import type { Locker, LockerAvailabilityItem } from "../../types";
import { statusLabel } from "../../utils/appFormatters";

const NativeMaps = Platform.OS === "web" ? null : require("react-native-maps");
const NativeMapView = NativeMaps?.default ?? null;
const NativeMarker = NativeMaps?.Marker ?? null;

export function MapTab({
  cityName,
  lockers,
  selectedLockerId,
  onSelectLocker,
  onBackHome,
  loading,
  errorMessage,
  userLocation,
  locationState,
  lockerAvailabilityById,
}: {
  cityName: string;
  lockers: Locker[];
  selectedLockerId: string;
  onSelectLocker: (lockerId: string) => void;
  onBackHome: () => void;
  loading: boolean;
  errorMessage: string;
  userLocation: GeoPoint | null;
  locationState: GeoLocationState;
  lockerAvailabilityById: Record<string, LockerAvailabilityItem[]>;
}) {
  const mapRef = useRef<any>(null);
  const cardsRef = useRef<ScrollView | null>(null);

  const mappableLockers = useMemo(() => {
    const points = lockers
      .map((locker) => {
        const point = lockerGeoPoint(locker);
        return point ? { ...locker, point } : null;
      })
      .filter((item): item is Locker & { point: GeoPoint } => Boolean(item));

    const fallbackReference = averageGeoPoint(points.map((item) => item.point));
    const referencePoint = userLocation ?? fallbackReference;

    const withDistance = points.map((locker) => ({
      ...locker,
      distanceKm: referencePoint ? haversineDistanceKm(referencePoint, locker.point) : null,
    }));

    return withDistance.sort((left, right) => {
      const leftDistance = left.distanceKm ?? Number.POSITIVE_INFINITY;
      const rightDistance = right.distanceKm ?? Number.POSITIVE_INFINITY;
      return leftDistance - rightDistance;
    });
  }, [lockers, userLocation]);

  const initialRegion = useMemo(
    () => createBoundsRegion(mappableLockers.map((locker) => locker.point)),
    [mappableLockers],
  );

  const activeLocker =
    mappableLockers.find((locker) => locker.id === selectedLockerId) ??
    mappableLockers[0] ??
    null;
  const activeIndex = activeLocker
    ? Math.max(0, mappableLockers.findIndex((locker) => locker.id === activeLocker.id))
    : -1;
  const locationStatusLabel =
    locationState === "loading"
      ? "Ищем вас"
      : locationState === "ready"
        ? "Рядом с вами"
        : locationState === "denied"
          ? "Без геолокации"
          : cityName;

  useEffect(() => {
    if (!mappableLockers.length) {
      return;
    }

    if (!selectedLockerId || !mappableLockers.some((locker) => locker.id === selectedLockerId)) {
      onSelectLocker(mappableLockers[0].id);
    }
  }, [mappableLockers, onSelectLocker, selectedLockerId]);

  useEffect(() => {
    if (!activeLocker) {
      return;
    }

    cardsRef.current?.scrollTo({
      x: activeIndex * (MAP_CARD_WIDTH + MAP_CARD_GAP),
      animated: true,
    });

    if (Platform.OS !== "web" && mapRef.current && NativeMapView) {
      mapRef.current.animateToRegion(createFocusRegion(activeLocker.point), 320);
    }
  }, [activeIndex, activeLocker]);

  function handleCardsScrollEnd(event: any) {
    const nextIndex = Math.round(
      event.nativeEvent.contentOffset.x / (MAP_CARD_WIDTH + MAP_CARD_GAP),
    );
    const nextLocker = mappableLockers[Math.max(0, Math.min(nextIndex, mappableLockers.length - 1))];
    if (nextLocker && nextLocker.id !== selectedLockerId) {
      onSelectLocker(nextLocker.id);
    }
  }

  if (!mappableLockers.length) {
    return (
      <View style={styles.mapTabShell}>
        <MapBackButton onPress={onBackHome} />
        <View style={styles.mapEmptyState}>
          <Text style={styles.mapEmptyTitle}>Карта пока недоступна</Text>
          <Text style={styles.mapEmptyText}>
            У точек еще нет координат. Как только они появятся, здесь откроется карта и быстрый выбор постамата.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.mapTabShell}>
      <View style={styles.mapSurface}>
        {Platform.OS === "web" || !NativeMapView || !NativeMarker ? (
          <MapFallbackSurface
            cityName={cityName}
            lockers={mappableLockers}
            selectedLockerId={activeLocker?.id ?? ""}
            onSelectLocker={onSelectLocker}
            userLocation={userLocation}
            lockerAvailabilityById={lockerAvailabilityById}
          />
        ) : (
          <NativeMapView
            ref={mapRef}
            style={styles.nativeMap}
            initialRegion={initialRegion}
            mapType={Platform.OS === "ios" ? "mutedStandard" : "standard"}
            showsCompass={false}
            showsTraffic={false}
            toolbarEnabled={false}
            moveOnMarkerPress={false}
            showsPointsOfInterest={false}
            showsBuildings
            showsUserLocation={Boolean(userLocation)}
          >
            {mappableLockers.map((locker) => {
              const active = locker.id === activeLocker?.id;
              return (
                <NativeMarker
                  key={locker.id}
                  coordinate={locker.point}
                  anchor={{ x: 0.5, y: 0.5 }}
                  onPress={() => onSelectLocker(locker.id)}
                  tracksViewChanges={false}
                >
                  <View style={[styles.mapMarker, active && styles.mapMarkerActive]}>
                    <MapMarkerGlyph active={active} />
                  </View>
                </NativeMarker>
              );
            })}
          </NativeMapView>
        )}

        <View style={styles.mapTopOverlay} pointerEvents="box-none">
          <View style={styles.mapTopRow}>
            <MapBackButton onPress={onBackHome} />
            <View style={styles.mapStatusPill}>
              <Text style={styles.mapStatusPillText}>{locationStatusLabel}</Text>
            </View>
          </View>

          <ScrollView
            ref={cardsRef}
            horizontal
            showsHorizontalScrollIndicator={false}
            snapToInterval={MAP_CARD_WIDTH + MAP_CARD_GAP}
            decelerationRate="fast"
            contentContainerStyle={styles.mapCardsRow}
            onMomentumScrollEnd={handleCardsScrollEnd}
          >
            {mappableLockers.map((locker) => {
              const active = locker.id === activeLocker?.id;
              return (
                <Pressable
                  key={locker.id}
                  style={[styles.mapLockerCard, active && styles.mapLockerCardActive]}
                  onPress={() => onSelectLocker(locker.id)}
                >
                  <View style={styles.mapLockerDistanceBubble}>
                    <Text style={styles.mapLockerDistanceValue}>{formatDistanceBadge(locker.distanceKm)}</Text>
                    <Text style={styles.mapLockerDistanceUnit}>км</Text>
                  </View>

                  <View style={styles.mapLockerMain}>
                    <Text style={styles.mapLockerName} numberOfLines={1}>
                      {locker.name}
                    </Text>
                    <View style={styles.mapLockerMetaRow}>
                      <LocationPinGlyph />
                      <Text style={styles.mapLockerAddress} numberOfLines={1}>
                        {locker.address}
                      </Text>
                    </View>
                    <Text style={styles.mapLockerSummary}>
                      {locker.availableProductCount} SKU • {locker.availableUnitCount ?? 0} шт. • {statusLabel(locker.status)}
                    </Text>
                  </View>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>

        {loading ? (
          <View style={styles.mapInfoBanner}>
            <ActivityIndicator size="small" color={palette.hero} />
            <Text style={styles.mapInfoBannerText}>Обновляем точки по выбранному городу.</Text>
          </View>
        ) : null}

        {errorMessage ? (
          <View style={[styles.mapInfoBanner, styles.mapErrorBanner]}>
            <Text style={styles.mapErrorBannerText}>{errorMessage}</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}

function MapFallbackSurface({
  cityName,
  lockers,
  selectedLockerId,
  onSelectLocker,
  userLocation,
  lockerAvailabilityById,
}: {
  cityName: string;
  lockers: Array<Locker & { point: GeoPoint; distanceKm: number | null }>;
  selectedLockerId: string;
  onSelectLocker: (lockerId: string) => void;
  userLocation: GeoPoint | null;
  lockerAvailabilityById: Record<string, LockerAvailabilityItem[]>;
}) {
  const mapHostRef = useRef<any>(null);
  const webMapRef = useRef<YandexMapInstance | null>(null);
  const webMarkersRef = useRef<unknown[]>([]);
  const [webMapReady, setWebMapReady] = useState(false);
  const [webMapError, setWebMapError] = useState("");

  const selectedLocker =
    lockers.find((locker) => locker.id === selectedLockerId) ??
    lockers[0] ??
    null;
  const initialCenterPoint = selectedLocker?.point ?? averageGeoPoint(lockers.map((locker) => locker.point)) ?? DEFAULT_SPB_REGION;

  useEffect(() => {
    if (Platform.OS !== "web") {
      return;
    }

    if (!YANDEX_MAPS_API_KEY) {
      setWebMapError("Укажите EXPO_PUBLIC_YANDEX_MAPS_API_KEY в mobile/.env.local.");
      setWebMapReady(false);
      return;
    }

    let cancelled = false;
    setWebMapError("");

    void loadYandexMapsScript(YANDEX_MAPS_API_KEY)
      .then(
        () =>
          new Promise<void>((resolve, reject) => {
            const ymaps = getYandexMapsApi();
            if (!ymaps) {
              reject(new Error("Yandex API недоступен после загрузки скрипта."));
              return;
            }
            ymaps.ready(() => resolve());
          }),
      )
      .then(() => {
        if (cancelled) {
          return;
        }

        if (webMapRef.current) {
          setWebMapReady(true);
          return;
        }

        const ymaps = getYandexMapsApi();
        if (!ymaps) {
          throw new Error("Не удалось получить объект ymaps.");
        }
        if (!mapHostRef.current) {
          throw new Error("Контейнер карты не найден.");
        }

        webMapRef.current = new ymaps.Map(
          mapHostRef.current,
          {
            center: [initialCenterPoint.latitude, initialCenterPoint.longitude],
            zoom: 12,
            controls: [],
          },
          {
            suppressMapOpenBlock: true,
          },
        );
        setWebMapReady(true);
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setWebMapReady(false);
        setWebMapError(error instanceof Error ? error.message : "Не удалось загрузить Яндекс.Карту.");
      });

    return () => {
      cancelled = true;
    };
  }, [initialCenterPoint.latitude, initialCenterPoint.longitude]);

  useEffect(() => {
    if (Platform.OS !== "web") {
      return;
    }

    return () => {
      webMarkersRef.current = [];
      webMapRef.current?.destroy();
      webMapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (Platform.OS !== "web" || !webMapReady || webMapError) {
      return;
    }

    const map = webMapRef.current;
    const ymaps = getYandexMapsApi();
    if (!map || !ymaps) {
      return;
    }

    webMarkersRef.current.forEach((marker) => map.geoObjects.remove(marker));
    webMarkersRef.current = [];

    lockers.forEach((locker) => {
      const active = locker.id === selectedLockerId;
      const marker = new ymaps.Placemark(
        [locker.point.latitude, locker.point.longitude],
        {
          hintContent: locker.name,
          balloonContentBody: buildLockerBalloonHtml(locker, lockerAvailabilityById[locker.id]),
        },
        {
          preset: active ? "islands#redIcon" : "islands#nightCircleDotIcon",
          hideIconOnBalloonOpen: false,
        },
      );

      marker.events?.add("click", () => {
        onSelectLocker(locker.id);
        marker.balloon?.open();
      });
      map.geoObjects.add(marker);
      webMarkersRef.current.push(marker);

      if (active) {
        marker.balloon?.open();
      }
    });

    if (userLocation) {
      const userMarker = new ymaps.Placemark(
        [userLocation.latitude, userLocation.longitude],
        {
          hintContent: "Вы здесь",
        },
        {
          preset: "islands#blueCircleDotIcon",
        },
      );
      map.geoObjects.add(userMarker);
      webMarkersRef.current.push(userMarker);
    }
  }, [
    lockerAvailabilityById,
    lockers,
    onSelectLocker,
    selectedLockerId,
    userLocation,
    webMapError,
    webMapReady,
  ]);

  useEffect(() => {
    if (Platform.OS !== "web" || !webMapReady || webMapError) {
      return;
    }

    const map = webMapRef.current;
    if (!map) {
      return;
    }

    const points = [...lockers.map((locker) => locker.point), ...(userLocation ? [userLocation] : [])];
    if (!points.length) {
      return;
    }

    if (points.length === 1) {
      map.setCenter([points[0].latitude, points[0].longitude], 14, { duration: 220 });
      return;
    }

    const latitudes = points.map((point) => point.latitude);
    const longitudes = points.map((point) => point.longitude);
    map.setBounds(
      [
        [Math.min(...latitudes), Math.min(...longitudes)],
        [Math.max(...latitudes), Math.max(...longitudes)],
      ],
      {
        checkZoomRange: true,
        zoomMargin: [92, 34, 220, 34],
        duration: 220,
      },
    );
  }, [lockers, userLocation, webMapError, webMapReady]);

  useEffect(() => {
    if (Platform.OS !== "web" || !webMapReady || webMapError) {
      return;
    }

    const map = webMapRef.current;
    const activeLocker = lockers.find((locker) => locker.id === selectedLockerId);
    if (!map || !activeLocker) {
      return;
    }

    map.setCenter([activeLocker.point.latitude, activeLocker.point.longitude], 14, { duration: 200 });
  }, [lockers, selectedLockerId, webMapError, webMapReady]);

  if (Platform.OS === "web") {
    return (
      <View style={styles.mapFallbackSurface}>
        <div ref={mapHostRef} style={{ width: "100%", height: "100%" }} />
        {webMapError ? (
          <View style={styles.mapWebErrorCard}>
            <Text style={styles.mapWebErrorTitle}>Яндекс.Карта не загрузилась</Text>
            <Text style={styles.mapWebErrorText}>
              {webMapError}
              {"\n"}
              Город: {cityName}
            </Text>
          </View>
        ) : null}
      </View>
    );
  }

  const bounds = useMemo(() => {
    const latitudes = lockers.map((locker) => locker.point.latitude);
    const longitudes = lockers.map((locker) => locker.point.longitude);
    return {
      minLat: Math.min(...latitudes),
      maxLat: Math.max(...latitudes),
      minLon: Math.min(...longitudes),
      maxLon: Math.max(...longitudes),
    };
  }, [lockers]);

  function projectPoint(point: GeoPoint) {
    const lonRange = Math.max(bounds.maxLon - bounds.minLon, 0.01);
    const latRange = Math.max(bounds.maxLat - bounds.minLat, 0.01);
    const x = clampNumber(((point.longitude - bounds.minLon) / lonRange) * 68 + 16, 10, 88);
    const y = clampNumber(((bounds.maxLat - point.latitude) / latRange) * 54 + 20, 16, 84);
    return { x: `${x}%` as const, y: `${y}%` as const };
  }

  return (
    <View style={styles.mapFallbackSurface}>
      <View style={styles.mapFallbackRoadOne} />
      <View style={styles.mapFallbackRoadTwo} />
      <View style={styles.mapFallbackRoadThree} />
      <View style={styles.mapFallbackRoadFour} />
      <View style={styles.mapFallbackRoadFive} />
      <View style={styles.mapFallbackRoadSix} />
      <Text style={styles.mapFallbackCity}>{cityName}</Text>

      {userLocation ? (
        <View
          style={[
            styles.mapFallbackUserDot,
            {
              left: projectPoint(userLocation).x,
              top: projectPoint(userLocation).y,
            },
          ]}
        />
      ) : null}

      {lockers.map((locker) => {
        const active = locker.id === selectedLockerId;
        const projected = projectPoint(locker.point);
        return (
          <Pressable
            key={locker.id}
            style={[
              styles.mapFallbackMarkerWrap,
              active && styles.mapFallbackMarkerWrapActive,
              {
                left: projected.x,
                top: projected.y,
              },
            ]}
            onPress={() => onSelectLocker(locker.id)}
          >
            <View style={[styles.mapMarker, active && styles.mapMarkerActive]}>
              <MapMarkerGlyph active={active} />
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

function MapBackButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable style={styles.mapBackButton} onPress={onPress}>
      <Text style={styles.mapBackButtonText}>←</Text>
    </Pressable>
  );
}

function MapMarkerGlyph({ active }: { active: boolean }) {
  return (
    <View style={styles.mapMarkerGlyph}>
      <View style={[styles.mapMarkerGlyphHandleOne, !active && styles.mapMarkerGlyphHandleInactive]} />
      <View style={[styles.mapMarkerGlyphHandleTwo, !active && styles.mapMarkerGlyphHandleInactive]} />
    </View>
  );
}

function LocationPinGlyph() {
  return (
    <View style={styles.locationPinGlyph}>
      <View style={styles.locationPinGlyphRing} />
      <View style={styles.locationPinGlyphDot} />
    </View>
  );
}

