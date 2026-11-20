"""同单连带分析业务规则。

口径要点（与需求逐条对应）：

1. 购物篮取数：按订单编号 + 订单行接收 商品类目 / 订单行状态 / 实际件数；
   同一行重复导入按业务键 upsert，不会让含该类目的订单数重复增加。
2. 净件数恢复：退款明细关联到原订单行，只把「已复核」的退款从实际件数中扣减；
   部分退款（净件数 > 0）保留在购物篮，净件数归零才把该行从该单移出。
3. 同单去重：同一类目在同一订单有多行时只贡献一次（按订单-类目聚合）。
4. 样本规模：以「有效订单」（至少还剩一个有效类目）为 N。
5. 套装来源更正：同一套装展开的成分类目直接合计会抬高成分之间的连带值，
   当两个成分在该单都仅由同一个套装展开产生时，这一单不计入它们的同单次数，
   剔除数量逐格登记并在矩阵里展示。
6. 复核退款后允许按更正口径重算：每次重算生成一条同单连带分析记录（新版本），
   矩阵、联购单元格与有效购物篮都按当前最新口径重建。
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from app.store import store

MODULE_ORDER_LINE = "basket_order_line"
MODULE_REFUND = "basket_refund"
MODULE_RUN = "basket_analysis_run"
MODULE_CELL = "basket_affinity_cell"
MODULE_BASKET = "basket_valid_basket"

# 订单行状态：只有「正常」参与购物篮；取消 / 关闭等状态整行无效。
VALID_LINE_STATUSES = {"正常"}
INVALID_LINE_STATUSES = {"已取消", "已关闭"}
# 退款复核状态：只有已复核的退款参与净件数恢复。
REFUND_REVIEWED = "已复核"
REFUND_PENDING = "待复核"
REFUND_STATUSES = {REFUND_PENDING, REFUND_REVIEWED}
# 订单行来源类型。
SOURCE_ORIGINAL = "原始订单行"
SOURCE_BUNDLE_MAIN = "套装主行"
SOURCE_BUNDLE_PART = "套装展开成分"

REQUIRED_LINE_FIELDS = ["订单编号", "订单行编号", "商品类目", "订单行状态", "实际件数"]
REQUIRED_REFUND_FIELDS = ["退款编号", "订单编号", "订单行编号", "退款件数", "复核状态"]


def _to_int(value: Any, field: str, errors: list[str]) -> int | None:
    """把件数转成非负整数；转换失败时登记一条可读错误并返回 None。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field}「{value}」不是整数件数")
        return None
    if number < 0:
        errors.append(f"{field}不能为负：{number}")
        return None
    return number


class BasketAnalysisService:
    """购物篮取数、退款恢复与联购矩阵计算都收敛在这一个服务里。"""

    # ------------------------------------------------------------------ 取数
    def import_lines(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        """批量导入订单行。

        业务键为（订单编号, 订单行编号）：重复导入时整行覆盖更新而不是新增，
        因此重复导入不会增加含该类目的订单数。整批先校验再落库，任一行不合规
        则整批拒收，避免半成品口径污染后续矩阵。
        """
        if not isinstance(lines, list) or not lines:
            return {"ok": False, "message": "订单行列表为空，未导入任何数据", "errors": ["lines 为空"]}

        normalized: list[dict[str, Any]] = []
        errors: list[str] = []
        seen_keys: set[tuple[str, str]] = set()
        for index, raw in enumerate(lines, start=1):
            if not isinstance(raw, dict):
                errors.append(f"第 {index} 行不是对象结构")
                continue
            missing = [f for f in REQUIRED_LINE_FIELDS if str(raw.get(f) or "").strip() == ""]
            if missing:
                errors.append(f"第 {index} 行缺少必填字段：{'、'.join(missing)}")
                continue
            qty = _to_int(raw.get("实际件数"), f"第 {index} 行实际件数", errors)
            if qty is None:
                continue
            status = str(raw["订单行状态"]).strip()
            if status not in VALID_LINE_STATUSES and status not in INVALID_LINE_STATUSES:
                errors.append(f"第 {index} 行订单行状态「{status}」不受支持")
                continue
            key = (str(raw["订单编号"]).strip(), str(raw["订单行编号"]).strip())
            if key in seen_keys:
                errors.append(f"第 {index} 行业务键 {key[0]}/{key[1]} 在本批次重复")
                continue
            seen_keys.add(key)
            source_type = str(raw.get("来源类型") or SOURCE_ORIGINAL).strip()
            if source_type not in {SOURCE_ORIGINAL, SOURCE_BUNDLE_MAIN, SOURCE_BUNDLE_PART}:
                errors.append(f"第 {index} 行来源类型「{source_type}」不受支持")
                continue
            normalized.append({
                "订单编号": key[0],
                "订单行编号": key[1],
                "商品类目": str(raw["商品类目"]).strip(),
                "订单行状态": status,
                "实际件数": qty,
                "来源类型": source_type,
                "套装编号": str(raw.get("套装编号") or "").strip(),
                "商品名称": str(raw.get("商品名称") or "").strip(),
            })

        if errors:
            return {"ok": False, "message": "订单行校验未通过，整批未导入", "errors": errors}

        rows = store.rows(MODULE_ORDER_LINE)
        indexed = {(r["订单编号"], r["订单行编号"]): r for r in rows}
        inserted = updated = 0
        for line in normalized:
            old = indexed.get((line["订单编号"], line["订单行编号"]))
            if old is None:
                line["id"] = self._next_id(rows)
                rows.append(line)
                indexed[(line["订单编号"], line["订单行编号"])] = line
                inserted += 1
            else:
                line["id"] = old["id"]
                old.update(line)
                updated += 1
        return {
            "ok": True,
            "message": f"订单行导入完成：新增 {inserted} 行、更新 {updated} 行（重复导入按业务键覆盖，不重复计单）",
            "inserted": inserted,
            "updated": updated,
            "total": len(rows),
        }

    def list_lines(self, order_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE_ORDER_LINE)
        if order_no:
            rows = [r for r in rows if r["订单编号"] == order_no.strip()]
        return sorted(rows, key=lambda r: (r["订单编号"], r["订单行编号"]))

    # ------------------------------------------------------------------ 退款
    def import_refunds(self, refunds: list[dict[str, Any]]) -> dict[str, Any]:
        """批量导入退款明细；退款编号是业务键，重导覆盖，便于按更正口径重算。"""
        if not isinstance(refunds, list) or not refunds:
            return {"ok": False, "message": "退款明细列表为空，未导入任何数据", "errors": ["refunds 为空"]}

        normalized: list[dict[str, Any]] = []
        errors: list[str] = []
        seen_keys: set[str] = set()
        line_index = {(r["订单编号"], r["订单行编号"]): r for r in store.rows(MODULE_ORDER_LINE)}
        for index, raw in enumerate(refunds, start=1):
            if not isinstance(raw, dict):
                errors.append(f"第 {index} 条退款不是对象结构")
                continue
            missing = [f for f in REQUIRED_REFUND_FIELDS if str(raw.get(f) or "").strip() == ""]
            if missing:
                errors.append(f"第 {index} 条退款缺少必填字段：{'、'.join(missing)}")
                continue
            qty = _to_int(raw.get("退款件数"), f"第 {index} 条退款件数", errors)
            if qty is None:
                continue
            review_status = str(raw["复核状态"]).strip()
            if review_status not in REFUND_STATUSES:
                errors.append(f"第 {index} 条退款复核状态「{review_status}」不受支持")
                continue
            order_no = str(raw["订单编号"]).strip()
            line_no = str(raw["订单行编号"]).strip()
            origin = line_index.get((order_no, line_no))
            if origin is None:
                errors.append(f"第 {index} 条退款关联的原订单行 {order_no}/{line_no} 不存在")
                continue
            refund_no = str(raw["退款编号"]).strip()
            if refund_no in seen_keys:
                errors.append(f"第 {index} 条退款编号 {refund_no} 在本批次重复")
                continue
            seen_keys.add(refund_no)
            normalized.append({
                "退款编号": refund_no,
                "订单编号": order_no,
                "订单行编号": line_no,
                "退款件数": qty,
                "复核状态": review_status,
                "关联类目": origin["商品类目"],
            })

        # 同一原订单行的累计（含已存在的复核退款）不能超过实际件数。
        rows = store.rows(MODULE_REFUND)
        existing_qty: dict[tuple[str, str], int] = defaultdict(int)
        for r in rows:
            if r["复核状态"] == REFUND_REVIEWED:
                existing_qty[(r["订单编号"], r["订单行编号"])] += int(r["退款件数"])
        planned_qty = dict(existing_qty)
        for refund in normalized:
            key = (refund["订单编号"], refund["订单行编号"])
            if refund["复核状态"] == REFUND_REVIEWED:
                planned_qty[key] = planned_qty.get(key, 0) + refund["退款件数"]
        for key, total_refund in planned_qty.items():
            origin = line_index.get(key)
            if origin is not None and total_refund > int(origin["实际件数"]):
                errors.append(
                    f"原订单行 {key[0]}/{key[1]} 累计复核退款 {total_refund} 件超过实际件数 {origin['实际件数']} 件"
                )

        if errors:
            return {"ok": False, "message": "退款明细校验未通过，整批未导入", "errors": errors}

        indexed = {r["退款编号"]: r for r in rows}
        inserted = updated = 0
        for refund in normalized:
            old = indexed.get(refund["退款编号"])
            if old is None:
                refund["id"] = self._next_id(rows)
                rows.append(refund)
                indexed[refund["退款编号"]] = refund
                inserted += 1
            else:
                refund["id"] = old["id"]
                old.update(refund)
                updated += 1
        return {
            "ok": True,
            "message": f"退款明细导入完成：新增 {inserted} 条、更新 {updated} 条",
            "inserted": inserted,
            "updated": updated,
            "total": len(rows),
        }

    def list_refunds(self, review_status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE_REFUND)
        if review_status:
            rows = [r for r in rows if r["复核状态"] == review_status.strip()]
        return sorted(rows, key=lambda r: (r["复核状态"], r["订单编号"], r["退款编号"]))

    def review_refund(self, refund_id: int) -> tuple[dict[str, Any] | None, str]:
        """复核通过一条退款：状态置为已复核，之后重算即按更正口径恢复净件数。"""
        refund = store.find(MODULE_REFUND, refund_id)
        if refund is None:
            return None, f"退款明细 {refund_id} 不存在"
        if refund["复核状态"] == REFUND_REVIEWED:
            return refund, "该退款已复核，无需重复操作"
        origin = next(
            (r for r in store.rows(MODULE_ORDER_LINE)
             if r["订单编号"] == refund["订单编号"] and r["订单行编号"] == refund["订单行编号"]),
            None,
        )
        reviewed_total = sum(
            int(r["退款件数"]) for r in store.rows(MODULE_REFUND)
            if (r["订单编号"], r["订单行编号"]) == (refund["订单编号"], refund["订单行编号"])
            and r["复核状态"] == REFUND_REVIEWED
        ) + int(refund["退款件数"])
        if origin is not None and reviewed_total > int(origin["实际件数"]):
            return None, (
                f"复核后累计退款 {reviewed_total} 件超过原订单行实际件数 "
                f"{origin['实际件数']} 件，请先更正退款口径"
            )
        refund["复核状态"] = REFUND_REVIEWED
        return refund, f"退款 {refund['退款编号']} 已复核，重算后按更正口径恢复净件数"

    # ------------------------------------------------------------- 净件数/购物篮
    def _refunded_qty(self, order_no: str, line_no: str) -> int:
        """已复核退款关联回原订单行的累计退款件数；待复核退款不参与。"""
        return sum(
            int(r["退款件数"]) for r in store.rows(MODULE_REFUND)
            if r["订单编号"] == order_no and r["订单行编号"] == line_no
            and r["复核状态"] == REFUND_REVIEWED
        )

    def build_baskets(self) -> dict[str, Any]:
        """按当前订单行 + 已复核退款重建有效购物篮。

        返回每个有效订单的类目集合、每个类目在该单的来源，以及逐行净件数，
        供矩阵计算与「核对有效购物篮」界面共用。
        """
        # 订单 -> 类目 -> 该类目在本单的来源行集合（同单同类目多行只贡献一次）。
        order_categories: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        line_details: list[dict[str, Any]] = []
        invalid_lines = 0
        zeroed_lines = 0

        for line in store.rows(MODULE_ORDER_LINE):
            order_no = line["订单编号"]
            refunded = self._refunded_qty(order_no, line["订单行编号"])
            net_qty = int(line["实际件数"]) - refunded
            detail = {
                "订单编号": order_no,
                "订单行编号": line["订单行编号"],
                "商品类目": line["商品类目"],
                "商品名称": line.get("商品名称", ""),
                "订单行状态": line["订单行状态"],
                "来源类型": line["来源类型"],
                "套装编号": line.get("套装编号", ""),
                "实际件数": line["实际件数"],
                "已退款件数": refunded,
                "净件数": net_qty,
                "是否计入购物篮": False,
                "移出原因": "",
            }
            if line["订单行状态"] not in VALID_LINE_STATUSES:
                detail["移出原因"] = f"订单行状态为{line['订单行状态']}，整行无效"
                invalid_lines += 1
            elif net_qty <= 0:
                detail["移出原因"] = "复核退款后净件数归零，从该单移出"
                zeroed_lines += 1
            else:
                detail["是否计入购物篮"] = True
                order_categories[order_no][line["商品类目"]].append({
                    "来源类型": line["来源类型"],
                    "套装编号": line.get("套装编号", ""),
                    "订单行编号": line["订单行编号"],
                    "净件数": net_qty,
                })
            line_details.append(detail)

        baskets: list[dict[str, Any]] = []
        for order_no in sorted(order_categories):
            categories = order_categories[order_no]
            if not categories:
                continue
            cat_sources: dict[str, dict[str, Any]] = {}
            for category, sources in categories.items():
                source_types = sorted({s["来源类型"] for s in sources})
                bundle_ids = sorted({s["套装编号"] for s in sources if s["套装编号"]})
                cat_sources[category] = {
                    "source_types": source_types,
                    "bundle_ids": bundle_ids,
                    "lines": [s["订单行编号"] for s in sources],
                }
            baskets.append({
                "订单编号": order_no,
                "类目集合": sorted(categories),
                "类目来源": cat_sources,
            })

        return {
            "baskets": baskets,
            "line_details": sorted(line_details, key=lambda d: (d["订单编号"], d["订单行编号"])),
            "invalid_line_count": invalid_lines,
            "zeroed_line_count": zeroed_lines,
        }

    # ------------------------------------------------------------------ 矩阵
    def recompute(self, remark: str | None = None) -> dict[str, Any]:
        """按更正口径重算联购记录，落一条分析版本并重建单元格 / 有效购物篮表。"""
        built = self.build_baskets()
        baskets = built["baskets"]
        sample_size = len(baskets)

        # 各类目单独出现次数：同一订单同类目多行只贡献一次。
        support: dict[str, int] = defaultdict(int)
        for basket in baskets:
            for category in basket["类目集合"]:
                support[category] += 1
        categories = sorted(support, key=lambda c: (-support[c], c))

        # 两个类目同时出现的次数，并按套装来源更正规则登记剔除。
        pair_orders: dict[tuple[str, str], list[str]] = defaultdict(list)
        pair_excluded: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for basket in baskets:
            order_no = basket["订单编号"]
            cat_sources = basket["类目来源"]
            for cat_a, cat_b in combinations(basket["类目集合"], 2):
                if self._is_same_bundle_only(cat_sources[cat_a], cat_sources[cat_b]):
                    pair_excluded[(cat_a, cat_b)].append({
                        "订单编号": order_no,
                        "套装编号": cat_sources[cat_a]["bundle_ids"][0],
                    })
                    continue
                pair_orders[(cat_a, cat_b)].append(order_no)

        run_rows = store.rows(MODULE_RUN)
        run_id = self._next_id(run_rows)
        run = {
            "id": run_id,
            "分析编号": f"AFIN-{run_id:04d}",
            "样本规模": sample_size,
            "类目数量": len(categories),
            "无效行数": built["invalid_line_count"],
            "归零移出行数": built["zeroed_line_count"],
            "待复核退款数": sum(1 for r in store.rows(MODULE_REFUND) if r["复核状态"] == REFUND_PENDING),
            "已复核退款数": sum(1 for r in store.rows(MODULE_REFUND) if r["复核状态"] == REFUND_REVIEWED),
            "备注": remark or "按当前已复核退款口径重算",
        }
        run_rows.append(run)

        cell_rows = store.rows(MODULE_CELL)
        cells: list[dict[str, Any]] = []
        for cat_a in categories:
            for cat_b in categories:
                if cat_a == cat_b:
                    lift = 1.0
                    co_count = support[cat_a]
                    orders: list[str] = [b["订单编号"] for b in baskets if cat_a in b["类目集合"]]
                    excluded: list[dict[str, str]] = []
                else:
                    key = tuple(sorted((cat_a, cat_b)))
                    orders = sorted(pair_orders.get(key, []))
                    excluded = pair_excluded.get(key, [])
                    co_count = len(orders)
                    lift = self._lift(support[cat_a], support[cat_b], co_count, sample_size)
                cell = {
                    "id": self._next_id(cell_rows),
                    "分析编号": run["分析编号"],
                    "类目A": cat_a,
                    "类目B": cat_b,
                    "类目A单数": support[cat_a],
                    "类目B单数": support[cat_b],
                    "同单次数": co_count,
                    "剔除数": len(excluded),
                    "提升倍数": round(lift, 4) if lift is not None else None,
                    "样本规模": sample_size,
                    "联合订单": orders,
                    "剔除明细": excluded,
                }
                cell_rows.append(cell)
                cells.append(cell)

        # 有效购物篮落表，支撑「点开分值查订单集合 / 核对有效购物篮」。
        basket_rows = store.rows(MODULE_BASKET)
        for basket in baskets:
            basket_rows.append({
                "id": self._next_id(basket_rows),
                "分析编号": run["分析编号"],
                "订单编号": basket["订单编号"],
                "有效类目": "、".join(basket["类目集合"]),
                "类目来源": basket["类目来源"],
            })

        return {
            "ok": True,
            "message": f"联购记录已重算：样本 {sample_size} 个有效订单、{len(categories)} 个类目",
            "run": run,
            "categories": categories,
            "support": dict(support),
            "cells": cells,
            "baskets": baskets,
            "line_details": built["line_details"],
        }

    @staticmethod
    def _is_same_bundle_only(source_a: dict[str, Any], source_b: dict[str, Any]) -> bool:
        """两个成分是否在该单都仅由同一个套装展开产生。

        任一方还存在原始订单行 / 套装主行来源时，说明这一单的同单关系并非纯粹
        由套装展开制造，不应剔除。
        """
        pure_part_a = source_a["source_types"] == [SOURCE_BUNDLE_PART]
        pure_part_b = source_b["source_types"] == [SOURCE_BUNDLE_PART]
        if not (pure_part_a and pure_part_b):
            return False
        bundles_a = source_a.get("bundle_ids", [])
        bundles_b = source_b.get("bundle_ids", [])
        return len(bundles_a) == 1 and bundles_a == bundles_b

    @staticmethod
    def _lift(support_a: int, support_b: int, co_count: int, sample_size: int) -> float | None:
        """提升倍数 = P(B|A)/P(B) = (co/N) / (a/N * b/N)。"""
        if sample_size <= 0 or support_a <= 0 or support_b <= 0:
            return None
        expected = (support_a * support_b) / sample_size
        return co_count / expected if expected > 0 else None

    def list_runs(self) -> list[dict[str, Any]]:
        return sorted(store.rows(MODULE_RUN), key=lambda r: -int(r["id"]))

    def latest_run_no(self) -> str | None:
        runs = self.list_runs()
        return runs[0]["分析编号"] if runs else None

    def matrix(self, run_no: str | None = None) -> dict[str, Any]:
        """读同单连带分析表生成联购矩阵视图：每格含提升倍数、可比样本量、剔除数。"""
        run_no = run_no or self.latest_run_no()
        if run_no is None:
            return {"ok": False, "message": "尚未生成联购记录，请先触发重算", "cells": [], "categories": []}
        run = next((r for r in store.rows(MODULE_RUN) if r["分析编号"] == run_no), None)
        if run is None:
            return {"ok": False, "message": f"分析记录 {run_no} 不存在", "cells": [], "categories": []}
        cells = [c for c in store.rows(MODULE_CELL) if c["分析编号"] == run_no]
        categories = sorted({c["类目A"] for c in cells}, key=lambda c: (-self._support_of(cells, c), c))
        return {"ok": True, "run": run, "categories": categories, "cells": cells}

    @staticmethod
    def _support_of(cells: list[dict[str, Any]], category: str) -> int:
        for cell in cells:
            if cell["类目A"] == category and cell["类目B"] == category:
                return int(cell["类目A单数"])
        return 0

    def pair_detail(self, cat_a: str, cat_b: str, run_no: str | None = None) -> dict[str, Any]:
        """点开矩阵中的提升倍数：返回联合订单及其来源，并附有效购物篮用于核对。"""
        run_no = run_no or self.latest_run_no()
        if run_no is None:
            return {"ok": False, "message": "尚未生成联购记录，请先触发重算"}
        cell = next(
            (c for c in store.rows(MODULE_CELL)
             if c["分析编号"] == run_no and {c["类目A"], c["类目B"]} == {cat_a, cat_b}),
            None,
        )
        if cell is None:
            return {"ok": False, "message": f"分析 {run_no} 中没有类目对 {cat_a} / {cat_b}"}
        baskets = [
            b for b in store.rows(MODULE_BASKET)
            if b["分析编号"] == run_no and b["订单编号"] in cell["联合订单"]
        ]
        baskets.sort(key=lambda b: b["订单编号"])
        return {
            "ok": True,
            "run_no": run_no,
            "cell": cell,
            "baskets": baskets,
            "excluded_orders": cell["剔除明细"],
        }

    def valid_baskets(self, run_no: str | None = None) -> list[dict[str, Any]]:
        run_no = run_no or self.latest_run_no()
        if run_no is None:
            return []
        return sorted(
            (b for b in store.rows(MODULE_BASKET) if b["分析编号"] == run_no),
            key=lambda b: b["订单编号"],
        )

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(r.get("id", 0)) for r in rows), default=0) + 1


service = BasketAnalysisService()
