import { ImageIcon } from "lucide-react";

export function ProductGallery({ images, title }: { images: string[]; title: string }) {
  const cover = images[0];

  return (
    <div className="product-gallery">
      <div className="product-gallery-main">
        {cover ? <img src={cover} alt={title} /> : <ImageIcon size={72} />}
      </div>
      {images.length > 1 ? (
        <div className="product-gallery-thumbs">
          {images.slice(0, 5).map((url, index) => (
            <div className="product-gallery-thumb" key={url}>
              <img src={url} alt={`${title}, фото ${index + 1}`} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

