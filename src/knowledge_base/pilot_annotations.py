"""Conservative, review-required annotations for the first knowledge-card pilot."""

from __future__ import annotations


def ability(
    summary: str,
    *,
    damage: tuple[str, ...] = ("none",),
    targeting: tuple[str, ...] = ("other",),
    control: tuple[str, ...] = ("none",),
    mobility: tuple[str, ...] = ("none",),
    defense: tuple[str, ...] = ("none",),
    conditions: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "summary": summary,
        "damage_types": list(damage),
        "targeting_types": list(targeting),
        "control_types": list(control),
        "mobility_types": list(mobility),
        "defense_types": list(defense),
        "conditions": list(conditions),
        "limitations": list(limitations),
    }


PILOT_ANNOTATIONS: dict[str, dict[str, object]] = {
    "Poppy": {
        "form_id": "base",
        "abilities": {
            "passive": ability(
                "强化普攻会投出圆盾；拾取落地圆盾后获得短暂护盾。",
                damage=("physical",),
                targeting=("passive", "targeted_enemy"),
                defense=("shield",),
                conditions=("需要拾取落地圆盾才能获得护盾",),
            ),
            "q": ability(
                "锤击目标区域造成物理伤害和减速，区域随后再次爆炸。",
                damage=("physical",),
                targeting=("ground_area",),
                control=("slow",),
                conditions=("第二段伤害存在延迟",),
            ),
            "w": ability(
                "被动提供抗性；主动加速并中断附近符合条件的突进，随后施加减速和缚地。",
                targeting=("self", "self_area"),
                control=("slow", "other"),
                mobility=("movement_speed",),
                defense=("resistances",),
                limitations=("只中断符合该技能判定的突进", "缚地在当前枚举中记为 other"),
            ),
            "e": ability(
                "冲向目标并将其击退；目标撞墙时受到晕眩。",
                damage=("physical",),
                targeting=("targeted_enemy",),
                control=("knockback", "stun"),
                mobility=("charge",),
                conditions=("需要将目标推到墙体才能造成晕眩",),
            ),
            "r": ability(
                "引导锤击，将命中的敌人击飞并击退到远方；快速施放可作近距离击退。",
                damage=("physical",),
                targeting=("direction", "line"),
                control=("knockup", "knockback"),
                conditions=("引导时长影响击退效果",),
            ),
        },
        "attributes": [
            ("disengage", "high", "W 和 R 能分别限制突进与大范围驱离敌人。", ("w", "r")),
            ("peel", "high", "W、E、R 提供多种保护后排的位移限制。", ("w", "e", "r")),
            ("engage", "conditional", "E 撞墙和快速 R 可发起控制，但依赖位置与命中。", ("e", "r")),
            ("frontline", "medium", "被动护盾与 W 抗性支持前排承伤，但强度受条件影响。", ("passive", "w")),
            ("pick", "conditional", "E 在墙体附近能将单个目标转化为稳定控制机会。", ("e",)),
        ],
        "limitations": [
            ("wall_dependency", "E 的完整控制依赖目标撞墙。", ("e",)),
            ("dash_filter", "W 不能阻止所有移动技能，需按具体突进判定审核。", ("w",)),
        ],
    },
    "Camille": {
        "form_id": "base",
        "abilities": {
            "passive": ability(
                "攻击敌方英雄时，根据对方主要伤害类型获得对应的物理或魔法护盾。",
                targeting=("passive", "targeted_enemy"),
                defense=("shield",),
                conditions=("护盾类型由目标伤害类型决定",),
                limitations=("一次只针对一种伤害类型",),
            ),
            "q": ability(
                "强化下一次普攻并短暂加速；在正确间隔后使用第二段会显著增强伤害。",
                damage=("physical",),
                targeting=("targeted_enemy",),
                mobility=("movement_speed",),
                conditions=("第二段强化依赖施放间隔",),
            ),
            "w": ability(
                "延迟横扫锥形区域；外沿命中会减速、造成额外伤害并治疗自身。",
                damage=("physical",),
                targeting=("cone",),
                control=("slow",),
                defense=("heal",),
                conditions=("减速、额外伤害和治疗依赖外沿命中",),
            ),
            "e": ability(
                "先钩向墙体，再向指定方向跃出；命中敌方英雄时造成击飞。",
                damage=("physical",),
                targeting=("direction", "line"),
                control=("knockup",),
                mobility=("dash",),
                conditions=("第一段需要可连接的墙体", "控制依赖第二段命中英雄"),
            ),
            "r": ability(
                "冲向目标英雄并生成限制其离开的区域，对该目标的普攻附加魔法伤害。",
                damage=("magic",),
                targeting=("targeted_enemy", "ground_area"),
                control=("other",),
                mobility=("dash",),
                conditions=("只能以敌方英雄为目标",),
                limitations=("区域限制在当前控制枚举中记为 other",),
            ),
        },
        "attributes": [
            ("engage", "high", "E 提供远距离进场，R 能锁定单个关键目标。", ("e", "r")),
            ("pick", "high", "E 与 R 的组合适合隔离并限制单个目标。", ("e", "r")),
            ("mobility", "high", "E 的墙体位移和 Q 的加速提供高机动性。", ("q", "e")),
            ("burst", "conditional", "Q 第二段、W 外沿与进场连招可形成爆发，但均有条件。", ("q", "w", "e")),
            ("split_push", "medium", "强化普攻和机动能力支持边线施压；具体强度仍需战术审核。", ("q", "e")),
        ],
        "limitations": [
            ("terrain_dependency", "E 的主要进场距离依赖墙体位置。", ("e",)),
            ("damage_type_shield", "被动护盾只吸收一种伤害类型。", ("passive",)),
        ],
    },
    "Jayce": {
        "form_id": "dual_form_combined",
        "abilities": {
            "passive": ability(
                "切换武器形态后短暂获得移动速度。",
                targeting=("passive", "self"),
                mobility=("movement_speed",),
                conditions=("需要切换武器形态",),
            ),
            "q": ability(
                "锤形态跳向目标并减速；炮形态发射可在命中或最远距离爆炸的远程电球。",
                damage=("physical",),
                targeting=("targeted_enemy", "direction", "line"),
                control=("slow",),
                mobility=("leap",),
                conditions=("效果取决于当前形态",),
            ),
            "w": ability(
                "锤形态创造近身伤害区域并通过攻击回复法力；炮形态强化若干次普攻的攻速。",
                damage=("magic",),
                targeting=("self", "self_area"),
                conditions=("效果取决于当前形态",),
                limitations=("炮形态主要强化普攻，不能只按技能伤害理解",),
            ),
            "e": ability(
                "锤形态击退目标；炮形态生成友军加速门，并强化穿过门的 Q 弹道。",
                damage=("magic",),
                targeting=("targeted_enemy", "line"),
                control=("knockback",),
                mobility=("movement_speed",),
                conditions=("效果取决于当前形态", "Q 穿过加速门后才获得强化"),
            ),
            "r": ability(
                "在锤与炮形态之间切换，改变攻击距离、基础技能和切换后的首次攻击效果。",
                damage=("magic",),
                targeting=("self",),
                defense=("resistances",),
                conditions=("切换方向决定获得的效果",),
            ),
        },
        "attributes": [
            ("poke", "high", "炮形态 Q 与 E 的组合提供远距离消耗。", ("q", "e")),
            ("siege", "high", "远程消耗、加速门和强化普攻支持推进与拉扯。", ("q", "w", "e")),
            ("burst", "conditional", "双形态技能轮转可集中输出，但依赖形态和连招顺序。", ("q", "w", "e", "r")),
            ("disengage", "medium", "锤形态 E 击退和炮形态 E 加速可帮助拉开。", ("e",)),
            ("mobility", "medium", "形态切换加速、锤 Q 跳跃和加速门共同提供机动性。", ("passive", "q", "e")),
        ],
        "limitations": [
            ("form_dependency", "同一技能槽在两种形态下含义不同，必须结合当前形态解释。", ("q", "w", "e", "r")),
            ("gate_combo", "远程 Q 的最大威胁依赖穿过加速门。", ("q", "e")),
        ],
    },
    "Aphelios": {
        "form_id": "weapon_system",
        "abilities": {
            "passive": ability(
                "拥有五件不同武器，同时持有主手和副手；攻击与技能消耗弹药并推动武器队列。",
                damage=("unknown",),
                targeting=("passive", "self"),
                conditions=("效果由当前主副手武器、弹药和队列决定",),
            ),
            "q": ability(
                "Q 随主手武器变为五种不同技能，可提供远程标记、移动攻击、禁锢、范围攻击或驻灵。",
                damage=("physical",),
                targeting=("line", "cone", "ground_area", "self_area", "other"),
                control=("root",),
                conditions=("具体技能由当前主手武器决定", "部分效果会调用副手武器"),
                limitations=("单条组合记录不能替代五种武器技能的后续拆分审核",),
            ),
            "w": ability(
                "交换主手和副手武器，同时改变普攻方式与 Q 技能。",
                targeting=("self",),
                conditions=("需要同时持有两件武器",),
            ),
            "e": ability(
                "该槽位没有主动技能，仅显示下一件将进入队列的武器。",
                targeting=("passive", "self"),
                limitations=("不得将 E 槽描述为可主动施放技能",),
            ),
            "r": ability(
                "发射月光并在命中敌方英雄后爆炸，随后施加当前主手武器的独特效果。",
                damage=("physical",),
                targeting=("direction", "line", "ground_area"),
                conditions=("附加效果由当前主手武器决定",),
            ),
        },
        "attributes": [
            ("sustained_damage", "high", "武器普攻、主副手联动和 Q 技能构成持续输出核心。", ("passive", "q", "w")),
            ("waveclear", "conditional", "范围清线能力取决于当前武器，不能视为恒定能力。", ("passive", "q")),
            ("poke", "conditional", "远程消耗能力取决于当前主手武器。", ("passive", "q")),
            ("pick", "conditional", "特定武器提供减速后的禁锢，但受武器状态约束。", ("q",)),
            ("objective_damage", "conditional", "武器组合可强化持续目标输出，具体强度需结合当前状态。", ("passive", "q", "w")),
        ],
        "limitations": [
            ("weapon_state", "阵容上下文若不提供当前武器和队列，只能描述条件化能力。", ("passive", "q", "w", "e", "r")),
            ("combined_q", "Data Dragon 将五种 Q 合并描述，正式审核应决定是否拆为子事实。", ("q",)),
        ],
    },
    "Lulu": {
        "form_id": "base",
        "abilities": {
            "passive": ability(
                "皮克斯跟随的英雄攻击时会发射可被其他单位阻挡的魔法飞弹。",
                damage=("magic",),
                targeting=("passive", "direction"),
                limitations=("飞弹可能被其他单位阻挡", "皮克斯可能跟随璐璐或另一名友军"),
            ),
            "q": ability(
                "璐璐和皮克斯分别发射穿刺飞弹，对沿途敌人造成魔法伤害和强减速。",
                damage=("magic",),
                targeting=("direction", "line"),
                control=("slow",),
                conditions=("两枚飞弹的起点取决于璐璐与皮克斯位置",),
            ),
            "w": ability(
                "对友军提供攻速与移速；对敌方英雄施加变形，使其暂时无法攻击或施法。",
                targeting=("targeted_ally", "targeted_enemy"),
                control=("polymorph", "silence", "disarm"),
                mobility=("movement_speed",),
                conditions=("友军和敌军目标获得不同效果",),
            ),
            "e": ability(
                "对友军提供护盾并转移皮克斯；对敌人造成魔法伤害并提供其视野。",
                damage=("magic",),
                targeting=("targeted_ally", "targeted_enemy"),
                defense=("shield",),
                conditions=("友军和敌军目标获得不同效果",),
            ),
            "r": ability(
                "使友军变大、击飞附近敌人、增加目标生命值，并提供持续减速光环。",
                targeting=("targeted_ally", "self_area"),
                control=("knockup", "slow"),
                conditions=("范围控制以目标友军为中心",),
                limitations=("增加生命值不等同于普通治疗，当前防御枚举不强行归类",),
            ),
        },
        "attributes": [
            ("peel", "high", "W 变形、E 护盾和 R 击飞能够连续保护核心。", ("w", "e", "r")),
            ("disengage", "high", "Q 减速、W 变形和 R 范围击飞能阻断敌方进场。", ("q", "w", "r")),
            ("engage", "conditional", "R 可配合已进场友军制造击飞，但依赖友军位置。", ("r",)),
            ("poke", "medium", "Q 和敌军 E 提供远程消耗，但需要管理皮克斯位置。", ("q", "e")),
            ("siege", "medium", "加速、护盾和远程减速能辅助核心推进与拉扯。", ("q", "w", "e")),
        ],
        "limitations": [
            ("dual_target_modes", "W 和 E 对友军与敌军效果不同，不能在一次施放中同时获得。", ("w", "e")),
            ("pix_position", "Q 与被动效果受皮克斯当前跟随目标和位置影响。", ("passive", "q", "e")),
        ],
    },
}


PILOT_HERO_IDS = tuple(PILOT_ANNOTATIONS)
