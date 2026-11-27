"""Quest lifecycle handlers: start, objectives, completion, promotion trials, quest log and quest NPCs."""
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.quests.complete import QuestCompleteHandlers
from darkblood.games.handlers.quests.journal import QuestJournalHandlers
from darkblood.games.handlers.quests.npc import QuestNpcHandlers
from darkblood.games.handlers.quests.objectives import QuestObjectiveHandlers
from darkblood.games.handlers.quests.promotion import QuestPromotionHandlers
from darkblood.games.handlers.quests.start import QuestStartHandlers


class QuestHandlers(
    QuestStartHandlers,
    QuestObjectiveHandlers,
    QuestCompleteHandlers,
    QuestPromotionHandlers,
    QuestJournalHandlers,
    QuestNpcHandlers,
    BaseDomainService,
):
    """Quest start/complete, objectives, promotion trials, quest log and quest NPC services."""


__all__ = ["QuestHandlers"]
