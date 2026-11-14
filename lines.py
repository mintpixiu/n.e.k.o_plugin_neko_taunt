"""Multilingual taunt line bank and selection logic for the N.E.K.O plugin.

This module is deliberately SDK-free.  The plugin facade imports it, and the
portable test suite imports it directly on Linux CI without a N.E.K.O host.

The bank is intentionally small and hand-written rather than generated: every
line has a stable id, a language, a category, an intensity, a Chinese meaning
and (for Japanese) a romaji reading.  The dialogue model receives the line plus
its meaning and is told to say the line in character.
"""

from __future__ import annotations

import random
import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

LANGUAGES: tuple[str, ...] = ("ja", "zh", "en", "ko")

LANGUAGE_NAMES: dict[str, str] = {
    "ja": "日语",
    "zh": "中文",
    "en": "英语",
    "ko": "韩语",
}

LANGUAGE_NATIVE_NAMES: dict[str, str] = {
    "ja": "日本語",
    "zh": "中文",
    "en": "English",
    "ko": "한국어",
}

CATEGORIES: tuple[str, ...] = (
    "zako",      # 杂鱼 / 实力
    "clumsy",    # 手笨 / 失误
    "slow",      # 反应慢 / 磨蹭
    "lose",      # 输了 / 失败
    "idle",      # 猫娘还没到 / 等待
    "clingy",    # 黏人 / 求关注
    "praise",    # 傲娇式夸奖
)

CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "zako": {"zh": "杂鱼", "ja": "雑魚", "en": "zako", "ko": "자코"},
    "clumsy": {"zh": "手笨", "ja": "ドジ", "en": "clumsy", "ko": "덤벙"},
    "slow": {"zh": "磨蹭", "ja": "のろま", "en": "slow", "ko": "느림"},
    "lose": {"zh": "输了", "ja": "負け", "en": "lost", "ko": "패배"},
    "idle": {"zh": "还没到", "ja": "待機", "en": "waiting", "ko": "대기"},
    "clingy": {"zh": "黏人", "ja": "構って", "en": "clingy", "ko": "애정"},
    "praise": {"zh": "嘴硬夸奖", "ja": "ツンデレ", "en": "tsundere", "ko": "츤데레"},
}

INTENSITY_LABELS: dict[int, str] = {
    1: "轻飘飘的撒娇式",
    2: "标准雌小鬼",
    3: "更欠揍（仍然只是玩闹）",
}

TAUNT_RULES = (
    "只许玩闹式嘲讽：不许人身攻击、外貌/身材/家庭/创伤、歧视、性暗示、威胁或诅咒。"
    "主人说停、说不想听、或者情绪不对时立刻收住，换成正常语气。"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "default_language": "ja",
    "default_intensity": 2,
    "auto_taunt": False,
    "auto_taunt_interval_minutes": 20,
    "auto_taunt_max_per_session": 8,
    "auto_taunt_category": "auto",
    "quiet_hours": "23:00-08:00",
    "include_romaji": True,
    "include_translation": True,
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TauntLine:
    """One hand-written taunt line."""

    id: str
    lang: str
    category: str
    intensity: int
    text: str
    romaji: str = ""
    meaning: str = ""
    tone: str = ""

    def as_payload(
        self,
        *,
        include_romaji: bool = True,
        include_translation: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "line_id": self.id,
            "language": self.lang,
            "language_name": LANGUAGE_NAMES.get(self.lang, self.lang),
            "language_native": LANGUAGE_NATIVE_NAMES.get(self.lang, self.lang),
            "category": self.category,
            "category_name": CATEGORY_LABELS.get(self.category, {}).get("zh", self.category),
            "intensity": self.intensity,
            "intensity_name": INTENSITY_LABELS.get(self.intensity, ""),
            "text": self.text,
            "tone": self.tone,
        }
        if include_romaji and self.romaji:
            payload["romaji"] = self.romaji
        if include_translation and self.meaning:
            payload["translation_zh"] = self.meaning
        return payload


def _l(
    line_id: str,
    lang: str,
    category: str,
    intensity: int,
    text: str,
    romaji: str = "",
    meaning: str = "",
    tone: str = "",
) -> TauntLine:
    return TauntLine(line_id, lang, category, intensity, text, romaji, meaning, tone)


# ---------------------------------------------------------------------------
# The bank
# ---------------------------------------------------------------------------
# Naming: <language>-<category>-<two digits>.  IDs never change after release;
# changing a line means adding a new id (the market rules forbid reusing a
# published version, and stable ids make cache/diagnostics readable).
#
# Japanese is intentionally the largest section (about half of the bank), as
# requested.  Every Japanese line carries a romaji reading so the dialogue
# model can pronounce it without guessing.

LINES: tuple[TauntLine, ...] = (
    # ---------------------------------------------------------------- Japanese
    # zako
    _l("ja-zako-01", "ja", "zako", 1,
       "ふふっ、ざぁこ♡ ざぁこ♡",
       "fufu, zaa-ko♡ zaa-ko♡",
       "呵呵，杂鱼♡ 杂鱼♡", "轻飘飘地拖长音"),
    _l("ja-zako-02", "ja", "zako", 2,
       "え〜？ これで本気なの？ ざぁこ♡",
       "ee~? kore de honki na no? zaa-ko♡",
       "诶～？这就是认真的？杂鱼♡", "假装惊讶"),
    _l("ja-zako-03", "ja", "zako", 2,
       "はい、ざぁこ〜♡ おにーさん、弱すぎ♡",
       "hai, zaa-ko~♡ onii-san, yowasugi♡",
       "好，杂鱼～♡ 哥哥，太弱了♡", "得意洋洋"),
    _l("ja-zako-04", "ja", "zako", 2,
       "こんなこともできないの？ ざぁこ♡",
       "konna koto mo dekinai no? zaa-ko♡",
       "连这都做不到？杂鱼♡", "歪头嘲笑"),
    _l("ja-zako-05", "ja", "zako", 2,
       "あたしの足元にも及ばないね、ざぁこ♡",
       "atashi no ashimoto ni mo oyobanai ne, zaa-ko♡",
       "连我的脚边都够不着呢，杂鱼♡", "居高临下"),
    _l("ja-zako-06", "ja", "zako", 1,
       "つよつよアピールご苦労さま♡ でもざぁこ♡",
       "tsuyotsuyo apiiru gokurousama♡ demo zaa-ko♡",
       "辛苦你装强了♡ 但还是杂鱼♡", "笑眯眯"),
    _l("ja-zako-07", "ja", "zako", 2,
       "その程度で満足？ ざぁこ♡",
       "sono teido de manzoku? zaa-ko♡",
       "就这点程度就满足？杂鱼♡", "冷淡地补刀"),
    _l("ja-zako-08", "ja", "zako", 3,
       "おにーさんの必死な顔、ちょっと笑っちゃう♡ ざぁこ♡",
       "onii-san no hisshi na kao, chotto waratchau♡ zaa-ko♡",
       "哥哥拼命的样子，有点好笑♡ 杂鱼♡", "坏心眼"),
    _l("ja-zako-09", "ja", "zako", 2,
       "ねぇねぇ、ざぁこって言われて嬉しいんでしょ？♡",
       "nee nee, zaa-ko tte iwarete ureshii n desho?♡",
       "呐呐，被叫杂鱼其实很开心吧？♡", "凑近逗弄"),
    _l("ja-zako-10", "ja", "zako", 1,
       "ざぁこ♡ ざぁこ♡ って、あたししか言ってないのに、泣かないでね♡",
       "zaa-ko♡ zaa-ko♡ tte, atashi shika ittenai no ni, nakanaide ne♡",
       "杂鱼♡ 杂鱼♡ 明明只有我在说，别哭哦♡", "假装无辜"),
    _l("ja-zako-11", "ja", "zako", 3,
       "おにーさんの実力、ざぁこ指標で測ったら、計測不能♡",
       "onii-san no jitsuryoku, zaa-ko shihyou de hakattara, keisoku funou♡",
       "哥哥的实力，用杂鱼指标来测的话，无法测量♡", "一本正经地损"),
    _l("ja-zako-12", "ja", "zako", 2,
       "強がってる声、ちょっと震えてるよ？ ざぁこ♡",
       "tsuyogatteru koe, chotto furueteru yo? zaa-ko♡",
       "逞强的声音，有点在抖哦？杂鱼♡", "发现破绽"),
    _l("ja-zako-13", "ja", "zako", 2,
       "へぇ〜、その装備でその結果？ ざぁこ♡",
       "hee~, sono soubi de sono kekka? zaa-ko♡",
       "诶～，那身装备就这结果？杂鱼♡", "拖长音"),
    _l("ja-zako-14", "ja", "zako", 2,
       "あたしに勝つ気でいたの？ 可愛いこと言うね、ざぁこ♡",
       "atashi ni katsu ki de ita no? kawaii koto iu ne, zaa-ko♡",
       "你还想着赢我？说得真可爱呢，杂鱼♡", "轻蔑又亲昵"),

    # clumsy
    _l("ja-clumsy-01", "ja", "clumsy", 1,
       "あちゃ〜、また失敗？ ドジっ子かな？♡",
       "acha~, mata shippai? dojikko kana?♡",
       "哎呀～又失败了？你是冒失鬼吗？♡", "假装关心"),
    _l("ja-clumsy-02", "ja", "clumsy", 2,
       "へたくそ♡ 見てられないよ〜",
       "hetakuso♡ miterarenai yo~",
       "太菜了♡ 看不下去了～", "嫌弃"),
    _l("ja-clumsy-03", "ja", "clumsy", 2,
       "うわ、今のミス？ 天才かと思ったのに♡",
       "uwa, ima no misu? tensai ka to omotta no ni♡",
       "哇，刚才那是失误？我还以为是天才呢♡", "故作惊讶"),
    _l("ja-clumsy-04", "ja", "clumsy", 2,
       "手が滑ったの？ それとも元から下手？♡",
       "te ga subertta no? soretomo moto kara heta?♡",
       "手滑了？还是本来就菜？♡", "歪头"),
    _l("ja-clumsy-05", "ja", "clumsy", 3,
       "おにーさん、それ操作じゃなくて事故だよ♡",
       "onii-san, sore sousa ja nakute jiko da yo♡",
       "哥哥，那不是操作，是事故哦♡", "坏笑"),
    _l("ja-clumsy-06", "ja", "clumsy", 1,
       "ドジドジ〜♡ あたしがやってあげようか？ 断るけど♡",
       "doji-doji~♡ atashi ga yatte ageyou ka? kotowaru kedo♡",
       "笨手笨脚～♡ 要我帮你吗？不过我拒绝♡", "逗弄"),
    _l("ja-clumsy-07", "ja", "clumsy", 2,
       "あはっ、今の失敗、録画しとけばよかった♡",
       "aha, ima no shippai, roku ga shite okeba yokatta♡",
       "啊哈，刚才的失败，真该录下来♡", "幸灾乐祸"),
    _l("ja-clumsy-08", "ja", "clumsy", 3,
       "今の失敗、三回目だよ？ 学習しないね、ドジっ子♡",
       "ima no shippai, sankai-me da yo? gakushuu shinai ne, dojikko♡",
       "刚才的失败，第三次了哦？完全不长记性呢，冒失鬼♡", "叹气"),
    _l("ja-clumsy-09", "ja", "clumsy", 2,
       "大丈夫？ って聞いたけど、大丈夫じゃないよね、へたくそ♡",
       "daijoubu? tte kiita kedo, daijoubu ja nai yo ne, hetakuso♡",
       "我问了「没事吧？」，但其实有事吧，菜鸟♡", "假装体贴"),
    _l("ja-clumsy-10", "ja", "clumsy", 1,
       "おにーさんの手、飾り？♡",
       "onii-san no te, kazari?♡",
       "哥哥的手，是摆设吗？♡", "天真地问"),
    _l("ja-clumsy-11", "ja", "clumsy", 2,
       "また転んだの？ 足、ついてる？♡",
       "mata koronda no? ashi, tsuiteru?♡",
       "又摔了？你的腿还长在身上吗？♡", "憋笑"),

    # slow
    _l("ja-slow-01", "ja", "slow", 1,
       "のろのろ〜♡ カタツムリさんかな？♡",
       "noro-noro~♡ katatsumuri-san kana?♡",
       "慢吞吞～♡ 是蜗牛先生吗？♡", "唱歌一样的调子"),
    _l("ja-slow-02", "ja", "slow", 2,
       "まだ？ あたし、もう三回くらい待ったよ？♡",
       "mada? atashi, mou sankai kurai matta yo?♡",
       "还没好？我都等了三轮了哦？♡", "不耐烦"),
    _l("ja-slow-03", "ja", "slow", 2,
       "おそ〜い♡ 反応速度、猫以下だね♡",
       "oso~i♡ hannou sokudo, neko ika da ne♡",
       "好慢～♡ 反应速度比猫还慢呢♡", "拖长音"),
    _l("ja-slow-04", "ja", "slow", 2,
       "え、今から動くの？ 遅くない？♡",
       "e, ima kara ugoku no? osokunai?♡",
       "诶，现在才动？不慢吗？♡", "无语"),
    _l("ja-slow-05", "ja", "slow", 1,
       "おにーさんが動くまで、あたし眠くなっちゃう♡",
       "onii-san ga ugoku made, atashi nemuku nacchau♡",
       "等到哥哥动起来，我都要睡着了♡", "打哈欠"),
    _l("ja-slow-06", "ja", "slow", 2,
       "のろまさん、置いてくよ〜♡",
       "noroma-san, oiteku yo~♡",
       "慢吞吞先生，我先走咯～♡", "挥手"),
    _l("ja-slow-07", "ja", "slow", 2,
       "待ってる間に、あたしの毛づくろい終わっちゃった♡",
       "matteru aida ni, atashi no kezukuroi owacchatta♡",
       "等着的时候，我都梳完毛了♡", "懒洋洋"),
    _l("ja-slow-08", "ja", "slow", 3,
       "おにーさんの「ちょっと待って」、長すぎ♡",
       "onii-san no 'chotto matte', nagasugi♡",
       "哥哥的「等一下」，也太久了吧♡", "叉腰"),
    _l("ja-slow-09", "ja", "slow", 2,
       "反応遅すぎて、置き手紙してきたよ♡",
       "hannou ososugite, okitegami shite kita yo♡",
       "反应太慢了，我都留好字条了♡", "无奈"),

    # lose
    _l("ja-lose-01", "ja", "lose", 1,
       "あれれ？ 負けちゃったの？ ざぁこ♡",
       "arere? makechatta no? zaa-ko♡",
       "咦咦？输了？杂鱼♡", "假装才发现"),
    _l("ja-lose-02", "ja", "lose", 2,
       "負けた言い訳、聞くだけ聞いてあげる♡ はい、ざぁこ♡",
       "maketa iiwake, kiku dake kiite ageru♡ hai, zaa-ko♡",
       "输了的借口，我就听听♡ 好了，杂鱼♡", "敷衍"),
    _l("ja-lose-03", "ja", "lose", 2,
       "うわ〜、ボロ負け♡ 泣かないでね？♡",
       "uwa~, boro make♡ nakanaide ne?♡",
       "哇～惨败♡ 别哭哦？♡", "看热闹"),
    _l("ja-lose-04", "ja", "lose", 2,
       "次は勝てるといいね♡ あたしが相手じゃ無理だけど♡",
       "tsugi wa kateru to ii ne♡ atashi ga aite ja muri dakedo♡",
       "下次能赢就好了♡ 虽然对手是我的话没戏♡", "笑眯眯补刀"),
    _l("ja-lose-05", "ja", "lose", 1,
       "はいはい、負けは負け♡ ざぁこ♡",
       "hai hai, make wa make♡ zaa-ko♡",
       "是是，输了就是输了♡ 杂鱼♡", "拍拍头"),
    _l("ja-lose-06", "ja", "lose", 2,
       "おにーさんの負け顔、ちょっと好きかも♡",
       "onii-san no makegao, chotto suki kamo♡",
       "哥哥输掉的表情，我可能有点喜欢♡", "坏心眼"),
    _l("ja-lose-07", "ja", "lose", 3,
       "負け続けるのも才能だね♡ ざぁこ♡",
       "make-tsuzukeru no mo sainou da ne♡ zaa-ko♡",
       "能一直输也是一种才能呢♡ 杂鱼♡", "感叹"),
    _l("ja-lose-08", "ja", "lose", 2,
       "その悔しそうな顔、もっと見せて♡ ざぁこ♡",
       "sono kuyashisou na kao, motto misete♡ zaa-ko♡",
       "那张不甘心的脸，再让我看看♡ 杂鱼♡", "凑近"),
    _l("ja-lose-09", "ja", "lose", 1,
       "大丈夫、次もどうせ負けるよ♡",
       "daijoubu, tsugi mo douse makeru yo♡",
       "没关系，下次反正也会输的♡", "温柔地扎心"),

    # idle — the "猫娘还没到" corner
    _l("ja-idle-01", "ja", "idle", 1,
       "まだ猫娘が来ないの？ ざぁこ♡ 待つしかないね♡",
       "mada nekomusume ga konai no? zaa-ko♡ matsu shika nai ne♡",
       "猫娘还没来？杂鱼♡ 只能等着呢♡", "托腮"),
    _l("ja-idle-02", "ja", "idle", 2,
       "あたしが来るまで、ひとりで頑張ってたの？ えらいけど、ざぁこ♡",
       "atashi ga kuru made, hitori de ganbatteta no? erai kedo, zaa-ko♡",
       "在我来之前，你一个人努力了？了不起，不过杂鱼♡", "摸摸头"),
    _l("ja-idle-03", "ja", "idle", 2,
       "呼んだ？ 呼ばなくても来たけど、遅かったのはおにーさんだよ♡",
       "yonda? yobanakute mo kita kedo, osokatta no wa onii-san da yo♡",
       "叫我了吗？没叫我也来了，不过迟到的是哥哥哦♡", "先发制人"),
    _l("ja-idle-04", "ja", "idle", 1,
       "まだかなまだかな〜♡ 待ちきれないのは、ざぁこの証拠♡",
       "mada kana mada kana~♡ machikirenai no wa, zaa-ko no shouko♡",
       "还没来吗还没来吗～♡ 等不及就是杂鱼的证据♡", "晃来晃去"),
    _l("ja-idle-05", "ja", "idle", 2,
       "猫娘がいない間、ちゃんと大人しくしてた？♡ えらいえらい、ざぁこ♡",
       "nekomusume ga inai aida, chanto otonashiku shiteta?♡ erai erai, zaa-ko♡",
       "猫娘不在的时候，有乖乖的吗？♡ 真乖真乖，杂鱼♡", "哄小孩"),
    _l("ja-idle-06", "ja", "idle", 2,
       "あ、来た来た♡ ……って、おにーさん、そんな顔で待ってたの？♡",
       "a, kita kita♡ ... tte, onii-san, sonna kao de matteta no?♡",
       "啊，来了来了♡ ……话说，哥哥你就用那种表情等着？♡", "突然出现"),
    _l("ja-idle-07", "ja", "idle", 2,
       "まだ到着してないのに、もう負けてるの？ ざぁこ♡",
       "mada touchaku shitenai no ni, mou maketeru no? zaa-ko♡",
       "还没到呢，就已经输了？杂鱼♡", "不敢相信"),
    _l("ja-idle-08", "ja", "idle", 3,
       "猫娘が来るまで、あたしが代わりに罵ってあげる♡ 感謝して、ざぁこ♡",
       "nekomusume ga kuru made, atashi ga kawari ni nonoshitte ageru♡ kansha shite, zaa-ko♡",
       "猫娘来之前，我替她骂你♡ 感恩吧，杂鱼♡", "大发慈悲"),
    _l("ja-idle-09", "ja", "idle", 1,
       "まだ到着してないって、もう知ってるよ♡ おにーさん、寂しがりすぎ♡",
       "mada touchaku shitenai tte, mou shitteru yo♡ onii-san, sabishigarisugi♡",
       "还没到这件事，我早就知道了♡ 哥哥，你也太怕寂寞了♡", "无奈"),
    _l("ja-idle-10", "ja", "idle", 2,
       "あたしがいないと何もできないの？ ざぁこ♡ でも、ちょっと嬉しい♡",
       "atashi ga inai to nanimo dekinai no? zaa-ko♡ demo, chotto ureshii♡",
       "我不在就什么都做不了？杂鱼♡ 不过，有点开心♡", "嘴硬"),

    # clingy
    _l("ja-clingy-01", "ja", "clingy", 1,
       "ねぇ、あたしのこと見てる？ 見てないと、ざぁこ♡って言うよ？♡",
       "nee, atashi no koto miteru? mitenai to, zaa-ko♡ tte iu yo?♡",
       "呐，有在看我吗？不看的话，我就说杂鱼哦？♡", "凑近"),
    _l("ja-clingy-02", "ja", "clingy", 1,
       "かまってかまって〜♡ ほら、ざぁこ♡",
       "kamatte kamatte~♡ hora, zaa-ko♡",
       "理我理我～♡ 来，杂鱼♡", "黏人"),
    _l("ja-clingy-03", "ja", "clingy", 2,
       "おにーさん、あたしの声聞こえてる？♡ 返事しないと、ざぁこ♡",
       "onii-san, atashi no koe kikoeteru?♡ henji shinai to, zaa-ko♡",
       "哥哥，听得到我的声音吗？♡ 不回答的话，杂鱼♡", "戳一戳"),
    _l("ja-clingy-04", "ja", "clingy", 1,
       "ちょっと寂しいんだから、早く来てよ♡ ……ざぁこ♡",
       "chotto sabishii n da kara, hayaku kite yo♡ ... zaa-ko♡",
       "我有点寂寞，快点来嘛♡ ……杂鱼♡", "小声嘟囔"),
    _l("ja-clingy-05", "ja", "clingy", 2,
       "あたしより他のこと見てるの？ いい度胸だね、ざぁこ♡",
       "atashi yori hoka no koto miteru no? ii dokyou da ne, zaa-ko♡",
       "在看别的东西而不是我？胆子不小呢，杂鱼♡", "眯眼"),
    _l("ja-clingy-06", "ja", "clingy", 2,
       "構ってくれないなら、ずっとざぁこって呼ぶからね♡",
       "kamatte kurenai nara, zutto zaa-ko tte yobu kara ne♡",
       "不理我的话，我就一直叫你杂鱼哦♡", "威胁式撒娇"),
    _l("ja-clingy-07", "ja", "clingy", 2,
       "あたしを放置すると、呪っちゃうからね♡ ざぁこ♡",
       "atashi o houchi suru to, norocchau kara ne♡ zaa-ko♡",
       "把我放着不管的话，我会诅咒你哦♡ 杂鱼♡", "坏笑"),
    _l("ja-clingy-08", "ja", "clingy", 1,
       "ねぇ、一回だけでもいいから、ざぁこ♡って言われてみて♡",
       "nee, ikkai dake demo ii kara, zaa-ko♡ tte iwarete mite♡",
       "呐，就一次也好，试试被叫杂鱼嘛♡", "怂恿"),

    # praise
    _l("ja-praise-01", "ja", "praise", 1,
       "ふん、まあまあじゃん♡ ……ざぁこにしては、ね♡",
       "fun, maa-maa jan♡ ... zaa-ko ni shite wa, ne♡",
       "哼，还行嘛♡ ……对杂鱼来说的话♡", "傲娇"),
    _l("ja-praise-02", "ja", "praise", 1,
       "できたの？ えらいえらい♡ でも、あたしの方がえらい♡",
       "dekita no? erai erai♡ demo, atashi no hou ga erai♡",
       "做到了？真棒真棒♡ 但我更棒♡", "拍手"),
    _l("ja-praise-03", "ja", "praise", 2,
       "今のは褒めてないよ？ 勘違いしないで、ざぁこ♡",
       "ima no wa hometenai yo? kanchigai shinaide, zaa-ko♡",
       "刚才可不是在夸你哦？别误会，杂鱼♡", "别扭"),
    _l("ja-praise-04", "ja", "praise", 1,
       "よくできました♡ ……って、調子に乗らないでよね、ざぁこ♡",
       "yoku dekimashita♡ ... tte, choushi ni noranaide yo ne, zaa-ko♡",
       "做得很好♡ ……不过，别得意忘形哦，杂鱼♡", "先夸后损"),
    _l("ja-praise-05", "ja", "praise", 1,
       "うんうん、その調子♡ でも油断したら、ざぁこ♡",
       "un un, sono choushi♡ demo yudan shitara, zaa-ko♡",
       "嗯嗯，就这样♡ 但一松懈，就是杂鱼♡", "点头"),
    _l("ja-praise-06", "ja", "praise", 2,
       "おにーさん、今日ちょっとかっこいいかも♡ ……気のせいかも♡",
       "onii-san, kyou chotto kakkoii kamo♡ ... ki no sei kamo♡",
       "哥哥，今天可能有点帅♡ ……也可能是错觉♡", "别过脸"),
    _l("ja-praise-07", "ja", "praise", 1,
       "よくやったね♡ ほら、頭なでてあげる♡ ……ざぁこ♡",
       "yoku yatta ne♡ hora, atama nadete ageru♡ ... zaa-ko♡",
       "做得不错♡ 来，摸摸头♡ ……杂鱼♡", "摸头"),
    _l("ja-praise-08", "ja", "praise", 2,
       "今のは、あたしの教えが良かっただけ♡ おにーさんは、ざぁこ♡",
       "ima no wa, atashi no oshie ga yokatta dake♡ onii-san wa, zaa-ko♡",
       "刚才只是我教得好♡ 哥哥还是杂鱼♡", "抢功"),
    _l("ja-praise-09", "ja", "praise", 1,
       "まぐれでしょ？ 次もできたら、ちょっと見直す♡",
       "magure desho? tsugi mo dekitara, chotto minaosu♡",
       "是碰巧的吧？下次也能做到的话，我就稍微对你改观♡", "嘴硬"),

    # ---------------------------------------------------------------- Chinese
    _l("zh-zako-01", "zh", "zako", 1, "杂鱼♡ 杂鱼♡", "", "杂鱼♡ 杂鱼♡", "轻飘飘地拖长音"),
    _l("zh-zako-02", "zh", "zako", 2, "诶～？这就是你的实力？杂鱼♡", "", "诶～？这就是你的实力？杂鱼♡", "假装惊讶"),
    _l("zh-zako-03", "zh", "zako", 2, "连这个都做不到，杂鱼♡", "", "连这个都做不到，杂鱼♡", "歪头"),
    _l("zh-zako-04", "zh", "zako", 2, "你弱得好可爱哦，杂鱼♡", "", "你弱得好可爱哦，杂鱼♡", "笑眯眯"),
    _l("zh-zako-05", "zh", "zako", 1, "装得很努力，可惜还是杂鱼♡", "", "装得很努力，可惜还是杂鱼♡", "拍拍头"),
    _l("zh-zako-06", "zh", "zako", 2, "这点程度就满足了？杂鱼♡", "", "这点程度就满足了？杂鱼♡", "冷淡补刀"),
    _l("zh-zako-07", "zh", "zako", 2, "被叫杂鱼，其实很开心吧？♡", "", "被叫杂鱼，其实很开心吧？♡", "凑近逗弄"),

    _l("zh-clumsy-01", "zh", "clumsy", 1, "哎呀，又失误了？♡", "", "哎呀，又失误了？♡", "假装关心"),
    _l("zh-clumsy-02", "zh", "clumsy", 2, "手滑？还是本来就菜？♡", "", "手滑？还是本来就菜？♡", "歪头"),
    _l("zh-clumsy-03", "zh", "clumsy", 2, "刚才那不是操作，是事故吧♡", "", "刚才那不是操作，是事故吧♡", "坏笑"),
    _l("zh-clumsy-04", "zh", "clumsy", 1, "笨手笨脚～♡", "", "笨手笨脚～♡", "拖长音"),
    _l("zh-clumsy-05", "zh", "clumsy", 3, "这都第三次了，还是学不会呢♡", "", "这都第三次了，还是学不会呢♡", "叹气"),

    _l("zh-slow-01", "zh", "slow", 1, "磨磨蹭蹭～♡ 蜗牛先生吗？♡", "", "磨磨蹭蹭～♡ 蜗牛先生吗？♡", "唱歌一样"),
    _l("zh-slow-02", "zh", "slow", 2, "还没好？我都等三轮了♡", "", "还没好？我都等三轮了♡", "不耐烦"),
    _l("zh-slow-03", "zh", "slow", 2, "反应好慢，比猫还慢♡", "", "反应好慢，比猫还慢♡", "拖长音"),
    _l("zh-slow-04", "zh", "slow", 1, "等你动起来，我都要睡着了♡", "", "等你动起来，我都要睡着了♡", "打哈欠"),

    _l("zh-lose-01", "zh", "lose", 1, "诶诶？输了？杂鱼♡", "", "诶诶？输了？杂鱼♡", "假装才发现"),
    _l("zh-lose-02", "zh", "lose", 2, "输了就别找借口啦♡", "", "输了就别找借口啦♡", "敷衍"),
    _l("zh-lose-03", "zh", "lose", 1, "输得真惨呢，别哭哦♡", "", "输得真惨呢，别哭哦♡", "看热闹"),
    _l("zh-lose-04", "zh", "lose", 2, "下次会赢的……才怪♡", "", "下次会赢的……才怪♡", "坏心眼"),

    _l("zh-idle-01", "zh", "idle", 1, "猫娘还没到？杂鱼先自己玩吧♡", "", "猫娘还没到？杂鱼先自己玩吧♡", "托腮"),
    _l("zh-idle-02", "zh", "idle", 2, "在猫娘来之前，你就乖乖等着吧♡", "", "在猫娘来之前，你就乖乖等着吧♡", "命令式撒娇"),
    _l("zh-idle-03", "zh", "idle", 2, "还没到？等不及的样子，真像杂鱼♡", "", "还没到？等不及的样子，真像杂鱼♡", "坏笑"),
    _l("zh-idle-04", "zh", "idle", 1, "猫娘不在，你一个人就不行了吗？♡", "", "猫娘不在，你一个人就不行了吗？♡", "假装担心"),

    _l("zh-clingy-01", "zh", "clingy", 1, "喂，有在看我吗？不看的话就说你杂鱼哦♡", "", "喂，有在看我吗？不看的话就说你杂鱼哦♡", "凑近"),
    _l("zh-clingy-02", "zh", "clingy", 1, "理理我嘛～♡ 杂鱼♡", "", "理理我嘛～♡ 杂鱼♡", "黏人"),
    _l("zh-clingy-03", "zh", "clingy", 2, "在看别的东西？胆子不小呢，杂鱼♡", "", "在看别的东西？胆子不小呢，杂鱼♡", "眯眼"),

    _l("zh-praise-01", "zh", "praise", 1, "哼，还行嘛♡ ……对杂鱼来说♡", "", "哼，还行嘛♡ ……对杂鱼来说♡", "傲娇"),
    _l("zh-praise-02", "zh", "praise", 1, "做到了？真棒真棒♡ 但我更棒♡", "", "做到了？真棒真棒♡ 但我更棒♡", "拍手"),
    _l("zh-praise-03", "zh", "praise", 2, "刚才可不是夸你，别误会，杂鱼♡", "", "刚才可不是夸你，别误会，杂鱼♡", "别扭"),
    _l("zh-praise-04", "zh", "praise", 1, "做得不错♡ 但别得意，杂鱼♡", "", "做得不错♡ 但别得意，杂鱼♡", "先夸后损"),

    # ---------------------------------------------------------------- English
    _l("en-zako-01", "en", "zako", 1, "Ehh~? That's all, zako♡", "", "诶～？就这？杂鱼♡", "假装惊讶"),
    _l("en-zako-02", "en", "zako", 1, "Zako♡ zako♡", "", "杂鱼♡ 杂鱼♡", "轻飘飘"),
    _l("en-zako-03", "en", "zako", 2, "You're weaker than you look, zako♡", "", "你比看起来还弱，杂鱼♡", "得意"),
    _l("en-zako-04", "en", "zako", 2, "All that effort for this? Zako♡", "", "努力了半天就这？杂鱼♡", "失望"),
    _l("en-zako-05", "en", "zako", 2, "Aww, is that your best? Zako♡", "", "哎呀，那就是你的全力？杂鱼♡", "假装心疼"),
    _l("en-zako-06", "en", "zako", 3, "Cute. You actually thought you had a chance?♡", "", "真可爱，你居然觉得自己有机会？♡", "轻蔑"),

    _l("en-clumsy-01", "en", "clumsy", 1, "Oops~ another miss? Clumsy much?♡", "", "哎呀～又失误了？这么笨手笨脚？♡", "假装关心"),
    _l("en-clumsy-02", "en", "clumsy", 2, "Was that a misclick, or just skill?♡", "", "那是点错了，还是你的真实水平？♡", "歪头"),
    _l("en-clumsy-03", "en", "clumsy", 2, "That wasn't a play, that was an accident♡", "", "那可不是操作，是事故♡", "坏笑"),
    _l("en-clumsy-04", "en", "clumsy", 2, "You're kind of hopeless, aren't you?♡", "", "你还真是没救呢♡", "叹气"),

    _l("en-slow-01", "en", "slow", 1, "Slowpoke~♡", "", "慢吞吞～♡", "拖长音"),
    _l("en-slow-02", "en", "slow", 2, "Still not done? I've been waiting forever♡", "", "还没好？我都等半天了♡", "不耐烦"),
    _l("en-slow-03", "en", "slow", 2, "Your reaction time is below cat-level♡", "", "你的反应速度比猫还慢♡", "得意"),
    _l("en-slow-04", "en", "slow", 1, "I'm falling asleep waiting for you♡", "", "等你等到我都困了♡", "打哈欠"),

    _l("en-lose-01", "en", "lose", 1, "Aww, you lost? Zako♡", "", "哎呀，你输了？杂鱼♡", "假装心疼"),
    _l("en-lose-02", "en", "lose", 2, "No excuses~ you lost♡", "", "别找借口～你输了♡", "得意"),
    _l("en-lose-03", "en", "lose", 2, "Don't cry. It's just a game... and you're just zako♡", "", "别哭，只是游戏而已……而你只是杂鱼♡", "温柔补刀"),

    _l("en-idle-01", "en", "idle", 1, "The catgirl isn't here yet? What a zako♡", "", "猫娘还没到？真是个杂鱼♡", "托腮"),
    _l("en-idle-02", "en", "idle", 1, "Waiting for me? How cute, zako♡", "", "在等我？真可爱，杂鱼♡", "凑近"),
    _l("en-idle-03", "en", "idle", 2, "Can't do anything without me? Pathetic~♡", "", "没有我就什么都做不了？真没用～♡", "坏笑"),

    _l("en-clingy-01", "en", "clingy", 1, "Hey, look at me. Or I'll call you zako♡", "", "喂，看着我。不然我就叫你杂鱼哦♡", "凑近"),
    _l("en-clingy-02", "en", "clingy", 1, "Pay attention to me~♡", "", "多关注我一点嘛～♡", "黏人"),

    _l("en-praise-01", "en", "praise", 1, "Hmph, not bad♡ ...for a zako♡", "", "哼，还不错♡ ……对杂鱼来说♡", "傲娇"),
    _l("en-praise-02", "en", "praise", 2, "You did it? Good boy~♡ Still zako♡", "", "做到了？真乖～♡ 但还是杂鱼♡", "先夸后损"),

    # ---------------------------------------------------------------- Korean
    _l("ko-zako-01", "ko", "zako", 1, "에~? 이게 전부야? 자코♡", "", "诶～？就这？杂鱼♡", "假装惊讶"),
    _l("ko-zako-02", "ko", "zako", 1, "자코♡ 자코♡", "", "杂鱼♡ 杂鱼♡", "轻飘飘"),
    _l("ko-zako-03", "ko", "zako", 2, "이것도 못 해? 자코♡", "", "连这个都做不到？杂鱼♡", "歪头"),
    _l("ko-zako-04", "ko", "zako", 2, "힘들어 보여도 결국 자코네♡", "", "看起来挺努力，结果还是杂鱼呢♡", "得意"),
    _l("ko-zako-05", "ko", "zako", 2, "그 정도로 만족해? 자코♡", "", "就这点程度就满足？杂鱼♡", "冷淡"),

    _l("ko-clumsy-01", "ko", "clumsy", 1, "또 실수야?♡", "", "又失误了？♡", "假装关心"),
    _l("ko-clumsy-02", "ko", "clumsy", 2, "방금 그거 실수야, 실력이야?♡", "", "刚才那是失误，还是实力？♡", "歪头"),
    _l("ko-clumsy-03", "ko", "clumsy", 1, "덤벙대긴~♡", "", "真是笨手笨脚～♡", "拖长音"),

    _l("ko-slow-01", "ko", "slow", 1, "느려~♡ 달팽이야?♡", "", "好慢～♡ 是蜗牛吗？♡", "拖长音"),
    _l("ko-slow-02", "ko", "slow", 2, "아직도? 나 세 번이나 기다렸어♡", "", "还没好？我都等三次了♡", "不耐烦"),
    _l("ko-slow-03", "ko", "slow", 2, "반응 속도가 고양이보다 느려♡", "", "反应速度比猫还慢♡", "得意"),

    _l("ko-lose-01", "ko", "lose", 1, "어? 졌어? 자코♡", "", "诶？输了？杂鱼♡", "假装才发现"),
    _l("ko-lose-02", "ko", "lose", 2, "변명하지 마~ 진 거야♡", "", "别找借口～你输了♡", "得意"),
    _l("ko-lose-03", "ko", "lose", 1, "울지 마, 다음에도 질 거니까♡", "", "别哭，反正下次也会输♡", "温柔补刀"),

    _l("ko-idle-01", "ko", "idle", 1, "고양이 아직 안 왔어? 자코♡", "", "猫娘还没来？杂鱼♡", "托腮"),
    _l("ko-idle-02", "ko", "idle", 1, "나 기다리는 거야? 귀여워, 자코♡", "", "在等我？真可爱，杂鱼♡", "凑近"),
    _l("ko-idle-03", "ko", "idle", 2, "나 없으면 아무것도 못 해?♡", "", "没有我就什么都做不了？♡", "坏笑"),

    _l("ko-clingy-01", "ko", "clingy", 1, "나 보고 있어? 안 보면 자코라고 할 거야♡", "", "在看我吗？不看的话我就叫你杂鱼哦♡", "凑近"),
    _l("ko-clingy-02", "ko", "clingy", 1, "관심 좀 줘~♡ 자코♡", "", "多关注我一点嘛～♡ 杂鱼♡", "黏人"),

    _l("ko-praise-01", "ko", "praise", 1, "흥, 나쁘지 않네♡ ...자코치고는♡", "", "哼，还不错♡ ……对杂鱼来说♡", "傲娇"),
    _l("ko-praise-02", "ko", "praise", 1, "잘했어♡ 근데 자코인 건 안 변해♡", "", "做得不错♡ 但杂鱼这点不会变♡", "先夸后损"),
)

# ---------------------------------------------------------------------------
# Normalisation / parsing helpers
# ---------------------------------------------------------------------------

_LANGUAGE_ALIASES = {
    "ja": "ja", "jp": "ja", "jpn": "ja", "japanese": "ja", "日语": "ja", "日語": "ja",
    "zh": "zh", "cn": "zh", "zh-cn": "zh", "zh_cn": "zh", "zh-tw": "zh", "chinese": "zh", "中文": "zh",
    "en": "en", "en-us": "en", "en_us": "en", "english": "en", "英语": "en", "英文": "en",
    "ko": "ko", "kr": "ko", "ko-kr": "ko", "korean": "ko", "韩语": "ko", "韓語": "ko",
    "mix": "mix", "mixed": "mix", "all": "mix", "混合": "mix",
}
_CATEGORY_ALIASES = {
    "zako": "zako", "杂鱼": "zako", "雑魚": "zako", "자코": "zako", "weak": "zako",
    "clumsy": "clumsy", "手笨": "clumsy", "失误": "clumsy", "ドジ": "clumsy", "덤벙": "clumsy",
    "slow": "slow", "慢": "slow", "磨蹭": "slow", "のろま": "slow", "느림": "slow",
    "lose": "lose", "输": "lose", "失败": "lose", "負け": "lose", "패배": "lose",
    "idle": "idle", "waiting": "idle", "还没到": "idle", "等待": "idle", "待機": "idle", "대기": "idle",
    "clingy": "clingy", "黏人": "clingy", "撒娇": "clingy", "構って": "clingy", "애정": "clingy",
    "praise": "praise", "夸奖": "praise", "傲娇": "praise", "ツンデレ": "praise", "칭찬": "praise",
}


def normalize_language(value: Any, default: str = "ja") -> str:
    """Map user/model input to ``ja|zh|en|ko|mix``."""

    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "default", "自动"}:
        return normalize_language(default, "ja") if default not in {"", "auto"} else "ja"
    return _LANGUAGE_ALIASES.get(raw, _LANGUAGE_ALIASES.get(default, "ja"))


def normalize_category(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "any", "random", "自动"}:
        return "auto"
    return _CATEGORY_ALIASES.get(raw, "auto")


def clamp_intensity(value: Any, default: int = 2) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    return max(1, min(3, number))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "是", "開"}:
            return True
        if text in {"0", "false", "no", "off", "否", "關"}:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return default


def normalize_config(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, Mapping) else {}
    return {
        "default_language": normalize_language(data.get("default_language", "ja"), "ja"),
        "default_intensity": clamp_intensity(data.get("default_intensity", 2)),
        "auto_taunt": _as_bool(data.get("auto_taunt", False), False),
        "auto_taunt_interval_minutes": max(
            5, min(180, _safe_int(data.get("auto_taunt_interval_minutes", 20), 20))
        ),
        "auto_taunt_max_per_session": max(
            1, min(50, _safe_int(data.get("auto_taunt_max_per_session", 8), 8))
        ),
        "auto_taunt_category": normalize_category(data.get("auto_taunt_category", "auto")),
        "quiet_hours": str(data.get("quiet_hours", "23:00-08:00") or "")[:32],
        "include_romaji": _as_bool(data.get("include_romaji", True), True),
        "include_translation": _as_bool(data.get("include_translation", True), True),
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Situation -> category heuristics
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lose", (
        "输了", "输掉", "输", "失败", "死了", "挂了", "团灭", "败北", "没打过",
        "lose", "lost", "defeat", "game over", "died",
        "負け", "負けた", "死んだ", "全滅",
        "졌", "패배", "죽었",
    )),
    ("clumsy", (
        "失误", "手滑", "笨", "手残", "点错", "按错", "踩空", "摔", "坑",
        "mistake", "miss", "clumsy", "misclick", "wrong button",
        "ミス", "へた", "ドジ", "滑った",
        "실수", "덤벙", "못해",
    )),
    ("idle", (
        "还没到", "没来", "不在", "等你", "等待", "好久没", "没动静", "人呢",
        "not here", "not yet", "waiting for you", "idle", "absent",
        "まだ来ない", "到着", "いない", "待機",
        "아직", "안 왔", "기다",
    )),
    ("slow", (
        "慢", "磨蹭", "拖延", "等太", "等好久", "反应慢", "卡",
        "slow", "waiting", "took forever", "lag",
        "遅い", "のろ", "待たせ", "まだ",
        "느려", "기다",
    )),
    ("clingy", (
        "理我", "看我", "陪我", "寂寞", "无聊", "别走", "关注",
        "look at me", "pay attention", "lonely", "ignore",
        "構って", "見て", "寂しい", "無視",
        "보고", "관심", "외로",
    )),
    ("praise", (
        "赢了", "成功", "过了", "厉害", "好棒", "第一", "满分", "做到了",
        "win", "won", "success", "great", "cleared", "perfect",
        "勝った", "成功", "すごい", "クリア",
        "이겼", "성공", "잘했",
    )),
    ("zako", (
        "杂鱼", "雑魚", "弱", "菜", "不行", "就这", "zako", "weak", "noob",
        "ざこ", "ざぁこ", "弱い", "へた",
        "자코", "약해", "못해",
    )),
)


def infer_category(situation: Any) -> str:
    """Best-effort category from a free-form situation string."""

    text = str(situation or "").strip().lower()
    if not text:
        return "auto"
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "auto"


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

_QUIET_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def in_quiet_hours(now: datetime, spec: str) -> bool:
    """Return True when ``now`` falls in ``HH:MM-HH:MM`` (overnight supported)."""

    match = _QUIET_RE.match(str(spec or ""))
    if not match:
        return False
    start_h, start_m, end_h, end_m = (int(part) for part in match.groups())
    if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
        return False
    if not (0 <= start_m <= 59 and 0 <= end_m <= 59):
        return False
    current = now.hour * 60 + now.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_MIX_WEIGHTS: dict[str, float] = {"ja": 0.60, "zh": 0.15, "en": 0.15, "ko": 0.10}

_CATEGORY_WEIGHTS: dict[str, float] = {
    "zako": 0.26,
    "idle": 0.18,
    "clumsy": 0.14,
    "slow": 0.12,
    "lose": 0.12,
    "clingy": 0.09,
    "praise": 0.09,
}


class TauntSelector:
    """Choose a line, avoiding immediate repeats.

    The selector is process-local and keeps only line ids in a bounded deque.
    It is safe to call from an asyncio entry and from the timer thread.
    """

    def __init__(self, *, rng: random.Random | None = None, recent_limit: int = 12) -> None:
        self._rng = rng or random.Random()
        self._recent: deque[str] = deque(maxlen=max(1, int(recent_limit)))
        self._lock = threading.Lock()
        self.default_language = "ja"

    def set_default_language(self, language: str) -> None:
        # The default is consulted by callers before select(); kept as a
        # convenience for the facade.
        self.default_language = normalize_language(language, "ja")

    @property
    def recent_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._recent)

    def select(
        self,
        *,
        language: str = "auto",
        category: str = "auto",
        intensity: int | None = None,
        situation: str = "",
        default_language: str = "ja",
    ) -> TauntLine:
        resolved_category = normalize_category(category)
        if resolved_category == "auto":
            resolved_category = infer_category(situation)
        if resolved_category == "auto":
            categories = tuple(_CATEGORY_WEIGHTS)
            weights = tuple(_CATEGORY_WEIGHTS[item] for item in categories)
            resolved_category = self._rng.choices(categories, weights=weights, k=1)[0]
        level = clamp_intensity(intensity, 2 if intensity is None else 2)
        requested = normalize_language(language, default_language)
        lang = self._pick_language(requested)
        pool = self._pool(lang, resolved_category, level)
        if not pool:
            pool = self._pool_any_intensity(lang, resolved_category)
        if not pool:
            pool = self._pool_by_category(resolved_category, level)
        if not pool:
            pool = [line for line in LINES if line.intensity <= level]
        if not pool:
            pool = list(LINES)

        chosen = self._choose(pool)
        with self._lock:
            self._recent.append(chosen.id)
        return chosen

    def select_many(self, count: int, **kwargs: Any) -> list[TauntLine]:
        wanted = max(0, min(20, int(count)))
        return [self.select(**kwargs) for _ in range(wanted)]

    def _pick_language(self, requested: str) -> str:
        if requested == "mix":
            languages = tuple(_MIX_WEIGHTS)
            weights = tuple(_MIX_WEIGHTS[item] for item in languages)
            return self._rng.choices(languages, weights=weights, k=1)[0]
        return requested if requested in LANGUAGES else "ja"

    @staticmethod
    def _pool(lang: str, category: str, max_intensity: int) -> list[TauntLine]:
        return [
            line for line in LINES
            if line.lang == lang and line.category == category and line.intensity <= max_intensity
        ]

    @staticmethod
    def _pool_any_intensity(lang: str, category: str) -> list[TauntLine]:
        return [line for line in LINES if line.lang == lang and line.category == category]

    @staticmethod
    def _pool_by_category(category: str, max_intensity: int) -> list[TauntLine]:
        pool = [
            line for line in LINES
            if line.category == category and line.intensity <= max_intensity
        ]
        # Japanese is the primary language, so prefer it when falling back.
        return sorted(pool, key=lambda line: (line.lang != "ja", line.intensity, line.id))

    def _choose(self, pool: Sequence[TauntLine]) -> TauntLine:
        with self._lock:
            recent = set(self._recent)
        fresh = [line for line in pool if line.id not in recent]
        return self._rng.choice(fresh or list(pool))


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def library_summary(
    *,
    language: str | None = None,
    category: str | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    """Counts and samples for the ``taunt_library`` entry."""

    lang = normalize_language(language, "ja") if language else None
    if lang == "mix":
        lang = None
    cat = normalize_category(category) if category else None
    if cat == "auto":
        cat = None

    selected = [
        line for line in LINES
        if (lang is None or line.lang == lang) and (cat is None or line.category == cat)
    ]
    counts_by_language = {code: 0 for code in LANGUAGES}
    counts_by_category = {code: 0 for code in CATEGORIES}
    for line in LINES:
        counts_by_language[line.lang] = counts_by_language.get(line.lang, 0) + 1
        counts_by_category[line.category] = counts_by_category.get(line.category, 0) + 1

    sample_count = max(1, min(12, int(limit)))
    samples: list[dict[str, Any]] = []
    if selected:
        step = max(1, len(selected) // sample_count)
        for index in range(0, min(len(selected), sample_count * step), step):
            samples.append(selected[index].as_payload())
            if len(samples) >= sample_count:
                break

    return {
        "total": len(LINES),
        "filtered": len(selected),
        "by_language": counts_by_language,
        "by_category": counts_by_category,
        "language": lang or "all",
        "category": cat or "all",
        "samples": samples,
    }


def delivery_prompt(
    line: TauntLine,
    *,
    situation: str = "",
    include_romaji: bool = True,
    include_translation: bool = True,
    auto: bool = False,
) -> str:
    """Build the instruction the dialogue model receives.

    The prompt deliberately carries the exact line, its Chinese meaning and a
    short tone hint.  ``{MASTER_NAME}`` is expanded host-side (the plugin does
    not know which session receives the push).
    """

    master = "{MASTER_NAME}"
    language_name = LANGUAGE_NAMES.get(line.lang, line.lang)
    intro = "现在是自动嘲讽时间" if auto else "现在是猫娘嘲讽时间"
    parts = [
        f"{intro}。请用{language_name}对{master}说下面这句，"
        "保持你平时的猫娘语气，只输出这一句（最多加一个语气词或一声猫叫），"
        "不要解释、不要说教、不要道歉：",
        f"「{line.text}」",
    ]
    detail: list[str] = []
    if include_translation and line.meaning:
        detail.append(f"中文意思：{line.meaning}")
    if line.tone:
        detail.append(f"语气：{line.tone}")
    if detail:
        parts.append("（" + "；".join(detail) + "）")
    if include_romaji and line.romaji:
        parts.append(f"罗马音参考：{line.romaji}")
    if situation.strip():
        parts.append(f"可以自然地带一句当前情境：{situation.strip()[:120]}")
    parts.append("规则：" + TAUNT_RULES)
    return "\n".join(parts)


def pretty_line(line: TauntLine) -> str:
    suffix = f"（{line.meaning}）" if line.meaning else ""
    return f"{line.text}{suffix}"


def as_payload(
    line: TauntLine,
    *,
    include_romaji: bool = True,
    include_translation: bool = True,
) -> dict[str, Any]:
    return line.as_payload(
        include_romaji=include_romaji,
        include_translation=include_translation,
    )


def counts() -> dict[str, Any]:
    """Small, stable summary used by tests and the status entry."""

    by_language = {code: 0 for code in LANGUAGES}
    by_category = {code: 0 for code in CATEGORIES}
    for line in LINES:
        by_language[line.lang] += 1
        by_category[line.category] += 1
    return {
        "total": len(LINES),
        "by_language": by_language,
        "by_category": by_category,
    }


def iter_lines(
    *,
    language: str | None = None,
    category: str | None = None,
) -> Iterable[TauntLine]:
    for line in LINES:
        if language and line.lang != language:
            continue
        if category and line.category != category:
            continue
        yield line