type YandexMapsInput = {
  name?: string | null;
  address?: string | null;
  lat?: number | null;
  lon?: number | null;
};

export function buildYandexMapsUrl({ name, address, lat, lon }: YandexMapsInput) {
  if (typeof lat === "number" && typeof lon === "number") {
    return `https://yandex.ru/maps/?pt=${lon},${lat}&z=16&l=map`;
  }

  const query = [name, address].filter(Boolean).join(", ").trim();
  return `https://yandex.ru/maps/?text=${encodeURIComponent(query)}`;
}
