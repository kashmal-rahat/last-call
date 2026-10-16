"""Negotiator prompt rendering and natural language formatting helpers."""

from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import AwareDatetime

from lastcall_shared.clock import pickup_by_words, time_words
from lastcall_shared.condition_words import FEED_ONLY
from lastcall_shared.models import AgentDealBrief, BuyerType

PROMPT_VERSION = "1.24"
TEMPLATE_DIR = Path(__file__).parent

_GENDER_TABLE = {
    "male": {
        "deta": "deta",
        "raha": "raha",
        "tha": "tha",
        "bol_raha": "bol raha",
        "assistant": "AI assistant",
    },
    "female": {
        "deta": "deti",
        "raha": "rahi",
        "tha": "thi",
        "bol_raha": "bol rahi",
        "assistant": "AI assistant",
    },
}

_NUM_TO_WORDS: dict[int, str] = {
    0: "sifar",
    10: "das",
    15: "pandrah",
    20: "bees",
    25: "pachis",
    30: "tees",
    40: "chalis",
    50: "pachaas",
    60: "saath",
    70: "sattar",
    75: "pachhattar",
    80: "assi",
    85: "pachasi",
    88: "athasi",
    90: "nabbe",
    95: "pachaanve",
    100: "sau",
    110: "aik sau das",
    120: "aik sau bees",
    125: "sawa sau",
    130: "aik sau tees",
    140: "aik sau chalis",
    150: "dedh sau",
    160: "aik sau saath",
    170: "aik sau sattar",
    175: "paune do sau",
    180: "aik sau assi",
    188: "aik sau athasi",
    190: "aik sau nabbe",
    200: "do sau",
    220: "do sau bees",
    225: "sawa do sau",
    230: "do sau tees",
    250: "dhai sau",
    275: "paune teen sau",
    300: "teen sau",
}


def number_to_words(n: int) -> str:
    if n in _NUM_TO_WORDS:
        return _NUM_TO_WORDS[n]
    if n < 100:
        return str(n)
    hundreds = n // 100
    rem = n % 100
    h_word = "sau" if hundreds == 1 else f"{hundreds} sau"
    if rem == 0:
        return h_word
    rem_word = _NUM_TO_WORDS.get(rem, str(rem))
    return f"{h_word} {rem_word}"


def unit_words(unit: str) -> str:
    return "kilo" if unit == "kg" else "darjan"


def unit_words_en(unit: str) -> str:
    """The unit for an English-speaking buyer (a judge testing the call): "kilo" or "dozen"."""
    return "kilo" if unit == "kg" else "dozen"


def price_words(amount: int, unit: str) -> str:
    w = number_to_words(amount)
    u = unit_words(unit)
    return f"{w} rupay per {u}"


def _digits(quantity: float) -> str:
    return f"{int(quantity)}" if quantity.is_integer() else f"{quantity}"


def spoken_amount(quantity: float) -> str:
    """A quantity as people say it on a call: halves in their own words (0.5 "aadha", 1.5 "dedh", 2.5 "dhaai",
    4.5 "saadhe 4", which the agent says "saadhe chaar"), the only fractions a photo estimate gives (D71). Any
    other amount stays in digits."""
    whole = int(quantity)
    if quantity - whole == 0.5:
        return {0: "aadha", 1: "dedh", 2: "dhaai"}.get(whole, f"saadhe {whole}")
    return _digits(quantity)


def quantity_words(quantity: float, unit: str, confirmed: bool = True, spoken: bool = False) -> str:
    """ "4.5 kilo", or on a voice call "saadhe 4 kilo" (a decimal is read out as "chaar ishariya paanch")."""
    u = unit_words(unit)
    q_str = spoken_amount(quantity) if spoken else _digits(quantity)
    if confirmed:
        return f"{q_str} {u}"
    return f"taqreeban {q_str} {u}"


def buyer_type_words(buyer_type: str) -> str:
    mapping = {
        "juice_shop": "juice shop",
        "restaurant": "restaurant",
        "bakery": "bakery",
        "charity": "charity organisation",
        "dairy_farm": "dairy farm",
        "other": "business",
    }
    return mapping.get(buyer_type, "business")


CITY_STYLES: dict[str, str] = {
    # How to address the buyer is one rule in the prompt ("aap", then "Bhai" or "Baji" once clear), not per city
    "karachi": "- Karachi market style: polite, friendly, business-minded.",
    "lahore": "- Lahore market style: warm and friendly, relaxed and confident bargaining.",
    "islamabad": "- Islamabad style: polite, formal and courteous market tone.",
}


# What the stock suits, by the kind of buyer called: the reason the Scout searched that kind (D46, D52), so it is true
# for any produce it is offered to
USE_FOR: dict[BuyerType, str] = {
    "juice_shop": "juice aur shake ke liye bilkul theek",
    "restaurant": "khana banane ke liye bilkul theek",
    "bakery": "bakery items ke liye bilkul theek",
    "charity": "bilkul khane ke qabil",
    "dairy_farm": "chaare ke liye bilkul theek",
    "other": "aap ke kaam ke liye bilkul theek",
}


def generate_pitch(view: AgentDealBrief, spoken: bool = False) -> str:
    """The pitch: what, how much and, with the spoken words (D77), the condition framed as a shopkeeper would ("bas
    thoray pakke huay aur daaghi hain, lekin juice aur shake ke liye bilkul theek"). For a sale the agent adds the
    price from verify_offer. An English description stays out of it (too long to say)."""
    q = quantity_words(view.quantity, view.quantity_unit, view.quantity_confirmed_by_staff, spoken)
    head = f"Humare paas {q} {view.item} hain"
    if not view.condition_spoken:
        if view.deal_type == "donation":
            return f"{head}, aap ke idaare ke liye bilkul free."
        return f"{head}, rate bohat munasib hai."

    if view.condition == FEED_ONLY:
        what = f"{head}, khane ke liye nahi, lekin {USE_FOR['dairy_farm']}"
    elif view.condition == "taaza":
        what = f"{head}, bilkul taaza"
    else:  # ripe, marked or wilted: said plainly, then why it still suits this buyer
        what = f"{head}, bas {view.condition} hain, lekin {USE_FOR[view.buyer.type]}"
    if view.deal_type == "donation":
        return f"{what}, aap ke idaare ke liye bilkul free."
    return f"{what}."


def quality_line(view: AgentDealBrief) -> str:
    """What the agent says to a quality doubt before sending the photo. Feed-only stock is never called fine inside."""
    if view.condition_spoken and view.condition == FEED_ONLY:
        return "Yeh maal chaare ke liye hai, khane ke liye nahi. Photo bhej deta hoon, khud dekh lein."
    if view.condition_spoken:
        return f"Bahar se {view.condition} hain, andar se maal theek hai. Photo bhej deta hoon, khud tasalli kar lein."
    condition_short = view.condition.split(",")[0].strip().lower()
    return (
        f"Bahar se thora {condition_short} hai, andar se maal theek hai. Photo bhej deta hoon, khud tasalli kar lein."
    )


def render_instruction(
    view: AgentDealBrief,
    *,
    mode: Literal["text", "voice"] = "text",
    agent_gender: Literal["male", "female"] = "male",
    city_style: str = "karachi",
    now: AwareDatetime | None = None,
) -> str:
    """Renders the negotiator system instruction prompt from prompt_template.j2."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
    )
    template = env.get_template("prompt_template.j2")

    current_time = now or view.pickup_deadline
    g = _GENDER_TABLE[agent_gender]

    # Pickup is "by the deadline" (D76), worded as the page and WhatsApp say it: "today, 4:30 PM". The window is
    # background, for a buyer who asks when they can come
    pickup_window_words = view.pickup_window
    pickup_deadline_words = pickup_by_words(view.pickup_deadline, current_time)
    now_words = time_words(current_time)

    market_rate_w = None
    if view.market_rate_per_unit is not None:
        market_rate_w = price_words(view.market_rate_per_unit, view.opening_price_unit)

    resolved_city_style = CITY_STYLES.get(city_style, city_style)
    spoken = mode == "voice"  # quantities as people say them; text mode keeps digits
    rendered = template.render(
        mart_name=view.mart.name,
        mart_location=view.mart.location,
        buyer_name=view.buyer.name,
        buyer_type_words=buyer_type_words(view.buyer.type),
        item=view.item,
        condition=view.condition,
        quality_line=quality_line(view),
        quantity_words=quantity_words(view.quantity, view.quantity_unit, view.quantity_confirmed_by_staff, spoken),
        # The number confirm_deal takes, when the words aren't digits ("saadhe 4 kilo" → 4.5)
        quantity_number=_digits(view.quantity)
        if spoken and spoken_amount(view.quantity) != _digits(view.quantity)
        else None,
        pickup_window_words=pickup_window_words,
        pickup_deadline_words=pickup_deadline_words,
        payment_terms=view.payment_terms,
        now_words=now_words,
        market_rate_words=market_rate_w,
        gender_words=f"{agent_gender} shopkeeper",
        g=g,
        city_style=resolved_city_style,
        mode=mode,
        deal_type=view.deal_type,
        condition_spoken=view.condition_spoken,
        pitch_line=generate_pitch(view, spoken),
        unit_words=unit_words(view.quantity_unit),
        unit_words_en=unit_words_en(view.quantity_unit),
    )
    return rendered
