import glob
import os
from PIL import Image
from rembg import remove
from io import BytesIO

def process_images(directory):
    extensions = ('*.webp', '*.png', '*.jpg', '*.jpeg')
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(directory, '**', ext), recursive=True))

    for file in files:
        print(f"Processing {file}")
        try:
            with open(file, 'rb') as i:
                input_data = i.read()
            
            # Remove background
            subject_bytes = remove(input_data)
            
            subject_img = Image.open(BytesIO(subject_bytes)).convert("RGBA")
            
            # Keep original canvas size and composition to avoid awkward cropping
            bg = Image.new("RGB", subject_img.size, (255, 255, 255))
            bg.paste(subject_img, (0, 0), subject_img)
            
            # Overwrite the file
            bg.save(file, format='WEBP' if file.lower().endswith('.webp') else 'JPEG')
            print(f"Successfully processed {file}")
        except Exception as e:
            print(f"Error processing {file}: {e}")

if __name__ == "__main__":
    process_images(r"c:\Users\Green_Tea\Documents\New project\items")
