"""Importing this module patches rich."""

# pragma: exclude file
from lazi.core import lazi

# lazi imports only actually imported when used,
# helps to speed up loading and the use of optional imports.
with lazi:  # type: ignore[attr-defined] # lazi has incorrectly typed code
    import io
    from typing import Any
    from warnings import warn

    import gorilla
    import requests
    import rich
    import rich.markdown
    import structlog
    from rich.console import Console
    from rich.text import Style  # type: ignore[attr-defined] # no explicit export
    from rich.text import Text
try:
    import chafa

except ImportError:
    warn("chafa not installed; using text fallback.", stacklevel=2)
    chafa = None  # type: ignore[assignment]
try:
    from PIL import Image as PILImage

except ImportError:
    warn("pillow not installed; using text fallback.", stacklevel=2)
    PILImage = None  # type: ignore[assignment]

settings = gorilla.Settings(allow_hit=True)
logger = structlog.getLogger("ttrpgdataman")


@gorilla.patch(rich.markdown.ImageItem, settings=settings)  # type: ignore[no-untyped-call,misc] # pyright: ignore[reportUntypedFunctionDecorator, reportUnknownMemberType]
def __rich_console__(  # noqa: C901, N807, PLR0912, PLR0915
    self: Any,
    console: Console,
    options: rich.console.ConsoleOptions,
) -> rich.console.RenderResult:
    self.source = self.destination
    if PILImage is None or chafa is None:
        placeholder = Text(f"IMG[image: {self.source}]", style="italic")
        if self.link:
            placeholder.stylize(Style(link=self.link), 0, len(placeholder))
        yield placeholder
        return

    # -- fetch/load via Pillow (supports local paths and URLs) --
    try:
        pil: Any
        if self.source.startswith(("http://", "https://")):
            r = requests.get(self.source, timeout=20)
            r.raise_for_status()
            pil = PILImage.open(io.BytesIO(r.content))
        else:
            pil = PILImage.open(self.source)
        pil.load()
    except Exception as e:  # noqa: BLE001
        err = Text(f"[image load error {self.source}: {e}]", style="red")
        if self.link:
            err.stylize(Style(link=self.link), 0, len(err))
        yield err
        return

    # Normalize to common formats and derive PixelType
    bands = pil.getbands()  # e.g., ('R','G','B'), ('R','G','B','A'), ('L',), etc.
    pixel_type = None
    if bands == ("R", "G", "B"):
        pixel_type = chafa.enums.PixelType.CHAFA_PIXEL_RGB8
        pil = pil.convert("RGB")
        channels = 3
    elif bands == ("R", "G", "B", "A"):
        pixel_type = chafa.enums.PixelType.CHAFA_PIXEL_RGBA8_UNASSOCIATED
        pil = pil.convert("RGBA")
        channels = 4
    else:
        # Fallback to RGBA
        pixel_type = chafa.enums.PixelType.CHAFA_PIXEL_RGBA8_UNASSOCIATED
        pil = pil.convert("RGBA")
        channels = 4

    if pixel_type is None:
        # Ultimate fallback if binding uses different names; convert to RGB
        pil = pil.convert("RGB")
        channels = 3
        pixel_type = chafa.enums.PixelType.CHAFA_PIXEL_RGB8

    width_px, height_px = pil.size
    pixels = pil.tobytes()
    rowstride = width_px * channels

    # --- size to terminal width (auto height) ---
    cols = max(16, min(options.max_width or console.size.width, console.size.width))

    # Configure canvas
    config = chafa.canvas_config.CanvasConfig()
    # Prefer width-constrained, auto-height if supported by the binding
    try:
        config.width = int(cols)
        # Many bindings accept 0 to mean "auto"
        config.height = 1
        # config.pixel_mode = chafa.PixelMode.CHAFA_PIXEL_MODE_KITTY
        config.cell_width = 11
        config.cell_height = 24
        config.calc_canvas_geometry(  # pyright: ignore[reportUnknownMemberType]
            # defined in surrounding code
            image.width,  # type: ignore[name-defined] # pyright: ignore[reportUnknownMemberType]  # noqa: F821
            image.height,  # type: ignore[name-defined]  # pyright: ignore[reportUndefinedVariable] # noqa: F821
            11 / 24,
        )

    except Exception:  # noqa: BLE001
        # If attributes don't exist / 0 not accepted, approximate height
        # Note: terminal cell aspect ratio roughly ~ 2:1 height:width, adjust with 0.5
        approx_rows = max(
            1,
            round(cols * (height_px / max(1, width_px)) * 0.5),
        )
        try:
            config.width = int(cols)
            config.height = approx_rows
        except Exception:  # noqa: BLE001
            # If even that fails, chafa will still render with its defaults
            logger.debug("chafa render failed, loading with defaults.")

    # Render
    try:
        canvas = chafa.canvas.Canvas(config)

        canvas.draw_all_pixels(  # pyright: ignore[reportUnknownMemberType]
            pixel_type,
            pixels,
            width_px,
            height_px,
            rowstride,
        )
        # chafa.Canvas.print() usually returns bytes

        out = canvas.print()
        ansi = out.decode() if isinstance(out, (bytes, bytearray)) else str(out)

        txt = Text.from_ansi(ansi)
        if self.link:
            txt.stylize(Style(link=self.link), 0, len(txt))
        yield txt

    except Exception as e:  # noqa: BLE001
        err = Text(f"[chafa error rendering {self.source}: {e}]", style="red")
        if self.link:
            err.stylize(Style(link=self.link), 0, len(err))
        yield err


def patch() -> None:
    """Patches rich via gorilla."""
    logger.debug("patching rich with cli image support via chafa")
    gorilla.apply(  # type: ignore[no-untyped-call] # pyright: ignore[reportUnknownMemberType]
        gorilla.Patch(
            rich.markdown.ImageItem,
            "__rich_console__",
            __rich_console__,
            settings=settings,
        ),
    )
