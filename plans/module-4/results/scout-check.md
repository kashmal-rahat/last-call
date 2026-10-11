# Module 4 Scout Verification Check (`scout-check.md`)

**Date:** 2026-10-11 13:52:52 UTC
**Total Live Places API Requests:** 7 / 7 budget
**Strict Privacy Assurance:** Zero phone numbers are stored or printed in this document.

---

## Summary of Runs

| Run | Target / Step | Branch | Places Reqs | Raw Found | Final Buyers | Latency | Tokens (In/Out) | Fit Fallback |
|---|---|---|---|---|---|---|---|---|
| Run 1: Overripe Banana (Bulk Sale) @ Johar Town (Default) | bulk_sale (juice_shop, bakery) | Demo Mart Johar Town | 2 | 40 | 5 | 11887 ms | 2024 / 965 | False |
| Run 2: Overripe Spinach (Donate) @ Johar Town (Default) | donate (charity) | Demo Mart Johar Town | 1 | 15 | 5 | 6232 ms | 1179 / 386 | False |
| Run 3: Cattle-Safe Produce (Animal Feed) @ Johar Town (Default) | animal_feed (dairy_farm) | Demo Mart Johar Town | 1 | 20 | 5 | 5727 ms | 1261 / 458 | False |
| Run 4 (Contrast): Overripe Banana (Bulk Sale) @ Gulberg (Commercial) | bulk_sale (juice_shop, bakery) | Demo Mart Gulberg | 2 | 40 | 5 | 6729 ms | 2032 / 940 | False |
| Run 5 (Contrast): Cattle-Safe Produce (Animal Feed) @ Bahria Town (Suburban) | animal_feed (dairy_farm) | Demo Mart Bahria Town | 1 | 20 | 5 | 15089 ms | 1318 / 500 | False |

---

## Run 1: Overripe Banana (Bulk Sale) @ Johar Town (Default)

- **Branch:** `johar_town` (Demo Mart Johar Town)
- **Step:** `bulk_sale`
- **Buyer Types Searched:** `juice_shop, bakery`
- **Places Requests:** 2 | **Raw Places Returned:** 40
- **Latency:** 11887 ms | **Tokens:** 2024 in / 965 out
- **Skipped Counts:** `{'no_phone': 17, 'unlikely_fit': 6}`

### Top Ranked Buyers

| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |
|---|---|---|---|---|---|---|---|---|
| 1 | JuicePanda | juice_shop | 0.6 km | open now | **likely** | Local juice shop; ripe bananas are ideal for shakes | Juice shop · 0.6 km · open now | |
| 2 | Bismillah Fresh Juice & Dahi bhally \| Johar Town Lahore | juice_shop | 1.3 km | open now | **likely** | Local fresh juice and snack shop; regularly uses bananas for shakes | Juice shop · 1.3 km · open now | |
| 3 | Niazi Juice Corner | juice_shop | 1.3 km | open now | **likely** | Local juice corner; ripe bananas are ideal for milkshakes | Juice shop · 1.3 km · open now | |
| 4 | AH FRESHOP | juice_shop | 1.4 km | open now | **likely** | Local juice shop; very ripe bananas suit fresh shakes | Juice shop · 1.4 km · open now | |
| 5 | Juicella Shakes Juices & Buns | juice_shop | 1.5 km | open now | **likely** | Independent shake shop; high demand for bananas in milkshakes | Juice shop · 1.5 km · open now | |

### Screened Out / Unlikely Fits

| Business Name | Type | Distance | Fit Why | Sense check (user) |
|---|---|---|---|---|
| Cakes & Bakes | bakery | 0.6 km | Large bakery chain; operates through centralized procurement | |
| SweetCakeBloom \| Customized Cakes in Lahore | bakery | 0.7 km | Customized cake studio; unlikely to buy bulk fresh bananas | |
| Butt Sweets & Bakers | bakery | 0.8 km | Well-known sweets and bakery chain; uses central procurement | |
| Gourmet Foods - Air Line | bakery | 0.8 km | Major retail and bakery chain; relies on centralized supply chain | |
| Suleman Sweets & Bakers (JT) | bakery | 0.9 km | Established sweets chain; unlikely to buy ad-hoc produce locally | |
| GreenO Emporium Mall | juice_shop | 2.2 km | Mall chain kiosk; subject to corporate mall vendor policies | |

---

## Run 2: Overripe Spinach (Donate) @ Johar Town (Default)

- **Branch:** `johar_town` (Demo Mart Johar Town)
- **Step:** `donate`
- **Buyer Types Searched:** `charity`
- **Places Requests:** 1 | **Raw Places Returned:** 15
- **Latency:** 6232 ms | **Tokens:** 1179 in / 386 out
- **Skipped Counts:** `{'no_phone': 3, 'too_far': 3, 'unlikely_fit': 3}`

### Top Ranked Buyers

| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |
|---|---|---|---|---|---|---|---|---|
| 1 | Bahria Dastarkhwan | charity | 6.3 km | open now | **likely** | Well-known free charity meal dastarkhwan cooking daily meals | Charity · 6.3 km · open now | |
| 2 | Bahria Daster Khawan | charity | 7.7 km | open now | **likely** | Registered non-profit free food kitchen can use spinach today | Charity · 7.7 km · open now | |
| 3 | Allah Walay Trust (Dasterkhawn) | charity | 2.1 km | unknown | **likely** | Known charitable trust dastarkhwan serving free daily cooked meals | Charity · 2.1 km · hours unknown | |
| 4 | Maan G Ka Dasterkhwan | charity | 2.9 km | open now | **possible** | Could be a commercial eatery or community free food kitchen | Charity · 2.9 km · open now | |
| 5 | Bahria Dastarkhwan | charity | 7.5 km | open now | **possible** | Likely Bahria charity kitchen but categorized as health establishment | Charity · 7.5 km · open now | |

### Screened Out / Unlikely Fits

| Business Name | Type | Distance | Fit Why | Sense check (user) |
|---|---|---|---|---|
| Hyderabadi Dastarkhwan | charity | 1.5 km | Commercial restaurant named Dastarkhwan, not a charitable free kitchen | |
| Online Dastarkhwan | charity | 5.9 km | Listed as shipping service, not a local charity kitchen | |
| Home kitchen Ghar ka dastarkhwan | charity | 9.8 km | Commercial home kitchen restaurant, not a charitable food distributor | |

---

## Run 3: Cattle-Safe Produce (Animal Feed) @ Johar Town (Default)

- **Branch:** `johar_town` (Demo Mart Johar Town)
- **Step:** `animal_feed`
- **Buyer Types Searched:** `dairy_farm`
- **Places Requests:** 1 | **Raw Places Returned:** 20
- **Latency:** 5727 ms | **Tokens:** 1261 in / 458 out
- **Skipped Counts:** `{'no_phone': 5, 'too_far': 4, 'unlikely_fit': 2}`

### Top Ranked Buyers

| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |
|---|---|---|---|---|---|---|---|---|
| 1 | Butt Cattle Farm | dairy_farm | 6.9 km | open now | **likely** | Active cattle farm and ranch suitable for cattle feed | Dairy farm · 6.9 km · open now | |
| 2 | Shandar Pakistan Agri and Livestock Farms | dairy_farm | 2.5 km | unknown | **likely** | Livestock farm that can use spoiled carrots as animal feed | Dairy farm · 2.5 km · hours unknown | |
| 3 | Mehboob Awan Goat and Cattle Farm | dairy_farm | 6.6 km | unknown | **likely** | Local goat and cattle farm needing cheap animal feed | Dairy farm · 6.6 km · hours unknown | |
| 4 | Quality Meat Exports (Private) Limited | dairy_farm | 7.7 km | unknown | **possible** | Meat exporter and ranch; may raise animals on site | Dairy farm · 7.7 km · hours unknown | |
| 5 | Sab Cattle & Dairy Farm | dairy_farm | 9.3 km | unknown | **possible** | Dairy farm business, though listed primarily as a corporate office | Dairy farm · 9.3 km · hours unknown | |

### Screened Out / Unlikely Fits

| Business Name | Type | Distance | Fit Why | Sense check (user) |
|---|---|---|---|---|
| Happy Cattle Dairy Farm Head Office | dairy_farm | 4.5 km | Corporate head office rather than the actual cattle farm location | |
| Surgipharma (Exporters / Suppliers of Veterinary Equipments) | dairy_farm | 8.6 km | Veterinary equipment supplier, does not raise cattle | |

---

## Run 4 (Contrast): Overripe Banana (Bulk Sale) @ Gulberg (Commercial)

- **Branch:** `gulberg` (Demo Mart Gulberg)
- **Step:** `bulk_sale`
- **Buyer Types Searched:** `juice_shop, bakery`
- **Places Requests:** 2 | **Raw Places Returned:** 40
- **Latency:** 6729 ms | **Tokens:** 2032 in / 940 out
- **Skipped Counts:** `{'no_phone': 18, 'unlikely_fit': 8}`

### Top Ranked Buyers

| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |
|---|---|---|---|---|---|---|---|---|
| 1 | Bholli Juice Corner بھولی جوس کارنر | juice_shop | 0.4 km | open now | **likely** | Local juice corner; ripe bananas are staple ingredients for milkshakes. | Juice shop · 0.4 km · open now | |
| 2 | OMG Juices & More | juice_shop | 0.5 km | open now | **likely** | Local juice bar; ripe bananas are suitable for smoothies and shakes. | Juice shop · 0.5 km · open now | |
| 3 | Fine Kulfi & Fresh Juice Corner | juice_shop | 0.7 km | open now | **likely** | Local kulfi and juice stall; can use ripe bananas in shakes. | Juice shop · 0.7 km · open now | |
| 4 | Juice Corner | juice_shop | 0.8 km | open now | **likely** | Local juice corner; ideal buyer for bulk ripe milkshake bananas. | Juice shop · 0.8 km · open now | |
| 5 | Markhor Juice Point | juice_shop | 0.0 km | unknown | **likely** | Local juice shop; ripe bananas are ideal for banana milkshakes. | Juice shop · 0.0 km · hours unknown | |

### Screened Out / Unlikely Fits

| Business Name | Type | Distance | Fit Why | Sense check (user) |
|---|---|---|---|---|
| SUPER HOT POTATOES | bakery | 0.2 km | Name indicates potato fast food; unlikely to buy bananas. | |
| Shezan Bakers & Confectioners | bakery | 0.2 km | Major bakery chain; relies on centralized procurement. | |
| Liberty Garato Jalebi | bakery | 0.3 km | Traditional jalebi sweet shop; does not use fresh bananas. | |
| Jalal Sons - Hussain Chowk | bakery | 0.4 km | Large retail supermarket chain; uses corporate central distribution. | |
| Khalifa Bakers Badam Nankhatai Home Delivery service | bakery | 0.4 km | Specializes in traditional nankhatai biscuits; does not use bananas. | |
| Khushi Sweets - MM Alam Road | bakery | 0.5 km | Traditional mithai shop; does not use bulk fresh bananas. | |
| Layers Bakeshop - MM Alam | bakery | 0.5 km | Major national bakery chain; uses centralized ingredient purchasing. | |
| Pie In The Sky MM Alam Road | bakery | 0.5 km | Well-known bakery chain; uses central commercial supply channels. | |

---

## Run 5 (Contrast): Cattle-Safe Produce (Animal Feed) @ Bahria Town (Suburban)

- **Branch:** `bahria_town` (Demo Mart Bahria Town)
- **Step:** `animal_feed`
- **Buyer Types Searched:** `dairy_farm`
- **Places Requests:** 1 | **Raw Places Returned:** 20
- **Latency:** 15089 ms | **Tokens:** 1318 in / 500 out
- **Skipped Counts:** `{'no_phone': 3, 'too_far': 5, 'unlikely_fit': 4}`

### Top Ranked Buyers

| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |
|---|---|---|---|---|---|---|---|---|
| 1 | Joan Dairy & Cattle Farm | dairy_farm | 2.5 km | open now | **likely** | Local dairy and cattle farm can use carrots for animal feed | Dairy farm · 2.5 km · open now | |
| 2 | WARSA DAIRY FARM | dairy_farm | 3.4 km | open now | **likely** | Local dairy farm suited to take carrots for cattle feed | Dairy farm · 3.4 km · open now | |
| 3 | MP Dairies | dairy_farm | 5.1 km | open now | **likely** | Local dairy farm can use surplus carrots for cattle feed | Dairy farm · 5.1 km · open now | |
| 4 | Ch Sharif Dairy Farm | dairy_farm | 5.7 km | unknown | **likely** | Independent dairy farm likely accepts carrots as cattle feed | Dairy farm · 5.7 km · hours unknown | |
| 5 | Kamboh Cattle Farm | dairy_farm | 6.1 km | unknown | **likely** | Local cattle farm suited for buying cheap cattle feed | Dairy farm · 6.1 km · hours unknown | |

### Screened Out / Unlikely Fits

| Business Name | Type | Distance | Fit Why | Sense check (user) |
|---|---|---|---|---|
| Cattlekit | dairy_farm | 4.1 km | Appears to be an equipment supplier, not an active farm | |
| Happy Cattle Dairy Farm Head Office | dairy_farm | 8.1 km | Corporate head office rather than the actual cattle farm | |
| Melken Dairy (Farm Fresh Milk & Dairy products) | dairy_farm | 9.0 km | Retail milk and dairy products shop, not a farm | |
| Organic Lahore | dairy_farm | 9.4 km | Retail food store selling organic goods, not a livestock farm | |

---

## Branch Contrast Analysis

### Bulk Sale Contrast: Johar Town (Suburban Residential) vs Gulberg (Dense Commercial)

- **Place ID Overlap (M3):** 0 overlapping places out of 5 (Johar Town) and 5 (Gulberg).
- **Johar Town Average Top-5 Distance:** 1.22 km
- **Gulberg Average Top-5 Distance:** 0.48 km

| Aspect | Johar Town (`johar_town`) | Gulberg (`gulberg`) |
|---|---|---|
| Raw Places Found | 40 | 40 |
| Qualified Buyers | 5 | 5 |
| Top 1 Buyer | JuicePanda (0.6 km) | Bholli Juice Corner بھولی جوس کارنر (0.4 km) |
| Top 2 Buyer | Bismillah Fresh Juice (1.3 km) | OMG Juices & More (0.5 km) |
| Skipped Breakdown | `{'no_phone': 17, 'unlikely_fit': 6}` | `{'no_phone': 18, 'unlikely_fit': 8}` |

### Animal Feed Contrast: Johar Town vs Bahria Town (Peri-Urban / Cattle Area)

- **Place ID Overlap (M3):** 0 overlapping places.
- **Johar Town Qualified Dairy Farms:** 5
- **Bahria Town Qualified Dairy Farms:** 5

| Aspect | Johar Town (`johar_town`) | Bahria Town (`bahria_town`) |
|---|---|---|
| Raw Results | 20 | 20 |
| Qualified Buyers | 5 | 5 |
| Top-ranked buyer | Butt Cattle Farm (6.9 km) | Joan Dairy & Cattle Farm (2.5 km) |
| Skipped Breakdown | `{'no_phone': 5, 'too_far': 4, 'unlikely_fit': 2}` | `{'no_phone': 3, 'too_far': 5, 'unlikely_fit': 4}` |
