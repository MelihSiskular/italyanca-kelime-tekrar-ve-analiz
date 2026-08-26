#!/usr/bin/env python3
"""
Append-only CSV -> Supabase vocabulary sync.

Usage: 
    python sync_words.py

Expected CSV:
    data/Italyanca_Kelimeler.csv

Required .env values:
    SUPABASE_URL=https://YOUR_PROJECT.supabase.co
    SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_OR_SECRET_KEY

Important:
- Existing rows are never updated or deleted.
- CSV row order defines sequence_no.
- If an existing sequence_no points to a different Italian word, sync aborts.
- Empty optional fields are sent as NULL; Supabase computes is_ready automatically.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_DIR = Path(__file__).resolve().parent
CSV_PATH = PROJECT_DIR / "data" / "Italyanca_Kelimeler.csv"
ENV_PATH = PROJECT_DIR / ".env"

TABLE_NAME = "words"
FETCH_PAGE_SIZE = 1000
INSERT_BATCH_SIZE = 100

CSV_TO_DB = {
    "İtalyanca Kelime": "italian",
    "İngilizcesi": "english",
    "Türkçesi": "turkish",
    "İtalyanca Anlamı": "italian_definition",
    "İtalyanca Cümle -1": "example_1_it",
    "Cümle -1 Anlam": "example_1_meaning",
    "İtalyanca Cümle -2": "example_2_it",
    "Cümle -2 Anlam": "example_2_meaning",
}


def load_simple_env(path: Path) -> None:
    """Load a small .env file without requiring python-dotenv."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def normalize_word(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned if cleaned else None


def detect_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        sample = file.read(4096)

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        return dialect.delimiter
    except csv.Error:
        return ";"


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"CSV bulunamadı:\n{path}\n\n"
            "CSV_PATH değerini kontrol et."
        )

    delimiter = detect_delimiter(path)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=delimiter)

        if reader.fieldnames is None:
            raise ValueError("CSV başlık satırı okunamadı.")

        headers = [header.strip() for header in reader.fieldnames]
        missing = [name for name in CSV_TO_DB if name not in headers]

        if missing:
            raise ValueError(
                "CSV'de beklenen kolonlar eksik:\n- "
                + "\n- ".join(missing)
            )

        raw_rows = list(reader)

    rows: list[dict[str, Any]] = []
    seen_italian: dict[str, int] = {}

    for sequence_no, raw in enumerate(raw_rows, start=1):
        italian = optional_text(raw.get("İtalyanca Kelime"))

        if italian is None:
            raise ValueError(
                f"{sequence_no}. satırda İtalyanca Kelime boş. "
                "Sync durduruldu."
            )

        normalized = normalize_word(italian)

        if normalized in seen_italian:
            previous = seen_italian[normalized]
            raise ValueError(
                "CSV içinde duplicate İtalyanca kelime bulundu:\n"
                f"  satır {previous}: {italian}\n"
                f"  satır {sequence_no}: {italian}\n"
                "Sync durduruldu."
            )

        seen_italian[normalized] = sequence_no

        db_row: dict[str, Any] = {"sequence_no": sequence_no}

        for csv_column, db_column in CSV_TO_DB.items():
            value = optional_text(raw.get(csv_column))

            if db_column == "italian":
                db_row[db_column] = italian
            else:
                db_row[db_column] = value

        rows.append(db_row)

    return rows


class SupabaseREST:
    def __init__(self, url: str, key: str) -> None:
        self.base_url = url.rstrip("/")
        self.key = key

    @property
    def table_url(self) -> str:
        return f"{self.base_url}/rest/v1/{TABLE_NAME}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: Any | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
        }

        if extra_headers:
            headers.update(extra_headers)

        data = None

        if body is not None:
            data = json.dumps(
                body,
                ensure_ascii=False,
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            url=url,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=30) as response:
                response_headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                }
                return response.read(), response_headers

        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Supabase HTTP {exc.code} hatası:\n{error_body}"
            ) from exc

        except URLError as exc:
            raise RuntimeError(
                f"Supabase bağlantı hatası: {exc.reason}"
            ) from exc

    def fetch_existing_words(self) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        offset = 0

        while True:
            params = urlencode(
                {
                    "select": "sequence_no,italian",
                    "order": "sequence_no.asc",
                    "limit": FETCH_PAGE_SIZE,
                    "offset": offset,
                }
            )

            body, _ = self._request(
                "GET",
                f"{self.table_url}?{params}",
            )

            page = json.loads(body.decode("utf-8"))

            if not isinstance(page, list):
                raise RuntimeError(
                    "Supabase words yanıtı beklenen liste formatında değil."
                )

            all_rows.extend(page)

            if len(page) < FETCH_PAGE_SIZE:
                break

            offset += FETCH_PAGE_SIZE

        return all_rows

    def insert_words(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), INSERT_BATCH_SIZE):
            batch = rows[start : start + INSERT_BATCH_SIZE]

            self._request(
                "POST",
                self.table_url,
                body=batch,
                extra_headers={
                    "Prefer": "return=minimal",
                },
            )


def validate_against_database(
    csv_rows: list[dict[str, Any]],
    db_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    csv_by_sequence = {
        int(row["sequence_no"]): row
        for row in csv_rows
    }

    db_by_sequence = {
        int(row["sequence_no"]): row
        for row in db_rows
    }

    if db_by_sequence:
        max_db_sequence = max(db_by_sequence)

        if max_db_sequence > len(csv_rows):
            raise ValueError(
                "Supabase, bu CSV'den daha ileride görünüyor.\n"
                f"DB max sequence_no : {max_db_sequence}\n"
                f"CSV satır sayısı   : {len(csv_rows)}\n\n"
                "Daha eski bir CSV ile sync yapmaya çalışma."
            )

    mismatches: list[str] = []

    for sequence_no, db_row in db_by_sequence.items():
        csv_row = csv_by_sequence.get(sequence_no)

        if csv_row is None:
            mismatches.append(
                f"{sequence_no}: DB='{db_row.get('italian')}', CSV satırı yok"
            )
            continue

        db_italian = normalize_word(str(db_row.get("italian", "")))
        csv_italian = normalize_word(str(csv_row["italian"]))

        if db_italian != csv_italian:
            mismatches.append(
                f"{sequence_no}: "
                f"DB='{db_row.get('italian')}' "
                f"!= CSV='{csv_row['italian']}'"
            )

    if mismatches:
        preview = "\n".join(
            f"  - {item}" for item in mismatches[:10]
        )

        raise ValueError(
            "CSV'nin mevcut satır sırası Supabase ile uyuşmuyor.\n"
            "Bu genelde eski satırların arasına yeni kelime eklendiğinde olur.\n"
            "Mevcut sequence_no'ları kaydırmak word_progress ilişkilerini bozabilir.\n\n"
            f"İlk uyuşmazlıklar:\n{preview}\n\n"
            "Sync güvenlik amacıyla durduruldu. "
            "Yeni kelimeleri CSV'nin SONUNA ekle."
        )

    existing_sequences = set(db_by_sequence)

    new_rows = [
        row
        for row in csv_rows
        if int(row["sequence_no"]) not in existing_sequences
    ]

    # Extra protection against DB's case-insensitive Italian unique index.
    existing_italian = {
        normalize_word(str(row.get("italian", "")))
        for row in db_rows
    }

    conflicts = [
        row
        for row in new_rows
        if normalize_word(str(row["italian"])) in existing_italian
    ]

    if conflicts:
        names = ", ".join(
            str(row["italian"]) for row in conflicts[:10]
        )
        raise ValueError(
            "Yeni satırlarda Supabase'de zaten bulunan İtalyanca kelime var:\n"
            f"{names}\n"
            "Sync durduruldu."
        )

    return new_rows


def is_ready_source(row: dict[str, Any]) -> bool:
    return bool(
        optional_text(str(row.get("italian") or ""))
        and optional_text(str(row.get("english") or ""))
        and optional_text(str(row.get("turkish") or ""))
    )


def main() -> int:
    print("\n🇮🇹 Italian Vocabulary Sync")
    print("─" * 42)

    load_simple_env(ENV_PATH)

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        "",
    ).strip()

    if not supabase_url or not service_key:
        print(
            "❌ .env içinde aşağıdaki değerler gerekli:\n\n"
            "SUPABASE_URL=https://YOUR_PROJECT.supabase.co\n"
            "SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_OR_SECRET_KEY\n\n"
            "Secret/service-role key'i GitHub'a commit etme."
        )
        return 1

    try:
        csv_rows = load_csv_rows(CSV_PATH)

        client = SupabaseREST(
            supabase_url,
            service_key,
        )

        db_rows = client.fetch_existing_words()

        new_rows = validate_against_database(
            csv_rows,
            db_rows,
        )

        ready_new = sum(
            1 for row in new_rows if is_ready_source(row)
        )
        incomplete_new = len(new_rows) - ready_new

        print(f"CSV words       : {len(csv_rows)}")
        print(f"Database words  : {len(db_rows)}")
        print(f"New words       : {len(new_rows)}")

        if not new_rows:
            print("\n✅ Database is already up to date.")
            return 0

        print("\nYeni kelimeler:")
        for row in new_rows:
            readiness = "ready" if is_ready_source(row) else "incomplete"
            print(
                f"  {row['sequence_no']:>4}. "
                f"{row['italian']}  [{readiness}]"
            )

        print(
            f"\nReady           : {ready_new}\n"
            f"Incomplete      : {incomplete_new}"
        )

        client.insert_words(new_rows)

        # Verify after insert.
        db_after = client.fetch_existing_words()
        db_sequences_after = {
            int(row["sequence_no"])
            for row in db_after
        }

        missing_after = [
            int(row["sequence_no"])
            for row in new_rows
            if int(row["sequence_no"]) not in db_sequences_after
        ]

        if missing_after:
            raise RuntimeError(
                "Insert tamamlandı ancak doğrulamada bazı sequence_no "
                f"değerleri bulunamadı: {missing_after}"
            )

        print("\n" + "─" * 42)
        print(
            f"✅ {len(new_rows)} new word(s) uploaded."
        )
        print(
            f"✅ Database now contains {len(db_after)} word(s)."
        )

        if incomplete_new:
            print(
                f"ℹ️ {incomplete_new} yeni kelime English/Turkish "
                "alanları eksik olduğu için uygulamada is_ready=false kalacak."
            )

        return 0

    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"\n❌ Sync durduruldu:\n{exc}")
        return 1

    except KeyboardInterrupt:
        print("\n\n⚠️ Sync kullanıcı tarafından durduruldu.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
