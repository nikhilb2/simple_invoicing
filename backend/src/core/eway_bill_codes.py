"""Codes and formats of the NIC e-way bill bulk upload, from NIC's own material.

Taken from the bulk generation tools on docs.ewaybillgst.gov.in: the attributes
workbook (EWB_Attributes_new.xlsx), the JSON preparation tool
(EWB_Preparation_Tool_17062021.xlsm) and the API master code list. The bulk file
is not the API payload: it names several keys differently (transType,
actualFromStateCode, OthValue), so the API schema is no guide to its key names.
"""

import re

# What the newest NIC preparation tool we could find writes into the file. The
# portal's handling of this field could not be tested: see the PR for #378.
NIC_JSON_VERSION = "1.0.0621"

# Master codes: Unit.
NIC_UQC_CODES = frozenset({
    "BAG", "BAL", "BDL", "BKL", "BOU", "BOX", "BTL", "BUN", "CAN", "CBM", "CCM", "CMS",
    "CTN", "DOZ", "DRM", "GGK", "GMS", "GRS", "GYD", "KGS", "KLR", "KME", "LTR", "MTR",
    "MLT", "MTS", "NOS", "OTH", "PAC", "PCS", "PRS", "QTL", "ROL", "SET", "SQF", "SQM",
    "SQY", "TBS", "TGM", "THD", "TON", "TUB", "UGS", "UNT", "YDS",
})

# The sub-supply types NIC allows on an outward Tax Invoice (the "Supply Type -
# Document Type Mapping"), which is the only document these routes generate from.
# Job Work, Line Sales, Exhibition, For Own Use and the rest need a delivery challan.
SUB_SUPPLY_SUPPLY = "1"
SUB_SUPPLY_EXPORT = "3"
SUB_SUPPLY_SKD_CKD = "9"
INVOICE_SUB_SUPPLY_CODES = {
    SUB_SUPPLY_SUPPLY: "Supply",
    SUB_SUPPLY_EXPORT: "Export",
    SUB_SUPPLY_SKD_CKD: "SKD/CKD/Lots",
}

# transType: 1=Regular, 2=Bill To-Ship To, 3=Bill From-Dispatch From, 4=both.
TRANSACTION_REGULAR = "1"
TRANSACTION_BILL_TO_SHIP_TO = "2"
TRANSACTION_BILL_FROM_DISPATCH_FROM = "3"
TRANSACTION_COMBINATION = "4"
TRANSACTION_TYPE_CODES = frozenset({
    TRANSACTION_REGULAR,
    TRANSACTION_BILL_TO_SHIP_TO,
    TRANSACTION_BILL_FROM_DISPATCH_FROM,
    TRANSACTION_COMBINATION,
})

# transMode: 1=Road, 2=Rail, 3=Air, 4=Ship.
ROAD_MODE = "1"
RAIL_MODE = "2"
AIR_MODE = "3"
SHIP_MODE = "4"
TRANSPORT_MODE_CODES = frozenset({ROAD_MODE, RAIL_MODE, AIR_MODE, SHIP_MODE})

# vehicleType: R=Regular, O=Over Dimensional Cargo.
VEHICLE_TYPE_ODC = "O"
VEHICLE_TYPE_CODES = frozenset({"R", VEHICLE_TYPE_ODC})

# Master codes: Valid Formats of Vehicle Numbers.
VEHICLE_REGEX = re.compile(
    r"^(?:"
    r"[A-Z]{2}[0-9]{2}[A-Z]{0,3}[0-9]{4}"  # AB121234, AB12A1234, AB12AB1234, AB12ABC1234
    r"|[A-Z]{3}[0-9]{4}"  # ABC1234
    r"|[A-Z]{2}[0-9]{3}[A-Z][0-9]{4}"  # AB123A1234
    r"|DF[A-Z0-9]{6}"  # defence
    r"|(?:TM|BP|NP)[A-Z0-9]{5,13}"  # temporary registration, Bhutan, Nepal
    r")$"
)

# transporterId takes a GSTIN or an enrolled transporter's TRANSIN.
TRANSPORTER_ID_REGEX = re.compile(r"^[0-9]{2}[0-9A-Z]{13}$")

# docNo: at most 16 characters, alphanumeric with / - and .
DOC_NO_REGEX = re.compile(r"^[A-Za-z0-9/.\-]{1,16}$")

# Everything NIC's tool accepts in names, addresses, places and descriptions.
DISALLOWED_TEXT_REGEX = re.compile(r"[^A-Za-z0-9 @#\-/,&.]")

MAX_DISTANCE_KM = 4000
# The most NIC allows when the two PIN codes are the same.
MAX_SAME_PIN_DISTANCE_KM = 100
MAX_ITEMS = 250
MAX_ADDRESS_LENGTH = 120
MAX_NAME_LENGTH = 100
MAX_PLACE_LENGTH = 50
MAX_DESC_LENGTH = 100
MAX_TRANSPORT_DOC_NO_LENGTH = 15

# GST state codes the portal takes for "Other Country" (it stores 96 as 99).
OTHER_COUNTRY_STATE_CODES = frozenset({"96", "99"})
