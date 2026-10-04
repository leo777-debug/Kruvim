"""Deterministic display names and handles so agents read like people in the timeline."""
from __future__ import annotations

ARAB_M = ["Ahmed", "Mohammed", "Omar", "Khalid", "Yousef", "Hamad", "Saeed", "Faisal", "Abdullah", "Majid", "Rashid", "Tariq",
          "Saud", "Fahad", "Nasser", "Ali", "Hassan", "Ibrahim", "Karim", "Ziad", "Sultan", "Mansour", "Bader", "Hamza"]
ARAB_F = ["Fatima", "Mariam", "Aisha", "Noura", "Sara", "Hessa", "Latifa", "Reem", "Dana", "Lulwa", "Amna", "Shamma",
          "Layla", "Huda", "Yasmin", "Rania", "Salma", "Nada", "Dalia", "Mona", "Jana", "Lina", "Hind", "Maha"]
SOUTH_ASIAN_M = ["Rahul", "Arjun", "Imran", "Vikram", "Faizan", "Rohit", "Anil", "Sanjay", "Ravi", "Zain", "Kiran", "Aditya"]
SOUTH_ASIAN_F = ["Priya", "Ayesha", "Ananya", "Sana", "Neha", "Pooja", "Zara", "Meera", "Divya", "Hina", "Kavya", "Riya"]
FILIPINO_M = ["Mark", "John Paul", "Jericho", "Paolo", "Miguel", "Carlo"]
FILIPINO_F = ["Maria", "Angelica", "Kristine", "Joy", "Camille", "Bea"]
WEST_M = ["James", "Michael", "Daniel", "Chris", "Tom", "Ryan", "Jake", "Ben", "Luke", "Sam", "Oliver", "Ethan"]
WEST_F = ["Emma", "Olivia", "Sophie", "Hannah", "Chloe", "Grace", "Emily", "Megan", "Lucy", "Ava", "Mia", "Ella"]
MAGHREB_M = ["Youssef", "Mehdi", "Hamza", "Amine", "Ayoub", "Othmane", "Reda", "Anas", "Ilyas", "Soufiane"]
MAGHREB_F = ["Salma", "Imane", "Kawtar", "Hiba", "Meryem", "Oumaima", "Ghita", "Sanaa", "Nisrine", "Houda"]
US_M = WEST_M + ["Carlos", "Luis", "Marcus", "Andre", "Kevin", "Brandon"]
US_F = WEST_F + ["Sofia", "Isabella", "Jasmine", "Aaliyah", "Madison", "Kayla"]
LAST_INITIALS = "ABDEFHJKLMNRSTZ"

CITY_TAG = {"AE": "dxb", "SA": "ruh", "EG": "cai", "JO": "amm", "MA": "casa", "US": "nyc", "GB": "ldn", "IN": "bom"}


def _pick(lst: list[str], h: int) -> str:
    return lst[h % len(lst)]


def name_for(idx: int, region: str, origin: str, male: bool) -> tuple[str, str]:
    h = (idx * 2654435761) & 0xFFFFFFFF
    o = origin.lower()
    if any(group in o for group in ("south asian", "indian", "pakistani", "bangladeshi")) or region == "IN":
        pool = SOUTH_ASIAN_M if male else SOUTH_ASIAN_F
    elif "filipino" in o:
        pool = FILIPINO_M if male else FILIPINO_F
    elif "western" in o or region == "GB":
        pool = WEST_M if male else WEST_F
    elif region == "US":
        pool = US_M if male else US_F
    elif region == "MA":
        pool = MAGHREB_M if male else MAGHREB_F
    else:
        pool = ARAB_M if male else ARAB_F
    first = _pick(pool, h)
    last = LAST_INITIALS[(h >> 8) % len(LAST_INITIALS)]
    name = f"{first} {last}."
    handle = f"{first.split()[0].lower()}_{CITY_TAG.get(region, region.lower())}{(h >> 12) % 97}"
    return name, handle
