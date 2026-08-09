from typing import TypedDict


class ChapterContext(TypedDict):
    project_title: str
    genre: str
    rebirth_year: int
    rebirth_location: str
    chapter_title: str
    reader_promise: str
    opening_hook: str
    state_change: str
    emotional_payoff: str
    ending_cliffhanger: str


def generate_demo_draft(context: ChapterContext) -> str:
    year = context["rebirth_year"]
    location = context["rebirth_location"]
    opening_hook = context["opening_hook"].rstrip("。！？!?；; ")
    state_change = context["state_change"].rstrip("。！？!?；; ")
    emotional_payoff = context["emotional_payoff"].rstrip("。！？!?；; ")
    ending_cliffhanger = context["ending_cliffhanger"].rstrip("。！？!?；; ")
    if context["genre"] == "historical_rebirth":
        draft = (
            f"{year}年的雨落在{location}城头时，他已经在冷硬的砖地上跪了半个时辰。\n\n"
            "上一世，就是从这道没有送出去的文书开始，家中一步步走向败落。如今纸还藏在袖中，"
            "门外的脚步声也才刚刚响起。\n\n"
            "他没有急着起身，只把文书折痕换了一个方向。来人推门的刹那，他抬起头，"
            "第一次说出了上一世咽回去的那句话。"
        )
    else:
        draft = (
            f"{year}年的慢车驶进{location}时，站台上的广播带着刺耳的电流声。\n\n"
            "他隔着起雾的车窗，看见那个早已拆掉的旧招牌，也看见二十岁的自己映在玻璃上。"
            "口袋里只有皱巴巴的零钱，脑中却装着此后二十多年的涨落与代价。\n\n"
            "列车停稳前，他先撕掉了原本准备递出去的辞职信。上一世从今天开始失去的东西，"
            "这一世，他决定换一种顺序拿回来。"
        )
    brief_beats = [
        beat
        for beat in (opening_hook, state_change, emotional_payoff, ending_cliffhanger)
        if beat
    ]
    if not brief_beats:
        return draft
    return f"{draft}\n\n" + "。\n\n".join(brief_beats) + "。"
