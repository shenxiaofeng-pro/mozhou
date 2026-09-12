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
    elif context["genre"] == "urban_rebirth":
        draft = (
            f"{year}年的慢车驶进{location}时，站台上的广播带着刺耳的电流声。\n\n"
            "他隔着起雾的车窗，看见那个早已拆掉的旧招牌，也看见二十岁的自己映在玻璃上。"
            "口袋里只有皱巴巴的零钱，脑中却装着此后二十多年的涨落与代价。\n\n"
            "列车停稳前，他先撕掉了原本准备递出去的辞职信。上一世从今天开始失去的东西，"
            "这一世，他决定换一种顺序拿回来。"
        )
    elif context["genre"] == "eastern_fantasy":
        draft = (
            f"{year}纪的晨钟穿过{location}群峰时，山门前的测灵碑忽然裂开一道金纹。\n\n"
            "少年按在碑上的手没有移开。他能感觉到经脉里那股陌生气息正逆着常理运转，"
            "每前进一寸，都要从识海中带走一段清晰的记忆。\n\n"
            "执事命人封锁山门，他却先看见裂缝深处浮出一枚失传宗印。要拿到入门资格，"
            "他必须在众目睽睽之下决定：隐藏异象，还是承担力量真正的代价。"
        )
    else:
        draft = (
            f"王历{year}年的第一场雪封住{location}时，废弃法师塔顶重新亮起了蓝火。\n\n"
            "学徒把最后一枚银币压进符文槽，石门没有开启，掌心却浮出本该属于王室的誓印。"
            "这份魔力能让他越过行会的审查，也会把他的名字送进审判庭的名单。\n\n"
            "钟楼敲响宵禁前，他听见塔内有人用古语报出他的真名。门后的交易只有一次机会，"
            "而每一次施法，都必须支付等量且可追查的代价。"
        )
    brief_beats = [
        beat
        for beat in (opening_hook, state_change, emotional_payoff, ending_cliffhanger)
        if beat
    ]
    if not brief_beats:
        return draft
    return f"{draft}\n\n" + "。\n\n".join(brief_beats) + "。"
