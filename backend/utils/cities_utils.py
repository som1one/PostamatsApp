from backend.models.city import City


def serialize_city(city: City) -> dict:
    return {
        "id": str(city.id),
        "name": city.name,
        "slug": city.slug,
        "timezone": city.timezone,
        "isActive": city.is_active,
        "sortOrder": city.sort_order,
    }
