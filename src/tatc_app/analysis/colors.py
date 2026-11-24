"""
Display colors of satellites and their instruments in animated results.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import colorsys
from typing import Dict, Optional, Sequence, Tuple

# categorical colors (Tableau 10) assigned to satellites without a color
PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    """
    Converts a hex color (`#rrggbb`) to red, green, and blue values (0-255).
    """
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def assign_colors(
    members: Sequence[str], colors: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """
    Assigns a color to each member, defaulting to a categorical palette.

    Args:
        members (Sequence[str]): The member names.
        colors (Optional[Dict[str, str]]): Requested colors by member name.

    Returns:
        Dict[str, str]: The color (`#rrggbb`) of each member.
    """
    colors = colors or {}
    return {
        member: colors.get(member) or PALETTE[i % len(PALETTE)]
        for i, member in enumerate(members)
    }


def instrument_color(color: str, index: int, count: int) -> str:
    """
    Derives a distinct color for each instrument of a satellite: the first
    instrument keeps the satellite color, and others rotate its hue evenly
    (with a minimum saturation, so variants of gray colors stay distinct).

    The client mirrors this in `defaultInstrumentColor` (static/design-state.js).

    Args:
        color (str): The satellite color (`#rrggbb`).
        index (int): The instrument index.
        count (int): The number of instruments of the satellite.

    Returns:
        str: The instrument color (`#rrggbb`).
    """
    if index <= 0 or count <= 1:
        return color
    red, green, blue = (c / 255 for c in hex_to_rgb(color))
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    red, green, blue = colorsys.hls_to_rgb(
        (hue + index / count) % 1, lightness, max(saturation, 0.5)
    )
    return "#" + "".join(f"{round(c * 255):02x}" for c in (red, green, blue))
