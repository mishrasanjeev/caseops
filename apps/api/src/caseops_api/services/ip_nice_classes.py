"""WIPO Nice Classification class headings for trademark class selection.

The catalogue is reference data, identical for every tenant. It is the single
predicate that both the class picker (``GET /api/ip/nice-classes``) and the
trademark particulars validator use, so the UI can never offer a class the API
rejects.

Edition: NCL 13-2026, i.e. the 13th edition, version 2026, in force from
1 January 2026 (the version WIPO publishes as in force on that date).

Provenance (retrieved 2026-10-31):

* Data file: ``ncl-20260101-en-classification_texts-20250610.xml`` inside
  ``ncl-20260101-classification_texts-20260715.zip`` from WIPO's Nice download
  and IT support area (``NICE_SOURCE_DATA_URL``). The XML root declares
  ``edition="13" version="2026" dateInForce="2026-01-01"``. Its MD5,
  ``b7d3af7e78931286d4efbfc200e64a09``, matches WIPO's published
  ``20260101md5.txt``; its SHA-256 is
  ``8616c54919178fd27e3cc6adf8ad6105b13b72921e4c678b8f14403e93eea21d``.
* Goods/services kind per class: ``classification_top_structure`` for the same
  version (``isGoodOrService``), SHA-256 of the XML
  ``c496a5968382f6df70bb316b1749bb27bc03144d882d308bce396d2bdb118533``.
* ``heading`` is each class's ``HeadingItem`` texts joined with ``"; "`` and
  closed with ``"."``, which is how WIPO's NCL publication
  (``NICE_SOURCE_URL``) renders the class heading. ``note`` is the
  ``Introduction`` sentence of the class's explanatory note.

Edition NCL 13-2027 (13th edition, version 2027, in force from 1 January
2027) is held as its own catalogue, retrieved 2026-10-31:

* Data file: ``ncl-20270101-en-classification_texts-20260526.xml`` inside
  ``ncl-20270101-classification_texts-20260526.zip`` (``NCL_13_2027.source_data_url``).
  The XML root declares ``edition="13" version="2027" dateInForce="2027-01-01"``.
  Its MD5, ``33795931965a2da2121993401f8a4dcb``, matches WIPO's published
  ``20270101md5.txt`` (generated 2026-09-03); its SHA-256 is
  ``235fbf5973e13ea9ab0fee003846b7de1c5237a66cfb5b0e976b0901ea25095d``.
* ``classification_top_structure`` 20260526: MD5
  ``ad153ef9b41839431b3b8baff3fb6f8d`` (matches ``20270101md5.txt``), SHA-256
  ``b59b8aa63fbe9ec3ae993955dc0400c322a52cb6342b4337d5b25736f042848c``.
* Against version 2026 only the class 6 heading and note and the class 9
  heading change; ``NCL_13_2027_REVISED_CLASSES`` holds those rows verbatim and
  every other row is the 2026 text, which the 2027 XML repeats unchanged. The
  2027 digests pin the full 45-class text.

The edition served by default, and stamped on a row that states none, is the
one in force on the server's UTC date (``nice_catalogue_in_force``). A row may
also state an earlier edition CaseOps holds (``recordable_nice_editions``):
an application keeps the edition it was classified under, so an amendment or
an import of a 2026 record stays valid after 1 January 2027. An edition not yet
in force, or one CaseOps does not hold, is refused. Every held edition stays
readable (``GET /api/ip/nice-classes?edition=``), so a recorded row keeps its
class heading after its edition is superseded.

Text is copied verbatim; do not edit it by hand. ``NICE_HEADINGS_SHA256`` and
``NICE_NOTES_SHA256`` pin the normalized text (see ``normalized_headings`` and
``normalized_notes``), and the tests recompute them. A new edition or version
is a new catalogue with new provenance, never an in-place edit: stored class
rows carry the edition they were validated against.

WIPO requires its copyright to be acknowledged wherever the NCL is used
(``NICE_ATTRIBUTION``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

NiceClassKind = Literal["goods", "services"]

NICE_EDITION = "NCL 13-2026"
NICE_IN_FORCE_FROM = date(2026, 1, 1)
NICE_RETRIEVED_ON = date(2026, 10, 31)
NICE_SOURCE_URL = (
    "https://nclpub.wipo.int/enfr/?basic_numbers=show&explanatory_notes=show&lang=en"
    "&menulang=en&mode=flat&notion=&pagination=no&version=20260101"
)
NICE_SOURCE_DATA_URL = (
    "https://www.wipo.int/classifications/data/nice/ITSupport_and_download_area/20260101/"
    "MasterFiles/ncl-20260101-classification_texts-20260715.zip"
)
NICE_ATTRIBUTION = (
    "Nice Classification, 13th edition, version 2026 (NCL 13-2026). "
    "Copyright World Intellectual Property Organization (WIPO)."
)
NICE_HEADINGS_SHA256 = "ef15fc8e741c2bfac8892f82fc796f759d4a504017f02e51699a50b90d93dcbf"
NICE_NOTES_SHA256 = "381bec1d255fe01b7d28ceea8c5164e82375c05aa9bd80ce96d3dcf6a176f9ad"
NICE_CLASS_MIN = 1
NICE_CLASS_MAX = 45


@dataclass(frozen=True, slots=True)
class NiceClass:
    number: int
    kind: NiceClassKind
    heading: str
    note: str


NICE_CLASSES: tuple[NiceClass, ...] = (
    NiceClass(
        number=1,
        kind="goods",
        heading=(
            "Chemicals for use in industry, science and photography, as well as in "
            "agriculture, horticulture and forestry; unprocessed artificial resins, "
            "unprocessed plastics; fire extinguishing and fire prevention compositions; "
            "tempering and soldering preparations; substances for tanning animal skins and "
            "hides; adhesives for use in industry; compost, manures, fertilizers; "
            "biological preparations for use in industry and science."
        ),
        note=(
            "Class 1 includes mainly chemical products for use in industry, science and "
            "agriculture, including those which go to the making of products belonging to "
            "other classes."
        ),
    ),
    NiceClass(
        number=2,
        kind="goods",
        heading=(
            "Paints, varnishes, lacquers; preservatives against rust and against "
            "deterioration of wood; colorants, dyes; inks for printing, marking and "
            "engraving; raw natural resins; metals in foil and powder form for use in "
            "painting, decorating, printing and art."
        ),
        note=(
            "Class 2 includes mainly paints, colorants and preparations used for "
            "protection against corrosion."
        ),
    ),
    NiceClass(
        number=3,
        kind="goods",
        heading=(
            "Non-medicated cosmetics and toiletry preparations; non-medicated dentifrices; "
            "perfumes; bleaching preparations and other substances for laundry use; "
            "cleaning, polishing and abrasive preparations."
        ),
        note=(
            "Class 3 includes mainly non-medicated toiletry preparations, as well as "
            "cleaning preparations for use in the home and other environments."
        ),
    ),
    NiceClass(
        number=4,
        kind="goods",
        heading=(
            "Industrial oils and greases, wax; lubricants; dust absorbing, wetting and "
            "binding compositions; fuels and illuminants; candles and wicks for lighting."
        ),
        note="Class 4 includes mainly industrial oils and greases, fuels and illuminants.",
    ),
    NiceClass(
        number=5,
        kind="goods",
        heading=(
            "Pharmaceuticals, medical and veterinary preparations; sanitary preparations "
            "for medical purposes; dietetic food and substances adapted for medical or "
            "veterinary purposes, food for babies; dietary supplements for human beings "
            "and animals; adhesive plasters, materials for dressings; material for filling "
            "teeth, dental wax; disinfectants; preparations for destroying vermin; "
            "fungicides, herbicides."
        ),
        note=(
            "Class 5 includes mainly pharmaceuticals and other preparations for medical or "
            "veterinary purposes."
        ),
    ),
    NiceClass(
        number=6,
        kind="goods",
        heading=(
            "Common metals and their alloys, ores; metal materials for building and "
            "construction; transportable buildings of metal; non-electric cables and wires "
            "of common metal; small items of metal hardware; metal containers for storage "
            "or transport; safes."
        ),
        note=(
            "Class 6 includes mainly unwrought and partly wrought common metals, including "
            "ores, as well as certain goods made of common metals."
        ),
    ),
    NiceClass(
        number=7,
        kind="goods",
        heading=(
            "Machines, machine tools, power-operated tools; motors and engines, except for "
            "land vehicles; machine coupling and transmission components, except for land "
            "vehicles; agricultural implements, other than hand-operated hand tools; "
            "incubators for eggs; automatic vending machines."
        ),
        note="Class 7 includes mainly machines and machine tools, motors and engines.",
    ),
    NiceClass(
        number=8,
        kind="goods",
        heading=(
            "Hand-operated hand tools and implements; cutlery; side arms, except firearms; "
            "razors."
        ),
        note=(
            "Class 8 includes mainly hand-operated tools and implements for performing "
            "tasks, such as drilling, shaping, cutting and piercing."
        ),
    ),
    NiceClass(
        number=9,
        kind="goods",
        heading=(
            "Scientific, research, navigation, surveying, photographic, cinematographic, "
            "audiovisual, optical, weighing, measuring, signalling, detecting, testing, "
            "inspecting, life-saving and teaching apparatus and instruments; apparatus and "
            "instruments for conducting, switching, transforming, accumulating, regulating "
            "or controlling the distribution or use of electricity; apparatus and "
            "instruments for recording, transmitting, reproducing or processing sound, "
            "images or data; recorded and downloadable multimedia files, computer "
            "software, blank digital or analogue recording and storage media; mechanisms "
            "for coin-operated apparatus; cash registers, calculating devices; computers "
            "and computer peripheral devices; diving suits, divers' masks, ear plugs for "
            "divers, nose clips for divers, gloves for divers, breathing apparatus for "
            "underwater swimming; fire-extinguishing apparatus."
        ),
        note=(
            "Class 9 includes mainly apparatus and instruments for scientific or research "
            "purposes, audiovisual and information technology equipment, as well as safety "
            "and life-saving equipment."
        ),
    ),
    NiceClass(
        number=10,
        kind="goods",
        heading=(
            "Surgical, medical, dental and veterinary apparatus and instruments; "
            "artificial limbs, eyes and teeth; spectacles, contact lenses and sunglasses; "
            "orthopaedic articles; suture materials; therapeutic and assistive devices "
            "adapted for persons with disabilities; massage apparatus; apparatus, devices "
            "and articles for nursing infants; sexual activity apparatus, devices and "
            "articles."
        ),
        note=(
            "Class 10 includes mainly surgical, medical, dental and veterinary apparatus, "
            "instruments and articles generally used for the diagnosis, treatment or "
            "improvement of function or condition of persons and animals."
        ),
    ),
    NiceClass(
        number=11,
        kind="goods",
        heading=(
            "Apparatus and installations for lighting, heating, cooling, steam generating, "
            "cooking, drying, ventilating, water supply and sanitary purposes."
        ),
        note=(
            "Class 11 includes mainly environmental control apparatus and installations, "
            "in particular, for the purposes of lighting, cooking, cooling and sanitizing."
        ),
    ),
    NiceClass(
        number=12,
        kind="goods",
        heading="Vehicles; apparatus for locomotion by land, air or water.",
        note=(
            "Class 12 includes mainly vehicles and apparatus for the transport of people "
            "or goods by land, air or water."
        ),
    ),
    NiceClass(
        number=13,
        kind="goods",
        heading="Firearms; ammunition and projectiles; explosives; fireworks.",
        note="Class 13 includes mainly firearms and pyrotechnic products.",
    ),
    NiceClass(
        number=14,
        kind="goods",
        heading=(
            "Precious metals and their alloys; jewellery, precious and semi-precious "
            "stones; horological and chronometric instruments."
        ),
        note=(
            "Class 14 includes mainly precious metals and certain goods made of precious "
            "metals or coated therewith, as well as jewellery, clocks and watches, and "
            "component parts therefor."
        ),
    ),
    NiceClass(
        number=15,
        kind="goods",
        heading=(
            "Musical instruments; music stands and stands for musical instruments; "
            "conductors' batons."
        ),
        note=(
            "Class 15 includes mainly musical instruments, their parts and their "
            "accessories."
        ),
    ),
    NiceClass(
        number=16,
        kind="goods",
        heading=(
            "Paper and cardboard; printed matter; bookbinding material; photographs; "
            "stationery and office requisites, except furniture; adhesives for stationery "
            "or household purposes; drawing materials and materials for artists; "
            "paintbrushes; instructional and teaching materials; plastic sheets, films and "
            "bags for wrapping and packaging; printers' type, printing blocks."
        ),
        note=(
            "Class 16 includes mainly paper, cardboard and certain goods made of those "
            "materials, as well as office requisites."
        ),
    ),
    NiceClass(
        number=17,
        kind="goods",
        heading=(
            "Unprocessed and semi-processed rubber, gutta-percha, gum, asbestos, mica and "
            "substitutes for all these materials; plastics and resins in extruded form for "
            "use in manufacture; packing, stopping and insulating materials; flexible "
            "pipes, tubes and hoses, not of metal."
        ),
        note=(
            "Class 17 includes mainly electrical, thermal and acoustic insulating "
            "materials and plastics for use in manufacture in the form of sheets, blocks "
            "and rods, as well as certain goods made of rubber, gutta-percha, gum, "
            "asbestos, mica or substitutes therefor."
        ),
    ),
    NiceClass(
        number=18,
        kind="goods",
        heading=(
            "Leather and imitations of leather; animal skins and hides; luggage and "
            "carrying bags; umbrellas and parasols; walking sticks; whips, harness and "
            "saddlery; collars, leashes and clothing for animals."
        ),
        note=(
            "Class 18 includes mainly leather, imitations of leather and certain goods "
            "made of those materials."
        ),
    ),
    NiceClass(
        number=19,
        kind="goods",
        heading=(
            "Materials, not of metal, for building and construction; rigid pipes, not of "
            "metal, for building; asphalt, pitch, tar and bitumen; transportable "
            "buildings, not of metal; monuments, not of metal."
        ),
        note=(
            "Class 19 includes mainly materials, not of metal, for building and "
            "construction."
        ),
    ),
    NiceClass(
        number=20,
        kind="goods",
        heading=(
            "Furniture, mirrors, picture frames; containers, not of metal, for storage or "
            "transport; unworked or semi-worked bone, horn, whalebone or mother-of-pearl; "
            "shells; meerschaum; yellow amber."
        ),
        note=(
            "Class 20 includes mainly furniture and parts therefor, as well as certain "
            "goods made of wood, cork, reed, cane, wicker, horn, bone, whalebone, shell, "
            "amber, mother-of-pearl, meerschaum and substitutes for all these materials, "
            "or of plastic."
        ),
    ),
    NiceClass(
        number=21,
        kind="goods",
        heading=(
            "Household or kitchen utensils and containers; cookware and tableware, except "
            "forks, knives and spoons; combs and sponges; brushes, except paintbrushes; "
            "brush-making materials; articles for cleaning purposes; unworked or "
            "semi-worked glass, except building glass; glassware, porcelain and "
            "earthenware."
        ),
        note=(
            "Class 21 includes mainly small, hand-operated utensils and apparatus for "
            "household and kitchen use, as well as cosmetic utensils, glassware and "
            "certain goods made of porcelain, ceramic, earthenware, terra-cotta, clay or "
            "glass."
        ),
    ),
    NiceClass(
        number=22,
        kind="goods",
        heading=(
            "Ropes and string; nets; tents and tarpaulins; awnings of textile or synthetic "
            "materials; sails; sacks for the transport and storage of materials in bulk; "
            "padding, cushioning and stuffing materials, except of paper, cardboard, "
            "rubber or plastics; raw fibrous textile materials and substitutes therefor."
        ),
        note=(
            "Class 22 includes mainly canvas and other materials for making sails, rope, "
            "padding, cushioning and stuffing materials and raw fibrous textile materials."
        ),
    ),
    NiceClass(
        number=23,
        kind="goods",
        heading="Yarns and threads for textile use.",
        note=(
            "Class 23 includes mainly natural or synthetic yarns and threads for textile "
            "use."
        ),
    ),
    NiceClass(
        number=24,
        kind="goods",
        heading=(
            "Textiles and substitutes for textiles; household linen; curtains of textile "
            "or plastic."
        ),
        note="Class 24 includes mainly fabrics and fabric covers for household use.",
    ),
    NiceClass(
        number=25,
        kind="goods",
        heading="Clothing, footwear, headwear.",
        note="Class 25 includes mainly clothing, footwear and headwear for human beings.",
    ),
    NiceClass(
        number=26,
        kind="goods",
        heading=(
            "Lace and embroidery, and haberdashery ribbons and bows; buttons, hooks and "
            "eyes, pins and needles; artificial flowers; hair decorations; false hair."
        ),
        note=(
            "Class 26 includes mainly dressmakers' articles, natural or synthetic hair for "
            "wear, and hair adornments, as well as small decorative items intended to "
            "adorn a variety of objects, not included in other classes."
        ),
    ),
    NiceClass(
        number=27,
        kind="goods",
        heading=(
            "Carpets, rugs, mats and matting, linoleum and other materials for covering "
            "existing floors; wall hangings, not of textile."
        ),
        note=(
            "Class 27 includes mainly products intended to be added as coverings to "
            "previously constructed floors and walls."
        ),
    ),
    NiceClass(
        number=28,
        kind="goods",
        heading=(
            "Games, toys and playthings; video game apparatus; gymnastic and sporting "
            "articles; decorations for Christmas trees."
        ),
        note=(
            "Class 28 includes mainly toys, apparatus for playing games, sports equipment, "
            "amusement and novelty items, as well as certain articles for Christmas trees."
        ),
    ),
    NiceClass(
        number=29,
        kind="goods",
        heading=(
            "Meat, fish, poultry and game; meat extracts for culinary purposes; preserved, "
            "frozen, dried and cooked fruits, vegetables and seaweeds; jellies, jams, "
            "compotes; eggs; milk, cheese, butter, yogurt and other milk products; oils "
            "and fats for food."
        ),
        note=(
            "Class 29 includes mainly foodstuffs of animal origin, as well as fruits and "
            "vegetables, and other horticultural comestible products which are prepared or "
            "preserved for consumption."
        ),
    ),
    NiceClass(
        number=30,
        kind="goods",
        heading=(
            "Coffee, tea, cocoa and substitutes therefor; rice, pasta and noodles; tapioca "
            "and sago; flour and preparations made from cereals; bread, pastries and "
            "confectionery; chocolate; ice cream, sorbets and other edible ices; sugar, "
            "honey, treacle; yeast, baking-powder; salt, seasonings, spices, preserved "
            "herbs; vinegar, sauces and other condiments; ice (frozen water)."
        ),
        note=(
            "Class 30 includes mainly foodstuffs of plant origin, except fruits and "
            "vegetables, prepared or preserved for consumption, as well as auxiliaries "
            "intended for the improvement of the flavour of food."
        ),
    ),
    NiceClass(
        number=31,
        kind="goods",
        heading=(
            "Raw and unprocessed agricultural, aquacultural, horticultural and forestry "
            "products; raw and unprocessed grains and seeds; fresh fruits and vegetables, "
            "fresh herbs; natural plants and flowers; bulbs, seedlings and seeds for "
            "planting; live animals; foodstuffs and beverages for animals; malt."
        ),
        note=(
            "Class 31 includes mainly land and sea products not having been subjected to "
            "any form of preparation for consumption, live animals and plants, as well as "
            "foodstuffs for animals."
        ),
    ),
    NiceClass(
        number=32,
        kind="goods",
        heading=(
            "Beers; non-alcoholic beverages; mineral and aerated waters; fruit beverages "
            "and fruit juices; syrups and other preparations for making non-alcoholic "
            "beverages."
        ),
        note="Class 32 includes mainly non-alcoholic beverages, as well as beer.",
    ),
    NiceClass(
        number=33,
        kind="goods",
        heading=(
            "Alcoholic beverages, except beers; alcoholic preparations for making "
            "beverages."
        ),
        note="Class 33 includes mainly alcoholic beverages, essences and extracts.",
    ),
    NiceClass(
        number=34,
        kind="goods",
        heading=(
            "Tobacco and tobacco substitutes; cigarettes and cigars; electronic cigarettes "
            "and oral vaporizers for smokers; smokers' articles; matches."
        ),
        note=(
            "Class 34 includes mainly tobacco and articles used for smoking, as well as "
            "certain accessories and containers related to their use."
        ),
    ),
    NiceClass(
        number=35,
        kind="services",
        heading=(
            "Advertising; business management, organization and administration; office "
            "functions."
        ),
        note=(
            "Class 35 includes mainly services involving business management, operation, "
            "organization and administration of a commercial or industrial enterprise, as "
            "well as advertising, marketing and promotional services. For the purposes of "
            "classification, the sale of goods is not considered to be a service."
        ),
    ),
    NiceClass(
        number=36,
        kind="services",
        heading=(
            "Financial, monetary and banking services; insurance services; real estate "
            "services."
        ),
        note=(
            "Class 36 includes mainly services relating to banking and other financial "
            "transactions, financial valuation services, as well as insurance and real "
            "estate activities."
        ),
    ),
    NiceClass(
        number=37,
        kind="services",
        heading=(
            "Construction services; installation and repair services; mining extraction, "
            "oil and gas drilling."
        ),
        note=(
            "Class 37 includes mainly services in the field of construction, as well as "
            "services involving the restoration of objects to their original condition or "
            "their preservation without altering their physical or chemical properties."
        ),
    ),
    NiceClass(
        number=38,
        kind="services",
        heading="Telecommunications services.",
        note=(
            "Class 38 includes mainly services that allow at least one party to "
            "communicate with another, as well as services for the broadcasting and "
            "transmission of data."
        ),
    ),
    NiceClass(
        number=39,
        kind="services",
        heading="Transport; packaging and storage of goods; travel arrangement.",
        note=(
            "Class 39 includes mainly services for the transport of people, animals or "
            "goods from one place to another by rail, road, water, air or pipeline and "
            "services necessarily connected with such transport, as well as the storing of "
            "goods in any kind of storage facility, warehouses or other types of building "
            "for their preservation or guarding."
        ),
    ),
    NiceClass(
        number=40,
        kind="services",
        heading=(
            "Treatment of materials; recycling of waste and trash; air purification and "
            "treatment of water; printing services; food and drink preservation."
        ),
        note=(
            "Class 40 includes mainly services rendered by the mechanical or chemical "
            "processing, transformation or production of objects or inorganic or organic "
            "substances, including custom manufacturing services. For the purposes of "
            "classification, the production or manufacturing of goods is considered a "
            "service only in cases where it is effected for the account of another person "
            "to their order and specification. If the production or manufacturing is not "
            "being performed to fulfil an order for goods which meet the customer's "
            "particular needs, requirements, or specifications, then it is generally "
            "ancillary to the maker's primary commercial activity or goods in trade. If "
            "the substance or object is marketed to third parties by the person who "
            "processed, transformed or produced it, then this would generally not be "
            "considered a service."
        ),
    ),
    NiceClass(
        number=41,
        kind="services",
        heading=(
            "Education; providing of training; entertainment; sporting and cultural "
            "activities."
        ),
        note=(
            "Class 41 includes mainly services consisting of all forms of education or "
            "training, services having the basic aim of the entertainment, amusement or "
            "recreation of people, as well as the presentation of works of visual art or "
            "literature to the public for cultural or educational purposes."
        ),
    ),
    NiceClass(
        number=42,
        kind="services",
        heading=(
            "Scientific and technological services and research and design relating "
            "thereto; industrial analysis, industrial research and industrial design "
            "services; quality control and authentication services; design and development "
            "of computer hardware and software."
        ),
        note=(
            "Class 42 includes mainly services provided by persons in relation to the "
            "theoretical and practical aspects of complex fields of activities, for "
            "example, scientific laboratory services, engineering, computer programming, "
            "architectural services or interior design."
        ),
    ),
    NiceClass(
        number=43,
        kind="services",
        heading="Services for providing food and drink; temporary accommodation.",
        note=(
            "Class 43 includes mainly services provided in relation to the preparation of "
            "food and drink for consumption, as well as services for providing temporary "
            "accommodation."
        ),
    ),
    NiceClass(
        number=44,
        kind="services",
        heading=(
            "Medical services; veterinary services; hygienic and beauty care for human "
            "beings or animals; agriculture, aquaculture, horticulture and forestry "
            "services."
        ),
        note=(
            "Class 44 includes mainly medical care, including alternative medicine, "
            "hygienic and beauty care given by persons or establishments to human beings "
            "and animals, as well as services relating to the fields of agriculture, "
            "aquaculture, horticulture and forestry."
        ),
    ),
    NiceClass(
        number=45,
        kind="services",
        heading=(
            "Legal services; security services for the physical protection of tangible "
            "property and individuals; dating services, online social networking services; "
            "funerary services; babysitting."
        ),
        note=(
            "Class 45 includes mainly legal and security services, as well as certain "
            "personal and social services rendered by others to meet the needs of "
            "individuals."
        ),
    ),
)

_BY_NUMBER: dict[int, NiceClass] = {row.number: row for row in NICE_CLASSES}

NCL_13_2027_REVISED_CLASSES: tuple[NiceClass, ...] = (
    NiceClass(
        number=6,
        kind="goods",
        heading=(
            "Common metals and their alloys; ores; metal materials for building and "
            "construction; transportable buildings of metal; non-electric cables and wires "
            "of common metal; small items of metal hardware; metal containers for storage "
            "or transport; safes."
        ),
        note=(
            "Class 6 includes mainly unwrought and partly wrought common metals, as well "
            "as certain goods made of common metals."
        ),
    ),
    NiceClass(
        number=9,
        kind="goods",
        heading=(
            "Scientific, research, navigation, surveying, photographic, cinematographic, "
            "audiovisual, optical, weighing, measuring, signalling, detecting, testing, "
            "inspecting, life-saving and teaching apparatus and instruments; apparatus and "
            "instruments for conducting, switching, transforming, accumulating, regulating or "
            "controlling the distribution or use of electricity; apparatus and instruments "
            "for recording, transmitting, reproducing or processing sound, images or data; "
            "recorded and downloadable multimedia files, computer software, blank digital or "
            "analogue recording and storage media; mechanisms for coin-operated apparatus; "
            "cash registers, calculating devices; computers and computer peripheral devices; "
            "diving suits, diving masks, ear plugs for diving, nose clips for diving, diving "
            "gloves, breathing apparatus for underwater swimming; fire-extinguishing "
            "apparatus."
        ),
        note=_BY_NUMBER[9].note,
    ),
)


@dataclass(frozen=True, slots=True)
class NiceCatalogue:
    edition: str
    in_force_from: date
    retrieved_on: date
    source_url: str
    source_data_url: str
    attribution: str
    headings_sha256: str
    notes_sha256: str
    classes: tuple[NiceClass, ...]


NCL_13_2026 = NiceCatalogue(
    edition=NICE_EDITION,
    in_force_from=NICE_IN_FORCE_FROM,
    retrieved_on=NICE_RETRIEVED_ON,
    source_url=NICE_SOURCE_URL,
    source_data_url=NICE_SOURCE_DATA_URL,
    attribution=NICE_ATTRIBUTION,
    headings_sha256=NICE_HEADINGS_SHA256,
    notes_sha256=NICE_NOTES_SHA256,
    classes=NICE_CLASSES,
)

_REVISED_2027 = {row.number: row for row in NCL_13_2027_REVISED_CLASSES}
NCL_13_2027 = NiceCatalogue(
    edition="NCL 13-2027",
    in_force_from=date(2027, 1, 1),
    retrieved_on=date(2026, 10, 31),
    source_url=NICE_SOURCE_URL.replace("version=20260101", "version=20270101"),
    source_data_url=(
        "https://www.wipo.int/classifications/data/nice/ITSupport_and_download_area/20270101/"
        "MasterFiles/ncl-20270101-classification_texts-20260526.zip"
    ),
    attribution=(
        "Nice Classification, 13th edition, version 2027 (NCL 13-2027). "
        "Copyright World Intellectual Property Organization (WIPO)."
    ),
    headings_sha256="27cd8bcd75b69ce8ad8787b0710e84a2256371cc23deb5fbcaea406a9496d2ed",
    notes_sha256="4a875e8c6763be8de2993d352753c10e8ff771252873ebd5a61dfdd901d8a465",
    classes=tuple(_REVISED_2027.get(row.number, row) for row in NICE_CLASSES),
)

# Oldest first; every edition lists classes 1-45.
NICE_CATALOGUES: tuple[NiceCatalogue, ...] = (NCL_13_2026, NCL_13_2027)


def _server_date() -> date:
    return datetime.now(UTC).date()


def nice_catalogue_in_force(on: date | None = None) -> NiceCatalogue:
    """Return the latest edition in force on ``on`` (default: the server's UTC date)."""
    day = on or _server_date()
    in_force = [row for row in NICE_CATALOGUES if row.in_force_from <= day]
    return in_force[-1] if in_force else NICE_CATALOGUES[0]


def recordable_nice_editions(on: date | None = None) -> tuple[str, ...]:
    """Editions a class row may record on ``on``, newest (the one in force) first.

    The edition in force and every earlier edition CaseOps holds; never one
    that is not yet in force.
    """
    current = nice_catalogue_in_force(on)
    return tuple(
        row.edition
        for row in reversed(NICE_CATALOGUES)
        if row.in_force_from <= current.in_force_from
    )


def nice_edition_refusal(on: date | None = None) -> str:
    """The sentence a refused ``nice_edition`` reads, without a row prefix."""
    accepted = recordable_nice_editions(on)
    if len(accepted) == 1:
        return f"only Nice edition {accepted[0]} is supported."
    return f"Nice edition must be one of {', '.join(accepted)}."


def nice_class(number: int) -> NiceClass | None:
    """Return the NCL 13-2026 class for ``number``, or ``None`` if it is not one."""
    if isinstance(number, bool):
        return None
    return _BY_NUMBER.get(number)


def is_nice_class(number: object) -> bool:
    return isinstance(number, int) and not isinstance(number, bool) and number in _BY_NUMBER


def normalized_headings(classes: Iterable[NiceClass] = NICE_CLASSES) -> str:
    return "".join(f"{row.number}\t{row.kind}\t{row.heading}\n" for row in classes)


def normalized_notes(classes: Iterable[NiceClass] = NICE_CLASSES) -> str:
    return "".join(f"{row.number}\t{row.note}\n" for row in classes)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
