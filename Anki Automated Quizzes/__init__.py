from aqt import mw
from aqt.qt import (
    QAction,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QCheckBox,
    QMessageBox,
    QGroupBox,
    QAbstractItemView,
    QTreeWidget,
    QTreeWidgetItem
)
from aqt.utils import tooltip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QSizePolicy, QRadioButton, QFrame, QScrollArea
import random
import os
import json
import re
from functools import partial
from typing import Final

MENU_WIDTH: Final = 550
MENU_HEIGHT: Final = 858
QUESTIONS_WIDTH: Final = 900
QUESTIONS_HEIGHT: Final = 758

# ---- Cross-version helpers ----
def _deck_tuple(dni):
    if hasattr(dni, "id") and hasattr(dni, "name"):
        return (dni.id, dni.name)
    try:
        return (dni["id"], dni["name"])
    except Exception:
        return (getattr(dni, "id", None), str(dni))

def _get_all_decks():
    try:
        items = mw.col.decks.all_names_and_ids()
    except Exception:
        items = mw.col.decks.allNamesAndIds()
    return [_deck_tuple(d) for d in items]

def _note_type_obj(note):
    try:
        return note.note_type()  # New API
    except Exception:
        return note.model()      # Old API

def _note_type_name(note):
    nt = _note_type_obj(note)
    try:
        return nt.name
    except Exception:
        try:
            return nt["name"]
        except Exception:
            return str(nt)

def _field_names_for_model(model_obj):
    try:
        return list(model_obj.field_names())
    except Exception:
        pass
    try:
        return [f["name"] for f in model_obj["flds"]]
    except Exception:
        return []

def _find_notes_in_deck(self, deck_name, exclude_tags):
    tag_filter = " ".join(f'-tag:"{t}"' for t in exclude_tags if t)
    state_filter = ""
    
    states = []
    if self.newCards.isChecked():
        states.append("new")
    if self.learnCards.isChecked():
        states.append("learn")
    if self.dueCards.isChecked():
        states.append("due")
    if self.reviewCards.isChecked():
        states.append("review")
        
    state_filter = " OR ".join(f'is:"{s}"' for s in states if s)
    if len(state_filter) > 0:
        state_filter = "(" + state_filter + ")"
        
    filters = " ".join([tag_filter, state_filter]).strip()
    query = f'deck:"{deck_name}" {filters}'.strip()
    return mw.col.find_notes(query)

def _collect_models_and_fields(nids):
    """Return mapping: model_name -> (model_obj, field_names)."""
    res = {}
    for nid in nids:
        n = mw.col.get_note(nid)
        if not n:
            continue
        mobj = _note_type_obj(n)
        try:
            mname = mobj.name
        except Exception:
            mname = mobj.get("name") if isinstance(mobj, dict) else str(mobj)
        if mname in res:
            continue
        fields = _field_names_for_model(mobj)
        res[mname] = (mobj, fields)
    return res

def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    text = re.sub(r"</?[^>]+>", "", text or "")
    return text.strip()

def _normalize_html(s: str) -> str:
    """Normalize for equality checks: collapse whitespace, lower, strip."""
    s = (s or "").replace("\r", "").replace("\n", "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _notes_to_qa(notes, prompt_field, answer_field, required_model_name=None):
    qa = []
    for nid in notes:
        n = mw.col.get_note(nid)
        if n is None:
            continue
        if required_model_name and _note_type_name(n) != required_model_name:
            continue
        if prompt_field not in n or answer_field not in n:
            continue
        front = (n[prompt_field] or "").strip()
        back = (n[answer_field] or "").strip()
        if front and back:
            qa.append({"nid": nid, "prompt": front, "answer": back})
    return qa

def _make_quiz_items(qa, num_questions, num_choices, allow_answer_reuse: bool):
    if len(qa) == 0:
        raise ValueError("No notes found to generate questions.")
    pool = qa[:]
    random.shuffle(pool)
    selected = pool[:min(num_questions, len(pool))]
    all_answers = [x["answer"] for x in qa]

    quiz = []
    for item in selected:
        correct = item["answer"]
        options = [correct]

        if allow_answer_reuse:
            unique_others = [a for a in set(all_answers) if _normalize_html(a) != _normalize_html(correct)]
            random.shuffle(unique_others)
            options += unique_others[:max(0, num_choices - 1)]
            while len(options) < num_choices:
                options.append(random.choice(all_answers))
        else:
            candidates = [a for a in set(all_answers) if _normalize_html(a) != _normalize_html(correct)]
            random.shuffle(candidates)
            options += candidates[:max(0, num_choices - 1)]

        options = options[:num_choices]
        random.shuffle(options)

        quiz.append({
            "nid": item["nid"],
            "prompt": item["prompt"],     # raw HTML allowed
            "correct": correct,           # raw HTML allowed
            "options": options,           # list of raw HTML strings
        })
    return quiz

# Quiz history helpers
def _history_path():
    addon_folder = os.path.dirname(__file__)
    return os.path.join(addon_folder, "quiz_history.json")

def _load_history():
    try:
        with open(_history_path(), "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_history(nid_list):
    history = _load_history()
    history.update(nid_list)
    with open(_history_path(), "w", encoding="utf-8") as f:
        json.dump(list(history), f)

# ---- Option row widget (Radio + HTML label) ----
class OptionRow(QWidget):
    def __init__(self, html_text: str, parent=None):
        super().__init__(parent)
        self.raw_html = html_text or ""
        row = QHBoxLayout(self)
        row.setSpacing(0) # column spacing
        row.setContentsMargins(0, 4, 0, 4)
        self.radio = QRadioButton(self)
        self.radio.setFixedWidth(50)
        row.addWidget(self.radio, 0)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.label.setOpenExternalLinks(True)
        self.label.setWordWrap(True)
        
        # Render raw HTML; if actually empty, show a placeholder
        self.label.setText(self.raw_html if self.raw_html.strip() else "<i>(blank)</i>")
        self.label.setMinimumWidth(400)
        self.label.setMaximumWidth(700)
        # self.setStyleSheet("font-size: 14px;")
        row.addWidget(self.label, 1)
        row.addStretch()

        # Allow clicking the label to toggle the radio
        self.label.mousePressEvent = lambda e: self.radio.setChecked(True)

    def set_enabled(self, enabled: bool):
        self.radio.setEnabled(enabled)
        self.label.setEnabled(enabled)

    def set_background(self, color_css: str):
        self.setStyleSheet(f"QWidget {{ background: {color_css}; border-radius: 6px; }}")

class MCQuizDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Automated Quiz")
        self.resize(MENU_WIDTH, MENU_HEIGHT)
        # item_list = [listWidget.item(i).text() for i in range(listWidget.count())]
        self.cfg = mw.addonManager.getConfig(__name__) or {}
        self.cfg.setdefault("default_deck", "")
        self.cfg.setdefault("num_choices", 4)
        self.cfg.setdefault("num_questions", 25)
        self.cfg.setdefault("exclude_tags", [])
        self.cfg.setdefault("allow_answer_reuse", True)
        self.cfg.setdefault("last_model_name", "")
        self.cfg.setdefault("last_prompt_field", "")
        self.cfg.setdefault("last_answer_field", "")
        self.cfg.setdefault("num_per_page", 5)
        self.cfg.setdefault("card_states", ["learn, due"])
        self.cfg.setdefault("font_size_q", 22)
        self.cfg.setdefault("font_size_a", 14)

        layout = QVBoxLayout(self)

        # --- Config panel ---
        self.config_widget = QWidget(self)
        config_layout = QVBoxLayout(self.config_widget)

        decks = _get_all_decks()
        self.deck_cb = QComboBox(self.config_widget)
        names = [name for (_id, name) in decks]
        self.deck_cb.addItems(names)
        if self.cfg["default_deck"] and self.cfg["default_deck"] in names:
            self.deck_cb.setCurrentText(self.cfg["default_deck"])

        # Deck
        config_layout.addWidget(QLabel("Deck:"))
        config_layout.addWidget(self.deck_cb)

        # Note type
        config_layout.addWidget(QLabel("Note type:"))
        self.model_cb = QComboBox(self.config_widget)
        config_layout.addWidget(self.model_cb)

        # middle area that has 2 colums
        #   left column has prompt field, answer field, questions, choices, and questions per page
        #   right column has card selection
        middleColumns = QHBoxLayout()

        # --- left column ---
        leftColumn = QVBoxLayout()
        leftColumn.setContentsMargins(0, 0, 15, 0)
        
        # Prompt field
        promptFieldRow = QHBoxLayout()
        promptFieldLabel = QLabel("Prompt field:")
        promptFieldLabel.setFixedWidth(120) 
        promptFieldRow.addWidget(promptFieldLabel, 0)
        self.prompt_cb = QComboBox(self.config_widget)
        promptFieldRow.addWidget(self.prompt_cb, 1)
        
        # Answer field
        answerFieldRow = QHBoxLayout()
        anwerFieldLabel = QLabel("Answer field:")
        anwerFieldLabel.setFixedWidth(120) 
        answerFieldRow.addWidget(anwerFieldLabel, 0)
        self.answer_cb = QComboBox(self.config_widget)
        answerFieldRow.addWidget(self.answer_cb, 1)

        # Questions
        questionsRow = QHBoxLayout()
        questionsLabel = QLabel("Questions:")
        questionsLabel.setFixedWidth(120) 
        questionsRow.addWidget(questionsLabel, 0)
        self.qcount = QSpinBox(self.config_widget); self.qcount.setRange(1, 1000); self.qcount.setValue(int(self.cfg["num_questions"]))
        questionsRow.addWidget(self.qcount, 1)
        
        # Choices
        choicesRow = QHBoxLayout()
        choicesLabel = QLabel("Choices:")
        choicesLabel.setFixedWidth(120) 
        choicesRow.addWidget(choicesLabel, 0)
        self.ccount = QSpinBox(self.config_widget); self.ccount.setRange(2, 10); self.ccount.setValue(int(self.cfg["num_choices"]))
        choicesRow.addWidget(self.ccount, 1)
        
        # Questions per page
        questionsPerPageRow = QHBoxLayout()
        questionsPerPageLabel = QLabel("Questions per page:")
        questionsPerPageLabel.setFixedWidth(120) 
        questionsPerPageRow.addWidget(questionsPerPageLabel, 0)
        self.qperpage = QSpinBox(self.config_widget); self.qperpage.setRange(1, 20); self.qperpage.setValue(int(self.cfg.get("num_per_page", 5)))
        questionsPerPageRow.addWidget(self.qperpage, 1)
        
        leftColumn.addLayout(promptFieldRow)
        leftColumn.addLayout(answerFieldRow)
        leftColumn.addLayout(questionsRow)
        leftColumn.addLayout(choicesRow)
        leftColumn.addLayout(questionsPerPageRow)
        
        leftColumnPanel = QWidget()
        leftColumnPanel.setLayout(leftColumn)
        leftColumnPanel.setContentsMargins(0, 12, 0, 0)
        
        middleColumns.addWidget(leftColumnPanel)
        
        # --- right column ---
        rightColumn = QVBoxLayout()
        rightColumn.setContentsMargins(10, 10, 2, 0)
        cardSelectBox = QGroupBox()
        cardSelectBox.setFixedWidth(130)
        cardSelectBoxLayout = QVBoxLayout()
        cardSelectBox.setLayout(cardSelectBoxLayout)
        
        # Card types
        self.allCards = QCheckBox("Select all", self.config_widget)
        self.newCards = QCheckBox("New cards", self.config_widget)
        self.learnCards = QCheckBox("Learn cards", self.config_widget)
        self.dueCards = QCheckBox("Due cards", self.config_widget)
        self.reviewCards = QCheckBox("Review cards", self.config_widget)
        
        card_states = self.cfg["card_states"]
        
        if "new" in card_states:
            self.newCards.setChecked(True)
        if "learn" in card_states:
            self.learnCards.setChecked(True)
        if "due" in card_states:
            self.dueCards.setChecked(True)
        if "review" in card_states:
            self.reviewCards.setChecked(True)
        if self.newCards.isChecked() and self.learnCards.isChecked() and self.dueCards.isChecked() and self.reviewCards.isChecked():
            self.allCards.setChecked(True)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setFixedWidth(105)
        separator.setContentsMargins(8, 0, 0, 0)
        
        cardSelectBoxLayout.addWidget(self.allCards)
        cardSelectBoxLayout.addWidget(separator)
        cardSelectBoxLayout.addWidget(self.newCards)
        cardSelectBoxLayout.addWidget(self.learnCards)
        cardSelectBoxLayout.addWidget(self.dueCards)
        cardSelectBoxLayout.addWidget(self.reviewCards)
        
        # listeners to auto check all/none
        self.allCards.stateChanged.connect(self._on_card_type_select)
        self.newCards.stateChanged.connect(self._on_card_type_select)
        self.learnCards.stateChanged.connect(self._on_card_type_select)
        self.dueCards.stateChanged.connect(self._on_card_type_select)
        self.reviewCards.stateChanged.connect(self._on_card_type_select)
        
        cardTypesLabel = QLabel("Card types:")
        cardTypesLabel.setContentsMargins(3, 0, 0, 0)
        rightColumn.addWidget(cardTypesLabel)
        rightColumn.addWidget(cardSelectBox)
        rightColumn.addStretch()
        
        middleColumns.addLayout(rightColumn)
        config_layout.addLayout(middleColumns)

        # Allow Answer re-use
        self.dup_cb = QCheckBox("Allow answer re-use", self.config_widget)
        self.dup_cb.setChecked(bool(self.cfg["allow_answer_reuse"]))
        config_layout.addWidget(self.dup_cb)

        # Exclude tags
        config_layout.addWidget(QLabel("Exclude tags (optional):"))
        self.tags_list = QListWidget(self.config_widget)
        self.tags_list.setFixedHeight(100)
        self.tags_list.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        for t in self.cfg["exclude_tags"]:
            self.tags_list.addItem(QListWidgetItem(t))
        config_layout.addWidget(self.tags_list)

        # Exclude cards from previous quizzes
        self.exclude_history_cb = QCheckBox("Exclude cards from previous quizzes", self.config_widget)
        self.exclude_history_cb.setChecked(False)
        config_layout.addWidget(self.exclude_history_cb)

        # Clear quiz history
        self.clear_history_btn = QPushButton("Clear Quiz History", self.config_widget)
        self.clear_history_btn.clicked.connect(self._on_clear_history)
        config_layout.addWidget(self.clear_history_btn)

        # Start quiz
        self.start_btn = QPushButton("Start Quiz", self.config_widget)
        self.start_btn.clicked.connect(self.start_quiz)
        config_layout.addWidget(self.start_btn)

        layout.addWidget(self.config_widget)

        # --- Quiz container inside a scroll area ---
        self.quiz_widget = QWidget()
        self.quiz_container = QVBoxLayout(self.quiz_widget)
        self.quiz_widget.setLayout(self.quiz_container)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.quiz_widget)
        layout.addWidget(self.scroll_area)

        # Nav buttons
        self.next_btn = QPushButton("Next Page")
        self.next_btn.clicked.connect(self._on_next_page)
        self.next_btn.hide()
        layout.addWidget(self.next_btn)

        self.prev_btn = QPushButton("Previous Page")
        self.prev_btn.clicked.connect(self._on_prev_page)
        self.prev_btn.hide()
        layout.addWidget(self.prev_btn)
        
        # font control
        fontLayout = QHBoxLayout()
        self.font_btn = QPushButton(">")
        self.font_btn.setFixedWidth(40) 
        self.font_btn.setFixedHeight(25) 
        self.font_btn.setStyleSheet("padding: 0px;")
        self.font_btn.clicked.connect(self._on_font_button)
        fontLayout.addWidget(self.font_btn)
        fontLayout.addStretch()
        
        self.qf_label = QLabel("Question font size:")
        fontLayout.addWidget(self.qf_label)
        self.qfontsize = QSpinBox(self.config_widget); self.qfontsize.setRange(6, 40); self.qfontsize.setValue(int(self.cfg["font_size_q"]))
        self.qfontsize.setFixedWidth(50) 
        fontLayout.addWidget(self.qfontsize)
        
        self.af_label = QLabel("Answer font size:")
        fontLayout.addWidget(self.af_label)
        self.afontsize = QSpinBox(self.config_widget); self.afontsize.setRange(6, 40); self.afontsize.setValue(int(self.cfg["font_size_a"]))
        self.afontsize.setFixedWidth(50) 
        fontLayout.addWidget(self.afontsize)
        
        self.fontframe = QFrame()
        self.fontframe.setLayout(fontLayout)
        self.fontframe.setFixedHeight(25) 
        fontLayout.setContentsMargins(0, 0, 0, 0)
        self.fontframe.setContentsMargins(0, 0, 0, 0)
        self.fontframe.hide()
        layout.addWidget(self.fontframe)
        
        self.qfontsize.valueChanged.connect(self._on_font_changed)
        self.afontsize.valueChanged.connect(self._on_font_changed)
        
        self.qf_label.hide()
        self.qfontsize.hide()
        self.af_label.hide()
        self.afontsize.hide()

        # Signals
        self.deck_cb.currentTextChanged.connect(self._on_deck_changed)
        self.model_cb.currentTextChanged.connect(self._on_model_changed)

        # Init
        self._on_deck_changed(self.deck_cb.currentText())

        self.state = {"quiz": [], "idx": 0, "correct": 0, "total": 0, "page": 0, "per_page": 1}
        self.current_question_widgets = []
        self.user_answers = {}  # quiz index -> chosen raw html

    def _on_font_button(self):
        val = self.font_btn.text()
        if val == "<":
            self.font_btn.setText(">")
            self.qf_label.hide()
            self.qfontsize.hide()
            self.af_label.hide()
            self.afontsize.hide()
        else:
            self.font_btn.setText("<")
            self.qf_label.show()
            self.qfontsize.show()
            self.af_label.show()
            self.afontsize.show()

    def _on_font_changed(self):
        
        for qlabel in self.qlabels:
            qlabel.setStyleSheet("font-size: " + str(self.qfontsize.value()) + "px;")
            
        for alabel in self.alabels:
            alabel.setStyleSheet("font-size: " + str(self.afontsize.value()) + "px;")
        
        self.cfg["font_size_q"] = int(self.qfontsize.value())
        self.cfg["font_size_a"] = int(self.afontsize.value())
        
        try:
            mw.addonManager.writeConfig(__name__, self.cfg)
        except Exception:
            pass

    def _on_card_type_select(self):
        sender = self.sender()
        
        if sender is self.allCards:
            self.newCards.blockSignals(True)
            self.newCards.setChecked(self.allCards.isChecked())
            self.newCards.blockSignals(False)
            
            self.learnCards.blockSignals(True)
            self.learnCards.setChecked(self.allCards.isChecked())
            self.learnCards.blockSignals(False)
            
            self.dueCards.blockSignals(True)
            self.dueCards.setChecked(self.allCards.isChecked())
            self.dueCards.blockSignals(False)
            
            self.reviewCards.blockSignals(True)
            self.reviewCards.setChecked(self.allCards.isChecked())
            self.reviewCards.blockSignals(False)
        elif self.newCards.isChecked() and self.learnCards.isChecked() and self.dueCards.isChecked() and self.reviewCards.isChecked():
            self.allCards.blockSignals(True)
            self.allCards.setChecked(True)
            self.allCards.blockSignals(False)
        else:
            self.allCards.blockSignals(True)
            self.allCards.setChecked(False)
            self.allCards.blockSignals(False)

    # ---- UI updates ----
    def _on_deck_changed(self, deck_name):
        nids = _find_notes_in_deck(self, deck_name, [])
        models = _collect_models_and_fields(nids)
        self.model_cb.blockSignals(True)
        self.model_cb.clear()
        for mname in sorted(models.keys()):
            self.model_cb.addItem(mname)
        self.model_cb.blockSignals(False)

        if self.cfg.get("last_model_name") in models:
            self.model_cb.setCurrentText(self.cfg["last_model_name"])

        self._populate_fields(deck_models=models)

    def _populate_fields(self, deck_models=None):
        deck_name = self.deck_cb.currentText()
        if deck_models is None:
            nids = _find_notes_in_deck(self, deck_name, [])
            deck_models = _collect_models_and_fields(nids)

        mname = self.model_cb.currentText()
        fields = []
        if mname in deck_models:
            fields = deck_models[mname][1]

        self.prompt_cb.blockSignals(True)
        self.answer_cb.blockSignals(True)
        self.prompt_cb.clear()
        self.answer_cb.clear()
        for f in fields:
            self.prompt_cb.addItem(f)
            self.answer_cb.addItem(f)

        if self.cfg.get("last_prompt_field") in fields:
            self.prompt_cb.setCurrentText(self.cfg["last_prompt_field"])
        else:
            for guess in ("Front", "Question", "Prompt"):
                if guess in fields:
                    self.prompt_cb.setCurrentText(guess); break
        if self.cfg.get("last_answer_field") in fields:
            self.answer_cb.setCurrentText(self.cfg["last_answer_field"])
        else:
            for guess in ("Back", "Answer", "Response"):
                if guess in fields:
                    self.answer_cb.setCurrentText(guess); break

        self.prompt_cb.blockSignals(False)
        self.answer_cb.blockSignals(False)

    def _on_model_changed(self, _text):
        self._populate_fields()

    # ---- Quiz flow ----
    def start_quiz(self):
        self.resize(QUESTIONS_WIDTH, QUESTIONS_HEIGHT)
        deck = self.deck_cb.currentText()
        exclude = [self.tags_list.item(i).text() for i in range(self.tags_list.count())]
        num_q = int(self.qcount.value())
        num_c = int(self.ccount.value())
        allow_dup = bool(self.dup_cb.isChecked())
        
        card_states = []
        if self.newCards.isChecked():
            card_states.append("new")
        if self.learnCards.isChecked():
            card_states.append("learn")
        if self.dueCards.isChecked():
            card_states.append("due")
        if self.reviewCards.isChecked():
            card_states.append("review")

        model_name = self.model_cb.currentText()
        prompt_field = self.prompt_cb.currentText()
        answer_field = self.answer_cb.currentText()

        nids = _find_notes_in_deck(self, deck, exclude)
        if self.exclude_history_cb.isChecked():
            used_nids = _load_history()
            nids = [nid for nid in nids if nid not in used_nids]
        qa = _notes_to_qa(nids, prompt_field, answer_field, required_model_name=model_name)

        if len(qa) == 0:
            QMessageBox.warning(self, "No matching notes",
                                "No notes found with the chosen fields in this deck.\n"
                                f"Deck: {deck}\nNote type: {model_name}\nFields: {prompt_field} / {answer_field}")
            return

        try:
            quiz = _make_quiz_items(qa, num_q, num_c, allow_dup)
        except Exception as e:
            QMessageBox.warning(self, "Quiz error",
                                f"Could not build quiz: {e}\n"
                                f"Notes available: {len(qa)}")
            return
        
        # persist choices
        self.cfg["default_deck"] = deck
        self.cfg["num_choices"] = num_c
        self.cfg["num_questions"] = num_q
        self.cfg["allow_answer_reuse"] = allow_dup
        self.cfg["last_model_name"] = model_name
        self.cfg["last_prompt_field"] = prompt_field
        self.cfg["last_answer_field"] = answer_field
        self.cfg["num_per_page"] = int(self.qperpage.value())
        self.cfg["card_states"] = card_states
        
        try:
            mw.addonManager.writeConfig(__name__, self.cfg)
        except Exception:
            pass

        random.shuffle(quiz)
        self.state = {
            "quiz": quiz,
            "idx": 0,
            "correct": 0,
            "total": len(quiz),
            "page": 0,
            "per_page": int(self.qperpage.value()),
        }
        self.user_answers = {}
        self.config_widget.hide()
        self._show_current_page()

    def _clear_quiz_container(self):
        for widget in self.current_question_widgets:
            widget.setParent(None)
        self.current_question_widgets = []

    def _show_current_page(self):
        self._clear_quiz_container()
        quiz = self.state["quiz"]
        idx = self.state["idx"]
        per_page = self.state["per_page"]
        total = self.state["total"]

        if idx >= total:
            self.fontframe.hide()
            self.next_btn.hide()
            self.prev_btn.hide()
            self._show_results_page()
            return

        end = min(idx + per_page, total)
        self.page_option_rows = []
        
        self.qlabels = list()
        self.alabels = list()

        for i, qidx in enumerate(range(idx, end)):
            q = quiz[qidx]
            q_group = QVBoxLayout()
            group_widget = QGroupBox()
            group_widget.setStyleSheet("QGroupBox { border: 2px solid #afafaf; border-radius: 10px; margin-top: 10px; padding: 10px; }")
            
            q_label = QLabel(f"Q{qidx+1}: {_strip_html(q['prompt'])}")
            q_label.setStyleSheet("font-size: " + str(self.qfontsize.value()) + "px;")
            q_label.setWordWrap(True)
            q_label.setMaximumWidth(820)
            q_group.addWidget(q_label)
            self.qlabels.append(q_label)

            rows = []
            for opt in q["options"]:
                row = OptionRow(opt, self)
                row.setStyleSheet("font-size: " + str(self.cfg["font_size_a"]) + "px;")
                # clicking the radio selects and finalizes the question
                row.radio.toggled.connect(partial(self._on_choose, i, row, group_widget))
                q_group.addWidget(row)
                rows.append(row)
                self.current_question_widgets.append(row)
                self.alabels.append(row)
            self.page_option_rows.append(rows)

            group_widget.setLayout(q_group)
            group_widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            
            self.quiz_container.addWidget(group_widget)
            self.current_question_widgets.append(q_label)
            self.current_question_widgets.append(group_widget)

        if end < total:
            self.next_btn.setText("Next Page")
            self.next_btn.show()
        else:
            self.next_btn.setText("Finish")
            self.next_btn.show()

        if idx > 0:
            self.prev_btn.show()
        else:
            self.prev_btn.hide()
            
        self.fontframe.show()

        # --- Auto-scroll to top ---
        self.scroll_area.verticalScrollBar().setValue(0)

    def _on_choose(self, question_idx_in_page, chosen_row: OptionRow, group_widget: QGroupBox, checked: bool):
        if not checked:
            return
        quiz = self.state["quiz"]
        idx = self.state["idx"]
        qidx = idx + question_idx_in_page
        if qidx in self.user_answers:
            return  # already answered

        q = quiz[qidx]
        chosen_raw = chosen_row.raw_html
        correct_raw = q["correct"]

        # record
        self.user_answers[qidx] = chosen_raw

        # peer rows for this question
        rows = self.page_option_rows[question_idx_in_page]
        # lock and colorize
        
        isCorrect = True
        for row in rows:
            row.radio.setEnabled(False)
            row.label.mousePressEvent = lambda event: event.ignore()
            
            if _normalize_html(row.raw_html) == _normalize_html(correct_raw):
                row.radio.setText("✔")
                row.radio.setStyleSheet("QRadioButton { color: green; }")
            elif row is chosen_row:
                row.radio.setText("✘")
                row.radio.setStyleSheet("QRadioButton { color: red; }")
                isCorrect = False
        
        if isCorrect:
            group_widget.setStyleSheet("QGroupBox { border: 2px solid green; border-radius: 10px; margin-top: 10px; padding: 10px; }")
        else:
            group_widget.setStyleSheet("QGroupBox { border: 2px solid red; border-radius: 10px; margin-top: 10px; padding: 10px; }")
        
        if _normalize_html(chosen_raw) == _normalize_html(correct_raw):
            self.state["correct"] += 1

    def _on_next_page(self):
        self.state["idx"] += self.state["per_page"]
        self._show_current_page()

    def _on_prev_page(self):
        self.state["idx"] = max(0, self.state["idx"] - self.state["per_page"])
        self._show_current_page()

    def _show_results_page(self):
        self._clear_quiz_container()
        self.resize(MENU_WIDTH, MENU_HEIGHT)
        quiz = self.state["quiz"]
        total = self.state["total"]
        correct = self.state["correct"]

        pct = round(100 * correct / max(1, total))
        summary = QLabel(f"<b>Quiz Complete!</b><br>Score: {correct}/{total} ({pct}%)")
        self.quiz_container.addWidget(summary)
        self.current_question_widgets.append(summary)

        # results table (text-only for readability)
        html = "<table border=1 cellpadding=4><tr><th>#</th><th>Prompt</th><th>Your Answer</th><th>Correct Answer</th></tr>"
        for i, q in enumerate(quiz):
            ua_raw = self.user_answers.get(i, "")
            ua_txt = _strip_html(ua_raw)
            ca_txt = _strip_html(q["correct"])
            color = "#cfc" if _normalize_html(ua_raw) == _normalize_html(q["correct"]) else "#fcc"
            prompt_txt = _strip_html(q["prompt"])
            html += f"<tr style='color:black;background:{color};'><td>{i+1}</td><td>{prompt_txt}</td><td>{ua_txt}</td><td>{ca_txt}</td></tr>"
        html += "</table>"

        results_label = QLabel()
        results_label.setTextFormat(Qt.TextFormat.RichText)
        results_label.setText(html)
        results_label.setWordWrap(True)
        self.quiz_container.addWidget(results_label)
        self.current_question_widgets.append(results_label)

        export_btn = QPushButton("Export Results to HTML")
        export_btn.clicked.connect(self._export_results_html)
        self.quiz_container.addWidget(export_btn)
        self.current_question_widgets.append(export_btn)

        _save_history([q["nid"] for q in quiz])
        self.config_widget.show()

    def _export_results_html(self):
        quiz = self.state["quiz"]
        total = self.state["total"]
        correct = self.state["correct"]
        pct = round(100 * correct / max(1, total))

        html = f"<h2>Quiz Results</h2><p>Score: {correct}/{total} ({pct}%)</p>"
        html += "<table border=1 cellpadding=4><tr><th>#</th><th>Prompt</th><th>Your Answer</th><th>Correct Answer</th></tr>"
        for i, q in enumerate(quiz):
            ua_raw = self.user_answers.get(i, "")
            ua_txt = _strip_html(ua_raw)
            ca_txt = _strip_html(q["correct"])
            color = "#cfc" if _normalize_html(ua_raw) == _normalize_html(q["correct"]) else "#fcc"
            prompt_txt = _strip_html(q["prompt"])
            html += f"<tr style='background:{color}'><td>{i+1}</td><td>{prompt_txt}</td><td>{ua_txt}</td><td>{ca_txt}</td></tr>"
        html += "</table>"

        fname, _ = QFileDialog.getSaveFileName(self, "Save Results", "quiz_results.html", "HTML Files (*.html)")
        if fname:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            tooltip("Results exported.")

        retry_btn = QPushButton("Retry Quiz")
        retry_btn.clicked.connect(self.retry_quiz)
        self.quiz_container.addWidget(retry_btn)
        self.current_question_widgets.append(retry_btn)

    def retry_quiz(self):
        self.state = {"quiz": [], "idx": 0, "correct": 0, "total": 0, "page": 0, "per_page": 5}
        self.user_answers = {}
        self.config_widget.show()
        self.next_btn.hide()
        self.prev_btn.hide()
        self.fontframe.hide()

    def _on_clear_history(self):
        path = _history_path()
        if os.path.exists(path):
            try:
                os.remove(path)
                tooltip("Quiz history cleared.")
            except Exception as e:
                tooltip(f"Error clearing quiz history: {e}")

def show_quiz_dialog():
    dlg = MCQuizDialog(mw)
    dlg.exec()

action = QAction("Automated Quizzes", mw)
action.triggered.connect(show_quiz_dialog)
mw.form.menuTools.addAction(action)
