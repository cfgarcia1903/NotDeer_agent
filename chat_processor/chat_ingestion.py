from os.path import join as os_path_join, exists as os_path_exists, isfile as os_path_isfile
from os import makedirs, listdir
import shutil
import re
import sqlite3

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from tqdm import tqdm

DATA_PATH = "data/"

CHAT_FILE_PREFIX = {
    "es": "Chat de WhatsApp con",
    "en": "Whatsapp Chat with"
}


@dataclass
class ChatMessage:
    timestamp: datetime
    author: str 
    text: str = None
    is_system: bool = True
    is_voice_note: bool = False
    voice_note_file: str = None
    raw: str = None


class ChatExport:

    # =========================================================
    # Constantes parser
    # =========================================================

    ENCODING = "utf-8"

    INVISIBLE_UNICODE_REGEX = r"[\u200e\u200f\u202a-\u202e]"

    ATTACHMENT_SUFFIX = "(archivo adjunto)"

    OMITTED_MEDIA_LABELS = {
        "<Multimedia omitido>",
        "‎<Multimedia omitido>",
        "<Media omitted>",
        "‎<Media omitted>",
    }

    VOICE_NOTE_PREFIX = "PTT-"
    VOICE_NOTE_EXTENSION = ".opus"

    MESSAGE_HEADER_REGEX = re.compile(
    r"^"
    r"(\d{1,2}/\d{1,2}/\d{2,4})"
    r",\s+"
    r"(\d{1,2}:\d{2}.*?)"
    r"\s+-\s+"
    r"(.*)$",
    re.UNICODE | re.DOTALL
    )

    AUTHOR_MESSAGE_REGEX = re.compile(
        r"^([^:]+?):\s(.*)$",
        re.UNICODE | re.DOTALL
    )

    ATTACHMENT_LINE_REGEX = re.compile(
        r"^(.*?)\s*\(archivo adjunto\)\s*(.*)$",
        re.UNICODE
    )

    DATETIME_FORMATS = [
        "%d/%m/%Y, %I:%M %p",
        "%d/%m/%y, %I:%M %p",
    ]

    def __init__(self, name, raw_ruta, language="es"):
        self.name = name
        self.raw_dir = raw_ruta
        self.language = language
        self.raw_dir_files = self._list_files(self.raw_dir)

        self.chat_path = os_path_join(DATA_PATH, self.name)
        self.vn_files_path = os_path_join(self.chat_path, "vn_files")
        self.raw_chat_path = os_path_join(self.chat_path, "raw_chat.txt")

    # =========================================================
    # File handling
    # =========================================================

    def _copy_relevant_files(self):

        if not os_path_exists(self.chat_path):

            makedirs(self.chat_path)

            if not os_path_exists(self.vn_files_path):
                makedirs(self.vn_files_path)
            else:
                raise FileExistsError(
                    f"El directorio {self.vn_files_path} ya existe."
                )

            if os_path_exists(self.raw_chat_path):
                raise FileExistsError(
                    f"El archivo {self.raw_chat_path} ya existe."
                )

        else:
            return
            raise FileExistsError(
                f"El directorio {self.chat_path} ya existe."
            )

        for file in self.raw_dir_files:

            if file.startswith("PTT-"):

                shutil.copy(
                    os_path_join(self.raw_dir, file),
                    os_path_join(self.vn_files_path, file)
                )

            elif file.startswith(CHAT_FILE_PREFIX[self.language]):

                shutil.copy(
                    os_path_join(self.raw_dir, file),
                    self.raw_chat_path
                )

    # =========================================================
    # Helpers parser
    # =========================================================

    def _clean_text(self, text):

        text = re.sub(
            self.INVISIBLE_UNICODE_REGEX,
            "",
            text
        )

        # normalizar espacios unicode raros
        text = (
            text
            .replace("\u00A0", " ")
            .replace("\u202F", " ")
            .replace("\u2009", " ")
        )

        text = text.replace("\r\n", "\n")

        return text.strip()

    def _normalize_ampm(self, time_str):

        # =========================================
        # Normalizar espacios unicode raros
        # =========================================

        unicode_spaces = [
            "\u00A0",  # NO-BREAK SPACE
            "\u202F",  # NARROW NO-BREAK SPACE
            "\u2009",  # THIN SPACE
        ]

        for space in unicode_spaces:
            time_str = time_str.replace(space, " ")

        time_str = time_str.strip().lower()

        # =========================================
        # Normalizaciones AM/PM
        # =========================================

        replacements = {
            "a. m.": "AM",
            "a.m.": "AM",
            "a m": "AM",
            "am": "AM",

            "p. m.": "PM",
            "p.m.": "PM",
            "p m": "PM",
            "pm": "PM",
        }

        for old, new in replacements.items():
            time_str = time_str.replace(old, new)

        # eliminar espacios sobrantes
        time_str = re.sub(r"\s+", " ", time_str)

        return time_str.upper().strip()

    def _parse_datetime(self, date_str, time_str):

        normalized_time = self._normalize_ampm(time_str)

        combined = f"{date_str}, {normalized_time}"

        for fmt in self.DATETIME_FORMATS:

            try:
                return datetime.strptime(combined, fmt)

            except ValueError:
                pass

        raise ValueError(
            f"No se pudo parsear datetime: {combined}"
        )

    def _is_new_message(self, line):

        return bool(
            self.MESSAGE_HEADER_REGEX.match(line)
        )

    def _is_voice_note_attachment(self, filename):

        filename = filename.strip()

        return (
            filename.startswith(self.VOICE_NOTE_PREFIX)
            and filename.endswith(self.VOICE_NOTE_EXTENSION)
        )

    # =========================================================
    # Main parser
    # =========================================================

    def _parse_chat(self):

        with open(
            self.raw_chat_path,
            "r",
            encoding=self.ENCODING
        ) as f:

            chat_content = f.read()

        chat_content = self._clean_text(chat_content)

        lines = chat_content.split("\n")

        # =====================================================
        # Reconstrucción mensajes multilínea
        # =====================================================

        reconstructed_messages = []

        current_message = ""

        for line in tqdm(lines):

            line = line.rstrip()

            if self._is_new_message(line):

                if current_message:
                    reconstructed_messages.append(
                        current_message
                    )

                current_message = line

            else:

                current_message += "\n" + line

        if current_message:
            reconstructed_messages.append(
                current_message
            )

        # =====================================================
        # Parse estructurado
        # =====================================================

        parsed_messages = []

        participants = set()

        for raw_message in reconstructed_messages:

            header_match = self.MESSAGE_HEADER_REGEX.match(
                raw_message
            )

            if not header_match:
                continue

            date_str, time_str, remainder = (
                header_match.groups()
            )

            timestamp = self._parse_datetime(
                date_str,
                time_str
            )

            author = 'System'
            text = remainder
            is_system = True
            is_voice_note = False
            voice_note_file = None

            # =================================================
            # Separar autor
            # =================================================

            author_match = self.AUTHOR_MESSAGE_REGEX.match(
                remainder
            )

            if author_match:

                author, text = author_match.groups()

                author = author.strip()
                text = text.strip()

                participants.add(author)

                is_system = False

            text = self._clean_text(text)

            # =================================================
            # Ignorar multimedia omitida pura
            # =================================================

            if text in self.OMITTED_MEDIA_LABELS:
                continue

            # =================================================
            # Procesar adjuntos
            # =================================================

            text_lines = text.split("\n")

            first_line = text_lines[0].strip()

            remaining_lines = text_lines[1:]

            remaining_text = "\n".join(
                remaining_lines
            ).strip()

            attachment_match = (
                self.ATTACHMENT_LINE_REGEX.match(
                    first_line
                )
            )

            if attachment_match:

                filename, inline_caption = (
                    attachment_match.groups()
                )

                filename = filename.strip()

                inline_caption = inline_caption.strip()

                full_caption = (
                    inline_caption
                )

                if remaining_text:

                    if full_caption:
                        full_caption += "\n"

                    full_caption += remaining_text

                # =============================================
                # Nota de voz
                # =============================================

                if self._is_voice_note_attachment(
                    filename
                ):

                    is_voice_note = True
                    voice_note_file = filename
                    text = full_caption

                # =============================================
                # Otros adjuntos
                # =============================================

                else:

                    # Imagen/video/pdf/sticker/etc.
                    # sin caption -> ignorar

                    if not full_caption:
                        continue

                    # conservar solo caption

                    text = full_caption

            # =================================================
            # Multimedia omitida + caption
            # =================================================

            elif first_line in self.OMITTED_MEDIA_LABELS:

                if not remaining_text:
                    continue

                text = remaining_text

            # =================================================
            # Ignorar mensajes sistema vacíos
            # =================================================

            if is_system and not text:
                continue

            # =================================================
            # Ignorar mensajes vacíos
            # =================================================

            if not text and not is_voice_note:
                continue

            parsed_messages.append(ChatMessage(timestamp=timestamp,
                                               author=author,
                                               text=text,
                                               is_system=is_system,
                                               is_voice_note=is_voice_note,
                                               voice_note_file=voice_note_file,
                                               raw=raw_message))

        self.participants = sorted(participants)

        self.messages = parsed_messages

        return parsed_messages


    def _save_to_sqlite(self, db_path=None):

        if not hasattr(self, "messages"):
            raise ValueError(
                "No hay mensajes parseados. Ejecuta _parse_chat() primero."
            )

        if db_path is None:
            db_path = os_path_join(
                self.chat_path,
                "chat.db"
            )

        conn = sqlite3.connect(db_path)

        cursor = conn.cursor()

        # =====================================================
        # Tabla principal
        # =====================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT NOT NULL,

            author TEXT NOT NULL,

            text TEXT,

            is_voice_note INTEGER NOT NULL,

            voice_note_file TEXT,

            raw TEXT
        )
        """)

        # =====================================================
        # Índices
        # =====================================================

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp
        ON messages(timestamp)
        """)

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_author
        ON messages(author)
        """)

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_voice_note
        ON messages(is_voice_note)
        """)

        # =====================================================
        # Insertar mensajes
        # =====================================================

        for msg in self.messages:

            # Ignorar mensajes sistema
            if msg.is_system:
                continue

            cursor.execute("""
            INSERT INTO messages (

                timestamp,
                author,
                text,
                is_voice_note,
                voice_note_file,
                raw

            )
            VALUES (?, ?, ?, ?, ?, ?)
            """, (

                msg.timestamp.isoformat(),

                msg.author,

                msg.text,

                int(msg.is_voice_note),

                msg.voice_note_file,

                msg.raw

            ))

        conn.commit()

        conn.close()
    # =========================================================
    # Utils
    # =========================================================

    def _list_files(self, path):

        return [
            f for f in listdir(path)
            if os_path_isfile(os_path_join(path, f))
        ]

if __name__ == "__main__":
    from tkinter import Tk
    from tkinter.filedialog import askdirectory

    ruta = askdirectory(title="Selecciona una carpeta")

    #chat_export = ChatExport(name="name", raw_ruta=ruta, language="es")
    #chat_export._copy_relevant_files()
    #chat = chat_export._parse_chat()
    #chat_export._save_to_sqlite()

    print(ruta)