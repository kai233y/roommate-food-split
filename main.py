"""Flet desktop UI for the shared pantry."""

from __future__ import annotations

import os
import shutil
import sys
from datetime import date
from pathlib import Path

# Python.org's macOS Python can have no configured CA bundle. Flet downloads
# its desktop client on first launch, so point urllib at a normal trusted CA
# bundle without disabling TLS verification.
if sys.platform == "darwin" and not os.environ.get("SSL_CERT_FILE"):
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
if sys.platform == "darwin" and shutil.which("open") is None:
    os.environ["PATH"] = os.pathsep.join(filter(None, [os.environ.get("PATH"), "/usr/bin", "/bin"]))

import flet as ft

from pantry import Pantry, money, quantity


DB_PATH = Path(os.environ.get("PANTRY_DB", Path(__file__).parent / "data" / "pantry.db"))
COLORS = [ft.Colors.TEAL_600, ft.Colors.BLUE_600, ft.Colors.ORANGE_700]


def main(page: ft.Page):
    pantry = Pantry(DB_PATH)
    page.title = "合租食材账本"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = ft.Colors.GREY_50
    page.padding = 24
    page.window.width = 1080
    page.window.height = 800
    current_tab = "总览"
    content = ft.Column(spacing=18, scroll=ft.ScrollMode.AUTO, expand=True)

    def tip(message: str):
        page.show_dialog(ft.SnackBar(ft.Text(message)))

    def run_action(action, success: str):
        try:
            action()
        except (ValueError, OverflowError) as exc:
            tip(str(exc))
            return False
        tip(success)
        render()
        return True

    def heading(title: str, subtitle: str = ""):
        return ft.Column([
            ft.Text(title, size=26, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
            ft.Text(subtitle, size=13, color=ft.Colors.BLUE_GREY_600),
        ], spacing=3)

    def card(*controls, width=None):
        return ft.Container(
            content=ft.Column(list(controls), spacing=12),
            width=width, padding=18, bgcolor=ft.Colors.WHITE,
            border_radius=14,
        )

    def person_options(include_all=False):
        options = [ft.DropdownOption(key="", text="全部人员")] if include_all else []
        return options + [ft.DropdownOption(key=str(p["id"]), text=p["name"])
                          for p in pantry.roommates()]

    def batch_options():
        return [ft.DropdownOption(key=str(b["id"]),
                text=f"#{b['id']} {b['name']} · {quantity(b['remaining_milli'], b['unit'])} · {b['buyer_name']}")
                for b in pantry.batches(True)]

    def open_consume(batch_id=None):
        batches = pantry.batches(True)
        if not batches:
            tip("当前没有可消耗的食材")
            return
        selected = ft.Dropdown(label="食材批次", width=470, options=batch_options(),
                               value=str(batch_id or batches[0]["id"]))
        amount = ft.TextField(label="消耗数量（kg 或个）", width=220, value="0.5")
        actor = ft.Dropdown(label="操作人", width=220, options=person_options())
        checks = [(p["id"], ft.Checkbox(label=p["name"])) for p in pantry.roommates()]

        def save(_):
            ids = [id_ for id_, check in checks if check.value]
            if run_action(lambda: pantry.consume(int(selected.value), amount.value,
                                                  int(actor.value or 0), ids), "已记录消耗及分摊"):
                page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True, title=ft.Text("记录食材消耗"),
            content=ft.Column([
                selected, ft.Row([amount, actor], wrap=True),
                ft.Text("选择实际消耗人，金额按人数均分"),
                ft.Row([check for _, check in checks], wrap=True),
            ], tight=True, spacing=12),
            actions=[ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                     ft.Button("确认消耗", on_click=save)],
        )
        page.show_dialog(dialog)

    def open_waste(batch_id: int):
        batch = next((b for b in pantry.batches(True) if b["id"] == batch_id), None)
        if batch is None:
            tip("该批次已无库存")
            return
        amount = ft.TextField(label=f"报废数量（最多 {quantity(batch['remaining_milli'],batch['unit'])}）",
                              value=quantity(batch["remaining_milli"], batch["unit"]).split()[0])
        reason = ft.TextField(label="报废原因", hint_text="例如：已过期或变质")
        actor = ft.Dropdown(label="操作人", options=person_options())
        buyer_bears = ft.Checkbox(label="由购买人承担报废金额（默认不计入任何人消耗）")

        def save(_):
            if run_action(lambda: pantry.waste(batch_id, amount.value, int(actor.value or 0),
                                                reason.value, bool(buyer_bears.value)),
                          "已记录报废"):
                page.pop_dialog()

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(f"报废 #{batch_id} {batch['name']}"),
            content=ft.Column([amount, reason, actor, buyer_bears], tight=True, spacing=12),
            actions=[ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                     ft.Button("确认报废", on_click=save)],
        ))

    def overview():
        stats = pantry.summary()
        batches = pantry.batches()
        active = [b for b in batches if b["remaining_milli"] > 0]
        remaining_value = sum(b["remaining_cents"] for b in active)
        total_consumed = sum(s["consumed"] for s in stats)
        tiles = ft.Row([
            card(ft.Text("在库批次", color=ft.Colors.BLUE_GREY_600),
                 ft.Text(str(len(active)), size=28, weight=ft.FontWeight.BOLD), width=225),
            card(ft.Text("剩余库存价值", color=ft.Colors.BLUE_GREY_600),
                 ft.Text(money(remaining_value), size=28, weight=ft.FontWeight.BOLD), width=225),
            card(ft.Text("累计食用金额", color=ft.Colors.BLUE_GREY_600),
                 ft.Text(money(total_consumed), size=28, weight=ft.FontWeight.BOLD), width=225),
        ], wrap=True, spacing=12)
        rows = []
        for i, s in enumerate(stats):
            # Purchased stock is not yet a settled expense. The transfer balance
            # counts only consumed food; waste is shown separately.
            balance = s["food_provided"] - s["consumed"]
            rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(str(s["id"]))),
                ft.DataCell(ft.Text(s["name"])), ft.DataCell(ft.Text(money(s["purchases"]))),
                ft.DataCell(ft.Text(money(s["remaining_contribution"]))),
                ft.DataCell(ft.Text(money(s["consumed"]))),
                ft.DataCell(ft.Text(money(s["waste_borne"]))),
                ft.DataCell(ft.Text(money(s["purchases"] - s["consumed"]))),
                ft.DataCell(ft.Text(money(balance), color=COLORS[i % 3]))]))
        table = ft.DataTable(columns=[ft.DataColumn(ft.Text(x)) for x in
            ("ID", "室友", "累计购买", "未消耗贡献", "个人食用", "承担报废", "贡献−消耗", "待结算净额")], rows=rows)
        max_cost = max([s["consumed"] for s in stats] + [1])
        bars = []
        for i, s in enumerate(stats):
            bars.append(ft.Row([
                ft.Text(s["name"], width=80),
                ft.Container(width=max(4, int(340 * s["consumed"] / max_cost)), height=22,
                             bgcolor=COLORS[i % 3], border_radius=5),
                ft.Text(money(s["consumed"])),
            ], spacing=10))
        history = pantry.stock_history()[-12:]
        max_stock = max([value for _, value in history] + [1])
        stock_bars = [ft.Row([
            ft.Text(day[5:], width=60),
            ft.Container(width=max(4, int(340 * value / max_stock)), height=18,
                         bgcolor=ft.Colors.TEAL_400, border_radius=5),
            ft.Text(money(value)),
        ], spacing=10) for day, value in history]
        return [heading("账本总览", "购买贡献、食用分摊和待结算金额一目了然"), tiles,
            card(ft.Text("室友账目", size=18, weight=ft.FontWeight.BOLD),
                 ft.Row([table], scroll=ft.ScrollMode.AUTO),
                 ft.Text("贡献−消耗 = 累计购买 − 个人食用（含未食用库存）；待结算净额 = 已被食用的贡献 − 个人食用，正数应收、负数应付。报废单列。",
                         size=12, color=ft.Colors.BLUE_GREY_600)),
            card(ft.Text("个人食用金额", size=18, weight=ft.FontWeight.BOLD),
                 *(bars or [ft.Text("添加室友和食材后显示图表")])),
            card(ft.Text("库存价值变化（最近 12 个操作日）", size=18, weight=ft.FontWeight.BOLD),
                 *(stock_bars or [ft.Text("入库后显示图表")]))]

    def roommates_view():
        name = ft.TextField(label="室友姓名", width=260, max_length=30)
        def add(_):
            if run_action(lambda: pantry.add_roommate(name.value), "已添加室友"):
                name.value = ""
        people = pantry.roommates()
        return [heading("室友管理", "最多添加 3 位室友，ID 将用于关联每笔购买和消耗"),
            card(ft.Row([name, ft.Button("添加室友", on_click=add, disabled=len(people) >= 3)], wrap=True),
                 ft.Text(f"已添加 {len(people)} / 3 位")),
            card(*([ft.Text(f"#{p['id']}  {p['name']}", size=16) for p in people]
                   or [ft.Text("尚无室友，请先添加")]))]

    def purchase_view():
        name = ft.TextField(label="食材名称", width=260)
        unit = ft.Dropdown(label="计量方式", width=180, value="weight", options=[
            ft.DropdownOption(key="weight", text="按重量（kg）"),
            ft.DropdownOption(key="piece", text="按个数")])
        price = ft.TextField(label="单价（元/kg 或元/个）", width=220, keyboard_type=ft.KeyboardType.NUMBER)
        amount = ft.TextField(label="购买数量（kg 或个）", width=220, keyboard_type=ft.KeyboardType.NUMBER)
        buyer = ft.Dropdown(label="购买人", width=220, options=person_options())
        bought = ft.TextField(label="购买日期 YYYY-MM-DD", width=220, value=date.today().isoformat())
        days = ft.TextField(label="保质期（天）", width=220, value="7", keyboard_type=ft.KeyboardType.NUMBER)
        preview = ft.Text("总价值将按单价 × 数量自动计算", color=ft.Colors.BLUE_GREY_600)

        def update_preview(_):
            try:
                from pantry import parse_price, parse_quantity
                from decimal import Decimal, ROUND_HALF_UP
                cents = int((Decimal(parse_price(price.value)) * parse_quantity(amount.value, unit.value)
                             / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                preview.value = f"预计总价值：{money(cents)}"
            except (ValueError, TypeError):
                preview.value = "填写单价和数量后显示总价值"
            page.update()
        price.on_change = update_preview
        amount.on_change = update_preview
        unit.on_select = update_preview

        def save(_):
            if run_action(lambda: pantry.purchase(name.value, unit.value, price.value, amount.value,
                                                   int(buyer.value or 0), bought.value, days.value),
                          "食材已入库"):
                name.value = ""

        return [heading("食材入库", "每次购买生成独立批次，按购买人记录贡献"),
            card(ft.Row([name, unit], wrap=True, spacing=12),
                 ft.Row([price, amount], wrap=True, spacing=12),
                 ft.Row([buyer, bought, days], wrap=True, spacing=12),
                 preview, ft.Button("确认入库", on_click=save,
                                    disabled=len(pantry.roommates()) == 0))]

    def inventory_view():
        batches = pantry.batches()
        today = date.today().isoformat()
        rows = []
        for b in batches:
            state = ("已报废" if b["remaining_milli"] == 0 and b["has_waste"] else
                     "已用完" if b["remaining_milli"] == 0 else
                     "已过期 / 部分报废" if b["expires_on"] < today and b["has_waste"] else
                     "已过期" if b["expires_on"] < today else
                     "部分报废" if b["has_waste"] else "在库")
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(f"#{b['id']} {b['name']}")),
                ft.DataCell(ft.Text("重量" if b["unit"] == "weight" else "个数")),
                ft.DataCell(ft.Text(quantity(b["remaining_milli"], b["unit"]))),
                ft.DataCell(ft.Text(money(b["remaining_cents"]))),
                ft.DataCell(ft.Text(b["buyer_name"])),
                ft.DataCell(ft.Text(b["expires_on"])),
                ft.DataCell(ft.Text(state)),
                ft.DataCell(ft.Row([
                    ft.TextButton("消耗", on_click=lambda _, id_=b["id"]: open_consume(id_),
                                  disabled=b["remaining_milli"] == 0),
                    ft.TextButton("报废", on_click=lambda _, id_=b["id"]: open_waste(id_),
                                  disabled=b["remaining_milli"] == 0),
                ], spacing=0)),
            ]))
        table = ft.DataTable(columns=[ft.DataColumn(ft.Text(x)) for x in
            ("批次 / 食材", "类型", "剩余量", "剩余价值", "购买人", "到期日", "状态", "操作")], rows=rows)
        return [heading("食材库存", "按购买批次查看剩余库存和到期情况"),
            ft.Row([ft.Button("记录消耗", on_click=lambda _: open_consume(), disabled=not any(
                b["remaining_milli"] for b in batches))]),
            card(ft.Row([table], scroll=ft.ScrollMode.AUTO) if batches else ft.Text("暂无食材，先去入库"))]

    def ledger_view():
        start = ft.TextField(label="开始日期 YYYY-MM-DD", width=205)
        end = ft.TextField(label="结束日期 YYYY-MM-DD", width=205)
        ingredient = ft.TextField(label="食材名称", width=190)
        person = ft.Dropdown(label="相关人员", width=180, value="", options=person_options(True))
        result = ft.Column(spacing=8)
        def search(_=None):
            try:
                records = pantry.ledger(start.value or "", end.value or "",
                                        ingredient.value or "", int(person.value) if person.value else None)
            except ValueError:
                tip("筛选日期格式须为 YYYY-MM-DD")
                return
            result.controls = []
            for l in records:
                action = {"purchase": "入库", "consume": "消耗", "waste": "报废"}[l["kind"]]
                detail = f"{action} · #{l['batch_id']} {l['ingredient_name']} · {quantity(l['quantity_milli'], l['unit'])} · {money(l['amount_cents'])}"
                extra = (f"分摊：{l['allocation_text']} 元" if l["kind"] == "consume" else
                         f"原因：{l['reason']} · {'购买人承担' if l['buyer_bears'] else '不分摊'}" if l["kind"] == "waste" else
                         f"购买人：{l['buyer_name']}")
                result.controls.append(card(ft.Text(detail, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{l['occurred_at'][:19].replace('T',' ')} · 操作人：{l['actor_name']} · {extra}",
                            size=12, color=ft.Colors.BLUE_GREY_600)))
            if not records:
                result.controls = [ft.Text("没有匹配的流水")]
            page.update()
        search()
        return [heading("流水追溯", "记录每笔入库、消耗和报废，支持组合筛选"),
            card(ft.Row([start, end, ingredient, person, ft.Button("筛选", on_click=search)],
                        wrap=True, spacing=10)), result]

    def render():
        tabs = ["总览", "室友", "入库", "库存", "流水"]
        navigation = ft.Row([
            ft.Button(t, on_click=lambda _, tab=t: select_tab(tab),
                      bgcolor=ft.Colors.TEAL_100 if t == current_tab else ft.Colors.WHITE)
            for t in tabs], wrap=True, spacing=8)
        views = {"总览": overview, "室友": roommates_view, "入库": purchase_view,
                 "库存": inventory_view, "流水": ledger_view}
        content.controls = [ft.Text("合租食材账本", size=16, weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.TEAL_700), navigation, ft.Divider(),
                            *views[current_tab]()]
        page.update()

    def select_tab(tab: str):
        nonlocal current_tab
        current_tab = tab
        render()

    page.add(content)
    render()


if __name__ == "__main__":
    ft.run(main)
