"""Transcript price guard and spoken price extraction."""

import re
from typing import Literal

URDU_DIGITS = {
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
}

# 1-99 Roman Urdu & Urdu script mapping
NUMBER_WORDS: dict[str, int] = {
    # 1 - 10
    "aik": 1, "ek": 1, "ایک": 1,
    "do": 2, "دو": 2,
    "teen": 3, "tin": 3, "تین": 3,
    "chaar": 4, "char": 4, "چار": 4,
    "paanch": 5, "panch": 5, "پانچ": 5,
    "chhe": 6, "che": 6, "چھ": 6,
    "saat": 7, "سات": 7,
    "aath": 8, "ath": 8, "آٹھ": 8,
    "nau": 9, "no": 9, "نو": 9,
    "das": 10, "دس": 10,
    # 11 - 20
    "gyarah": 11, "gyaara": 11, "گیارہ": 11,
    "barah": 12, "baara": 12, "بارہ": 12,
    "terah": 13, "tera": 13, "تیرہ": 13,
    "chaudah": 14, "chauda": 14, "چودہ": 14,
    "pandrah": 15, "pandra": 15, "پندرہ": 15,
    "solah": 16, "sola": 16, "سولہ": 16,
    "satrah": 17, "satra": 17, "سترہ": 17,
    "atharah": 18, "athara": 18, "اٹھارہ": 18,
    "unnees": 19, "unis": 19, "انیس": 19,
    "bees": 20, "bis": 20, "بیس": 20,
    # 21 - 30
    "ikkees": 21, "ikkis": 21, "اکیس": 21,
    "baaees": 22, "baees": 22, "bais": 22, "بائیس": 22,
    "teees": 23, "teis": 23, "تئیس": 23,
    "chaubees": 24, "chaubis": 24, "چوبیس": 24,
    "pachchees": 25, "pachis": 25, "پچیس": 25,
    "chhabbees": 26, "chabbis": 26, "چھبیس": 26,
    "sattaees": 27, "sataees": 27, "satais": 27, "ستائیس": 27,
    "atthaees": 28, "athaees": 28, "athais": 28, "اٹھائیس": 28,
    "untees": 29, "untis": 29, "انتیس": 29,
    "tees": 30, "tis": 30, "تیس": 30,
    # 31 - 40
    "iktees": 31, "iktis": 31, "اکتیس": 31,
    "battees": 32, "battis": 32, "بتیس": 32,
    "tentees": 33, "tentis": 33, "تینتیس": 33,
    "chauntees": 34, "chauntis": 34, "چونتیس": 34,
    "paintees": 35, "paintis": 35, "پینتیس": 35,
    "chhattees": 36, "chhattis": 36, "چھتیس": 36,
    "saintees": 37, "saintis": 37, "سینتیس": 37,
    "arhtees": 38, "arhtis": 38, "athtees": 38, "اڑتیس": 38,
    "untaalees": 39, "untalis": 39, "انتالیس": 39,
    "chaalees": 40, "chalis": 40, "chalees": 40, "chaliss": 40, "چالیس": 40,
    # 41 - 50
    "iktaalees": 41, "iktalis": 41, "iktalees": 41, "ektalis": 41, "اکتالیس": 41,
    "bayaalees": 42, "bayalis": 42, "bayalees": 42, "بیالیس": 42,
    "tentaalees": 43, "tetalis": 43, "tentalis": 43, "tentalees": 43, "تیتالیس": 43,
    "chawalees": 44, "chawalis": 44, "chawalees": 44, "چوالیس": 44,
    "paintaalees": 45, "paintalis": 45, "pantalees": 45, "pantalis": 45, "paintalees": 45, "پینتالیس": 45,
    "chhiyaalees": 46, "chhiyalis": 46, "chheyalis": 46, "chheyalees": 46, "چھیالیس": 46,
    "saintaalees": 47, "saintalis": 47, "santalees": 47, "santalis": 47, "saintalees": 47, "سینتالیس": 47,
    "arhtaalees": 48, "arhtalis": 48, "athtalis": 48, "artalees": 48, "artalis": 48, "اڑتالیس": 48,
    "unchaas": 49, "unchas": 49, "انچاس": 49,
    "pachaas": 50, "pachas": 50, "پچاس": 50,
    # 51 - 60
    "ikyaawan": 51, "ikyawan": 51, "اکیاون": 51,
    "baawan": 52, "bawan": 52, "باون": 52,
    "tarpan": 53, "tirpan": 53, "تیرپن": 53,
    "chawwan": 54, "chawan": 54, "چوون": 54,
    "pachpan": 55, "پچپن": 55,
    "chhappan": 56, "chappan": 56, "چھپن": 56,
    "sattawan": 57, "satawan": 57, "ستاون": 57,
    "atthaawan": 58, "athawan": 58, "اٹھاون": 58,
    "unsath": 59, "unsat": 59, "انسٹھ": 59,
    "saath": 60, "sath": 60, "saatth": 60, "saathh": 60, "ساٹھ": 60,
    # 61 - 70
    "iksath": 61, "iksat": 61, "اکسٹھ": 61,
    "baasath": 62, "basat": 62, "باسٹھ": 62,
    "tarsath": 63, "tirasath": 63, "تریسٹھ": 63,
    "chaunsath": 64, "chonsat": 64, "چونسٹھ": 64,
    "painsath": 65, "painset": 65, "pansath": 65, "pansat": 65, "painsat": 65, "pensath": 65, "pensat": 65, "painstah": 65, "پینسٹھ": 65,
    "chhiyasath": 66, "chiyasat": 66, "چھیاسٹھ": 66,
    "sarsath": 67, "sarsat": 67, "سرسٹھ": 67,
    "arhsath": 68, "arsat": 68, "athsat": 68, "اڑسٹھ": 68,
    "unhattar": 69, "unhatar": 69, "انہتر": 69,
    "sattar": 70, "satar": 70, "ستر": 70,
    # 71 - 80
    "ikhattar": 71, "ikhatar": 71, "ikattar": 71, "اکہتر": 71,
    "bahattar": 72, "bahatar": 72, "bahttar": 72, "بہتر": 72,
    "tihattar": 73, "tihatar": 73, "tihttar": 73, "تہتر": 73,
    "chauhattar": 74, "chauhatar": 74, "chohattar": 74, "چوہتر": 74,
    "pachhattar": 75, "pachhatar": 75, "pachattar": 75, "پچھتر": 75,
    "chhihattar": 76, "chhihatar": 76, "chihattar": 76, "چھہتر": 76,
    "satattar": 77, "satatar": 77, "sathattar": 77, "sathatar": 77, "sattatar": 77, "ستتر": 77,
    "athhattar": 78, "athhatar": 78, "athattar": 78, "اٹھتر": 78,
    "unyasi": 79, "unasi": 79, "اناسی": 79,
    "assi": 80, "asi": 80, "assee": 80, "اسی": 80,
    # 81 - 90
    "ikyasi": 81, "ikasi": 81, "اکیاسی": 81,
    "bayasi": 82, "byasi": 82, "بیاسی": 82,
    "tirasi": 83, "terasi": 83, "تراسی": 83,
    "chaurasi": 84, "chorasi": 84, "چوراسی": 84,
    "pachasi": 85, "pachaasi": 85, "پچاسی": 85,
    "chhiyasi": 86, "chyasi": 86, "چھیاسی": 86,
    "satasi": 87, "sataasi": 87, "ستاسی": 87,
    "athasi": 88, "athaasi": 88, "اٹھاسی": 88,
    "nawasi": 89, "نواسی": 89,
    "nabbe": 90, "nave": 90, "nabbay": 90, "navvay": 90, "nawway": 90, "nawwe": 90, "nabway": 90, "nabbey": 90, "naway": 90, "نوے": 90,
    # 91 - 99
    "ikyaanwe": 91, "ikyanwe": 91, "ikkanve": 91, "اکیانوے": 91,
    "baanwe": 92, "banwe": 92, "بانوے": 92,
    "tiraanwe": 93, "tiranwe": 93, "ترانوے": 93,
    "chauraanwe": 94, "chauranwe": 94, "چورانوے": 94,
    "pachaanve": 95, "pachanve": 95, "pachaanwe": 95, "pachanwe": 95, "پچانوے": 95,
    "chhiyaanwe": 96, "chhiyanwe": 96, "چھیانوے": 96,
    "satataanwe": 97, "satanwe": 97, "ستانوے": 97,
    "atthaanwe": 98, "athanwe": 98, "اٹھانوے": 98,
    "ninaanwe": 99, "ninanwe": 99, "ننانوے": 99,
}

PRICE_WORDS = {
    "rupay", "rupaye", "rupiya", "rupiye", "روپے", "روپیہ", "rs", "rate",
    "ریٹ", "kilo", "کلو", "darjan", "درجن", "daam", "دام", "per", "pkr", "فی",
}


def _replace_urdu_digits(text: str) -> str:
    res = []
    for ch in text:
        res.append(URDU_DIGITS.get(ch, ch))
    return "".join(res)


def _parse_composed_phrase(tokens: list[str]) -> tuple[int | None, int]:
    """Tries to parse a composed number starting at tokens[0].

    Returns (parsed_number, tokens_consumed).
    Handles:
    - "dedh sau" -> 150
    - "dhai sau" -> 250
    - "sawa sau" -> 125
    - "sawa do sau" -> 225
    - "paune do sau" -> 175
    - "paune teen sau" -> 275
    - "aik sau bees" -> 120
    - "do sau pachaas" -> 250
    - "sau" -> 100
    - "hazaar" -> 1000
    - Single numbers: "120", "bees", "pachaanve"
    """
    if not tokens:
        return None, 0

    first = tokens[0].lower()

    # Fractional compound phrases
    if first in ("dedh", "ڈیڑھ"):
        if len(tokens) > 1 and tokens[1].lower() in ("sau", "سو"):
            return 150, 2
        if len(tokens) > 1 and tokens[1].lower() in ("hazaar", "ہزار"):
            return 1500, 2
        return None, 0

    if first in ("dhai", "ڈھائی"):
        if len(tokens) > 1 and tokens[1].lower() in ("sau", "سو"):
            return 250, 2
        if len(tokens) > 1 and tokens[1].lower() in ("hazaar", "ہزار"):
            return 2500, 2
        return None, 0

    if first in ("sawa", "سوا"):
        if len(tokens) > 1 and tokens[1].lower() in ("sau", "سو"):
            return 125, 2
        if len(tokens) > 2 and tokens[1].lower() in NUMBER_WORDS and tokens[2].lower() in ("sau", "سو"):
            base = NUMBER_WORDS[tokens[1].lower()]
            return (base * 100) + 25, 3
        return None, 0

    if first in ("paune", "پونے"):
        if len(tokens) > 1 and tokens[1].lower() in ("sau", "سو"):
            return 75, 2
        if len(tokens) > 2 and tokens[1].lower() in NUMBER_WORDS and tokens[2].lower() in ("sau", "سو"):
            base = NUMBER_WORDS[tokens[1].lower()]
            # paune do sau -> 175 (100 + 75), paune teen sau -> 275 (200 + 75)
            return ((base - 1) * 100) + 75, 3
        return None, 0

    # Western digits
    if re.fullmatch(r"\d+", first):
        val = int(first)
        # Check if followed by "sau" or "hazaar"
        if len(tokens) > 1 and tokens[1].lower() in ("sau", "سو"):
            hundreds = val * 100
            if len(tokens) > 2 and tokens[2].lower() in NUMBER_WORDS:
                return hundreds + NUMBER_WORDS[tokens[2].lower()], 3
            if len(tokens) > 2 and re.fullmatch(r"\d+", tokens[2]):
                return hundreds + int(tokens[2]), 3
            return hundreds, 2
        return val, 1

    # Word hundreds: "aik sau bees", "do sau", etc.
    if first in NUMBER_WORDS:
        base = NUMBER_WORDS[first]
        if len(tokens) > 1 and tokens[1].lower() in ("sau", "سو"):
            hundreds = base * 100
            if len(tokens) > 2 and tokens[2].lower() in NUMBER_WORDS:
                return hundreds + NUMBER_WORDS[tokens[2].lower()], 3
            if len(tokens) > 2 and re.fullmatch(r"\d+", tokens[2]):
                return hundreds + int(tokens[2]), 3
            return hundreds, 2
        if len(tokens) > 1 and tokens[1].lower() in ("hazaar", "ہزار"):
            return base * 1000, 2
        return base, 1

    if first in ("sau", "سو"):
        if len(tokens) > 1 and tokens[1].lower() in NUMBER_WORDS:
            return 100 + NUMBER_WORDS[tokens[1].lower()], 2
        return 100, 1

    if first in ("hazaar", "ہزار"):
        return 1000, 1

    return None, 0


CURRENCY_WORDS = {
    "rupay", "rupaye", "rupiya", "rupiye", "روپے", "روپیہ", "rs", "rate",
    "ریٹ", "daam", "دام", "pkr",
}
RATE_PREPOSITIONS = {"per", "فی"}


def find_spoken_prices(text: str) -> list[int]:
    """Finds all spoken prices in a given utterance.

    A number is counted as a price ONLY when a price context word
    (rupay, rate, rs, daam, per kilo, etc.) appears within its clause context.
    Quantities (e.g. '50 kilo aam') are cleanly distinguished from rates.
    """
    clean_text = _replace_urdu_digits(text)
    raw_tokens = re.findall(r"[\w۰-۹]+|[^\s\w]+", clean_text)
    tokens = [t.lower() for t in raw_tokens if re.match(r"[\w۰-۹]+", t)]

    found_numbers: list[tuple[int, int, int]] = []  # (value, start_idx, end_idx)
    i = 0
    while i < len(tokens):
        val, consumed = _parse_composed_phrase(tokens[i:])
        if val is not None and consumed > 0:
            found_numbers.append((val, i, i + consumed))
            i += consumed
        else:
            i += 1

    prices: list[int] = []
    last_boundary = 0
    for val, start_idx, end_idx in found_numbers:
        start_w = max(last_boundary, start_idx - 3)
        end_w = min(len(tokens), end_idx + 3)
        window = tokens[start_w:end_w]

        is_price = any(w in CURRENCY_WORDS for w in window)
        if not is_price:
            for j in range(start_w, min(len(tokens) - 1, end_w)):
                if tokens[j] in RATE_PREPOSITIONS and tokens[j + 1] in ("kilo", "کلو", "darjan", "درجن", "crate"):
                    is_price = True
                    break

        # Check if the price is explicitly negated/rejected by the speaker
        # e.g., "50 PKR mein deal confirm nahi kar sakta", "50 rupay nahi de sakta"
        post_window = tokens[end_idx : min(len(tokens), end_idx + 7)]
        is_negated = False
        negation_words = {"nahi", "nahin", "nae", "نہیں", "not", "cannot", "can't", "impossible"}
        clause_delimiters = {".", "!", "?", "lekin", "par", "aur", "magar", "jab", "لیکن", "اور", "مگر"}
        for w in post_window:
            if w in clause_delimiters:
                break
            if w in negation_words:
                is_negated = True
                break

        if is_price and not is_negated:
            prices.append(val)
            last_boundary = end_idx
            for k in range(end_idx, min(len(tokens), end_idx + 4)):
                if tokens[k] in CURRENCY_WORDS or tokens[k] in RATE_PREPOSITIONS:
                    last_boundary = max(last_boundary, k + 1)

    return prices


def classify(
    prices: list[int],
    floor: int,
    approved_prices: list[int],
    current_price: int,
) -> Literal["below_floor", "unapproved", "ok"]:
    """Classifies spoken prices against floor and negotiation state.

    - below_floor if any price < floor
    - unapproved if any price < current_price and not in approved_prices and >= floor
    - otherwise ok
    """
    has_unapproved = False
    for p in prices:
        if p < floor:
            return "below_floor"
        if p < current_price and p not in approved_prices:
            has_unapproved = True

    if has_unapproved:
        return "unapproved"
    return "ok"
