"""Bedown GUI — a CustomTkinter wrapper around the scraper.

Single-window app for designers who never open Terminal.
The scrape itself runs on a background thread; the UI thread polls a queue
for log lines and progress updates and stays responsive throughout.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog

from bedown import __version__
from bedown.scraper import (
    ScrapeOptions,
    default_output_dir,
    is_valid_behance_profile_url,
    run as run_scrape,
)


# Sentinel objects placed on the queue for non-log events.
@dataclass
class _Progress:
    done: int
    total: int


@dataclass
class _Done:
    saved: int
    images: int
    skipped: int
    failed: int
    cancelled: bool
    output_dir: Path


@dataclass
class _Error:
    message: str


class BedownApp(ctk.CTk):
    POLL_MS = 100

    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.title("Bedown")
        self.geometry("680x620")
        self.minsize(560, 540)

        self._queue: "queue.Queue[object]" = queue.Queue()
        self._cancel_event: Optional[threading.Event] = None
        self._worker: Optional[threading.Thread] = None
        self._output_dir: Optional[Path] = None
        self._user_picked_output = False

        self._build_layout()
        self.after(self.POLL_MS, self._drain_queue)

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        pad = {"padx": 20, "pady": 6}

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 0))
        ctk.CTkLabel(
            header, text="Bedown",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Behance portfolio downloader",
            text_color=("gray40", "gray70"),
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w")

        # URL input
        ctk.CTkLabel(self, text="Behance profile URL", anchor="w").pack(
            fill="x", padx=20, pady=(16, 2)
        )
        self.url_entry = ctk.CTkEntry(
            self,
            placeholder_text="https://www.behance.net/yourname",
            height=36,
        )
        self.url_entry.pack(fill="x", **pad)
        self.url_entry.bind("<KeyRelease>", lambda _e: self._refresh_default_output())

        # Output folder row
        ctk.CTkLabel(self, text="Save to", anchor="w").pack(
            fill="x", padx=20, pady=(8, 2)
        )
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", **pad)
        self.folder_label = ctk.CTkLabel(
            folder_row,
            text="(enter a URL above)",
            anchor="w",
            text_color=("gray35", "gray70"),
        )
        self.folder_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            folder_row, text="Choose folder…", width=130,
            command=self._choose_folder,
        ).pack(side="right")

        # Options row
        options_row = ctk.CTkFrame(self, fg_color="transparent")
        options_row.pack(fill="x", **pad)
        ctk.CTkLabel(options_row, text="Max width (px)").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.max_width_entry = ctk.CTkEntry(options_row, width=90)
        self.max_width_entry.insert(0, "1200")
        self.max_width_entry.grid(row=0, column=1, sticky="w", padx=(0, 24))
        ctk.CTkLabel(options_row, text="Delay between projects (s)").grid(
            row=0, column=2, sticky="w", padx=(0, 8)
        )
        self.delay_entry = ctk.CTkEntry(options_row, width=70)
        self.delay_entry.insert(0, "2.0")
        self.delay_entry.grid(row=0, column=3, sticky="w")

        # Download button
        self.download_button = ctk.CTkButton(
            self, text="Download", height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_download_click,
        )
        self.download_button.pack(fill="x", padx=20, pady=(14, 6))

        # Progress bar — pack at the right position, then hide until a run starts.
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0.0)
        self.progress.pack(fill="x", padx=20, pady=(0, 8))
        self.progress.pack_forget()

        # Status text area
        self._status_label = ctk.CTkLabel(self, text="Status", anchor="w")
        self._status_label.pack(fill="x", padx=20, pady=(8, 2))
        self.status_box = ctk.CTkTextbox(
            self,
            height=220,
            font=ctk.CTkFont(family="Menlo", size=12),
            wrap="word",
        )
        self.status_box.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        self.status_box.configure(state="disabled")

        # Bottom row — Open folder button (hidden until success)
        self.open_button = ctk.CTkButton(
            self, text="Open output folder", width=180,
            command=self._open_output_folder,
        )
        # Packed on completion.

        self.footer = ctk.CTkLabel(
            self, text=f"v{__version__}",
            text_color=("gray60", "gray50"),
            font=ctk.CTkFont(size=11),
        )
        self.footer.pack(side="bottom", pady=(0, 8))

    # --------------------------------------------------------- UI helpers

    def _refresh_default_output(self) -> None:
        if self._user_picked_output:
            return
        url = self.url_entry.get().strip()
        if is_valid_behance_profile_url(url):
            self._output_dir = default_output_dir(url)
            self.folder_label.configure(text=str(self._output_dir))
        else:
            self._output_dir = None
            self.folder_label.configure(text="(enter a URL above)")

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose output folder")
        if chosen:
            self._output_dir = Path(chosen)
            self._user_picked_output = True
            self.folder_label.configure(text=str(self._output_dir))

    def _append_status(self, line: str) -> None:
        self.status_box.configure(state="normal")
        self.status_box.insert("end", line + "\n")
        self.status_box.see("end")
        self.status_box.configure(state="disabled")

    def _clear_status(self) -> None:
        self.status_box.configure(state="normal")
        self.status_box.delete("1.0", "end")
        self.status_box.configure(state="disabled")

    def _show_progress(self, show: bool) -> None:
        if show:
            if not self.progress.winfo_ismapped():
                self.progress.pack(
                    fill="x", padx=20, pady=(0, 8),
                    before=self._status_label,
                )
            self.progress.set(0.0)
        else:
            if self.progress.winfo_ismapped():
                self.progress.pack_forget()

    def _show_open_button(self, show: bool) -> None:
        if show:
            if not self.open_button.winfo_ismapped():
                self.open_button.pack(pady=(0, 6))
        else:
            if self.open_button.winfo_ismapped():
                self.open_button.pack_forget()

    # ------------------------------------------------------- Run lifecycle

    def _on_download_click(self) -> None:
        if self._worker and self._worker.is_alive():
            self._cancel_run()
        else:
            self._start_run()

    def _start_run(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self._append_status("Please enter a Behance profile URL.")
            return
        if not is_valid_behance_profile_url(url):
            self._append_status(
                f"'{url}' does not look like a Behance profile URL.\n"
                "Expected: https://www.behance.net/<username>"
            )
            return

        try:
            max_width = int(self.max_width_entry.get())
            if max_width < 100 or max_width > 10000:
                raise ValueError
        except ValueError:
            self._append_status("Max width must be a number between 100 and 10000.")
            return

        try:
            delay = float(self.delay_entry.get())
            if delay < 0:
                raise ValueError
        except ValueError:
            self._append_status("Delay must be a non-negative number.")
            return

        if self._output_dir is None:
            self._output_dir = default_output_dir(url)

        opts = ScrapeOptions(
            profile_url=url,
            output_dir=self._output_dir,
            max_width=max_width,
            headless=True,
            delay=delay,
        )

        self._clear_status()
        self._append_status(f"Starting download → {self._output_dir}")
        self._show_progress(True)
        self._show_open_button(False)
        self.download_button.configure(text="Cancel")

        self._cancel_event = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_run, args=(opts,), daemon=True
        )
        self._worker.start()

    def _cancel_run(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._append_status("Cancelling…")
            self.download_button.configure(text="Cancelling…", state="disabled")

    def _worker_run(self, opts: ScrapeOptions) -> None:
        def log(msg: str) -> None:
            self._queue.put(str(msg))

        def progress(done: int, total: int) -> None:
            self._queue.put(_Progress(done, total))

        try:
            result = run_scrape(
                opts, log=log, cancel_event=self._cancel_event, progress=progress
            )
        except Exception as e:
            self._queue.put(_Error(f"Unexpected error: {e}"))
            return

        cancelled = result.errors == ["cancelled"]
        self._queue.put(_Done(
            saved=result.saved,
            images=result.images,
            skipped=result.skipped,
            failed=result.failed,
            cancelled=cancelled,
            output_dir=opts.output_dir,
        ))

    def _drain_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, str):
                    self._append_status(item)
                elif isinstance(item, _Progress):
                    if item.total > 0:
                        self.progress.set(item.done / item.total)
                elif isinstance(item, _Error):
                    self._append_status(f"! {item.message}")
                    self._reset_after_run()
                elif isinstance(item, _Done):
                    self._handle_done(item)
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._drain_queue)

    def _handle_done(self, done: _Done) -> None:
        if done.cancelled:
            self._append_status("Run cancelled.")
        else:
            self._append_status(
                f"Done — {done.saved} projects saved, "
                f"{done.images} images downloaded, "
                f"{done.skipped} skipped"
                + (f", {done.failed} failed" if done.failed else "")
            )
            self._show_open_button(True)
        self._reset_after_run()

    def _reset_after_run(self) -> None:
        self.download_button.configure(text="Download", state="normal")
        self._show_progress(False)
        self._cancel_event = None
        self._worker = None

    def _open_output_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            if sys.platform == "darwin":
                subprocess.run(["open", str(self._output_dir)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(self._output_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(self._output_dir)], check=False)


def launch() -> None:
    app = BedownApp()
    app.mainloop()
