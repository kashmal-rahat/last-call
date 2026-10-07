"""Negotiator prompt rendering and natural language formatting helpers."""

from pathlib import Path
from typing import Literal
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import AwareDatetime

from lastcall_shared.models import AgentDealBrief

PROMPT_VERSION = "1.2"
TEMPLATE_DIR = Path(__file__).parent

_GENDER_TABLE = {
    "male": {
        "deta": "deta",
        "raha": "raha",
        "tha": "tha",
        "assistant": "AI assistant",
    },
    "female": {
        "deta": "deti",
        "raha": "rahi",
        "tha": "thi",
        "assistant": "AI assistant",
    },
}

_NUM_TO_WORDS: dict[int, str] = {
    0: "sifar",
    10: "das", 15: "pandrah", 20: "bees", 25: "pachis", 30: "tees",
    40: "chalis", 50: "pachaas", 60: "saath", 70: "sattar", 75: "pachhattar",
    80: "assi", 85: "pachasi", 88: "athasi", 90: "nabbe", 95: "pachaanve",
    100: "sau", 110: "aik sau das", 120: "aik sau bees", 125: "sawa sau",
    130: "aik sau tees", 140: "aik sau chalis", 150: "dedh sau",
    160: "aik sau saath", 170: "aik sau sattar", 175: "paune do sau",
    180: "aik sau assi", 188: "aik sau athasi", 190: "aik sau nabbe",
    200: "do sau", 220: "do sau bees", 225: "sawa do sau", 230: "do sau tees",
    250: "dhai sau", 275: "paune teen sau", 300: "teen sau",
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


def price_words(amount: int, unit: str) -> str:
    w = number_to_words(amount)
    u = unit_words(unit)
    return f"{w} rupay per {u}"


def quantity_words(quantity: float, unit: str, confirmed: bool = True) -> str:
    u = unit_words(unit)
    q_str = f"{int(quantity)}" if quantity.is_integer() else f"{quantity}"
    if confirmed:
        return f"{q_str} {u}"
    return f"taqreeban {q_str} {u}"


def time_words(dt: AwareDatetime) -> str:
    hour = dt.strftime("%I").lstrip("0")
    minute = dt.strftime("%M")
    ampm = dt.strftime("%p")
    time_str = f"{hour}:{minute} {ampm}" if minute != "00" else f"{hour} {ampm}"
    return f"{dt.strftime('%d %B')}, {time_str}"


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


def generate_pitch(view: AgentDealBrief) -> str:
    u = unit_words(view.quantity_unit)
    q = quantity_words(view.quantity, view.quantity_unit, view.quantity_confirmed_by_staff)
    if view.deal_type == "donation":
        return f"Humare paas {q} {view.item} hain jo abhi theek hain, aap ke shelter ke liye bilkul free dene ko tayyar hain."
    return f"Humare paas {q} taaza {view.item} hain, condition {view.condition} hai, aur rate bohat munasib hai."


def render_instruction(
    view: AgentDealBrief,
    *,
    mode: Literal["text", "voice"] = "text",
    agent_gender: Literal["male", "female"] = "male",
    city_style: str = "- Karachi style: friendly and polite.",
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

    pickup_window_words = f"pickup between {view.pickup_window}"
    pickup_deadline_words = time_words(view.pickup_deadline)
    now_words = time_words(current_time)

    market_rate_w = None
    if view.market_rate_per_unit is not None:
        market_rate_w = price_words(view.market_rate_per_unit, view.opening_price_unit)

    rendered = template.render(
        mart_name=view.mart.name,
        mart_location=view.mart.location,
        buyer_name=view.buyer.name,
        buyer_type_words=buyer_type_words(view.buyer.type),
        item=view.item,
        condition=view.condition,
        quantity_words=quantity_words(view.quantity, view.quantity_unit, view.quantity_confirmed_by_staff),
        pickup_window_words=pickup_window_words,
        pickup_deadline_words=pickup_deadline_words,
        payment_terms=view.payment_terms,
        now_words=now_words,
        market_rate_words=market_rate_w,
        gender_words=f"{agent_gender} shopkeeper",
        g=g,
        city_style=city_style,
        buyer_honorific="Bhai",
        mode=mode,
        deal_type=view.deal_type,
        pitch_line=generate_pitch(view),
        unit_words=unit_words(view.quantity_unit),
    )
    return rendered
