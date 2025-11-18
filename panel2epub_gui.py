# -*- coding: utf-8 -*-
import os
import uuid
import threading
import traceback
import zipfile
import shutil

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from convert_to_epub import (
    initial_setup,
    copy_images_to_temp_images,
    generate_xhtml_pages,
    generate_content_opf,
    generate_toc_ncx,
    generate_nav_xhtml,
    generate_style_css,
    create_epub_from_temp,
)


def parse_resolution(res_str, default=(1072, 1448)):
    """
    Parse a resolution string of the form "widthxheight" and return a tuple (width, height).

    If parsing fails or the format is invalid, the provided default resolution is returned.
    """
    try:
        parts = res_str.lower().split("x")
        if len(parts) != 2:
            return default
        w = int(parts[0].strip())
        h = int(parts[1].strip())
        return (w, h)
    except Exception:
        return default


def run_pipeline_folder(
    source_images,
    base_path,
    title,
    creator,
    has_cover,
    reading_direction,
    original_resolution,
    book_id,
    spread_mode,
    double_page_ratio,
    log_callback,
):
    """
    Run the full EPUB generation pipeline for a folder of images.

    Steps:
      1) Create temp EPUB structure under base_path.
      2) Copy images into temp/OEBPS/Images.
      3) Generate XHTML pages and optionally split double pages.
      4) Generate content.opf.
      5) Generate toc.ncx.
      6) Generate nav.xhtml and style.css.
      7) Create the final .epub file.
    """
    log = log_callback

    log("=== Converting an image folder ===\n")
    log(f"Source images: {source_images}\n")
    log(f"Output folder (base_path): {base_path}\n")
    log(f"Title: {title}\n")
    log(f"Author: {creator}\n")
    log(f"Reading direction: {reading_direction}\n")
    log(f"Original resolution: {original_resolution}\n")
    log(f"BookID: {book_id}\n")
    log(f"rendition:spread: {spread_mode}\n")
    log(f"double_page_ratio: {double_page_ratio}\n\n")

    if not os.path.isdir(source_images):
        raise ValueError(f"Source folder does not exist: {source_images}")

    os.makedirs(base_path, exist_ok=True)

    # 1) Temp structure + mimetype + META-INF/container.xml, etc.
    log("[1/7] Initializing EPUB structure (temp)...\n")
    initial_setup(base_path=base_path)

    # 2) Copy images to temp/OEBPS/Images
    log("[2/7] Copying images to temp/OEBPS/Images...\n")
    copy_images_to_temp_images(source_folder=source_images, base_path=base_path)

    # 3) Generate XHTML pages (with optional double-page splitting)
    log("[3/7] Generating XHTML files...\n")
    fallback_w, fallback_h = parse_resolution(original_resolution)
    generate_xhtml_pages(
        base_path=base_path,
        fallback_width=fallback_w,
        fallback_height=fallback_h,
        reading_direction=reading_direction,
        double_page_ratio=double_page_ratio,
    )

    # 4) Generate content.opf
    log("[4/7] Generating content.opf...\n")
    generate_content_opf(
        base_path=base_path,
        title=title,
        creator=creator,
        has_cover=has_cover,
        reading_direction=reading_direction,
        original_resolution=original_resolution,
        book_id=book_id,
        spread_mode=spread_mode,
    )

    # 5) Generate toc.ncx
    log("[5/7] Generating toc.ncx...\n")
    generate_toc_ncx(
        base_path=base_path,
        book_id=book_id,
        title=title,
    )

    # 6) Generate nav.xhtml + style.css
    log("[6/7] Generating nav.xhtml and style.css...\n")
    generate_nav_xhtml(base_path=base_path, title=title)
    generate_style_css(base_path=base_path)

    # 7) Create .epub file
    log("[7/7] Creating EPUB file...\n")
    epub_path = create_epub_from_temp(
        base_path=base_path,
        title=title,
    )

    log("\nConversion finished successfully.\n")
    log(f"EPUB generated: {epub_path}\n")
    return epub_path


def run_pipeline_cbz_list(
    cbz_paths,
    root_base_path,
    creator,
    has_cover,
    reading_direction,
    original_resolution,
    spread_mode,
    double_page_ratio,
    log_callback,
):
    """
    Process a list of CBZ files.

    For each CBZ:
      - Extract into root_base_path/<cbz_name>_extract
      - Run the full EPUB pipeline with base_path = root_base_path
      - title = CBZ filename without extension
      - book_id is auto-generated
      - the extraction folder is deleted after conversion

    Result:
      - a single temp folder: root_base_path/temp (re-created for each CBZ)
      - all EPUB files generated directly in root_base_path
    """
    log = log_callback
    generated_epubs = []

    if not cbz_paths:
        raise ValueError("No CBZ files provided.")

    log(f"=== Converting {len(cbz_paths)} CBZ file(s) ===\n")
    log(f"Output root folder: {root_base_path}\n\n")

    os.makedirs(root_base_path, exist_ok=True)

    for idx, cbz_path in enumerate(cbz_paths, start=1):
        log(f"--- [{idx}/{len(cbz_paths)}] {cbz_path} ---\n")

        if not os.path.isfile(cbz_path):
            log(f"File not found, skipping: {cbz_path}\n")
            continue

        base_name = os.path.splitext(os.path.basename(cbz_path))[0]

        # Title = CBZ name (without extension)
        title = base_name
        book_id = f"urn:uuid:{uuid.uuid4()}"

        # Extraction directory (base_path for EPUB remains root_base_path)
        extract_dir = os.path.join(root_base_path, f"{base_name}_extract")
        os.makedirs(extract_dir, exist_ok=True)

        log(f"Extracting {cbz_path} to {extract_dir}...\n")
        with zipfile.ZipFile(cbz_path, "r") as zf:
            zf.extractall(extract_dir)

        try:
            # Run EPUB pipeline with base_path = root_base_path
            epub_path = run_pipeline_folder(
                source_images=extract_dir,
                base_path=root_base_path,
                title=title,
                creator=creator,
                has_cover=has_cover,
                reading_direction=reading_direction,
                original_resolution=original_resolution,
                book_id=book_id,
                spread_mode=spread_mode,
                double_page_ratio=double_page_ratio,
                log_callback=log_callback,
            )

            generated_epubs.append(epub_path)
            log("\n")

        finally:
            # Clean up the extraction folder
            if os.path.exists(extract_dir):
                try:
                    shutil.rmtree(extract_dir)
                    log(f"Removed extraction folder: {extract_dir}\n")
                except Exception as e:
                    log(f"Could not remove extraction folder {extract_dir}: {e}\n")

    return generated_epubs


class EpubApp(tk.Tk):
    """
    Simple Tkinter GUI to drive the EPUB generation pipeline
    either from a folder of images or from one or more CBZ files.
    """

    def __init__(self):
        super().__init__()

        self.title("Convert to EPUB")
        self.geometry("900x650")

        # Store the actual list of selected CBZ files
        self.cbz_files = []

        self._build_ui()

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)

        row = 0

        # --- Source type (folder or CBZ) ---
        ttk.Label(main_frame, text="Source type:").grid(row=row, column=0, sticky="w")
        self.var_source_mode = tk.StringVar(value="cbz")
        rb_cbz = ttk.Radiobutton(
            main_frame, text="CBZ file(s)", variable=self.var_source_mode, value="cbz"
        )
        rb_folder = ttk.Radiobutton(
            main_frame, text="Image folder", variable=self.var_source_mode, value="folder"
        )
        rb_cbz.grid(row=row, column=1, sticky="w")
        rb_folder.grid(row=row, column=2, sticky="w")
        row += 1

        # --- Source (folder or CBZ) ---
        ttk.Label(main_frame, text="Source:").grid(row=row, column=0, sticky="w")
        self.var_source = tk.StringVar()
        entry_source = ttk.Entry(main_frame, textvariable=self.var_source, width=70)
        entry_source.grid(row=row, column=1, sticky="we", padx=5)
        btn_browse_source = ttk.Button(main_frame, text="Browse...", command=self.browse_source)
        btn_browse_source.grid(row=row, column=2, sticky="w")
        row += 1

        # --- Output root folder ---
        ttk.Label(main_frame, text="Output root folder:").grid(row=row, column=0, sticky="w")
        self.var_base_path = tk.StringVar(value=os.getcwd())
        entry_base = ttk.Entry(main_frame, textvariable=self.var_base_path, width=70)
        entry_base.grid(row=row, column=1, sticky="we", padx=5)
        btn_browse_base = ttk.Button(main_frame, text="Browse...", command=self.browse_base)
        btn_browse_base.grid(row=row, column=2, sticky="w")
        row += 1

        # --- Title (folder mode only) ---
        ttk.Label(main_frame, text="Title (folder mode only):").grid(row=row, column=0, sticky="w")
        self.var_title = tk.StringVar(value="")
        entry_title = ttk.Entry(main_frame, textvariable=self.var_title, width=70)
        entry_title.grid(row=row, column=1, columnspan=2, sticky="we", padx=5)
        row += 1

        # --- Author ---
        ttk.Label(main_frame, text="Author:").grid(row=row, column=0, sticky="w")
        self.var_creator = tk.StringVar(value="")
        entry_creator = ttk.Entry(main_frame, textvariable=self.var_creator, width=70)
        entry_creator.grid(row=row, column=1, columnspan=2, sticky="we", padx=5)
        row += 1

        # --- Has cover ---
        self.var_has_cover = tk.BooleanVar(value=True)
        chk_cover = ttk.Checkbutton(
            main_frame,
            text="Use the first image as cover, or a file named cover.png / cover.jpg / ... if present.",
            variable=self.var_has_cover,
        )
        chk_cover.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        # --- Reading direction ---
        ttk.Label(main_frame, text="Reading direction:").grid(row=row, column=0, sticky="w")
        self.var_reading_dir = tk.StringVar(value="rtl")
        rb_rtl = ttk.Radiobutton(main_frame, text="RTL (manga)", variable=self.var_reading_dir, value="rtl")
        rb_ltr = ttk.Radiobutton(main_frame, text="LTR", variable=self.var_reading_dir, value="ltr")
        rb_rtl.grid(row=row, column=1, sticky="w")
        rb_ltr.grid(row=row, column=2, sticky="w")
        row += 1

        # --- Original resolution ---
        ttk.Label(main_frame, text="Original resolution (w x h):").grid(row=row, column=0, sticky="w")
        self.var_resolution = tk.StringVar(value="1072x1448")
        entry_res = ttk.Entry(main_frame, textvariable=self.var_resolution, width=20)
        entry_res.grid(row=row, column=1, sticky="w", padx=5)
        row += 1

        # --- Double page ratio ---
        ttk.Label(main_frame, text="Double page ratio (w/h ≥):").grid(row=row, column=0, sticky="w")
        self.var_double_ratio = tk.StringVar(value="1.28")
        entry_ratio = ttk.Entry(main_frame, textvariable=self.var_double_ratio, width=10)
        entry_ratio.grid(row=row, column=1, sticky="w", padx=5)
        row += 1

        # --- rendition:spread mode ---
        ttk.Label(main_frame, text="Spread mode (rendition:spread):").grid(row=row, column=0, sticky="w")
        self.var_spread_mode = tk.StringVar(value="auto")
        combo_spread = ttk.Combobox(
            main_frame,
            textvariable=self.var_spread_mode,
            values=["auto", "none", "landscape", "both"],
            state="readonly",
            width=15,
        )
        combo_spread.grid(row=row, column=1, sticky="w", padx=5)
        row += 1

        # --- BookID (folder mode only) ---
        ttk.Label(main_frame, text="BookID (folder mode, empty = auto):").grid(row=row, column=0, sticky="w")
        self.var_bookid = tk.StringVar()
        entry_bookid = ttk.Entry(main_frame, textvariable=self.var_bookid, width=70)
        entry_bookid.grid(row=row, column=1, columnspan=2, sticky="we", padx=5)
        row += 1

        # --- Start button ---
        self.btn_start = ttk.Button(main_frame, text="Generate EPUB", command=self.on_start)
        self.btn_start.grid(row=row, column=0, columnspan=3, pady=10)
        row += 1

        # --- Log area ---
        ttk.Label(main_frame, text="Log:").grid(row=row, column=0, sticky="nw")
        self.txt_log = tk.Text(main_frame, height=15, wrap="word")
        self.txt_log.grid(row=row, column=1, columnspan=2, sticky="nsew", padx=5)
        row += 1

        scroll = ttk.Scrollbar(main_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        scroll.grid(row=row - 1, column=3, sticky="ns")

        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(row - 1, weight=1)

    # --- UI Callbacks ---

    def browse_source(self):
        """
        Let the user select the source (image folder or CBZ files),
        depending on the current mode.
        """
        mode = self.var_source_mode.get()
        if mode == "folder":
            folder = filedialog.askdirectory(title="Select image folder")
            if folder:
                self.var_source.set(folder)
                self.cbz_files = []
        else:
            paths = filedialog.askopenfilenames(
                title="Select one or more CBZ files",
                filetypes=[("CBZ files", "*.cbz"), ("All files", "*.*")],
            )
            if paths:
                self.cbz_files = list(paths)
                display = "; ".join(os.path.basename(p) for p in paths)
                self.var_source.set(display)

    def browse_base(self):
        """
        Let the user select the output root folder.
        """
        folder = filedialog.askdirectory(title="Select output root folder")
        if folder:
            self.var_base_path.set(folder)

    def log(self, text: str):
        """
        Append a line to the log Text widget and scroll to the end.
        """
        self.txt_log.insert("end", text)
        self.txt_log.see("end")

    def thread_safe_log(self, text: str):
        """
        Thread-safe wrapper to log from background threads using Tkinter's 'after'.
        """
        self.after(0, self.log, text)

    def on_start(self):
        """
        Validate inputs and start the EPUB generation in a background thread.
        """
        mode = self.var_source_mode.get()
        source_display = self.var_source.get().strip()
        base_root = self.var_base_path.get().strip()
        title = self.var_title.get().strip()
        creator = self.var_creator.get().strip()
        has_cover = self.var_has_cover.get()
        reading_dir = self.var_reading_dir.get()
        original_resolution = self.var_resolution.get().strip()
        spread_mode = self.var_spread_mode.get().strip()
        bookid_input = self.var_bookid.get().strip()
        double_ratio_str = self.var_double_ratio.get().strip()

        # Simple parsing of the ratio
        try:
            double_page_ratio = float(double_ratio_str.replace(",", ".")) if double_ratio_str else 1.3
        except Exception:
            double_page_ratio = 1.3
        self.var_double_ratio.set(str(double_page_ratio))

        if not base_root:
            base_root = os.getcwd()
            self.var_base_path.set(base_root)

        if not creator:
            messagebox.showerror("Error", "Please enter an author.")
            return

        if not source_display:
            messagebox.showerror("Error", "Please select a source (folder or CBZ).")
            return

        if mode == "folder":
            source_folder = source_display
            if not os.path.isdir(source_folder):
                messagebox.showerror("Error", "The image source folder is invalid.")
                return
            if not title:
                messagebox.showerror("Error", "Please enter a title (folder mode).")
                return
            if bookid_input:
                book_id = bookid_input
            else:
                book_id = f"urn:uuid:{uuid.uuid4()}"
                self.var_bookid.set(book_id)
        else:  # CBZ mode
            if not self.cbz_files:
                messagebox.showerror("Error", "No CBZ files selected.")
                return
            # In CBZ mode: BookID is auto-generated per file, BookID input is ignored
            book_id = None  # not used in this mode

        self.txt_log.delete("1.0", "end")
        self.btn_start.config(state="disabled")

        def done(success: bool, message: str):
            """
            Called when the background work is finished, to re-enable the UI
            and show a final message to the user.
            """
            def _finish():
                self.btn_start.config(state="normal")
                if success:
                    messagebox.showinfo("Success", message)
                else:
                    messagebox.showerror("Error", message)
            self.after(0, _finish)

        def worker():
            """
            Background worker that performs the actual conversion.
            """
            try:
                if mode == "folder":
                    epub_path = run_pipeline_folder(
                        source_images=source_folder,
                        base_path=base_root,
                        title=title,
                        creator=creator,
                        has_cover=has_cover,
                        reading_direction=reading_dir,
                        original_resolution=original_resolution,
                        book_id=book_id,
                        spread_mode=spread_mode,
                        double_page_ratio=double_page_ratio,
                        log_callback=self.thread_safe_log,
                    )
                    done(True, f"EPUB generated: {epub_path}")
                else:
                    epubs = run_pipeline_cbz_list(
                        cbz_paths=self.cbz_files,
                        root_base_path=base_root,
                        creator=creator,
                        has_cover=has_cover,
                        reading_direction=reading_dir,
                        original_resolution=original_resolution,
                        spread_mode=spread_mode,
                        double_page_ratio=double_page_ratio,
                        log_callback=self.thread_safe_log,
                    )
                    if epubs:
                        msg = "EPUB files generated:\n" + "\n".join(epubs)
                        done(True, msg)
                    else:
                        done(False, "No EPUB generated (error or invalid CBZ files).")
            except Exception as e:
                err_msg = f"Error: {e}\n\n{traceback.format_exc()}"
                self.thread_safe_log(err_msg)
                done(False, str(e))

        t = threading.Thread(target=worker, daemon=True)
        t.start()


if __name__ == "__main__":
    app = EpubApp()
    app.mainloop()
