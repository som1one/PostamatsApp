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
            
            # Get bounding box of the non-transparent area
            bbox = subject_img.getbbox()
            if bbox:
                subject_img = subject_img.crop(bbox)
            
            # Create a white background image with some padding
            padding = 40
            width, height = subject_img.size
            
            # Ensure at least 4:3 or 1:1 aspect ratio?
            # actually we don't need to force aspect ratio if we use object-fit: contain
            new_width = width + padding * 2
            new_height = height + padding * 2
            
            bg = Image.new("RGB", (new_width, new_height), (255, 255, 255))
            bg.paste(subject_img, (padding, padding), subject_img)
            
            # Overwrite the file
            bg.save(file, format='WEBP' if file.lower().endswith('.webp') else 'JPEG')
            print(f"Successfully processed {file}")
        except Exception as e:
            print(f"Error processing {file}: {e}")

if __name__ == "__main__":
    process_images(r"c:\Users\Green_Tea\Documents\New project\items")
