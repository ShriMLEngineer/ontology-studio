"""Generate the sample PDF used by the Phase 3 knowledge-graph demonstration.

Run from the repository root (standard library only):

    python samples/supply-chain/make_sample_pdf.py

The PDF is a plain two-page text document so that page numbers flow into fact provenance.
"""

from pathlib import Path

PAGES = [
    """Supplier Performance Review - Q3 2026
Prepared by Procurement Excellence for the Supply Chain Steering Committee.

1. Northwind Components
Northwind Components (supplier S-001) supplies the Hydraulic Pump HP-100 (product P-100)
and the Control Valve CV-210 (product P-210). Purchase order PO-7001 was issued to
Northwind Components on 2026-07-14 for 20 units of the Hydraulic Pump HP-100.
On-time delivery for Northwind Components was 97 percent this quarter.

2. Contoso Metals
Contoso Metals (supplier S-002) supplies the Steel Bracket SB-200 (product P-200).
Contoso Metals is certified by Bureau Veritas, an independent quality auditor, under
certificate ISO-9001-4471. Purchase order PO-7002 was issued to Contoso Metals on 2026-08-02.""",
    """3. Fabrikam Plastics
Fabrikam Plastics (supplier S-003) supplies the Polymer Housing PH-300 (product P-300).
The risk rating of Fabrikam Plastics was raised to high after two late deliveries in August.

4. Logistics
Shipment SH-9001 fulfils purchase order PO-7001. Shipment SH-9001 is carried by
Blue Yonder Freight and ships to the Rotterdam Distribution Center.

5. Watch list
Contoso is reviewing a new alloy line; the committee will revisit its tier next quarter.""",
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, text in enumerate(pages):
        ops = ["BT", "/F1 11 Tf", "14 TL", "60 740 Td"]
        ops += [f"({_escape(line)}) Tj T*" for line in text.split("\n")]
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects[page_ids[i] + 1] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        objects[page_ids[i]] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>"
        ).encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


if __name__ == "__main__":
    target = Path(__file__).with_name("supplier-performance-review.pdf")
    target.write_bytes(make_pdf(PAGES))
    print(f"Wrote {target} ({target.stat().st_size} bytes)")
