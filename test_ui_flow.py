"""Regression test for the modal/SnackBar ordering."""

import tempfile
import unittest
from pathlib import Path

import flet as ft

import main as app
from pantry import Pantry


class FakePage:
    def __init__(self):
        self.window = type("Window", (), {})()
        self.dialogs = []

    def add(self, control):
        self.content = control

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        self.dialogs.pop()


class ModalFlowTests(unittest.TestCase):
    def test_consume_closes_modal_then_shows_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            app.DB_PATH = Path(tmp) / "pantry.db"
            pantry = Pantry(app.DB_PATH)
            buyer = pantry.add_roommate("A")
            eater = pantry.add_roommate("B")
            pantry.purchase("牛肉", "weight", "50", "1", buyer, "2026-09-27", "7")
            pantry.close()

            page = FakePage()
            app.main(page)
            page.content.controls[1].controls[3].on_click(None)  # 库存
            page.content.controls[4].controls[0].on_click(None)  # 记录消耗
            dialog = page.dialogs[-1]
            dialog.content.controls[1].controls[0].value = "0.5"
            dialog.content.controls[1].controls[1].value = str(eater)
            dialog.content.controls[3].controls[1].value = True
            dialog.actions[1].on_click(None)

            self.assertEqual(len(page.dialogs), 1)
            self.assertIsInstance(page.dialogs[0], ft.SnackBar)
            check = Pantry(app.DB_PATH)
            self.assertEqual(check.batches()[0]["remaining_milli"], 500)
            check.close()

    def test_period_close_shows_new_cycle_and_saved_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            app.DB_PATH = Path(tmp) / "pantry.db"
            pantry = Pantry(app.DB_PATH)
            buyer = pantry.add_roommate("A")
            eater = pantry.add_roommate("B")
            batch = pantry.purchase("牛肉", "weight", "50", "1", buyer, "2026-09-27", "7")
            pantry.consume(batch, "0.5", eater, [eater])
            pantry.close()

            page = FakePage()
            app.main(page)
            page.content.controls[1].controls[5].on_click(None)  # 结算
            settlement_card = page.content.controls[4]
            settlement_card.content.controls[-1].on_click(None)  # 结束本期
            self.assertIsInstance(page.dialogs[-1], ft.AlertDialog)
            page.dialogs[-1].actions[1].on_click(None)

            self.assertEqual(len(page.dialogs), 1)
            self.assertIsInstance(page.dialogs[0], ft.SnackBar)
            check = Pantry(app.DB_PATH)
            self.assertEqual(check.current_period()["id"], 2)
            self.assertEqual(check.period_report(1)["transfers"][0]["amount_cents"], 2500)
            check.close()


if __name__ == "__main__":
    unittest.main()
