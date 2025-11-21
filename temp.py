import os
import shutil

def move_with_suffix(src_file, dest_dir):
    # Get the filename and extension
    filename = os.path.basename(src_file)
    base_name, ext = os.path.splitext(filename)
    
    # Initial destination path (original filename)
    dest_path = os.path.join(dest_dir, filename)

    # 1. If file DOES NOT exist, move it directly
    if not os.path.exists(dest_path):
        shutil.move(src_file, dest_path)
        print(f"Moved: {src_file} -> {dest_path}")
        return

    # 2. If file DOES exist, find a variant name
    variant = 1
    while True:
        new_name = f"{base_name} - variant {variant}{ext}"
        dest_path = os.path.join(dest_dir, new_name)
        
        if not os.path.exists(dest_path):
            break # Found a free name
        variant += 1

    shutil.move(src_file, dest_path)
    print(f"Moved (renamed): {src_file} -> {dest_path}")


def move_all_pdfs(src_folder, dest_folder):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
        
    if not os.path.exists(src_folder):
        print(f"Source folder not found: {src_folder}")
        return

    for filename in os.listdir(src_folder):
        if filename.lower().endswith(".pdf"):
            src_path = os.path.join(src_folder, filename)
            move_with_suffix(src_path, dest_folder)

# Execute moves
move_all_pdfs("./extra-pdfs/C", "./pdf/C")
move_all_pdfs("./extra-pdfs/Clarinet Bb", "./pdf/Clarinet Bb")
move_all_pdfs("./extra-pdfs/Saxophone Eb", "./pdf/Saxophone Eb")
