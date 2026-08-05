#!/usr/bin/env python3
"""
İtalyanca Quiz Oturum Analiz Sistemi

Bu betik proje klasöründeki:
    sessions/*_attempts.csv
    sessions/*_summary.csv
    failed/*_failed.csv

dosyalarını okur ve analysis_reports klasörüne şu çıktıları üretir:

    en_zor_kelimeler.csv
    en_sik_hata_turleri.csv
    en_cok_karistirilan_kelime_ciftleri.csv
    tarihsel_gelisim.csv
    tarihsel_gelisim_gunluk.csv
    analiz_raporu.md

Matplotlib kuruluysa ayrıca PNG grafikler oluşturur.

Kullanım:
    python italian_quiz_analyzer.py

Farklı proje klasörü:
    python italian_quiz_analyzer.py --project-dir "/proje/klasoru"

Grafikleri kapatmak:
    python italian_quiz_analyzer.py --no-charts

Gerekli paket:
    pip install pandas

İsteğe bağlı grafik paketi:
    pip install matplotlib
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


ERROR_LABELS = {
    "correct": "Doğru",
    "spelling_error": "Yazım hatası",
    "confused_with_another_word": "Başka kelimeyle karıştırma",
    "wrong_word_form": "Yanlış/çekimli kelime biçimi",
    "no_recall": "Hatırlayamama / boş cevap",
    "unknown_or_semantic_error": "Bilinmeyen veya anlamsal hata",
}

ERROR_COLUMNS = {
    "spelling_error": "spelling_error_count",
    "confused_with_another_word": "confusion_count",
    "wrong_word_form": "wrong_word_form_count",
    "no_recall": "no_recall_count",
    "unknown_or_semantic_error": "unknown_semantic_error_count",
}

VALID_ERROR_TYPES = set(ERROR_LABELS)

# Mastar yerine çekimli biçim yazıldığında kullanılacak temel sözlük.
# Yeni fiiller öğrenildikçe genişletilebilir.
WORD_FORMS = {
    "volere": {
        "voglio", "vuoi", "vuole", "vogliamo", "volete", "vogliono"
    },
    "potere": {
        "posso", "puoi", "può", "possiamo", "potete", "possono"
    },
    "dovere": {
        "devo", "devi", "deve", "dobbiamo", "dovete", "devono"
    },
    "essere": {
        "sono", "sei", "è", "siamo", "siete"
    },
    "avere": {
        "ho", "hai", "ha", "abbiamo", "avete", "hanno"
    },
    "andare": {
        "vado", "vai", "va", "andiamo", "andate", "vanno"
    },
    "fare": {
        "faccio", "fai", "fa", "facciamo", "fate", "fanno"
    },
    "venire": {
        "vengo", "vieni", "viene", "veniamo", "venite", "vengono"
    },
    "bere": {
        "bevo", "bevi", "beve", "beviamo", "bevete", "bevono"
    },
    "dire": {
        "dico", "dici", "dice", "diciamo", "dite", "dicono"
    },
    "uscire": {
        "esco", "esci", "esce", "usciamo", "uscite", "escono"
    },
    "sapere": {
        "so", "sai", "sa", "sappiamo", "sapete", "sanno"
    },
}

FILENAME_DATE_PATTERN = re.compile(
    r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})_"
    r"(?P<hour>\d{2})\.(?P<minute>\d{2})\.(?P<second>\d{2})"
)


def clean_text(value: Any) -> str:
    """NaN değerlerini ve gereksiz boşlukları temizler."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def normalize_text(value: Any) -> str:
    """Karşılaştırma için metni küçük harfe ve tek boşluğa dönüştürür."""
    return " ".join(clean_text(value).casefold().split())


def parse_bool(value: Any) -> bool:
    """CSV içindeki farklı doğru/yanlış gösterimlerini bool'a dönüştürür."""
    if isinstance(value, bool):
        return value

    normalized = normalize_text(value)

    return normalized in {
        "true", "1", "yes", "evet", "doğru", "dogru"
    }


def safe_number(value: Any, default: float = 0.0) -> float:
    """Sayısal olmayan veya boş değerlerde varsayılan değer döndürür."""
    try:
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def read_csv_flexible(file_path: Path) -> pd.DataFrame:
    """
    CSV dosyasını önce noktalı virgül, sonra virgül ile okumayı dener.
    Tüm sütun adlarını temizler.
    """
    last_error: Exception | None = None

    for separator in (";", ","):
        try:
            frame = pd.read_csv(
                file_path,
                sep=separator,
                encoding="utf-8-sig",
                dtype=str,
                keep_default_na=False,
            )
            frame.columns = frame.columns.str.strip()

            # Yanlış ayraç seçildiyse genellikle tek sütun oluşur.
            if len(frame.columns) > 1:
                return frame
        except Exception as exc:
            last_error = exc

    raise ValueError(
        f"CSV okunamadı: {file_path}\n"
        f"Son hata: {last_error}"
    )


def infer_datetime_from_filename(file_path: Path) -> pd.Timestamp:
    """20.07.2026_14.07.27 biçimindeki dosya adından tarih çıkarır."""
    match = FILENAME_DATE_PATTERN.search(file_path.name)

    if not match:
        return pd.NaT

    parts = {key: int(value) for key, value in match.groupdict().items()}

    return pd.Timestamp(
        year=parts["year"],
        month=parts["month"],
        day=parts["day"],
        hour=parts["hour"],
        minute=parts["minute"],
        second=parts["second"],
    )


def infer_session_id(file_path: Path) -> str:
    """Dosya adından YYYYMMDD_HHMMSS biçiminde session_id üretir."""
    timestamp = infer_datetime_from_filename(file_path)

    if pd.isna(timestamp):
        return file_path.stem

    return timestamp.strftime("%Y%m%d_%H%M%S")


def normalize_forms_dictionary(
    forms_dictionary: dict[str, set[str]]
) -> dict[str, set[str]]:
    return {
        normalize_text(lemma): {
            normalize_text(form) for form in forms
        }
        for lemma, forms in forms_dictionary.items()
    }


NORMALIZED_WORD_FORMS = normalize_forms_dictionary(WORD_FORMS)


def looks_like_regular_verb_form(
    user_answer: str,
    correct_answer: str,
) -> bool:
    """
    Düzenli -are, -ere ve -ire fiillerinin yaygın çekimlerini
    yaklaşık olarak tespit eder.
    """
    answer = normalize_text(user_answer)
    lemma = normalize_text(correct_answer)

    if not lemma.endswith(("are", "ere", "ire")) or len(lemma) <= 4:
        return False

    stem = lemma[:-3]

    if not answer.startswith(stem):
        return False

    suffix = answer[len(stem):]

    common_endings = {
        "o", "i", "a", "e",
        "iamo", "ate", "ete", "ite", "ano", "ono",
        "isco", "isci", "isce", "iscono",
        "ato", "uto", "ito",
        "ando", "endo",
    }

    return suffix in common_endings


def classify_answer(
    user_answer: str,
    correct_answer: str,
    italian_word_lookup: dict[str, str],
) -> tuple[str, float, str]:
    """
    Yanlış cevabı otomatik sınıflandırır.

    Dönüş:
        error_type, similarity_score, confused_with
    """
    normalized_user = normalize_text(user_answer)
    normalized_correct = normalize_text(correct_answer)

    if not normalized_user:
        return "no_recall", 0.0, ""

    if normalized_user == normalized_correct:
        return "correct", 1.0, ""

    similarity_score = SequenceMatcher(
        None,
        normalized_user,
        normalized_correct,
    ).ratio()

    known_forms = NORMALIZED_WORD_FORMS.get(
        normalized_correct,
        set(),
    )

    if normalized_user in known_forms:
        return "wrong_word_form", round(similarity_score, 3), ""

    if looks_like_regular_verb_form(user_answer, correct_answer):
        return "wrong_word_form", round(similarity_score, 3), ""

    if normalized_user in italian_word_lookup:
        return (
            "confused_with_another_word",
            round(similarity_score, 3),
            italian_word_lookup[normalized_user],
        )

    if similarity_score >= 0.75:
        return "spelling_error", round(similarity_score, 3), ""

    return (
        "unknown_or_semantic_error",
        round(similarity_score, 3),
        "",
    )


def collect_files(folder: Path, suffix: str) -> list[Path]:
    """Klasördeki ilgili CSV dosyalarını tarih sırasına dizer."""
    files = list(folder.rglob(f"*_{suffix}.csv"))

    return sorted(
        files,
        key=lambda path: (
            infer_datetime_from_filename(path)
            if not pd.isna(infer_datetime_from_filename(path))
            else pd.Timestamp.max
        ),
    )


def load_attempts(files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for file_path in files:
        frame = read_csv_flexible(file_path)

        if "session_id" not in frame.columns:
            frame["session_id"] = infer_session_id(file_path)

        frame["source_file"] = file_path.name
        frame["source_datetime"] = infer_datetime_from_filename(file_path)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    attempts = pd.concat(frames, ignore_index=True, sort=False)

    required_defaults = {
        "session_id": "",
        "answered_at": "",
        "attempt_order": "",
        "italian_word": "",
        "clue_language": "",
        "clue_column": "",
        "clue": "",
        "user_answer": "",
        "is_correct": False,
        "task_attempt_number": 1,
        "is_first_try_correct": False,
        "error_type": "",
        "similarity_score": "",
        "confused_with": "",
    }

    for column, default in required_defaults.items():
        if column not in attempts.columns:
            attempts[column] = default

    attempts["italian_word"] = attempts["italian_word"].map(clean_text)
    attempts["word_key"] = attempts["italian_word"].map(normalize_text)
    attempts["user_answer"] = attempts["user_answer"].map(clean_text)
    attempts["is_correct"] = attempts["is_correct"].map(parse_bool)
    attempts["is_first_try_correct"] = attempts[
        "is_first_try_correct"
    ].map(parse_bool)

    attempts["task_attempt_number"] = pd.to_numeric(
        attempts["task_attempt_number"],
        errors="coerce",
    ).fillna(1).astype(int)

    attempts["attempt_order"] = pd.to_numeric(
        attempts["attempt_order"],
        errors="coerce",
    )

    attempts["answered_at"] = pd.to_datetime(
        attempts["answered_at"],
        errors="coerce",
    )

    return attempts


def load_summaries(files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for file_path in files:
        frame = read_csv_flexible(file_path)

        if "session_id" not in frame.columns:
            frame["session_id"] = infer_session_id(file_path)

        frame["source_file"] = file_path.name
        frame["source_datetime"] = infer_datetime_from_filename(file_path)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    summaries = pd.concat(frames, ignore_index=True, sort=False)

    for column in ("started_at", "ended_at"):
        if column not in summaries.columns:
            summaries[column] = ""
        summaries[column] = pd.to_datetime(
            summaries[column],
            errors="coerce",
        )

    return summaries


def load_failed(files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for file_path in files:
        frame = read_csv_flexible(file_path)
        frame["source_file"] = file_path.name
        frame["session_id"] = infer_session_id(file_path)
        frame["source_datetime"] = infer_datetime_from_filename(file_path)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True, sort=False)


def find_vocabulary_words(
    project_dir: Path,
    attempts: pd.DataFrame,
    failed: pd.DataFrame,
) -> dict[str, str]:
    """
    Bilinen İtalyanca kelimeleri attempts, failed ve proje kökündeki
    kelime CSV'sinden toplar.
    """
    words: dict[str, str] = {}

    if not attempts.empty and "italian_word" in attempts.columns:
        for word in attempts["italian_word"]:
            cleaned = clean_text(word)
            if cleaned:
                words[normalize_text(cleaned)] = cleaned

    if not failed.empty and "İtalyanca Kelime" in failed.columns:
        for word in failed["İtalyanca Kelime"]:
            cleaned = clean_text(word)
            if cleaned:
                words[normalize_text(cleaned)] = cleaned

    for csv_path in project_dir.glob("*.csv"):
        filename = csv_path.name.casefold()

        if "talyanca" not in filename or "kelime" not in filename:
            continue

        try:
            vocabulary = read_csv_flexible(csv_path)
        except Exception:
            continue

        if "İtalyanca Kelime" not in vocabulary.columns:
            continue

        for word in vocabulary["İtalyanca Kelime"]:
            cleaned = clean_text(word)
            if cleaned:
                words[normalize_text(cleaned)] = cleaned

    return words


def enrich_error_classification(
    attempts: pd.DataFrame,
    italian_word_lookup: dict[str, str],
) -> pd.DataFrame:
    """
    Yeni dosyalardaki hata sınıflarını korur.
    Eski veya eksik kayıtlarda sınıflandırmayı yeniden yapar.
    """
    if attempts.empty:
        return attempts

    enriched = attempts.copy()

    error_types: list[str] = []
    similarity_scores: list[float] = []
    confused_words: list[str] = []

    for row in enriched.itertuples(index=False):
        is_correct = bool(row.is_correct)
        existing_type = clean_text(getattr(row, "error_type", ""))
        existing_confused = clean_text(
            getattr(row, "confused_with", "")
        )
        existing_similarity = safe_number(
            getattr(row, "similarity_score", ""),
            default=-1.0,
        )

        if is_correct:
            error_types.append("correct")
            similarity_scores.append(1.0)
            confused_words.append("")
            continue

        if existing_type in VALID_ERROR_TYPES and existing_type != "correct":
            error_types.append(existing_type)
            similarity_scores.append(
                existing_similarity if existing_similarity >= 0 else 0.0
            )
            confused_words.append(existing_confused)
            continue

        error_type, similarity, confused_with = classify_answer(
            user_answer=clean_text(row.user_answer),
            correct_answer=clean_text(row.italian_word),
            italian_word_lookup=italian_word_lookup,
        )

        error_types.append(error_type)
        similarity_scores.append(similarity)
        confused_words.append(confused_with)

    enriched["error_type"] = error_types
    enriched["error_type_tr"] = enriched["error_type"].map(ERROR_LABELS)
    enriched["similarity_score"] = similarity_scores
    enriched["confused_with"] = confused_words

    return enriched


def build_hardest_words(attempts: pd.DataFrame) -> pd.DataFrame:
    """
    Kelime bazında hata yoğunluğunu ve hata ciddiyetini birleştirir.

    Zorluk puanı:
        %45 yanlış oranı
        %20 hatırlayamama oranı
        %15 bilinmeyen/anlamsal hata oranı
        %10 karıştırma oranı
        %5 yazım hatası oranı
        %5 tekrar denemesi oranı
    """
    if attempts.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []

    for word_key, group in attempts.groupby("word_key", dropna=False):
        if not word_key:
            continue

        wrong = group[~group["is_correct"]]
        first_attempts = group[group["task_attempt_number"] == 1]

        total_attempts = len(group)
        wrong_count = len(wrong)
        correct_count = int(group["is_correct"].sum())
        repeated_attempts = int((group["task_attempt_number"] > 1).sum())

        wrong_rate = (
            wrong_count / total_attempts if total_attempts else 0.0
        )

        wrong_denominator = max(wrong_count, 1)

        counts = {
            error_type: int(
                (wrong["error_type"] == error_type).sum()
            )
            for error_type in ERROR_COLUMNS
        }

        ratios = {
            error_type: count / wrong_denominator
            for error_type, count in counts.items()
        }

        repeated_ratio = (
            repeated_attempts / total_attempts
            if total_attempts
            else 0.0
        )

        difficulty_score = 100 * (
            0.45 * wrong_rate
            + 0.20 * ratios["no_recall"]
            + 0.15 * ratios["unknown_or_semantic_error"]
            + 0.10 * ratios["confused_with_another_word"]
            + 0.05 * ratios["spelling_error"]
            + 0.05 * repeated_ratio
        )

        first_try_accuracy = (
            first_attempts["is_correct"].mean() * 100
            if len(first_attempts)
            else 0.0
        )

        sessions_seen = group["session_id"].nunique()
        days_seen = group["answered_at"].dropna().dt.date.nunique()

        recommendation = make_recommendation(counts)

        rows.append({
            "italian_word": clean_text(group["italian_word"].iloc[0]),
            "difficulty_score": round(difficulty_score, 2),
            "total_attempts": total_attempts,
            "correct_answers": correct_count,
            "wrong_answers": wrong_count,
            "wrong_rate_percent": round(wrong_rate * 100, 2),
            "first_try_accuracy_percent": round(
                first_try_accuracy,
                2,
            ),
            "repeated_attempts": repeated_attempts,
            "sessions_seen": sessions_seen,
            "different_days_seen": days_seen,
            "spelling_error_count": counts["spelling_error"],
            "confusion_count": counts[
                "confused_with_another_word"
            ],
            "wrong_word_form_count": counts["wrong_word_form"],
            "no_recall_count": counts["no_recall"],
            "unknown_semantic_error_count": counts[
                "unknown_or_semantic_error"
            ],
            "recommended_study": recommendation,
        })

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    return result.sort_values(
        by=[
            "difficulty_score",
            "wrong_answers",
            "no_recall_count",
            "confusion_count",
        ],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def make_recommendation(counts: dict[str, int]) -> str:
    """Kelimenin baskın hata türüne göre kısa çalışma önerisi üretir."""
    if not any(counts.values()):
        return "Güçlü; normal tekrar yeterli"

    priority = [
        ("no_recall", "Öncelikli aktif hatırlama tekrarı"),
        (
            "unknown_or_semantic_error",
            "Anlamı ve örnek cümleyi yeniden çalış",
        ),
        (
            "confused_with_another_word",
            "Karıştırılan kelimeyle karşılaştırmalı çalış",
        ),
        (
            "wrong_word_form",
            "Mastar ve çekimli biçimleri birlikte çalış",
        ),
        ("spelling_error", "Yazım ve harf dizilimi çalışması"),
    ]

    dominant_error = max(
        priority,
        key=lambda item: counts[item[0]],
    )

    return dominant_error[1]


def build_error_types(attempts: pd.DataFrame) -> pd.DataFrame:
    """Yanlış cevapların hata türlerine göre genel dağılımını çıkarır."""
    if attempts.empty:
        return pd.DataFrame()

    wrong = attempts[~attempts["is_correct"]].copy()

    if wrong.empty:
        return pd.DataFrame(
            columns=[
                "error_type",
                "error_type_tr",
                "error_count",
                "percentage_of_errors",
                "unique_words",
                "sessions",
            ]
        )

    rows: list[dict[str, Any]] = []
    total_errors = len(wrong)

    for error_type, group in wrong.groupby("error_type"):
        rows.append({
            "error_type": error_type,
            "error_type_tr": ERROR_LABELS.get(
                error_type,
                error_type,
            ),
            "error_count": len(group),
            "percentage_of_errors": round(
                len(group) / total_errors * 100,
                2,
            ),
            "unique_words": group["word_key"].nunique(),
            "sessions": group["session_id"].nunique(),
        })

    return pd.DataFrame(rows).sort_values(
        by=["error_count", "unique_words"],
        ascending=[False, False],
    ).reset_index(drop=True)


def build_confusion_pairs(attempts: pd.DataFrame) -> pd.DataFrame:
    """
    A yerine B ve B yerine A karıştırmalarını aynı çiftte birleştirir.
    """
    if attempts.empty:
        return pd.DataFrame()

    confused = attempts[
        (attempts["error_type"] == "confused_with_another_word")
        & (attempts["confused_with"].map(clean_text) != "")
    ].copy()

    if confused.empty:
        return pd.DataFrame(
            columns=[
                "word_1",
                "word_2",
                "total_confusions",
                "word_1_instead_of_word_2",
                "word_2_instead_of_word_1",
                "sessions",
                "last_confused_at",
            ]
        )

    pair_rows: list[dict[str, Any]] = []

    for row in confused.itertuples(index=False):
        correct = clean_text(row.italian_word)
        answered = clean_text(row.confused_with)

        ordered = sorted(
            [correct, answered],
            key=lambda value: normalize_text(value),
        )

        pair_rows.append({
            "word_1": ordered[0],
            "word_2": ordered[1],
            "correct_word": correct,
            "answered_word": answered,
            "session_id": row.session_id,
            "answered_at": row.answered_at,
        })

    pairs = pd.DataFrame(pair_rows)
    result_rows: list[dict[str, Any]] = []

    for (word_1, word_2), group in pairs.groupby(
        ["word_1", "word_2"]
    ):
        word_1_instead_of_word_2 = int(
            (
                (group["correct_word"] == word_2)
                & (group["answered_word"] == word_1)
            ).sum()
        )

        word_2_instead_of_word_1 = int(
            (
                (group["correct_word"] == word_1)
                & (group["answered_word"] == word_2)
            ).sum()
        )

        last_confused = group["answered_at"].max()

        result_rows.append({
            "word_1": word_1,
            "word_2": word_2,
            "total_confusions": len(group),
            "word_1_instead_of_word_2":
                word_1_instead_of_word_2,
            "word_2_instead_of_word_1":
                word_2_instead_of_word_1,
            "sessions": group["session_id"].nunique(),
            "last_confused_at": (
                last_confused.isoformat()
                if not pd.isna(last_confused)
                else ""
            ),
        })

    return pd.DataFrame(result_rows).sort_values(
        by=["total_confusions", "sessions"],
        ascending=[False, False],
    ).reset_index(drop=True)


def build_history(
    attempts: pd.DataFrame,
    summaries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Her oturum için doğruluk, ilk deneme başarısı, süre ve hata türlerini
    tek tabloda birleştirir.
    """
    session_ids = set()

    if not attempts.empty:
        session_ids.update(
            attempts["session_id"].dropna().astype(str)
        )

    if not summaries.empty:
        session_ids.update(
            summaries["session_id"].dropna().astype(str)
        )

    rows: list[dict[str, Any]] = []

    for session_id in session_ids:
        session_attempts = (
            attempts[attempts["session_id"].astype(str) == session_id]
            if not attempts.empty
            else pd.DataFrame()
        )

        session_summary = (
            summaries[
                summaries["session_id"].astype(str) == session_id
            ]
            if not summaries.empty
            else pd.DataFrame()
        )

        summary_row = (
            session_summary.iloc[-1]
            if not session_summary.empty
            else None
        )

        started_at = (
            summary_row.get("started_at")
            if summary_row is not None
            else pd.NaT
        )
        ended_at = (
            summary_row.get("ended_at")
            if summary_row is not None
            else pd.NaT
        )

        if pd.isna(started_at) and not session_attempts.empty:
            started_at = session_attempts["answered_at"].min()

        if pd.isna(ended_at) and not session_attempts.empty:
            ended_at = session_attempts["answered_at"].max()

        total_attempts = (
            int(safe_number(summary_row.get("total_attempts")))
            if summary_row is not None
            and safe_number(summary_row.get("total_attempts")) > 0
            else len(session_attempts)
        )

        correct_answers = (
            int(safe_number(summary_row.get("correct_answers")))
            if summary_row is not None
            and clean_text(summary_row.get("correct_answers")) != ""
            else int(session_attempts["is_correct"].sum())
            if not session_attempts.empty
            else 0
        )

        wrong_answers = (
            int(safe_number(summary_row.get("wrong_answers")))
            if summary_row is not None
            and clean_text(summary_row.get("wrong_answers")) != ""
            else total_attempts - correct_answers
        )

        total_tasks = (
            int(safe_number(summary_row.get("total_language_tasks")))
            if summary_row is not None
            else 0
        )

        first_try_correct = (
            int(
                safe_number(
                    summary_row.get("first_try_correct_tasks")
                )
            )
            if summary_row is not None
            and clean_text(
                summary_row.get("first_try_correct_tasks")
            ) != ""
            else int(
                session_attempts["is_first_try_correct"].sum()
            )
            if not session_attempts.empty
            else 0
        )

        accuracy = (
            correct_answers / total_attempts * 100
            if total_attempts
            else 0.0
        )

        first_try_accuracy = (
            first_try_correct / total_tasks * 100
            if total_tasks
            else (
                session_attempts[
                    session_attempts["task_attempt_number"] == 1
                ]["is_correct"].mean() * 100
                if not session_attempts.empty
                and (
                    session_attempts["task_attempt_number"] == 1
                ).any()
                else 0.0
            )
        )

        duration_seconds = 0

        if (
            summary_row is not None
            and clean_text(summary_row.get("duration_seconds")) != ""
        ):
            duration_seconds = int(
                safe_number(summary_row.get("duration_seconds"))
            )
        elif not pd.isna(started_at) and not pd.isna(ended_at):
            duration_seconds = max(
                0,
                int((ended_at - started_at).total_seconds()),
            )

        error_counts = {
            error_type: 0 for error_type in ERROR_COLUMNS
        }

        if not session_attempts.empty:
            for error_type in error_counts:
                error_counts[error_type] = int(
                    (
                        session_attempts["error_type"]
                        == error_type
                    ).sum()
                )

        rows.append({
            "session_id": session_id,
            "date": (
                started_at.date().isoformat()
                if not pd.isna(started_at)
                else ""
            ),
            "started_at": (
                started_at.isoformat()
                if not pd.isna(started_at)
                else ""
            ),
            "ended_at": (
                ended_at.isoformat()
                if not pd.isna(ended_at)
                else ""
            ),
            "duration_seconds": duration_seconds,
            "duration_minutes": round(
                duration_seconds / 60,
                2,
            ),
            "total_unique_words": (
                int(
                    safe_number(
                        summary_row.get("total_unique_words")
                    )
                )
                if summary_row is not None
                else session_attempts["word_key"].nunique()
                if not session_attempts.empty
                else 0
            ),
            "total_language_tasks": total_tasks,
            "total_attempts": total_attempts,
            "correct_answers": correct_answers,
            "wrong_answers": wrong_answers,
            "accuracy_percent": round(accuracy, 2),
            "first_try_correct_tasks": first_try_correct,
            "first_try_accuracy_percent": round(
                first_try_accuracy,
                2,
            ),
            "average_attempts_per_task": round(
                total_attempts / total_tasks,
                3,
            ) if total_tasks else 0.0,
            "words_with_mistakes": (
                session_attempts.loc[
                    ~session_attempts["is_correct"],
                    "word_key",
                ].nunique()
                if not session_attempts.empty
                else 0
            ),
            "spelling_errors": error_counts["spelling_error"],
            "confusion_errors": error_counts[
                "confused_with_another_word"
            ],
            "wrong_word_form_errors": error_counts[
                "wrong_word_form"
            ],
            "no_recall_errors": error_counts["no_recall"],
            "unknown_semantic_errors": error_counts[
                "unknown_or_semantic_error"
            ],
        })

    history = pd.DataFrame(rows)

    if history.empty:
        return history

    history["_sort_date"] = pd.to_datetime(
        history["started_at"],
        errors="coerce",
    )

    history = history.sort_values(
        ["_sort_date", "session_id"]
    ).reset_index(drop=True)

    history["accuracy_change_vs_previous"] = (
        history["accuracy_percent"].diff().round(2)
    )

    history["first_try_change_vs_previous"] = (
        history["first_try_accuracy_percent"].diff().round(2)
    )

    history["accuracy_3_session_average"] = (
        history["accuracy_percent"]
        .rolling(window=3, min_periods=1)
        .mean()
        .round(2)
    )

    # Tarih boyunca karşılaşılan benzersiz kelimelerin kümülatif sayısı.
    cumulative_words: set[str] = set()
    cumulative_counts: list[int] = []

    for session_id in history["session_id"]:
        if not attempts.empty:
            session_words = attempts.loc[
                attempts["session_id"].astype(str) == str(session_id),
                "word_key",
            ]
            cumulative_words.update(
                word for word in session_words if word
            )

        cumulative_counts.append(len(cumulative_words))

    history["cumulative_unique_words_seen"] = cumulative_counts

    return history.drop(columns="_sort_date")


def build_daily_history(history: pd.DataFrame) -> pd.DataFrame:
    """Birden fazla oturumu aynı gün bazında birleştirir."""
    if history.empty:
        return pd.DataFrame()

    numeric_sum_columns = [
        "duration_seconds",
        "duration_minutes",
        "total_language_tasks",
        "total_attempts",
        "correct_answers",
        "wrong_answers",
        "first_try_correct_tasks",
        "words_with_mistakes",
        "spelling_errors",
        "confusion_errors",
        "wrong_word_form_errors",
        "no_recall_errors",
        "unknown_semantic_errors",
    ]

    grouped = history.groupby("date", as_index=False).agg({
        "session_id": "nunique",
        "total_unique_words": "max",
        "cumulative_unique_words_seen": "max",
        **{column: "sum" for column in numeric_sum_columns},
    })

    grouped = grouped.rename(
        columns={"session_id": "session_count"}
    )

    grouped["accuracy_percent"] = (
        grouped["correct_answers"]
        / grouped["total_attempts"].replace(0, pd.NA)
        * 100
    ).fillna(0).round(2)

    grouped["first_try_accuracy_percent"] = (
        grouped["first_try_correct_tasks"]
        / grouped["total_language_tasks"].replace(0, pd.NA)
        * 100
    ).fillna(0).round(2)

    grouped["accuracy_change_vs_previous_day"] = (
        grouped["accuracy_percent"].diff().round(2)
    )

    return grouped.sort_values("date").reset_index(drop=True)


def markdown_table(
    frame: pd.DataFrame,
    columns: list[str],
    headers: list[str],
    limit: int = 10,
) -> str:
    """Ek paket gerektirmeden küçük Markdown tablosu üretir."""
    if frame.empty:
        return "_Veri bulunamadı._"

    selected = frame.loc[:, columns].head(limit).copy()

    def format_value(value: Any) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value).replace("|", "\\|")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for row in selected.itertuples(index=False, name=None):
        lines.append(
            "| "
            + " | ".join(format_value(value) for value in row)
            + " |"
        )

    return "\n".join(lines)


def build_markdown_report(
    attempts: pd.DataFrame,
    failed: pd.DataFrame,
    hardest_words: pd.DataFrame,
    error_types: pd.DataFrame,
    confusion_pairs: pd.DataFrame,
    history: pd.DataFrame,
) -> str:
    generated_at = datetime.now()

    total_sessions = (
        history["session_id"].nunique()
        if not history.empty
        else 0
    )
    total_attempts = len(attempts)
    total_correct = (
        int(attempts["is_correct"].sum())
        if not attempts.empty
        else 0
    )
    total_wrong = total_attempts - total_correct
    overall_accuracy = (
        total_correct / total_attempts * 100
        if total_attempts
        else 0.0
    )
    unique_words = (
        attempts["word_key"].nunique()
        if not attempts.empty
        else 0
    )

    first_date = (
        history["date"].iloc[0]
        if not history.empty
        else "-"
    )
    last_date = (
        history["date"].iloc[-1]
        if not history.empty
        else "-"
    )

    lines = [
        "# İtalyanca Quiz Analiz Raporu",
        "",
        f"**Oluşturulma zamanı:** {generated_at:%d.%m.%Y %H:%M:%S}",
        "",
        "## Genel özet",
        "",
        f"- İncelenen tarih aralığı: **{first_date} – {last_date}**",
        f"- Oturum sayısı: **{total_sessions}**",
        f"- Karşılaşılan benzersiz kelime: **{unique_words}**",
        f"- Toplam cevap denemesi: **{total_attempts}**",
        f"- Doğru cevap: **{total_correct}**",
        f"- Yanlış cevap: **{total_wrong}**",
        f"- Genel doğruluk: **%{overall_accuracy:.2f}**",
        f"- Okunan failed kaydı: **{len(failed)}**",
        "",
        "## En zor kelimeler",
        "",
        markdown_table(
            hardest_words[
                hardest_words["wrong_answers"] > 0
            ] if not hardest_words.empty else hardest_words,
            columns=[
                "italian_word",
                "difficulty_score",
                "wrong_answers",
                "wrong_rate_percent",
                "first_try_accuracy_percent",
                "recommended_study",
            ],
            headers=[
                "Kelime",
                "Zorluk",
                "Yanlış",
                "Yanlış %",
                "İlk deneme %",
                "Öneri",
            ],
            limit=15,
        ),
        "",
        "## En sık yapılan hata türleri",
        "",
        markdown_table(
            error_types,
            columns=[
                "error_type_tr",
                "error_count",
                "percentage_of_errors",
                "unique_words",
            ],
            headers=[
                "Hata türü",
                "Sayı",
                "Hatalardaki payı %",
                "Etkilenen kelime",
            ],
            limit=10,
        ),
        "",
        "## En çok karıştırılan kelime çiftleri",
        "",
        markdown_table(
            confusion_pairs,
            columns=[
                "word_1",
                "word_2",
                "total_confusions",
                "word_1_instead_of_word_2",
                "word_2_instead_of_word_1",
            ],
            headers=[
                "Kelime 1",
                "Kelime 2",
                "Toplam",
                "1, 2 yerine",
                "2, 1 yerine",
            ],
            limit=15,
        ),
        "",
        "## Tarihsel gelişim",
        "",
        markdown_table(
            history,
            columns=[
                "date",
                "duration_minutes",
                "total_attempts",
                "accuracy_percent",
                "first_try_accuracy_percent",
                "wrong_answers",
            ],
            headers=[
                "Tarih",
                "Süre (dk)",
                "Deneme",
                "Doğruluk %",
                "İlk deneme %",
                "Yanlış",
            ],
            limit=50,
        ),
        "",
    ]

    if len(history) >= 2:
        first = history.iloc[0]
        last = history.iloc[-1]

        accuracy_change = (
            last["accuracy_percent"]
            - first["accuracy_percent"]
        )
        first_try_change = (
            last["first_try_accuracy_percent"]
            - first["first_try_accuracy_percent"]
        )

        lines.extend([
            "### İlk ve son oturum karşılaştırması",
            "",
            (
                f"- Doğruluk değişimi: "
                f"**{accuracy_change:+.2f} puan**"
            ),
            (
                f"- İlk deneme başarısı değişimi: "
                f"**{first_try_change:+.2f} puan**"
            ),
            (
                f"- Kümülatif görülen kelime: "
                f"**{int(last['cumulative_unique_words_seen'])}**"
            ),
            "",
        ])
    else:
        lines.extend([
            "Henüz yalnızca bir oturum bulunduğu için uzun dönemli "
            "gelişim karşılaştırması yapılamadı.",
            "",
        ])

    lines.extend([
        "## Zorluk puanı nasıl hesaplanıyor?",
        "",
        "Zorluk puanı; yanlış oranı, hatırlayamama, anlamsal hata, "
        "başka kelimeyle karıştırma, yazım hatası ve tekrar denemelerini "
        "birleştiren 0–100 arası bir öncelik puanıdır. Puan yüksekse "
        "kelime tekrar çalışmada daha öne alınmalıdır.",
        "",
        "Eski attempts dosyalarında `error_type` bulunmuyorsa betik "
        "cevapları otomatik olarak yeniden sınıflandırır.",
        "",
    ])

    return "\n".join(lines)


def create_charts(
    output_dir: Path,
    hardest_words: pd.DataFrame,
    error_types: pd.DataFrame,
    history: pd.DataFrame,
) -> list[Path]:
    """
    Matplotlib varsa üç ayrı grafik üretir.
    Kurulu değilse analiz CSV ve Markdown çıktıları yine oluşturulur.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "ℹ️ Matplotlib kurulu değil; grafikler atlandı. "
            "İstersen: pip install matplotlib"
        )
        return []

    created: list[Path] = []

    if not hardest_words.empty:
        chart_data = hardest_words[
            hardest_words["wrong_answers"] > 0
        ].head(12).sort_values("difficulty_score")

        if not chart_data.empty:
            plt.figure(figsize=(10, 7))
            plt.barh(
                chart_data["italian_word"],
                chart_data["difficulty_score"],
            )
            plt.xlabel("Zorluk puanı")
            plt.ylabel("İtalyanca kelime")
            plt.title("En Zor Kelimeler")
            plt.tight_layout()

            path = output_dir / "en_zor_kelimeler.png"
            plt.savefig(path, dpi=160)
            plt.close()
            created.append(path)

    if not error_types.empty:
        chart_data = error_types.sort_values("error_count")

        plt.figure(figsize=(10, 6))
        plt.barh(
            chart_data["error_type_tr"],
            chart_data["error_count"],
        )
        plt.xlabel("Hata sayısı")
        plt.ylabel("Hata türü")
        plt.title("Hata Türlerinin Dağılımı")
        plt.tight_layout()

        path = output_dir / "hata_turleri.png"
        plt.savefig(path, dpi=160)
        plt.close()
        created.append(path)

    if not history.empty:
        chart_data = history.copy()
        chart_data["_date"] = pd.to_datetime(
            chart_data["started_at"],
            errors="coerce",
        )

        plt.figure(figsize=(11, 6))
        plt.plot(
            chart_data["_date"],
            chart_data["accuracy_percent"],
            marker="o",
            label="Genel doğruluk",
        )
        plt.plot(
            chart_data["_date"],
            chart_data["first_try_accuracy_percent"],
            marker="o",
            label="İlk deneme başarısı",
        )
        plt.xlabel("Oturum tarihi")
        plt.ylabel("Başarı (%)")
        plt.title("Tarihsel Gelişim")
        plt.ylim(0, 100)
        plt.legend()
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()

        path = output_dir / "tarihsel_gelisim.png"
        plt.savefig(path, dpi=160)
        plt.close()
        created.append(path)

    return created


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(
        path,
        sep=";",
        index=False,
        encoding="utf-8-sig",
    )


def run_analysis(
    project_dir: Path,
    create_chart_files: bool = True,
) -> dict[str, Path]:
    sessions_dir = project_dir / "sessions"
    failed_dir = project_dir / "failed"
    output_dir = project_dir / "analysis_reports"

    if not sessions_dir.exists():
        raise FileNotFoundError(
            f"'sessions' klasörü bulunamadı:\n{sessions_dir}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    attempt_files = collect_files(sessions_dir, "attempts")
    summary_files = collect_files(sessions_dir, "summary")
    failed_files = (
        collect_files(failed_dir, "failed")
        if failed_dir.exists()
        else []
    )

    if not attempt_files:
        raise FileNotFoundError(
            f"Hiç '*_attempts.csv' bulunamadı:\n{sessions_dir}"
        )

    print(f"📂 Attempts dosyası: {len(attempt_files)}")
    print(f"📂 Summary dosyası : {len(summary_files)}")
    print(f"📂 Failed dosyası  : {len(failed_files)}")

    attempts = load_attempts(attempt_files)
    summaries = load_summaries(summary_files)
    failed = load_failed(failed_files)

    italian_word_lookup = find_vocabulary_words(
        project_dir=project_dir,
        attempts=attempts,
        failed=failed,
    )

    attempts = enrich_error_classification(
        attempts=attempts,
        italian_word_lookup=italian_word_lookup,
    )

    hardest_words = build_hardest_words(attempts)
    error_types = build_error_types(attempts)
    confusion_pairs = build_confusion_pairs(attempts)
    history = build_history(attempts, summaries)
    daily_history = build_daily_history(history)

    outputs = {
        "hardest_words":
            output_dir / "en_zor_kelimeler.csv",
        "error_types":
            output_dir / "en_sik_hata_turleri.csv",
        "confusion_pairs":
            output_dir
            / "en_cok_karistirilan_kelime_ciftleri.csv",
        "history":
            output_dir / "tarihsel_gelisim.csv",
        "daily_history":
            output_dir / "tarihsel_gelisim_gunluk.csv",
        "classified_attempts":
            output_dir / "tum_denemeler_siniflandirilmis.csv",
        "report":
            output_dir / "analiz_raporu.md",
    }

    save_csv(hardest_words, outputs["hardest_words"])
    save_csv(error_types, outputs["error_types"])
    save_csv(confusion_pairs, outputs["confusion_pairs"])
    save_csv(history, outputs["history"])
    save_csv(daily_history, outputs["daily_history"])

    classified_columns = [
        column for column in [
            "session_id",
            "answered_at",
            "attempt_order",
            "italian_word",
            "clue_language",
            "clue",
            "user_answer",
            "is_correct",
            "error_type",
            "error_type_tr",
            "similarity_score",
            "confused_with",
            "task_attempt_number",
            "is_first_try_correct",
            "source_file",
        ]
        if column in attempts.columns
    ]

    save_csv(
        attempts[classified_columns],
        outputs["classified_attempts"],
    )

    report = build_markdown_report(
        attempts=attempts,
        failed=failed,
        hardest_words=hardest_words,
        error_types=error_types,
        confusion_pairs=confusion_pairs,
        history=history,
    )

    outputs["report"].write_text(
        report,
        encoding="utf-8",
    )

    chart_paths: list[Path] = []

    if create_chart_files:
        chart_paths = create_charts(
            output_dir=output_dir,
            hardest_words=hardest_words,
            error_types=error_types,
            history=history,
        )

    print("\n" + "=" * 60)
    print("📊 ANALİZ TAMAMLANDI")
    print("=" * 60)

    print(
        f"İncelenen oturum       : "
        f"{history['session_id'].nunique() if not history.empty else 0}"
    )
    print(
        f"Toplam cevap denemesi  : {len(attempts)}"
    )
    print(
        f"Benzersiz kelime       : "
        f"{attempts['word_key'].nunique()}"
    )
    print(
        f"Toplam yanlış          : "
        f"{int((~attempts['is_correct']).sum())}"
    )

    print(f"\n💾 Rapor klasörü: {output_dir}")

    for label, path in outputs.items():
        print(f"   - {label}: {path.name}")

    for path in chart_paths:
        print(f"   - chart: {path.name}")

    return outputs


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "İtalyanca quiz sessions ve failed dosyalarını "
            "analiz eder."
        )
    )

    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help=(
            "sessions ve failed klasörlerinin bulunduğu proje "
            "klasörü. Varsayılan: betiğin bulunduğu klasör."
        ),
    )

    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="PNG grafiklerini oluşturma.",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    project_dir = arguments.project_dir.expanduser().resolve()

    try:
        run_analysis(
            project_dir=project_dir,
            create_chart_files=not arguments.no_charts,
        )
        return 0
    except Exception as exc:
        print(f"\n❌ Analiz oluşturulamadı:\n{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())