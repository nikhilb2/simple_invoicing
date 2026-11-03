"""GSTN's HSN/SAC master: the committed list and the script that rebuilds it."""
import io
import zipfile

import pytest

from refresh_hsn_codes import OUTPUT, normalize_code, parse_codes
from src.core.validation import HSN_SAC_REGEX, hsn_sac_warning, is_known_hsn_sac


@pytest.mark.parametrize("raw, expected", [
    ("84733020", "84733020"),
    ("847330", "847330"),
    ("9983", "9983"),
    ("0101", "0101"),
    # Stray spaces and lost leading zeros, all present in the April 2026 workbook.
    ("2307 00", "230700"),
    ("3074330", "03074330"),
    ("30559", "030559"),
    # Chapter headings are listed, but GST doesn't accept them on a document.
    ("01", None),
    ("HSN_CD", None),
    ("", None),
    (None, None),
])
def test_normalize_code(raw, expected):
    assert normalize_code(raw) == expected


def _workbook() -> zipfile.ZipFile:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", (
            f"<sst {ns}><si><t>HSN_CD</t></si><si><t>0101</t></si><si><t>Live horses</t></si>"
            "<si><t>9983</t></si></sst>"
        ))
        archive.writestr("xl/worksheets/sheet1.xml", (
            f'<worksheet {ns}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>'
            '<row r="3"><c r="A3"><v>84733020</v></c><c r="B3" t="e"><v>#NAME?</v></c></row>'
            '</sheetData></worksheet>'
        ))
        archive.writestr("xl/worksheets/sheet2.xml", (
            f'<worksheet {ns}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>3</v></c></row>'
            '</sheetData></worksheet>'
        ))
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


def test_parse_codes_reads_every_sheet_and_only_column_a():
    assert parse_codes(_workbook()) == {"0101", "84733020", "9983"}


def test_the_committed_list_only_holds_codes_a_document_can_carry():
    lines = OUTPUT.read_text(encoding="ascii").splitlines()
    codes = [line for line in lines if not line.startswith("#")]
    assert codes == sorted(set(codes))
    assert all(HSN_SAC_REGEX.fullmatch(code) for code in codes)


@pytest.mark.parametrize("code", ["84733020", "847330", "8473", "0101", "998713", "9983", " 84733020 "])
def test_known_codes(code):
    assert is_known_hsn_sac(code)
    assert hsn_sac_warning(code) is None


# 84733000 is the right length and was rejected by the portal as RET191349.
@pytest.mark.parametrize("code", ["84733000", "1234", "99842"])
def test_unknown_codes_warn(code):
    assert not is_known_hsn_sac(code)
    assert code in hsn_sac_warning(code)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_blank_code_is_not_a_warning(value):
    assert hsn_sac_warning(value) is None
