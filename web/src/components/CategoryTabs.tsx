import {
  Boxes,
  Gamepad2,
  House,
  MonitorPlay,
  Projector,
  SprayCan,
  TvMinimalPlay,
  Wrench,
  type LucideIcon,
} from "lucide-react";

function iconForCategory(category: { id: string; label: string }): LucideIcon {
  const value = `${category.id} ${category.label}`.toLowerCase();
  if (!category.id) {
    return Boxes;
  }
  if (value.includes("пристав") || value.includes("console") || value.includes("game")) {
    return Gamepad2;
  }
  if (value.includes("проектор") || value.includes("projector")) {
    return Projector;
  }
  if (value.includes("уборк") || value.includes("clean")) {
    return SprayCan;
  }
  if (value.includes("инструмент") || value.includes("tool")) {
    return Wrench;
  }
  if (value.includes("дом") || value.includes("home")) {
    return House;
  }
  if (value.includes("тв") || value.includes("экран") || value.includes("monitor")) {
    return MonitorPlay;
  }
  return TvMinimalPlay;
}

export function CategoryTabs({
  categories,
  activeId,
  onChange,
}: {
  categories: Array<{ id: string; label: string }>;
  activeId: string;
  onChange: (categoryId: string) => void;
}) {
  return (
    <div className="category-tabs" aria-label="Категории товаров">
      {categories.map((category) => {
        const Icon = iconForCategory(category);
        return (
          <button
            className={`category-tab ${activeId === category.id ? "is-active" : ""}`}
            key={category.id || "all"}
            type="button"
            onClick={() => onChange(category.id)}
          >
            <span className="category-tab-icon">
              <Icon size={16} />
            </span>
            <span className="category-tab-label">{category.label}</span>
          </button>
        );
      })}
    </div>
  );
}
