import random
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
import pandas as pd

# Elimdeki csv dosyamın path yolu
PROJECT_DIR = Path(
    "/Users/melihsiskular/PycharmProjects/Italian_xlsx_quiz"
)

CSV_PATH = PROJECT_DIR / "data" / "Italyanca_Kelimeler.csv"

SESSIONS_DIR = PROJECT_DIR / "sessions"
FAILED_DIR = PROJECT_DIR / "failed"

# Bana csv dosyamda lazım olan columnlar
ITALIAN_COLUMN = "İtalyanca Kelime"
CLUE_COLUMNS = ["Türkçesi", "İngilizcesi"]
EXAMPLE_COLUMN = "İtalyanca Cümle -1"



# CSV dosya aralığımda satır başlangıç ve son
# Tüm kelimeler dahil edilmek istenirse None yaz
START_ROW = 291
END_ROW = 301



# Bu kısım öğrendiğim fiillerin çekimleri için
# Yeni fiil öğrendikçe çekimleri eklenebilir
# Hata türü ona göre şekillenir eğer çekimli hali yazarsam.

WORD_FORMS = {
    "volere": {
        "voglio",
        "vuoi",
        "vuole",
        "vogliamo",
        "volete",
        "vogliono"
    },

    "potere": {
        "posso",
        "puoi",
        "può",
        "possiamo",
        "potete",
        "possono"
    },

    "dovere": {
        "devo",
        "devi",
        "deve",
        "dobbiamo",
        "dovete",
        "devono"
    },

    "essere": {
        "sono",
        "sei",
        "è",
        "siamo",
        "siete"
    },

    "avere": {
        "ho",
        "hai",
        "ha",
        "abbiamo",
        "avete",
        "hanno"
    },

    "andare": {
        "vado",
        "vai",
        "va",
        "andiamo",
        "andate",
        "vanno"
    },

    "fare": {
        "faccio",
        "fai",
        "fa",
        "facciamo",
        "fate",
        "fanno"
    },

    "venire": {
        "vengo",
        "vieni",
        "viene",
        "veniamo",
        "venite",
        "vengono"
    }
}

# CSV yardımcı fonksiyonlar
def clean_text(value) -> str:
    """
    NaN değerlerini ve gereksiz boşlukları temizler.
    """

    if pd.isna(value):
        return ""

    return str(value).strip()


def normalize_text(value) -> str:
    """
    Cevap karşılaştırmasını büyük/küçük harften ve
    gereksiz boşluklardan bağımsız hâle getirir.
    """

    return " ".join(
        clean_text(value).casefold().split()
    )

def normalize_forms_dictionary(forms_dictionary: dict) -> dict:
    """
    WORD_FORMS sözlüğündeki bütün kelimeleri normalize eder.
    """

    normalized_dictionary = {}

    for lemma, forms in forms_dictionary.items():

        normalized_lemma = normalize_text(lemma)

        normalized_dictionary[normalized_lemma] = {
            normalize_text(form)
            for form in forms
        }

    return normalized_dictionary


NORMALIZED_WORD_FORMS = normalize_forms_dictionary(
    WORD_FORMS
)

def looks_like_regular_verb_form(
    user_answer: str,
    correct_answer: str
) -> bool:
    """
    Düzenli -are, -ere ve -ire fiillerinin bazı çekimli
    biçimlerini yaklaşık olarak tespit eder.

    Örnek:
        trovare -> trovo
        dormire -> dormo
        ricevere -> ricevo
    """

    answer = normalize_text(user_answer)
    lemma = normalize_text(correct_answer)

    if not lemma.endswith(("are", "ere", "ire")):
        return False

    if len(lemma) <= 4:
        return False

    stem = lemma[:-3]

    if not answer.startswith(stem):
        return False

    suffix = answer[len(stem):]

    common_verb_endings = {
        # Şimdiki zaman
        "o",
        "i",
        "a",
        "e",
        "iamo",
        "ate",
        "ete",
        "ite",
        "ano",
        "ono",

        # -isc fiilleri
        "isco",
        "isci",
        "isce",
        "iscono",

        # Geçmiş zaman ortaçları
        "ato",
        "uto",
        "ito",

        # Gerundio
        "ando",
        "endo"
    }

    return suffix in common_verb_endings

# Cevabın gireceği sınıf
def classify_answer(
    user_answer: str,
    correct_answer: str,
    italian_word_lookup: dict
) -> tuple[str, float, str]:
    """
    Kullanıcının cevabını otomatik olarak sınıflandırır.

    Dönüş değerleri:
        error_type
        similarity_score
        confused_with

    Hata türleri:
        correct
        spelling_error
        confused_with_another_word
        wrong_word_form
        no_recall
        unknown_or_semantic_error
    """

    normalized_user = normalize_text(user_answer)
    normalized_correct = normalize_text(correct_answer)

    # D - Boş cevap / hiç hatırlayamama
    if not normalized_user:
        return "no_recall", 0.0, ""

    # Doğru cevap
    if normalized_user == normalized_correct:
        return "correct", 1.0, ""

    similarity_score = SequenceMatcher(
        None,
        normalized_user,
        normalized_correct
    ).ratio()

    # C - Bilinen düzensiz çekimli biçim
    known_forms = NORMALIZED_WORD_FORMS.get(
        normalized_correct,
        set()
    )

    if normalized_user in known_forms:
        return (
            "wrong_word_form",
            round(similarity_score, 3),
            ""
        )

    # C - Düzenli fiilin çekimli biçimi
    if looks_like_regular_verb_form(
        user_answer,
        correct_answer
    ):
        return (
            "wrong_word_form",
            round(similarity_score, 3),
            ""
        )

    # B - CSV'deki başka bir İtalyanca kelimeyi yazmış
    if normalized_user in italian_word_lookup:

        confused_word = italian_word_lookup[
            normalized_user
        ]

        return (
            "confused_with_another_word",
            round(similarity_score, 3),
            confused_word
        )

    # A - Doğru kelimeye benzeyen yazım hatası
    if similarity_score >= 0.75:
        return (
            "spelling_error",
            round(similarity_score, 3),
            ""
        )

    # E - Alakasız cevap veya kelimenin bilinmemesi
    return (
        "unknown_or_semantic_error",
        round(similarity_score, 3),
        ""
    )


def load_vocabulary(file_path: Path) -> pd.DataFrame:
    """
    CSV dosyasını noktalı virgül veya virgül ayırıcıyla okumayı dener.
    Ayrıca dosyada fazladan ilk satır varsa onu atlamayı da dener.
    """

    required_columns = {
        ITALIAN_COLUMN,
        "Türkçesi",
        "İngilizcesi"
    }

    for separator in (";", ","):
        for skipped_rows in (1, 0):
            try:
                loaded_df = pd.read_csv(
                    file_path,
                    sep=separator,
                    skiprows=skipped_rows,
                    encoding="utf-8-sig",
                    dtype=str,
                    keep_default_na=False
                )

                loaded_df.columns = loaded_df.columns.str.strip()

                if required_columns.issubset(loaded_df.columns):

                    if EXAMPLE_COLUMN not in loaded_df.columns:
                        loaded_df[EXAMPLE_COLUMN] = ""

                    return loaded_df

            except Exception:
                continue

    raise ValueError(
        "CSV okunamadı veya gerekli sütunlar bulunamadı.\n"
        f"Gerekli sütunlar: {sorted(required_columns)}\n"
        f"Dosya konumu: {file_path}"
    )


def language_display_name(column_name: str) -> str:
    """CSV sütun adını kullanıcıya gösterilecek hâle getirir."""

    language_names = {
        "Türkçesi": "Türkçe",
        "İngilizcesi": "İngilizce"
    }

    return language_names.get(column_name, column_name)



df = load_vocabulary(CSV_PATH)

total_csv_rows = len(df)

if START_ROW is not None or END_ROW is not None:

    # Kullanıcı satırları 1'den başlayarak girer.
    start_row = START_ROW if START_ROW is not None else 1
    end_row = END_ROW if END_ROW is not None else total_csv_rows

    if start_row < 1:
        raise ValueError(
            "START_ROW değeri 1 veya daha büyük olmalıdır."
        )

    if end_row > total_csv_rows:
        raise ValueError(
            f"END_ROW en fazla {total_csv_rows} olabilir. "
            f"CSV dosyasında toplam {total_csv_rows} kelime var."
        )

    if start_row > end_row:
        raise ValueError(
            "START_ROW, END_ROW değerinden büyük olamaz."
        )

    # iloc başlangıcı dahil, bitişi hariç çalışır.
    # Kullanıcı için bitiş satırını dahil ediyoruz.
    df = df.iloc[start_row - 1:end_row].copy()

    print(
        f"📖 Çalışılacak CSV satırları: "
        f"{start_row}–{end_row}"
    )

    print(
        f"📚 Seçilen toplam satır: {len(df)}"
    )

else:
    print(
        f"📚 Bütün CSV kullanılacak. "
        f"Toplam satır: {total_csv_rows}"
    )

df[ITALIAN_COLUMN] = df[ITALIAN_COLUMN].apply(clean_text)

# İtalyanca kelimesi boş olan satırları kaldır.
df = df[df[ITALIAN_COLUMN] != ""].copy()

# Aynı kelimeyi büyük/küçük harften bağımsız şekilde tanımak için.
df["_word_key"] = df[ITALIAN_COLUMN].apply(normalize_text)

original_unique_word_count = df["_word_key"].nunique()

# Normalize edilmiş cevap -> CSV'deki gerçek yazılışı
#
# Örnek:
# "benvenuto" -> "Benvenuto"
# "ciao" -> "Ciao"

italian_word_lookup = {
    normalize_text(word): clean_text(word)
    for word in df[ITALIAN_COLUMN]
    if clean_text(word)
}

# Aynı İtalyanca kelime dosyada birden fazla kez bulunuyorsa
# yalnızca ilk satırı kullan.
df = (
    df.drop_duplicates(
        subset="_word_key",
        keep="first"
    )
    .reset_index(drop=True)
)

task_data = {}

# Bir kelimenin hangi dillerde görevi olduğunu tutar.
languages_by_word = defaultdict(set)

for row_index, row in df.iterrows():

    word_key = row["_word_key"]
    italian_word = clean_text(row[ITALIAN_COLUMN])
    example = clean_text(row.get(EXAMPLE_COLUMN, ""))

    for clue_column in CLUE_COLUMNS:

        clue = clean_text(row.get(clue_column, ""))

        # Türkçe veya İngilizce ipucu boşsa o görev oluşturulmaz.
        if not clue:
            continue

        task = (word_key, clue_column)

        task_data[task] = {
            "row_index": row_index,
            "word_key": word_key,
            "italian_word": italian_word,
            "clue_column": clue_column,
            "clue": clue,
            "example": example
        }

        languages_by_word[word_key].add(clue_column)


quiz_word_keys = set(languages_by_word.keys())

total_unique_words = len(quiz_word_keys)
total_language_tasks = len(task_data)

skipped_word_count = (
    original_unique_word_count - total_unique_words
)

if total_language_tasks == 0:
    raise ValueError(
        "Sorulabilecek görev bulunamadı. "
        "Türkçesi ve İngilizcesi sütunlarını kontrol et."
    )



started_at = datetime.now()

session_id = started_at.strftime(
    "%Y%m%d_%H%M%S"
)

# Henüz doğru cevaplanmamış görevler.
pending_tasks = set(task_data.keys())

# Doğru cevaplanıp bitirilmiş görevler.
completed_tasks = set()

# Her kelimenin hangi dil görevlerinin tamamlandığı.
completed_languages_by_word = defaultdict(set)

# Her görev kaç defa soruldu?
attempts_per_task = defaultdict(int)

# Her görevde kaç yanlış yapıldı?
mistakes_per_task = defaultdict(int)

# Analiz için bütün cevapların kaydı.
attempt_log = []

last_task = None
exit_reason = "all_tasks_completed"

print("\n" + "=" * 60)
print("🇮🇹 BENVENUTO!")
print("=" * 60)

print(
    f"Toplam benzersiz İtalyanca kelime : "
    f"{total_unique_words}"
)

print(
    f"Toplam dil görevi                  : "
    f"{total_language_tasks}"
)

print(
    "Her kelimenin Türkçe ve İngilizce ipucu "
    "ayrı görev olarak değerlendirilir."
)

if skipped_word_count > 0:
    print(
        f"\nUyarı: {skipped_word_count} kelimenin "
        "Türkçe ve İngilizce ipuçları boş olduğu için atlandı."
    )

print(
    "\nÇıkmak için cevap alanına veya "
    "devam ekranına 'esc' yazabilirsin."
)


# Quiz döngüsü
while pending_tasks:

    candidates = list(pending_tasks)

    # Yanlış cevaplanan sorunun hemen tekrar gelmesini önler.
    # Havuzda başka soru yoksa aynı soru tekrar gelebilir.
    if last_task in candidates and len(candidates) > 1:
        candidates.remove(last_task)

    current_task = random.choice(candidates)

    current = task_data[current_task]

    word_key = current["word_key"]
    clue_column = current["clue_column"]
    clue_language = language_display_name(clue_column)

    correct_answer = current["italian_word"]

    print("\n" + "-" * 60)

    print(f"İpucu dili : {clue_language}")
    print(f"İpucu      : {current['clue']}")

    user_answer = input(
        "İtalyanca kelime nedir? "
    ).strip()

    # Quizden çıkış
    if user_answer.casefold() == "esc":
        exit_reason = "manual_exit"
        break

    # Bu görev kaçıncı kez cevaplandı?
    attempts_per_task[current_task] += 1

    task_attempt_number = attempts_per_task[current_task]

    is_correct = (
        normalize_text(user_answer)
        == normalize_text(correct_answer)
    )
    error_type, similarity_score, confused_with = (
        classify_answer(
            user_answer=user_answer,
            correct_answer=correct_answer,
            italian_word_lookup=italian_word_lookup
        )
    )

    # Görev ilk gösterildiğinde doğru cevaplandı mı?
    is_first_try_correct = (
        is_correct
        and task_attempt_number == 1
    )

    if is_correct:

        print("🎉 Esatto! Doğru cevap.")

        # Doğru cevaplanan görev havuzdan çıkarılır.
        # Örneğin yalnızca Türkçe doğruysa İngilizce görev kalır.
        pending_tasks.remove(current_task)

        completed_tasks.add(current_task)

        completed_languages_by_word[word_key].add(
            clue_column
        )

    else:

        print(
            f"❌ Sbagliato. "
            f"Doğru cevap: {correct_answer}"
        )

        print(
            "Bu görev havuzda kalacak ve "
            "daha sonra tekrar gelebilecek."
        )

        mistakes_per_task[current_task] += 1

    if current["example"]:
        print(f"Örnek: {current['example']}")

    # -----------------------------------------------------
    # DENEMEYİ KAYDET
    # -----------------------------------------------------
    attempt_log.append({
        "session_id": session_id,
        "answered_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "attempt_order": len(attempt_log) + 1,
        "word_key": word_key,
        "italian_word": correct_answer,
        "clue_language": clue_language,
        "clue_column": clue_column,
        "clue": current["clue"],
        "user_answer": user_answer,
        "is_correct": is_correct,
        "error_type": error_type,
        "similarity_score": similarity_score,
        "confused_with": confused_with,
        "task_attempt_number": task_attempt_number,
        "is_first_try_correct": is_first_try_correct,
        "example": current["example"]
    })

    # Bir kelimenin mevcut bütün dil görevleri tamamlanmışsa
    # kelime tamamen öğrenilmiş sayılır.
    mastered_word_count = sum(
        completed_languages_by_word[key]
        == languages_by_word[key]
        for key in quiz_word_keys
    )

    completed_task_count = len(completed_tasks)

    print(
        f"\n📊 Dil görevleri: "
        f"{completed_task_count}/{total_language_tasks} tamamlandı"
    )

    print(
        f"📚 Tam öğrenilen kelimeler: "
        f"{mastered_word_count}/{total_unique_words}"
    )

    print(
        f"⏳ Kalan dil görevi: "
        f"{len(pending_tasks)}"
    )

    last_task = current_task

    # Bütün görevler bittiyse devam sorusu sormadan döngü biter.
    if pending_tasks:

        continue_answer = input(
            "\nDevam etmek için Enter, "
            "çıkmak için 'esc': "
        ).strip().casefold()

        if continue_answer == "esc":
            exit_reason = "manual_exit"
            break



ended_at = datetime.now()

duration_seconds = max(
    0,
    int(
        (ended_at - started_at).total_seconds()
    )
)

duration_minutes = round(
    duration_seconds / 60,
    2
)

duration_display = (
    f"{duration_seconds // 60} dk "
    f"{duration_seconds % 60} sn"
)

SESSIONS_DIR.mkdir(
    parents=True,
    exist_ok=True
)

FAILED_DIR.mkdir(
    parents=True,
    exist_ok=True
)

file_stamp = started_at.strftime(
    "%d.%m.%Y_%H.%M.%S"
)



attempt_columns = [
    "session_id",
    "answered_at",
    "attempt_order",
    "word_key",
    "italian_word",
    "clue_language",
    "clue_column",
    "clue",
    "user_answer",
    "is_correct",
    "error_type",
    "similarity_score",
    "confused_with",
    "task_attempt_number",
    "is_first_try_correct",
    "example"
]

attempts_df = pd.DataFrame(
    attempt_log,
    columns=attempt_columns
)
# failed.csv analizi için kelime anahtarını kesin olarak oluştur.
attempts_df["word_key"] = (
    attempts_df["italian_word"]
    .apply(normalize_text)
)
attempts_file = (
    SESSIONS_DIR
    / f"{file_stamp}_attempts.csv"
)

attempts_df.to_csv(
    attempts_file,
    sep=";",
    index=False,
    encoding="utf-8-sig"
)


# İstatistikler
if not attempts_df.empty:

    correct_answer_count = int(
        attempts_df["is_correct"].sum()
    )

    first_try_correct_count = int(
        attempts_df["is_first_try_correct"].sum()
    )

else:

    correct_answer_count = 0
    first_try_correct_count = 0


wrong_answer_count = (
    len(attempts_df) - correct_answer_count
)

mastered_word_count = sum(
    completed_languages_by_word[key]
    == languages_by_word[key]
    for key in quiz_word_keys
)

if len(attempts_df) > 0:

    accuracy_percent = round(
        correct_answer_count
        / len(attempts_df)
        * 100,
        2
    )

else:
    accuracy_percent = 0.0



summary_data = {
    "session_id": session_id,
    "started_at": started_at.isoformat(
        timespec="seconds"
    ),
    "ended_at": ended_at.isoformat(
        timespec="seconds"
    ),
    "duration_seconds": duration_seconds,
    "duration_minutes": duration_minutes,
    "duration_display": duration_display,
    "exit_reason": exit_reason,
    "total_unique_words": total_unique_words,
    "total_language_tasks": total_language_tasks,
    "completed_language_tasks": len(completed_tasks),
    "remaining_language_tasks": len(pending_tasks),
    "mastered_unique_words": mastered_word_count,
    "total_attempts": len(attempts_df),
    "correct_answers": correct_answer_count,
    "wrong_answers": wrong_answer_count,
    "first_try_correct_tasks": first_try_correct_count,
    "accuracy_percent": accuracy_percent
}

summary_file = (
    SESSIONS_DIR
    / f"{file_stamp}_summary.csv"
)

pd.DataFrame([summary_data]).to_csv(
    summary_file,
    sep=";",
    index=False,
    encoding="utf-8-sig"
)


wrong_word_keys = {
    task[0]
    for task, mistake_count
    in mistakes_per_task.items()
    if mistake_count > 0
}

failed_file = None

if wrong_word_keys:

    failed_records = []

    for word_key in sorted(wrong_word_keys):
        row = df[
            df["_word_key"] == word_key
            ].iloc[0]

        turkish_task = (
            word_key,
            "Türkçesi"
        )

        english_task = (
            word_key,
            "İngilizcesi"
        )

        word_error_rows = attempts_df[
            (attempts_df["word_key"] == word_key)
            & (attempts_df["is_correct"] == False)
            ]

        record = {
            column: clean_text(row[column])
            for column in df.columns
            if column != "_word_key"
        }

        record.update({
            "Türkçe Yanlış Sayısı":
                mistakes_per_task[turkish_task],

            "İngilizce Yanlış Sayısı":
                mistakes_per_task[english_task],

            "Toplam Yanlış Sayısı":
                (
                        mistakes_per_task[turkish_task]
                        + mistakes_per_task[english_task]
                ),

            "Yazım Hatası Sayısı": int(
                (
                        word_error_rows["error_type"]
                        == "spelling_error"
                ).sum()
            ),

            "Karıştırma Sayısı": int(
                (
                        word_error_rows["error_type"]
                        == "confused_with_another_word"
                ).sum()
            ),

            "Yanlış Kelime Biçimi Sayısı": int(
                (
                        word_error_rows["error_type"]
                        == "wrong_word_form"
                ).sum()
            ),

            "Hatırlayamama Sayısı": int(
                (
                        word_error_rows["error_type"]
                        == "no_recall"
                ).sum()
            ),

            "Bilinmeyen veya Anlamsal Hata Sayısı": int(
                (
                        word_error_rows["error_type"]
                        == "unknown_or_semantic_error"
                ).sum()
            ),

            "Karıştırılan Kelimeler": ", ".join(
                sorted(
                    {
                        clean_text(value)
                        for value
                        in word_error_rows["confused_with"]
                        if clean_text(value)
                    }
                )
            ),

            "Oturum Sonunda Tamamlandı":
                (
                        completed_languages_by_word[word_key]
                        == languages_by_word[word_key]
                )
        })

        failed_records.append(record)

    failed_df = pd.DataFrame(
        failed_records
    )

    failed_file = (
        FAILED_DIR
        / f"{file_stamp}_failed.csv"
    )

    failed_df.to_csv(
        failed_file,
        sep=";",
        index=False,
        encoding="utf-8-sig"
    )


# QUIZ BİTTİ!
print("\n" + "=" * 60)
print("🏁 QUIZ FINISHED")
print("=" * 60)

if exit_reason == "all_tasks_completed":

    print(
        "Bütün kelime-dil görevleri tamamlandı. "
        "Bravissimo! 👏"
    )

else:

    print(
        "Quiz kullanıcı tarafından "
        "erken sonlandırıldı."
    )

print(
    f"\nToplam benzersiz kelime : "
    f"{total_unique_words}"
)

print(
    f"Tam öğrenilen kelime    : "
    f"{mastered_word_count}"
)

print(
    f"Tamamlanan dil görevi   : "
    f"{len(completed_tasks)}/{total_language_tasks}"
)

print(
    f"Toplam cevap denemesi   : "
    f"{len(attempts_df)}"
)

print(
    f"Doğru cevap             : "
    f"{correct_answer_count}"
)

print(
    f"Yanlış cevap            : "
    f"{wrong_answer_count}"
)

print(
    f"İlk denemede doğru      : "
    f"{first_try_correct_count}"
)

print(
    f"Doğruluk oranı          : "
    f"%{accuracy_percent}"
)

print(
    f"\n💾 Tüm denemeler: "
    f"{attempts_file}"
)

print(
    f"💾 Oturum özeti : "
    f"{summary_file}"
)

if failed_file:

    print(
        f"💾 Yanlış listesi: "
        f"{failed_file}"
    )

else:

    print(
        "Hiç yanlış yapılmadığı için "
        "ayrıca yanlış listesi oluşturulmadı."
    )

print(
    "\nA presto! Successo nei tuoi studi!"
)