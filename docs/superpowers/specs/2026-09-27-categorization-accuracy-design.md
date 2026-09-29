# Design Spec: Categorization Accuracy Improvements

**Date:** 2026-09-27
**Status:** Draft
**Branch:** TBD (off `feat/categorization-redesign` or `main`)

## Problem

Laya accepted only 1 out of ~86 fresh transactions. Of the 57 manual corrections needed:
- ~28 were vacation transactions miscategorized by type (a McDonald's in Utah tagged as Restaurants instead of Vacation)
- The rest were confusion between ambiguous categories (Car/Gas vs Utilities/Gas, restaurants as Car, etc.)

Root causes:
1. Auto-generated category descriptions (`"gas (car)"`, `"family (restaurants)"`) give laya no useful signal to differentiate categories.
2. No mechanism to detect out-of-state transactions as vacation.

## Changes

### Change 1: Location-based vacation categorizer

A new `LocationCategorizer` class that detects US state abbreviations and Canadian province codes in transaction descriptions. Any transaction with a state/province other than the user's home state is categorized as Vacation.

**Pipeline placement:** Tier 1.5 — after regex pre-pass, before laya. Regex rules fire first so known online merchants (Amazon, Netflix, etc.) are already categorized and skip location detection.

**State extraction:** Regex pattern matching two uppercase letters at the end of the description (or before a trailing dollar amount). Bank transaction descriptions consistently place the state code at or near the end:
- `MCDONALD'S F40509 CEDAR CITY UT`
- `SHELL C81446 STRATHROY ON`
- `MACYS WOODLANDKENTWOODMI $86.86`

**Online exclusion:** Descriptions containing `.COM`, `WWW.`, `/BILL`, or `ONLINE` are skipped — these show the company's billing state, not the transaction location. This is a simple heuristic that catches Amazon, Walmart.com, and similar online merchants without needing an explicit merchant list.

**Categorization output:**
- `category = "Vacation"`
- `sub_category = ""` (user assigns trip name manually in the dashboard)
- `confidence = 0.9` (high but not 1.0 — the state extraction is heuristic, not guaranteed)
- `categorized_by = "location"`

**Configuration:**
```yaml
home_state: "MI"   # Two-letter state/province code
```

New `home_state` field in `Settings` with default `"MI"`. The location categorizer is always active (no separate enable flag — it does nothing if `home_state` is empty).

**Edge cases:**
- Transactions with no detectable state code: skipped (pass through to laya).
- Uber/Lyft with CA state code: these typically contain `.COM` or are online-pattern matches. If not caught, the user can add a regex rule for `UBER` and `LYFT` patterns from the dashboard. Regex rules run before location detection.
- `DC` (Washington DC): treated as a non-MI state → Vacation. Correct for this user's data.
- Descriptions ending in `HK`, `UK`, or other country codes that happen to match state abbreviations: `HK` is not a US state or Canadian province, so it won't match. All valid codes are from the US 50 states + DC + 13 Canadian provinces/territories.

### Change 2: Rewrite category descriptions

One-time update of all category descriptions in `budget.db` with specific, disambiguating text. These descriptions are used as laya's `criteria` values — they determine what each category "means" to the classifier.

**Guiding principles:**
- Include specific merchant names and keywords that commonly appear in bank transaction descriptions for that category.
- Disambiguate confusing pairs explicitly (Car/Gas mentions gas stations; Utilities/Gas mentions utility bills).
- Keep descriptions concise (under 15 words) — laya works best with focused criteria.

**Updated descriptions:**

| Category | Sub-Category | New Description |
|---|---|---|
| Car | Gas | gas stations, fuel, Shell, BP, Speedway, Meijer gas |
| Car | Insurance | auto insurance, car insurance premium, Progressive, Geico |
| Car | Service | auto repair, oil change, tire, mechanic, dealership service, car wash |
| Car | Taxi | taxi, cab fare, airport shuttle |
| Entertainment | Events | concerts, shows, theme parks, sporting events, tickets, museum |
| Entertainment | Movies | movie theater, cinema, AMC, Regal, Celebration Cinema |
| Entertainment | Streaming | movie rentals, pay-per-view, Fandango, Vudu |
| Grocery | Grocery | grocery stores, supermarkets, Meijer, Kroger, Aldi, food shopping |
| Grocery | Indian | Indian grocery, Indian market, Spice of India, specialty spices |
| Grooming | Clothes | clothing stores, apparel, shoes, fashion retail |
| Grooming | Haircut | haircut, salon, barber, Great Clips, hair styling |
| Grooming | Makeup | cosmetics, beauty products, skincare, Sephora, Ulta |
| Hobby | Books | books, bookstore, Kindle, audiobooks, reading apps |
| Hobby | Learning | online courses, education, training, Claude, ChatGPT, AI tools |
| Hobby | Pickleball | pickleball courts, paddles, pickleball equipment |
| Hobby | YMCA | YMCA membership, gym fees, fitness center |
| House | Aquarium | aquarium supplies, fish, pet store aquarium |
| House | Association Fee | HOA fee, homeowner association dues, community fee |
| House | Insurance | homeowner insurance, home insurance, dwelling policy |
| House | Mortgage | mortgage payment, home loan, escrow |
| House | Ring | Ring doorbell, home security subscription |
| India | Parents | wire transfer to India, remittance, family support |
| Kids Activity | Ice Skating | ice skating rink, skating lessons, Patterson Ice |
| Kids Activity | Music | music lessons, piano, instrument classes, music school |
| Kids Activity | Swimming | swim lessons, pool membership, swimming class |
| Kids Activity | Toys | toy stores, games, LEGO, children's toys |
| Kids Activity | YMCA | kids YMCA programs, youth activities, day camp |
| Medical | Dentist | dentist, dental, orthodontist, teeth cleaning, eye doctor, optometrist |
| Misc | Gifts | gifts, presents, jewelry, department store, Kate Spade, Coach, Perfumania |
| Misc | Photo | photography, photo prints, Shutterfly, portrait studio |
| Online Shopping | Amazon | Amazon, Amazon Marketplace, Amzn, Prime purchases |
| Restaurants | Bubble | bubble tea, boba, smoothie, juice bar, Surf City Squeeze |
| Restaurants | Family | family dining, sit-down restaurants, casual dining, takeout, fast food |
| Restaurants | Office | work lunch, office meal, business dining |
| Tax | Income | income tax, tax payment, IRS, state tax |
| Utilities | Cloud Storage | iCloud, Google One, cloud storage subscription, Apple storage |
| Utilities | Electricity | electric bill, power company, DTE Energy, Consumers Energy |
| Utilities | Gas | natural gas utility bill, gas utility, heating |
| Utilities | Internet | internet service, ISP, Comcast, Xfinity, broadband |
| Utilities | Phone | cell phone bill, mobile plan, T-Mobile, Verizon, AT&T |
| Utilities | Streaming | Netflix, Hulu, Disney+, YouTube TV, Paramount+, HBO, streaming subscription |
| Vacation | Bahamas | Bahamas cruise, Royal Caribbean, Caribbean vacation |
| Vacation | Detroit | Detroit area trip, Sterling Heights, Canton, Troy |
| Vacation | Minnesota | Minnesota trip, Mall of America, Bloomington MN |
| Vacation | Ohio | Ohio trip, Hocking Hills, Logan OH |
| Vacation | Orlando | Orlando trip, Universal Studios, Florida vacation |
| Vacation | Toronto | Toronto trip, Ontario Canada, Niagara |
| Vacation | Utah | Utah trip, Bryce Canyon, Zion, Cedar City, Las Vegas |

**Implementation:** A migration function in `db.py` that runs once at `init_db()` time. It updates descriptions only where the current description matches the auto-generated pattern (`"<sub> (<cat>)"` or empty). Manually edited descriptions are preserved.

**Also update `auto_populate_category_descriptions`:** The current function generates `"{sub_category} ({category})"` for new categories. Change it to just use the sub_category name as-is (e.g., `"Gas"` not `"gas (car)"`). The user can then edit it in the dashboard to be more specific. This is a minor improvement for future categories — the migration handles existing ones.

## Files Changed

| File | Change |
|---|---|
| `budget_parser/categorizer/location_categorizer.py` | **New.** `LocationCategorizer` class with state extraction regex and online exclusion |
| `budget_parser/cli/categorize.py` | Wire location categorizer as Tier 1.5 between regex and laya |
| `budget_parser/database/db.py` | Add `_migrate_category_descriptions()` function; update `auto_populate_category_descriptions` |
| `budget_parser/config/settings.py` | Add `home_state: str` field |
| `budget_parser/config/default_config.yaml` | Add `home_state: "MI"` |
| `tests/test_categorizer/test_location_categorizer.py` | **New.** State extraction, online exclusion, home state skip, edge cases |
| `tests/test_core/test_db_schema.py` | Test description migration |

## Not in Scope

- Trip registry / date-range-based vacation detection
- Automatic sub_category assignment for vacation (user assigns trip name manually)
- Retraining or re-running categorization on already-categorized transactions
