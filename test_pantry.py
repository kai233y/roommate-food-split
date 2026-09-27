import tempfile
import unittest
from pathlib import Path

from pantry import Pantry


class PantryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Pantry(Path(self.tmp.name) / "test.db")
        self.a = self.p.add_roommate("A")
        self.b = self.p.add_roommate("B")
        self.c = self.p.add_roommate("C")

    def tearDown(self):
        self.p.close()
        self.tmp.cleanup()

    def test_example_split_and_remainder(self):
        beef = self.p.purchase("牛肉", "weight", "50", "1", self.a, "2026-09-27", "3")
        self.p.consume(beef, "0.5", self.b, [self.b, self.c])
        stats = {r["name"]: r for r in self.p.summary()}
        self.assertEqual((stats["B"]["consumed"], stats["C"]["consumed"]), (1250, 1250))
        self.assertEqual(stats["A"]["remaining_contribution"], 2500)
        self.assertEqual(stats["A"]["food_provided"], 2500)
        self.assertEqual(self.p.batches()[0]["remaining_milli"], 500)
        self.assertEqual(len(self.p.ledger(person_id=self.c)), 1)  # shared consumption
        self.assertEqual(self.p.stock_history()[-1][1], 2500)

    def test_waste_and_invalid_removal(self):
        eggs = self.p.purchase("鸡蛋", "piece", "2", "3", self.a, "2026-09-27", "7")
        with self.assertRaises(ValueError):
            self.p.consume(eggs, "3.5", self.b, [self.b])
        with self.assertRaises(ValueError):
            self.p.consume(eggs, "4", self.b, [self.b])
        self.assertEqual(self.p.batches()[0]["remaining_milli"], 3000)
        self.p.waste(eggs, "1", self.c, "破损")
        self.assertEqual(self.p.summary()[0]["waste_borne"], 0)
        self.p.waste(eggs, "2", self.c, "过期", buyer_bears=True)
        self.assertEqual(self.p.summary()[0]["waste_borne"], 400)
        self.assertEqual(self.p.batches()[0]["remaining_cents"], 0)
        self.assertEqual(len(self.p.ledger(ingredient="鸡", person_id=self.c)), 2)

    def test_cent_rounding_allocates_full_value(self):
        item = self.p.purchase("香料", "weight", "0.03", "1", self.a, "2026-09-27", "7")
        for _ in range(3):
            self.p.consume(item, "0.333" if _ < 2 else "0.334", self.a, [self.a, self.b])
        s = self.p.summary()
        self.assertEqual(sum(row["consumed"] for row in s), 3)
        self.assertEqual(self.p.batches()[0]["remaining_cents"], 0)

    def test_period_transfers_and_stock_carry_forward(self):
        beef = self.p.purchase("牛肉", "weight", "50", "1", self.a, "2026-09-27", "3")
        self.p.consume(beef, "0.5", self.b, [self.b, self.c])
        report = self.p.period_report()
        self.assertEqual(report["consumed_cents"], 2500)
        self.assertEqual([(t["payer"], t["receiver"], t["amount_cents"])
                          for t in report["transfers"]],
                         [("B", "A", 1250), ("C", "A", 1250)])
        self.p.set_cycle_type("week")
        first_id = self.p.close_period()
        self.assertEqual(self.p.current_period()["cycle_type"], "week")
        self.assertEqual(self.p.period_report()["transfers"], [])
        self.assertEqual(self.p.batches()[0]["remaining_milli"], 500)
        self.assertEqual(self.p.db.execute(
            "SELECT count(*) FROM settlements WHERE period_id=?", (first_id,)).fetchone()[0], 2)
        self.p.consume(beef, "0.5", self.b, [self.b, self.c])
        self.assertEqual(self.p.period_report()["consumed_cents"], 2500)
        self.assertEqual(self.p.period_report(first_id)["consumed_cents"], 2500)

    def test_period_netting_and_due_dates(self):
        a_food = self.p.purchase("A的菜", "piece", "10", "1", self.a, "2026-09-27", "7")
        b_food = self.p.purchase("B的菜", "piece", "4", "1", self.b, "2026-09-27", "7")
        self.p.consume(a_food, "1", self.b, [self.b])
        self.p.consume(b_food, "1", self.a, [self.a])
        transfers = self.p.period_report()["transfers"]
        self.assertEqual([(t["payer"], t["receiver"], t["amount_cents"]) for t in transfers],
                         [("B", "A", 600)])
        self.assertEqual(Pantry._due_on("2026-01-31T10:00:00", "month"), "2026-02-28")
        self.assertEqual(Pantry._due_on("2026-09-27T10:00:00", "week"), "2026-10-04")


if __name__ == "__main__":
    unittest.main()
