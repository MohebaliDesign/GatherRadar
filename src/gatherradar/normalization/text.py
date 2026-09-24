"""Internal parsing copies only: never assign folded text to source fields."""
from persiantools import characters, digits


def fold(text: str) -> str:
    text = characters.ar_to_fa(digits.fa_to_en(digits.ar_to_fa(text)))
    return " ".join(text.replace("\u200c", " ").replace("\u200f", "").split()).casefold()
