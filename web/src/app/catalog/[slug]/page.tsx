import { ProductDetailClient } from "@/app/products/[id]/ProductDetailClient";

export default async function CatalogProductPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <ProductDetailClient productRef={slug} />;
}

