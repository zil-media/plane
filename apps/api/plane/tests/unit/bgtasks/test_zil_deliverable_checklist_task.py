# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the Zil deliverable checklist mapping/dedupe logic.

``plane.utils.zil_deliverable_checklists`` is dependency-free by design
(stdlib only), so it is loaded directly from its file instead of through the
``plane`` package — that keeps these tests runnable without Django/Celery
installed, the same way the Notion importer tests do.
"""

import importlib.util
import pathlib

import pytest

_MODULE_PATH = pathlib.Path(__file__).resolve().parents[3] / "utils" / "zil_deliverable_checklists.py"
_spec = importlib.util.spec_from_file_location("zil_deliverable_checklists_under_test", _MODULE_PATH)
checklists_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checklists_module)

DELIVERABLE_CHECKLISTS = checklists_module.DELIVERABLE_CHECKLISTS
DELIVERABLE_LABEL_NAMES = checklists_module.DELIVERABLE_LABEL_NAMES
titles_for_labels = checklists_module.titles_for_labels

EXPECTED_DELIVERABLE_LABELS = {
    "Branding",
    "Web",
    "Landing",
    "Redes Sociales",
    "Email",
    "Merchandising",
}


class TestDeliverableChecklistsMapping:
    def test_covers_every_expected_deliverable_label(self):
        assert set(DELIVERABLE_CHECKLISTS.keys()) == EXPECTED_DELIVERABLE_LABELS
        assert DELIVERABLE_LABEL_NAMES == frozenset(EXPECTED_DELIVERABLE_LABELS)

    @pytest.mark.parametrize("label_name", sorted(EXPECTED_DELIVERABLE_LABELS))
    def test_each_deliverable_has_a_non_empty_titles_list(self, label_name):
        titles = DELIVERABLE_CHECKLISTS[label_name]
        assert isinstance(titles, list)
        assert len(titles) > 0
        assert all(isinstance(title, str) and title.strip() for title in titles)

    def test_titles_are_unique_within_a_single_deliverable(self):
        for label_name, titles in DELIVERABLE_CHECKLISTS.items():
            normalized = [t.strip().lower() for t in titles]
            assert len(normalized) == len(set(normalized)), f"duplicate title within {label_name!r}"


class TestTitlesForLabels:
    def test_unknown_label_contributes_nothing(self):
        assert titles_for_labels(["Not A Deliverable Type"]) == []

    def test_no_labels_returns_empty(self):
        assert titles_for_labels([]) == []

    def test_known_label_returns_its_full_checklist_in_order(self):
        assert titles_for_labels(["Branding"]) == DELIVERABLE_CHECKLISTS["Branding"]

    def test_multiple_labels_combine_checklists(self):
        result = titles_for_labels(["Branding", "Web"])
        assert result == DELIVERABLE_CHECKLISTS["Branding"] + DELIVERABLE_CHECKLISTS["Web"]

    def test_mix_of_known_and_unknown_labels(self):
        result = titles_for_labels(["Bug", "Web", "Priority: High"])
        assert result == DELIVERABLE_CHECKLISTS["Web"]

    def test_existing_titles_are_excluded_case_insensitively(self):
        first_title = DELIVERABLE_CHECKLISTS["Branding"][0]
        result = titles_for_labels(["Branding"], existing_titles=[first_title.upper()])
        assert first_title not in result
        assert result == DELIVERABLE_CHECKLISTS["Branding"][1:]

    def test_existing_titles_strip_whitespace_before_matching(self):
        first_title = DELIVERABLE_CHECKLISTS["Branding"][0]
        result = titles_for_labels(["Branding"], existing_titles=[f"  {first_title}  "])
        assert first_title not in result

    def test_all_titles_already_present_yields_nothing(self):
        result = titles_for_labels(["Branding"], existing_titles=DELIVERABLE_CHECKLISTS["Branding"])
        assert result == []

    def test_rerun_is_idempotent_once_titles_exist(self):
        # Simulates the task being dispatched twice for the same issue: the
        # second call sees the sub-issues the first call created as
        # "existing_titles" and must not propose them again.
        first_run = titles_for_labels(["Web", "Landing"])
        second_run = titles_for_labels(["Web", "Landing"], existing_titles=first_run)
        assert second_run == []

    def test_duplicate_title_across_two_labels_is_created_once(self, monkeypatch):
        # Craft two labels that happen to share a title and confirm the
        # combined result only lists it once, regardless of dict order.
        shared_title = "Shared checklist item"
        patched = dict(DELIVERABLE_CHECKLISTS)
        patched["A"] = [shared_title, "A-only item"]
        patched["B"] = [shared_title, "B-only item"]
        monkeypatch.setattr(checklists_module, "DELIVERABLE_CHECKLISTS", patched)

        result = titles_for_labels(["A", "B"])
        assert result == [shared_title, "A-only item", "B-only item"]
