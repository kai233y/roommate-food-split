"""SQLite accounting core for the shared pantry."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


def parse_quantity(value: str, unit: str) -> int:
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("数量必须是数字") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("数量必须大于 0")
    scaled = number * 1000
    if scaled != scaled.to_integral_value() or (unit == "piece" and number != number.to_integral_value()):
        raise ValueError("重量最多保留 3 位小数；按个数计必须为整数")
    return int(scaled)


def parse_price(value: str) -> int:
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("单价必须是数字") from exc
    if not number.is_finite() or number < 0 or number != number.quantize(Decimal("0.01")):
        raise ValueError("单价不能为负，最多保留 2 位小数")
    return int(number * 100)


def money(cents: int) -> str:
    return f"¥{Decimal(cents) / 100:.2f}"


def quantity(milli: int, unit: str) -> str:
    value = Decimal(milli) / 1000
    return f"{value.normalize():f} {'kg' if unit == 'weight' else '个'}"


class Pantry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS roommates (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE CHECK(length(trim(name)) > 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                unit TEXT NOT NULL CHECK(unit IN ('weight', 'piece')),
                unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
                original_milli INTEGER NOT NULL CHECK(original_milli > 0),
                remaining_milli INTEGER NOT NULL CHECK(remaining_milli >= 0),
                total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
                remaining_cents INTEGER NOT NULL CHECK(remaining_cents >= 0),
                buyer_id INTEGER NOT NULL REFERENCES roommates(id),
                purchase_date TEXT NOT NULL,
                shelf_days INTEGER NOT NULL CHECK(shelf_days >= 0),
                expires_on TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('purchase', 'consume', 'waste')),
                occurred_at TEXT NOT NULL,
                actor_id INTEGER NOT NULL REFERENCES roommates(id),
                batch_id INTEGER NOT NULL REFERENCES batches(id),
                quantity_milli INTEGER NOT NULL CHECK(quantity_milli > 0),
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                reason TEXT,
                buyer_bears INTEGER NOT NULL DEFAULT 0 CHECK(buyer_bears IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS allocations (
                ledger_id INTEGER NOT NULL REFERENCES ledger(id),
                roommate_id INTEGER NOT NULL REFERENCES roommates(id),
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                PRIMARY KEY (ledger_id, roommate_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_time ON ledger(occurred_at);
            CREATE INDEX IF NOT EXISTS idx_ledger_batch ON ledger(batch_id);
            CREATE INDEX IF NOT EXISTS idx_alloc_roommate ON allocations(roommate_id);
        """)

    def close(self):
        self.db.close()

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def roommates(self):
        return self.db.execute("SELECT * FROM roommates ORDER BY id").fetchall()

    def add_roommate(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("请输入室友姓名")
        with self.db:
            if self.db.execute("SELECT count(*) FROM roommates").fetchone()[0] >= 3:
                raise ValueError("最多添加 3 位室友")
            try:
                cur = self.db.execute("INSERT INTO roommates(name,created_at) VALUES(?,?)", (name, self._now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("室友姓名不能重复") from exc
            return cur.lastrowid

    def _roommate_exists(self, id_: int) -> bool:
        return self.db.execute("SELECT 1 FROM roommates WHERE id=?", (id_,)).fetchone() is not None

    def purchase(self, name: str, unit: str, price: str, amount: str,
                 buyer_id: int, purchase_date: str, shelf_days: str) -> int:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("食材名称不能为空且不能超过 80 字")
        if unit not in ("weight", "piece"):
            raise ValueError("请选择计量方式")
        qty = parse_quantity(amount, unit)
        unit_price = parse_price(price)
        total = int((Decimal(qty) * unit_price / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if total == 0:
            raise ValueError("总价值必须至少为 0.01 元")
        try:
            bought = date.fromisoformat(purchase_date)
            days = int(shelf_days)
        except (ValueError, TypeError) as exc:
            raise ValueError("购买日期或保质期格式不正确") from exc
        if days < 0 or days > 36500:
            raise ValueError("保质期须在 0 到 36500 天之间")
        if not self._roommate_exists(buyer_id):
            raise ValueError("请选择购买人")
        expires = bought + timedelta(days=days)
        now = self._now()
        with self.db:
            cur = self.db.execute("""INSERT INTO batches
                (name,unit,unit_price_cents,original_milli,remaining_milli,total_cents,
                 remaining_cents,buyer_id,purchase_date,shelf_days,expires_on,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, unit, unit_price, qty, qty, total, total, buyer_id,
                 bought.isoformat(), days, expires.isoformat(), now))
            self.db.execute("""INSERT INTO ledger
                (kind,occurred_at,actor_id,batch_id,quantity_milli,amount_cents)
                VALUES('purchase',?,?,?,?,?)""", (now, buyer_id, cur.lastrowid, qty, total))
            return cur.lastrowid

    def batches(self, in_stock_only: bool = False):
        where = "WHERE b.remaining_milli > 0" if in_stock_only else ""
        return self.db.execute(f"""SELECT b.*, r.name AS buyer_name,
            EXISTS(SELECT 1 FROM ledger l WHERE l.batch_id=b.id AND l.kind='waste') AS has_waste
            FROM batches b
            JOIN roommates r ON r.id=b.buyer_id {where} ORDER BY b.expires_on,b.id""").fetchall()

    def _remove(self, batch_id: int, amount: str, actor_id: int, kind: str,
                participant_ids: list[int] | None = None, reason: str = "",
                buyer_bears: bool = False) -> int:
        with self.db:
            batch = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if batch is None:
                raise ValueError("食材批次不存在")
            qty = parse_quantity(amount, batch["unit"])
            if qty > batch["remaining_milli"]:
                raise ValueError("数量超过剩余库存")
            if not self._roommate_exists(actor_id):
                raise ValueError("请选择操作人")
            if kind == "consume":
                people = sorted(set(participant_ids or []))
                if not 1 <= len(people) <= 3 or any(not self._roommate_exists(p) for p in people):
                    raise ValueError("请选择 1 到 3 位消耗人")
            else:
                people = []
                if not reason.strip():
                    raise ValueError("请输入报废原因")
            # Allocate all remaining cents to the last removal, so cumulative
            # rounding cannot leave value behind on an empty batch.
            cost = (batch["remaining_cents"] if qty == batch["remaining_milli"] else
                    int((Decimal(batch["total_cents"]) * qty / batch["original_milli"])
                        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
            cost = min(cost, batch["remaining_cents"])
            now = self._now()
            self.db.execute("""UPDATE batches SET remaining_milli=remaining_milli-?,
                remaining_cents=remaining_cents-? WHERE id=?""", (qty, cost, batch_id))
            cur = self.db.execute("""INSERT INTO ledger
                (kind,occurred_at,actor_id,batch_id,quantity_milli,amount_cents,reason,buyer_bears)
                VALUES(?,?,?,?,?,?,?,?)""", (kind, now, actor_id, batch_id, qty,
                                             cost, reason.strip() or None, int(buyer_bears)))
            if people:
                base, remainder = divmod(cost, len(people))
                self.db.executemany("""INSERT INTO allocations
                    (ledger_id,roommate_id,amount_cents) VALUES(?,?,?)""",
                    [(cur.lastrowid, person, base + (i < remainder))
                     for i, person in enumerate(people)])
            elif buyer_bears:
                self.db.execute("""INSERT INTO allocations
                    (ledger_id,roommate_id,amount_cents) VALUES(?,?,?)""",
                    (cur.lastrowid, batch["buyer_id"], cost))
            return cur.lastrowid

    def consume(self, batch_id: int, amount: str, actor_id: int,
                participant_ids: list[int]) -> int:
        return self._remove(batch_id, amount, actor_id, "consume", participant_ids)

    def waste(self, batch_id: int, amount: str, actor_id: int,
              reason: str, buyer_bears: bool = False) -> int:
        return self._remove(batch_id, amount, actor_id, "waste", reason=reason,
                            buyer_bears=buyer_bears)

    def summary(self):
        return self.db.execute("""SELECT r.id,r.name,
            COALESCE((SELECT sum(b.total_cents) FROM batches b WHERE b.buyer_id=r.id),0) AS purchases,
            COALESCE((SELECT sum(b.remaining_cents) FROM batches b WHERE b.buyer_id=r.id),0) AS remaining_contribution,
            COALESCE((SELECT sum(a.amount_cents) FROM allocations a
                JOIN ledger l ON l.id=a.ledger_id WHERE a.roommate_id=r.id AND l.kind='consume'),0) AS consumed,
            COALESCE((SELECT sum(a.amount_cents) FROM allocations a
                JOIN ledger l ON l.id=a.ledger_id WHERE a.roommate_id=r.id AND l.kind='waste'),0) AS waste_borne,
            COALESCE((SELECT sum(l.amount_cents) FROM ledger l JOIN batches b ON b.id=l.batch_id
                WHERE b.buyer_id=r.id AND l.kind='consume'),0) AS food_provided,
            COALESCE((SELECT sum(l.amount_cents) FROM ledger l JOIN batches b ON b.id=l.batch_id
                WHERE b.buyer_id=r.id AND l.kind='waste'),0) AS wasted_value
            FROM roommates r ORDER BY r.id""").fetchall()

    def stock_history(self):
        """Inventory value at the end of each day with an operation."""
        rows = self.db.execute("""SELECT substr(occurred_at,1,10) AS day,
            SUM(CASE WHEN kind='purchase' THEN amount_cents ELSE -amount_cents END) AS change_cents
            FROM ledger GROUP BY day ORDER BY day""").fetchall()
        total = 0
        history = []
        for row in rows:
            total += row["change_cents"]
            history.append((row["day"], total))
        return history

    def ledger(self, start: str = "", end: str = "", ingredient: str = "",
               person_id: int | None = None):
        sql = """SELECT l.*, b.name AS ingredient_name,b.unit,b.buyer_id,
            actor.name AS actor_name,buyer.name AS buyer_name,
            GROUP_CONCAT(person.name || ' ' || printf('%.2f',a.amount_cents/100.0),'、') AS allocation_text
            FROM ledger l JOIN batches b ON b.id=l.batch_id
            JOIN roommates actor ON actor.id=l.actor_id
            JOIN roommates buyer ON buyer.id=b.buyer_id
            LEFT JOIN allocations a ON a.ledger_id=l.id
            LEFT JOIN roommates person ON person.id=a.roommate_id WHERE 1=1"""
        params: list = []
        if start:
            date.fromisoformat(start)
            sql += " AND substr(l.occurred_at,1,10)>=?"
            params.append(start)
        if end:
            date.fromisoformat(end)
            sql += " AND substr(l.occurred_at,1,10)<=?"
            params.append(end)
        if ingredient:
            sql += " AND b.name LIKE ?"
            params.append(f"%{ingredient.strip()}%")
        if person_id is not None:
            sql += " AND (l.actor_id=? OR b.buyer_id=? OR EXISTS(SELECT 1 FROM allocations ax WHERE ax.ledger_id=l.id AND ax.roommate_id=?))"
            params += [person_id] * 3
        sql += " GROUP BY l.id ORDER BY l.occurred_at DESC,l.id DESC"
        return self.db.execute(sql, params).fetchall()
