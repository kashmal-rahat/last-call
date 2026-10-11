# Places API Probe Report (Milestone 4A Step 4)
Generated: 2026-10-11 12:40:14 UTC

## Summary of Findings

| # | Branch | Buyer Type | Query | Rank Pref | Raw Count | With Phone | Open Now (T/F/?) | Usable (≤10km+phone) | Latency | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Demo Mart Johar Town | `juice_shop` | `juice shop` | DISTANCE | 20 | 17 | 19/0/1 | 14 | 1695ms | OK |
| 2 | Demo Mart Johar Town | `restaurant` | `restaurant` | DISTANCE | 20 | 20 | 20/0/0 | 20 | 615ms | OK |
| 3 | Demo Mart Johar Town | `bakery` | `bakery` | DISTANCE | 20 | 15 | 19/1/0 | 15 | 561ms | OK |
| 4 | Demo Mart Johar Town | `charity` | `charity food bank welfare dastarkhwan` | RELEVANCE | 4 | 4 | 2/0/2 | 3 | 569ms | OK |
| 5 | Demo Mart Johar Town | `dairy_farm` | `dairy farm cattle farm` | RELEVANCE | 20 | 14 | 8/6/6 | 11 | 619ms | OK |
| 6 | Demo Mart Bahria Town | `juice_shop` | `juice shop` | DISTANCE | 20 | 15 | 17/0/3 | 15 | 628ms | OK |
| 7 | Demo Mart Gulberg | `juice_shop` | `juice shop` | DISTANCE | 20 | 17 | 20/0/0 | 15 | 580ms | OK |

## SKU & Field Mask Verification
- **Field Mask**: `places.id,places.displayName,places.primaryType,places.types,places.location,places.businessStatus,places.internationalPhoneNumber,places.currentOpeningHours.openNow,places.googleMapsUri`
- **Field Mask Status**: Accepted by Places API (New) without rejection.
- **Atmosphere Fields**: Zero Atmosphere fields requested (strictly Enterprise SKU).
- **Rank Preferences**: `DISTANCE` accepted for typed queries (`juice_shop`, `restaurant`, `bakery`); `RELEVANCE` accepted for free-text queries (`charity`, `dairy_farm`).

## Detailed Candidate Lists (Top 10 Nearest per Probe)

### Probe 1: juice_shop (Demo Mart Johar Town)
- **Query**: `juice shop`
- **Business Status Counts**: {"OPERATIONAL": 20}
- **Usable Count (Operational + Phone + ≤10km)**: 14

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Bismillah Fresh Juice & Dahi bhally \| Johar Town Lahore | `juice_shop` | 1.32 km | Yes | Yes | OPERATIONAL | Yes |
| 2 | AH FRESHOP | `juice_shop` | 1.4 km | Yes | Yes | OPERATIONAL | Yes |
| 3 | AB Juice Corner | `juice_shop` | 1.57 km | Yes | Yes | OPERATIONAL | Yes |
| 4 | Tayyab Juice | `juice_shop` | 1.93 km | Yes | Yes | OPERATIONAL | Yes |
| 5 | Juices Island | `juice_shop` | 2.19 km | Yes | Yes | OPERATIONAL | Yes |
| 6 | Al razzaq juice corner and ice bar | `juice_shop` | 2.81 km | Yes | Yes | OPERATIONAL | Yes |
| 7 | Haji Juice Shop | `juice_shop` | 3.67 km | Yes | Yes | OPERATIONAL | Yes |
| 8 | Haji Juice Corner | `juice_shop` | 3.81 km | Yes | Yes | OPERATIONAL | Yes |
| 9 | Sheikh Juice Corner | `juice_shop` | 4.16 km | Yes | Yes | OPERATIONAL | Yes |
| 10 | Lovely Juice Corner | `juice_shop` | 4.51 km | Yes | Yes | OPERATIONAL | Yes |

### Probe 2: restaurant (Demo Mart Johar Town)
- **Query**: `restaurant`
- **Business Status Counts**: {"OPERATIONAL": 20}
- **Usable Count (Operational + Phone + ≤10km)**: 20

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Bait Al Mandi Restaurant | `middle_eastern_restaurant` | 0.34 km | Yes | Yes | OPERATIONAL | Yes |
| 2 | Marfa Cafe | `restaurant` | 0.4 km | Yes | Yes | OPERATIONAL | Yes |
| 3 | Maalga Restaurant | `afghani_restaurant` | 0.44 km | Yes | Yes | OPERATIONAL | Yes |
| 4 | Karachi Red Rock Family Restaurant | `restaurant` | 2.11 km | Yes | Yes | OPERATIONAL | Yes |
| 5 | Al-Madina Family Restaurant | `pakistani_restaurant` | 2.77 km | Yes | Yes | OPERATIONAL | Yes |
| 6 | Pak Punjab Restaurant | `restaurant` | 2.93 km | Yes | Yes | OPERATIONAL | Yes |
| 7 | Buqayvia Restaurant | `restaurant` | 3.11 km | Yes | Yes | OPERATIONAL | Yes |
| 8 | AlKhan | `family_restaurant` | 3.45 km | Yes | Yes | OPERATIONAL | Yes |
| 9 | At Food | `restaurant` | 3.51 km | Yes | Yes | OPERATIONAL | Yes |
| 10 | Namak Nomadic Cuisine | `afghani_restaurant` | 4.29 km | Yes | Yes | OPERATIONAL | Yes |

### Probe 3: bakery (Demo Mart Johar Town)
- **Query**: `bakery`
- **Business Status Counts**: {"OPERATIONAL": 20}
- **Usable Count (Operational + Phone + ≤10km)**: 15

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Bundu khan sweet bakery pia Society | `bakery` | 0.98 km | Yes | Yes | OPERATIONAL | Yes |
| 2 | Cakes & Bakes | `bakery` | 1.17 km | Yes | Yes | OPERATIONAL | Yes |
| 3 | Divine Bakers | `bakery` | 1.51 km | Yes | Yes | OPERATIONAL | Yes |
| 4 | Cakes & Bakes | `bakery` | 2.51 km | Yes | Yes | OPERATIONAL | Yes |
| 5 | Bevro Bakery Cafe | `bakery` | 2.58 km | Yes | Yes | OPERATIONAL | Yes |
| 6 | Cakes & Bakes | `bakery` | 2.72 km | Yes | Yes | OPERATIONAL | Yes |
| 7 | Al ameer bakery | `bakery` | 2.88 km | Yes | Yes | OPERATIONAL | Yes |
| 8 | Slice Bakery By Bushra | `bakery` | 3.09 km | Yes | Yes | OPERATIONAL | Yes |
| 9 | Cakes & Bakes | `bakery` | 3.39 km | Yes | Yes | OPERATIONAL | Yes |
| 10 | Gourmet Bakery - Valencia Town | `bakery` | 3.61 km | Yes | Yes | OPERATIONAL | Yes |

### Probe 4: charity (Demo Mart Johar Town)
- **Query**: `charity food bank welfare dastarkhwan`
- **Business Status Counts**: {"OPERATIONAL": 4}
- **Usable Count (Operational + Phone + ≤10km)**: 3

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Allah Walay Trust (Dasterkhawn) | `restaurant` | 2.07 km | Yes | Unknown | OPERATIONAL | Yes |
| 2 | Zainab dastarkhan | `association_or_organization` | 3.21 km | Yes | Unknown | OPERATIONAL | Yes |
| 3 | Cravins | `association_or_organization` | 4.53 km | Yes | Yes | OPERATIONAL | Yes |
| 4 | Saylani Welfare Trust Charity | `association_or_organization` | 10.17 km | Yes | Yes | OPERATIONAL | No |

### Probe 5: dairy_farm (Demo Mart Johar Town)
- **Query**: `dairy farm cattle farm`
- **Business Status Counts**: {"OPERATIONAL": 20}
- **Usable Count (Operational + Phone + ≤10km)**: 11

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Shandar Pakistan Agri and Livestock Farms | `service` | 2.49 km | Yes | Unknown | OPERATIONAL | Yes |
| 2 | Happy Cattle Dairy Farm Head Office | `corporate_office` | 4.5 km | Yes | No | OPERATIONAL | Yes |
| 3 | 7 Stars Cattle & Dairy Farm House | `ranch` | 4.58 km | No | Yes | OPERATIONAL | No |
| 4 | Cream Dairy Cattle Farm | `ranch` | 4.96 km | No | Yes | OPERATIONAL | No |
| 5 | House of Cattle | `ranch` | 5.08 km | Yes | Unknown | OPERATIONAL | Yes |
| 6 | Arain Dairies | `ranch` | 5.54 km | No | Yes | OPERATIONAL | No |
| 7 | SK Livestock LLP | `ranch` | 5.9 km | Yes | No | OPERATIONAL | Yes |
| 8 | Mid East Farms | `farm` | 5.93 km | Yes | Yes | OPERATIONAL | Yes |
| 9 | Al-Badar Dairy & Farmhouse | `ranch` | 6.17 km | Yes | No | OPERATIONAL | Yes |
| 10 | IJ&SONS | `ranch` | 6.33 km | Yes | No | OPERATIONAL | Yes |

### Probe 6: juice_shop (Demo Mart Bahria Town)
- **Query**: `juice shop`
- **Business Status Counts**: {"OPERATIONAL": 20}
- **Usable Count (Operational + Phone + ≤10km)**: 15

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Iceland & Dry Fruits | `juice_shop` | 0.25 km | Yes | Yes | OPERATIONAL | Yes |
| 2 | Juice Hub | `juice_shop` | 1.24 km | Yes | Yes | OPERATIONAL | Yes |
| 3 | AMIR JUICE CORNER Bahria Town | `juice_shop` | 2.09 km | Yes | Unknown | OPERATIONAL | Yes |
| 4 | Juice House | `juice_shop` | 3.95 km | Yes | Yes | OPERATIONAL | Yes |
| 5 | Tayyab Juice | `juice_shop` | 4.12 km | Yes | Yes | OPERATIONAL | Yes |
| 6 | Ice Land | `juice_shop` | 4.71 km | Yes | Yes | OPERATIONAL | Yes |
| 7 | AH FRESHOP | `juice_shop` | 4.87 km | Yes | Yes | OPERATIONAL | Yes |
| 8 | Bismillah Juice Corner | `juice_shop` | 5.08 km | No | Yes | OPERATIONAL | No |
| 9 | Ice Land | `juice_shop` | 5.28 km | Yes | Yes | OPERATIONAL | Yes |
| 10 | TAYYAB JUICE | `juice_shop` | 5.37 km | Yes | Yes | OPERATIONAL | Yes |

### Probe 7: juice_shop (Demo Mart Gulberg)
- **Query**: `juice shop`
- **Business Status Counts**: {"OPERATIONAL": 20}
- **Usable Count (Operational + Phone + ≤10km)**: 15

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |
|---|---|---|---|---|---|---|---|
| 1 | Maulvi Juice Corner | `juice_shop` | 4.42 km | No | Yes | OPERATIONAL | No |
| 2 | Nirala Juice & Milk Shake | `juice_shop` | 4.47 km | Yes | Yes | OPERATIONAL | Yes |
| 3 | Lovely Juice Corner | `juice_shop` | 5.31 km | Yes | Yes | OPERATIONAL | Yes |
| 4 | Juice Junction | `juice_shop` | 5.39 km | Yes | Yes | OPERATIONAL | Yes |
| 5 | Hafiz Juice | `juice_shop` | 5.61 km | Yes | Yes | OPERATIONAL | Yes |
| 6 | Pehlwan Fruits,Dry Fruits & juice corner | `juice_shop` | 5.65 km | No | Yes | OPERATIONAL | No |
| 7 | Shahbaz Juice Corner | `juice_shop` | 6.26 km | Yes | Yes | OPERATIONAL | Yes |
| 8 | Haji Juice Corner | `juice_shop` | 6.77 km | Yes | Yes | OPERATIONAL | Yes |
| 9 | Life Line Juice Corner | `juice_shop` | 7.24 km | Yes | Yes | OPERATIONAL | Yes |
| 10 | Hafiz Fruit & Juice Corner | `juice_shop` | 7.67 km | Yes | Yes | OPERATIONAL | Yes |


---

## P1 & P2 Diagnostic Results (2026-10-11 12:56:51 UTC)

### P1: Charity Query Variants (Johar Town, 10 km radius)

| Query | Raw Count | With Phone | Open Now (T/F/?) | Usable (≤10km+phone) | Latency | Status |
|---|---|---|---|---|---|---|
| `welfare trust dastarkhwan` (A) | 2 | 2 | 1/0/1 | **1** | 1797ms | OK |
| `dastarkhwan` (B) | 17 | 13 | 10/4/3 | **9** | 578ms | OK |

#### P1-A Top Candidates (`welfare trust dastarkhwan`):

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Usable |
|---|---|---|---|---|---|---|
| 1 | Allah Walay Trust (Dasterkhawn) | `restaurant` | 2.07 km | Yes | Unknown | Yes |
| 2 | Saylani Welfare Trust Charity | `association_or_organization` | 10.17 km | Yes | Yes | No |

#### P1-B Top Candidates (`dastarkhwan`):

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Usable |
|---|---|---|---|---|---|---|
| 1 | Hyderabadi Dastarkhwan | `pakistani_restaurant` | 1.49 km | Yes | Yes | Yes |
| 2 | Allah Walay Trust (Dasterkhawn) | `restaurant` | 2.07 km | Yes | Unknown | Yes |
| 3 | Maan G Ka Dasterkhwan | `restaurant` | 2.89 km | Yes | Yes | Yes |
| 4 | Thokar Dastarkhwan | `restaurant` | 3.31 km | No | Yes | No |
| 5 | Bahria Dastarkhawan | `food` | 3.38 km | No | No | No |
| 6 | Al Khidmat Dastarkhwan الخدمت دسترخواں منصورہ | `asian_restaurant` | 5.11 km | No | Unknown | No |
| 7 | Online Dastarkhwan | `shipping_service` | 5.88 km | Yes | No | Yes |
| 8 | Bahria Dastarkhwan | `restaurant` | 6.35 km | Yes | Yes | Yes |
| 9 | MUSA CARE FOUNDATION DASTARKHWAN | `association_or_organization` | 7.19 km | Yes | No | Yes |
| 10 | Bahria Dastarkhwan | `health` | 7.52 km | Yes | Yes | Yes |

### P2: Gulberg Nearby Search Diagnostic (`searchNearby`, 5000m radius)
- **Status Code**: 200
- **Latency**: 487ms
- **Raw Results Count**: 20
- **Text Search Nearest Baseline**: 4.42 km (`Maulvi Juice Corner`)
- **Nearby Search Nearest Distance**: 0.04 km

| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Usable |
|---|---|---|---|---|---|---|
| 1 | Siddique Juice Corner | `juice_shop` | 0.04 km | No | Unknown | No |
| 2 | Sajjan Allah Juice Corner | `juice_shop` | 0.05 km | Yes | Unknown | Yes |
| 3 | Markhor Juice Point | `juice_shop` | 0.05 km | Yes | Unknown | Yes |
| 4 | Manzoor Brothers Fresh Juice & Dry Fruit | `juice_shop` | 0.18 km | No | No | No |
| 5 | Liberty Parking Juice Corner | `juice_shop` | 0.19 km | No | No | No |
| 6 | Malee Juice Stand مالی جوس سٹینڈ | `juice_shop` | 0.19 km | No | Yes | No |
| 7 | Hafiz juice corner | `juice_shop` | 0.23 km | No | No | No |
| 8 | 786 Fruit Chat & Juice Corner | `juice_shop` | 0.3 km | No | Yes | No |
| 9 | Taqwaa Juice Corner (Saraiki's) | `juice_shop` | 0.31 km | No | Unknown | No |
| 10 | Bholli Juice Corner بھولی جوس کارنر | `juice_shop` | 0.44 km | Yes | Yes | Yes |
