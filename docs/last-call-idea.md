# 🥬 Last Call — Idea

> 🏆 AI Builder Cup 2026 · Theme: **Retail & Commerce**

## Problem

Marts in Pakistan and across South Asia lose money every day on fruit and vegetables they can't sell. Most of it isn't rotten, just too ripe for shelf customers, so it's written off and thrown away. Meanwhile juice shops, restaurants, bakeries, charities and dairy farms would happily take it.

Existing solutions are mostly apps and online marketplaces, but the people most likely to buy surplus produce rarely check them; they do business over the phone. So the value is lost, because no one at the mart has time to notice the produce in time, work out who would want it, and phone around to sell it.

## Solution

An AI system that watches a mart's fresh produce, decides the best way to recover each item's value before it goes to waste, and does the selling itself by phoning nearby buyers and negotiating in the local language, within rules the manager sets once.

## How it works

1. **Set the rules (once):** the manager decides how far the AI can go on its own, such as the maximum discount it can apply, the lowest acceptable price for each type of item, when calls can be made, and which actions need approval.
2. **See:** a camera on the shelf takes a picture a few times a day (for example morning, midday and late afternoon) and sends it for checking. One picture can show several items.
3. **Judge:** AI identifies each item and how fresh it is, and flags anything it isn't sure about for a staff check.
4. **Decide:** for each item, AI picks the best step on the ladder and explains why. It moves down only when the step above stops working:
    1. Keep at full price
    2. Discount in store
    3. Sell in bulk to businesses (juice shops, restaurants, bakeries)
    4. Donate to charities and food banks
    5. Sell or give as animal feed to dairy and cattle farms
    6. Compost

    Produce goes to animal feed only when it's safe for animals; mouldy or harmful items go to compost.
5. **Find buyers:** for bulk sale, donation or animal feed, AI works out which kinds of buyers would want this item in its current condition and finds relevant ones nearby on Google.
6. **Negotiate (the hero):** AI calls them in the local language (Urdu in our demo) and adjusts the pitch to the buyer: fresh-enough fruit for a juice shop, a donation for a charity, cheap daily feed for a dairy farm. It negotiates without going below the manager's price, handles objections and counter-offers, and confirms price, quantity and pickup time, with the buyer collecting from the mart. A confirmation can follow on WhatsApp.
7. **Ask only when needed:** AI acts on its own within the manager's rules and asks for approval only for exceptions, such as sending produce to compost or checking items it isn't sure about. The manager can also choose to review the buyer list before calls go out.
8. **Report and learn:** the manager gets one summary at the end of the day showing what was sold, donated, fed to animals or composted, and how much money was recovered. The system remembers which buyers said yes, at what price, and which discounts worked, so every decision and call gets better.

## The four parts

| Part | Role |
|---|---|
| Freshness Inspector | Judges each item in the picture |
| Ladder | Decides the step and price for each item: Gemini writes a profile for each produce once (how long it lasts, who can use it), and code makes the decision consistently |
| Scout Agent | Finds relevant nearby buyers on Google Maps, has Gemini screen out unlikely ones, and ranks them in code with a reason each |
| **Negotiator Agent** | Makes the call and closes the deal (the hero) |

## What makes it different

Existing tools, from AI markdown systems to surplus-food apps, either recommend what staff should do or sell to consumers through an app. None of them find and close deals with offline business buyers, who trade by phone. This one goes all the way to finding a buyer and closing a deal by voice, the way local businesses actually trade. It follows the food-waste hierarchy (people first, then animals, then compost), so almost nothing ends up with zero value. It works for any fresh produce, and the manager stays in control without having to approve every step.

## Impact

- **For the mart:** revenue recovered from stock that would otherwise be written off.
- **For the community:** less food in landfill, more food reaching charities, and cheap feed for local farms.

## One-line pitch

> 💬 "Marts throw away produce they could have sold. Our AI notices it in time, finds who'll buy it, and calls them in their own language to close the deal."

- [Last Call — Module Plan](last-call-module-plan.md)
- [Last Call — Architecture](last-call-architecture.md)
