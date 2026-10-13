"""Seeds the Firestore database with the demo mart document (Milestone 2B Step 9)."""

import asyncio
from datetime import datetime, timezone

from google.cloud import firestore

from lastcall_shared.config import get_settings


async def seed_demo():
    settings = get_settings()
    client = firestore.AsyncClient(project=settings.GOOGLE_CLOUD_PROJECT, database="(default)")
    mart_ref = client.collection("marts").document("demo_mart")

    doc = await mart_ref.get()
    if doc.exists:
        print("marts/demo_mart already exists. Ensuring fields are up to date...")

    demo_mart_data = {
        "mart_id": "demo_mart",
        "name": "Fresh Mart Clifton",
        "location": "Clifton Block 2, Karachi",
        "city": "Karachi",
        "city_style": "- Karachi market style: polite, friendly, business-minded. Call the buyer 'Bhai'.",
        "calling_hours": {
            "start": "09:00:00",
            "end": "21:00:00",
            "timezone": "Asia/Karachi",
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await mart_ref.set(demo_mart_data, merge=True)
    print("Successfully seeded marts/demo_mart in Firestore.")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed_demo())
