import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.1.6"],
  turbopack: {
    root: rootDir,
  },
  // Проверку типов и eslint гоняем локально перед пушем (tsc --noEmit, eslint).
  // На production-сборке (в т.ч. в Docker на VPS с малой памятью) их отключаем:
  // шаг "Running TypeScript" на сборке прожорлив к RAM и приводил к зависанию
  // деплоя по OOM. Сборка становится легче и быстрее, качество не теряем.
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
