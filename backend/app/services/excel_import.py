"""Flexible lead extraction from ANY Excel/CSV shape.

Priority: company name, person name, website — plus email, title, phone,
country. Header names are matched loosely; if headers are missing entirely we
fall back to pattern detection (emails by regex, URLs by prefix) so 'any form
of excel' still imports correctly."""
import io
import re
import csv
import openpyxl

ALIASES = {
    "name": {"name", "full name", "fullname", "client", "client name", "contact",
             "contact name", "person", "person name", "first name", "lead name",
             "owner", "decision maker"},
    "email": {"email", "e-mail", "mail", "email address", "work email",
              "business email", "contact email"},
    "company": {"company", "company name", "organisation", "organization", "org",
                "business", "business name", "firm", "brand", "account"},
    "title": {"title", "job title", "role", "designation", "position"},
    "phone": {"phone", "phone number", "mobile", "contact number", "tel",
              "telephone", "whatsapp"},
    "website": {"website", "site", "url", "domain", "web", "company website",
                "web site", "homepage", "link"},
    "country": {"country", "location", "region", "market", "geo", "nation"},
}

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
URL_RE = re.compile(r"^(https?://|www\.)|(\.[a-z]{2,}(/|$))", re.I)


def _map_headers(headers: list[str]) -> dict[int, str]:
    mapping = {}
    for i, h in enumerate(headers):
        key = (h or "").strip().lower()
        for field, names in ALIASES.items():
            if key in names and field not in mapping.values():
                mapping[i] = field
    return mapping


def _rows_from_xlsx(raw: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    for row in ws.iter_rows(values_only=True):
        yield ["" if c is None else str(c).strip() for c in row]


def _rows_from_csv(raw: bytes):
    text = raw.decode("utf-8-sig", errors="replace")
    for row in csv.reader(io.StringIO(text)):
        yield [c.strip() for c in row]


COUNTRIES = {
    "united states", "usa", "us", "united kingdom", "uk", "canada", "australia",
    "germany", "france", "spain", "italy", "netherlands", "sweden", "norway",
    "denmark", "switzerland", "austria", "ireland", "portugal", "poland",
    "uae", "united arab emirates", "saudi arabia", "qatar", "kuwait", "bahrain",
    "oman", "turkey", "egypt", "india", "pakistan", "bangladesh", "sri lanka",
    "china", "japan", "south korea", "singapore", "malaysia", "indonesia",
    "philippines", "thailand", "vietnam", "brazil", "mexico", "argentina",
    "chile", "colombia", "south africa", "nigeria", "kenya", "new zealand",
    "israel", "russia", "ukraine",
}


def _detect_by_pattern(cells: list[str]) -> dict:
    """Headerless fallback: find email/website/phone/country by pattern, then
    disambiguate person vs company by matching the email's local part."""
    lead = {"name": "", "email": "", "company": "", "title": "", "phone": "",
            "website": "", "country": ""}
    rest = []
    for c in cells:
        if not c:
            continue
        m = EMAIL_RE.search(c)
        if m and not lead["email"]:
            lead["email"] = m.group(0).lower()
        elif c.strip().lower() in COUNTRIES and not lead["country"]:
            lead["country"] = c.strip()
        elif URL_RE.search(c) and not lead["website"]:
            lead["website"] = c
        elif re.fullmatch(r"[+\d][\d\s()\-]{6,}", c) and not lead["phone"]:
            lead["phone"] = c
        else:
            rest.append(c)

    # Person name = the candidate sharing a token with the email local part
    # (john@acme.com -> "John Carter"); everything else -> company.
    local_tokens = set(re.split(r"[._\-\d]+", lead["email"].split("@")[0])) \
        if lead["email"] else set()
    local_tokens.discard("")
    for c in rest:
        toks = {w.lower() for w in c.split()}
        if local_tokens & toks and not lead["name"]:
            lead["name"] = c
        elif not lead["company"]:
            lead["company"] = c
        elif not lead["name"]:
            lead["name"] = c
    return lead


def parse_leads(filename: str, raw: bytes) -> list[dict]:
    rows = list(_rows_from_csv(raw) if filename.lower().endswith(".csv")
                else _rows_from_xlsx(raw))
    if not rows:
        return []

    mapping = _map_headers(rows[0])
    header_mode = "email" in mapping.values() or len(mapping) >= 2
    data_rows = rows[1:] if header_mode else rows

    leads, seen = [], set()
    for row in data_rows:
        if header_mode:
            lead = {"name": "", "email": "", "company": "", "title": "",
                    "phone": "", "website": "", "country": ""}
            for idx, field in mapping.items():
                if idx < len(row):
                    lead[field] = str(row[idx]).strip()
            if not lead["email"]:                      # rescue email anywhere in row
                for c in row:
                    m = EMAIL_RE.search(c or "")
                    if m:
                        lead["email"] = m.group(0).lower()
                        break
        else:
            lead = _detect_by_pattern(row)

        email = lead["email"].lower()
        if EMAIL_RE.fullmatch(email or "") and email not in seen:
            seen.add(email)
            lead["email"] = email
            leads.append(lead)
    return leads
