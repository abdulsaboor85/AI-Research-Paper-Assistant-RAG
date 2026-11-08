"""
table_reader.py  -  read a table from the PDF by WHERE the words are on the page.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
Think of looking at a printed table with your eyes, row by row.
1. The normal PDF text is jumbled: the numbers of one column come one after
   another, so the AI must guess which number belongs to which row.
2. Here we ask PyMuPDF for every WORD and its position (x and y) on the page.
3. Words with almost the same y are on the same line, so they are ONE row.
4. A big empty gap between two words means "a new column starts here".
   We write that gap as " | ".
5. We start at the caption ("Table 5 ...") and stop when normal paragraph
   text starts, or when the next Table / Figure caption starts.
6. If we cannot find a table with numbers, we return "" and term_explainer.py
   uses the old chunk method instead (nothing breaks).
This file reads only. It never talks to Gemini and never saves anything.

FUNCTION GUIDE
------------------------------------------------------------
   center_y             the middle height of a word
   left_x               the left side of a word
   get_page_lines       group the words of a page into lines
   words_of             the plain texts of the words in a line
   line_text            one line as text, with " | " for column gaps
   is_caption_line      does this line start the caption of the table?
   count_number_words   how many words in a line are numbers
   is_prose_line        does this line look like a normal paragraph?
   is_other_caption     does this line start another Table or Figure?
   find_table_in_page   the rows of one table on one page
   read_table_text      look through the PDF for the table
"""

import fitz        # PyMuPDF: it gives us every word with its position
import re

LINE_TOLERANCE = 3         # words this close in height are on the same line
COLUMN_GAP = 10            # a gap wider than this (in points) starts a new column
MAX_TABLE_LINES = 150
MAX_TABLE_CHARS = 9000
MIN_NUMBER_LINES = 2       # fewer number rows than this = we did not find a real table
PROSE_WORD_LIMIT = 7       # this many small lowercase words in a line = normal text

NUMBER_WORD = re.compile(r"^-?\d+(?:\.\d+)?%?$")

# term_explainer.py looks for this first line to know the text was read by position
LAYOUT_MARK = "[TABLE ROWS READ BY POSITION: one line = one row, ' | ' = a gap between columns]"


# ---------------------------------------------------------------
# Words and lines
# ---------------------------------------------------------------
def center_y(word):
    """The middle height of a word (a word is a tuple: x0, y0, x1, y1, text, ...)."""
    return (word[1] + word[3]) / 2


def left_x(word):
    return word[0]


def get_page_lines(page):
    """Group the words of one page into lines (top to bottom, left to right)."""
    words = page.get_text("words")
    words.sort(key=center_y)

    groups = []
    current = []
    current_y = None
    for word in words:
        y = center_y(word)
        if current_y is not None and abs(y - current_y) <= LINE_TOLERANCE:
            current.append(word)
        else:
            if current:
                groups.append(current)
            current = [word]
            current_y = y
    if current:
        groups.append(current)

    for group in groups:
        group.sort(key=left_x)
    return groups


def words_of(group):
    texts = []
    for word in group:
        texts.append(word[4])
    return texts


def line_text(group):
    """One line as text. A big gap between two words becomes " | "."""
    text = ""
    previous_right = None
    for word in group:
        if previous_right is not None:
            if word[0] - previous_right > COLUMN_GAP:
                text = text + " | "
            else:
                text = text + " "
        text = text + word[4]
        previous_right = word[2]
    return text


# ---------------------------------------------------------------
# Finding the table
# ---------------------------------------------------------------
def is_caption_line(words, token):
    """True for "Table 5", "Table 5:", "Table 5. Results" or "Table 5 Results".
    False for a normal sentence like "Table 5 shows that..." and for "Table 50"."""
    if len(words) < 2:
        return False
    if words[0].lower() not in ["table", "tab."]:
        return False

    second = words[1]
    if not second.lower().startswith(token.lower()):
        return False

    rest = second[len(token):]
    if rest != "":
        return rest[0] in ":."
    if len(words) == 2:
        return True
    third = words[2]
    return third[0] in ":." or third[0].isupper()


def count_number_words(words):
    total = 0
    for word in words:
        if NUMBER_WORD.match(word):
            total += 1
    return total


def is_prose_line(words):
    """A normal paragraph line has many small lowercase words. A table row does not."""
    total = 0
    for word in words:
        if word.isalpha() and word.islower() and len(word) >= 3:
            total += 1
    return total >= PROSE_WORD_LIMIT


def is_other_caption(words):
    """True when the line starts another "Table 6" or "Fig. 2" caption."""
    if len(words) < 2:
        return False
    if words[0].lower() not in ["table", "tab.", "fig.", "figure"]:
        return False
    return words[1][0].isdigit()


def find_table_in_page(page, token):
    """The rows of the table on this page. "" if it is not here."""
    lines = get_page_lines(page)

    caption_index = -1
    for i in range(len(lines)):
        if is_caption_line(words_of(lines[i]), token):
            caption_index = i
            break
    if caption_index == -1:
        return ""

    rows = [line_text(lines[caption_index])]
    number_lines = 0
    for i in range(caption_index + 1, len(lines)):
        words = words_of(lines[i])
        if is_other_caption(words):
            break
        # normal text only ends the table AFTER we saw some number rows,
        # because a long caption also looks like normal text
        if number_lines >= MIN_NUMBER_LINES and is_prose_line(words):
            break
        if count_number_words(words) >= 2:
            number_lines += 1
        rows.append(line_text(lines[i]))
        if len(rows) >= MAX_TABLE_LINES:
            break

    if number_lines < MIN_NUMBER_LINES:
        return ""
    return "\n".join(rows)


def read_table_text(pdf_path, token):
    """Look through the PDF for "Table <token>". Returns the rows as text, or "" if not found."""
    try:
        with fitz.open(str(pdf_path)) as document:
            for page in document:
                text = find_table_in_page(page, token)
                if text:
                    return (LAYOUT_MARK + "\n" + text)[:MAX_TABLE_CHARS]
    except Exception as error:
        print("[table_reader] could not read the table:", error)
    return ""