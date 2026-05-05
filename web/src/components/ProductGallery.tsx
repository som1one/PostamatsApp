"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ImageIcon } from "lucide-react";
import { resolvePublicAssetUrl } from "@/shared/media";

export function ProductGallery({ images, title }: { images: string[]; title: string }) {
  const resolvedImages = images.map((image) => resolvePublicAssetUrl(image) || image);
  const [activeIndex, setActiveIndex] = useState(0);
  const touchStartX = useRef<number | null>(null);

  useEffect(() => {
    if (!resolvedImages.length) {
      setActiveIndex(0);
      return;
    }
    setActiveIndex((current) => Math.min(current, resolvedImages.length - 1));
  }, [resolvedImages.length]);

  const activeImage = resolvedImages[activeIndex] ?? null;
  const canNavigate = resolvedImages.length > 1;

  function showImage(index: number) {
    if (!resolvedImages.length) {
      return;
    }
    const normalizedIndex = (index + resolvedImages.length) % resolvedImages.length;
    setActiveIndex(normalizedIndex);
  }

  function handleTouchStart(clientX: number) {
    touchStartX.current = clientX;
  }

  function handleTouchEnd(clientX: number) {
    if (touchStartX.current === null) {
      return;
    }
    const deltaX = clientX - touchStartX.current;
    touchStartX.current = null;

    if (Math.abs(deltaX) < 36) {
      return;
    }

    if (deltaX < 0) {
      showImage(activeIndex + 1);
      return;
    }

    showImage(activeIndex - 1);
  }

  return (
    <div className="product-gallery">
      <div
        className="product-gallery-main"
        onTouchStart={(event) => handleTouchStart(event.changedTouches[0]?.clientX ?? 0)}
        onTouchEnd={(event) => handleTouchEnd(event.changedTouches[0]?.clientX ?? 0)}
      >
        {activeImage ? <img src={activeImage} alt={`${title}, фото ${activeIndex + 1}`} /> : <ImageIcon size={72} />}
        {canNavigate ? (
          <>
            <button
              aria-label="Предыдущее фото"
              className="button button-secondary icon-button product-gallery-nav product-gallery-nav-prev"
              type="button"
              onClick={() => showImage(activeIndex - 1)}
            >
              <ChevronLeft size={18} />
            </button>
            <button
              aria-label="Следующее фото"
              className="button button-secondary icon-button product-gallery-nav product-gallery-nav-next"
              type="button"
              onClick={() => showImage(activeIndex + 1)}
            >
              <ChevronRight size={18} />
            </button>
            <span className="product-gallery-counter">
              {activeIndex + 1}/{resolvedImages.length}
            </span>
          </>
        ) : null}
      </div>
      {canNavigate ? (
        <div className="product-gallery-thumbs">
          {resolvedImages.map((url, index) => (
            <button
              aria-label={`Открыть фото ${index + 1}`}
              className={`product-gallery-thumb ${index === activeIndex ? "is-active" : ""}`}
              key={`${url}-${index}`}
              type="button"
              onClick={() => showImage(index)}
            >
              <img src={url} alt={`${title}, фото ${index + 1}`} />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
