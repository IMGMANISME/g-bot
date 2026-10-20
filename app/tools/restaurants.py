# app/tools/restaurants.py
from app.services.restaurant_service import build_restaurant_query, get_restaurant_recommendation
from app.tools.base import QuickReplyItem, ToolContext, ToolResult, tool

RECOMMEND_RESTAURANTS = "recommend_restaurants"


@tool(
    name=RECOMMEND_RESTAURANTS,
    description="推薦使用者附近的餐廳。使用者想找東西吃、問吃什麼、要餐廳推薦時使用。",
    parameters={
        "price": {"type": "STRING", "enum": ["cheap", "medium", "expensive", "any"], "description": "價位"},
        "cuisine": {"type": "STRING", "description": "料理類型，例如 拉麵、火鍋；沒指定時留空"},
        "max_distance_m": {"type": "INTEGER", "description": "最遠距離（公尺）；沒指定時留空"},
        "count": {"type": "INTEGER", "description": "要推薦幾間（1 到 5）；沒指定時留空"},
    },
)
def recommend_restaurants(args: dict, ctx: ToolContext) -> ToolResult:
    query = build_restaurant_query(
        ctx.user_text,
        price=args.get("price"),
        cuisine=args.get("cuisine"),
        max_distance_m=args.get("max_distance_m"),
        count=args.get("count"),
    )
    result = get_restaurant_recommendation(ctx.sender_id, query)

    if result.needs_location:
        return ToolResult(
            data={"status": "need_location", "message": "需要使用者先傳送位置才能推薦附近餐廳"},
            fallback_text=result.text,
            quick_replies=[QuickReplyItem("📍 傳送位置")],
        )
    if not result.place_ids:
        return ToolResult(data={"status": "not_found", "message": result.text}, fallback_text=result.text)

    return ToolResult(
        data={
            "status": "found",
            "restaurant_count": len(result.place_ids),
            "note": "餐廳清單（店名、評分、距離、地圖連結）會自動附在你的回覆後面，你只要用一兩句話開場，不要再列出餐廳。",
            "list_preview": result.text[:800],
        },
        fallback_text="幫你找了幾間附近的餐廳：",
        attachment=result.text,
        quick_replies=[
            QuickReplyItem("換一批", f"{ctx.mention_prefix}吃什麼"),
            QuickReplyItem("便宜一點", f"{ctx.mention_prefix}吃什麼 便宜"),
            QuickReplyItem("近一點", f"{ctx.mention_prefix}吃什麼 近一點"),
        ],
    )
