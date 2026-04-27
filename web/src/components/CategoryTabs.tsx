import { Boxes, Sparkles } from "lucide-react";

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
        const Icon = category.id ? Sparkles : Boxes;
        return (
          <button
            className={`category-tab ${activeId === category.id ? "is-active" : ""}`}
            key={category.id || "all"}
            type="button"
            onClick={() => onChange(category.id)}
          >
            <Icon size={16} />
            {category.label}
          </button>
        );
      })}
    </div>
  );
}

