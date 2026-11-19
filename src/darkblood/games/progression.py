"""Character level and ability point accounting."""
from darkblood.games.game_data.client_dict import char_level_stat, level_up_ap, skill_learn_cost


MAX_LEVEL = 60
MAX_AP = 0x7fffffff


def ap_at_level(level):
    return level_up_ap().get(level, 3 if level < 20 else 4)


def total_ap(char):
    if 'total_ap' in char:
        return char['total_ap']
    spent = sum(skill_learn_cost(int(index), 0, level)[0]
                for index, level in char.get('skills', {}).items())
    earned = sum(ap_at_level(level) for level in range(2, char.get('level', 1) + 1))
    return min(MAX_AP, max(earned, char.get('sp', 0) + spent))


def add_ap(char, amount):
    total = total_ap(char)
    remaining = char.get('sp', 0) + amount
    new_total = total + amount
    if not (0 <= remaining <= new_total <= MAX_AP):
        raise ValueError('AP balance out of range')
    char.update(sp=remaining, total_ap=new_total)


def advance_level(char, level, exp):
    total = total_ap(char)
    gain = sum(ap_at_level(n) for n in range(char.get('level', 1) + 1, level + 1))
    stats = char_level_stat(int(char.get('char_class', 0)), level)
    char.update(level=level, exp=exp, max_hp=stats['hp'], max_mp=stats['mp'],
                sp=min(MAX_AP, char.get('sp', 0) + gain), total_ap=min(MAX_AP, total + gain))
