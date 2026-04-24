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


def serialize_admin_city_list_item(city: City, *, locker_count: int) -> dict:
    return {
        **serialize_city(city),
        "lockerCount": int(locker_count),
        "createdAt": city.created_at.isoformat(),
    }
