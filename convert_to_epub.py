import os
import shutil
from datetime import datetime, timezone
from xml.sax.saxutils import escape
import uuid  # used to generate a unique identifier
import zipfile
from PIL import Image  # pip install pillow


def initial_setup(base_path=None):
    """
    Create the following structure:

    base_path/
        temp/
            mimetype
            META-INF/
                container.xml
            OEBPS/
                Images/
                Text/

    - If temp/ already exists, it is fully deleted and recreated.
    """

    if base_path is None:
        base_path = os.getcwd()  # current working directory

    # Root "temp" folder
    root = os.path.join(base_path, "temp")

    # Remove existing temp folder if it already exists
    if os.path.exists(root):
        print(f"Removing existing temp folder: {root}")
        shutil.rmtree(root)

    # Subfolders
    meta_inf = os.path.join(root, "META-INF")
    oebps = os.path.join(root, "OEBPS")
    images = os.path.join(oebps, "Images")
    text = os.path.join(oebps, "Text")

    # Create all folders
    os.makedirs(meta_inf, exist_ok=True)
    os.makedirs(images, exist_ok=True)
    os.makedirs(text, exist_ok=True)

    # Create "mimetype" file at the root of "temp"
    mimetype_path = os.path.join(root, "mimetype")
    with open(mimetype_path, "w", encoding="utf-8") as f:
        # No trailing newline for EPUB spec
        f.write("application/epub+zip")

    # Create "container.xml" inside META-INF
    container_path = os.path.join(meta_inf, "container.xml")
    container_content = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>"""

    with open(container_path, "w", encoding="utf-8") as f:
        f.write(container_content)

    print(f"Root folder recreated: {root}")
    print(f"Folder: {meta_inf}")
    print(f"Folder: {oebps}")
    print(f"Folder: {images}")
    print(f"Folder: {text}")
    print(f"File created: {mimetype_path}")
    print(f"File created: {container_path}")


def copy_images_to_temp_images(source_folder, base_path=None):
    """
    Copy image files from 'source_folder' to:
        base_path/temp/OEBPS/Images

    If an image is named 'cover' (cover.jpg, COVER.PNG, etc.),
    it is copied under a name that will be lexicographically first
    in the folder (0.ext, 0_1.ext, ...).
    """
    if base_path is None:
        base_path = os.getcwd()  # current working directory

    dest_images = os.path.join(base_path, "temp", "OEBPS", "Images")
    os.makedirs(dest_images, exist_ok=True)

    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}

    # Collect all image files from the source folder
    image_files = []
    for filename in os.listdir(source_folder):
        src_path = os.path.join(source_folder, filename)
        if not os.path.isfile(src_path):
            continue
        _, ext = os.path.splitext(filename)
        if ext.lower() in image_extensions:
            image_files.append(filename)

    # Separate cover images from others
    cover_files = []
    other_files = []
    for filename in image_files:
        name_no_ext, _ = os.path.splitext(filename)
        if name_no_ext.lower() == "cover":
            cover_files.append(filename)
        else:
            other_files.append(filename)

    # Copy non-cover images with original names
    for filename in sorted(other_files):
        src_path = os.path.join(source_folder, filename)
        dest_path = os.path.join(dest_images, filename)
        shutil.copy2(src_path, dest_path)
        print(f"Copied: {src_path} -> {dest_path}")

    # Copy covers and rename them to 0.ext, 0_1.ext, ...
    for idx, filename in enumerate(cover_files):
        src_path = os.path.join(source_folder, filename)
        _, ext = os.path.splitext(filename)

        if idx == 0:
            base_name = "0"
        else:
            base_name = f"0_{idx}"

        dest_name = base_name + ext.lower()
        dest_path = os.path.join(dest_images, dest_name)

        # Ensure the generated name is unique
        suffix = 1
        while os.path.exists(dest_path):
            dest_name = f"{base_name}_{suffix}{ext.lower()}"
            dest_path = os.path.join(dest_images, dest_name)
            suffix += 1

        shutil.copy2(src_path, dest_path)
        print(f"Copied (cover renamed): {src_path} -> {dest_path}")

    print("Image copy finished.")


def generate_xhtml_pages(
    base_path=None,
    fallback_width=1046,
    fallback_height=1448,
    double_page_ratio=1.3,   # ratio threshold above which an image is considered a double-page
    reading_direction="rtl"  # "rtl" or "ltr"
):
    """
    Generate XHTML files in temp/OEBPS/Text for each image in temp/OEBPS/Images.

    - For "single" images (width/height < double_page_ratio):
        -> the original image file is kept
        -> 1 XHTML file: page_<safe_name>_F.xhtml
        -> viewport = actual image size

    - For "double" images (width/height >= double_page_ratio):
        -> the image is split into two vertical halves
        -> the original is removed
        -> two new images are created:
             * <name>_a.<ext>
             * <name>_b.<ext>
           with the mapping:
             - LTR: _a = left half, _b = right half
             - RTL: _a = right half, _b = left half
        -> for each half, 1 XHTML: page_<safe_part>_F.xhtml
        -> viewport = (width/2, height)

    All XHTML pages:
      - use only src on <img> (no width/height attributes)
      - have a viewport set to the dimensions of the corresponding image.
    """

    if base_path is None:
        base_path = os.getcwd()  # current working directory

    images_dir = os.path.join(base_path, "temp", "OEBPS", "Images")
    text_dir   = os.path.join(base_path, "temp", "OEBPS", "Text")

    os.makedirs(text_dir, exist_ok=True)

    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    # Freeze the initial list of files so we are not affected
    # by additions/removals during iteration
    filenames = sorted(os.listdir(images_dir))

    reading_direction = reading_direction.lower()
    if reading_direction not in ("rtl", "ltr"):
        reading_direction = "rtl"

    def sanitize_name(name: str) -> str:
        """Return a filesystem-safe name (letters, digits, underscore, hyphen)."""
        return "".join(
            c if c.isalnum() or c in ("_", "-") else "_"
            for c in name
        )

    for filename in filenames:
        src_path = os.path.join(images_dir, filename)

        if not os.path.isfile(src_path):
            continue

        name, ext = os.path.splitext(filename)
        if ext.lower() not in image_extensions:
            # Skip non-raster images (SVG, etc.); they could be handled separately if needed
            print(f"Skipping non-raster image: {filename}")
            continue

        # Read actual image size (with a fallback if it fails)
        img_width = fallback_width
        img_height = fallback_height
        try:
            with Image.open(src_path) as img:
                img_width, img_height = img.size
        except Exception as e:
            print(f"Warning: cannot read size for {filename}: {e}")
            print(f"Using fallback size {fallback_width}x{fallback_height}")

        # Detect single vs double page by ratio
        ratio = img_width / img_height if img_height > 0 else 0.0
        is_double = ratio >= double_page_ratio

        # Safe base name (without extension)
        safe_base = sanitize_name(name)

        if is_double and img_width > 1:
            # ----- DOUBLE PAGE CASE: split into two halves -----
            half_width = img_width // 2

            try:
                with Image.open(src_path) as img:
                    # Define crop boxes (left, upper, right, lower)
                    box_left  = (0, 0, half_width, img_height)
                    box_right = (half_width, 0, img_width, img_height)

                    parts = []
                    if reading_direction == "ltr":
                        # _a = left half, _b = right half
                        parts = [
                            ("a", "left",  box_left),
                            ("b", "right", box_right),
                        ]
                    else:  # rtl
                        # _a = right half, _b = left half
                        parts = [
                            ("a", "right", box_right),
                            ("b", "left",  box_left),
                        ]

                    for suffix_letter, side, box in parts:
                        part_base = f"{safe_base}_{suffix_letter}"
                        part_img_name = f"{part_base}{ext}"
                        part_img_path = os.path.join(images_dir, part_img_name)

                        cropped = img.crop(box)
                        # Save with default PIL format/settings
                        cropped.save(part_img_path)

                        # Generate XHTML for this half
                        xhtml_filename = f"page_{part_base}_F.xhtml"
                        xhtml_path = os.path.join(text_dir, xhtml_filename)
                        title = f"page_{part_base}_F"

                        viewport_w = half_width
                        viewport_h = img_height

                        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>{title}</title>
<link href="style.css" type="text/css" rel="stylesheet"/>
<meta name="viewport" content="width={viewport_w}, height={viewport_h}"/>
</head>
<body class="single-page">
<div>
<img src="../Images/{part_img_name}" alt=""/>
</div>
</body>
</html>
'''
                        with open(xhtml_path, "w", encoding="utf-8") as f:
                            f.write(content)

                        print(
                            f"Created XHTML page (split {side}): {xhtml_path} "
                            f"(viewport {viewport_w}x{viewport_h})"
                        )

            except Exception as e:
                # If the split fails, fall back to a simple page using the original image
                print(f"Error splitting double page {filename}: {e}")
                is_double = False  # handle as a single page below

            # If split worked, remove the original image and move on
            if is_double:
                try:
                    os.remove(src_path)
                    print(f"Removed original double-page image: {src_path}")
                except OSError as e:
                    print(f"Warning: could not remove original image {src_path}: {e}")
                # Do not generate XHTML for the original image
                continue

        # ----- SINGLE PAGE CASE (or fallback if the split failed) -----
        safe_name = safe_base
        xhtml_filename = f"page_{safe_name}_F.xhtml"
        xhtml_path = os.path.join(text_dir, xhtml_filename)
        title = f"page_{safe_name}_F"

        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>{title}</title>
<link href="style.css" type="text/css" rel="stylesheet"/>
<meta name="viewport" content="width={img_width}, height={img_height}"/>
</head>
<body class="single-page">
<div>
<img src="../Images/{filename}" alt=""/>
</div>
</body>
</html>
'''
        with open(xhtml_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(
            f"Created XHTML page: {xhtml_path} "
            f"(SINGLE, viewport {img_width}x{img_height})"
        )


from datetime import datetime, timezone
from html import escape
import os
import uuid


def generate_content_opf(
    base_path=None,
    title="title",
    creator="author",
    has_cover=True,
    reading_direction="rtl",  # "rtl" or "ltr"
    original_resolution="1072x1448",
    book_id=None,
    spread_mode="auto",       # "none", "auto", "landscape", "both", ...
):
    """
    Generate temp/OEBPS/content.opf based on the images in
    temp/OEBPS/Images and the XHTML pages in temp/OEBPS/Text.

    Current assumptions:
      - generate_xhtml_pages has already:
          * split double pages into two images:
                <base>_a.ext and <base>_b.ext
          * generated XHTML files:
                page_<safe_name>_F.xhtml
            (no _T suffix on XHTML files)

    Rules:
      - has_cover:
          True  -> first image is used as cover (meta cover + centered page)
          False -> no cover
      - reading_direction: "rtl" or "ltr"
      - single pages:
          alternation between page-spread-right / page-spread-left
      - double pages (a/b):
          * detected by <root>_a + <root>_b consecutive files
          * in RTL: we want half 'a' to appear on the RIGHT
            -> if next_side != right, insert a blank page before
          * in LTR: we want half 'a' to appear on the LEFT
            -> if next_side != left, insert a blank page before
      - spread_mode controls <meta property="rendition:spread">

      IMPORTANT: each blank page is unique:
        page_blank_1, page_blank_2, ...
    """

    if base_path is None:
        base_path = os.getcwd()

    if book_id is None:
        book_id = f"urn:uuid:{uuid.uuid4()}"

    spread_mode = (spread_mode or "auto").strip()

    oebps_dir  = os.path.join(base_path, "temp", "OEBPS")
    images_dir = os.path.join(oebps_dir, "Images")
    text_dir   = os.path.join(oebps_dir, "Text")
    opf_path   = os.path.join(oebps_dir, "content.opf")

    os.makedirs(oebps_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(text_dir, exist_ok=True)

    # Reading direction metadata
    rd = reading_direction.lower()
    if rd not in ("rtl", "ltr"):
        rd = "rtl"
    primary_writing_mode = "horizontal-rl" if rd == "rtl" else "horizontal-lr"

    # List all image files
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}
    image_files = []
    for filename in sorted(os.listdir(images_dir)):
        path = os.path.join(images_dir, filename)
        if not os.path.isfile(path):
            continue
        _, ext = os.path.splitext(filename)
        if ext.lower() in image_extensions:
            image_files.append(filename)

    def sanitize_name(name: str) -> str:
        """Return a safe ID/name for use in manifest IDs and filenames."""
        return "".join(
            c if c.isalnum() or c in ("_", "-") else "_"
            for c in name
        )

    def image_media_type(ext_lower: str) -> str:
        """Return the appropriate media-type for an image extension."""
        if ext_lower in (".jpg", ".jpeg"):
            return "image/jpeg"
        if ext_lower == ".png":
            return "image/png"
        if ext_lower == ".gif":
            return "image/gif"
        if ext_lower == ".svg":
            return "image/svg+xml"
        return "image/jpeg"

    # --- Manifest & spine containers ---
    manifest_items = []
    spine_items = []

    # nav.xhtml
    manifest_items.append(
        '    <item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>'
    )

    # toc.ncx
    manifest_items.append(
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    )

    # CSS
    manifest_items.append(
        '    <item id="css" href="Text/style.css" media-type="text/css"/>'
    )

    cover_image_id = None

    # --- Resolution used for blank pages ---
    def parse_resolution(res_str, default=(1072, 1448)):
        """Parse 'WxH' resolution string into an (int, int) tuple."""
        try:
            parts = res_str.lower().split("x")
            if len(parts) != 2:
                return default
            w = int(parts[0].strip())
            h = int(parts[1].strip())
            return (w, h)
        except Exception:
            return default

    blank_w, blank_h = parse_resolution(original_resolution)
    blank_counter = 0  # counter for unique blank pages: page_blank_1, etc.

    # Keep track of page spread side (left/right)
    last_side = None           # "left" or "right"
    next_side = "right"        # first simple page will appear on the right

    def add_spine_page(page_id: str, side: str):
        """Add an itemref with page-spread-<side> and update side tracking."""
        nonlocal last_side, next_side
        spine_items.append(
            f'    <itemref idref="{page_id}" linear="yes" properties="page-spread-{side}"/>'
        )
        last_side = side
        next_side = "left" if side == "right" else "right"

    def add_blank_page(side: str):
        """
        Create a new unique blank page:
          - file: Text/page_blank_<n>.xhtml
          - manifest: item id="page_blank_<n>"
          - spine: itemref with page-spread-<side> via add_spine_page()
        """
        nonlocal blank_counter, manifest_items
        blank_counter += 1
        blank_id = f"page_blank_{blank_counter}"
        blank_xhtml_filename = f"page_blank_{blank_counter}.xhtml"
        blank_path = os.path.join(text_dir, blank_xhtml_filename)

        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>blank</title>
<link href="style.css" type="text/css" rel="stylesheet"/>
<meta name="viewport" content="width={blank_w}, height={blank_h}"/>
</head>
<body class="blank-page">
<div></div>
</body>
</html>
'''
        with open(blank_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Add blank page to manifest
        manifest_items.append(
            f'    <item id="{blank_id}" href="Text/{blank_xhtml_filename}" media-type="application/xhtml+xml"/>'
        )
        # Add to spine (and update next_side)
        add_spine_page(blank_id, side)

    # --- Traverse images and handle a/b pairs for double spreads ---
    i = 0
    while i < len(image_files):
        img_name = image_files[i]
        base, ext = os.path.splitext(img_name)
        safe_name = sanitize_name(base)
        ext_lower = ext.lower()

        # XHTML file expected for this image
        xhtml_filename = f"page_{safe_name}_F.xhtml"
        xhtml_path = os.path.join(text_dir, xhtml_filename)
        if not os.path.exists(xhtml_path):
            print(
                f"Warning: XHTML page not found for image '{img_name}' "
                f"-> expected {xhtml_filename}"
            )
            i += 1
            continue

        # First image may be used as cover
        is_first = (i == 0)
        is_cover = has_cover and is_first

        # Detect whether this is the start of an a/b pair
        is_double_group_start = False
        root_name = safe_name
        part_letter = None

        if safe_name.endswith("_a") or safe_name.endswith("_b"):
            part_letter = safe_name[-1]    # "a" or "b"
            root_name = safe_name[:-2]     # remove "_a" / "_b"

        if part_letter == "a":
            # Check if the next file is the corresponding "_b" half
            if i + 1 < len(image_files):
                img_name_next = image_files[i + 1]
                base_next, ext_next = os.path.splitext(img_name_next)
                safe_name_next = sanitize_name(base_next)
                if safe_name_next == f"{root_name}_b" and ext_next.lower() == ext_lower:
                    is_double_group_start = True

        # --- Cover case: always centered ---
        if is_cover:
            page_id = f"page_Images_{safe_name}_F"

            manifest_items.append(
                f'    <item id="{page_id}" href="Text/{xhtml_filename}" media-type="application/xhtml+xml"/>'
            )

            media_type = image_media_type(ext_lower)
            image_id = "cover"
            cover_image_id = image_id
            manifest_items.append(
                f'    <item id="{image_id}" href="Images/{img_name}" media-type="{media_type}" properties="cover-image"/>'
            )

            # Cover page is centered
            spine_items.append(
                f'    <itemref idref="{page_id}" linear="yes" properties="page-spread-center"/>'
            )

            # Do not change last_side / next_side for cover
            i += 1
            continue

        media_type = image_media_type(ext_lower)

        # --- Double spread (a/b pair) ---
        if is_double_group_start:
            # Desired side for the first half (a)
            desired_side_a = "right" if rd == "rtl" else "left"

            # If the next page side is wrong, insert a blank page before
            if last_side is not None and next_side != desired_side_a:
                add_blank_page(next_side)
                print(
                    f"Inserted blank page before double spread root='{root_name}' "
                    f"(last_side={last_side}, new_next_side={next_side})"
                )

            # --- Half A ---
            page_id_a = f"page_Images_{safe_name}_F"
            manifest_items.append(
                f'    <item id="{page_id_a}" href="Text/{xhtml_filename}" media-type="application/xhtml+xml"/>'
            )
            image_id_a = f"img_Images_{safe_name}"
            manifest_items.append(
                f'    <item id="{image_id_a}" href="Images/{img_name}" media-type="{media_type}"/>'
            )
            # Consume the current next_side for half A
            add_spine_page(page_id_a, next_side)

            # --- Half B ---
            img_name_b = image_files[i + 1]
            base_b, ext_b = os.path.splitext(img_name_b)
            safe_name_b = sanitize_name(base_b)
            xhtml_filename_b = f"page_{safe_name_b}_F.xhtml"
            xhtml_path_b = os.path.join(text_dir, xhtml_filename_b)

            if not os.path.exists(xhtml_path_b):
                print(
                    f"Warning: XHTML page not found for image '{img_name_b}' "
                    f"-> expected {xhtml_filename_b}"
                )
            else:
                page_id_b = f"page_Images_{safe_name_b}_F"
                manifest_items.append(
                    f'    <item id="{page_id_b}" href="Text/{xhtml_filename_b}" media-type="application/xhtml+xml"/>'
                )
                image_id_b = f"img_Images_{safe_name_b}"
                media_type_b = image_media_type(ext_b.lower())
                manifest_items.append(
                    f'    <item id="{image_id_b}" href="Images/{img_name_b}" media-type="{media_type_b}"/>'
                )
                # Consume the opposite side for half B
                add_spine_page(page_id_b, next_side)

            i += 2
            continue

        # --- Simple page ---
        page_id = f"page_Images_{safe_name}_F"
        manifest_items.append(
            f'    <item id="{page_id}" href="Text/{xhtml_filename}" media-type="application/xhtml+xml"/>'
        )
        image_id = f"img_Images_{safe_name}"
        manifest_items.append(
            f'    <item id="{image_id}" href="Images/{img_name}" media-type="{media_type}"/>'
        )

        # Use next_side (right/left) then alternate
        add_spine_page(page_id, next_side)

        i += 1

    # --- Cover metadata ---
    if has_cover and cover_image_id is not None:
        cover_meta_line = f'    <meta name="cover" content="{cover_image_id}"/>'
    else:
        cover_meta_line = None

    # --- Modification date ---
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Write content.opf ---
    with open(opf_path, "w", encoding="utf-8") as f_opf:
        f_opf.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f_opf.write('<package xmlns="http://www.idpf.org/2007/opf" '
                    'version="3.0" unique-identifier="BookID">\n')
        f_opf.write('  <metadata xmlns:opf="http://www.idpf.org/2007/opf" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/">\n')
        f_opf.write(f'    <dc:identifier id="BookID">{escape(book_id)}</dc:identifier>\n')
        f_opf.write(f'    <dc:title id="id">{escape(title)}</dc:title>\n')
        f_opf.write(f'    <dc:creator id="id-2">{escape(creator)}</dc:creator>\n')
        f_opf.write(f'    <meta property="dcterms:modified">{modified}</meta>\n')

        if cover_meta_line:
            f_opf.write(cover_meta_line + "\n")

        f_opf.write('    <meta name="fixed-layout" content="true"/>\n')
        f_opf.write(f'    <meta name="original-resolution" content="{escape(original_resolution)}"/>\n')
        f_opf.write('    <meta name="book-type" content="comic"/>\n')
        f_opf.write(f'    <meta name="primary-writing-mode" content="{primary_writing_mode}"/>\n')
        f_opf.write('    <meta name="zero-gutter" content="true"/>\n')
        f_opf.write('    <meta name="zero-margin" content="true"/>\n')
        f_opf.write('    <meta name="ke-border-color" content="#FFFFFF"/>\n')
        f_opf.write('    <meta name="ke-border-width" content="0"/>\n')
        f_opf.write('    <meta name="orientation-lock" content="none"/>\n')
        f_opf.write('    <meta name="region-mag" content="true"/>\n')
        f_opf.write(f'    <meta property="rendition:spread">{escape(spread_mode)}</meta>\n')
        f_opf.write('    <meta property="rendition:layout">pre-paginated</meta>\n')
        f_opf.write('  </metadata>\n')

        f_opf.write('  <manifest>\n')
        for line in manifest_items:
            f_opf.write(line + "\n")
        f_opf.write('  </manifest>\n')

        f_opf.write(f'  <spine page-progression-direction="{rd}" toc="ncx">\n')
        for line in spine_items:
            f_opf.write(line + "\n")
        f_opf.write('  </spine>\n')
        f_opf.write('</package>\n')

    print(f"content.opf generated at: {opf_path}")
    print(f"BookID used: {book_id}")
    print(f"rendition:spread = {spread_mode}")


def generate_toc_ncx(
    base_path=None,
    book_id=None,
    title="title"
):
    """
    Generate temp/OEBPS/toc.ncx from the *.xhtml files in
    temp/OEBPS/Text.

    - book_id: SHOULD ideally match the one used in content.opf
               (dc:identifier id="BookID").
               If None, a UUID is generated (but that will be different
               from the OPF unless you pass it explicitly).
    """

    if base_path is None:
        base_path = os.getcwd()

    # If no book_id is provided, generate a new one
    # (recommended to pass the same one used in the OPF)
    if book_id is None:
        book_id = f"urn:uuid:{uuid.uuid4()}"

    oebps_dir = os.path.join(base_path, "temp", "OEBPS")
    text_dir = os.path.join(oebps_dir, "Text")
    ncx_path = os.path.join(oebps_dir, "toc.ncx")

    os.makedirs(text_dir, exist_ok=True)

    # Collect all XHTML pages
    xhtml_files = [
        f for f in sorted(os.listdir(text_dir))
        if os.path.isfile(os.path.join(text_dir, f)) and f.lower().endswith(".xhtml")
    ]

    with open(ncx_path, "w", encoding="utf-8") as f_ncx:
        f_ncx.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f_ncx.write('<ncx version="2005-1" xml:lang="en-US" xmlns="http://www.daisy.org/z3986/2005/ncx/">\n')
        f_ncx.write('  <head>\n')
        f_ncx.write(f'    <meta name="dtb:uid" content="{escape(book_id)}"/>\n')
        f_ncx.write('    <meta name="dtb:depth" content="1"/>\n')
        f_ncx.write('    <meta name="dtb:totalPageCount" content="0"/>\n')
        f_ncx.write('    <meta name="dtb:maxPageNumber" content="0"/>\n')
        f_ncx.write('    <meta name="generated" content="true"/>\n')
        f_ncx.write('  </head>\n')
        f_ncx.write(f'  <docTitle><text>{escape(title)}</text></docTitle>\n')
        f_ncx.write('  <navMap>\n')

        # One navPoint per page
        for i, xhtml in enumerate(xhtml_files, start=1):
            label = f"Page {i}"  # can be customized if desired
            f_ncx.write(f'    <navPoint id="navPoint-{i}" playOrder="{i}">\n')
            f_ncx.write(f'      <navLabel><text>{escape(label)}</text></navLabel>\n')
            f_ncx.write(f'      <content src="Text/{xhtml}"/>\n')
            f_ncx.write('    </navPoint>\n')

        f_ncx.write('  </navMap>\n')
        f_ncx.write('</ncx>\n')

    print(f"toc.ncx generated at: {ncx_path}")
    print(f"dtb:uid used: {book_id}")
    return book_id


def generate_nav_xhtml(base_path=None, title="title"):
    """
    Generate temp/OEBPS/nav.xhtml using ONLY the first XHTML page
    found in temp/OEBPS/Text (lexicographical order).

    - base_path: directory containing "temp" (defaults to current directory)
    - title: text used in <title> and in navigation links
    """

    if base_path is None:
        base_path = os.getcwd()

    oebps_dir = os.path.join(base_path, "temp", "OEBPS")
    text_dir = os.path.join(oebps_dir, "Text")
    nav_path = os.path.join(oebps_dir, "nav.xhtml")

    os.makedirs(text_dir, exist_ok=True)

    # Collect all XHTML pages
    xhtml_files = [
        f for f in sorted(os.listdir(text_dir))
        if os.path.isfile(os.path.join(text_dir, f)) and f.lower().endswith(".xhtml")
    ]

    if not xhtml_files:
        print("No XHTML files found in Text/ to build nav.xhtml")
        return

    # Use only the first page for navigation
    first_page = xhtml_files[0]
    first_href = f"Text/{first_page}"

    content = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>{escape(title)}</title>
<meta charset="utf-8"/>
</head>
<body>
<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc" id="toc">
<ol>
<li><a href="{escape(first_href)}">{escape(title)}</a></li>
</ol>
</nav>
<nav epub:type="page-list">
<ol>
<li><a href="{escape(first_href)}">{escape(title)}</a></li>
</ol>
</nav>
</body>
</html>'''

    with open(nav_path, "w", encoding="utf-8") as f_nav:
        f_nav.write(content)

    print(f"nav.xhtml generated at: {nav_path}")
    print(f"First page used: {first_href}")


def generate_style_css(base_path=None):
    """
    Create temp/OEBPS/Text/style.css with CSS suited for a fixed-layout EPUB
    taking the full screen (no white borders).

    Final path:
        base_path/temp/OEBPS/Text/style.css

    If base_path is None, the current working directory is used.
    """
    if base_path is None:
        base_path = os.getcwd()

    text_dir = os.path.join(base_path, "temp", "OEBPS", "Text")
    os.makedirs(text_dir, exist_ok=True)

    css_path = os.path.join(text_dir, "style.css")

    css_content = """html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background-color: #000000; /* or #FFFFFF if you prefer a white background */
}

body > div {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
}

/* Fullscreen image pages */
img {
    display: block;
    margin: 0 auto;      /* horizontally centered */
    padding: 0;
    border: none;

    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
}
"""

    with open(css_path, "w", encoding="utf-8") as f_css:
        f_css.write(css_content)

    print(f"style.css generated at: {css_path}")


def sanitize_filename(name: str) -> str:
    """
    Simplify a string so it can be safely used as a filename.
    Keep letters, digits, spaces, dashes and underscores.
    Replace everything else with "_".
    """
    return "".join(
        c if c.isalnum() or c in (" ", "-", "_") else "_"
        for c in name
    ).strip() or "book"


def create_epub_from_temp(base_path=None, title="title"):
    """
    Zip the entire content of base_path/temp/ into an EPUB file named "title.epub".

    EPUB rules:
        * the 'mimetype' file must be the FIRST entry in the ZIP
          and must be stored without compression (ZIP_STORED).
        * all other files can be compressed (ZIP_DEFLATED).

    - base_path: directory containing 'temp' (defaults to current directory)
    - title: used as the .epub filename => "<title>.epub"
    """

    if base_path is None:
        base_path = os.getcwd()

    temp_dir = os.path.join(base_path, "temp")
    if not os.path.isdir(temp_dir):
        raise FileNotFoundError(f"'temp' folder not found at: {temp_dir}")

    # Output EPUB filename
    safe_title = sanitize_filename(title)
    epub_filename = f"{safe_title}.epub"
    epub_path = os.path.join(base_path, epub_filename)

    mimetype_path = os.path.join(temp_dir, "mimetype")
    if not os.path.isfile(mimetype_path):
        raise FileNotFoundError(f"'mimetype' file not found at: {mimetype_path}")

    # Create the ZIP (EPUB)
    with zipfile.ZipFile(epub_path, "w") as zf:
        # 1) Add 'mimetype' first, uncompressed
        zf.write(
            mimetype_path,
            arcname="mimetype",
            compress_type=zipfile.ZIP_STORED
        )

        # 2) Add all other files/folders under temp/
        for root, dirs, files in os.walk(temp_dir):
            for filename in files:
                full_path = os.path.join(root, filename)

                # Skip 'mimetype' since it was already added
                if os.path.abspath(full_path) == os.path.abspath(mimetype_path):
                    continue

                # Relative path inside the archive (without the temp/ prefix)
                rel_path = os.path.relpath(full_path, temp_dir)

                zf.write(
                    full_path,
                    arcname=rel_path,
                    compress_type=zipfile.ZIP_DEFLATED
                )

    print(f"EPUB created: {epub_path}")

    # Remove the temp folder once the EPUB has been created
    try:
        shutil.rmtree(temp_dir)
        print(f"Temporary folder removed: {temp_dir}")
    except Exception as e:
        print(f"Warning: could not remove temp folder {temp_dir}: {e}")

    return epub_path


# Example usage
if __name__ == "__main__":
    # =========================
    # 1) Configuration variables
    # =========================
    base_path = os.getcwd()  # or a specific path if preferred

    source_images = r"./test_book"

    title = "test title"
    creator = "test author"

    has_cover = True          # True = first image is used as cover
    reading_direction = "rtl" # "rtl" or "ltr"

    # Resolution used in metadata
    original_resolution = "1072x1448"

    # =========================
    # 2) Book ID
    # =========================
    book_id = f"urn:uuid:{uuid.uuid4()}"
    print(f"Generated bookId: {book_id}")

    # =========================
    # 3) Generation pipeline
    # =========================

    # 3.1 Create temp structure + mimetype + META-INF/container.xml, etc.
    initial_setup()  # pass base_path=base_path if your function needs it

    # 3.2 Copy images from source folder to temp/OEBPS/Images
    copy_images_to_temp_images(source_folder=source_images, base_path=base_path)

    # 3.3 Generate XHTML files in temp/OEBPS/Text
    generate_xhtml_pages(base_path=base_path, fallback_width=1046, fallback_height=1448)

    # 3.4 Generate content.opf in temp/OEBPS/
    generate_content_opf(
        base_path=base_path,
        title=title,
        creator=creator,
        has_cover=has_cover,
        reading_direction=reading_direction,
        original_resolution=original_resolution,
        book_id=book_id,
        spread_mode="auto",
    )

    # 3.5 Generate toc.ncx in temp/OEBPS/
    generate_toc_ncx(
        base_path=base_path,
        book_id=book_id,
        title=title,
    )

    # 3.6 Generate nav.xhtml and style.css
    generate_nav_xhtml(base_path=base_path, title=title)
    generate_style_css(base_path=base_path)

    # 3.7 Create final EPUB file from temp/
    create_epub_from_temp(
        base_path=base_path,
        title=title,
    )

    print("\nEPUB structure generation finished.")
