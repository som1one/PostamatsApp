/**
 * Категории каталога. Вынесено из content.tsx (чистые данные без иконок),
 * чтобы мобильное приложение использовало тот же список — файл копируется
 * в mobile/src/shared байт-идентично.
 */
export const productCategories = [
  { id: "", label: "Все" },
  { id: "consoles", label: "Приставки" },
  { id: "projectors", label: "Проекторы" },
  { id: "cleaning", label: "Уборка" },
  { id: "tools", label: "Инструменты" },
  { id: "home", label: "Для дома" },
];
