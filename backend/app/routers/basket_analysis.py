"""同单连带分析接口：购物篮取数、退款复核、重算联购记录与联购矩阵查询。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult
from app.services.basket_analysis import BasketAnalysisService

router = APIRouter(prefix="/api/basket_analysis", tags=["同单连带分析"])

service = BasketAnalysisService()


class OrderLineBatch(BaseModel):
    """购物篮取数入参：订单编号 + 订单行（类目 / 行状态 / 实际件数）。"""

    lines: list[dict[str, Any]] = Field(default_factory=list)
    remark: str | None = None


class RefundBatch(BaseModel):
    """退款明细入参：退款关联原订单行，按复核状态决定是否参与净件数恢复。"""

    refunds: list[dict[str, Any]] = Field(default_factory=list)
    remark: str | None = None


class RecomputePayload(BaseModel):
    remark: str | None = None


@router.get("/lines")
def list_lines(order_no: str | None = Query(default=None, description="按订单编号过滤")) -> dict[str, Any]:
    """查看已导入的订单行及其来源类型。"""
    items = service.list_lines(order_no=order_no)
    return {"items": items, "total": len(items)}


@router.post("/lines/import")
def import_lines(payload: OrderLineBatch) -> dict[str, Any]:
    """购物篮取数：批量导入订单行，重复业务键覆盖更新而不重复计单。"""
    return service.import_lines(payload.lines)


@router.get("/refunds")
def list_refunds(
    review_status: str | None = Query(default=None, description="待复核 / 已复核"),
) -> dict[str, Any]:
    """查看退款明细与复核状态。"""
    items = service.list_refunds(review_status=review_status)
    return {"items": items, "total": len(items)}


@router.post("/refunds/import")
def import_refunds(payload: RefundBatch) -> dict[str, Any]:
    """补交退款明细；只有已复核的退款会在重算时恢复净件数。"""
    return service.import_refunds(payload.refunds)


@router.post("/refunds/{refund_id}/review", response_model=ActionResult)
def review_refund(refund_id: int) -> ActionResult:
    """复核退款：通过后允许按更正口径重算联购记录。"""
    refund, message = service.review_refund(refund_id)
    if refund is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=refund)


@router.get("/baskets")
def valid_baskets(run_no: str | None = Query(default=None, description="分析编号，缺省取最新版本")) -> dict[str, Any]:
    """核对有效购物篮：列出某次分析纳入的订单、有效类目与逐类目来源。"""
    items = service.valid_baskets(run_no=run_no)
    return {"items": items, "total": len(items)}


@router.get("/line_details")
def line_details() -> dict[str, Any]:
    """逐行净件数视图：实际件数、已复核退款、净件数与移出原因。"""
    built = service.build_baskets()
    return {
        "items": built["line_details"],
        "total": len(built["line_details"]),
        "invalid_line_count": built["invalid_line_count"],
        "zeroed_line_count": built["zeroed_line_count"],
    }


@router.post("/recompute")
def recompute(payload: RecomputePayload) -> dict[str, Any]:
    """按更正口径重算联购记录，生成新的同单连带分析版本。"""
    return service.recompute(remark=payload.remark)


@router.get("/runs")
def list_runs() -> dict[str, Any]:
    """同单连带分析版本列表（含样本规模、剔除数等汇总）。"""
    items = service.list_runs()
    return {"items": items, "total": len(items)}


@router.get("/matrix")
def matrix(run_no: str | None = Query(default=None, description="分析编号，缺省取最新版本")) -> dict[str, Any]:
    """联购矩阵视图：每格展示提升倍数、可比较样本量与剔除数。"""
    result = service.matrix(run_no=run_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/pair")
def pair_detail(
    cat_a: str = Query(..., description="类目A"),
    cat_b: str = Query(..., description="类目B"),
    run_no: str | None = Query(default=None, description="分析编号，缺省取最新版本"),
) -> dict[str, Any]:
    """点开矩阵中的提升倍数：返回联合订单及其来源，核对包含的有效购物篮。"""
    result = service.pair_detail(cat_a, cat_b, run_no=run_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result
