"""同单连带分析口径测试：直接 python3 tests/test_basket_analysis.py 运行。

覆盖需求要点：
1. 同单同类目多行只贡献一次；重复导入不增加含该类目的订单数；
2. 已复核退款按原订单行恢复净件数，部分退款保留、归零才移出；
3. 有效订单样本规模、各类目单数、两两类目同单次数与提升倍数；
4. 套装来源更正：纯同套装展开的成分连带被剔除，混合来源不剔除；
5. 复核退款后重算，矩阵与有效购物篮按更正口径变化；
6. pair 查询返回联合订单及其来源，可核对有效购物篮。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PASS = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global PASS
    assert condition, f"[{label}] {detail}"
    PASS += 1
    print(f"  ✓ {label}")


def cell(matrix: dict, cat_a: str, cat_b: str) -> dict:
    for c in matrix["cells"]:
        if c["类目A"] == cat_a and c["类目B"] == cat_b:
            return c
    raise AssertionError(f"未找到单元格 {cat_a} x {cat_b}")


# ---------------------------------------------------------------- 1. 初始矩阵
print("【1】用两个真实类目的有效订单生成矩阵（首次重算）")
r = client.post("/api/basket_analysis/recompute", json={"remark": "首版口径"})
check("重算接口返回 ok", r.json()["ok"] is True, r.text)
run1 = r.json()["run"]
check("首版样本规模=10 个有效订单", run1["样本规模"] == 10, run1)

matrix = client.get("/api/basket_analysis/matrix").json()
check("矩阵覆盖 6 个类目", len(matrix["categories"]) == 6, matrix["categories"])

# 各类目单独出现次数（同单同类目多行只贡献一次；取消行不计）
support = {c["类目A"]: c["类目A单数"] for c in matrix["cells"] if c["类目A"] == c["类目B"]}
# 运动鞋：SO-1001/1002/1005/1010（SO-1009 取消、SO-1010 两行合一）共 4 单
expect_support = {"运动鞋": 4, "T恤": 4, "卫衣": 4, "季节性套装": 3, "上衣": 3, "裤子": 3}
check("各类目单独出现次数正确", support == expect_support, support)

# 两个真实类目：运动鞋 × T恤 同单 2 次（SO-1001、SO-1005；SO-1009 运动鞋行已取消）
c_st = cell(matrix, "运动鞋", "T恤")
check("运动鞋×T恤 同单次数=2", c_st["同单次数"] == 2, c_st)
check("真实类目无套装剔除", c_st["剔除数"] == 0, c_st)
# lift = (2/10) / (4/10 * 4/10) = 1.25
check("运动鞋×T恤 提升倍数=1.25", abs(c_st["提升倍数"] - 1.25) < 1e-6, c_st)

# 提升倍数 >1 的强连带：运动鞋 × 卫衣（SO-1002、SO-1005、SO-1010）
c_sh = cell(matrix, "运动鞋", "卫衣")
check("运动鞋×卫衣 同单次数=3", c_sh["同单次数"] == 3, c_sh)
# lift = (3/10)/(4/10*4/10) = 1.875
check("运动鞋×卫衣 提升倍数=1.875", abs(c_sh["提升倍数"] - 1.875) < 1e-6, c_sh)

# 同单同类目多行：SO-1010 运动鞋两行，仍只贡献一次
baskets = client.get("/api/basket_analysis/baskets").json()["items"]
b1010 = next(b for b in baskets if b["订单编号"] == "SO-1010")
check("SO-1010 运动鞋多行只贡献一次", b1010["有效类目"].count("运动鞋") == 1, b1010)

# 取消行：SO-1009 只剩 T恤
b1009 = next(b for b in baskets if b["订单编号"] == "SO-1009")
check("SO-1009 取消行被移出，仅留 T恤", b1010 and b1009["有效类目"] == "T恤", b1009)

# ------------------------------------------------------------ 2. 套装来源更正
print("【2】套装来源更正：纯同套装展开的成分连带被剔除")
c_top_pants = cell(matrix, "上衣", "裤子")
# SO-1006、SO-1008 纯套装 -> 剔除；SO-1007 上衣含原始行 -> 保留
check("上衣×裤子 同单次数=1（仅 SO-1007）", c_top_pants["同单次数"] == 1, c_top_pants)
check("上衣×裤子 剔除数=2", c_top_pants["剔除数"] == 2, c_top_pants)
excluded_orders = {e["订单编号"] for e in c_top_pants["剔除明细"]}
check("剔除明细指向 SO-1006/SO-1008", excluded_orders == {"SO-1006", "SO-1008"}, excluded_orders)

# 若直接合计不剔除，同单应为 3、lift=3.33；更正后 lift=1.11
# lift = (1/10)/(3/10*3/10) = 1.1111
check("上衣×裤子 提升倍数已被压低=1.1111", abs(c_top_pants["提升倍数"] - 10 / 9) < 1e-3, c_top_pants)

# 混合来源不剔除：上衣 在 SO-1007 同时有展开行与原始行
c_season_top = cell(matrix, "季节性套装", "上衣")
check("套装主行×上衣 不剔除（3 单全保留）", c_season_top["同单次数"] == 3 and c_season_top["剔除数"] == 0, c_season_top)

# ------------------------------------------------------- 3. 重复导入不重复计单
print("【3】订单行重复导入：覆盖更新，含该类目的订单数不增加")
before = support["运动鞋"]
r = client.post("/api/basket_analysis/lines/import", json={"lines": [
    {"订单编号": "SO-1010", "订单行编号": "L01", "商品类目": "运动鞋", "订单行状态": "正常", "实际件数": 1, "来源类型": "原始订单行"},
]})
check("重复导入识别为更新", r.json()["updated"] == 1 and r.json()["inserted"] == 0, r.json())
client.post("/api/basket_analysis/recompute", json={"remark": "重复导入后重算"})
matrix2 = client.get("/api/basket_analysis/matrix").json()
support2 = {c["类目A"]: c["类目A单数"] for c in matrix2["cells"] if c["类目A"] == c["类目B"]}
check("重复导入后运动鞋订单数不变", support2["运动鞋"] == before, (before, support2["运动鞋"]))

# 非法行整批拒收
r = client.post("/api/basket_analysis/lines/import", json={"lines": [
    {"订单编号": "SO-X", "订单行编号": "L01", "商品类目": "运动鞋", "订单行状态": "正常", "实际件数": -2},
]})
check("负件数整批拒收", r.json()["ok"] is False and r.json()["errors"], r.json())

# ------------------------------------------------- 4. 补交套装退货明细 + 复核重算
print("【4】补交一张套装的退货明细，复核后按更正口径重算")
# 先以「待复核」补交：SO-1008 整套退货（主行+两个展开行各 1 件）
refund_lines = [
    ("RF-1001", "SO-1008", "L01", "季节性套装", 1),
    ("RF-1002", "SO-1008", "L02", "上衣", 1),
    ("RF-1003", "SO-1008", "L03", "裤子", 1),
]
r = client.post("/api/basket_analysis/refunds/import", json={"refunds": [
    {"退款编号": no, "订单编号": o, "订单行编号": l, "退款件数": q, "复核状态": "待复核"}
    for no, o, l, _cat, q in refund_lines
]})
check("退货明细导入成功", r.json()["ok"] is True, r.json())

# 待复核阶段重算：净件数未恢复，SO-1008 仍是有效单
r = client.post("/api/basket_analysis/recompute", json={"remark": "退货待复核"})
check("待复核阶段样本规模仍=10", r.json()["run"]["样本规模"] == 10, r.json()["run"])
check("待复核退款计数=4（含种子 RF-0001）", r.json()["run"]["待复核退款数"] == 4, r.json()["run"])

# 复核三条退款（id 为退款表中的 2/3/4，种子 RF-0001 占 id=1）
for refund_id in (2, 3, 4):
    rr = client.post(f"/api/basket_analysis/refunds/{refund_id}/review")
    check(f"退款 {refund_id} 复核通过", rr.json()["ok"] is True, rr.text)

# 重算：SO-1008 三个行净件数全部归零 -> 整单移出
r = client.post("/api/basket_analysis/recompute", json={"remark": "套装退货复核后重算"})
run3 = r.json()["run"]
check("复核后样本规模降为 9", run3["样本规模"] == 9, run3)
check("归零移出行数=3", run3["归零移出行数"] == 3, run3)
check("已复核退款数=3", run3["已复核退款数"] == 3, run3)

matrix3 = client.get("/api/basket_analysis/matrix").json()
support3 = {c["类目A"]: c["类目A单数"] for c in matrix3["cells"] if c["类目A"] == c["类目B"]}
check("季节性套装/上衣/裤子 单数降为 2", all(support3[k] == 2 for k in ("季节性套装", "上衣", "裤子")), support3)
baskets3 = client.get("/api/basket_analysis/baskets").json()["items"]
check("SO-1008 已不在有效购物篮", all(b["订单编号"] != "SO-1008" for b in baskets3))
# 上衣×裤子 原本剔除 2 单（1006/1008），1008 整单消失后剔除明细只剩 1006
c_tp3 = cell(matrix3, "上衣", "裤子")
ex3 = {e["订单编号"] for e in c_tp3["剔除明细"]}
check("重算后上衣×裤子 仅剔除 SO-1006", c_tp3["剔除数"] == 1 and ex3 == {"SO-1006"}, c_tp3)

# 逐行净件数视图可核对
ld = client.get("/api/basket_analysis/line_details").json()
l1008 = [d for d in ld["items"] if d["订单编号"] == "SO-1008"]
check("SO-1008 三行净件数归零并标注移出原因", all(d["净件数"] == 0 and d["是否计入购物篮"] is False for d in l1008), l1008)

# ---------------------------------------------------------- 5. 部分退款不归零
print("【5】部分退款：净件数>0 时保留在购物篮，归零才移出")
# SO-1001 T恤 2 件，种子退款 RF-0001 待复核 1 件；复核后净件数=1，仍在篮内
rf1 = next(x for x in client.get("/api/basket_analysis/refunds").json()["items"] if x["退款编号"] == "RF-0001")
rr = client.post(f"/api/basket_analysis/refunds/{rf1['id']}/review")
check("RF-0001 部分退款复核通过", rr.json()["ok"] is True, rr.text)
client.post("/api/basket_analysis/recompute", json={"remark": "部分退款复核后重算"})
ld = client.get("/api/basket_analysis/line_details").json()
l1001 = next(d for d in ld["items"] if d["订单编号"] == "SO-1001" and d["订单行编号"] == "L02")
check("SO-1001 T恤 净件数=1 且仍计入购物篮", l1001["净件数"] == 1 and l1001["是否计入购物篮"] is True, l1001)
baskets4 = client.get("/api/basket_analysis/baskets").json()["items"]
check("SO-1001 仍是有效订单", any(b["订单编号"] == "SO-1001" for b in baskets4))

# 再补一条退款把同一行退到归零，验证「归零才移出」
r = client.post("/api/basket_analysis/refunds/import", json={"refunds": [
    {"退款编号": "RF-1004", "订单编号": "SO-1001", "订单行编号": "L02", "退款件数": 1, "复核状态": "已复核"},
]})
check("补退到归零导入成功", r.json()["ok"] is True, r.json())
client.post("/api/basket_analysis/recompute", json={"remark": "T恤退净后重算"})
ld = client.get("/api/basket_analysis/line_details").json()
l1001 = next(d for d in ld["items"] if d["订单编号"] == "SO-1001" and d["订单行编号"] == "L02")
check("SO-1001 T恤 净件数归零被移出", l1001["净件数"] == 0 and l1001["是否计入购物篮"] is False, l1001)
# SO-1001 还剩运动鞋，订单本身仍有效
baskets5 = client.get("/api/basket_analysis/baskets").json()["items"]
b1001 = next(b for b in baskets5 if b["订单编号"] == "SO-1001")
check("SO-1001 仍有效但仅剩运动鞋", b1001["有效类目"] == "运动鞋", b1001)

# 超退拦截：累计复核退款超过实际件数
r = client.post("/api/basket_analysis/refunds/import", json={"refunds": [
    {"退款编号": "RF-BAD", "订单编号": "SO-1001", "订单行编号": "L01", "退款件数": 5, "复核状态": "已复核"},
]})
check("累计超退被整批拒绝", r.json()["ok"] is False and r.json()["errors"], r.json())

# --------------------------------------------- 6. 点开提升倍数：联合订单与来源
print("【6】点开提升倍数：查询接口返回联合订单及其来源，核对有效购物篮")
matrix_latest = client.get("/api/basket_analysis/matrix").json()
target = cell(matrix_latest, "运动鞋", "卫衣")
pair = client.get("/api/basket_analysis/pair", params={"cat_a": "运动鞋", "cat_b": "卫衣"}).json()
check("pair 返回同单次数与矩阵一致", pair["cell"]["同单次数"] == target["同单次数"], pair["cell"])
check("联合订单为 SO-1002/SO-1005/SO-1010",
      pair["cell"]["联合订单"] == ["SO-1002", "SO-1005", "SO-1010"], pair["cell"]["联合订单"])
check("返回的有效购物篮数量与联合订单一致", len(pair["baskets"]) == 3, pair["baskets"])
b1002 = next(b for b in pair["baskets"] if b["订单编号"] == "SO-1002")
check("购物篮带来源信息", "卫衣" in b1002["类目来源"] and b1002["类目来源"]["运动鞋"]["source_types"] == ["原始订单行"], b1002)
# 反向传参也能查到同一格
pair_rev = client.get("/api/basket_analysis/pair", params={"cat_a": "卫衣", "cat_b": "运动鞋"}).json()
check("类目顺序不影响 pair 查询", pair_rev["cell"]["联合订单"] == pair["cell"]["联合订单"])

# 历史版本仍可回溯（首版矩阵 SO-1008 在篮）
first_matrix = client.get("/api/basket_analysis/matrix", params={"run_no": run1["分析编号"]}).json()
check("历史版本可回溯，首版样本=10", first_matrix["run"]["样本规模"] == 10, first_matrix["run"])
first_baskets = client.get("/api/basket_analysis/baskets", params={"run_no": run1["分析编号"]}).json()["items"]
check("首版有效购物篮含 SO-1008", any(b["订单编号"] == "SO-1008" for b in first_baskets))

# 不存在的类目对返回 404
code = client.get("/api/basket_analysis/pair", params={"cat_a": "运动鞋", "cat_b": "不存在类目"}).status_code
check("未知类目对返回 404", code == 404, code)

print(f"\n全部 {PASS} 项断言通过 ✅")
